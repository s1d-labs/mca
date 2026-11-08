"""Build f04_issues.json, the queue of F04 (mca-strikeoff): every weekly Gazette of India Part III-Section 1 issue with a text
layer (issue date from 2013-06-01; older issues are scans and need OCR), from the land-acquisition family's gazette list in
scrape_hub. Run on a team box (psql reads scrape_hub); commit the file; the Setup workflow seeds the new keys.

    python3 f04_issues.py            # writes f04_issues.json next to this file
"""
import json
import subprocess
from pathlib import Path

FIRST_TEXT_ISSUE = "2013-06-01"
SQL = f"""
select json_agg(json_build_object(
    'gazette_id', record_id, 'serial', (data->>'serial')::int, 'publish_date', data->>'publish_date',
    'issue_date', data->>'issue_date', 'file_mb', (data->>'file_mb')::numeric) order by data->>'issue_date', record_id)
from records
where project = 'land-acquisition-egazette' and data->>'category' = 'Weekly' and data->>'part_section' = 'Part III-Section 1'
  and data->>'issue_date' >= '{FIRST_TEXT_ISSUE}' and (data->>'has_pdf')::boolean
"""


def main():
    out = subprocess.run(["psql", "-d", "scrape_hub", "-At", "-c", SQL], check=True, capture_output=True, text=True).stdout
    issues = json.loads(out) or []
    path = Path(__file__).with_name("f04_issues.json")
    path.write_text("[\n" + ",\n".join(json.dumps(i, separators=(",", ":")) for i in issues) + "\n]\n")
    print(f"{len(issues)} issues, {sum(float(i['file_mb'] or 0) for i in issues):.0f} MB -> {path}")


if __name__ == "__main__":
    main()
