## mr_write_stac: a data variable's fill is its `nodata` in cube:variables
## (datacube v2.3.0), and a render's `nodata` from STAC_RENDERS is kept. Both
## are written so that a float32 fill reads back as the same double: the
## collection is written with 15 significant digits, and -1e20 as float32 is
## -1.0000000200408773e+20, which 15 digits change. A variable with no fill
## has no `nodata`. Run from the repository root:
##   Rscript tests/stac_nodata.R
## Needs DBI, RSQLite, jsonlite, xml2.
source(file.path("R", "mdimrefs.R")); source(file.path("R", "mdimrefs_pipeline.R"))
source(file.path("R", "stac.R"))

f32 <- -1.0000000200408773e20  # float32 -1e20, as a double
stopifnot(identical(unclass(.nodata_json(f32)), "-1.0000000200408773e+20"),
          identical(unclass(.nodata_json("-32768")), "-32768"),
          identical(unclass(.nodata_json(0.1)), "0.1"),
          identical(.nodata_json(NaN), "nan"), identical(.nodata_json(-Inf), "-inf"),
          is.null(.nodata_json(NA)), is.null(.nodata_json(NULL)), is.null(.nodata_json("land")))

con <- dbConnect(RSQLite::SQLite(), ":memory:", bigint = "integer64")
mr_init(con)
invisible(dbExecute(con, "INSERT INTO meta(key,value) VALUES('dataset','nodata-test')"))
mr_add_array(con, "lat", dims = "lat", chunks = 4L, dtype = "<f8", kind = "coord", storage = "affine",
             shape = 4L, affine = list(start = -60.5, step = 1), attrs = list(units = "degrees_north"))
mr_add_array(con, "lon", dims = "lon", chunks = 6L, dtype = "<f8", kind = "coord", storage = "affine",
             shape = 6L, affine = list(start = 100.5, step = 1), attrs = list(units = "degrees_east"))
mr_add_array(con, "eta_t", dims = c("lat", "lon"), chunks = c(4L, 6L), dtype = "<f4", shape = c(4L, 6L),
             fill = f32, attrs = list(`_FillValue` = f32))
mr_add_array(con, "temp", dims = c("lat", "lon"), chunks = c(4L, 6L), dtype = "<i2", shape = c(4L, 6L),
             fill = -32768)
mr_add_array(con, "mask", dims = c("lat", "lon"), chunks = c(4L, 6L), dtype = "|u1", shape = c(4L, 6L))
sid <- mr_add_sources(con, "/data/a.nc", size = 100)
for (a in c("eta_t", "temp", "mask"))
  invisible(dbExecute(con, "INSERT INTO placements VALUES(?,?,?,?,?,?)",
                      params = list(a, sid, a, "[0,0]", "[4,6]", "[0,0]")))

out <- tempfile(); dir.create(out)
Sys.setenv(STAC_RENDERS = paste0(
  '{"eta_t":{"assets":["icechunk"],"rescale":[[-1.8,0.8]],"nodata":-1.0000000200408773e+20,',
  '"colormap_name":"viridis"},"ice":{"assets":["browser"],"nodata":[251,255]}}'))
mr_write_stac(con, out, verbose = FALSE)
Sys.unsetenv("STAC_RENDERS")
file <- file.path(out, "stac", "collection.json")
txt <- paste(readLines(file), collapse = "\n")
coll <- jsonlite::fromJSON(file, simplifyVector = FALSE)

v <- coll$`cube:variables`
stopifnot(identical(v$eta_t$nodata, f32), identical(as.numeric(v$temp$nodata), -32768),
          is.null(v$mask$nodata))
stopifnot(identical(coll$renders$eta_t$nodata, f32),
          identical(as.numeric(unlist(coll$renders$ice$nodata)), c(251, 255)))
## the exact text: 15 significant digits would write -1.00000002004088e+20
stopifnot(lengths(regmatches(txt, gregexpr("-1.0000000200408773e+20", txt, fixed = TRUE))) == 2L,
          !grepl("-1.00000002004088e+20", txt, fixed = TRUE))
stopifnot("https://stac-extensions.github.io/datacube/v2.3.0/schema.json" %in% unlist(coll$stac_extensions))
cat("stac_nodata: ok\n")
