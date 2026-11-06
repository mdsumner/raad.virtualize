# Versioning

Product repos run this engine pinned to a tag, so a tag is a promise about
what a build produces. Tags are `v<major>.<minor>.<patch>`. Before 1.0, a
breaking change bumps the minor number (v0.1.0 to v0.2.0) and anything else
bumps the patch number.

The older tags `latest` and `oisst` point at the initial commit and carry
release files (such as `oisst-refs.sqlite`). They are not engine versions.

## What counts as a breaking change

A change is breaking when a build from the same config, on the same source
files, would publish something an existing reader or product repo cannot use
as before:

- **Byte-reference table.** The byterefs version written (`byterefs/0.1`),
  or the files and columns of `arrays.json`, `refs_<array>.parquet` and
  `sources.parquet`.
- **Published layout.** File and directory names under a dataset prefix
  (`flat/`, `mdim.vrt`, `kerchunk/`, `icechunk/`, `stac/`, `grist/`,
  `plan.vrt`, `store.sqlite`, `sources.meta.tsv`), or where `run.sh` puts a
  dataset in a product.
- **Catalog columns.** The columns of `grist/catalog.parquet` and what they
  mean, and the STAC collection and item fields that readers use.
- **Config interface.** Step names in `run.sh`, and the variables and
  functions a dataset config sets (`DATASET`, `ARRAYS`, `sources()`,
  `make_plan()`, `REMAPS`, the `*_TARGET` variables, `PRODUCT_GROUP`, the
  `SOURCECOOP_*` variables), when an existing config would stop working or
  change what it publishes.

Not breaking: new steps, new optional variables, new rendered forms beside
the existing ones, new checks in `verify`, and fixes whose published output
is the same or is corrected to match the sources.

## Releases

Each tag gets a GitHub release whose notes say which of the four areas
above changed, if any, and what a product repo must do to move to it.
