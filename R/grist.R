## grist.R -- grist catalog render: store -> one row per 2D field.
##
## Rscript grist.R STORE OUT_DIR [TARGET] [BASE]
##   OUT_DIR/grist/catalog.parquet   the mdim catalog of the hypertidy/grist
##                                   catalog contract (grist README, "Catalog
##                                   contract"), one row per (array, date,
##                                   level), columns:
##     date    date32   day of the time coordinate
##     dsn     string   GDAL open string of the published mdim.vrt
##     array   string   array name in the VRT
##     index   string   coordinate VALUES of every non-spatial dimension,
##                      "Time=1993-01-01,st_ocean=2.5" (never positions)
##     source  string   the granule(s) behind the field, from placements,
##                      remapped to TARGET (";" between several)
## TARGET: remap target for `source` ("" = verbatim sources); run.sh passes
##   GRIST_TARGET, default VRT_TARGET (the URIs the mdim.vrt reads).
## BASE: URL of the published dataset prefix; dsn is /vsicurl/BASE/mdim.vrt.
##   Without it dsn is the local OUT_DIR/mdim.vrt (re-render with BASE set
##   before publish, as for the stac step).
## Environment:
##   GRIST_ARRAYS   arrays to list, space or comma separated (default every
##                  referenced array)
##   GRIST_LEVELS   values of the vertical dimension to list, comma separated,
##                  or "all" (default the first value of that dimension)
##
## Everything comes from the plan layer of the store (placements and the
## coordinate arrays); no granule is opened. Time values are decoded from CF
## units (standard calendars); a time axis with two steps on one day is
## refused, since the contract matches time at day resolution. Positions no
## placement covers (gaps in a regular axis) get no row. A non-spatial
## dimension that is neither time nor vertical must have length 1.
if (sys.nframe() == 0L) {
  args <- commandArgs(trailingOnly = TRUE)
  if (length(args) < 2L) stop("usage: grist.R STORE OUT_DIR [TARGET] [BASE]")
  here <- dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1]))
  source(file.path(here, "mdimrefs.R")); source(file.path(here, "mdimrefs_pipeline.R"))
  source(file.path(here, "stac.R"))  # .stac_plan, .dim_role, .coord_vals, .cf_time
}

GRIST_CONTRACT <- "grist-catalog/mdim"

## a coordinate value as text: 7 significant digits for float32, 15 for
## wider types (grist matches numbers within a relative 1e-6)
.grist_num <- function(v, dtype) {
  d <- if (!is.null(dtype) && grepl("f4$", dtype)) 7L else 15L
  x <- sub("\\.?0+(e|$)", "\\1", formatC(v, digits = d, format = "g", flag = "#"))
  sub("\\.$", "", x)
}

.split_env <- function(x) {
  x <- trimws(unlist(strsplit(x, "[ ,]+")))
  x[nzchar(x)]
}

