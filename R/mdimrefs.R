## mdimrefs.R -- reference implementation of the mdim-refs/0.2 store (SPEC.md).
## ----------------------------------------------------------------------------
## Merges raad.virtualize R/store.R (per-source rows keyed on source + within-
## source chunk coord; source recorded verbatim) with aad-filelist
## mdim_refs_sqlite.R (arrays metadata, inline data, info, format version).
## The global chunk index is a VIEW, refs_<array>, whose columns are the
## block-info row: dim_0..dim_{n-1}, present, path, offset, size, info, data.
##
## Dependencies: DBI, RSQLite, jsonlite, xml2 (plan parsing), arrow (scan
## ingest), blocklist (kerchunk Parquet writer).
## ----------------------------------------------------------------------------
library(DBI)

MR_FORMAT   <- "mdim-refs/0.2"
MR_RESERVED <- c("meta", "sources", "arrays", "placements", "remap")
## meta keys that hold JSON for the renders, not dataset attributes
MR_META_JSON <- c("coord_attrs", "dimensions")

.q   <- function(con, x) as.character(dbQuoteIdentifier(con, x))
.j   <- function(x) if (is.null(x)) NA_character_ else
  as.character(jsonlite::toJSON(x, auto_unbox = TRUE, digits = I(17), null = "null"))  # 17 significant: exact round trip
.jl  <- function(x) as.character(jsonlite::toJSON(x, auto_unbox = FALSE))  # always array
.fj  <- function(x) if (is.na(x)) NULL else jsonlite::fromJSON(x, simplifyVector = TRUE)
.dims <- function(rank) paste0("dim_", seq_len(rank) - 1L)

## ---- connection -------------------------------------------------------------
mr_open <- function(path, write = FALSE) {
  con <- dbConnect(RSQLite::SQLite(), path, bigint = "integer64",
                   flags = if (write) RSQLite::SQLITE_RWC else RSQLite::SQLITE_RO)
  dbExecute(con, "PRAGMA foreign_keys = ON")
  if (write) {
    dbExecute(con, "PRAGMA journal_mode = WAL")
    dbExecute(con, "PRAGMA synchronous = NORMAL")
    dbExecute(con, "PRAGMA busy_timeout = 30000")
  }
  con
}

