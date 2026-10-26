"""Parsing tests on a saved API answer: fast, no network. tests/pages/ogd-synthetic.json is synthetic (the API was not reachable
when this was written); save a real answer next to it (python crawl.py --local <resource id> shows the columns) and test that too."""
import json
from pathlib import Path

import crawl

PAGES = Path(__file__).parent / "pages"


def load(name):
    return json.loads((PAGES / name).read_text(encoding="utf-8"))


def test_rows_become_companies_keyed_by_cin():
    rows = crawl.parse(load("ogd-synthetic.json"))
    assert [cin for cin, _ in rows] == ["U72200MH2010PTC123456", "L85110KA1981PLC000001"]   # the row without a CIN is skipped
    _, c = rows[0]
    assert c["name"] == "EXAMPLE SOFTWARE PRIVATE LIMITED" and c["status"] == "ACTIVE" and c["class"] == "Private"
    assert c["authorized_capital"] == 100000 and c["paidup_capital"] == 100000
    assert c["registration_date"] == "05-03-2010" and c["registration_date_iso"] == "2010-03-05"
    assert c["address"] == "1 Example Road, Pune 411001" and c["roc"] == "RoC-Pune" and c["state"] == "Maharashtra"
    assert c["nic_code"] == "72200" and c["activity"] == "Business Services"
    assert c["other"] == {"LATEST_YEAR_ANNUAL_RETURN": "2022"}                               # e-mail is dropped


def test_other_column_names_map_to_the_same_fields():
    _, c = crawl.parse(load("ogd-synthetic.json"))[1]
    assert c["name"] == "EXAMPLE TECH LIMITED" and c["class"] == "Public" and c["state"] == "Karnataka"
    assert c["registration_date_iso"] == "1981-07-02" and c["paidup_capital"] == 2070000000.5
    assert c["nic_code"] == "85110" and c["roc"] == "RoC-Bangalore" and c["address"] == "Example Campus, Bengaluru"


def test_state_and_nic_code_come_from_the_cin():
    _, c = crawl.parse(load("ogd-synthetic.json"))[0]
    assert (c["listing"], c["cin_nic_code"], c["state_code"], c["cin_year"], c["ownership"]) == ("U", "72200", "MH", 2010, "PTC")


def test_an_error_answer_gives_nothing():
    assert crawl.parse({"message": "Invalid key"}) == []
    assert crawl.parse({"records": []}) == []
