"""stac_geoparquet.py -- STAC items (ndjson) to stac-geoparquet.

  python py/stac_geoparquet.py ITEMS.ndjson ITEMS.parquet
  python py/stac_geoparquet.py --check

Writes one row per item with the rustac Python package (pip install rustac),
or the rustac command line where the package is missing. --check exits 0
when either writer is available, so run.sh declares the collection's
"geoparquet-items" asset only when the file is written.
"""
import argparse
import json
import shutil
import subprocess
import sys


def writer():
    try:
        import rustac  # noqa: F401
        return "python"
    except ImportError:
        return "cli" if shutil.which("rustac") else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ndjson", nargs="?")
    ap.add_argument("parquet", nargs="?")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    w = writer()
    if a.check:
        sys.exit(0 if w else 1)
    if not (a.ndjson and a.parquet):
        ap.error("needs ITEMS.ndjson ITEMS.parquet")
    if w is None:
        sys.exit("stac_geoparquet: neither the rustac package nor the rustac command is installed")
    if w == "cli":
        subprocess.run(["rustac", "translate", a.ndjson, a.parquet], check=True)
    else:
        import rustac
        with open(a.ndjson) as f:
            items = [json.loads(ln) for ln in f if ln.strip()]
        rustac.write_sync(a.parquet, items)
        n = len(items)
        print(f"stac_geoparquet: {n} items -> {a.parquet}")


if __name__ == "__main__":
    main()
