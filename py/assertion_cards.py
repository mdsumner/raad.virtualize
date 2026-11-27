"""The done test of the assertion step: every projection carries the asserted facts.

    python py/assertion_cards.py --out WORK/out --assertions assertions/DATASET \\
        [--before BASE] [--overlay DIR] [--md cards/DATASET.md] [--json FILE]

For each projection of the rendered store in --out (kerchunk/, icechunk/,
mdim.vrt, stac/) and each applied assertion in --assertions, the facts the
assertion touches (grid transform, shape, spatial dimensions, CRS and its
axis mapping) are read from the projection and compared with the
assertion:

- kerchunk and Icechunk: the storecard card (hypertidy/storecard,
  `pip install "storecard[virtual] @ git+https://github.com/hypertidy/storecard"`),
  with no overlay. With --overlay DIR (storecard's
  assertions/ausantarctic/<dataset>/, documents named <form>-<variable>.json)
  and --before, the card is also compared with the card of the published
  form with that overlay applied, on the grid, crs and findings sections:
  card(P) == card(source, assertions=[A]).
- mdim.vrt: osgeo.gdal (multidimensional API): the array's SRS, its
  dataAxisToSRSAxisMapping and the transform restated from its 1-D x and y
  indexing variables (storecard does not card a VRT).
- stac: the first and last item's proj:code, proj:shape and proj:transform
  for the asserted array, and the collection's rv:assertions.

--before BASE (the published dataset prefix, https://...) cards the
published projections the same way, for the before column. Hosts are not
probed (chunk-host CORS is not a fact an assertion touches).

Writes a Markdown report (--md) and JSON (--json); exits 1 when any
projection differs from its assertion.
"""

import argparse
import json
import pathlib
import struct
import sys

CRS_FINDINGS = {"CRS_NOT_DECLARED", "PROJECTED_NO_GRID_MAPPING"}
TOL = 1e-6


def _load_assertions(d):
    out = []
    for f in sorted(pathlib.Path(d).glob("*.json")):
        doc = json.loads(f.read_text())
        if doc.get("status") != "withdrawn":
            out.append(doc)
    return out


def _close(a, b, scale=1.0):
    if a is None or b is None or len(a) != len(b):
        return False
    return all(abs(float(x) - float(y)) <= TOL * max(scale, 1.0) for x, y in zip(a, b))


def target(doc):
    a = doc["asserts"]
    return {"crs": a.get("proj:code") or a.get("proj:wkt2") or "projjson",
            "transform": [float(x) for x in a["spatial:transform"]],
            "shape": list(a["spatial:shape"]),
            "dimensions": list(a["spatial:dimensions"]),
            "crs_axes": list(doc["crs_axes"])}


def compare(facts, t):
    """(ok, reasons) of projection facts against the assertion target."""
    if facts is None or facts.get("error"):
        return False, [facts.get("error") if facts else "not present"]
    why = []
    if facts.get("crs") != t["crs"]:
        why.append(f"crs {facts.get('crs')} != {t['crs']}")
    if not _close(facts.get("transform"), t["transform"], abs(t["transform"][0])):
        why.append(f"transform {facts.get('transform')} != {t['transform']}")
    if facts.get("shape") is not None and list(facts["shape"]) != t["shape"]:
        why.append(f"shape {facts.get('shape')} != {t['shape']}")
    if "dimensions" in facts and facts["dimensions"] != t["dimensions"]:
        why.append(f"dimensions {facts['dimensions']} != {t['dimensions']}")
    if "mapping" in facts and facts["mapping"] != facts.get("mapping_expected"):
        why.append(f"axis mapping {facts['mapping']} != {facts.get('mapping_expected')}")
    return not why, why


# ---------------------------------------------------------------- Zarr forms (storecard)

def _norm_card_var(c, var):
    """The sections of a card an assertion touches, provenance removed."""
    v = next((x for x in c["variables"] if x["name"] == var), None)
    if v is None:
        return None
    g = json.loads(json.dumps(v["grid"]))
    for k in ("assertion", "costume_presented"):
        g.pop(k, None)
    if isinstance(g.get("transform"), dict):
        g["transform"].pop("from", None)
    for ax in (g.get("axes") or {}).values():
        ax.pop("values", None)
    g["declared"] = sorted(g.get("declared") or [])
    crs = json.loads(json.dumps(v.get("crs") or {}))
    for s in crs.get("sources") or []:
        s.pop("on", None)
    findings = sorted(set(c.get("findings_summary") or {}) - {"CHUNK_HOST_NO_CORS"})
    return {"grid": g, "crs": crs, "findings": findings}


