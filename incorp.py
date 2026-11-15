"""Parse MCA's monthly "Companies and LLPs registered" Excel file (F03). Pure: bytes in, records out; tested in tests/test_incorp.py.

The workbook has one sheet per kind: Indian companies (CIN), LLPs (LLPIN), foreign companies (FCIN). The layout changed several
times (title rows above the header or not, 6 to 17 columns, dates as text or Excel dates), so each sheet's header row is found by
its id column and every column is mapped by its normalised name (COLUMNS). Unknown columns go to `other`; e-mail and phone columns
are dropped.

Record id: the CIN / LLPIN / FCIN (one record per entity; `report_month` says which monthly file it came from).
"""
import io
import re
from datetime import date, datetime

import openpyxl

from crawl import CIN, iso_date, norm, number

IDS = {"cin": "company", "llpin": "llp", "fcin": "foreign"}
LLPIN = re.compile(r"^[A-Z]{3}-\d{4}$")
FCIN = re.compile(r"^F\d{4,6}$")

# output field -> normalised header names (lower-case a-z0-9 only). A column takes the first field (in this order) that lists its
# name and is still free, so "Industrial Activity" is the code where it is alone and the group next to "Industrial Activity Code".
COLUMNS = {
    "name": ["companyname", "llpname", "limitedliabilitypartnershipname", "name"],
    "registration_date": ["dateofregistration", "founded", "dateofincorporation", "date", "registrationdate"],
    "state": ["state"],
    "district": ["district"],
    "roc": ["roc", "roclocation"],
    "status": ["companystatus", "llpstatus", "status", "company"],
    "category": ["category", "companycategory"],
    "class": ["class", "companyclass"],
    "company_type": ["companytype", "companysubcategory", "subcategory", "natureofcompany"],
    "authorized_capital": ["authorized", "authorizedcapital", "authorisedcapital", "authorizedcapitalinthousandrs"],
    "paidup_capital": ["paidup", "paidupcapital", "paidupcapitalinthousandrs"],
    "activity_code": ["activitycode", "industrialactivitycode", "activity", "industrialactivity", "niccode"],
    "activity_group": ["activitydescription", "industrialactivitydescription", "industrialdescription", "descriptionactivity",
                       "activtydescription", "maindiscription", "maindescription", "industrialactivity"],
    "activity_detail": ["description5digitdiscription"],     # and "description" next to a group column (see header_map)
    "address": ["registeredofficeaddress", "address", "companyaddress", "registeredaddress"],
    "obligation_of_contribution": ["obligationofcontribution", "obligationofcontributionrs", "totalobligationofcontribution"],
    "partners": ["numberofpartners", "noofpartners"],
    "designated_partners": ["numberofdesignatedpartners", "noofdesignatedpartners", "numberof"],   # "Number of" (2022-04, cut)
    "office_type": ["officetype", "typeofoffice"],
}
GROUP_NAMES = set(COLUMNS["activity_group"]) - {"industrialactivity"}
THOUSANDS = {"authorizedcapitalinthousandrs", "paidupcapitalinthousandrs"}     # 2018-10 .. 2019-07: capital in thousand rupees
NUMBERS = ("authorized_capital", "paidup_capital", "obligation_of_contribution", "partners", "designated_partners")
SKIP = {"monthname", "sno", "slno", ""}                             # the month is report_month; serial numbers
DROP = re.compile(r"email|phone|mobile")                            # personal contact data: never kept
MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def clean(v):
    if isinstance(v, str):
        v = re.sub(r"\s+", " ", v.replace("\xa0", " ")).strip()
        if v.startswith("="):                                       # a formula without a cached value (2022-06)
            return None
        return v or None
    return v


def as_date(v):
    """Excel date, dd-mm-yyyy, dd-MON-yyyy -> yyyy-mm-dd; None otherwise."""
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    if v in (None, ""):
        return None
    if m := re.match(r"^(\d{1,2})[-/ ]([A-Za-z]{3})[A-Za-z]*[-/ ](\d{4})\b", str(v).strip()):
        mon = MON.get(m[2].lower())
        return f"{m[3]}-{mon:02d}-{int(m[1]):02d}" if mon else None
    return iso_date(v)


