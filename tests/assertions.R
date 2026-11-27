## An applied assertion (py/assertions.py, meta key `assertions`) reaches the
## emitters through mr_array_list: the variable's attributes gain the
## spatial:/proj: keys and their zarr_conventions registrations, and the
## mdim VRT gives the variable an <SRS> with the axis mapping of crs_axes;
## a withdrawn record changes nothing. Run from the repository root:
##   Rscript tests/assertions.R
## Needs DBI, RSQLite, jsonlite, xml2.
source(file.path("R", "mdimrefs.R")); source(file.path("R", "mdimrefs_pipeline.R"))

con <- dbConnect(RSQLite::SQLite(), ":memory:", bigint = "integer64")
mr_init(con)
mr_add_array(con, "sic", dims = c("time", "y", "x"), chunks = c(1L, 4L, 4L), dtype = "|u1",
             shape = c(2L, 8L, 6L), attrs = list(units = "1"))
mr_add_array(con, "sst", dims = c("time", "lat", "lon"), chunks = c(1L, 4L, 4L), dtype = "<f4",
             shape = c(2L, 8L, 6L))
mr_add_array(con, "other", dims = c("time", "y", "x"), chunks = c(1L, 4L, 4L), dtype = "<f4",
             shape = c(2L, 8L, 6L))
rec <- function(var, code, dims, axes, applied = TRUE)
  list(id = var, variable = var, kind = "grid", status = if (applied) "proposed" else "withdrawn",
       digest = "sha256:0", applied = applied, crs_axes = axes,
       asserts = list(`spatial:transform` = c(25000, 0, -75000, 0, -25000, 100000),
                      `spatial:shape` = c(8L, 6L), `spatial:dimensions` = dims,
                      `proj:code` = code))
recs <- list(rec("sic", "EPSG:3412", c("y", "x"), c("x", "y")),
             rec("sst", "EPSG:4326", c("lat", "lon"), c("y", "x")),
             rec("other", "EPSG:3031", c("y", "x"), c("x", "y"), applied = FALSE))
invisible(dbExecute(con, "INSERT INTO meta(key,value) VALUES('assertions',?)",
          params = list(as.character(jsonlite::toJSON(recs, auto_unbox = TRUE, digits = I(17))))))

A <- mr_array_list(con); names(A) <- vapply(A, `[[`, "", "array")
stopifnot(identical(A$sic$attrs$`proj:code`, "EPSG:3412"),
          identical(as.numeric(A$sic$attrs$`spatial:transform`), c(25000, 0, -75000, 0, -25000, 100000)),
          identical(A$sic$attrs$units, "1"),
          length(A$sic$attrs$zarr_conventions) == 2L,
          identical(A$sic$srs$mapping, "3,2"),
          identical(A$sst$srs$mapping, "2,3"),
          is.null(A$other$srs), is.null(A$other$attrs$`proj:code`))
## JSON as the Zarr forms write it: arrays stay arrays
j <- jsonlite::fromJSON(as.character(jsonlite::toJSON(A$sic$attrs, auto_unbox = TRUE)), simplifyVector = FALSE)
stopifnot(length(j$`spatial:transform`) == 6L, length(j$`spatial:shape`) == 2L,
          identical(j$zarr_conventions[[1]]$name, "spatial:"))

f <- tempfile(fileext = ".vrt")
mr_write_mdim_vrt(con, f)
doc <- xml2::read_xml(f)
srs <- function(a) xml2::xml_find_first(doc, sprintf("//Array[@name='%s']/SRS", a))
stopifnot(identical(xml2::xml_text(srs("sic")), "EPSG:3412"),
          identical(xml2::xml_attr(srs("sic"), "dataAxisToSRSAxisMapping"), "3,2"),
          identical(xml2::xml_attr(srs("sst"), "dataAxisToSRSAxisMapping"), "2,3"),
          is.na(srs("other")),
          ## no attribute for the convention objects
          !length(xml2::xml_find_all(doc, "//Attribute[@name='zarr_conventions']")),
          ## the records stay out of the dataset attributes
          !length(xml2::xml_find_all(doc, "/VRTDataset/Group/Attribute[@name='assertions']")))
## summary for the root attributes: no asserts
s <- .assertion_summary(mr_assertions(con))
stopifnot(length(s) == 3L, is.null(s[[1]]$asserts), isTRUE(s[[1]]$applied), isFALSE(s[[3]]$applied))
cat("assertions: ok\n")