## ---- core tables ------------------------------------------------------------
mr_init <- function(con, meta = list()) {
  dbExecute(con, "CREATE TABLE IF NOT EXISTS meta(
      key TEXT PRIMARY KEY, value TEXT) WITHOUT ROWID")
  dbExecute(con, "CREATE TABLE IF NOT EXISTS sources(
      source_id INTEGER PRIMARY KEY,
      source    TEXT NOT NULL UNIQUE,   -- URI as opened at scan time, verbatim
      size      BIGINT,                 -- bytes, at scan time
      mtime     BIGINT,                 -- unix seconds, at scan time
      etag      TEXT)")
  dbExecute(con, "CREATE TABLE IF NOT EXISTS arrays(
      array   TEXT PRIMARY KEY,
      kind    TEXT NOT NULL,            -- 'data' | 'coord'
      storage TEXT NOT NULL,            -- 'referenced' | 'inline' | 'affine'
      dims    TEXT,                     -- JSON names, C order
      shape   TEXT,                     -- JSON ints, global (from the plan)
      chunks  TEXT,                     -- JSON ints, chunk shape
      dtype   TEXT,                     -- numpy, e.g. '<i2'
      fill    TEXT,                     -- text token (NaN/Inf safe)
      codec   TEXT,                     -- JSON {compressor, filters} (Zarr v2 ids)
      attrs   TEXT,                     -- JSON, CF attributes
      affine  TEXT,                     -- JSON {start, step} for storage='affine'
      \"values\" BLOB                    -- whole-array bytes for storage='inline'
    ) WITHOUT ROWID")
  dbExecute(con, "CREATE TABLE IF NOT EXISTS placements(
      array        TEXT NOT NULL REFERENCES arrays(array),
      source_id    INTEGER NOT NULL REFERENCES sources(source_id),
      source_array TEXT NOT NULL,       -- name of the array inside the source
      src_offset   TEXT NOT NULL,       -- JSON element offsets (VRT SourceSlab)
      count        TEXT NOT NULL,       -- JSON element counts  (VRT SourceSlab)
      dest         TEXT NOT NULL,       -- JSON element offsets (VRT DestSlab)
      PRIMARY KEY (array, dest)) WITHOUT ROWID")
  dbExecute(con, "CREATE TABLE IF NOT EXISTS remap(
      target      TEXT NOT NULL,        -- e.g. 'public', 's3', 'local'
      prefix      TEXT NOT NULL,
      replacement TEXT NOT NULL,
      PRIMARY KEY (target, prefix)) WITHOUT ROWID")
  meta <- utils::modifyList(list(format_version = MR_FORMAT), meta)
  for (k in names(meta))
    dbExecute(con, "INSERT INTO meta(key,value) VALUES(?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              params = list(k, as.character(meta[[k]])))
  invisible(con)
}

mr_rank <- function(con, array) {
  sum(grepl("^dim_[0-9]+$",
            dbGetQuery(con, sprintf("PRAGMA table_info(%s)", .q(con, array)))$name))
}

## ---- arrays -----------------------------------------------------------------
## A 'referenced' array gets a chunk table named after it: within-source rows,
## keyed (source_id, dim_0..), source_id first so "all chunks of a source" is a
## prefix scan and a rescan of one source is an in-place upsert.
mr_add_array <- function(con, array, dims, chunks, dtype, kind = "data",
                         storage = "referenced", shape = NULL, fill = NA,
                         codec = NULL, attrs = NULL, affine = NULL, values = NULL) {
  stopifnot(!array %in% MR_RESERVED, length(dims) >= 1L,
            length(chunks) == length(dims))
  dbExecute(con, 'INSERT INTO arrays(array,kind,storage,dims,shape,chunks,dtype,
                                     fill,codec,attrs,affine,"values")
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(array) DO UPDATE SET kind=excluded.kind, storage=excluded.storage,
      dims=excluded.dims, shape=COALESCE(excluded.shape, shape),
      chunks=excluded.chunks, dtype=excluded.dtype, fill=excluded.fill,
      codec=excluded.codec, attrs=excluded.attrs, affine=excluded.affine,
      "values"=excluded."values"',
    params = list(array, kind, storage, .jl(dims),
                  if (is.null(shape)) NA_character_ else .jl(as.integer(shape)),
                  .jl(as.integer(chunks)), dtype, as.character(fill),
                  .j(codec), .j(attrs), .j(affine),
                  list(if (is.null(values)) NULL else values)))
  if (storage == "referenced") {
    rank <- length(dims); d <- .dims(rank); tbl <- .q(con, array)
    if (array %in% dbListTables(con) && mr_rank(con, array) != rank)
      stop(sprintf("array '%s' exists with rank %d, not %d", array,
                   mr_rank(con, array), rank))
    dbExecute(con, sprintf('CREATE TABLE IF NOT EXISTS %s (
        source_id INTEGER NOT NULL REFERENCES sources(source_id),
        %s,
        present INTEGER NOT NULL DEFAULT 1,
        "offset" BIGINT,
        size     BIGINT,
        info     TEXT,
        data     BLOB,
        PRIMARY KEY (source_id, %s)) WITHOUT ROWID', tbl,
      paste(d, "INTEGER NOT NULL", collapse = ",\n        "),
      paste(d, collapse = ", ")))
  }
  invisible(array)
}

mr_arrays <- function(con) dbGetQuery(con, "SELECT * FROM arrays ORDER BY kind DESC, array")