def card_zarr(url, var, overlay=None):
    try:
        from storecard import card
    except ImportError:
        return {"error": "storecard not installed"}
    try:
        c = card(url, probe_hosts=False, assertions=overlay or ())
    except Exception as e:  # noqa: BLE001 - report, do not stop the other forms
        return {"error": f"{type(e).__name__}: {e}"}
    v = next((x for x in c["variables"] if x["name"] == var), None)
    if v is None:
        return {"error": f"no variable {var}"}
    g, crs = v.get("grid") or {}, v.get("crs") or {}
    tr = g.get("transform") if isinstance(g.get("transform"), dict) else {}
    srcs = crs.get("sources") or []
    out = {"crs": srcs[0]["value"] if srcs else None,
           "crs_via": (srcs[0].get("via"), srcs[0].get("on")) if srcs else None,
           "transform": tr.get("spatial:transform"),
           "shape": tr.get("spatial:shape"),
           "costume": g.get("costume"),
           "findings": sorted(c.get("findings_summary") or {}),
           "card": _norm_card_var(c, var)}
    if tr.get("spatial:dimensions"):
        out["dimensions"] = list(tr["spatial:dimensions"])
    if overlay is not None:
        out["overlay_applied"] = all(a.get("applied") for a in c["source"].get("assertions") or [])
    return out


# ---------------------------------------------------------------- mdim VRT (GDAL)

def card_vrt(path, var, doc):
    try:
        from osgeo import gdal
    except ImportError:
        return {"error": "osgeo.gdal not installed"}
    gdal.UseExceptions()
    try:
        ds = gdal.OpenEx(path, gdal.OF_MULTIDIM_RASTER)
        rg = ds.GetRootGroup()
        arr = rg.OpenMDArrayFromFullname("/" + var)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    dims = [d.GetName() for d in arr.GetDimensions()]
    srs = arr.GetSpatialRef()
    crs = mapping = None
    if srs is not None:
        srs.AutoIdentifyEPSG()
        name, code = srs.GetAuthorityName(None), srs.GetAuthorityCode(None)
        crs = f"{name}:{code}" if name and code else srs.ExportToWkt()[:60]
        mapping = ",".join(str(i) for i in srs.GetDataAxisToSRSAxisMapping())
    yd, xd = doc["asserts"]["spatial:dimensions"]
    role = {"y": yd, "x": xd}
    expected = ",".join(str(dims.index(role[r]) + 1) for r in doc["crs_axes"])
    tr = []
    for d in (xd, yd):
        dim = next(x for x in arr.GetDimensions() if x.GetName() == d)
        iv = dim.GetIndexingVariable()
        if iv is None:
            return {"crs": crs, "error": f"no indexing variable for {d}"}
        n = dim.GetSize()
        f64 = gdal.ExtendedDataType.Create(gdal.GDT_Float64)
        f0, f1 = (struct.unpack("d", iv.Read(array_start_idx=[i], count=[1], buffer_datatype=f64))[0]
                  for i in (0, n - 1))
        step = (f1 - f0) / (n - 1)
        tr.append((f0 - step / 2, step, n))
    (x0, dx, nx), (y0, dy, ny) = tr
    return {"crs": crs, "mapping": mapping, "mapping_expected": expected,
            "transform": [dx, 0.0, x0, 0.0, dy, y0], "shape": [ny, nx]}


# ---------------------------------------------------------------- STAC

def _read_text(p):
    if str(p).startswith(("http://", "https://")):
        import urllib.request
        with urllib.request.urlopen(p) as r:
            return r.read().decode()
    return pathlib.Path(p).read_text()


def card_stac(stac_dir, var):
    try:
        coll = json.loads(_read_text(f"{stac_dir}/collection.json"))
        lines = [x for x in _read_text(f"{stac_dir}/items.ndjson").splitlines() if x.strip()]
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    items = [json.loads(lines[0]), json.loads(lines[-1])] if lines else []
    for it in items:
        pl = (it["assets"].get("data") or {}).get("rv:placement") or {}
        if pl and var not in pl and not any(var in (a.get("rv:placement") or {}) for a in it["assets"].values()):
            return {"error": f"item {it['id']} does not hold {var}"}
    props = [it["properties"] for it in items]
    p0 = props[0] if props else {}
    same = all(p.get("proj:code") == p0.get("proj:code") and p.get("proj:transform") == p0.get("proj:transform")
               for p in props)
    out = {"crs": p0.get("proj:code"), "transform": p0.get("proj:transform"),
           "shape": p0.get("proj:shape"), "items_agree": same,
           "rv:assertions": [a.get("id") for a in coll.get("rv:assertions") or []]}
    if not same:
        out["error"] = "first and last item differ in proj:*"
    return out


# ---------------------------------------------------------------- report

FORMS = ("kerchunk", "icechunk", "mdim.vrt", "stac")


def facts_for(base, form, var, doc, overlay=None):
    remote = str(base).startswith(("http://", "https://"))
    if form in ("kerchunk", "icechunk"):
        return card_zarr(f"{base}/{form}", var, overlay)
    if form == "mdim.vrt":
        return card_vrt(f"/vsicurl/{base}/mdim.vrt" if remote else f"{base}/mdim.vrt", var, doc)
    return card_stac(f"{base}/stac", var)


