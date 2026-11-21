## Row groups of the flat refs files (mr_write_flat row_group_rows): whole
## steps of the leading dimension, statistics on dim_* and present only, rows
## unchanged. Run from the repository root:
##   Rscript tests/flat_row_groups.R
## Needs DBI, RSQLite, jsonlite, blob, arrow.
source(file.path("R", "mdimrefs.R")); source(file.path("R", "mdimrefs_pipeline.R"))

## 10 one-day sources, shape (10, 5, 7), chunks (1, 2, 3): 9 chunks a step
con <- dbConnect(RSQLite::SQLite(), ":memory:", bigint = "integer64")
mr_init(con)
mr_add_array(con, "sst", dims = c("time", "lat", "lon"), chunks = c(1L, 2L, 3L),
             dtype = "<i2", shape = c(10L, 5L, 7L))
grid <- expand.grid(dim_1 = 0:2, dim_2 = 0:2)
rows <- do.call(rbind, lapply(1:10, function(t) {
  data.frame(source = sprintf("/rdsi/day%05d.nc", t), dim_0 = 0L, grid,
             present = 1L, offset = 1000 * t + 10 * seq_len(nrow(grid)),
             size = 10, info = "COMPRESSION=DEFLATE")
}))
rows$data <- vector("list", nrow(rows))
mr_merge(con, "sst", rows)
sid <- dbGetQuery(con, "SELECT source, source_id FROM sources")
dbWriteTable(con, "placements", data.frame(
  array = "sst", source_id = sid$source_id[match(unique(rows$source), sid$source)],
  source_array = "sst", src_offset = "[0,0,0]", count = "[1,5,7]",
  dest = sprintf("[%d,0,0]", 0:9)), append = TRUE)

view <- mr_refs(con, "sst")
groups <- function(dir) {
  pf <- arrow::ParquetFileReader$create(file.path(dir, "refs_sst.parquet"))
  t <- pf$ReadTable()
  n <- pf$num_row_groups
  d0 <- lapply(seq_len(n) - 1L, function(g) unique(as.vector(pf$ReadRowGroup(g)$dim_0)))
  list(table = as.data.frame(t), n = n, d0 = d0)
}
for (case in list(list(rows = 27, steps = 3), list(rows = 9, steps = 1),
                  list(rows = 1e6, steps = 10))) {
  dir <- tempfile()
  mr_write_flat(con, dir, verbose = FALSE, row_group_rows = case$rows)
  g <- groups(dir)
  ## groups start at multiples of `steps` in dim_0: 10 steps in groups of 3 is
  ## 0-2, 3-5, 6-8, 9
  want <- split(0:9, (0:9) %/% case$steps)
  stopifnot(g$n == length(want),
            all(mapply(function(a, b) setequal(a, b), g$d0, want)))
  ## same rows in the same order as the view
  stopifnot(nrow(g$table) == nrow(view),
            all(g$table$dim_0 == view$dim_0), all(g$table$dim_1 == view$dim_1),
            all(g$table$dim_2 == view$dim_2), all(g$table$offset == view$offset))
}

## writer default (row_group_rows = 0): one group for 90 rows
dir <- tempfile()
mr_write_flat(con, dir, verbose = FALSE, row_group_rows = 0)
stopifnot(groups(dir)$n == 1L)
cat("flat row groups: ok\n")
