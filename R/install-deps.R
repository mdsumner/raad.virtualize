## install-deps.R -- park the R packages the pipeline needs in a local library.
##
## Rscript install-deps.R [LIB]      (default: ../r-lib beside this directory)
##
## run.sh puts LIB first on the library path (R_LIBS), so nothing is installed
## into the image or the user library. Only missing packages are installed.
## On Linux it uses Posit Package Manager binaries for the distro when it can
## tell which one it is (arrow from source takes a long time), and otherwise
## falls back to a source build with the prebuilt libarrow download.
args <- commandArgs(trailingOnly = TRUE)
here <- dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1]))
lib <- if (length(args)) args[1] else file.path(dirname(normalizePath(here)), "r-lib")
dir.create(lib, recursive = TRUE, showWarnings = FALSE)
.libPaths(c(lib, .libPaths()))

need <- c("DBI", "RSQLite", "jsonlite", "xml2", "arrow", "blob")
miss <- need[!vapply(need, requireNamespace, logical(1), quietly = TRUE)]
if (!length(miss)) {
  message("all present: ", paste(need, collapse = " "), "\nlibrary: ", lib)
  quit(save = "no")
}
message("installing into ", lib, ": ", paste(miss, collapse = " "))

repos <- c(CRAN = "https://cloud.r-project.org")
if (file.exists("/etc/os-release")) {
  os <- readLines("/etc/os-release")
  code <- sub("^VERSION_CODENAME=", "", grep("^VERSION_CODENAME=", os, value = TRUE))
  if (length(code) && nzchar(code)) {
    repos <- c(CRAN = sprintf("https://p3m.dev/cran/__linux__/%s/latest", code))
    ## P3M serves binaries only to a user agent that names R and the platform
    options(HTTPUserAgent = sprintf("R/%s R (%s)", getRversion(),
      paste(getRversion(), R.version["platform"], R.version["arch"], R.version["os"])))
  }
}
Sys.setenv(NOT_CRAN = "true", LIBARROW_BINARY = "true")
install.packages(miss, lib = lib, repos = repos, Ncpus = max(1L, parallel::detectCores() - 1L))

still <- miss[!vapply(miss, requireNamespace, logical(1), quietly = TRUE)]
if (length(still)) stop("not installed: ", paste(still, collapse = " "))
if (!arrow::arrow_info()$capabilities[["parquet"]]) stop("arrow was built without Parquet")
message("done; library: ", lib)
