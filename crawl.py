"""The family's `crawl` task (see scrape.json). Try it without the hub: python crawl.py --local <resource id> [offset]
The pool worker runs it with the assignment's env (OGD_API, OGD_KEY, OGD_PAGE from family.py) and:
SCRAPE_POOL_PROJECT (which project), SCRAPE_JOB_INDEX / SCRAPE_TOTAL_JOBS (this worker's slice), SCRAPE_MAX_HOURS (time budget).

Each queue item is a chunk of a data.gov.in OGD resource (offset + rows). The task pages through it OGD_PAGE rows per request,
stores one record per company keyed by CIN, keeps the chunk's raw API rows in the family's bucket (the hub signs the upload; this
code never holds a storage key), and reports the standard counters (n_http, t_http_s, http_error, http_<code>).
"""
import gzip
import json
import os
import re
import sys
import time

import requests

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
API = os.environ.get("OGD_API", "https://api.data.gov.in")
KEY = os.environ.get("OGD_KEY", "579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b")
PAGE = int(os.environ.get("OGD_PAGE", "10"))
DEADLINE = time.time() + float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600 - 120
UA = "s1d-labs scraper (https://github.com/s1d-labs)"

# CIN: listing (L/U), 5-digit NIC industry code, 2-letter state, year of incorporation, ownership class (PLC, PTC, GOI, ...), number
CIN = re.compile(r"^([LU])(\d{5})([A-Z]{2})(\d{4})([A-Z]{3})(\d{6})$")

# output field -> column names it may have in the API, compared after lower-casing and dropping everything but a-z 0-9
COLUMNS = {
    "cin": ["corporateidentificationnumber", "cin", "companycin"],
    "name": ["companyname", "name"],
    "status": ["companystatus", "status"],
    "class": ["companyclass", "class"],
    "category": ["companycategory", "category"],
    "subcategory": ["companysubcategory", "subcategory"],
    "authorized_capital": ["authorizedcapital", "authorizedcap", "authorisedcapital", "authorisedcap"],
    "paidup_capital": ["paidupcapital", "paidupcap"],
    "registration_date": ["dateofregistration", "companyregistrationdate", "registrationdate", "companyregistrationdatedate"],
    "address": ["registeredofficeaddress", "companyregaddress", "registeredaddress", "address"],
    "roc": ["registrarofcompanies", "companyroccode", "roccode", "roc"],
    "state": ["registeredstate", "companystatecode", "state"],
    "listing_status": ["listingstatus"],
    "nic_code": ["niccode", "industrialclass"],
    "activity": ["companyindustrialclassification", "principalbusinessactivityaspercin", "principalbusinessactivity"],
}
DROP = re.compile(r"email|phone|mobile")        # personal contact data: not kept even in `other`


def norm(column):
    return re.sub(r"[^a-z0-9]", "", column.lower())


def number(value):
    """'1,00,000' / '100000.00' -> 100000; anything else unchanged."""
    s = str(value).replace(",", "").strip()
    try:
        f = float(s)
    except ValueError:
        return value
    return int(f) if f.is_integer() else f


def iso_date(value):
    """dd-mm-yyyy, dd/mm/yyyy or yyyy-mm-dd (optionally with a time) -> yyyy-mm-dd; None if it is none of those."""
    s = str(value).strip()
    if m := re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b", s):
        return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}"
    if m := re.match(r"^(\d{4})-(\d{2})-(\d{2})\b", s):
        return f"{m[1]}-{m[2]}-{m[3]}"
    return None


def company(row):
    """One API row -> (cin, data), or None when the row has no usable CIN. Pure."""
    cols = {norm(k): (k, v) for k, v in row.items()}
    data, used = {}, set()
    for field, names in COLUMNS.items():
        for n in names:
            if n in cols and n not in used:
                used.add(n)
                v = cols[n][1]
                data[field] = v.strip() if isinstance(v, str) else v
                break
    cin = str(data.pop("cin", "") or "").strip().upper()
    if not cin:
        return None
    for f in ("authorized_capital", "paidup_capital"):
        if data.get(f) not in (None, ""):
            data[f] = number(data[f])
    if data.get("registration_date"):
        data["registration_date_iso"] = iso_date(data["registration_date"])
    if m := CIN.match(cin):
        data.update(listing=m[1], cin_nic_code=m[2], state_code=m[3], cin_year=int(m[4]), ownership=m[5])
    data["other"] = {k: v for n, (k, v) in cols.items() if n not in used and not DROP.search(n)}
    return cin, data


