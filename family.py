"""What this family scrapes: MCA company master data from data.gov.in's Open Government Data (OGD) API.

FAMILY must equal the repo name (s1d-labs/<FAMILY>) and the family the hub owner added on scrape.s1d.me/runners.
The queue is the dataset cut into chunks of CHUNK rows (offsets); setup_family.py asks the API for each resource's total row
count and seeds one item per chunk. Records are keyed by CIN; the state comes from the CIN itself (see crawl.parse).
"""
import json
import os
from pathlib import Path

import requests

from crawl import UA

FAMILY = json.loads((Path(__file__).parent / "scrape.json").read_text())["family"]

API = "https://api.data.gov.in"
# data.gov.in's published sample key: anyone may use it, it returns at most 10 rows per request. A personal key allows larger
# pages but this repo is public, so a personal key must not go here (ask the hub owner about secret env first); for local runs
# set OGD_KEY (and OGD_PAGE) in the shell.
API_KEY = os.environ.get("OGD_KEY", "579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b")
PAGE = int(os.environ.get("OGD_PAGE", "10"))   # rows per API request (the sample key's cap is 10)
CHUNK = 1000                 # rows per queue item: 100 requests with the sample key

# OGD resource ids (the UUID in the resource's API tab on data.gov.in), by a short name used in queue keys and file paths.
# One entry for the all-India "RoC-wise Company Master Data" resource, or one per state if you use the state-wise resources.
RESOURCES = {
    "roc-wise": "4dbe5667-7b6b-41d7-82af-211562424d9a",   # Registrars of Companies (RoC)-wise Company Master Data
}
# Last row count seen per resource. The Setup workflow runs on a GitHub runner without a proxy, where data.gov.in does not answer;
# setup_family.py then seeds from this count. Seeding again later adds the chunks of a resource that grew.
KNOWN_TOTALS = {"4dbe5667-7b6b-41d7-82af-211562424d9a": 3738721}   # 2026-10-27


def resource_url(resource_id):
    return f"{API}/resource/{resource_id}"


def total_rows(resource_id):
    """The resource's row count, from one 1-row request (run by setup_family.py, not at import). The API never answers requests
    with python-requests' default User-Agent, so this sends the scraper's own. Outside India the API does not answer: then the
    count in KNOWN_TOTALS is used."""
    try:
        r = requests.get(resource_url(resource_id), params={"api-key": API_KEY, "format": "json", "limit": 1},
                         headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
        return int(r.json()["total"])
    except (requests.RequestException, ValueError, KeyError):
        if resource_id in KNOWN_TOTALS:
            print(f"{resource_id}: data.gov.in did not answer, using the known count {KNOWN_TOTALS[resource_id]}")
            return KNOWN_TOTALS[resource_id]
        raise


def chunk_items(name, resource_id, total):
    return [{"key": f"{name}/{offset}",
             "payload": {"resource": resource_id, "source": name, "offset": offset,
                         "rows": min(CHUNK, total - offset), "expected": min(CHUNK, total - offset)}}
            for offset in range(0, total, CHUNK)]


PROJECTS = [
    {
        "name": f"{FAMILY}-companies",         # project names: 2-64 chars of a-z 0-9 - _, start them with the family name
        "title": "MCA company master (data.gov.in)",
        "task": "crawl",                         # a task from scrape.json
        "target": "api.data.gov.in",
        "env": {"OGD_API": API, "OGD_KEY": API_KEY, "OGD_PAGE": str(PAGE)},
        "probe": f"{FAMILY}:api.data.gov.in",
        "proxy": "IN",                           # data.gov.in answers only Indian IPs: pool workers go through the hub's Indian proxies
        # out of the pool: the shared sample key answers 429 even from India, so workers would only hold proxies. Turn it on
        # (True) once the hub's secret env gives this project a personal OGD key.
        "pool": False,
        "unit_label": "chunk", "record_label": "company",
        "resources": RESOURCES,                  # setup_family.py turns these into queue items (chunk_items)
    },
    {
        # F04: ROC strike-off notices (STK-1/5/6/7, LLP, section 560) in the weekly Gazette of India, Part III-Section 1
        "name": f"{FAMILY}-strikeoff",
        "title": "MCA struck-off companies: ROC notices in the Gazette of India (F04)",
        "task": "strikeoff",
        "target": "egazette.gov.in",
        "env": {},
        # no health check: egazette.gov.in answers its home page with a redirect into a session URL (302), and the hub counts only
        # 200 as up, so a check on it always shows "down" and holds the work (land-acquisition runs without one for the same
        # reason). "" clears a check set before. A failed download fails the item and the hub retries it later.
        "probe": "",
        "proxy": "IN",                           # egazette.gov.in answers only Indian IPs
        "pool": True,
        "unit_label": "gazette issue", "record_label": "notice entry",
        "items": "strikeoff_items",              # setup_family.py calls this function of family.py for the queue items
    },
]

# F04 queue: f04_issues.json (python3 f04_issues.py on a team box). First pool run: only the pilot issues; set F04_ALL = True
# after checking them on scrape.s1d.me.
F04_ALL = True
F04_PILOT = ["CG-DL-W-24102026-277391", "CG-MH-W-27122021-232123", "NA-188763", "NA-164490", "NA-156837"]


def strikeoff_items():
    issues = json.loads((Path(__file__).parent / "f04_issues.json").read_text())
    if not F04_ALL:
        issues = [i for i in issues if i["gazette_id"] in F04_PILOT]
    return [{"key": i["gazette_id"], "payload": i} for i in issues]

# health checks the hub runs every minute; work for a project holds while its probe fails
PROBES = [{"name": f"{FAMILY}:api.data.gov.in",
           "url": f"{resource_url(rid)}?api-key={API_KEY}&format=json&limit=1",
           "expect": "records"}
          for rid in list(RESOURCES.values())[:1]]
