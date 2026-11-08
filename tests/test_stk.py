"""Parsing of strike-off notices (F04, stk.py) on text excerpts of real Gazette of India issues (Part III-Section 1), as
pypdfium2 gives it. Fast, no network."""
from pathlib import Path

import stk

PAGES = Path(__file__).parent / "pages"


def recs(name, issue_date, gid="G"):
    text = (PAGES / f"{name}.txt").read_text(encoding="utf-8")
    out = stk.parse([text], {"gazette_id": gid, "issue_date": issue_date, "source_url": "u", "pdf_path": "p"})
    return {(d["cin"] or d["llpin"] or d["company_no"]): d for _, d in out}


def test_cpace_stk7_gives_struck_off_date_and_notice():
    r = recs("stk7-cpace-2026", "2026-10-24")
    assert len(r) == 7
    d = r["U64990AP2025PTC120006"]
    assert d["company_name"] == "BKR CHITS PRIVATE LIMITED" and d["form"] == "STK-7" and d["final"] is True
    assert d["roc"] == "C-PACE" and d["notice_no"] == "ROC/C-PACE/STK-2/248(5)/2026-27/1675"
    assert d["notice_date"] == "2026-10-21" and d["struck_off_date"] == "2026-10-21"
    assert d["gazette_id"] == "G" and d["issue_date"] == "2026-10-24" and d["source_url"] == "u" and d["pdf_path"] == "p"


def test_stk6_is_a_proposal_without_a_struck_off_date_and_wrapped_names_are_joined():
    r = recs("stk6-cpace-2026", "2026-10-24")
    assert len(r) == 7
    d = r["U45309AP2021PTC117447"]
    assert d["company_name"] == "GOPROPERTIEES URBAN SPACES PRIVATE LIMITED"
    assert d["form"] == "STK-6" and d["final"] is False and d["struck_off_date"] is None
    assert d["notice_no"] == "ROC/C-PACE/STK-2/248(2)/2026-27/1707"


def test_llp_strike_off_keyed_by_llpin():
    r = recs("llp-cpace-2026", "2026-10-24")
    assert len(r) == 6
    d = r["ACD-5670"]
    assert d["entity_type"] == "llp" and d["cin"] is None and d["llpin"] == "ACD-5670"
    assert d["company_name"] == "PRECIOUS WORLDINFRA LLP" and d["form"] == "LLP" and d["final"] is True
    assert d["struck_off_date"] == "2026-10-21"


def test_row_dates_in_month_first_order_and_names_on_the_line_after_the_cin():
    r = recs("stk7-chennai-2018", "2018-08-18")
    assert r["U72900TN2013PTC089577"]["company_name"] == "1 GBPS IT SOLUTIONSPRIVATE LIMITED"
    assert r["U72900TN2013PTC089577"]["struck_off_date"] == "2018-08-04"      # 8/4/2018 in an (MM/DD/YYYY) column
    assert r["U74999TN2012PTC088819"]["struck_off_date"] == "2018-08-09"
    assert r["U74999TN2013PTC092459"]["company_name"] == "1MARK EDUCATIONAL SOLUTIONS PRIVATE LIMITED"
    assert r["U74999TN2013PTC092459"]["struck_off_date"] == "2018-08-09"
    assert r["U72900TN2013PTC089577"]["notice_no"] == "ROC/CHN/STK-7/2018"       # printed above the FORM heading
    assert r["U72900TN2013PTC089577"]["roc"] == "ROC Chennai"


def test_name_printed_before_the_cin_and_wrapped():
    r = recs("stk7-guwahati-2021", "2021-12-25")
    assert len(r) == 14
    assert r["U45309AS2017PTC017854"]["company_name"] == "KDL GLOBAL PROJECTS PRIVATE LIMITED"
    assert r["U45201MZ2014PLC008277"]["company_name"] == "MIZORAM INFRASTRUCTURE DEVELOPMENT COMPANY LIMITED"
    assert r["U40108AS2018OPC018794"]["company_name"] == "ACCEAN CLEAN ENERGIES EVOLUTION (OPC) PRIVATE LIMITED"
    d = r["U26940ML2009PTC008378"]
    assert d["roc"] == "ROC Guwahati" and d["notice_date"] == "2021-12-16" and d["struck_off_date"] == "2021-12-16"


def test_1956_act_notices_with_company_numbers_and_with_cins():
    r = recs("s560-jaipur-2015", "2015-06-20")
    assert set(r) == {"022843", "035612", "026842"}
    d = r["035612"]
    assert d["cin"] is None and d["company_no"] == "035612" and d["form"] == "S560(5)" and d["final"] is True
    assert d["company_name"] == "KING ARTHUR HOSPITALITY AND SOLUTIONS RAJASTHAN PRIVATE LIMITED"
    assert d["roc"] == "ROC Jaipur" and d["struck_off_date"] == "2015-06-03"
    r = recs("s560-mumbai-2015", "2015-06-20")
    assert len(r) == 6
    d = r["U01403MH2010PTC201186"]
    assert d["company_name"] == "BHOOMIAJINKYA CROP AND AGRO SERVICES PRIVATE LIMITED" and d["form"] == "S560(5)"
    assert d["notice_no"] == "ROC/PT/FTE, 2011/560(5)/139" and d["notice_date"] == "2015-06-03"


def test_record_ids_are_stable_and_one_per_company_and_form():
    text = (PAGES / "stk7-cpace-2026.txt").read_text(encoding="utf-8")
    a = stk.parse([text, text], {"gazette_id": "G", "issue_date": "2026-10-24"})          # the Hindi and English copies
    assert len(a) == 7 and a[0][0] == "G:U10402AP2025PTC121805:STK-7"


def test_dates():
    assert stk.iso_date("21st October 2026") == "2026-10-21"
    assert stk.iso_date("8th day of August, 2018") == "2018-08-08"
    assert stk.iso_date("21.10.2026") == "2026-10-21"
    assert stk.month_first("", ["8/13/2018"], None) is True
    assert stk.month_first("", ["13/8/2018"], None) is False
    assert stk.month_first("", ["8/9/2018"], "2018-08-18") is True       # 8 Sep would be after the gazette's own date
