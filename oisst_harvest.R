## oisst_harvest.R -- STAGE 1: scan once, locally, into the generic store.
## The published mdim VRT is the source-of-files-to-harvest. We remap its /vsis3
## references to LOCAL /rdsi paths (a projection rule, applied HERE, not stored),
## scan what's present, and record source = the local URI we actually read.
## ----------------------------------------------------------------------------
source("R/store.R")

## 1. the files to harvest, from the daily-updated published VRT
vrt <- tempfile(fileext = ".vrt")
download.file("https://projects.pawsey.org.au/aad-index/oisst/oisst-mdim.vrt", vrt)
srcs <- unique(na.omit(
  stringr::str_match(readLines(vrt), "<SourceFilename[^>]*>([^<]+)</SourceFilename>")[, 2]))

## 2. remap harvest reference (/vsis3 NOAA bucket) -> LOCAL /rdsi ncei mirror.
##    dataset-specific; lives in the harvester, never in the store.
to_local <- function(s) sub(
  "^/vsis3/noaa-cdr-sea-surface-temp-optimum-interpolation-pds/data/v2\\.1/avhrr/",
  "/rdsi/PUBLIC/raad/data/www.ncei.noaa.gov/data/sea-surface-temperature-optimum-interpolation/v2.1/access/avhrr/",
  s)
local <- to_local(srcs)
have  <- fs::file_exists(local)          # leniency: harvest what's actually present
message(sprintf("harvesting %d of %d files present locally", sum(have), length(have)))



## 4. scan available files into the generic store. source = the LOCAL uri read.
con    <- mr_open("oisst-refs.sqlite", write = TRUE); mr_init(con)
arrays <- c("anom", "err", "ice", "sst")                 # data vars; coords via VRT
parsed <- blocklist::parse_mosaic_vrt(vrt)               # per-array A (uniform across files)




for (nm in arrays) mr_declare_array(con, nm, length(parsed$arrays[[nm]]$shape))

harvest_one <- purrr::in_parallel(function(path) {

  ## 3. adapter: blocklist::scan_source_chunks output -> store rows (within-file).
  ##    c1..cN are the source-local chunk coords; offset/size are the bytes. We
  ##    drop `path` -- the source is recorded once in files(), not per chunk.
  .canon_local <- function(r) {
    cc <- grep("^c[0-9]+$", names(r), value = TRUE)
    cc <- cc[order(as.integer(sub("^c", "", cc)))]
    idx <- as.data.frame(as.matrix(r[cc]))
    names(idx) <- paste0("idx", seq_along(cc) - 1L)
    data.frame(idx,
               present = as.integer(!is.na(r$offset)),
               offset  = bit64::as.integer64(r$offset),
               size    = bit64::as.integer64(r$size))
  }

  list(
  source = path,                                         # <- harvest truth
  arrays = setNames(lapply(arrays, function(nm)
    .canon_local(blocklist::scan_source_chunks(
      path, paste0("/", nm), path, parsed$arrays[[nm]], contiguous = FALSE))), arrays))
}, arrays = arrays, parsed = parsed)

library(mirai)
daemons(8)
## (parallelize the scan; merge serially in batches -- the single-writer boundary)
batch <- purrr::map(local[have], harvest_one)
daemons(0)
mr_merge(con, batch)
DBI::dbDisconnect(con)
## oisst-refs.sqlite is now STORE #1: source + per-file chunks, dataset-agnostic.
