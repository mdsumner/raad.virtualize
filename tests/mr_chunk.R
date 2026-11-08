## Placement-first chunk lookup (mr_chunk_sql, mr_chunks, mr_chunk) against
## the view (mr_refs). Run from the repository root:
##   Rscript tests/mr_chunk.R
## Needs DBI, RSQLite, jsonlite, blob.
source(file.path("R", "mdimrefs.R"))

## a store with `nsrc` sources of one day each, plus one two-day source read
## from its second day; shape (nsrc + 1, 5, 7), chunks (1, 2, 3) so y and x
## end in partial chunks
make_store <- function(nsrc) {
  con <- dbConnect(RSQLite::SQLite(), ":memory:", bigint = "integer64")
  mr_init(con)
  mr_add_array(con, "sst", dims = c("time", "lat", "lon"), chunks = c(1L, 2L, 3L),
               dtype = "<i2", shape = c(nsrc + 1L, 5L, 7L))
  grid <- expand.grid(dim_1 = 0:2, dim_2 = 0:2)
  rows <- do.call(rbind, lapply(seq_len(nsrc), function(t) {
    data.frame(source = sprintf("/rdsi/day%05d.nc", t), dim_0 = 0L, grid,
               present = 1L, offset = 1000 * t + 10 * seq_len(nrow(grid)),
               size = 10, info = "COMPRESSION=DEFLATE")
  }))
  ## one absent chunk and one inline chunk
  rows$present[2] <- 0L; rows$offset[2] <- NA; rows$size[2] <- NA
  rows$offset[3] <- NA; rows$size[3] <- NA
  rows$data <- vector("list", nrow(rows)); rows$data[[3]] <- as.raw(1:4)
  two <- data.frame(source = "/rdsi/twoday.nc", dim_0 = rep(0:1, each = nrow(grid)),
                    rbind(grid, grid), present = 1L,
                    offset = 5e6 + seq_len(2 * nrow(grid)), size = 20,
                    info = "COMPRESSION=DEFLATE")
  two$data <- vector("list", nrow(two))
  mr_merge(con, "sst", rows); mr_merge(con, "sst", two)
  sid <- dbGetQuery(con, "SELECT source, source_id FROM sources")
  pl <- data.frame(array = "sst",
                   source_id = sid$source_id[match(c(unique(rows$source), "/rdsi/twoday.nc"), sid$source)],
                   source_array = "sst",
                   src_offset = c(rep("[0,0,0]", nsrc), "[1,0,0]"),
                   count = "[1,5,7]",
                   dest = sprintf("[%d,0,0]", c(seq_len(nsrc) - 1L, nsrc)))
  dbWriteTable(con, "placements", pl, append = TRUE)
  mr_set_remap(con, "public", "/rdsi/", "https://example.org/data/")
  con
}

same <- function(a, b) {
  a$k <- NULL; b$k <- NULL; rownames(a) <- rownames(b) <- NULL
  ## RSQLite types an all-NULL column as logical; compare values, not that
  for (nm in names(a)) if (is.logical(a[[nm]]) && all(is.na(a[[nm]]))) a[[nm]] <- b[[nm]][NA_integer_][seq_len(nrow(a))]
  for (nm in names(b)) if (is.logical(b[[nm]]) && all(is.na(b[[nm]]))) b[[nm]] <- a[[nm]][NA_integer_][seq_len(nrow(b))]
  isTRUE(all.equal(as.data.frame(a), as.data.frame(b), check.attributes = FALSE))
}

con <- make_store(4L)
for (target in list(NULL, "public")) {
  view <- mr_refs(con, "sst", target)
  stopifnot(nrow(view) == 5L * 9L)
  ## every key the view holds, one at a time
  for (r in seq_len(nrow(view))) {
    key <- unlist(view[r, c("dim_0", "dim_1", "dim_2")])
    got <- mr_chunk(con, "sst", key, target)
    stopifnot(nrow(got) == 1L, same(got, view[r, , drop = FALSE]))
  }
  ## all keys in one batch, in reverse order: rows come back in request order
  keys <- as.matrix(view[rev(seq_len(nrow(view))), c("dim_0", "dim_1", "dim_2")])
  got <- mr_chunks(con, "sst", keys, target)
  stopifnot(identical(got$k, seq_len(nrow(keys))),
            same(got, view[rev(seq_len(nrow(view))), , drop = FALSE]))
}
## the two-day source is read from its second day
stopifnot(all(mr_chunk(con, "sst", c(4, 0, 0))$offset == 5e6 + 10))
## keys outside the array give no rows; a mixed batch keeps the found ones
stopifnot(nrow(mr_chunk(con, "sst", c(5, 0, 0))) == 0L,
          nrow(mr_chunk(con, "sst", c(0, 3, 0))) == 0L)
got <- mr_chunks(con, "sst", rbind(c(9, 9, 9), c(1, 1, 1), c(-1, 0, 0)))
stopifnot(identical(got$k, 2L))
dbDisconnect(con)

## spatial tiles: two sources side by side on the last axis, so the slab
## starts differ only there
con <- dbConnect(RSQLite::SQLite(), ":memory:", bigint = "integer64")
mr_init(con)
mr_add_array(con, "z", dims = c("y", "x"), chunks = c(2L, 3L), dtype = "<f4", shape = c(2L, 6L))
mr_merge(con, "z", data.frame(source = c("/a.tif", "/b.tif"), dim_0 = 0L, dim_1 = 0L,
                              present = 1L, offset = c(100, 200), size = 50, info = ""))
sid <- dbGetQuery(con, "SELECT source, source_id FROM sources")
dbWriteTable(con, "placements", data.frame(array = "z",
  source_id = sid$source_id[match(c("/a.tif", "/b.tif"), sid$source)], source_array = "band:1",
  src_offset = "[0,0]", count = "[2,3]", dest = c("[0,0]", "[0,3]")), append = TRUE)
got <- mr_chunks(con, "z", rbind(c(0, 1), c(0, 0), c(0, 2)))
stopifnot(identical(got$k, 1:2), identical(got$path, c("/b.tif", "/a.tif")),
          same(mr_chunk(con, "z", c(0, 1)), mr_refs(con, "z")[2, , drop = FALSE]))
dbDisconnect(con)

## timing at a larger size: view filter against the placement-first join
con <- make_store(20000L)
key <- c(15000, 1, 2)
t_view <- system.time(for (j in 1:5)
  dbGetQuery(con, sprintf("SELECT * FROM (%s) WHERE dim_0 = 15000 AND dim_1 = 1 AND dim_2 = 2",
                          mr_view_sql(con, "sst"))))[["elapsed"]] / 5
t_join <- system.time(for (j in 1:5) mr_chunk(con, "sst", key))[["elapsed"]] / 5
keys <- cbind(sample(0:20000, 1000, replace = TRUE), sample(0:2, 1000, TRUE), sample(0:2, 1000, TRUE))
t_batch <- system.time(b <- mr_chunks(con, "sst", keys))[["elapsed"]]
stopifnot(nrow(b) == 1000L)
cat(sprintf("%d chunk rows: view filter %.3f s, mr_chunk %.4f s, 1000 keys in one mr_chunks call %.3f s\n",
            9L * 20000L + 18L, t_view, t_join, t_batch))
dbDisconnect(con)
cat("ok\n")
