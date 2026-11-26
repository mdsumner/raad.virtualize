## Overview levels in the multidimensional VRT (mr_write_mdim_vrt): an array
## that other arrays name in overview_of (decision 0006) lists them in
## <Overviews>, finest first, by full name; a level of an array not in the
## VRT is left out of every <Overviews>. Run from the repository root:
##   Rscript tests/mdim_vrt_overviews.R
## Needs DBI, RSQLite, jsonlite, blob, xml2.
source(file.path("R", "mdimrefs.R")); source(file.path("R", "mdimrefs_pipeline.R"))

con <- dbConnect(RSQLite::SQLite(), ":memory:", bigint = "integer64")
mr_init(con)
lvl <- function(of, f) list(overview_of = of, overview_factor = c(f, f), overview_resampling = "AVERAGE")
mr_add_array(con, "z", dims = c("y", "x"), chunks = c(4L, 4L), dtype = "<f4", shape = c(16L, 16L))
## levels added coarsest first: the VRT lists them finest first
mr_add_array(con, "z_x4", dims = c("y_x4", "x_x4"), chunks = c(4L, 4L), dtype = "<f4",
             shape = c(4L, 4L), attrs = lvl("z", 4))
mr_add_array(con, "z_x2", dims = c("y_x2", "x_x2"), chunks = c(4L, 4L), dtype = "<f4",
             shape = c(8L, 8L), attrs = lvl("z", 2))
## an array in a group, and its level
mr_add_array(con, "g/t", dims = c("y", "x"), chunks = c(4L, 4L), dtype = "<i2", shape = c(16L, 16L))
mr_add_array(con, "g/t_x2", dims = c("y_x2", "x_x2"), chunks = c(4L, 4L), dtype = "<i2",
             shape = c(8L, 8L), attrs = lvl("g/t", 2))
## a level of an array the store does not have, and an array with no levels
mr_add_array(con, "q_x2", dims = c("y_x2", "x_x2"), chunks = c(4L, 4L), dtype = "<f4",
             shape = c(8L, 8L), attrs = lvl("q", 2))
mr_add_array(con, "w", dims = c("y", "x"), chunks = c(4L, 4L), dtype = "<f4", shape = c(16L, 16L))

f <- tempfile(fileext = ".vrt")
mr_write_mdim_vrt(con, f)
doc <- xml2::read_xml(f)
ovr <- function(path) xml2::xml_text(xml2::xml_find_all(doc, paste0(path, "/Overviews/ArrayFullName")))

stopifnot(identical(ovr("//Group[@name='/']/Array[@name='z']"), c("/z_x2", "/z_x4")))
stopifnot(identical(ovr("//Group[@name='g']/Array[@name='t']"), "/g/t_x2"))
stopifnot(length(ovr("//Array[@name='w']")) == 0L)
stopifnot(!"/q_x2" %in% xml2::xml_text(xml2::xml_find_all(doc, "//ArrayFullName")))
## only base arrays carry the element
stopifnot(length(xml2::xml_find_all(doc, "//Overviews")) == 2L)
cat("mdim_vrt_overviews: ok\n")
