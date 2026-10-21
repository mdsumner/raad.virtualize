## store.R -- generic per-file byte-ref cache. Knows only: sources (the harvest
## URIs, verbatim) and, per array, the WITHIN-FILE chunk grid -> (offset, size).
## No dates, no global index, no mosaic, no remap. "here's a file, here are its
## chunks." Every interpretation (date pattern, dedup, mirror rewrite, concat)
## is a projection a caller applies -- never encoded here.
## ----------------------------------------------------------------------------
library(DBI)

mr_open <- function(path, write = FALSE) {
  con <- dbConnect(RSQLite::SQLite(), path, bigint = "integer64",
                   flags = if (write) RSQLite::SQLITE_RWC else RSQLite::SQLITE_RO)
  dbExecute(con, "PRAGMA foreign_keys = ON")
  if (write) {
    dbExecute(con, "PRAGMA journal_mode = WAL")
    dbExecute(con, "PRAGMA synchronous = NORMAL")
    dbExecute(con, "PRAGMA busy_timeout = 30000")
  }
  con
}

mr_init <- function(con) {
  dbExecute(con, "CREATE TABLE IF NOT EXISTS files(
                    file_id INTEGER PRIMARY KEY,
                    source  TEXT UNIQUE)")               # source = harvest URI, as-is
  dbExecute(con, "CREATE TABLE IF NOT EXISTS arrays(
                    name TEXT PRIMARY KEY, ndim INTEGER) WITHOUT ROWID")
  invisible(con)
}

mr_rank <- function(con, array) {
  ti <- dbGetQuery(con, sprintf("PRAGMA table_info(%s)", dbQuoteIdentifier(con, array)))
  sum(grepl("^idx[0-9]+$", ti$name))
}

## per-array chunk table: keyed on (file_id, WITHIN-FILE chunk coord). file_id
## first in the PK so "all chunks of a file" is a prefix scan.
mr_declare_array <- function(con, name, rank) {
  stopifnot(rank >= 1L)
  idx <- paste0("idx", seq_len(rank) - 1L)
  tbl <- dbQuoteIdentifier(con, name)
  if (name %in% dbListTables(con)) {
    have <- sum(grepl("^idx[0-9]+$",
      dbGetQuery(con, sprintf("PRAGMA table_info(%s)", tbl))$name))
    if (have != rank) {
      message(sprintf("array '%s': replacing stale table (had %d idx cols, need %d)",
                      name, have, rank))
      dbExecute(con, sprintf("DROP TABLE %s", tbl))
    }
  }
  dbExecute(con, sprintf('CREATE TABLE IF NOT EXISTS %s (
      file_id INTEGER NOT NULL REFERENCES files(file_id),
      %s,
      present INTEGER NOT NULL DEFAULT 1,
      "offset" INTEGER,
      size     INTEGER,
      PRIMARY KEY (file_id, %s)
    ) WITHOUT ROWID', tbl,
    paste0(idx, " INTEGER NOT NULL", collapse = ",\n      "),
    paste(idx, collapse = ", ")))
  dbExecute(con, "INSERT INTO arrays(name,ndim) VALUES(?,?)
                  ON CONFLICT(name) DO UPDATE SET ndim=excluded.ndim",
            params = list(name, rank))
  invisible(name)
}

## MERGE a batch of scanned files. batch = list of
##   list(source = <uri>, arrays = list(<array> = df(idx0..,present,offset,size)))
## One transaction over the batch (the single-writer boundary). Upsert on the
## (file_id, within-file idx) PK -- re-scanning a file replaces its rows in place.
mr_merge <- function(con, batch) {
  dbWithTransaction(con, {
    src <- vapply(batch, `[[`, "", "source")
    dbExecute(con, "INSERT INTO files(source) VALUES(?) ON CONFLICT(source) DO NOTHING",
              params = list(src))
    qn  <- paste(rep("?", length(src)), collapse = ",")
    fid <- dbGetQuery(con, sprintf(
      "SELECT source, file_id FROM files WHERE source IN (%s)", qn), params = as.list(src))

    for (b in batch) {
      f <- fid$file_id[match(b$source, fid$source)]
      for (nm in names(b$arrays)) {
        df <- b$arrays[[nm]]; if (!nrow(df)) next
        rank <- mr_rank(con, nm); idx <- paste0("idx", seq_len(rank) - 1L)
        val  <- c("file_id", idx, "present", '"offset"', "size")
        set  <- c("present", '"offset"', "size")
        sql  <- sprintf('INSERT INTO %s (%s) VALUES (%s)
                         ON CONFLICT (file_id, %s) DO UPDATE SET %s',
          dbQuoteIdentifier(con, nm), paste(val, collapse = ","),
          paste(rep("?", length(val)), collapse = ","),
          paste(idx, collapse = ","),
          paste(sprintf("%s=excluded.%s", set, set), collapse = ", "))
        dbExecute(con, sql, params = c(
          list(rep(f, nrow(df))), lapply(idx, function(k) df[[k]]),
          list(df$present, df$offset, df$size)))
      }
    }
    TRUE
  })
}

## read all chunks of one array in one file (for a projection to assemble from).
mr_file_chunks <- function(con, array, source) {
  rank <- mr_rank(con, array)
  sel  <- paste(c(paste0("idx", seq_len(rank) - 1L), '"offset"', "size", "present"),
                collapse = ", ")
  dbGetQuery(con, sprintf(
    'SELECT %s FROM %s a JOIN files f USING(file_id) WHERE f.source = ?',
    sel, dbQuoteIdentifier(con, array)), params = list(source))
}
