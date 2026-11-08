"""Download a whole OGD resource to local files, outside the pool (data.gov.in refuses GitHub runners; it answers Indian networks).
Uses crawl.fetch / crawl.parse, one request at a time with a pause between them.

  OGD_KEY=<key> OGD_PAGE=1000 python dump.py <resource id> <out dir>   # resumable: pages already in <out dir>/pages are skipped
  python dump.py --combine <out dir>                                  # -> companies.jsonl.gz, companies.csv.gz, summary.json
  python dump.py --llp <dump dir> <out dir>                           # LLPs only (LLPIN ids) -> llps.jsonl.gz, llps.csv.gz, summary.json

The RoC-wise Company Master Data resource holds companies, LLPs and foreign companies; data.gov.in has no separate LLP master
resource in the API, so the LLP master is the LLPIN rows of the same pages.

Each page is saved as <out dir>/pages/<offset>.json.gz (the API's raw rows). The run makes passes over the missing pages until
none are left (at most PASSES), and exits non-zero if some still are.
"""
import csv
import gzip
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

import requests

import crawl

DELAY = float(os.environ.get("DUMP_DELAY_S", "1"))     # pause between requests
TRIES = 8                                               # per page and pass; waits 15 s, 30 s, ... up to 10 min between tries
PASSES = 3
CSV_FIELDS = ["cin", "name", "status", "class", "category", "subcategory", "authorized_capital", "paidup_capital",
              "registration_date", "registration_date_iso", "address", "roc", "state", "state_code", "nic_code", "cin_nic_code",
              "activity", "listing_status"]
LLP_FIELDS = ["llpin", "name", "status", "registration_date", "registration_date_iso", "address", "roc", "state", "activity"]
LLPIN = re.compile(r"^[A-Z]{3}-\d{4}$")


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def page(hub, session, resource, offset, limit):
    """The raw rows at offset, retried with growing waits; None if every try failed."""
    for attempt in range(TRIES):
        doc = crawl.fetch(hub, session, resource, offset, limit)
        if doc is not None:
            return doc
        wait = min(600, 15 * 2 ** attempt)
        log(f"offset {offset}: try {attempt + 1} failed (counters {hub.counts}); waiting {wait} s")
        time.sleep(wait)
    return None


def dump(resource, out):
    pages = out / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    hub, session = crawl.LocalHub(), requests.Session()
    first = page(hub, session, resource, 0, 1)
    if first is None:
        sys.exit("the API did not answer")
    total = int(first["total"])
    log(f"{first.get('title')}: {total} rows, {crawl.PAGE} per request")
    for n in range(1, PASSES + 1):
        todo = [o for o in range(0, total, crawl.PAGE) if not (pages / f"{o:08d}.json.gz").exists()]
        log(f"pass {n}: {len(todo)} pages to fetch")
        if not todo:
            break
        start = time.time()
        for i, offset in enumerate(todo, 1):
            doc = page(hub, session, resource, offset, crawl.PAGE)
            if doc is not None:
                rows = doc.get("records") or []
                if len(rows) != min(crawl.PAGE, total - offset):
                    log(f"offset {offset}: {len(rows)} rows (expected {min(crawl.PAGE, total - offset)}); total now {doc.get('total')}")
                tmp = pages / f"{offset:08d}.json.gz.tmp"
                tmp.write_bytes(gzip.compress(json.dumps({"offset": offset, "total": doc.get("total"), "rows": rows},
                                                         ensure_ascii=False).encode()))
                tmp.replace(pages / f"{offset:08d}.json.gz")
            if i % 50 == 0 or i == len(todo):
                eta = (time.time() - start) / i * (len(todo) - i)
                log(f"pass {n}: {i}/{len(todo)} pages, eta {eta / 60:.0f} min, counters {hub.counts}")
            time.sleep(DELAY)
    missing = [o for o in range(0, total, crawl.PAGE) if not (pages / f"{o:08d}.json.gz").exists()]
    log(f"done: {total} rows expected, {len(missing)} pages missing {missing[:20]}")
    sys.exit(1 if missing else 0)


def combine(out):
    """All pages -> one record per CIN (the first seen), as JSONL and as a CSV of the main fields, plus counts per state."""
    seen, dups, rows, states = set(), 0, 0, Counter()
    totals = set()
    with gzip.open(out / "companies.jsonl.gz", "wt", encoding="utf-8") as js, \
         gzip.open(out / "companies.csv.gz", "wt", encoding="utf-8", newline="") as cs:
        w = csv.DictWriter(cs, CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for path in sorted((out / "pages").glob("*.json.gz")):
            doc = json.loads(gzip.decompress(path.read_bytes()))
            totals.add(doc.get("total"))
            rows += len(doc["rows"])
            for cin, data in crawl.parse({"records": doc["rows"]}):
                if cin in seen:
                    dups += 1
                    continue
                seen.add(cin)
                states[data.get("state_code") or data.get("state") or "?"] += 1
                js.write(json.dumps({"cin": cin, **data}, ensure_ascii=False) + "\n")
                w.writerow({"cin": cin, **data})
    summary = {"rows": rows, "companies": len(seen), "duplicate_rows": dups, "rows_without_cin": rows - len(seen) - dups,
               "api_totals_seen": sorted(t for t in totals if t is not None), "by_state_code": dict(states.most_common())}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    log(f"{len(seen)} companies from {rows} rows ({dups} duplicate rows); summary.json written")


def llps(src, out):
    """The LLPIN rows of src's pages -> one record per LLPIN in out, as JSONL and as a CSV of the LLP fields, plus counts."""
    out.mkdir(parents=True, exist_ok=True)
    seen, dups, rows, states, statuses = set(), 0, 0, Counter(), Counter()
    with gzip.open(out / "llps.jsonl.gz", "wt", encoding="utf-8") as js, \
         gzip.open(out / "llps.csv.gz", "wt", encoding="utf-8", newline="") as cs:
        w = csv.DictWriter(cs, LLP_FIELDS, extrasaction="ignore")
        w.writeheader()
        for path in sorted((src / "pages").glob("*.json.gz")):
            doc = json.loads(gzip.decompress(path.read_bytes()))
            rows += len(doc["rows"])
            for llpin, data in crawl.parse({"records": doc["rows"]}):
                if not LLPIN.match(llpin):
                    continue
                if llpin in seen:
                    dups += 1
                    continue
                seen.add(llpin)
                rec = {"llpin": llpin, **{f: data.get(f) for f in LLP_FIELDS[1:]}}
                states[rec["state"] or "?"] += 1
                statuses[rec["status"] or "?"] += 1
                js.write(json.dumps(rec, ensure_ascii=False) + "\n")
                w.writerow(rec)
    summary = {"source_rows": rows, "llps": len(seen), "duplicate_rows": dups, "by_status": dict(statuses.most_common()),
               "by_state": dict(states.most_common())}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    log(f"{len(seen)} LLPs from {rows} rows ({dups} duplicate rows); summary.json written")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--combine"] and len(sys.argv) == 3:
        combine(Path(sys.argv[2]))
    elif sys.argv[1:2] == ["--llp"] and len(sys.argv) == 4:
        llps(Path(sys.argv[2]), Path(sys.argv[3]))
    elif len(sys.argv) == 3:
        dump(sys.argv[1], Path(sys.argv[2]))
    else:
        sys.exit(__doc__)
