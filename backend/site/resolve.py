"""Three tiers, and the call graph with per-call timeouts.

Tier 1 LIVE -> Tier 2 CACHED -> Tier 3 FIXTURE (a local file, zero network).
Supabase would be Tier 2, but it is a CLOUD service: it dies with the hotspot, at
exactly the same moment the government APIs do. Only something entirely local is a
real fallback for total connectivity loss, which is why Founders Hall skips
straight to Tier 3 with no live attempt at all.

ONE attempt per call, no retries (I7): a retry turns a 3 s failure into a 9 s hang,
and a 9 s hang in front of a judge is far worse than a fallback that renders now.
"""
import asyncio
import json

import httpx

from .. import config
from . import parsers as PZ

# Verified live 2026-09-12 by walking the ArcGIS service directory. An earlier
# guessed path returned HTTP 200 with a {"error": 404 "Service not found"} BODY,
# which parsed as zero features and rendered as "no WA coverage" — a wrong endpoint
# disguised as a real geographic answer. Layer 1 = NEHRP Seismic Site Class,
# layer 0 = Liquefaction Susceptibility.
DNR = "https://gis.dnr.wa.gov/site1/rest/services/Public_Geology/Ground_Response/MapServer"
USGS = "https://earthquake.usgs.gov/ws/designmaps/asce7-22.json"
CENSUS = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"


def fixture():
    f = config.FIXTURES / "founders_hall.json"
    return json.loads(f.read_text()) if f.exists() else None


def is_demo_address(address):
    return PZ.house_number(address) == "4215" and "stevens way" in (address or "").lower()


UA = {"User-Agent": "quake-assess/1.0 (hackathon project; contact via github)"}


async def _get(client, url, **kw):
    """One attempt. A timeout, a 500, a 404 and a shape mismatch are all just
    'this tier did not answer' — one code path, one fallback."""
    try:
        kw.setdefault("headers", {}).update(UA)
        r = await client.get(url, **kw)
        if r.status_code != 200:
            return None
        d = r.json()
        # ArcGIS answers 200 with an error BODY. Without this check a bad endpoint
        # is indistinguishable from a point genuinely outside Washington.
        return None if isinstance(d, dict) and "error" in d and "features" not in d else d
    except Exception:
        return None


async def _post(client, url, data, **kw):
    """Overpass rejects the GET form with 406; it wants the query in the body."""
    try:
        kw.setdefault("headers", {}).update(UA)
        r = await client.post(url, content=data, **kw)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


async def _dnr(client, lat, lon, layer, timeout):
    return await _get(client, f"{DNR}/{layer}/query", timeout=timeout, params={
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "outFields": "*",
        "returnGeometry": "false", "f": "json"})


async def geocode(client, address):
    ll = PZ.census_latlon(await _get(client, CENSUS, timeout=config.TIMEOUT_GEOCODE,
        params={"address": address, "benchmark": "Public_AR_Current", "format": "json"}) or {})
    if ll:
        return ll
    r = await _get(client, NOMINATIM, timeout=config.TIMEOUT_GEOCODE,
                   headers={"User-Agent": "quake-assess/1.0 (hackathon project)"},
                   params={"q": address, "format": "json", "limit": 1})
    return PZ.nominatim_latlon(r) if r else None


async def resolve(address, offline=False):
    """Returns the normalised §4.7 object, or {"error": ...} stated honestly."""
    # The one address the demo depends on never touches the network.
    if is_demo_address(address) or offline and not address:
        f = fixture()
        if f:
            return f
    if offline:
        return {"error": "offline — only Founders Hall is available without a network",
                "tier": "offline", "address": address}

    async with httpx.AsyncClient(follow_redirects=True) as client:
        ll = await geocode(client, address)
        if not ll:
            return {"error": "couldn't locate that address", "tier": "live", "address": address}
        lat, lon = ll

        # Layer 1 gates USGS; layer 0 and Overpass gate nothing, so they run in
        # parallel rather than putting 3-8 s on the critical path for free.
        sc_task = asyncio.create_task(_dnr(client, lat, lon, 1, config.TIMEOUT_DNR))
        lq_task = asyncio.create_task(_dnr(client, lat, lon, 0, config.TIMEOUT_DNR))
        ov_task = asyncio.create_task(_post(
            client, OVERPASS, timeout=config.TIMEOUT_OVERPASS,
            data=f'[out:json][timeout:20];way(around:{config.OVERPASS_RADIUS_M},'
                 f'{lat},{lon})["building"];out geom tags;'))

        raw_sc = await sc_task
        code = PZ.dnr_site_class(raw_sc) if raw_sc else None
        assumed = code is None
        site_class = PZ.validate_site_class(code)

        usgs = await _get(client, USGS, timeout=config.TIMEOUT_USGS, params={
            "latitude": lat, "longitude": lon, "riskCategory": config.USGS_RISK_CATEGORY,
            "siteClass": site_class, "title": "quake-assess"})
        raw_lq, raw_ov = await lq_task, await ov_task

    return {
        "address": address, "latitude": lat, "longitude": lon,
        "site_class": None if assumed else code,
        "site_class_assumed": assumed,
        "site_class_used": site_class,
        "liquefaction_susceptibility": PZ.dnr_liquefaction(raw_lq) if raw_lq else None,
        "usgs_spectrum": PZ.usgs_spectrum(usgs) if usgs else None,
        "building_footprint": PZ.overpass_building(raw_ov, address, lat, lon) if raw_ov else None,
        "tier": "live",
    }
