"""Build f03_reports.json: the monthly "Companies and LLPs registered in <month>" Excel files on mca.gov.in (F03 queue items).

Run on a team box (www.mca.gov.in answers from Germany too): .venv/bin/python f03_reports.py
Re-run it each month after MCA adds the new file (around the 1st-5th), commit, and run the Setup workflow: existing keys stay.
One item per report month (key YYYY-MM). The month comes from the title; a title without a year ("... in June.xlsx") takes the year
of the publication date (the month before it).
"""
import json
import re
import sys
from pathlib import Path

import mcaportal

OUT = Path(__file__).with_name("f03_reports.json")
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MONTH = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b\W{0,3}((?:19|20)\d\d)?", re.I)


def report_month(title, published):
    """'Companies and LLPs registered in October' 2026', '05-11-2026' -> '2026-10'. Pure."""
    found = MONTH.findall(re.sub(r"\.xlsx?$", "", title, flags=re.I))
    if not found:
        return None
    mon, year = found[-1]
    m = MONTHS[mon[:3].lower()]
    pd, pm, py = (int(x) for x in published.split("-"))
    y = int(year) if year else (py if m < pm else py - 1)
    return f"{y}-{m:02d}"


class Quiet:
    settings = {"delay_ms": 500}

    def metric(self, *a):
        pass

    def block(self, *a):
        pass

    def error(self, *a):
        pass


def items(docs):
    out = {}
    for d in docs:
        month = report_month(d["column1"], d["docDate"] or d["column2"])
        if not month:
            print("no month in title:", d["column1"], file=sys.stderr)
            continue
        if month in out:
            print(f"{month}: second file {d['column1']!r} ({d['docDate']}) not used", file=sys.stderr)
            continue
        out[month] = {"month": month, "title": d["column1"].strip(), "published": d["docDate"] or d["column2"],
                      "doc_id": d["docID"], "doc_type": d["docType"], "doc_size": d["docSize"]}
    return sorted(out.values(), key=lambda i: i["month"])


if __name__ == "__main__":
    docs = mcaportal.Portal(Quiet()).documents(mcaportal.FOLDER_REGISTERED)
    reports = items(docs)
    OUT.write_text(json.dumps(reports, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(docs)} documents, {len(reports)} months ({reports[0]['month']} .. {reports[-1]['month']}) -> {OUT.name}")