def activity(v):
    """NIC code as text: 1 -> '01', '01409' stays."""
    if v in (None, ""):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, int):
        return f"{v:02d}"
    return re.sub(r"^ZMCA_INDUS_ACT_", "", str(v).strip()) or None     # 2018: "ZMCA_INDUS_ACT_93"


def header_map(header):
    """({column index: field or ("other", header text)}, id column index, kind from the header) for one header row."""
    names = [norm(str(c or "")) for c in header]
    id_col = next(i for i, n in enumerate(names) if n in IDS)
    fields, used = {id_col: "id"}, set()
    has_group = any(n in GROUP_NAMES for n in names)
    for i, n in enumerate(names):
        if i == id_col or n in SKIP or DROP.search(n):
            continue
        if n == "description":                        # the detail next to a group column, else the activity group itself
            cands = ["activity_detail", "activity_group"] if has_group else ["activity_group", "activity_detail"]
        else:
            cands = [f for f, ns in COLUMNS.items() if n in ns]
        f = next((f for f in cands if f not in used), None)
        if f:
            used.add(f)
            fields[i] = (f, n in THOUSANDS)
        else:
            fields[i] = ("other", str(header[i]).strip())
    return fields, id_col, IDS[names[id_col]]


def kind_of(rid, sheet_kind):
    """By the id's shape: 2016-18 files list foreign companies (F01234) in a sheet whose id column is called CIN."""
    if FCIN.match(rid):
        return "foreign"
    if LLPIN.match(rid):
        return "llp"
    return sheet_kind


def sheet_rows(ws):
    """[(record id, kind, fields, other)] for one sheet; [] when the sheet has no id column."""
    fields, out = None, []
    for row in ws.iter_rows(values_only=True):
        if fields is None:
            if any(norm(str(c or "")) in IDS for c in row):
                fields, id_col, sheet_kind = header_map(row)
            continue
        rid = str((clean(row[id_col]) if id_col < len(row) else None) or "").upper()
        if not re.search(r"\d", rid) or norm(rid) in IDS:
            continue                                   # empty, a repeated header, a footer line
        rec, other = {}, {}
        for i, (f, extra) in fields.items():
            if f == "id":
                continue
            v = clean(row[i]) if i < len(row) else None
            if f == "other":
                if v is not None:
                    other[extra] = v.isoformat() if isinstance(v, (datetime, date)) else v
                continue
            if f in NUMBERS and v not in (None, ""):
                v = number(v)
                if extra and isinstance(v, (int, float)):
                    v = round(v * 1000)
            rec[f] = v
        rec["registration_date"] = as_date(rec.get("registration_date"))
        rec["activity_code"] = activity(rec.get("activity_code"))
        if isinstance(rec.get("activity_group"), str):
            rec["activity_group"] = re.sub(r"^Industrial Activity\s*-\s*", "", rec["activity_group"]) or None
        out.append((rid, kind_of(rid, sheet_kind), rec, other))
    return out


def parse(body, facts):
    """[(record id, data)] for one monthly workbook. `facts` (report_month, title, published, source, xlsx_path) is copied into
    every record."""
    wb = openpyxl.load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    out = {}
    for ws in wb.worksheets:
        for rid, kind, rec, other in sheet_rows(ws):
            data = {"kind": kind, "id": rid, "cin": rid if kind == "company" else None,
                    "llpin": rid if kind == "llp" else None, "fcin": rid if kind == "foreign" else None}
            data.update({f: rec.get(f) for f in COLUMNS})
            if kind == "company" and (m := CIN.match(rid)):
                data.update(listing=m[1], cin_nic_code=m[2], state_code=m[3], cin_year=int(m[4]), ownership=m[5])
            data["sheet"] = ws.title.strip()
            data.update(facts)
            data["other"] = other
            out[rid] = data                            # a row repeated in the sheet (seen in foreign companies) counts once
    wb.close()
    return list(out.items())
