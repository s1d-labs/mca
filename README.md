# mca

This family of the s1d-labs scrape pool collects data on Indian companies and LLPs from the Ministry of Corporate Affairs
(MCA). `family.py` lists the projects.

## Projects

| Project | Source | Task | Record |
|---|---|---|---|
| `mca-companies` | data.gov.in OGD API: RoC-wise Company Master Data | `crawl` (`crawl.py`) | one company, keyed by CIN (F01/F02) |
| `mca-strikeoff` | weekly Gazette of India, Part III-Section 1 (egazette.gov.in) | `strikeoff` (`strikeoff.py`, `stk.py`, `egazette.py`) | one company or LLP for each strike-off notice (STK-1/5/6/7) (F04) |

- Both projects run on GitHub runners through the hub's Indian proxies (`proxy="IN"`): the sites do not answer foreign IPs.
- `mca-companies`: one queue item is 1,000 rows of the dataset. The repo uses data.gov.in's public sample key (10 rows for
  each request). Never put a personal key in this public repo; set `OGD_KEY` in the shell for local runs.
- `mca-strikeoff`: one queue item is one weekly issue, from `f04_issues.json` (built by `f04_issues.py`). The PDF and its
  text go to the family bucket.
- `dump.py` downloads a whole OGD resource to local files, outside the pool.

## Run and check

- `python -m pytest tests` runs the parsing tests on the saved answers and gazette excerpts in `tests/pages/`. No network.
- `scrape-check --items 2` runs setup and a task against a local stand-in hub (through a proxy from a team box:
  `myproxy run scrape-check --items 2`).
- Run the **setup** workflow after a change to `family.py` or `f04_issues.json`.

The full contract for family code is in [CLAUDE.md](CLAUDE.md).