## ---- sources ----------------------------------------------------------------
mr_add_sources <- function(con, source, size = NA, mtime = NA, etag = NA) {
  n <- length(source)
  dbExecute(con, "INSERT INTO sources(source,size,mtime,etag) VALUES(?,?,?,?)
                  ON CONFLICT(source) DO UPDATE SET
                    size=COALESCE(excluded.size,size),
                    mtime=COALESCE(excluded.mtime,mtime),
                    etag=COALESCE(excluded.etag,etag)",
            params = list(source, rep_len(as.numeric(size), n),
                          rep_len(as.numeric(mtime), n), rep_len(as.character(etag), n)))
  ids <- dbGetQuery(con, "SELECT source, source_id FROM sources")
  ids$source_id[match(source, ids$source)]
}

## ---- merge per-source chunk rows (block-info shape + `source`) ---------------
## rows: data.frame(source, dim_0.., present, offset, size, info[, data]).
## One transaction: the single-writer boundary.
mr_merge <- function(con, array, rows) {
  if (!nrow(rows)) return(invisible(0L))
  rank <- mr_rank(con, array); d <- .dims(rank)
  stopifnot(all(d %in% names(rows)))
  dbWithTransaction(con, {
    sid <- mr_add_sources(con, unique(rows$source))
    rows$source_id <- sid[match(rows$source, unique(rows$source))]
    if (is.null(rows$data)) rows$data <- vector("list", nrow(rows))
    val <- c("source_id", d, "present", '"offset"', "size", "info", "data")
    set <- c("present", '"offset"', "size", "info", "data")
    dbExecute(con, sprintf('INSERT INTO %s (%s) VALUES (%s)
                            ON CONFLICT (source_id, %s) DO UPDATE SET %s',
      .q(con, array), paste(val, collapse = ","),
      paste(rep("?", length(val)), collapse = ","), paste(d, collapse = ","),
      paste(sprintf("%s=excluded.%s", set, set), collapse = ", ")),
      params = c(list(rows$source_id), lapply(d, function(k) as.integer(rows[[k]])),
                 list(as.integer(rows$present), as.numeric(rows$offset),
                      as.numeric(rows$size), as.character(rows$info),
                      blob::as_blob(lapply(rows$data, function(x) if (is.null(x)) NULL else as.raw(x))))))
  })
  invisible(nrow(rows))
}

## ---- codec from block-info `info` --------------------------------------------
## GDAL reports per-chunk KEY=VALUE pairs; map the array-level set to Zarr v2.
## TIFF PREDICTOR=2 is horizontal differencing restarted on every row, which
## numcodecs `delta` (one run over the flattened chunk) does not reproduce;
## it maps to imagecodecs `imagecodecs_delta` along the last axis, as tifffile
## writes it. Readers need imagecodecs; GDAL's Zarr driver has no equivalent.
mr_codec_from_info <- function(info, dtype, chunks = NULL) {
  kv <- trimws(strsplit(info, ";", fixed = TRUE)[[1]])
  kv <- stats::setNames(sub("^[^=]*=", "", kv), sub("=.*$", "", kv))
  itemsize <- as.integer(sub("^.{2}", "", dtype))
  filters <- list(); compressor <- NULL
  for (f in kv[names(kv) == "FILTER"]) {
    if (f == "SHUFFLE") filters[[length(filters) + 1L]] <- list(id = "shuffle", elementsize = itemsize)
    else stop("unsupported FILTER=", f)
  }
  pred <- if ("PREDICTOR" %in% names(kv)) kv[["PREDICTOR"]] else "1"
  if (pred == "2") {
    if (is.null(chunks)) stop("PREDICTOR=2 needs the chunk shape")
    filters[[length(filters) + 1L]] <- list(id = "imagecodecs_delta", axis = -1L, dist = 1L,
                                            dtype = dtype, shape = as.integer(chunks))
  } else if (pred != "1") stop("unsupported PREDICTOR=", pred)
  comp <- kv[["COMPRESSION"]] %||% "NONE"
  compressor <- switch(comp, DEFLATE = list(id = "zlib", level = 1L),
                       ZSTD = list(id = "zstd", level = 1L), NONE = NULL,
                       stop("unsupported COMPRESSION=", comp))
  list(compressor = compressor, filters = if (length(filters)) filters else NULL)
}
`%||%` <- function(a, b) if (is.null(a) || (length(a) == 1L && is.na(a))) b else a

