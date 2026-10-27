"""Parsing tests on a saved API answer: fast, no network. tests/pages/ogd-roc-wise-0.json is a real answer (limit=1)."""
import json
from pathlib import Path

import crawl

PAGES = Path(__file__).parent / "pages"


def load(name):
    return json.loads((PAGES / name).read_text(encoding="utf-8"))


def test_a_real_row_becomes_a_company_keyed_by_cin():
    [(cin, c)] = crawl.parse(load("ogd-roc-wise-0.json"))
    assert cin == "U27900GJ2025PTC166696"
    assert c["name"] == "EMSGLOB TECHNOLOGIES PRIVATE LIMITED" and c["status"] == "Active" and c["class"] == "Private"
    assert c["category"] == "Company limited by shares" and c["subcategory"] == "Non-government company"
    assert c["authorized_capital"] == 500000 and c["paidup_capital"] == 500000
    assert c["registration_date"] == "2025-08-26" and c["registration_date_iso"] == "2025-08-26"
    assert c["address"].endswith("Vadodara,Gujarat,391240-India") and c["roc"] == "ROC Ahmedabad" and c["state"] == "gujarat"
    assert c["nic_code"] == "NA" and c["activity"] == "Manufacturing (Machinery and Equipments)"
    assert c["listing_status"] == "Unlisted"
    assert c["other"] == {"CompanyIndian/Foreign Company": "91"}


def test_state_and_nic_code_come_from_the_cin():
    [(_, c)] = crawl.parse(load("ogd-roc-wise-0.json"))
    assert (c["listing"], c["cin_nic_code"], c["state_code"], c["cin_year"], c["ownership"]) == ("U", "27900", "GJ", 2025, "PTC")


def test_older_column_spellings_map_to_the_same_fields():
    row = {"CORPORATE_IDENTIFICATION_NUMBER": "u72200mh2010ptc123456", "COMPANY_NAME": "X", "DATE_OF_REGISTRATION": "05-03-2010",
           "AUTHORIZED_CAP": "1,00,000", "REGISTRAR_OF_COMPANIES": "RoC-Pune", "EMAIL_ADDR": "a@b.c"}
    [(cin, c)] = crawl.parse({"records": [row, {"COMPANY_NAME": "no CIN"}]})
    assert cin == "U72200MH2010PTC123456" and c["registration_date_iso"] == "2010-03-05"
    assert c["authorized_capital"] == 100000 and c["roc"] == "RoC-Pune" and c["other"] == {}      # e-mail is dropped


def test_an_error_answer_gives_nothing():
    assert crawl.parse({"error": "Too many requests"}) == []
    assert crawl.parse({"records": []}) == []
