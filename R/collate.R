## collate.R -- step 3: harvest + plan -> mdim-refs/0.2 SQLite store.
##
## Rscript collate.R SCAN_DIR PLAN_VRT STORE DATASET [REMAP ...]
##   REMAP is "target|prefix|replacement", repeatable, applied only at publish.
##
## Ingests every harvest fragment (physical layer: rows keyed within source),
## copies the mosaic VRT's SourceSlab/DestSlab into `placements` (plan layer,
## chunk-alignment checked), creates the refs_<array> views (view layer), and
## publishes the file in DELETE journal mode.
args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 4L) stop("usage: collate.R SCAN_DIR PLAN_VRT STORE DATASET [target|prefix|replacement ...]")
here <- dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(here, "mdimrefs.R")); source(file.path(here, "mdimrefs_pipeline.R"))
scan <- args[1]; vrt <- args[2]; db <- args[3]; dataset <- args[4]

t0 <- Sys.time()
unlink(c(db, paste0(db, c("-wal", "-shm"))))
con <- mr_open(db, write = TRUE)
## generator and config come from run.sh (repo commit, config files used)
prov <- Filter(nzchar, list(generator = Sys.getenv("E2E_GENERATOR"), config = Sys.getenv("E2E_CONFIG")))
mr_init(con, meta = c(list(dataset = dataset, created = format(Sys.time(), tz = "UTC", usetz = TRUE)), prov))
message("ingest ", scan)
mr_ingest_scan_dir(con, scan)
message("plan ", vrt)
mr_set_plan(con, mr_plan_vrt(vrt), plan_uri = basename(vrt))  # published beside the store
for (r in args[-(1:4)]) {
  p <- strsplit(r, "|", fixed = TRUE)[[1]]
  stopifnot(length(p) == 3L)
  mr_set_remap(con, p[1], p[2], p[3])
}
for (a in dbGetQuery(con, "SELECT array FROM arrays WHERE storage = 'referenced'")$array) {
  n <- dbGetQuery(con, sprintf('SELECT count(*) AS n, sum(present) AS p FROM "refs_%s"', a))
  message(sprintf("  refs_%s: %s chunks, %s present", a, n$n, n$p))
}
mr_publish(con)
DBI::dbDisconnect(con)
message(sprintf("collate: %s (%.1f MB) in %.1f s", db, file.size(db) / 1e6,
                as.numeric(Sys.time() - t0, units = "secs")))