## CF attributes from the scanner's physical description: GDAL lifts units,
## scale, offset and nodata out of the attribute list, so they are restored.
.cf_attrs <- function(m) {
  a <- m$attrs %||% list()
  if (!is.null(m$unit))   a$units        <- m$unit
  if (!is.null(m$nodata)) a[["_FillValue"]] <- m$nodata
  if (!is.null(m$scale)  && !isTRUE(m$scale == 1))  a$scale_factor <- m$scale
  if (!is.null(m$offset) && !isTRUE(m$offset == 0)) a$add_offset   <- m$offset
  a
}

## One fill value per array. An absent chunk reads as the Zarr fill_value,
## which the renders set to `fill`; a CF reader masks _FillValue and
## missing_value. If these differ, absent chunks read as data, or readers
## disagree on what is masked, so ingest stops.
.check_fill <- function(nm, attrs, fill) {
  num <- function(x) suppressWarnings(as.numeric(unlist(x)))
  same <- function(a, b) (is.nan(a) & is.nan(b)) | (!is.na(a) & !is.na(b) & a == b)
  f <- num(fill); fv <- num(attrs[["_FillValue"]]); mv <- num(attrs$missing_value)
  if (!length(f) || (is.na(f) && !is.nan(f))) {
    if (length(fv) || length(mv))
      warning(sprintf("array '%s': no nodata, but _FillValue/missing_value set", nm), call. = FALSE)
    return(invisible(TRUE))
  }
  bad <- c(if (length(fv) && !all(same(fv, f))) sprintf("_FillValue %s", paste(fv, collapse = ",")),
           if (length(mv) && !any(same(mv, f))) sprintf("missing_value %s", paste(mv, collapse = ",")))
  if (length(bad)) stop(sprintf("array '%s': fill %s conflicts with %s", nm, fill,
                                paste(bad, collapse = " and ")), call. = FALSE)
  invisible(TRUE)
}

## ---- ingest a blockinfo_scan.py output directory ------------------------------
mr_ingest_scan <- function(con, dir) {
  src <- as.data.frame(arrow::read_parquet(file.path(dir, "sources.parquet")))
  mr_add_sources(con, src$source, src$size, src$mtime)
  meta <- jsonlite::fromJSON(file.path(dir, "arrays.json"), simplifyVector = FALSE)
  for (nm in names(meta)) {
    m <- meta[[nm]]
    if (!isTRUE(m$scanned)) next
    rows <- as.data.frame(arrow::read_parquet(file.path(dir, sprintf("chunks_%s.parquet", nm))))
    info <- unique(stats::na.omit(rows$info[rows$present == 1L]))
    if (length(info) > 1L) stop(sprintf(
      "array '%s': chunks disagree on codec (%s); not virtualizable as one array",
      nm, paste(info, collapse = " | ")))
    dtype <- m$dtype
    .check_fill(nm, m$attrs %||% list(), m$nodata %||% NA)
    mr_add_array(con, nm, dims = unlist(m$dims), chunks = unlist(m$chunks),
                 dtype = dtype, fill = m$nodata %||% NA,
                 codec = if (length(info)) mr_codec_from_info(info, dtype, unlist(m$chunks)) else NULL,
                 attrs = .cf_attrs(m))
    mr_merge(con, nm, rows)
  }
  ## coordinate attrs (units the mosaic VRT drops) kept for the plan step
  coords <- Filter(function(m) !isTRUE(m$scanned), meta)
  dbExecute(con, "INSERT INTO meta(key,value) VALUES('coord_attrs',?)
                  ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            params = list(.j(lapply(coords, .cf_attrs))))
  invisible(con)
}

