-- chunk_index.sql: a chunk index over the leading two dimensions of one
-- array in a flat refs store (mdim-refs/0.2: arrays.json, refs_<array>.parquet).
--
-- Set two variables first, then read this file, e.g. with the duckdb CLI
-- from the repository root:
--
--   duckdb <<'EOF'
--   SET VARIABLE base = 'https://data.source.coop/ausantarctic/ausantarctic-scratch/bluelink/bluelink-daily-temp/flat';
--   SET VARIABLE arr = 'temp';
--   .read sql/chunk_index.sql
--   EOF
--
-- base is a directory (local path or https URL, no trailing slash), arr is the
-- array name. Tested with DuckDB 1.1.3, 1.3.2 and 2.0.0. https reads load the
-- httpfs extension on first use. Leaves tables meta, coords, grid, idx, labels and
-- views refs, idx_labelled in the session. Runs from Python with
-- con.execute(open("sql/chunk_index.sql").read()).

-- arrays.json: the array's dims, shape and chunks, and the chunk grid
CREATE OR REPLACE TEMP TABLE meta AS
SELECT a->>'$.array' AS name,
       CAST(a->'$.dims'   AS VARCHAR[]) AS dims,
       CAST(a->'$.shape'  AS BIGINT[])  AS shape,
       CAST(a->'$.chunks' AS BIGINT[])  AS chunks
FROM (SELECT unnest(json->'$.arrays[*]') AS a
      FROM read_json_objects(getvariable('base') || '/arrays.json', format = 'auto'))
WHERE a->>'$.array' = getvariable('arr');

-- coordinate arrays held in arrays.json (affine start/step or inline values)
CREATE OR REPLACE TEMP TABLE coords AS
SELECT a->>'$.array' AS name,
       a->>'$.storage' AS storage,
       CAST(a->>'$.affine.start' AS DOUBLE) AS start,
       CAST(a->>'$.affine.step'  AS DOUBLE) AS step,
       CAST(a->'$.values' AS DOUBLE[])      AS vals,
       a->>'$.attrs.units' AS units
FROM (SELECT unnest(json->'$.arrays[*]') AS a
      FROM read_json_objects(getvariable('base') || '/arrays.json', format = 'auto'))
WHERE a->>'$.kind' = 'coord';

-- the chunk grid, one row per dim (k from 1)
CREATE OR REPLACE TEMP TABLE grid AS
SELECT r.k, m.dims[r.k] AS dim, m.shape[r.k] AS shape, m.chunks[r.k] AS chunk,
       (m.shape[r.k] + m.chunks[r.k] - 1) // m.chunks[r.k] AS n
FROM meta m, range(1, 33) r(k)
WHERE r.k <= len(m.dims);

SELECT (SELECT name FROM meta) AS name,
       list(dim ORDER BY k) AS dims, list(shape ORDER BY k) AS shape,
       list(chunk ORDER BY k) AS chunks, list(n ORDER BY k) AS grid,
       CAST(coalesce(product(n) FILTER (k > 2), 1) AS BIGINT) AS per_pair
FROM grid;

CREATE OR REPLACE TEMP VIEW refs AS
SELECT * FROM read_parquet(getvariable('base') || '/refs_' || getvariable('arr') || '.parquet');

-- one row per (dim_0, dim_1) chunk pair: chunks listed and present, bytes,
-- files, the byte span those chunks cover in their file, and the bytes in
-- that span that are not chunks of this pair (gap = 0: one range request
-- reads exactly the pair, and gap only means something when files = 1)
CREATE OR REPLACE TEMP TABLE idx AS
SELECT dim_0, dim_1,
       count(*)                                AS rows,
       count(*) FILTER (present = 1)           AS present,
       sum(size) FILTER (present = 1)          AS bytes,
       count(DISTINCT path)                    AS files,
       min("offset") FILTER (present = 1)        AS span_start,
       max("offset" + size) FILTER (present = 1) AS span_end,
       max("offset" + size) FILTER (present = 1)
         - min("offset") FILTER (present = 1)
         - sum(size) FILTER (present = 1)      AS gap,
       any_value(path)                         AS path
FROM refs
GROUP BY dim_0, dim_1;

-- coordinate value at the first element of each chunk along the leading two
-- dims (NULL where the coordinate is not held in arrays.json), and a
-- timestamp where its units are "days since" or "seconds since"
CREATE OR REPLACE TEMP TABLE labels AS
WITH d AS (
  SELECT k - 1 AS axis, dim, chunk, unnest(range(n)) AS i
  FROM grid WHERE k <= 2
)
SELECT d.axis, d.i AS idx, d.dim,
       coalesce(c.vals[d.i * d.chunk + 1], c.start + c.step * d.i * d.chunk) AS value,
       CASE WHEN c.units LIKE 'days since %' THEN 86400e6
            WHEN c.units LIKE 'seconds since %' THEN 1e6 END AS us,
       try_cast(regexp_extract(c.units, 'since ([0-9]{4}-[0-9]{1,2}-[0-9]{1,2})', 1) AS TIMESTAMP) AS epoch
FROM d
LEFT JOIN coords c ON c.name = d.dim;

CREATE OR REPLACE TEMP VIEW idx_labelled AS
SELECT x.dim_0, coalesce(CAST(l0.epoch + to_microseconds(CAST(round(l0.value * l0.us) AS BIGINT)) AS VARCHAR),
                         CAST(l0.value AS VARCHAR)) AS label_0,
       x.dim_1, coalesce(CAST(l1.epoch + to_microseconds(CAST(round(l1.value * l1.us) AS BIGINT)) AS VARCHAR),
                         CAST(l1.value AS VARCHAR)) AS label_1,
       x.* EXCLUDE (dim_0, dim_1)
FROM idx x
LEFT JOIN labels l0 ON l0.axis = 0 AND l0.idx = x.dim_0
LEFT JOIN labels l1 ON l1.axis = 1 AND l1.idx = x.dim_1;

SELECT * EXCLUDE (path) FROM idx_labelled ORDER BY dim_0, dim_1 LIMIT 10;