mr_grist_catalog <- function(con, out, target = NULL, base = NULL, plan_file = NULL,
                             arrays_sel = NULL, levels = NULL) {
  plan <- .stac_plan(plan_file)
  if (!length(plan$dim_type)) plan$dim_type <- unlist(lapply(mr_dimensions(con), `[[`, "type"))
  arrays <- mr_array_list(con); names(arrays) <- vapply(arrays, `[[`, "", "array")
  data <- Filter(function(a) a$storage == "referenced", arrays)
  ## overview levels (attribute overview_of) only when asked for by name
  if (!length(arrays_sel)) data <- Filter(function(a) is.null(a$attrs$overview_of), data)
  if (length(arrays_sel)) {
    miss <- setdiff(arrays_sel, names(data))
    if (length(miss)) stop("grist: no referenced array ", paste(miss, collapse = ", "))
    data <- data[arrays_sel]
  }
  if (!length(data)) stop("grist: no referenced arrays in the store")
  dsn <- if (is.null(base)) normalizePath(file.path(out, "mdim.vrt"), mustWork = FALSE)
         else .gdal_url(paste0(sub("/$", "", base), "/mdim.vrt"))

  rows <- list()
  for (a in data) {
    ## each dimension: role, values as text, and the positions selected
    sel <- lapply(stats::setNames(a$dims, a$dims), function(d) {
      co <- arrays[[d]]; at <- co$attrs %||% list()
      if (is.null(at$units) && !is.null(plan$units[[d]])) at$units <- plan$units[[d]]
      v <- .coord_vals(co)
      role <- .dim_role(d, at, plan$dim_type[d][[1]])
      if (role %in% c("x", "y")) return(list(role = role))
      if (is.null(v)) stop(sprintf("grist: dimension '%s' of '%s' has no indexing variable", d, a$array))
      if (role == "t") {
        tt <- .cf_time(v, at$units, at$calendar)
        if (is.null(tt)) stop(sprintf("grist: cannot decode time '%s' (units '%s')", d, at$units %||% ""))
        txt <- format(as.Date(tt, tz = "UTC"))
        if (anyDuplicated(txt))
          stop(sprintf("grist: '%s' has more than one step on a day (%s); the catalog matches time at day resolution",
                       d, txt[anyDuplicated(txt)]))
        return(list(role = role, pos = seq_along(v), text = txt, date = as.Date(tt, tz = "UTC")))
      }
      txt <- .grist_num(v, co$dtype)
      if (role == "z") {
        if (identical(levels, "all")) pos <- seq_along(v)
        else if (!length(levels)) pos <- 1L
        else {
          want <- as.numeric(levels)
          pos <- vapply(want, function(w) {
            k <- which(abs(v - w) <= 1e-6 * max(abs(w), 1e-12))
            if (length(k) != 1L) stop(sprintf("grist: level %s matches %d values of '%s'", w, length(k), d))
            k
          }, 1L)
        }
        return(list(role = role, pos = pos, text = txt))
      }
      if (length(v) != 1L)
        stop(sprintf("grist: dimension '%s' of '%s' (length %d) is neither time nor vertical; the catalog needs one value per row",
                     d, a$array, length(v)))
      list(role = role, pos = 1L, text = txt)
    })
    roles <- vapply(sel, `[[`, "", "role")
    if (sum(roles %in% c("x", "y")) != 2L || !all(c("x", "y") %in% roles))
      stop(sprintf("grist: '%s' needs one x and one y dimension (roles: %s)", a$array,
                   paste(a$dims, roles, sep = "=", collapse = ", ")))
    nd <- a$dims[!roles %in% c("x", "y")]
    if (!"t" %in% roles[nd]) stop(sprintf("grist: '%s' has no time dimension", a$array))
    ## every combination of the selected positions, time varying fastest
    ## after the outer dimensions so rows sort by date within a level
    g <- expand.grid(lapply(sel[nd], `[[`, "pos"), KEEP.OUT.ATTRS = FALSE)
    dt <- nd[roles[nd] == "t"][1]
    g <- g[do.call(order, c(g[setdiff(nd, dt)], g[dt])), , drop = FALSE]
    index <- do.call(paste, c(lapply(nd, function(d) paste0(d, "=", sel[[d]]$text[g[[d]]])), sep = ","))

    ## the source behind each row: the placements whose slab covers its
    ## position on every non-spatial dimension
    P <- dbGetQuery(con, "SELECT s.source, p.count, p.dest FROM placements p
                          JOIN sources s USING (source_id) WHERE p.array = ?",
                    params = list(a$array))
    P$path <- mr_remap(con, P$source, target)
    k <- match(nd, a$dims)
    de <- do.call(rbind, lapply(P$dest, function(x) .fj(x)[k]))
    cn <- do.call(rbind, lapply(P$count, function(x) .fj(x)[k]))
    pos0 <- as.matrix(g) - 1L
    src <- vapply(seq_len(nrow(pos0)), function(i) {
      hit <- rowSums(sweep(de, 2, pos0[i, ], "<=") & sweep(de + cn, 2, pos0[i, ], ">")) == length(k)
      paste(unique(P$path[hit]), collapse = ";")
    }, "")
    ## a position no source covers (a gap the mosaic filled on a regular
    ## axis) is fill only: no field, no row
    if (any(gap <- !nzchar(src)))
      message(sprintf("  grist: %d rows of '%s' dropped, no source covers them (first: %s)",
                      sum(gap), a$array, index[gap][1]))
    rows[[a$array]] <- data.frame(date = sel[[dt]]$date[g[[dt]]], dsn = dsn, array = a$array,
                                  index = index, source = src,
                                  stringsAsFactors = FALSE)[!gap, , drop = FALSE]
  }
  do.call(rbind, unname(rows))
}

mr_write_grist <- function(con, out, ..., verbose = TRUE) {
  cat_df <- mr_grist_catalog(con, out, ...)
  dir <- file.path(out, "grist"); dir.create(dir, recursive = TRUE, showWarnings = FALSE)
  meta <- dbReadTable(con, "meta"); meta <- meta[!meta$key %in% MR_META_JSON, , drop = FALSE]
  tb <- arrow::Table$create(cat_df, schema = arrow::schema(
    date = arrow::date32(), dsn = arrow::utf8(), array = arrow::utf8(),
    index = arrow::utf8(), source = arrow::utf8()))
  tb$metadata <- c(list(contract = GRIST_CONTRACT),
                   stats::setNames(as.list(meta$value), paste0("rv:", meta$key)))
  f <- file.path(dir, "catalog.parquet")
  arrow::write_parquet(tb, f, compression = .pq_codec())
  if (verbose) message(sprintf("  grist: %d rows (%s; %s to %s), dsn %s", nrow(cat_df),
                               paste(unique(cat_df$array), collapse = ", "),
                               min(cat_df$date), max(cat_df$date), cat_df$dsn[1]))
  invisible(f)
}

if (sys.nframe() == 0L) {
  db <- args[1]; out <- args[2]
  tg <- function(x) if (is.na(x) || !nzchar(x)) NULL else x
  target <- tg(args[3]); base <- tg(args[4])
  con <- mr_open(db)
  pf <- dbGetQuery(con, "SELECT value FROM meta WHERE key = 'plan'")$value
  pf <- if (length(pf) && !is.na(pf)) file.path(dirname(db), pf)
  lv <- .split_env(Sys.getenv("GRIST_LEVELS"))
  if (identical(tolower(lv), "all")) lv <- "all"
  t0 <- Sys.time()
  mr_write_grist(con, out, target = target, base = base, plan_file = pf,
                 arrays_sel = .split_env(Sys.getenv("GRIST_ARRAYS")), levels = lv)
  DBI::dbDisconnect(con)
  message(sprintf("grist catalog: %.1f s", as.numeric(Sys.time() - t0, units = "secs")))
}