## ---- the plan: a `gdal mdim mosaic` VRT ---------------------------------------
.gdal_numpy <- c(Byte = "|u1", Int8 = "|i1", UInt16 = "<u2", Int16 = "<i2",
                 UInt32 = "<u4", Int32 = "<i4", UInt64 = "<u8", Int64 = "<i8",
                 Float32 = "<f4", Float64 = "<f8")
.ints <- function(x) as.integer(strsplit(x, ",", fixed = TRUE)[[1]])

mr_plan_vrt <- function(vrt) {
  doc <- xml2::read_xml(vrt); g <- xml2::xml_find_first(doc, ".//Group")
  dm <- xml2::xml_find_all(g, "./Dimension")
  dim_size <- stats::setNames(as.integer(xml2::xml_attr(dm, "size")), xml2::xml_attr(dm, "name"))
  ## dimension roles (HORIZONTAL_X, VERTICAL, TEMPORAL, ...) and directions
  ## (EAST, UP, ...) as the mosaic wrote them, kept so the renders restate them
  dim_role <- lapply(dm, function(d) {
    x <- list(type = xml2::xml_attr(d, "type"), direction = xml2::xml_attr(d, "direction"))
    x[!is.na(unlist(x))]
  })
  names(dim_role) <- names(dim_size)
  out <- list(arrays = list(), coords = list(), dimensions = Filter(length, dim_role))
  for (a in xml2::xml_find_all(g, "./Array")) {
    nm   <- xml2::xml_attr(a, "name")
    refs <- xml2::xml_attr(xml2::xml_find_all(a, "./DimensionRef"), "ref")
    dt   <- .gdal_numpy[[xml2::xml_text(xml2::xml_find_first(a, "./DataType"))]]
    srcs <- xml2::xml_find_all(a, "./Source")
    if (!length(srcs)) {
      iv <- xml2::xml_find_first(a, "./InlineValues")
      rs <- xml2::xml_find_first(a, "./RegularlySpacedValues")
      un <- xml2::xml_text(xml2::xml_find_first(a, "./Unit"))
      out$coords[[nm]] <- list(dims = refs, shape = unname(dim_size[refs]), dtype = dt,
        unit = if (!is.na(un)) un,
        values = if (!is.na(iv)) as.numeric(strsplit(trimws(xml2::xml_text(iv)), "\\s+")[[1]]),
        affine = if (!is.na(rs)) list(start = as.numeric(xml2::xml_attr(rs, "start")),
                                      step  = as.numeric(xml2::xml_attr(rs, "increment"))))
      next
    }
    fn <- xml2::xml_text(xml2::xml_find_first(srcs, "./SourceFilename"))
    rel <- !grepl("^(/|[a-zA-Z][a-zA-Z0-9+.-]*://)", fn)
    if (any(rel)) fn[rel] <- normalizePath(file.path(dirname(vrt), fn[rel]), mustWork = FALSE)
    ss <- xml2::xml_find_first(srcs, "./SourceSlab"); ds <- xml2::xml_find_first(srcs, "./DestSlab")
    rank <- length(refs)
    sl <- function(node, attr, default) lapply(xml2::xml_attr(node, attr),
                                               function(x) if (is.na(x)) default else .ints(x))
    ## a <SourceBand> source (a 2D raster band given a leading length-1 axis
    ## by <SourceTranspose>-1,0,1</SourceTranspose>, the vrtstack form) is
    ## recorded as source_array "band:<n>", placed whole
    sa <- sub("^/", "", xml2::xml_text(xml2::xml_find_first(srcs, "./SourceArray")))
    sb <- xml2::xml_text(xml2::xml_find_first(srcs, "./SourceBand"))
    band <- is.na(sa) & !is.na(sb)
    sa[band] <- paste0("band:", sb[band])
    band_count <- .jl(c(1L, unname(dim_size[refs])[-1L]))
    out$arrays[[nm]] <- list(
      dims = refs, shape = unname(dim_size[refs]), dtype = dt,
      sources = data.frame(
        source = fn,
        source_array = sa,
        src_offset = vapply(sl(ss, "offset", rep(0L, rank)), .jl, ""),
        count      = ifelse(band, band_count, vapply(sl(ss, "count",  NA_integer_), .jl, "")),
        step       = vapply(sl(ss, "step",   rep(1L, rank)), .jl, ""),
        dest       = vapply(sl(ds, "offset", rep(0L, rank)), .jl, ""),
        stringsAsFactors = FALSE))
  }
  out
}

