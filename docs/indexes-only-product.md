# Indexes-only products

An indexes-only product publishes byte-reference indexes of data that stays
with its provider, with no copy of the data itself. It is the form for
Bluelink (BRAN at NCI) and the template for further collections of the same
kind (OISST netCDF, for example). A product is one directory under
`products/` in this repository and one prefix in a bucket; the engine
(plan, harvest, collate, render, verify, publish) is unchanged.

Status: draft, first instance `products/bluelink/`. The catalog build and
the job loop are tested against local directories and a dry run; nothing
has been published from them yet.

## What a product holds

```
products/<product>/
  product.json     id, title, description, license
  datasets.tsv     one row per dataset: dataset, config, env, title
  README.md        landing page of the published product
```

No code. Each row names a dataset config (`config/*.sh`) and the settings
it takes (`env`, comma separated, the form `qsub -v` takes). A dataset that
needs code beyond a config row marks a gap in the engine, not in the
product.

The dataset name in a row must be the one the config derives
(`hpc/nci/submit-product.sh` stops on a mismatch), so the catalog points at
the directory that the jobs write.

## Published layout

The prefix is the publish target's `PUBLISH` (`config/aadc-transfer.sh`,
`config/source-coop.sh`). `run.sh ... publish` writes each dataset under
`<prefix>/<dataset>/`; `catalog.sh` writes the product files at the prefix
root:

```
<prefix>/
  catalog.json        STAC catalog, child link per row of datasets.tsv
  datasets.json       per row: published or not, time extent, build revision
  datasets.tsv        copy of the product's list
  product.json
  README.md
  <dataset>/          mdim.vrt, kerchunk/, icechunk/, flat/, stac/,
                      plan.vrt, store.sqlite (as in docs/ghrsst-source-coop.md)
```

For source.coop, the dataset directories sit under `virtual/` (the
`SOURCECOOP_PREFIX`) as in the GHRSST layout; for an indexes-only product
the product README at the product root is the one source.coop shows;
`catalog.sh publish` writes README.md to the prefix, and the copy at the
product root is a separate upload.

## Procedure

On Gadi, for BRAN (from the repository root, keys exported):

```sh
# needs AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (write pair) already exported
export PROJECT=jk72 ST=gdata/gb6+gdata/jk72+scratch/jk72
DRY_RUN=1 bash hpc/nci/submit-product.sh products/bluelink          # print the qsub lines
bash hpc/nci/submit-product.sh products/bluelink bluelink-daily-salt  # one dataset
bash hpc/nci/submit-product.sh products/bluelink                      # every row
```

Then, from any machine with the keys, the catalog:

```sh
bash catalog.sh products/bluelink config/aadc-transfer.sh check publish
```

`check` reads every row's `stac/collection.json` from the prefix and fails
when one is missing, so a catalog is not published over an incomplete
product. A rebuild of one dataset is one row resubmitted, followed by the
same catalog step.

## Common to every product

| Part | Where it lives |
|---|---|
| Store contract | the dataset directory layout above; mdim-refs/0.2 store, flat refs, plan VRT |
| Validator | `verify` and `verify-published` per dataset; `catalog.sh check` across the product |
| Trigger and cadence | the dataset config plus the job loop; a release is a full rebuild |
| Product template | `products/<product>/` (this document) |

## Open

- Collections do not link to the catalog as parent or root: `R/stac.R`
  writes each collection as its own root. Browsing from the catalog down
  works; browsing up from a collection does not.
- Source completeness within a dataset (expected source count against
  harvested count) is checked for COG sources in the GHRSST path
  (docs/ghrsst-source-coop.md) and not yet as a general harvest check.
- The AADC staging prefix (`michae_sum/e2e`) holds GHRSST datasets beside
  the Bluelink ones; `catalog.json` there lists only the Bluelink rows. A
  prefix per product (`AADC_PREFIX=michae_sum/bluelink`) keeps product and
  prefix one to one, at the cost of a re-publish.
- Multi-variable source files (BRAN `force`, `atm_flux_diag`, `ice_force`)
  need a config option before they can be rows.
