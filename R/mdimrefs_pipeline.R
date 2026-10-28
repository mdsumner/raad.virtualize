## mdimrefs_pipeline.R -- additions to mdimrefs.R for the pipeline (run.sh).
## ----------------------------------------------------------------------------
## - mr_ingest_scan_dir(): ingest a harvest.py output directory (one Parquet
##   fragment per source and array), source by source, so a large scan is
##   merged without holding every row in memory.
## - mr_write_flat(): the flat refs store ("parquet-zarr-lite"): arrays.json
##   plus refs_<array>.parquet per referenced array, the form wxylib wxy-refs
##   reads, plus sources.parquet (the export gap noted in the wxylib review).
## - mr_write_mdim_vrt(): render the store back to a GDAL multidimensional
##   VRT, the plan rebuilt from `placements`, `sources` and `arrays`, with
##   paths remapped for a chosen target and the CF attributes the mosaic VRT
##   drops (time units) restored.
##
## Needs mdimrefs.R sourced first. Dependencies: DBI, RSQLite, jsonlite, xml2,
## arrow, blob.
## ----------------------------------------------------------------------------

.fjl <- function(x) if (is.null(x) || is.na(x)) NULL else jsonlite::fromJSON(x, simplifyVector = FALSE)
.zobj <- function(x) if (length(x)) x else stats::setNames(list(), character(0))

## ---- ingest a harvest.py directory --------------------------------------------
mr_ingest_scan_dir <- function(con, dir, verbose = TRUE) {
  sj <- list.files(file.path(dir, "sources"), pattern = "[.]json$", full.names = TRUE)
  src <- do.call(rbind, lapply(sj, function(f) {
    x <- jsonlite::fromJSON(f)
    data.frame(source = x$source, size = x$size %||% NA, mtime = x$mtime %||% NA,
               key = sub("[.]json$", "", basename(f)), stringsAsFactors = FALSE)
  }))
  mr_add_sources(con, src$source, src$size, src$mtime)
  ## gdal mdim mosaic checks nodata across sources but takes scale and offset
  ## from the first: a dataset whose packing changes between files cannot be
  ## one virtual array, so stop here (sidecars from harvest.py >= 2026-10-21)
  pk <- lapply(sj, function(f) jsonlite::fromJSON(f, simplifyVector = FALSE)$packing)
  pk <- Filter(Negate(is.null), pk)
  if (length(pk)) for (nm in names(pk[[1]])) {
    u <- unique(vapply(pk, function(p) .j(p[[nm]]), ""))
    if (length(u) > 1L) stop(sprintf("array '%s': scale/offset/nodata differ between sources: %s",
                                     nm, paste(u, collapse = " | ")))
  }
  meta <- jsonlite::fromJSON(file.path(dir, "arrays.json"), simplifyVector = FALSE)
  for (nm in names(meta)) {
    m <- meta[[nm]]
    if (!isTRUE(m$scanned)) next
    frags <- file.path(dir, paste0("chunks_", nm), paste0(src$key, ".parquet"))
    frags <- frags[file.exists(frags)]
    ## one codec per array, checked over every fragment before anything is written
    info <- unique(unlist(lapply(frags, function(f) {
      x <- arrow::read_parquet(f, col_select = c("present", "info"))
      unique(stats::na.omit(x$info[x$present == 1L]))
    })))
    if (length(info) > 1L) stop(sprintf(
      "array '%s': chunks disagree on codec (%s); not virtualizable as one array",
      nm, paste(info, collapse = " | ")))
    .check_fill(nm, m$attrs %||% list(), m$nodata %||% NA)
    mr_add_array(con, nm, dims = unlist(m$dims), chunks = unlist(m$chunks),
                 dtype = m$dtype, fill = m$nodata %||% NA,
                 codec = if (length(info)) mr_codec_from_info(info, m$dtype, unlist(m$chunks)) else NULL,
                 attrs = .cf_attrs(m))
    t0 <- Sys.time(); n <- 0
    for (f in frags) {
      rows <- as.data.frame(arrow::read_parquet(f))
      n <- n + mr_merge(con, nm, rows)
    }
    if (verbose) message(sprintf("  %s: %d rows from %d sources in %.1f s", nm, n,
                                 length(frags), as.numeric(Sys.time() - t0, units = "secs")))
  }
  coords <- Filter(function(m) !isTRUE(m$scanned), meta)
  dbExecute(con, "INSERT INTO meta(key,value) VALUES('coord_attrs',?)
                  ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            params = list(.j(lapply(coords, .cf_attrs))))
  invisible(con)
}