## Write the plan into the store: global shapes, placements (replacing any
## previous plan) and coordinate arrays. Every placement must be chunk-aligned,
## or the mosaic is not expressible as one regular chunk grid.
mr_set_plan <- function(con, plan, plan_uri = NA_character_) {
  coord_attrs <- .fj(dbGetQuery(con, "SELECT value FROM meta WHERE key='coord_attrs'")$value %||% NA)
  dbWithTransaction(con, {
    dbExecute(con, "DELETE FROM placements")
    for (nm in names(plan$arrays)) {
      P <- plan$arrays[[nm]]
      a <- dbGetQuery(con, "SELECT * FROM arrays WHERE array = ?", params = list(nm))
      if (!nrow(a)) stop("plan array '", nm, "' has no scanned chunks in the store")
      ch <- .fj(a$chunks)
      dbExecute(con, "UPDATE arrays SET shape = ?, dims = ? WHERE array = ?",
                params = list(.jl(as.integer(P$shape)), .jl(P$dims), nm))
      S <- P$sources
      for (i in seq_len(nrow(S))) {
        so <- .fj(S$src_offset[i]); cn <- .fj(S$count[i]); de <- .fj(S$dest[i])
        st <- .fj(S$step[i])
        ok <- all(st == 1L) && all(so %% ch == 0L) && all(de %% ch == 0L) &&
              all((de + cn) %% ch == 0L | (de + cn) == P$shape)
        if (!ok) stop(sprintf("array '%s', source %s: slab not chunk-aligned (offset %s, count %s, dest %s, chunks %s)",
                              nm, S$source[i], S$src_offset[i], S$count[i], S$dest[i], .jl(ch)))
      }
      sid <- mr_add_sources(con, S$source)
      dbExecute(con, "INSERT INTO placements(array,source_id,source_array,src_offset,count,dest)
                      VALUES(?,?,?,?,?,?)",
                params = list(rep(nm, nrow(S)), sid, S$source_array, S$src_offset, S$count, S$dest))
    }
    for (nm in names(plan$coords)) {
      C <- plan$coords[[nm]]
      vals <- if (!is.null(C$values)) .values_to_raw(C$values, C$dtype)
      ## units from the plan where the harvest recorded none (the vrtstack
      ## plan for GeoTIFF sources has a time coordinate no source holds)
      at <- coord_attrs[[nm]]
      if (is.null(at$units) && !is.null(C$unit)) at <- c(at, list(units = C$unit))
      mr_add_array(con, nm, dims = C$dims, chunks = C$shape, dtype = C$dtype,
                   kind = "coord", storage = if (is.null(vals)) "affine" else "inline",
                   shape = C$shape, attrs = at, affine = C$affine,
                   values = vals)
    }
    dbExecute(con, "INSERT INTO meta(key,value) VALUES('plan',?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              params = list(plan_uri))
    if (length(plan$dimensions))
      dbExecute(con, "INSERT INTO meta(key,value) VALUES('dimensions',?)
                      ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                params = list(.j(plan$dimensions)))
  })
  mr_create_views(con)
  invisible(con)
}

## dimension type and direction from the plan, list(<dim> = list(type, direction))
mr_dimensions <- function(con) {
  v <- dbGetQuery(con, "SELECT value FROM meta WHERE key = 'dimensions'")$value
  if (!length(v)) return(list())
  jsonlite::fromJSON(v, simplifyVector = FALSE)
}

.values_to_raw <- function(values, dtype) {
  sz <- as.integer(sub("^.{2}", "", dtype)); fl <- substr(dtype, 2, 2) == "f"
  writeBin(if (fl) as.double(values) else as.integer(values), raw(), size = sz,
           endian = if (startsWith(dtype, ">")) "big" else "little")
}

## ---- remap: publish-time prefix rewrite of verbatim sources --------------------
mr_set_remap <- function(con, target, prefix, replacement) {
  dbExecute(con, "INSERT INTO remap(target,prefix,replacement) VALUES(?,?,?)
                  ON CONFLICT(target,prefix) DO UPDATE SET replacement=excluded.replacement",
            params = list(target, prefix, replacement))
  invisible(con)
}

## ---- the global view: block-info rows of the mosaic ----------------------------
## global dim_i = within-source dim_i - src_offset_i/chunk_i + dest_i/chunk_i,
## restricted to the chunks inside the source slab. `target` applies the
## longest matching remap prefix to `path`; NULL keeps the verbatim source.
mr_view_sql <- function(con, array, target = NULL) {
  a  <- dbGetQuery(con, "SELECT chunks FROM arrays WHERE array = ?", params = list(array))
  ch <- .fj(a$chunks); rank <- length(ch); i <- seq_len(rank) - 1L
  je <- function(col, k) sprintf("CAST(json_extract(p.%s, '$[%d]') AS INTEGER)", col, k)
  glob <- sprintf("c.dim_%d - %s / %d + %s / %d AS dim_%d", i, je("src_offset", i), ch,
                  je("dest", i), ch, i)
  inside <- sprintf("c.dim_%d >= %s / %d AND c.dim_%d < (%s + %s + %d - 1) / %d",
                    i, je("src_offset", i), ch, i, je("src_offset", i), je("count", i), ch, ch)
  path <- if (is.null(target)) "s.source" else sprintf(
    "COALESCE((SELECT r.replacement || substr(s.source, length(r.prefix) + 1) FROM remap r
       WHERE r.target = %s AND substr(s.source, 1, length(r.prefix)) = r.prefix
       ORDER BY length(r.prefix) DESC LIMIT 1), s.source)", dbQuoteString(con, target))
  sprintf('SELECT %s, c.present, CASE WHEN c."offset" IS NULL THEN NULL ELSE %s END AS path,
       c."offset", c.size, c.info, c.data
  FROM %s c JOIN placements p ON p.array = %s AND p.source_id = c.source_id
            JOIN sources s ON s.source_id = c.source_id
  WHERE %s
  ORDER BY %s',
    paste(glob, collapse = ",\n       "), path, .q(con, array), dbQuoteString(con, array),
    paste(inside, collapse = "\n    AND "), paste0("dim_", i, collapse = ", "))
}

