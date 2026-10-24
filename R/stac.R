## stac.R -- STAC render: store -> collection + one item per source.
##
## Rscript stac.R STORE OUT_DIR [TARGET] [BASE]
##   OUT_DIR/stac/collection.json  datacube collection, assets for every form
##                                 found in OUT_DIR (flat, mdim.vrt, kerchunk,
##                                 icechunk) and for the store and plan
##   OUT_DIR/stac/items/<id>.json  one item per source granule (static catalog)
##   OUT_DIR/stac/items.ndjson     the same items, one per line (for bulk
##                                 loading, stac-geoparquet, DuckDB, rstac)
## TARGET: remap target for item hrefs ("" = verbatim sources).
## BASE: URL of the published dataset prefix (the directory that holds
##   mdim.vrt, kerchunk/, icechunk/, store.sqlite). STAC_ITEM_FILES=0 in the
##   environment skips items/ (for a long series, where items.ndjson and its
##   stac-geoparquet translation serve better). With BASE the hrefs of
##   the collection assets are absolute and each asset carries a GDAL open
##   string (rv:gdal); without it they are relative to the published layout
##   (OUT_DIR synced to the prefix, store.sqlite and plan.vrt beside it).
##
## The plan VRT beside the store (meta key `plan`) supplies what the store
## does not keep: dimension types, the SRS and coordinate units.
if (sys.nframe() == 0L) {
  args <- commandArgs(trailingOnly = TRUE)
  if (length(args) < 2L) stop("usage: stac.R STORE OUT_DIR [TARGET] [BASE]")
  here <- dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1]))
  source(file.path(here, "mdimrefs.R")); source(file.path(here, "mdimrefs_pipeline.R"))
}

STAC_VERSION <- "1.1.0"
STAC_EXT <- c(
  datacube   = "https://stac-extensions.github.io/datacube/v2.2.0/schema.json",
  file       = "https://stac-extensions.github.io/file/v2.1.0/schema.json",
  projection = "https://stac-extensions.github.io/projection/v2.0.0/schema.json",
  xarray     = "https://stac-extensions.github.io/xarray-assets/v1.0.0/schema.json")

## ---- the plan: dimension types, SRS, coordinate units ----------------------------
.stac_plan <- function(file) {
  out <- list(dim_type = character(0), srs = NA_character_, units = list())
  if (is.null(file) || !file.exists(file)) return(out)
  doc <- xml2::read_xml(file); g <- xml2::xml_find_first(doc, ".//Group")
  dm <- xml2::xml_find_all(g, "./Dimension")
  out$dim_type <- stats::setNames(xml2::xml_attr(dm, "type"), xml2::xml_attr(dm, "name"))
  srs <- xml2::xml_find_first(g, ".//Array/SRS")
  if (!is.na(srs)) out$srs <- xml2::xml_text(srs)
  for (a in xml2::xml_find_all(g, "./Array")) {
    u <- xml2::xml_find_first(a, "./Unit")
    if (!is.na(u)) out$units[[xml2::xml_attr(a, "name")]] <- xml2::xml_text(u)
  }
  out
}

## EPSG code of a WKT2 or WKT1 string: the outermost authority, which is the
## last ID[] (WKT2) or AUTHORITY[] (WKT1) in the text
.epsg <- function(wkt) {
  if (is.na(wkt)) return(NA_character_)
  m <- regmatches(wkt, gregexpr('(ID|AUTHORITY)\\["EPSG",\\s*"?([0-9]+)"?\\]', wkt))[[1]]
  if (!length(m)) return(NA_character_)
  paste0("EPSG:", sub('.*"EPSG",\\s*"?([0-9]+).*', "\\1", m[length(m)]))
}

## ---- dimensions --------------------------------------------------------------------
.coord_vals <- function(a) {
  if (is.null(a)) return(NULL)
  if (!is.null(a$values)) return(as.numeric(a$values))
  if (!is.null(a$affine)) return(a$affine$start + a$affine$step * (seq_len(a$shape) - 1))
  NULL
}

