"""R4-R7 against recorded payloads. No test may make a network call.

A suite that fails because the venue WiFi is slow is a suite nobody runs after 11 AM.
"""
import json
import pytest
from backend import config
from backend.site import parsers as PZ
from backend.site import resolve as R

load = lambda n: json.loads((config.FIXTURES / f"founders_hall_{n}.json").read_text())


def test_R6_usgs_lowercase_fields_and_the_right_spectrum():
    sp = PZ.usgs_spectrum(load("usgs_asce7_22"))
    assert (sp["sds"], sp["sd1"], sp["t0"], sp["ts"], sp["sdc"]) == (1.03, 0.56, 0.109, 0.546, "D")
    assert "Fa" not in sp and "Fv" not in sp        # they do not exist in this response
    assert sp["two_period"][0].keys() == {"period_s", "sa_g"}   # converted from parallel arrays
    assert len(sp["two_period"]) > 50


def test_R7_dnr_layers_are_not_interchangeable():
    assert PZ.dnr_site_class(load("dnr_site_class")) == "C"
    assert PZ.dnr_liquefaction(load("dnr_liquefaction")) == "very low"
    # Layer 0 carries no site class, layer 1 carries no liquefaction.
    assert PZ.dnr_site_class(load("dnr_liquefaction")) is None
    assert PZ.dnr_liquefaction(load("dnr_site_class")) is None


def test_no_wa_coverage_is_an_empty_feature_list_not_an_error():
    assert PZ.dnr_site_class({"features": []}) is None


def test_R4_address_match_beats_nearest_centroid():
    """The real failure: querying the originally documented coordinate with
    around:30 returned PACCAR Hall, not Founders, because that coordinate was
    ~60-70 m off. Hand-built two-element payload because the committed Overpass
    fixture holds only one element and so cannot prove the discrimination."""
    payload = {"elements": [
        {"id": 222831276, "tags": {"building": "university", "addr:housenumber": "4295",
                                   "name": "Paccar Hall", "building:levels": "4"},
         "geometry": [{"lat": 47.6591, "lon": -122.3080}] * 4},          # NEARER
        {"id": 222831279, "tags": {"building": "university", "addr:housenumber": "4215",
                                   "name": "Founders Hall", "building:levels": "5"},
         "geometry": [{"lat": 47.6588, "lon": -122.3072}] * 4},
    ]}
    b = PZ.overpass_building(payload, config.FOUNDERS_HALL_ADDRESS, 47.6591, -122.3080)
    assert b["source_way_id"] == 222831279 and b["address_matched"] is True
    assert b["levels"] == 5
    # With no address to match on, it falls back to nearest — and picks the wrong
    # one. That is exactly why nearest-centroid is the fallback, not the primary.
    b2 = PZ.overpass_building(payload, None, 47.6591, -122.3080)
    assert b2["source_way_id"] == 222831276 and b2["address_matched"] is False


def test_overpass_real_fixture_is_founders_with_a_real_polygon():
    b = PZ.overpass_building(load("overpass_footprint"), config.FOUNDERS_HALL_ADDRESS)
    assert b["source_way_id"] == 222831279 and b["levels"] == 5
    assert len(b["geometry"]) >= 3


def test_site_class_enum_falls_back_explicitly_never_to_usgs_default():
    assert PZ.validate_site_class("C") == "C"
    assert PZ.validate_site_class("CD") == "CD"          # compound values are valid
    assert PZ.validate_site_class("Z") == "D"            # never "BC", USGS's magic default
    assert PZ.validate_site_class(None) == "D"


def test_census_empty_and_nominatim_fallback():
    assert PZ.census_latlon(load("census_geocode")) is None       # structural gap
    lat, lon = PZ.nominatim_latlon(load("nominatim"))
    assert (round(lat, 3), round(lon, 3)) == (47.659, -122.307)


def test_demo_address_short_circuits_to_the_fixture():
    assert R.is_demo_address(config.FOUNDERS_HALL_ADDRESS)
    assert not R.is_demo_address("4295 E Stevens Way NE, Seattle, WA 98195")


def test_offline_refuses_other_addresses_honestly():
    import asyncio
    d = asyncio.run(R.resolve("400 Broad St, Seattle, WA", offline=True))
    assert "error" in d and d["tier"] == "offline"


def test_founders_resolves_offline_with_no_network():
    import asyncio
    d = asyncio.run(R.resolve(config.FOUNDERS_HALL_ADDRESS, offline=True))
    assert d["site_class"] == "C" and d["tier"] == "fixture"
    assert d["usgs_spectrum"]["sds"] == 1.03


def test_founders_hall_makes_ZERO_network_calls(monkeypatch):
    """Gate 9's offline rehearsal, made executable.

    The flag is not the proof — this is. Any attempt to open an HTTP client while
    resolving the demo address raises, so the test fails loudly if a future change
    puts a live call on the one path the 5:45 PM demo depends on. Founders Hall must
    resolve from a local file whether or not the hotspot is alive.
    """
    import asyncio
    import httpx

    def boom(*a, **k):
        raise AssertionError("the demo address must never touch the network")

    monkeypatch.setattr(httpx, "AsyncClient", boom)
    d = asyncio.run(R.resolve(config.FOUNDERS_HALL_ADDRESS, offline=False))
    assert d["site_class"] == "C"
    assert d["usgs_spectrum"]["sds"] == 1.03
    assert d["building_footprint"]["levels"] == 5
    assert d["tier"] == "fixture"


def test_the_boot_measurement_also_needs_no_network(monkeypatch):
    """The other half of a cold start with a dead hotspot: `pinned` must resolve
    too, or Verdict, 3D and Retrofit boot with nothing to render."""
    import httpx
    from backend import store

    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    m = store.load_pinned()
    assert m is not None and m["frequency_hz"] is not None
    assert m["source"] in ("hardware", "simulated", "replay")
