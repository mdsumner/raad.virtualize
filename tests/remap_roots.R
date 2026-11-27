## Named remap roots (byterefs decision 0014): a rule may carry `root`, a name
## of [A-Za-z0-9-]+; rules of one prefix that name it agree; arrays.json
## writes `root` only on the rules that have one; a store from before 0014
## (no root column) takes a named rule. Run from the repository root:
##   Rscript tests/remap_roots.R
## Needs DBI, RSQLite, jsonlite, arrow.
source(file.path("R", "mdimrefs.R")); source(file.path("R", "mdimrefs_pipeline.R"))

con <- dbConnect(RSQLite::SQLite(), ":memory:", bigint = "integer64")
mr_init(con)
mr_set_remap_rules(con, c(
  "public|/vsicurl/https://|https://",
  "public|/g/data/gb6/|https://thredds.nci.org.au/thredds/fileServer/gb6/|bran2023",
  "gdal|/g/data/gb6/|/vsicurl/https://thredds.nci.org.au/thredds/fileServer/gb6/|bran2023"))
rm <- dbReadTable(con, "remap")
stopifnot(identical(sort(rm$root[rm$prefix == "/g/data/gb6/"]), c("bran2023", "bran2023")),
          is.na(rm$root[rm$prefix == "/vsicurl/https://"]))

## disagreeing names, a bad name and a bad rule shape stop
fails <- function(expr) inherits(try(expr, silent = TRUE), "try-error")
stopifnot(fails(mr_set_remap(con, "s3", "/g/data/gb6/", "s3://x/gb6/", "gb6")),
          fails(mr_set_remap(con, "s3", "/g/data/gb6/", "s3://x/gb6/", "bran 2023")),
          fails(mr_set_remap_rules(con, "public|/g/data/gb6/")))
## a rule with no root beside a named one is allowed, and replacing a rule keeps one row
mr_set_remap(con, "local", "/g/data/gb6/", "/g/data/gb6/")
mr_set_remap(con, "public", "/g/data/gb6/", "https://thredds.nci.org.au/thredds/fileServer/gb6/", "bran2023")
stopifnot(nrow(dbReadTable(con, "remap")) == 4L)

## arrays.json: root on the named rules only
mr_add_array(con, "eta_t", dims = c("Time", "y", "x"), chunks = c(1L, 2L, 2L),
             dtype = "<f4", shape = c(1L, 2L, 2L))
rows <- data.frame(source = "/g/data/gb6/BRAN/BRAN2023/daily/ocean_eta_t_2010_01.nc",
                   dim_0 = 0L, dim_1 = 0L, dim_2 = 0L, present = 1L, offset = 100,
                   size = 16, info = "")
rows$data <- vector("list", 1L)
mr_merge(con, "eta_t", rows)
sid <- dbGetQuery(con, "SELECT source_id FROM sources")$source_id
dbWriteTable(con, "placements", data.frame(array = "eta_t", source_id = sid, source_array = "eta_t",
                                           src_offset = "[0,0,0]", count = "[1,2,2]", dest = "[0,0,0]"),
             append = TRUE)
dir <- tempfile()
mr_write_flat(con, dir, verbose = FALSE)
doc <- jsonlite::fromJSON(file.path(dir, "arrays.json"), simplifyVector = FALSE)
roots <- vapply(doc$remap, function(r) if (is.null(r$root)) "" else r$root, "")
pref <- vapply(doc$remap, function(r) r$prefix, "")
tgt <- vapply(doc$remap, function(r) r$target, "")
stopifnot(all(roots[pref == "/g/data/gb6/" & tgt != "local"] == "bran2023"),
          roots[tgt == "local"] == "", roots[pref == "/vsicurl/https://"] == "")

## a store from before 0014: no root column; a named rule adds it
old <- dbConnect(RSQLite::SQLite(), ":memory:")
dbExecute(old, "CREATE TABLE remap(target TEXT NOT NULL, prefix TEXT NOT NULL,
                replacement TEXT NOT NULL, PRIMARY KEY (target, prefix)) WITHOUT ROWID")
dbExecute(old, "INSERT INTO remap VALUES('public', '/g/data/gb6/', 'https://h/gb6/')")
mr_set_remap_rules(old, "gdal|/g/data/gb6/|/vsicurl/https://h/gb6/|bran2023")
r2 <- dbReadTable(old, "remap")
stopifnot("root" %in% names(r2), identical(r2$root[r2$target == "gdal"], "bran2023"),
          is.na(r2$root[r2$target == "public"]))
cat("PASS tests/remap_roots.R\n")