## CF time: "<unit> since <origin>", standard calendars only
.cf_time <- function(v, units, calendar = NULL) {
  if (is.null(units) || !grepl("since", units)) return(NULL)
  if (!is.null(calendar) && !tolower(calendar) %in% c("standard", "gregorian", "proleptic_gregorian")) {
    warning("time calendar '", calendar, "' is not handled; no temporal extent written")
    return(NULL)
  }
  u <- tolower(trimws(sub("since.*$", "", units)))
  mult <- c(seconds = 1, second = 1, s = 1, minutes = 60, minute = 60, hours = 3600,
            hour = 3600, h = 3600, days = 86400, day = 86400, d = 86400)[u]
  if (is.na(mult)) return(NULL)
  origin <- trimws(sub("^.*since", "", units))
  o <- as.POSIXct(origin, tz = "UTC",
                  tryFormats = c("%Y-%m-%d %H:%M:%OS", "%Y-%m-%dT%H:%M:%OS", "%Y-%m-%d %H:%M",
                                 "%Y-%m-%d"))
  o + v * mult
}
.iso <- function(t) format(t, "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")

## the regular spacing of v (12 significant digits, as coordinates written in
## float32 or from text rarely carry more), or NULL
.step <- function(v) {
  if (length(v) < 2L) return(NULL)
  d <- diff(v)
  if (all(abs(d - d[1]) <= 1e-6 * max(abs(d[1]), .Machine$double.eps))) signif(mean(d), 12) else NULL
}
.iso_duration <- function(secs) {
  if (is.null(secs)) return(NULL)
  if (secs %% 86400 == 0) sprintf("P%dD", as.integer(secs / 86400))
  else if (secs %% 3600 == 0) sprintf("PT%dH", as.integer(secs / 3600))
  else sprintf("PT%gS", secs)
}

## the role of each dimension: t, x, y, z or other, from the plan's
## dimension type, then CF units and axis, then common names
.dim_role <- function(d, attrs, plan_type) {
  pt <- toupper(plan_type %||% "")
  u <- tolower(attrs$units %||% ""); ax <- toupper(attrs$axis %||% "")
  if (pt == "TEMPORAL" || ax == "T" || grepl("since", u)) return("t")
  if (pt == "HORIZONTAL_X" || ax == "X" || grepl("^degrees?_?e", u) ||
      tolower(d) %in% c("x", "lon", "longitude", "xt_ocean", "xu_ocean")) return("x")
  if (pt == "HORIZONTAL_Y" || ax == "Y" || grepl("^degrees?_?n", u) ||
      tolower(d) %in% c("y", "lat", "latitude", "yt_ocean", "yu_ocean")) return("y")
  if (pt == "VERTICAL" || ax == "Z" || !is.null(attrs$positive) ||
      tolower(d) %in% c("z", "depth", "lev", "level", "st_ocean", "sw_ocean")) return("z")
  "other"
}

## edges of a cell-centred coordinate over index range i (1-based)
.edges <- function(v, i) {
  x <- v[i]; s <- .step(v) %||% (if (length(v) > 1L) stats::median(abs(diff(v))) else 0)
  c(min(x) - abs(s) / 2, max(x) + abs(s) / 2)
}

## longitude edges to a STAC bbox west/east: [-180, 180], west > east when
## the range crosses the antimeridian
.lon_we <- function(e) {
  if (e[2] - e[1] >= 360 - 1e-6) return(c(-180, 180))
  w <- ((e[1] + 180) %% 360) - 180; ea <- ((e[2] + 180) %% 360) - 180
  if (ea == -180 && e[2] > e[1]) ea <- 180
  c(w, ea)
}

.bbox_geom <- function(b) {
  ring <- function(w, s, e, n) list(list(c(w, s), c(e, s), c(e, n), c(w, n), c(w, s)))
  if (b[1] <= b[3]) list(type = "Polygon", coordinates = ring(b[1], b[2], b[3], b[4]))
  else list(type = "MultiPolygon", coordinates = list(ring(b[1], b[2], 180, b[4]),
                                                      ring(-180, b[2], b[3], b[4])))
}