mr_create_views <- function(con) {
  for (nm in dbGetQuery(con, "SELECT array FROM arrays WHERE storage='referenced'")$array) {
    v <- .q(con, paste0("refs_", nm))
    dbExecute(con, sprintf("DROP VIEW IF EXISTS %s", v))
    dbExecute(con, sprintf("CREATE VIEW %s AS %s", v, mr_view_sql(con, nm)))
  }
  invisible(con)
}

mr_refs <- function(con, array, target = NULL) dbGetQuery(con, mr_view_sql(con, array, target))

## one chunk by global coordinate (the per-chunk read path)
mr_chunk <- function(con, array, idx, target = NULL) {
  w <- paste(sprintf("dim_%d = %d", seq_along(idx) - 1L, as.integer(idx)), collapse = " AND ")
  dbGetQuery(con, sprintf("SELECT * FROM (%s) WHERE %s", mr_view_sql(con, array, target), w))
}

## ---- Zarr v2 metadata synthesised from arrays rows ---------------------------
mr_zarr_v2 <- function(con, array) {
  a <- dbGetQuery(con, 'SELECT * FROM arrays WHERE array = ?', params = list(array))
  codec <- .fj(a$codec) %||% list()
  inl <- a$storage != "referenced"
  shape <- .fj(a$shape)
  list(.zarray = list(
         zarr_format = 2L, shape = I(shape),
         chunks = I(if (inl) shape else .fj(a$chunks)),
         dtype = a$dtype,
         compressor = if (inl) NULL else codec$compressor,
         filters = if (inl) NULL else codec$filters,
         fill_value = if (is.na(a$fill)) NULL else .fill_json(a$fill),
         order = "C", dimension_separator = "."),
       .zattrs = c(list(`_ARRAY_DIMENSIONS` = I(.fj(a$dims))), .fj(a$attrs) %||% list()))
}
.fill_json <- function(x) {
  v <- suppressWarnings(as.numeric(x))
  if (is.nan(v)) "NaN" else if (is.infinite(v)) (if (v > 0) "Infinity" else "-Infinity") else v
}

