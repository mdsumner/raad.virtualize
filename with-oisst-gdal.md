# Taster: opening the OISST byte-ref store with stock GDAL

A side story to the raad.virtualize README. The store described there is a
plain SQLite database of byte references. This document records the moment
that design choice paid off in a way nothing was written to do: the store,
published as a GitHub release artifact, opened remotely with stock GDAL --
no download, no SQLite client, no code from this project.

## The session

```r
oisststore <- new(
  gdalraster::GDALVector,
  "/vsicurl/https://github.com/mdsumner/raad.virtualize/releases/download/latest/oisst-refs.sqlite"
)

oisststore$getNextFeature()
## OGR feature (attributes)
## $file_id  1
## $idx0 0  $idx1 0  $idx2 0  $idx3 0
## $present  1
## $offset   47747
## $size     684063

oisststore$getArrowStream()
## <nanoarrow_array_stream
##   struct<OGC_FID: int64, file_id: int32, idx0..idx3: int32,
##          present: int32, offset: int32, size: int32>>
```

That is: a GDAL vector datasource, opened over HTTP with vsicurl range
requests against a release artifact, yielding both a feature cursor and a
zero-copy Arrow stream of chunk references. The first feature read is the
first chunk of the first harvested granule -- chunk (0,0,0,0) of the
1981-09-01 file, 684,063 bytes starting at offset 47,747.

## Why this matters

Nothing here was implemented by raad.virtualize. It falls out of one design
decision: the byte-ref store is a plain SQLite database, and GDAL treats
SQLite as a first-class vector datasource. Consequences:

- **The store is queryable by the whole OGR ecosystem.** ogr2ogr, OGR SQL,
  spatial and attribute filters, every OGR binding in every language.
- **The store streams as Arrow.** duckdb, polars, arrow R/Python, anything
  Arrow-native gets bulk columnar access to millions of chunk references
  without a row loop.
- **The store is distributable as a static file.** A GitHub release, an S3
  object, a THREDDS fileServer path -- anywhere vsicurl reaches, the index
  is live. No service, no server, no API.

The per-chunk read path of a hypothetical GDAL "reference store" reader is
one SQL statement against this file:

```sql
SELECT f.source, a."offset", a.size
FROM sst a JOIN files f USING (file_id)
WHERE idx0 = ? AND idx1 = ? AND idx2 = ? AND idx3 = ?
```

which is a single clustered-key seek (the chunk tables are WITHOUT ROWID,
keyed on the chunk coordinate). The session above executed the moral
equivalent of that interactively, over HTTP. In the context of the draft
GDAL RFC on multidimensional chunk-reference extraction, this is the
argument made concrete: the reference table does not need a new format to
be a GDAL citizen -- it already is one.

Note the contrast with the published forms this store feeds. Kerchunk
parquet and Icechunk manifests are purpose-built reference formats, and
GDAL consumes kerchunk through the ZARR driver -- but neither is a general
GDAL datasource you can open, filter, and stream as a table. The
intermediate store is more interoperable than its own downstream products.

## Two mechanical lessons the session surfaced

Both are one-line fixes in the store code, and both generalize to any
dataset added later.

**1. Publish in DELETE journal mode, not WAL.** The harvest side opens the
database with `PRAGMA journal_mode = WAL` (correct for a writer with
concurrent readers). But WAL requires write access to the -wal/-shm
sidecars, so a read-only remote copy cannot be opened normally -- GDAL
warned and recovered by retrying with IMMUTABLE=YES. The publish step
should checkpoint and switch to `PRAGMA journal_mode = DELETE` before
uploading. Harvest in WAL, publish in DELETE: the same staging-versus-
published split as everywhere else in this system.

**2. Declare offset and size as BIGINT.** The Arrow schema in the session
shows `offset: int32, size: int32`: OGR mapped the columns' plain INTEGER
declaration to 32-bit. Harmless for OISST (small files), silently wrong for
any granule over 2 GiB. SQLite integers are always up to 64-bit internally,
but OGR reads the *declared* type -- declaring the columns BIGINT gives
Integer64 through OGR and int64 through Arrow. This must be in place before
any large-file dataset is harvested.

## What the taster implies for the general design

The OISST store is dataset-scoped and transient -- a taster. The general
shape it points at:

- **One SQLite store per dataset**, not one mega-database. The release-
  artifact distribution model works per dataset; harvest writers never
  contend across datasets; and remote range-read access stays fast when
  each file stays modest.
- **A registry as the umbrella**: a small catalog of stores (dataset name,
  store URL, arrays, remap rules, dedup policy, VRT URL). The "grander
  container" is not a database holding every chunk -- it is a catalog
  holding every store. This is the bowerbird pattern lifted one level:
  bowerbird catalogs sources of files; the registry catalogs sources of
  references.
- **The schema contract is what unifies them**: files + per-array chunk
  tables, the source-verbatim rule, BIGINT byte columns, non-WAL on
  publish. Forty stores with one schema are one system.

The headline stands on its own: the "future GDAL meta format" this project
gestures at is not a roadmap item. It is a description of something that
already works, demonstrated in four lines of R against a public URL.
