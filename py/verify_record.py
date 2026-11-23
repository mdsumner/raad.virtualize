"""verify_record.py -- the verify outcome of one build, and the publish gate.

`verify` writes OUT/verify.json after every check of the step has passed:
the store it checked (size, mtime, and the meta `created` and `generator`
that the forms carry), the checks run, and the time. Any step that changes
the store or a verified form removes the record first (run.sh), so a record
exists only for a store and forms that passed together. `publish` refuses
without a record that matches the store as it is now. The record is
published with out/, so a reader of the product can see that the published
build passed, and against which store.

  python py/verify_record.py write WORK --check verify.py [--check ...]
  python py/verify_record.py check WORK     exit 1 unless WORK/out/verify.json
                                            matches WORK/store.sqlite
"""
import argparse
import datetime
import json
import os
import sqlite3
import sys


def store_id(work):
    """What identifies the store: its size and mtime, and the meta values
    every rendered form carries."""
    path = os.path.join(work, "store.sqlite")
    st = os.stat(path)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        meta = dict(con.execute("select key, value from meta where key in ('created', 'generator', 'dataset')"))
    finally:
        con.close()
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "created": meta.get("created"),
            "generator": meta.get("generator"), "dataset": meta.get("dataset")}


def record_path(work):
    return os.path.join(work, "out", "verify.json")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write")
    w.add_argument("work")
    w.add_argument("--check", action="append", default=[], help="a check that passed (repeatable)")
    c = sub.add_parser("check")
    c.add_argument("work")
    a = p.parse_args()
    if a.cmd == "write":
        rec = {"result": "pass", "checks": a.check, "store": store_id(a.work),
               "verified": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "windows": os.environ.get("VERIFY_WINDOWS") or None}
        tmp = record_path(a.work) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(rec, f, indent=1)
        os.replace(tmp, record_path(a.work))
        print(f"verify: recorded a pass for {rec['store']['dataset']} ({rec['store']['created']})")
        return
    path = record_path(a.work)
    if not os.path.exists(path):
        sys.exit("publish: no verify record (out/verify.json); run the verify step first. "
                 "A step that changes the store or a verified form removes the record.")
    with open(path) as f:
        rec = json.load(f)
    now = store_id(a.work)
    if rec.get("result") != "pass" or rec.get("store") != now:
        sys.exit(f"publish: out/verify.json does not match the store ({rec.get('store')} against {now}); "
                 "run the verify step again")
    print(f"publish: verify passed {rec['verified']} for this store")


if __name__ == "__main__":
    main()