## ---- assets ------------------------------------------------------------------------
.media_type <- function(path) {
  ext <- tolower(sub(".*[.]", "", sub("[?#].*$", "", path)))
  switch(ext, nc = , nc4 = "application/netcdf", h5 = , hdf5 = , he5 = "application/x-hdf5",
         tif = , tiff = "image/tiff; application=geotiff", grib = , grb = , grib2 = "application/x-grib",
         "application/octet-stream")
}

## GDAL open string for a published URL
.gdal_url <- function(u) if (grepl("^https?://", u)) paste0("/vsicurl/", u) else u

## Icechunk virtual chunk containers for a set of reference URLs, as
## py/render_icechunk.py registers them: scheme://host/ for http(s) and s3,
## the directory for local files. A reader authorizes each one.
.containers <- function(paths) {
  p <- sub("^/vsicurl/", "", paths)
  p <- ifelse(startsWith(p, "/"), paste0("file://", p), p)
  web <- grepl("^(https?|s3)://", p)
  out <- ifelse(web, sub("^([a-z0-9]+://[^/]+/).*$", "\\1", p), paste0(dirname(p), "/"))
  out <- sub("^file:/([^/])", "file:///\\1", out)
  sort(unique(out))
}

.form_assets <- function(out, base, containers = NULL) {
  rel <- function(p) if (is.null(base)) paste0("../", p) else paste0(sub("/$", "", base), "/", p)
  gd <- function(s) if (is.null(base)) NULL else s
  a <- list()
  if (file.exists(file.path(out, "mdim.vrt")))
    a$mdim_vrt <- list(href = rel("mdim.vrt"), type = "application/xml",
      title = "GDAL multidimensional VRT", roles = list("data", "virtual"),
      description = "Open with GDAL's multidimensional API (gdal mdim, gdalraster, osgeo.gdal); reads go to the source files.",
      `rv:form` = "mdim-vrt", `rv:gdal` = gd(.gdal_url(rel("mdim.vrt"))))
  if (dir.exists(file.path(out, "kerchunk")))
    a$kerchunk <- list(href = rel("kerchunk/"), type = "application/vnd+zarr",
      title = "kerchunk Parquet references (Zarr v2)", roles = list("data", "references", "virtual"),
      description = "fsspec reference filesystem in Parquet layout; GDAL reads it as ZARR:\"/vsikerchunk_parquet_ref/{...}\".",
      `xarray:open_kwargs` = list(engine = "kerchunk"),
      `rv:form` = "kerchunk-parquet",
      `rv:gdal` = gd(sprintf('ZARR:"/vsikerchunk_parquet_ref/{%s}"', .gdal_url(rel("kerchunk")))))
  if (dir.exists(file.path(out, "icechunk")))
    a$icechunk <- list(href = rel("icechunk/"), type = "application/vnd.zarr+icechunk",
      title = "Icechunk repository (virtual references)", roles = list("data", "references", "virtual"),
      description = "Zarr v3 under Icechunk; branch main. Virtual chunk containers must be authorized by the reader.",
      `xarray:open_kwargs` = list(engine = "zarr", consolidated = FALSE),
      `rv:form` = "icechunk",
      `rv:virtual_chunk_containers` = if (length(containers)) I(containers))
  if (file.exists(file.path(out, "flat", "arrays.json")))
    a$refs <- list(href = rel("flat/arrays.json"), type = "application/json",
      title = "Flat refs store (arrays.json + refs_<array>.parquet)", roles = list("metadata", "references"),
      description = "Chunk references as Parquet, one table per array, read by wxy-refs, DuckDB and arrow.",
      `rv:form` = "flat-refs")
  a$store <- list(href = rel("store.sqlite"), type = "application/vnd.sqlite3",
    title = "mdim-refs/0.2 store", roles = list("metadata", "references"),
    `rv:form` = "mdim-refs")
  a$plan <- list(href = rel("plan.vrt"), type = "application/xml",
    title = "Plan (gdal mdim mosaic VRT, verbatim sources)", roles = list("metadata"),
    `rv:form` = "plan")
  lapply(a, function(x) Filter(Negate(is.null), x))
}

