"""What this family scrapes: MCA company master data from data.gov.in's Open Government Data (OGD) API.

FAMILY must equal the repo name (s1d-labs/<FAMILY>) and the family the hub owner added on scrape.s1d.me/runners.
The queue is the dataset cut into chunks of CHUNK rows (offsets); setup_family.py asks the API for each resource's total row
count and seeds one item per chunk. Records are keyed by CIN; the state comes from the CIN itself (see crawl.parse).
"""
import json
from pathlib import Path

import requests

FAMILY = json.loads((Path(__file__).parent / "scrape.json").read_text())["family"]

API = "https://api.data.gov.in"
# data.gov.in's published sample key: anyone may use it, it returns at most 10 rows per request. A personal key allows larger
# pages but this repo is public, so a personal key must not go here (ask the hub owner about secret env first).
API_KEY = "579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b"
PAGE = 10                    # rows per API request (the sample key's cap)
CHUNK = 1000                 # rows per queue item: 100 requests with the sample key

# OGD resource ids (the UUID in the resource's API tab on data.gov.in), by a short name used in queue keys and file paths.
# One entry for the all-India "RoC-wise Company Master Data" resource, or one per state if you use the state-wise resources.
RESOURCES = {
    "roc-wise": "9ef84268-d588-465a-a308-a864a43d0070",
}


def resource_url(resource_id):
    return f"{API}/resource/{resource_id}"


def total_rows(resource_id):
    """The resource's row count, from one 1-row request (run by setup_family.py, not at import)."""
    r = requests.get(resource_url(resource_id), params={"api-key": API_KEY, "format": "json", "limit": 1}, timeout=60)
    r.raise_for_status()
    return int(r.json()["total"])


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
        "unit_label": "chunk", "record_label": "company",
        "resources": RESOURCES,                  # setup_family.py turns these into queue items (chunk_items)
    },
]

# health checks the hub runs every minute; work for a project holds while its probe fails
PROBES = [{"name": f"{FAMILY}:api.data.gov.in",
           "url": f"{resource_url(rid)}?api-key={API_KEY}&format=json&limit=1",
           "expect": "records"}
          for rid in list(RESOURCES.values())[:1]]