## whole-array bytes of a coordinate (inline values or affine materialised)
mr_coord_raw <- function(con, array) {
  a <- dbGetQuery(con, 'SELECT * FROM arrays WHERE array = ?', params = list(array))
  if (a$storage == "inline") return(a$values[[1]])
  af <- .fj(a$affine); n <- .fj(a$shape)
  .values_to_raw(af$start + af$step * (seq_len(n) - 1L), a$dtype)
}

## ---- writer D: kerchunk Parquet, via blocklist::write_kerchunk_parquet --------
mr_write_kerchunk_parquet <- function(con, root, target = NULL, record_size = 100000L) {
  A <- mr_arrays(con); vars_meta <- list(); ref_tables <- list(); inline <- list()
  for (i in seq_len(nrow(A))) {
    nm <- A$array[i]; z <- mr_zarr_v2(con, nm)
    zm <- z$.zarray; at <- z$.zattrs; at$`_ARRAY_DIMENSIONS` <- NULL
    vars_meta[[nm]] <- list(shape = zm$shape, chunks = zm$chunks, dtype = zm$dtype,
                            compressor = zm$compressor, filters = zm$filters,
                            fill_value = if (is.null(zm$fill_value)) NULL else zm$fill_value,
                            dim_names = .fj(A$dims[i]),
                            attrs = c(list(`_ARRAY_DIMENSIONS` = I(.fj(A$dims[i]))), at))
    if (A$storage[i] == "referenced") {
      r <- mr_refs(con, nm, target)
      if (any(r$present == 1L & is.na(r$path)))
        stop("array '", nm, "' has inline chunks; the kerchunk writer takes only whole-array inline")
      r <- r[r$present == 1L, , drop = FALSE]
      ref_tables[[nm]] <- data.frame(r[.dims(length(zm$shape))], path = r$path,
                                     offset = as.numeric(r$offset), size = as.numeric(r$size))
    } else {
      inline[[nm]] <- list(raw = mr_coord_raw(con, nm))
    }
  }
  blocklist::write_kerchunk_parquet(root, vars_meta, ref_tables, inline = inline,
                                    record_size = record_size)
}

## ---- publish: single-file, read-only friendly ---------------------------------
mr_publish <- function(con) {
  dbExecute(con, "PRAGMA wal_checkpoint(TRUNCATE)")
  dbExecute(con, "PRAGMA journal_mode = DELETE")
  dbExecute(con, "VACUUM")
  invisible(con)
}
