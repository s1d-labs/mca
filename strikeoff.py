"""The `strikeoff` task (see scrape.json), project mca-strikeoff (F04): ROC strike-off notices in the weekly Gazette of India.

One queue item = one weekly Part III-Section 1 issue (f04_issues.json, built by f04_issues.py). The task downloads the issue's PDF
from egazette.gov.in (egazette.py), keeps it and its text in the family's bucket (pdf/<year>/<id>.pdf, text/<year>/<id>.txt.gz),
and stores one record per company or LLP per notice form (stk.parse): STK-1/5/6 (proposed), STK-7 (struck off, with the date),
LLP strike-offs and section 560 notices of the 1956 Act. An issue without strike-off notices is done with 0 records.

egazette.gov.in answers only from India: the pool runs this through the hub's Indian proxies (set_pool(..., proxy="IN")).

Try it without the hub (from the box, through a proxy):
    myproxy run .venv/bin/python strikeoff.py --local <gazette_id> [--save DIR]      # an id from f04_issues.json
"""
import gzip
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import egazette
import stk

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
BUDGET = float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600
DEADLINE = time.time() + BUDGET - min(300, 0.1 * BUDGET)
RESERVE = min(600, 0.2 * BUDGET)          # one issue takes a few minutes at most (a 15 MB PDF, 1,700 pages of text)


def gazette_facts(payload, url, path):
    return {"gazette_id": payload["gazette_id"], "issue_date": payload.get("issue_date"), "part_section": "Part III-Section 1",
            "source_url": url, "pdf_path": path}


def do_issue(hub, payload, save=None):
    """Download, keep and parse one issue. Returns the number of records stored."""
    site = egazette.Site(hub)
    url, body = site.pdf(payload["serial"], payload["publish_date"], payload.get("issue_date"))
    year = (payload.get("issue_date") or payload["publish_date"])[:4]
    path = f"pdf/{year}/{payload['gazette_id']}.pdf"
    pages = stk.text_of(body)
    text = "\f".join(pages)
    hub.metric("pdfs")
    hub.metric("pdf_bytes", len(body))
    hub.metric("pdf_pages", len(pages))
    if not text.strip():
        hub.metric("pdf_no_text")                  # a scan: no text layer (needs OCR)
    recs = stk.parse(pages, gazette_facts(payload, url, path))
    if save:
        Path(save).mkdir(parents=True, exist_ok=True)
        (Path(save) / f"{payload['gazette_id']}.pdf").write_bytes(body)
        (Path(save) / f"{payload['gazette_id']}.txt").write_text(text, encoding="utf-8")
    elif hasattr(hub, "upload_many"):
        up = hub.upload_many([(path, body, "application/pdf"),
                              (f"text/{year}/{payload['gazette_id']}.txt.gz", gzip.compress(text.encode()), "application/gzip")])
        for u in up:
            if u["path"] == path:
                for _, d in recs:
                    d["pdf_sha256"] = u.get("sha256")
    for rid, data in recs:
        hub.record(rid, data)
    forms = Counter(d["form"] for _, d in recs)
    for form, n in forms.items():
        hub.metric(f"rows_{form.lower().replace('(', '').replace(')', '').replace('-', '')}", n)
    hub.metric("rows_without_name", sum(1 for _, d in recs if not d["company_name"]))
    hub.metric("rows_without_date", sum(1 for _, d in recs if not d["notice_date"]))
    return len(recs)


class LocalHub:
    """Stand-in for HubClient so --local runs without the hub: records to stdout, counters to stderr."""
    settings = {"threads": 1, "delay_ms": 300, "paused": False}

    def __init__(self):
        self.counts = Counter()

    def metric(self, name, value=1):
        self.counts[name] += value

    def error(self, n=1):
        self.metric("errors", n)

    def block(self, n=1):
        self.metric("blocked", n)

    def record(self, rid, data):
        print(json.dumps({"record_id": rid, "data": data}, ensure_ascii=False))


def local(args):
    issues = {i["gazette_id"]: i for i in json.loads(Path(__file__).with_name("f04_issues.json").read_text())}
    hub = LocalHub()
    save = args[args.index("--save") + 1] if "--save" in args else None
    n = do_issue(hub, issues[args[0]], save=save)
    print(f"{n} records, counters {dict(hub.counts)}", file=sys.stderr)


def main():
    from scrape_hub_client import HubClient        # imported here so --local works without it
    hub = HubClient(PROJECT, job_index=int(os.environ.get("SCRAPE_JOB_INDEX", "0")),
                    total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", "1")))
    try:
        while time.time() < DEADLINE - RESERVE:
            if hub.settings.get("paused"):
                time.sleep(30)
                continue
            items = hub.claim(1, steal=True, retry_failed=True)
            if not items:
                break
            item = items[0]
            try:
                n = do_issue(hub, item["payload"])
            except egazette.SiteError as e:
                hub.failure("pdf", item["key"], str(e)[:200], issue_date=item["payload"].get("issue_date"))
                hub.complete([item["key"]], "failed", error=str(e)[:200])
                time.sleep(10)
                continue
            hub.complete([item["key"]], "done", fetched=n)
        hub.close()
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


if __name__ == "__main__":
    if sys.argv[1:2] == ["--local"]:
        local(sys.argv[2:])
    else:
        main()
