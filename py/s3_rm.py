"""s3_rm.py -- remove every object under an S3 prefix, one request per object.

  python py/s3_rm.py /vsis3/BUCKET/PREFIX [--yes] [--workers N]

Lists the prefix and prints the object count and size. Without --yes
nothing is deleted (a dry run). With --yes each object is deleted with its
own DELETE: the source.coop data proxy has no batch DeleteObjects
(POST /<account>?delete answers NoSuchBucket). The prefix must have at
least two path levels below the bucket (account/product/prefix on
source.coop), so a product or bucket root cannot be emptied by mistake.

Connection settings and credentials as for py/s3_sync.py.
Needs obstore (pip install obstore).
"""
import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import obstore

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s3_sync import store_for  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("prefix", help="/vsis3/BUCKET/PREFIX")
    p.add_argument("--yes", action="store_true", help="delete (default: list only)")
    p.add_argument("--workers", type=int, default=8)
    a = p.parse_args()

    store, prefix = store_for(a.prefix)
    if len([x for x in prefix.split("/") if x]) < 2:
        sys.exit(f"s3_rm: refusing {a.prefix}: give a prefix at least two levels below the bucket")
    objs = [o for batch in obstore.list(store) for o in batch]
    size = sum(o["size"] for o in objs)
    print(f"s3_rm: {len(objs)} objects, {size / 1e6:.1f} MB under {a.prefix}")
    if not a.yes or not objs:
        if objs and not a.yes:
            print("s3_rm: dry run, pass --yes to delete")
        return

    t0 = time.time()
    keys = [o["path"] for o in objs]

    def rm(k):
        obstore.delete(store, k)
        return k

    with ThreadPoolExecutor(a.workers) as ex:
        for i, k in enumerate(ex.map(rm, keys), 1):
            if i % 500 == 0 or i == len(keys):
                print(f"s3_rm: {i}/{len(keys)} {k}", flush=True)
    left = sum(1 for batch in obstore.list(store) for _ in batch)
    print(f"s3_rm: removed {len(keys)} objects in {time.time() - t0:.1f} s; {left} left")
    if left:
        sys.exit(1)


if __name__ == "__main__":
    main()
