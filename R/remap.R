## Set a store's remap rules from a config's REMAPS, as collate does, for a
## store built elsewhere (a republish from the published store.sqlite, which
## skips collate): rules are added or replaced, others are kept.
##   Rscript R/remap.R STORE target|prefix|replacement[|root] ...
if (sys.nframe() == 0L) {
  args <- commandArgs(trailingOnly = TRUE)
  if (length(args) < 1L) stop("usage: remap.R STORE target|prefix|replacement[|root] ...")
  here <- dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1]))
  source(file.path(here, "mdimrefs.R"))
  con <- DBI::dbConnect(RSQLite::SQLite(), args[1])
  mr_set_remap_rules(con, args[-1])
  rm <- DBI::dbReadTable(con, "remap")
  for (i in seq_len(nrow(rm)))
    message(sprintf("remap %s %s -> %s%s", rm$target[i], rm$prefix[i], rm$replacement[i],
                    if (is.na(rm$root[i])) "" else paste0("  (root ", rm$root[i], ")")))
  DBI::dbDisconnect(con)
}
