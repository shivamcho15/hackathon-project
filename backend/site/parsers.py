"""Pure parsers over raw API payloads. Written against the RECORDED responses.

Reading actual payloads is what found the three bugs these functions encode: site
class lives on DNR layer 1 not layer 0, USGS field names are lowercase with no
Fa/Fv, and nearest-centroid Overpass matching silently returns the wrong building.
Parsing a cleaned-up version in tests would have found none of them.
"""
import math
import re
from .. import config


def unwrap(doc):
    """Committed fixtures are {"_fixture": {...}, "response": {...}}; live calls are
    the payload itself. Reading the wrapper as the payload looks exactly like an
    API-shape bug and is not one."""
    return doc["response"] if isinstance(doc, dict) and "_fixture" in doc else doc


def census_latlon(payload):
    m = unwrap(payload).get("result", {}).get("addressMatches", [])
    if not m:
        return None          # structural gap for campus addresses, not a hiccup
    c = m[0]["coordinates"]
    return float(c["y"]), float(c["x"])


def nominatim_latlon(payload):
    r = unwrap(payload)
    return (float(r[0]["lat"]), float(r[0]["lon"])) if r else None


def dnr_site_class(payload):
    """Layer 1. Returns the clean single letter, or None for no coverage.

    Outside Washington this comes back as {"features": []} with HTTP 200 — easy to
    detect, easy to mistake for success if unchecked.
    """
    f = unwrap(payload).get("features", [])
    return f[0]["attributes"].get("SEISMIC_SITE_CLASS_CD") if f else None


def dnr_liquefaction(payload):
    """Layer 0 — a different query. A string like "very low", not a number."""
    f = unwrap(payload).get("features", [])
    return f[0]["attributes"].get("LIQUEFACTION_SUSCEPT") if f else None


def usgs_spectrum(payload):
    """Only twoPeriodDesignSpectrum. The real response carries SIX spectra and the
    other five parse cleanly while giving a wrong curve: the multi-period one is a
    different shape with no plateau to divide by, the MCEr pair is a different
    hazard level, and the vertical pair is a different axis entirely."""
    d = unwrap(payload)["response"]["data"]
    pairs = lambda k: [{"period_s": p, "sa_g": a} for p, a in
                       zip(d[k]["periods"], d[k]["ordinates"])] if k in d else []
    return {**{k: d[k] for k in
               ("sds", "sd1", "t0", "ts", "sdc", "pgam", "ss", "s1", "tl") if k in d},
            "two_period": pairs("twoPeriodDesignSpectrum"),
            "multi_period": pairs("multiPeriodDesignSpectrum")}


def house_number(address):
    m = re.match(r"\s*(\d+)", address or "")
    return m.group(1) if m else None


def overpass_building(payload, address=None, lat=None, lon=None):
    """Match by address FIRST; nearest centroid only as a fallback.

    The failure this prevents is real: querying the originally documented
    coordinate with around:30 returns Paccar Hall (4295), not Founders Hall (4215),
    because that coordinate was ~60-70 m off. No error, no warning, a real polygon
    for the wrong building.
    """
    els = [e for e in unwrap(payload).get("elements", []) if e.get("tags")]
    if not els:
        return None
    want = house_number(address)
    chosen, matched = None, False
    if want:
        for e in els:
            if e["tags"].get("addr:housenumber") == want:
                chosen, matched = e, True
                break
    if chosen is None and lat is not None:
        def centre(e):
            g = e.get("geometry") or []
            if g:
                return (sum(p["lat"] for p in g) / len(g), sum(p["lon"] for p in g) / len(g))
            c = e.get("center")
            return (c["lat"], c["lon"]) if c else (None, None)
        best = None
        for e in els:
            la, lo = centre(e)
            if la is None:
                continue
            d = math.hypot(la - lat, lo - lon)
            if best is None or d < best[0]:
                best, chosen = (d, e), e
    if chosen is None:
        chosen = els[0]
    g = chosen.get("geometry") or []
    lv = chosen["tags"].get("building:levels")
    t = chosen["tags"]
    year = t.get("start_date", "")[:4]
    return {"levels": int(lv) if lv and lv.isdigit() else None,
            "geometry": [[p["lat"], p["lon"]] for p in g],
            "source_way_id": chosen.get("id"),
            "address_matched": matched,
            # Real identity from real tags — the 3D caption says which building this
            # actually is rather than repeating the address back.
            "name": t.get("name"),
            "year_built": int(year) if year.isdigit() else None,
            "kind": t.get("building")}


def validate_site_class(code):
    """Map a DNR code onto USGS's enum, falling back explicitly rather than sending
    an unknown value raw. Omitting siteClass entirely makes USGS silently default to
    an undocumented "BC".

    DNR really does return boundary classes: the Seattle Central Library resolves to
    "C-D" (confirmed live 2026-09-12, closing an open question). USGS accepts the
    same class spelled "CD", so normalising the hyphen keeps a genuinely more precise
    answer instead of discarding it to the "D" fallback.
    """
    if not code:
        return config.USGS_SITE_CLASS_FALLBACK
    c = code.strip().upper()
    if c in config.USGS_SITE_CLASS_ENUM:
        return c
    squashed = c.replace("-", "").replace(" ", "").replace("/", "")
    return squashed if squashed in config.USGS_SITE_CLASS_ENUM else config.USGS_SITE_CLASS_FALLBACK
