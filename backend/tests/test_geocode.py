from app.sources.geocode import pick_karnataka


def r(name, admin1, pop=None, cc="IN"):
    return {"name": name, "admin1": admin1, "admin2": "x", "country_code": cc,
            "latitude": 15.0, "longitude": 75.0, "population": pop}


def test_only_karnataka_kept():
    out = pick_karnataka([r("Dharwad", "Karnataka"), r("Dharwadih", "Jharkhand"), r("X", "Karnataka", cc="NP")])
    assert [p.name for p in out] == ["Dharwad"]


def test_larger_towns_first():
    out = pick_karnataka([r("Hubli", "Karnataka"), r("Hubballi", "Karnataka", 943788)])
    assert out[0].name == "Hubballi"


def test_empty_results():
    assert pick_karnataka(None) == [] and pick_karnataka([]) == []
