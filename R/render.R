## render.R -- step 4: store -> flat refs store, MDIM VRT, kerchunk Parquet.
##
## Rscript render.R STORE OUT_DIR [KERCHUNK_TARGET] [VRT_TARGET]
##   OUT_DIR/flat/       arrays.json + refs_<array>.parquet + sources.parquet
##   OUT_DIR/mdim.vrt    GDAL multidimensional VRT rebuilt from the store
##   OUT_DIR/kerchunk/   kerchunk Parquet (fsspec layout; blocklist's writer, vendored)
## KERCHUNK_TARGET, VRT_TARGET: remap targets ("" = verbatim sources).
## The Icechunk leg is py/render_icechunk.py, reading OUT_DIR/flat.
args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2L) stop("usage: render.R STORE OUT_DIR [KERCHUNK_TARGET] [VRT_TARGET]")
here <- dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(here, "mdimrefs.R")); source(file.path(here, "mdimrefs_pipeline.R"))
db <- args[1]; out <- args[2]
tg <- function(x) if (is.na(x) || !nzchar(x)) NULL else x
kt <- tg(args[3]); vt <- tg(args[4])
dir.create(out, recursive = TRUE, showWarnings = FALSE)
con <- mr_open(db)

tm <- function(label, expr) {
  t0 <- Sys.time(); force(expr)
  message(sprintf("%s: %.1f s", label, as.numeric(Sys.time() - t0, units = "secs")))
}
tm("flat refs store", mr_write_flat(con, file.path(out, "flat")))
tm("mdim VRT", mr_write_mdim_vrt(con, file.path(out, "mdim.vrt"), target = vt))
tm("kerchunk Parquet", mr_write_kerchunk_parquet(con, file.path(out, "kerchunk"), target = kt))
DBI::dbDisconnect(con)
