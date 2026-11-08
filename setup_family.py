"""Put this family's projects in the pool and register its health checks. Run by the Setup workflow (GitHub Actions: the hub
trusts this repo, s1d-labs/<family>, through its OIDC token). Safe to run again: queue items that exist are kept.

Queue items are built here from each resource's live row count (family.total_rows), so a resource that grows gets new chunks."""
import sys

from scrape_hub_client import register_project, seed_queue, set_pool, set_probes

from family import FAMILY, PROBES, PROJECTS, chunk_items, total_rows

import family

print("health checks:", set_probes(FAMILY, PROBES))
for p in PROJECTS:
    items = []
    if "resources" in p:
        if not p["resources"]:
            sys.exit(f"family.py: {p['name']}: RESOURCES is empty; add the data.gov.in resource id(s) first")
        for name, rid in p["resources"].items():
            total = total_rows(rid)
            print(f"{name} ({rid}): {total} rows")
            items += chunk_items(name, rid, total)
    else:
        items = getattr(family, p["items"])()
    register_project(p["name"], title=p["title"], unit_label=p["unit_label"], record_label=p["record_label"],
                     expected_units=len(items), expected_records=sum(i["payload"].get("expected") or 0 for i in items) or None)
    set_pool(p["name"], FAMILY, p["task"], target=p["target"], env=p["env"], probe=p["probe"], proxy=p.get("proxy"),
             pool=p.get("pool", True))
    print(p["name"], "queue:", seed_queue(p["name"], items))