def _fmt(f):
    if f is None:
        return "-"
    if f.get("error"):
        return f"error: {f['error']}"
    parts = [f"crs {f.get('crs')}"]
    if f.get("mapping"):
        parts.append(f"mapping {f['mapping']}")
    if f.get("transform"):
        parts.append("transform [" + ", ".join(f"{x:g}" for x in f["transform"]) + "]")
    if f.get("findings") is not None and "card" in f:
        parts.append("findings " + (", ".join(f["findings"]) or "none"))
    return "; ".join(parts)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", required=True, help="rendered output directory (WORK/out)")
    p.add_argument("--assertions", required=True, help="assertions/<dataset>")
    p.add_argument("--before", help="published dataset prefix (https://...)")
    p.add_argument("--overlay", help="storecard assertions/ausantarctic/<dataset> directory")
    p.add_argument("--forms", default=",".join(FORMS))
    p.add_argument("--md")
    p.add_argument("--json")
    a = p.parse_args(argv)
    docs = _load_assertions(a.assertions)
    if not docs:
        sys.exit(f"no applied assertions in {a.assertions}")
    forms = [f for f in a.forms.split(",") if f]
    out_dir = pathlib.Path(a.out)
    report, ok_all = [], True
    for doc in docs:
        var, t = doc["subject"]["variable"], target(doc)
        for form in forms:
            if form in ("kerchunk", "icechunk", "stac") and not (out_dir / form).exists():
                continue
            if form == "mdim.vrt" and not (out_dir / "mdim.vrt").exists():
                continue
            after = facts_for(out_dir, form, var, doc)
            before = facts_for(a.before.rstrip("/"), form, var, doc) if a.before else None
            ok, why = compare(after, t)
            rec = {"variable": var, "form": form, "after": after, "before": before,
                   "pass": ok, "why": why}
            # card(P) == card(source, assertions=[A]): the published form
            # with storecard's overlay, on the sections the assertion touches
            if form in ("kerchunk", "icechunk") and a.overlay and a.before:
                # every variable's overlay for this form: the findings are
                # the store's, so one variable's overlay alone leaves the
                # others' CRS findings in the reference
                ovs = [json.loads(f.read_text()) for f in sorted(pathlib.Path(a.overlay).glob(f"{form}-*.json"))]
                if any(o["subject"]["variable"] == var for o in ovs):
                    ref = card_zarr(f"{a.before.rstrip('/')}/{form}", var, ovs)
                    rec["reference"] = ref
                    if ref.get("card") and after.get("card"):
                        diff = {k for k in ("grid", "crs", "findings") if ref["card"][k] != after["card"][k]}
                        rec["card_diff"] = sorted(diff)
                        if diff:
                            rec["pass"] = ok = False
                            why.append("card differs from the overlaid published card in " + ", ".join(sorted(diff)))
            ok_all &= ok
            report.append(rec)
            print(f"{'PASS' if ok else 'FAIL'} {var} {form}" + ("".join(f"\n  {w}" for w in why)))
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(report, indent=1, default=str) + "\n")
    if a.md:
        ds = docs[0]["subject"]["dataset"]
        L = [f"# Assertion cards: {ds}", "",
             "Generated by py/assertion_cards.py. Target: the assertion's facts; "
             "before: the published projection; after: the render with the assertion step.", ""]
        for doc in docs:
            t = target(doc)
            L += [f"## {doc['subject']['variable']}", "",
                  f"Asserted: crs {t['crs']} (crs_axes {', '.join(t['crs_axes'])}); "
                  f"transform [{', '.join(f'{x:g}' for x in t['transform'])}]; "
                  f"shape {t['shape']}; dimensions {t['dimensions']}; status {doc['status']}.", "",
                  "| Projection | Before | After | Result |", "| --- | --- | --- | --- |"]
            for r in report:
                if r["variable"] != doc["subject"]["variable"]:
                    continue
                res = "pass" if r["pass"] else "FAIL: " + "; ".join(r["why"])
                L.append(f"| {r['form']} | {_fmt(r['before'])} | {_fmt(r['after'])} | {res} |")
            refs = [r for r in report if r.get("reference") and r["variable"] == doc["subject"]["variable"]]
            if refs:
                L += ["", "Card comparison, card(P) against card(published P, assertions=[storecard overlay]), "
                      "on grid, crs and findings (host findings and provenance fields left out):", ""]
                for r in refs:
                    d = r.get("card_diff")
                    L.append(f"- {r['form']}: " + ("equal" if d == [] else f"differs in {', '.join(d or ['(not compared)'])}"))
            L.append("")
        pathlib.Path(a.md).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(a.md).write_text("\n".join(L))
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