## ---- the render --------------------------------------------------------------------
mr_write_stac <- function(con, out, target = NULL, base = NULL, plan_file = NULL,
                          items_dir = TRUE, verbose = TRUE) {
  dir <- file.path(out, "stac")
  unlink(dir, recursive = TRUE); dir.create(file.path(dir, "items"), recursive = TRUE)
  meta <- dbReadTable(con, "meta"); meta <- as.list(stats::setNames(meta$value, meta$key))
  plan <- .stac_plan(plan_file)
  if (!length(plan$dim_type))  # no plan file beside the store: the store keeps the types
    plan$dim_type <- unlist(lapply(mr_dimensions(con), `[[`, "type"))
  arrays <- mr_array_list(con); names(arrays) <- vapply(arrays, `[[`, "", "array")
  data <- Filter(function(a) a$storage == "referenced", arrays)
  if (!length(data)) stop("stac: no referenced arrays in the store")

  ## dimensions of the data arrays, with values, role and decoded time
  dnames <- unique(unlist(lapply(data, `[[`, "dims")))
  dims <- lapply(stats::setNames(dnames, dnames), function(d) {
    co <- arrays[[d]]; at <- co$attrs %||% list()
    if (is.null(at$units) && !is.null(plan$units[[d]])) at$units <- plan$units[[d]]
    v <- .coord_vals(co)
    role <- .dim_role(d, at, plan$dim_type[d][[1]])
    list(name = d, values = v, attrs = at, role = role,
         time = if (role == "t" && !is.null(v)) .cf_time(v, at$units, at$calendar))
  })
  role_of <- vapply(dims, `[[`, "", "role")
  dx <- names(role_of)[role_of == "x"][1]; dy <- names(role_of)[role_of == "y"][1]
  dt <- names(role_of)[role_of == "t"][1]
  epsg <- .epsg(plan$srs)
  geographic <- !is.na(dx) && !is.na(dy) &&
    (is.na(epsg) || epsg == "EPSG:4326") &&
    (!is.na(epsg) || grepl("^degrees?_?e", tolower(dims[[dx]]$attrs$units %||% "")) ||
       tolower(dx) %in% c("lon", "longitude", "xt_ocean", "xu_ocean"))

  ## bbox over index ranges ix, iy (1-based); NULL without geographic x/y
  bbox_of <- function(ix, iy) {
    if (!geographic || is.null(dims[[dx]]$values) || is.null(dims[[dy]]$values)) return(NULL)
    we <- .lon_we(.edges(dims[[dx]]$values, ix))
    sn <- pmin(pmax(.edges(dims[[dy]]$values, iy), -90), 90)
    c(we[1], sn[1], we[2], sn[2])
  }
  full <- function(d) seq_along(dims[[d]]$values)
  cbbox <- if (geographic) bbox_of(full(dx), full(dy)) else c(-180, -90, 180, 90)
  if (!geographic) warning("stac: no geographic x/y found; spatial extent written as the globe")
  ttime <- if (!is.na(dt)) dims[[dt]]$time

  ## datacube
  cube_dims <- lapply(dims, function(d) {
    v <- d$values; st <- .step(v)
    x <- switch(d$role,
      x = , y = list(type = "spatial", axis = d$role,
                     extent = if (!is.null(v)) I(range(v)), step = st,
                     reference_system = if (!is.na(epsg)) as.integer(sub("EPSG:", "", epsg))
                                        else if (geographic) 4326L),
      z = list(type = "spatial", axis = "z", extent = if (!is.null(v)) I(range(v)),
               values = if (!is.null(v) && is.null(st) && length(v) <= 1000) I(v), step = st,
               unit = d$attrs$units),
      t = list(type = "temporal", extent = if (!is.null(d$time)) I(.iso(range(d$time))),
               step = if (!is.null(d$time)) .iso_duration(.step(as.numeric(d$time)))),
      list(type = "other", extent = if (!is.null(v)) I(range(v)), step = st,
           values = if (!is.null(v) && is.null(st) && length(v) <= 1000) I(v),
           unit = d$attrs$units))
    if (!is.null(d$attrs$long_name)) x$description <- d$attrs$long_name
    Filter(Negate(is.null), x)
  })
  cube_vars <- lapply(data, function(a) Filter(Negate(is.null), list(
    dimensions = I(a$dims), type = "data",
    description = a$attrs$long_name, unit = a$attrs$units,
    `rv:dtype` = a$dtype, `rv:chunks` = I(a$chunks))))

  ## items: one per source, from its placements
  P <- dbGetQuery(con, "SELECT p.array, p.source_id, p.count, p.dest, s.source, s.size
                        FROM placements p JOIN sources s USING (source_id)
                        ORDER BY p.source_id")
  P <- P[P$array %in% names(data), , drop = FALSE]
  P$path <- mr_remap(con, P$source, target)
  ## item id: the file name without extension, with the source_id appended
  ## where two sources share a name
  S <- unique(P[c("source_id", "source")])
  S$id <- sub("[.][^.]*$", "", basename(sub("[?#].*$", "", S$source)))
  dup <- S$id %in% S$id[duplicated(S$id)]
  S$id[dup] <- paste0(S$id[dup], "-", S$source_id[dup])
  P$id <- S$id[match(P$source_id, S$source_id)]
  items <- lapply(split(P, P$source_id), function(p) {
    a1 <- data[[p$array[1]]]
    de <- .fj(p$dest[1]); cn <- .fj(p$count[1])
    rng <- function(d) { k <- match(d, a1$dims); if (is.na(k)) NULL else seq.int(de[k] + 1L, length.out = cn[k]) }
    bb <- if (geographic) bbox_of(rng(dx) %||% full(dx), rng(dy) %||% full(dy)) else cbbox
    props <- list()
    if (!is.null(ttime) && !is.null(it <- rng(dt))) {
      tt <- range(ttime[it])
      if (tt[1] == tt[2]) props$datetime <- .iso(tt[1])
      else props[c("datetime", "start_datetime", "end_datetime")] <- list(NULL, .iso(tt[1]), .iso(tt[2]))
    } else {
      props$datetime <- meta$created %||% .iso(Sys.time())
    }
    if (is.null(props$datetime)) props["datetime"] <- list(NULL)
    if (!is.na(epsg) && !is.na(dx) && !is.na(dy) && !is.null(arrays[[dx]]$affine) &&
        !is.null(arrays[[dy]]$affine)) {
      ax <- arrays[[dx]]$affine; ay <- arrays[[dy]]$affine
      ix <- rng(dx) %||% full(dx); iy <- rng(dy) %||% full(dy)
      props[["proj:code"]] <- epsg
      props[["proj:shape"]] <- I(c(length(iy), length(ix)))
      props[["proj:transform"]] <- I(c(ax$step, 0, ax$start + ax$step * (ix[1] - 1.5),
                                       0, ay$step, ay$start + ay$step * (iy[1] - 1.5)))
    }
    props[["rv:placement"]] <- lapply(stats::setNames(seq_len(nrow(p)), p$array), function(i)
      list(dest = I(.fj(p$dest[i])), count = I(.fj(p$count[i]))))
    asset <- Filter(Negate(is.null), list(href = p$path[1], type = .media_type(p$source[1]),
      roles = list("data"), `file:size` = if (!is.na(p$size[1])) as.numeric(p$size[1]),
      `rv:source` = if (p$path[1] != p$source[1]) p$source[1]))
    list(type = "Feature", stac_version = STAC_VERSION,
         stac_extensions = I(unname(STAC_EXT[c("file", if (!is.null(props[["proj:code"]])) "projection")])),
         id = p$id[1], geometry = .bbox_geom(bb), bbox = I(bb), properties = props,
         links = list(), assets = list(data = asset), collection = meta$dataset)
  })
  items <- items[order(vapply(items, function(x) x$properties$start_datetime %||%
                                x$properties$datetime %||% "", ""))]

  ## collection
  forms <- .form_assets(out, base, .containers(unique(P$path)))
  textent <- if (!is.null(ttime)) I(list(I(.iso(range(ttime))))) else I(list(I(c(NA, NA))))
  coll <- list(
    type = "Collection", stac_version = STAC_VERSION,
    stac_extensions = I(unname(STAC_EXT[c("datacube", "xarray")])),
    id = meta$dataset,
    title = meta$dataset,
    description = sprintf(paste(
      "Virtualized collection of %d source files (%s), rendered from an mdim-refs/0.2 store",
      "of byte references. Collection assets are the virtual forms of the whole cube;",
      "items are the source granules."), length(items), paste(names(data), collapse = ", ")),
    license = "other",
    extent = list(spatial = list(bbox = I(list(I(cbbox)))), temporal = list(interval = textent)),
    `cube:dimensions` = cube_dims, `cube:variables` = cube_vars,
    item_assets = list(data = list(type = .media_type(P$source[1]), roles = list("data"))),
    assets = forms,
    links = unname(c(
      list(list(rel = "root", href = "./collection.json", type = "application/json")),
      if (!is.null(base)) list(list(rel = "self", type = "application/json",
                                    href = paste0(sub("/$", "", base), "/stac/collection.json"))),
      if (items_dir) lapply(items, function(x)
        list(rel = "item", href = sprintf("./items/%s.json", x$id), type = "application/geo+json")))),
    `rv:meta` = meta[setdiff(names(meta), MR_META_JSON)])

  js <- function(x, pretty = FALSE) jsonlite::toJSON(x, auto_unbox = TRUE, digits = I(15),
                                                     null = "null", na = "null", pretty = pretty)
  writeLines(js(coll, TRUE), file.path(dir, "collection.json"))
  ## each item is serialized once: the ndjson row has no links (its relative
  ## links would resolve against stac/, not stac/items/), the item file gets
  ## them spliced in
  rows <- vapply(items, function(x) as.character(js(x)), "")
  writeLines(rows, file.path(dir, "items.ndjson"))
  if (items_dir) {
    lk <- as.character(js(lapply(c("collection", "parent", "root"), function(r)
      list(rel = r, href = "../collection.json", type = "application/json"))))
    files <- file.path(dir, "items", paste0(vapply(items, `[[`, "", "id"), ".json"))
    for (i in seq_along(rows))
      writeLines(sub('"links":[]', paste0('"links":', lk), rows[i], fixed = TRUE), files[i])
  }
  if (!items_dir) unlink(file.path(dir, "items"), recursive = TRUE)
  if (verbose) message(sprintf("  stac: collection with %d assets, %d items", length(forms), length(items)))
  invisible(dir)
}

if (sys.nframe() == 0L) {
  db <- args[1]; out <- args[2]
  tg <- function(x) if (is.na(x) || !nzchar(x)) NULL else x
  target <- tg(args[3]); base <- tg(args[4])
  con <- mr_open(db)
  pf <- dbGetQuery(con, "SELECT value FROM meta WHERE key = 'plan'")$value
  pf <- if (length(pf) && !is.na(pf)) file.path(dirname(db), pf)
  t0 <- Sys.time()
  mr_write_stac(con, out, target = target, base = base, plan_file = pf,
                items_dir = Sys.getenv("STAC_ITEM_FILES", "1") != "0")
  DBI::dbDisconnect(con)
  message(sprintf("STAC: %.1f s", as.numeric(Sys.time() - t0, units = "secs")))
}