def parse(doc):
    """[(cin, data)] for the rows of one OGD API response. Pure: test it on saved responses."""
    return [c for c in map(company, doc.get("records") or []) if c]


class LocalHub:
    """Stand-in for HubClient so `--local` runs without the hub: counters go to stderr, records to stdout."""
    settings = {"threads": 1, "delay_ms": 0, "paused": False}

    def __init__(self):
        self.counts = {}

    def metric(self, name, value=1):
        self.counts[name] = self.counts.get(name, 0) + value

    def error(self, n=1):
        self.metric("errors", n)

    def block(self, n=1):
        self.metric("blocked", n)

    def failure(self, kind, key, reason, **detail):
        print(f"failure {kind} {key}: {reason} {detail}", file=sys.stderr)


def fetch(hub, session, resource, offset, limit):
    """One page of a resource as the parsed API JSON, or None (counted, and reported as a failure if the API said why)."""
    t = time.time()
    try:
        r = session.get(f"{API}/resource/{resource}", timeout=60, headers={"User-Agent": UA},
                        params={"api-key": KEY, "format": "json", "offset": offset, "limit": limit})
    except requests.RequestException:
        hub.metric("http_error")
        hub.error()
        return None
    hub.metric("n_http")
    hub.metric("t_http_s", time.time() - t)
    if r.status_code != 200:
        hub.metric(f"http_{r.status_code}")
        if r.status_code in (403, 429, 503):
            hub.block()
        return None
    try:
        doc = r.json()
    except ValueError:
        hub.metric("bad_json")
        hub.error()
        return None
    if not isinstance(doc, dict) or "records" not in doc:       # e.g. an invalid key or resource: the API answers 200 with a message
        hub.metric("api_error")
        hub.failure("api", f"{resource}/{offset}", str(doc.get("message") or doc.get("error") or doc)[:200]
                    if isinstance(doc, dict) else "unexpected answer")
        return None
    return doc


def crawl_chunk(hub, session, item):
    """Fetch every page of one queue item. Returns (rows, companies) or None if a page did not load or time ran out."""
    p = item["payload"]
    rows, out = [], []
    offset, end = p["offset"], p["offset"] + p["rows"]
    while offset < end:
        if time.time() > DEADLINE:
            return None
        doc = fetch(hub, session, p["resource"], offset, min(PAGE, end - offset))
        if doc is None:
            return None
        page = doc["records"] or []
        if not page:                            # past the end (the resource shrank since setup)
            break
        rows += page
        out += parse(doc)
        offset += len(page)
        time.sleep(max(0.5, hub.settings.get("delay_ms", 0) / 1000))
    return rows, out


def local(resource, offset):
    hub = LocalHub()
    doc = fetch(hub, requests.Session(), resource, offset, PAGE)
    rows = parse(doc) if doc else []
    for cin, data in rows:
        print(json.dumps({"record_id": cin, "data": data}, ensure_ascii=False))
    if doc:
        print(f"total {doc.get('total')}, columns {[f.get('id') for f in doc.get('field', [])]}", file=sys.stderr)
    print(f"{len(rows)} records, counters {hub.counts}", file=sys.stderr)


def main():
    from scrape_hub_client import HubClient      # imported here so --local works without it
    hub = HubClient(PROJECT, job_index=int(os.environ.get("SCRAPE_JOB_INDEX", "0")), total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", "1")))
    session = requests.Session()
    try:
        while time.time() < DEADLINE:
            if hub.settings.get("paused"):
                time.sleep(30)                          # the hub holds us (site down, or the family owner paused it)
                continue
            items = hub.claim(1, steal=True, retry_failed=True)
            if not items:
                break                                   # nothing left for this project: exit, the worker asks the hub for more
            item = items[0]
            got = crawl_chunk(hub, session, item)
            if got is None:
                hub.complete([item["key"]], "failed", error="a page did not load")
                continue
            rows, companies = got
            p = item["payload"]
            hub.upload_many([(f"rows/{p['source']}/{p['offset']}.json.gz",
                              gzip.compress(json.dumps(rows, ensure_ascii=False).encode()), "application/gzip")])
            for cin, data in companies:
                hub.record(cin, {**data, "source": p["source"]})
            if len(companies) < len(rows):
                hub.metric("rows_without_cin", len(rows) - len(companies))
            hub.complete([item["key"]], "done", fetched=len(companies))
        hub.close()
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


if __name__ == "__main__":
    if sys.argv[1:2] == ["--local"]:
        if len(sys.argv) < 3:
            sys.exit("usage: python crawl.py --local <resource id> [offset]")
        local(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 0)
    else:
        main()
