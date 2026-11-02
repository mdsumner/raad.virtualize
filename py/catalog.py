"""catalog.py -- STAC catalog of a product group (one child per dataset) or
of the product root (one child per group).

  python py/catalog.py PRODUCT_DIR OUT_DIR [--published PREFIX] [--check]
                       [--base URL] [--parent HREF]

PRODUCT_DIR holds product.json (id, title, description, license) and
datasets.tsv (dataset, config, env, title; # lines skipped). OUT_DIR gets
catalog.json, with one child link per dataset to
./<dataset>/stac/collection.json, and copies of product.json, datasets.tsv
and README.md (when present). OUT_DIR is synced to the publish prefix, so
the catalog sits beside the dataset directories that run.sh publishes.

--published PREFIX: where the dataset directories are (a local directory,
  /vsis3/BUCKET/PREFIX or https://...). Each child's collection.json is
  read from there; its temporal extent and source count go into
  datasets.json, and the child link takes its title. Without --check a
  missing collection is reported and the row is kept.
--check: fail when any row has no published collection.
--base URL: public URL of the publish prefix, for the catalog's self link.
--parent HREF: the catalog one level up (e.g. ../catalog.json), given to a
  group that sits under a root catalog; its root and parent links point
  there. Without it the group catalog is its own root.

Root mode: when PRODUCT_DIR holds groups.tsv (group, title) instead of
datasets.tsv, the catalog has one child per group at
./<group>/catalog.json, --published reads those, and the status file is
groups.json (with the group's dataset count where published). A group is
the directory PRODUCT_DIR/<group>/ with its own product.json and
datasets.tsv; a group with no rows yet is an empty, valid catalog.

Reads through GDAL's virtual file system, so the same credentials and
endpoint settings as publish apply (AWS_S3_ENDPOINT and the keys).
"""
import argparse
import csv
import json
import os
import shutil
import sys

STAC_VERSION = "1.1.0"


def read_rows(path, key="dataset", need=("dataset", "config", "env", "title")):
    with open(path, newline="") as f:
        lines = [ln for ln in f if ln.strip() and not ln.startswith("#")]
    rd = csv.DictReader(lines, delimiter="\t")
    rows = list(rd)
    if not rd.fieldnames or not set(need) <= set(rd.fieldnames):
        sys.exit(f"catalog: {path} needs columns {sorted(need)}")
    names = [r[key] for r in rows]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        sys.exit(f"catalog: duplicate {key}s in {path}: {', '.join(dup)}")
    return rows


def vsi_path(prefix, rel):
    p = prefix.rstrip("/") + "/" + rel
    if p.startswith(("https://", "http://")):
        return "/vsicurl/" + p
    return p


def read_json(path):
    if not path.startswith("/vsi"):
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)
    from osgeo import gdal
    gdal.UseExceptions()
    try:
        f = gdal.VSIFOpenL(path, "rb")
    except RuntimeError:
        return None
    if f is None:  # some GDAL builds return None instead of raising
        return None
    try:
        data = b""
        while True:
            chunk = gdal.VSIFReadL(1, 1 << 20, f)
            if not chunk:
                break
            data += chunk
    finally:
        gdal.VSIFCloseL(f)
    return json.loads(data)


def summary(coll):
    out = {"collection_id": coll.get("id")}
    try:
        out["interval"] = coll["extent"]["temporal"]["interval"][0]
    except (KeyError, IndexError, TypeError):
        pass
    meta = coll.get("rv:meta") or {}
    for k in ("generator", "created", "config"):
        if k in meta:
            out[k] = meta[k]
    out["items"] = sum(1 for ln in coll.get("links", []) if ln.get("rel") == "item") or None
    return {k: v for k, v in out.items() if v is not None}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("product_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--published")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--base")
    ap.add_argument("--parent")
    a = ap.parse_args()
    if a.check and not a.published:
        sys.exit("catalog: --check needs --published")

    with open(os.path.join(a.product_dir, "product.json")) as f:
        prod = json.load(f)
    root_mode = os.path.exists(os.path.join(a.product_dir, "groups.tsv"))
    if root_mode:
        key, cols, listing, status_file = "group", ("group", "title"), "groups.tsv", "groups.json"
    else:
        key, cols, listing, status_file = ("dataset", ("dataset", "config", "env", "title"),
                                           "datasets.tsv", "datasets.json")
    rows = read_rows(os.path.join(a.product_dir, listing), key, cols)
    if root_mode:
        for r in rows:
            if not os.path.exists(os.path.join(a.product_dir, r["group"], "product.json")):
                sys.exit(f"catalog: group {r['group']} has no {a.product_dir}/{r['group']}/product.json")

    up = a.parent if a.parent and not root_mode else "./catalog.json"
    links = [{"rel": "root", "href": up, "type": "application/json"}]
    if up != "./catalog.json":
        links.append({"rel": "parent", "href": up, "type": "application/json"})
    if a.base:
        links.append({"rel": "self", "href": a.base.rstrip("/") + "/catalog.json",
                      "type": "application/json"})
    status, missing = [], []
    for r in rows:
        rel = f"{r['group']}/catalog.json" if root_mode else f"{r['dataset']}/stac/collection.json"
        link = {"rel": "child", "href": "./" + rel, "type": "application/json",
                "title": r["title"]}
        st = {k: r[k] for k in cols}
        if a.published:
            doc = read_json(vsi_path(a.published, rel))
            if doc is None:
                missing.append(r[key])
                st["published"] = False
            else:
                st["published"] = True
                if root_mode:
                    st["datasets"] = sum(1 for ln in doc.get("links", []) if ln.get("rel") == "child")
                else:
                    st.update(summary(doc))
        links.append(link)
        status.append(st)

    if missing:
        what = "group catalog" if root_mode else "collection"
        msg = f"catalog: no published {what} for {len(missing)} of {len(rows)}: {', '.join(missing)}"
        if a.check:
            sys.exit(msg)
        print(msg, file=sys.stderr)

    cat = {"type": "Catalog", "stac_version": STAC_VERSION, "id": prod["id"],
           "title": prod.get("title", prod["id"]), "description": prod["description"],
           "links": links}
    if prod.get("license"):
        cat["rv:license"] = prod["license"]
    os.makedirs(a.out_dir, exist_ok=True)
    with open(os.path.join(a.out_dir, "catalog.json"), "w") as f:
        json.dump(cat, f, indent=2)
        f.write("\n")
    with open(os.path.join(a.out_dir, status_file), "w") as f:
        json.dump(status, f, indent=2)
        f.write("\n")
    for name in ("product.json", listing, "README.md"):
        src = os.path.join(a.product_dir, name)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(a.out_dir, name))
    n_pub = sum(1 for s in status if s.get("published"))
    print(f"catalog: {len(rows)} {key}s" + (f", {n_pub} published" if a.published else "")
          + f" -> {a.out_dir}/catalog.json")


if __name__ == "__main__":
    main()
