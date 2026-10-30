from app import config
from app.rules import soil as soil_rule
from app.sources import soil as soil_src

from .conftest import load_fixture


def props(sand=None, clay=None, ph=None, soc=None):
    return {"sand": {"value": sand}, "clay": {"value": clay}, "phh2o": {"value": ph}, "soc": {"value": soc}}


def test_conversion_uses_d_factor():
    p = soil_src.convert(load_fixture("soil_dharwad_nearby.json"))
    assert p["phh2o"]["value"] == p["phh2o"]["raw"] / 10
    assert p["clay"]["unit"] == "%" and p["clay"]["value"] == p["clay"]["raw"] / 10
    assert p["soc"]["unit"] == "g/kg"
    assert 3 < p["phh2o"]["value"] < 10  # a converted pH, not pH x 10


def test_urban_pixel_has_no_values():
    p = soil_src.convert(load_fixture("soil_dharwad_center_null.json"))
    assert not soil_src.has_values(p)
    assert soil_rule.evaluate(p)["status"] == "unknown"


def test_high_sand_and_clay_flags():
    assert soil_rule.evaluate(props(sand=config.SOIL_SAND_HIGH_PCT + 5, clay=10, ph=7))["flags"] == ["high_sand"]
    assert soil_rule.evaluate(props(sand=20, clay=config.SOIL_CLAY_HIGH_PCT + 5, ph=7))["flags"] == ["high_clay"]


def test_ph_flags():
    assert "acidic" in soil_rule.evaluate(props(sand=30, clay=30, ph=5.0))["flags"]
    assert "alkaline" in soil_rule.evaluate(props(sand=30, clay=30, ph=9.0))["flags"]
    assert soil_rule.evaluate(props(sand=30, clay=30, ph=7.0))["status"] == "ok"


def test_missing_values_listed():
    res = soil_rule.evaluate(props(sand=30))
    assert res["missing"] == ["clay", "pH"]


def test_real_dharwad_soil_is_ok():
    res = soil_rule.evaluate(soil_src.convert(load_fixture("soil_dharwad_nearby.json")))
    assert res["status"] in {"ok", "flags"} and res["ph"] is not None


def test_distance():
    assert soil_src.distance_km(15.46, 75.0, 15.48, 75.0) == 2.2
