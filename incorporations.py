"""The `incorporations` task (see scrape.json), project mca-incorporations (F03): companies, LLPs and foreign companies registered
each month, from MCA's monthly Excel files ("Incorporated Or Closed During The Month", www.mca.gov.in).

One queue item = one report month (f03_reports.json, built by f03_reports.py). The task downloads the month's workbook from the
site's document store (mcaportal: curl_cffi with a browser fingerprint, because Akamai refuses plain clients), keeps it in the
family's bucket (xlsx/<YYYY>/<YYYY-MM>.xlsx), and stores one record per entity (incorp.parse), keyed by CIN / LLPIN / FCIN.
The store has no content for the oldest files (up to June 2021): such an item is done with 0 records and an `empty_document`
failure on the dashboard, so it is not retried without end.

Try it without the hub:
    .venv/bin/python incorporations.py --local 2026-10 [--save DIR]      # a month from f03_reports.json
"""
import hashlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import incorp
import mcaportal

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
BUDGET = float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600
DEADLINE = time.time() + BUDGET - min(300, 0.1 * BUDGET)
RESERVE = min(600, 0.2 * BUDGET)          # one month: a 1-3 MB download and ~25,000 records


def do_month(hub, portal, payload, save=None):
    """Download, keep and parse one monthly file. Returns the number of records stored."""
    month = payload["month"]
    name, body = portal.document(payload["doc_id"])
    if body[:2] != b"PK":
        raise mcaportal.SiteError(f"not an xlsx file ({len(body)} bytes, starts {body[:20]!r})")
    hub.metric("files")
    hub.metric("file_bytes", len(body))
    path = f"xlsx/{month[:4]}/{month}.xlsx"
    facts = {"report_month": month, "report_title": payload.get("title"), "report_published": payload.get("published"),
             "source": f"{mcaportal.SITE}{mcaportal.MONTHLY_PAGE}", "source_file": name, "xlsx_path": path,
             "xlsx_sha256": hashlib.sha256(body).hexdigest()}
    recs = incorp.parse(body, facts)
    if save:
        Path(save).mkdir(parents=True, exist_ok=True)
        (Path(save) / f"{month}.xlsx").write_bytes(body)
    elif hasattr(hub, "upload_many"):
        hub.upload_many([(path, body, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")])
    for rid, data in recs:
        hub.record(rid, data)
    for kind, n in Counter(d["kind"] for _, d in recs).items():
        hub.metric(f"rows_{kind}", n)
    hub.metric("rows_without_date", sum(1 for _, d in recs if not d["registration_date"]))
    hub.metric("rows_outside_month", sum(1 for _, d in recs if d["registration_date"] and d["registration_date"][:7] != month))
    return len(recs)


class LocalHub:
    """Stand-in for HubClient so --local runs without the hub: records to stdout (or a count), counters to stderr."""
    settings = {"threads": 1, "delay_ms": 500, "paused": False}

    def __init__(self, quiet=False):
        self.counts = Counter()
        self.quiet = quiet

    def metric(self, name, value=1):
        self.counts[name] += value

    def error(self, n=1):
        self.metric("errors", n)

    def block(self, n=1):
        self.metric("blocked", n)

    def record(self, rid, data):
        if not self.quiet:
            print(json.dumps({"record_id": rid, "data": data}, ensure_ascii=False))


def local(args):
    reports = {i["month"]: i for i in json.loads(Path(__file__).with_name("f03_reports.json").read_text())}
    save = args[args.index("--save") + 1] if "--save" in args else None
    hub = LocalHub(quiet="--count" in args)
    portal = mcaportal.Portal(hub)
    for month in [a for a in args if a in reports]:
        try:
            n = do_month(hub, portal, reports[month], save=save)
            print(f"{month}: {n} records", file=sys.stderr)
        except mcaportal.SiteError as e:
            print(f"{month}: {type(e).__name__}: {e}", file=sys.stderr)
    print(f"counters {dict(hub.counts)}", file=sys.stderr)


def main():
    from scrape_hub_client import HubClient        # imported here so --local works without it
    hub = HubClient(PROJECT, job_index=int(os.environ.get("SCRAPE_JOB_INDEX", "0")),
                    total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", "1")))
    portal = mcaportal.Portal(hub)
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
                n = do_month(hub, portal, item["payload"])
            except mcaportal.EmptyDocument as e:
                hub.failure("empty_document", item["key"], str(e), title=item["payload"].get("title"))
                hub.complete([item["key"]], "done", fetched=0)
                continue
            except mcaportal.SiteError as e:
                hub.failure("download", item["key"], str(e)[:200], title=item["payload"].get("title"))
                hub.complete([item["key"]], "failed", error=str(e)[:200])
                time.sleep(10)
                continue
            hub.clear_failure("download", item["key"])
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