## ---- array rows as plain R lists (JSON-ready) -------------------------------------
.coord_values <- function(a) {
  if (is.null(a$values[[1]])) return(NULL)
  sz <- as.integer(sub("^.{2}", "", a$dtype)); fl <- substr(a$dtype, 2, 2) == "f"
  readBin(a$values[[1]], if (fl) "double" else "integer", n = prod(.fj(a$shape)), size = sz,
          endian = if (startsWith(a$dtype, ">")) "big" else "little")
}

mr_array_list <- function(con) {
  A <- mr_arrays(con)
  lapply(seq_len(nrow(A)), function(i) {
    a <- A[i, , drop = FALSE]
    list(array = a$array, kind = a$kind, storage = a$storage,
         dims = I(unlist(.fjl(a$dims))), shape = I(as.integer(unlist(.fjl(a$shape)))),
         chunks = I(as.integer(unlist(.fjl(a$chunks)))), dtype = a$dtype,
         fill = if (is.na(a$fill)) NULL else a$fill,
         codec = .fjl(a$codec), attrs = .zobj(.fjl(a$attrs)), affine = .fjl(a$affine),
         values = { v <- .coord_values(a); if (is.null(v)) NULL else I(v) })
  })
}

## ---- the flat refs store ----------------------------------------------------------
## Paths are written verbatim (as scanned) and the remap rules travel in
## arrays.json; a reader applies the target it wants (wxy-refs does).
mr_write_flat <- function(con, dir, verbose = TRUE, rows_per_chunk = 1e6) {
  dir.create(dir, recursive = TRUE, showWarnings = FALSE)
  arrays <- mr_array_list(con)
  for (k in seq_along(arrays)) {
    a <- arrays[[k]]
    if (a$storage != "referenced") next
    t0 <- Sys.time()
    r <- mr_refs(con, a$array)
    ## what a reader can know before reading: grid size, chunks referenced,
    ## chunks absent (present = 0 rows, or no row at all), referenced bytes
    grid <- prod(ceiling(a$shape / a$chunks)); np <- sum(as.integer(r$present) == 1L)
    arrays[[k]]$summary <- list(chunks = grid, present = np, absent = grid - np,
                                bytes = sum(as.numeric(r$size[as.integer(r$present) == 1L]), na.rm = TRUE))
    n <- length(a$dims)
    ## columns are built as chunked arrays of `rows_per_chunk` rows: a single
    ## utf8 array holds at most 2 GB, and the 22.8M paths of the GHRSST MUR
    ## series are 3.3 GB
    idx <- split(seq_len(nrow(r)), (seq_len(nrow(r)) - 1L) %/% rows_per_chunk)
    ch <- function(x, f) do.call(arrow::chunked_array, unname(lapply(idx, function(i) f(x[i]))))
    i64 <- function(x) arrow::Array$create(as.numeric(x))$cast(arrow::int64())
    utf8 <- function(x) arrow::Array$create(as.character(x), type = arrow::utf8())
    cols <- lapply(.dims(n), function(k) ch(r[[k]], i64))
    names(cols) <- .dims(n)
    tbl <- do.call(arrow::arrow_table, c(cols, list(
      present = ch(r$present, function(x) arrow::Array$create(as.integer(x))$cast(arrow::int8())),
      path    = ch(r$path, utf8),
      offset  = ch(r$offset, i64),
      size    = ch(r$size, i64),
      info    = ch(r$info, utf8),
      data    = ch(unclass(r$data), function(x) arrow::Array$create(
        lapply(x, function(v) if (is.null(v)) NULL else as.raw(v)), type = arrow::binary())))))
    arrow::write_parquet(tbl, file.path(dir, sprintf("refs_%s.parquet", a$array)),
                         compression = .pq_codec())
    if (verbose) message(sprintf("  refs_%s.parquet: %d rows in %.1f s", a$array, nrow(r),
                                 as.numeric(Sys.time() - t0, units = "secs")))
  }
  s <- dbReadTable(con, "sources")
  arrow::write_parquet(arrow::arrow_table(
    source_id = arrow::Array$create(as.numeric(s$source_id))$cast(arrow::int64()),
    source = s$source,
    size  = arrow::Array$create(as.numeric(s$size))$cast(arrow::int64()),
    mtime = arrow::Array$create(as.numeric(s$mtime))$cast(arrow::int64()),
    etag  = arrow::Array$create(as.character(s$etag), type = arrow::utf8())),
    file.path(dir, "sources.parquet"))
  m <- dbReadTable(con, "meta"); rm <- dbReadTable(con, "remap")
  doc <- list(format_version = MR_FORMAT,
              meta = .zobj(as.list(stats::setNames(m$value, m$key))[setdiff(m$key, MR_META_JSON)]),
              dimensions = .zobj(mr_dimensions(con)),
              arrays = arrays,
              remap = lapply(seq_len(nrow(rm)), function(i) as.list(rm[i, ])))
  writeLines(jsonlite::toJSON(doc, auto_unbox = TRUE, digits = I(17), null = "null",
                              na = "null", pretty = TRUE),
             file.path(dir, "arrays.json"))
  invisible(dir)
}

