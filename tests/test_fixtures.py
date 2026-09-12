"""Gate 0: the six captured payloads parse and still say what the plan says.

These are committed fixtures, so this is a regression test against someone
re-capturing or re-shaping them, not a check on a live API.
"""
import json
import pytest
from backend import config

RAW = {
    "census_geocode": "Census geocoder",
    "nominatim": "Nominatim (fallback)",
    "dnr_site_class": "WA DNR",
    "dnr_liquefaction": "WA DNR",
    "usgs_asce7_22": "USGS",
    "overpass_footprint": "Overpass",
}


def load(name):
    # Every fixture is {"_fixture": {...}, "response": {...}} — read ["response"].
    return json.loads((config.FIXTURES / f"founders_hall_{name}.json").read_text())


@pytest.mark.parametrize("name", RAW)
def test_fixture_parses_and_was_a_200(name):
    d = load(name)
    assert d["_fixture"]["http_status"] == 200
    assert d["response"] is not None


def test_census_does_not_resolve_the_campus_address():
    # Structural gap, not a hiccup: this is why Founders Hall never geocodes live.
    assert load("census_geocode")["response"]["result"]["addressMatches"] == []


def test_nominatim_resolves_to_the_right_building():
    r = load("nominatim")["response"][0]
    assert r["osm_id"] == 222831279
    assert float(r["lat"]) == pytest.approx(47.6588, abs=5e-4)
    assert float(r["lon"]) == pytest.approx(-122.3072, abs=5e-4)


def test_site_class_comes_from_layer_1():
    a = load("dnr_site_class")["response"]["features"][0]["attributes"]
    assert a["SEISMIC_SITE_CLASS_CD"] == "C"


def test_liquefaction_comes_from_layer_0_and_is_a_string():
    a = load("dnr_liquefaction")["response"]["features"][0]["attributes"]
    assert a["LIQUEFACTION_SUSCEPT"] == "very low"
    assert "SEISMIC_SITE_CLASS_CD" not in a


def test_usgs_scalars_are_lowercase_and_exact():
    d = load("usgs_asce7_22")["response"]["response"]["data"]
    assert (d["sds"], d["sd1"], d["t0"], d["ts"], d["sdc"], d["tl"]) == (
        1.03, 0.56, 0.109, 0.546, "D", 6)
    assert "Fa" not in d and "Fv" not in d          # they do not exist in this response
    assert "twoPeriodDesignSpectrum" in d           # the ONLY one the score may use


def test_overpass_is_founders_hall_not_paccar():
    e = load("overpass_footprint")["response"]["elements"][0]
    assert e["id"] == 222831279
    assert e["tags"]["addr:housenumber"] == "4215"   # 4295 would be Paccar Hall
    assert e["tags"]["building:levels"] == "5"


def test_normalised_tier3_file_is_self_consistent():
    s = json.loads((config.FIXTURES / "founders_hall.json").read_text())
    assert s["tier"] == "fixture"
    assert s["site_class"] == "C" and s["site_class_assumed"] is False
    assert s["building_footprint"]["address_matched"] is True
    assert len(s["building_footprint"]["geometry"]) >= 3   # a real polygon
    assert s["usgs_spectrum"]["sds"] == 1.03
