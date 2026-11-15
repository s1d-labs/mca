"""Parsing of MCA's monthly "Companies and LLPs registered" workbooks (F03, incorp.py) on real files cut to a few rows per sheet
(tests/pages/f03-<month>.xlsx, e-mails blanked), one per layout. Fast, no network."""
from pathlib import Path

import incorp
from f03_reports import report_month

PAGES = Path(__file__).parent / "pages"


def recs(month):
    out = incorp.parse((PAGES / f"f03-{month}.xlsx").read_bytes(), {"report_month": month})
    return dict(out)


def test_2026_short_layout_has_three_kinds():
    r = recs("2026-10")
    kinds = {d["kind"] for d in r.values()}
    assert kinds == {"company", "llp", "foreign"}
    d = r["U01110AS2026PTC031427"]
    assert d["name"] == "KALIAJULI AGAN FARMER PRODUCER COMPANY LIMITED" and d["registration_date"] == "2026-10-01"
    assert d["class"] == "Private" and d["company_type"] == "Non-government company" and d["activity_code"] == "01"
    assert d["state_code"] == "AS" and d["cin_year"] == 2026 and d["ownership"] == "PTC" and d["cin"] == d["id"]
    assert d["report_month"] == "2026-10" and d["other"] == {}
    llp = r["ADC-8302"]
    assert llp["kind"] == "llp" and llp["llpin"] == "ADC-8302" and llp["cin"] is None and llp["activity_code"] == "70"
    assert r["F07088"]["kind"] == "foreign" and r["F07088"]["registration_date"] == "2026-10-31"


def test_2016_foreign_sheet_with_a_cin_column_and_long_llp_headers():
    r = recs("2016-06")
    f = r["F06067"]
    assert f["kind"] == "foreign" and f["fcin"] == "F06067" and f["office_type"] == "Liaison Office"
    assert f["registration_date"] == "2016-06-27" and f["activity_code"] == "74"
    llp = r["AAF-1278"]
    assert llp["name"] == "SALIAN TOURS AND TECHNOLOGIES LLP" and llp["obligation_of_contribution"] == 100000
    assert llp["partners"] == 0 and llp["designated_partners"] == 2 and llp["registration_date"] == "2016-06-03"
    c = r["U74990AP2016PTC103381"]
    assert c["authorized_capital"] == 10000000 and c["category"] == "Companies Limited by Shares" and c["other"] == {}


def test_capital_in_thousand_rupees_is_converted_and_emails_are_dropped():
    r = recs("2019-03")
    c = r["U17299GJ2019PTC106990"]
    assert c["paidup_capital"] % 1000 == 0 and c["authorized_capital"] >= 100000
    assert c["activity_code"] == "17299" and c["roc"] == "ROC - AHMEDABAD" and c["registration_date"] == "2019-03-08"
    assert not any("mail" in k.lower() for d in r.values() for k in list(d) + list(d["other"]))
    llp = r["AAO-4130"]
    assert llp["activity_code"] == "52" and llp["activity_group"].startswith("Retail trade")


def test_2018_llp_activity_code_prefix_is_removed():
    r = recs("2018-10")
    codes = [d["activity_code"] for d in r.values() if d["kind"] == "llp"]
    assert codes and all(c.isdigit() for c in codes)


def test_month_name_dates_and_main_description():
    r = recs("2022-06")
    llp = r["ABB-2437"]
    assert llp["registration_date"] == "2022-06-01" and llp["activity_group"] == "Construction"
    assert llp["activity_detail"] == "Other specialized construction activities" and llp["designated_partners"] == 4
    assert r["F06734"]["office_type"] == "Branch Office"


def test_2023_wide_layout():
    r = recs("2023-10")
    c = next(d for d in r.values() if d["kind"] == "company")
    assert c["status"] == "Active" and c["activity_group"] and c["activity_detail"] and c["address"] and c["state"]


def test_report_month_from_title():
    assert report_month("Companies and LLPs registered in October' 2026", "05-11-2026") == "2026-10"
    assert report_month("Indian Companies Foreign Companies Register in Sep 2022", "06-10-2022") == "2022-09"
    assert report_month("Indian Companies_Foreign Companies Register in June.xlsx", "04-07-2022") == "2022-06"
    assert report_month("Companies and LLPs registered in December' 2025", "01-01-2026") == "2025-12"
    assert report_month("Master Details of Companies/LLPs Registered -January, 2016", "05-02-2016") == "2016-01"