## ---- remap in R (same rule as mr_view_sql: longest matching prefix) -------------
mr_remap <- function(con, path, target = NULL) {
  if (is.null(target)) return(path)
  rm <- dbGetQuery(con, "SELECT prefix, replacement FROM remap WHERE target = ?
                         ORDER BY length(prefix) DESC", params = list(target))
  out <- path; done <- rep(FALSE, length(path))
  for (i in seq_len(nrow(rm))) {
    hit <- !done & startsWith(path, rm$prefix[i])
    out[hit] <- paste0(rm$replacement[i], substring(path[hit], nchar(rm$prefix[i]) + 1L))
    done <- done | hit
  }
  out
}

## ---- render: GDAL multidimensional VRT ---------------------------------------------
.numpy_gdal <- stats::setNames(names(.gdal_numpy), sub("^[<>|]", "", .gdal_numpy))
.gdal_type <- function(dtype) .numpy_gdal[[sub("^[<>|]", "", dtype)]]
.num <- function(x) sprintf("%.17g", as.numeric(x))
## zstd where this arrow build has it (some builds lack it), else snappy
.pq_codec <- function() if (arrow::codec_is_available("zstd")) "zstd" else "snappy"

.lifted <- c("units", "_FillValue", "scale_factor", "add_offset", "missing_value")

.vrt_attrs <- function(node, attrs) {
  for (k in names(attrs)) {
    if (k %in% .lifted) next
    v <- unlist(attrs[[k]])
    if (is.null(v)) next
    at <- xml2::xml_add_child(node, "Attribute", name = k)
    xml2::xml_add_child(at, "DataType",
      if (is.character(v)) "String" else if (is.integer(v)) "Int32" else "Float64")
    for (x in v) xml2::xml_add_child(at, "Value", if (is.character(x)) x else .num(x))
  }
}

.vrt_lifted <- function(node, a) {
  at <- a$attrs
  if (!is.null(at$units)) xml2::xml_add_child(node, "Unit", at$units)
  if (!is.null(a$fill)) xml2::xml_add_child(node, "NoDataValue", a$fill)
  if (!is.null(at$add_offset)) xml2::xml_add_child(node, "Offset", .num(at$add_offset))
  if (!is.null(at$scale_factor)) xml2::xml_add_child(node, "Scale", .num(at$scale_factor))
}

mr_write_mdim_vrt <- function(con, file, target = NULL) {
  arrays <- mr_array_list(con)
  names(arrays) <- vapply(arrays, `[[`, "", "array")
  doc <- xml2::xml_new_root("VRTDataset")
  g <- xml2::xml_add_child(doc, "Group", name = "/")
  ## dimensions: every dim of every array, sized from the global shapes, with
  ## type and direction from the plan
  dims <- mr_dimensions(con)
  dsz <- list()
  for (a in arrays) for (i in seq_along(a$dims)) dsz[[a$dims[i]]] <- a$shape[i]
  for (d in names(dsz)) {
    attrs <- c(name = d, size = dsz[[d]])
    attrs <- c(attrs, unlist(dims[[d]]))
    if (!is.null(arrays[[d]]) && arrays[[d]]$kind == "coord") attrs <- c(attrs, indexingVariable = d)
    do.call(xml2::xml_add_child, c(list(g, "Dimension"), as.list(attrs)))
  }
  m <- dbReadTable(con, "meta")
  m <- m[!m$key %in% MR_META_JSON, , drop = FALSE]
  .vrt_attrs(g, as.list(stats::setNames(m$value, m$key)))  # dataset, generator, ...
  for (a in arrays[order(vapply(arrays, `[[`, "", "kind") != "coord")]) {
    node <- xml2::xml_add_child(g, "Array", name = a$array)
    xml2::xml_add_child(node, "DataType", .gdal_type(a$dtype))
    for (d in a$dims) xml2::xml_add_child(node, "DimensionRef", ref = d)
    if (a$storage == "referenced")
      xml2::xml_add_child(node, "BlockSize", paste(a$chunks, collapse = ","))
    .vrt_lifted(node, a)
    if (a$storage == "affine") {
      xml2::xml_add_child(node, "RegularlySpacedValues", start = .num(a$affine$start),
                          increment = .num(a$affine$step))
    } else if (a$storage == "inline") {
      xml2::xml_add_child(node, "InlineValues", paste(.num(a$values), collapse = " "),
                          offset = "0", count = length(a$values))
    } else {
      P <- dbGetQuery(con, "SELECT s.source, p.source_array, p.src_offset, p.count, p.dest
                            FROM placements p JOIN sources s USING (source_id)
                            WHERE p.array = ?", params = list(a$array))
      ## sources in destination order, as the mosaic writes them
      de <- lapply(P$dest, .fj)
      P <- P[do.call(order, as.data.frame(do.call(rbind, de))), , drop = FALSE]
      P$path <- mr_remap(con, P$source, target)
      for (i in seq_len(nrow(P))) {
        s <- xml2::xml_add_child(node, "Source")
        xml2::xml_add_child(s, "SourceFilename", P$path[i])
        cn <- .fj(P$count[i])
        if (startsWith(P$source_array[i], "band:")) {
          ## a raster band, given a leading length-1 axis (the vrtstack form)
          xml2::xml_add_child(s, "SourceBand", sub("^band:", "", P$source_array[i]))
          xml2::xml_add_child(s, "SourceTranspose",
                              paste(c(-1L, seq_len(length(cn) - 1L) - 1L), collapse = ","))
          ## the extent, so GDAL opens only the sources a read touches
          ## (without it every source is opened to learn its shape)
          xml2::xml_add_child(s, "SourceSlab", offset = paste(rep(0L, length(cn)), collapse = ","),
                              count = paste(cn, collapse = ","),
                              step = paste(rep(1L, length(cn)), collapse = ","))
        } else {
          xml2::xml_add_child(s, "SourceArray", paste0("/", P$source_array[i]))
          xml2::xml_add_child(s, "SourceSlab", offset = paste(.fj(P$src_offset[i]), collapse = ","),
                              count = paste(cn, collapse = ","),
                              step = paste(rep(1L, length(cn)), collapse = ","))
        }
        xml2::xml_add_child(s, "DestSlab", offset = paste(.fj(P$dest[i]), collapse = ","))
      }
    }
    .vrt_attrs(node, a$attrs)
  }
  xml2::write_xml(doc, file, options = c("format", "no_declaration"))
  invisible(file)
}

## ---- render: kerchunk Parquet ------------------------------------------------------
## blocklist::write_kerchunk_parquet (hypertidy/blocklist 9f5ede9), vendored
## with one change: .zmetadata is written with 17 significant digits. Upstream
## calls jsonlite::toJSON() with its default digits = 4, which is what turned
## BRAN's scale_factor 0.007782219909131527 into 0.0078 in the R-built index.
## Vendoring also drops the rhdf5 dependency for this example. Upstream fix:
## add `digits = I(17)` to the toJSON() call that writes .zmetadata.
.zfill <- function(x) {
  if (is.null(x) || length(x) == 0) return(NULL)
  x <- x[[1]]
  if (is.numeric(x)) {
    if (is.nan(x))      return(jsonlite::unbox("NaN"))
    if (is.infinite(x)) return(jsonlite::unbox(if (x > 0) "Infinity" else "-Infinity"))
    if (is.na(x))       return(NULL)
  }
  jsonlite::unbox(x)
}

mr_kerchunk_writer <- function(root, vars_meta, ref_tables, inline = list(),
                               record_size = 100000L, root_attrs = list()) {
  unbox <- jsonlite::unbox
  if (dir.exists(root)) unlink(root, recursive = TRUE)
  dir.create(root, recursive = TRUE)
  metadata <- list(".zgroup" = list(zarr_format = unbox(2L)), ".zattrs" = .zobj(root_attrs))
  for (v in names(vars_meta)) {
    info <- vars_meta[[v]]; is_inline <- v %in% names(inline)
    metadata[[paste0(v, "/.zarray")]] <- list(
      zarr_format = unbox(2L),
      shape  = I(as.integer(info$shape)),
      chunks = if (is_inline) I(as.integer(info$shape)) else I(as.integer(info$chunks)),
      dtype  = unbox(info$dtype),
      compressor = if (is_inline) NULL else info$compressor,
      filters    = if (is_inline) NULL else info$filters,
      fill_value = .zfill(info$fill_value),
      order = unbox("C"), dimension_separator = unbox("."))
    metadata[[paste0(v, "/.zattrs")]] <- .zobj(info$attrs)
    counts <- if (is_inline) rep(1L, length(info$shape)) else
      as.integer(ceiling(info$shape / info$chunks))
    n_chunks <- prod(counts)
    path <- rep(NA_character_, n_chunks); offset <- numeric(n_chunks)
    size <- numeric(n_chunks); raw <- vector("list", n_chunks)
    if (is_inline) {
      raw[[1L]] <- inline[[v]]$raw
    } else {
      df <- ref_tables[[v]]; ndim <- length(info$shape)
      coords <- as.matrix(df[, seq_len(ndim), drop = FALSE])
      stride <- rev(cumprod(rev(c(counts[-1], 1L))))
      fi <- as.numeric(coords %*% stride) + 1
      path[fi] <- df$path; offset[fi] <- as.double(df$offset); size[fi] <- as.double(df$size)
    }
    vdir <- file.path(root, v); dir.create(vdir, recursive = TRUE)
    for (p in seq_len(ceiling(n_chunks / record_size))) {
      idx <- ((p - 1) * record_size + 1):min(p * record_size, n_chunks)
      pad <- record_size - length(idx)
      tbl <- arrow::arrow_table(
        path   = c(path[idx], rep(NA_character_, pad)),
        offset = c(offset[idx], numeric(pad)),
        size   = c(size[idx], numeric(pad)),
        raw    = arrow::Array$create(c(raw[idx], vector("list", pad)), type = arrow::binary()))
      tbl$offset <- tbl$offset$cast(arrow::int64())
      tbl$size   <- tbl$size$cast(arrow::int64())
      arrow::write_parquet(tbl, file.path(vdir, sprintf("refs.%d.parq", p - 1L)))
    }
  }
  zmeta <- list(metadata = metadata, record_size = unbox(as.integer(record_size)))
  writeLines(jsonlite::toJSON(zmeta, auto_unbox = TRUE, null = "null", na = "null",
                              digits = I(17)),
             file.path(root, ".zmetadata"))
  invisible(root)
}

## mdimrefs.R's writer, pointed at the vendored function above. The codec
## and attrs come from the store's JSON parsed as lists, so single-element
## arrays and nested filters keep their shape.
mr_write_kerchunk_parquet <- function(con, root, target = NULL, record_size = 100000L) {
  arrays <- mr_array_list(con); vars_meta <- list(); ref_tables <- list(); inline <- list()
  for (a in arrays) {
    nm <- a$array; ref <- a$storage == "referenced"
    at <- a$attrs; at[["_FillValue"]] <- NULL
    if (!is.null(a$fill)) at[["_FillValue"]] <- .fill_json(a$fill)
    vars_meta[[nm]] <- list(shape = a$shape, chunks = a$chunks, dtype = a$dtype,
                            compressor = if (ref) a$codec$compressor else NULL,
                            filters = if (ref) a$codec$filters else NULL,
                            fill_value = if (is.null(a$fill)) NULL else .fill_json(a$fill),
                            attrs = c(list(`_ARRAY_DIMENSIONS` = I(a$dims)), at))
    if (ref) {
      r <- mr_refs(con, nm, target)
      if (any(r$present == 1L & is.na(r$path)))
        stop("array '", nm, "' has inline chunks; this writer takes only whole-array inline")
      r <- r[r$present == 1L, , drop = FALSE]
      ref_tables[[nm]] <- data.frame(r[.dims(length(a$shape))], path = r$path,
                                     offset = as.numeric(r$offset), size = as.numeric(r$size))
    } else {
      inline[[nm]] <- list(raw = mr_coord_raw(con, nm))
    }
  }
  m <- dbReadTable(con, "meta")
  m <- m[!m$key %in% MR_META_JSON, , drop = FALSE]
  mr_kerchunk_writer(root, vars_meta, ref_tables, inline = inline, record_size = record_size,
                     root_attrs = as.list(stats::setNames(m$value, m$key)))
}
