"""Parsing of ROC strike-off notices in the weekly Gazette of India, Part III-Section 1 (F04). Pure: text in, records out.

A weekly issue holds many notices of many offices. The strike-off notices of the Registrars of Companies (ROC) and of C-PACE are:

- STK-1 / STK-5: the ROC proposes to strike off companies (section 248(1), Companies Act 2013), objections within 30 days;
- STK-6: companies applied to be struck off (section 248(2), form STK-2), objections within 30 days;
- STK-7: the companies "have been struck off ... and are dissolved" (section 248(5)): the final notice, with the date;
- LLP: LLPs struck off under rule 37 of the LLP Rules 2009 (section 75 of the LLP Act); final, with the date;
- S560: section 560 of the Companies Act 1956 (before the 2013 Act): 560(3) proposes, 560(5) strikes off.

Each notice is printed in Hindi and then in English. Hindi before about 2019 is in legacy fonts and comes out as garbage, so a
company is kept once per notice form, with the English name when one is found. The text comes from pypdfium2 (one line per printed
line); see text_of().
"""
import re
from datetime import date

ID = re.compile(r"(?<![A-Z0-9])([UL]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}|[A-Z]{3}-\d{4})(?![A-Z0-9])")
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september",
                                       "october", "november", "december"], 1)}
MON = r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\.?"
FORM_HEAD = re.compile(r"^\W*FORM\s*(?:NO\.?|NUMBER)?\s*[:.]?\s*STK\s*[-–—]?\s*([1-7])\b", re.I)
STK7_HEAD = re.compile(r"^\W*NOTICE\s+OF\s+STRIKING\s+OFF\s+AND\s+DISSOLUTION", re.I)
LLP_MARK = re.compile(r"Limited\s+Liability\s+Partnership|LLP\s+Rules|LLP\s+Act|\bLLPs?\b.{0,40}struck\s+off|Rule\s*37\s*\(", re.I)
S560 = re.compile(r"section\s*560\s*(?:\(\s*([35])\s*\))?|560\s*\(\s*([35])\s*\)", re.I)
STRUCK = re.compile(r"(?:ha(?:s|ve)\s+(?:on\s+)?(?:this\s+day|been)|on\s+this\s+day)[^.]{0,120}?struck\s+off|struck\s+off\s+(?:from|on)\b", re.I)
PROPOSE = re.compile(r"propose|reasonable\s+cause|objection|shall\s+be\s+struck|will\s+be\s+struck|unless\s+cause", re.I)
DATE_LONG = re.compile(r"\b(\d{1,2})\s*(?:st|nd|rd|th)?\s*(?:day\s+of\s+)?" + MON + r",?\s*(\d{4})\b", re.I)
DATE_NUM = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-]((?:19|20)\d\d)\b")
PLACE_DATE = re.compile(r"^\s*([A-Z][A-Za-z .()'-]{1,40}?)(?:\s*[-–]\s*\d{6})?\s*,\s*(?:dated\s+)?(?:the\s+)?(\d{1,2})\s*(?:st|nd|rd|th)?\s*"
                        r"(?:day\s+of\s+)?" + MON + r",?\s*(\d{4})", re.I)
DATED_LINE = re.compile(r"^\s*(?:Date[d]?\s*[:\-]?|Place\s*:.*Date\s*:)\s*", re.I)
ON_DAY = re.compile(r"(?:this\s+day|on\s+this|w\.?e\.?f\.?|with\s+effect\s+from|struck\s+off\s+on)\D{0,20}?"
                    r"(\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d\d|\d{1,2}\s*(?:st|nd|rd|th)?\s*(?:day\s+of\s+)?" + MON + r",?\s*\d{4})", re.I)
NOTICE_NO = re.compile(r"(?:^|\s)(?:Public\s+)?(?:Notice\s*)?No\s*[.:\-]+\s*(?:-\s*)?([A-Za-z0-9/][\w/().,\- ]{2,70}?)\s*:?\s*(?:[—–]|\s-\s|dated|Reference|$)", re.I)
BARE_NO = re.compile(r"^\s*(ROC[\w/().\- ]{3,60}?)\s*(?:[—–]|$)")
SEPARATOR = re.compile(r"^\s*[—–\-_]{4,}\s*$")
PAGE_HEAD = re.compile(r"THE\s+GAZETTE\s+OF\s+INDIA|^\s*PART\s+III|^\s*\[?\s*PART\s+III", re.I)
NAME_END = re.compile(r"(?:LIMITED|LTD\.?|LLP|COMPANY|CORPORATION|LIMITE\s*D|\))\s*\.?$", re.I)
CPACE = re.compile(r"C\s*-\s*PACE|Centre\s+for\s+Processing\s+Accelerated", re.I)
SRN = re.compile(r"\b[A-Z]{1,2}\d{6,9}\b")
OLD_ROW = re.compile(r"^\s*(\d{1,5})[.)]?\s+(\d{4,6})\s+(.*[A-Za-z].*)$")     # S.No., company number (1956 Act notices), name


def iso_date(s):
    """'21/10/2026', '21.10.2026', '21st October 2026', '8th day of August, 2018' -> '2026-10-21' (None when not a date)."""
    if not s:
        return None
    m = DATE_NUM.search(s)
    try:
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        m = DATE_LONG.search(s)
        if m:
            mon = m.group(2).lower().rstrip(".")
            mon = next(v for k, v in MONTHS.items() if k.startswith(mon[:3]))
            return date(int(m.group(3)), mon, int(m.group(1))).isoformat()
    except (ValueError, StopIteration):
        return None
    return None


def text_of(pdf_bytes):
    """[page text] of a PDF, with pypdfium2 (pip wheel, no system packages: it also runs on the India servers)."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        return [doc[i].get_textpage().get_text_bounded() for i in range(len(doc))]
    finally:
        doc.close()


class Notice:
    def __init__(self, form, page, line_no):
        self.form, self.page, self.line_no = form, page, line_no
        self.head = []              # the lines before the first company row
        self.rows = []              # (id, name, row_date, page)
        self.loose = []             # lines after the last row not taken as its name (the next row's name, printed first)
        self.final = None           # True: struck off (STK-7, LLP, 560(5)); False: proposal (STK-1/5/6, 560(3))

    def facts(self):
        head = " ".join(self.head)
        place = notice_date = notice_no = None
        for line in self.head:
            m = PLACE_DATE.match(line)
            if m and not notice_date:
                place = re.sub(r"\s+", " ", m.group(1)).strip(" .,")
                notice_date = iso_date(" ".join(m.group(2, 3, 4)))
        if not notice_date:
            for line in self.head:
                if DATED_LINE.match(line) and iso_date(line):
                    notice_date = iso_date(line)
                    break
        for line in self.head:
            m = NOTICE_NO.search(line) or BARE_NO.match(line)
            if m and re.search(r"\d|ROC|STK", m.group(1)):
                notice_no = m.group(1).strip(" .,-—")
                break
        m = ON_DAY.search(head)
        struck_on = iso_date(m.group(1)) if m else None
        return place, notice_date, notice_no, struck_on, head


def kind_of(notice, head):
    """(form, final) of a notice from its heading and first lines."""
    form = notice.form
    if form == "LLP":
        return "LLP", not PROPOSE.search(head) or bool(STRUCK.search(head))
    if form in ("STK-7",):
        return form, True
    if form in ("STK-1", "STK-5", "STK-6"):
        return form, False
    if form == "S560":
        m = S560.search(head)
        sub = (m.group(1) or m.group(2)) if m else None
        if sub == "5" or (sub != "3" and STRUCK.search(head) and not PROPOSE.search(head)):
            return "S560(5)", True
        return "S560(3)", False
    return form, None


def segment(pages):
    """Cut the pages into strike-off notices. A notice starts at its heading (FORM STK-n, NOTICE OF STRIKING OFF AND
    DISSOLUTION, an LLP strike-off paragraph, a section 560 notice) and ends at the separator line between notices or at the
    next heading. Company rows outside a strike-off notice (other offices' notices) are not taken."""
    notices, cur = [], None
    prev = []                                    # the last lines seen (a notice number can stand above the FORM heading)
    for p, text in enumerate(pages, 1):
        for i, line in enumerate(text.splitlines()):
            s = line.strip()
            if not s:
                continue
            prev = (prev + [s])[-3:]
            if SEPARATOR.match(s):
                cur = None
                continue
            m = FORM_HEAD.match(s)
            if m and len(s) < 60:
                cur = Notice(f"STK-{m.group(1)}", p, i)
                cur.head.extend(x for x in prev[:-1] if NOTICE_NO.search(x) or BARE_NO.match(x))
                notices.append(cur)
                continue
            if STK7_HEAD.match(s):
                if not (cur and cur.form == "STK-7" and not cur.rows and len(cur.head) < 3):
                    cur = Notice("STK-7", p, i)
                    cur.head.extend(x for x in prev[:-1] if NOTICE_NO.search(x) or BARE_NO.match(x))
                    notices.append(cur)
                continue
            ids = ID.findall(s)
            if cur is None and s.isascii():
                # notices without a FORM heading: LLP strike-offs and section 560 notices of the 1956 Act
                if re.search(r"struck\s+off|strike\s+off|striking\s+off|removed\s+from\s+the\s+register", s, re.I) or LLP_MARK.search(s) or S560.search(s):
                    window = " ".join(x.strip() for x in text.splitlines()[max(0, i - 3):i + 6])
                    if LLP_MARK.search(window) and re.search(r"struck\s+off|strike\s+off|striking", window, re.I):
                        cur = Notice("LLP", p, i)
                    elif S560.search(window) and re.search(r"struck\s+off|strike\s+off|striking|removed", window, re.I):
                        cur = Notice("S560", p, i)
                    if cur:
                        cur.head.extend(x.strip() for x in text.splitlines()[max(0, i - 6):i])
                        notices.append(cur)
            if cur is None:
                continue
            if ids:
                for k, rid in enumerate(ids):
                    after = s.split(rid, 1)[1]
                    nxt = ids[k + 1] if k + 1 < len(ids) else None
                    if nxt:
                        after = after.split(nxt, 1)[0]
                    before = s.split(rid, 1)[0]
                    d = DATE_NUM.search(after)
                    name = row_name(before, after)
                    if name is None and cur.loose:           # name printed first and wrapped, the id alone below it
                        name = row_name(" ".join(cur.loose), "")
                    cur.rows.append([rid, name, d.group(0) if d else None, p])
                    cur.loose = []
            elif cur.form == "S560" and s.isascii() and (m := OLD_ROW.match(s)):
                d = DATE_NUM.search(m.group(3))
                cur.rows.append([f"#{m.group(2)}", row_name("", m.group(3)), d.group(0) if d else None, p])
            elif cur.rows:
                last = cur.rows[-1]
                # a company name wrapped onto the next line(s), or put on the line after its id: upper-case text
                if (s.isascii() and not PAGE_HEAD.search(s) and (last[1] is None or not NAME_END.search(last[1]))
                        and len(s) < 90 and not re.search(r"[a-z]{3,}\s+[a-z]{3,}", s) and re.search(r"[A-Z]{2}", s)):
                    d = DATE_NUM.search(s)
                    if d and not last[2]:
                        last[2] = d.group(0)
                    t = row_name("", s)
                    if t:
                        last[1] = f"{last[1]} {t}" if last[1] else t
                elif s.isascii() and not PAGE_HEAD.search(s):
                    cur.loose = (cur.loose + [s])[-3:]
            elif not PAGE_HEAD.search(s):
                cur.head.append(s)
    return notices


def row_name(before, after):
    """The company name of a row: the text after the id, or before it (S.No., SRN and dates removed). None when it is not ASCII
    (Hindi)."""
    for part, is_before in ((after, False), (before, True)):
        t = DATE_NUM.sub(" ", part)
        t = SRN.sub(" ", t)
        t = re.sub(r"^\s*M/s\.?\s+", " ", t, flags=re.I)
        if is_before:
            t = re.sub(r"^\W*\d+\s*[.)]?(?:\s+|$)", " ", t)          # S.No.
        t = re.sub(r"\s+\d+\s*$", " ", t)                          # a number after the name (S.No. of a two-column list)
        t = re.sub(r"\bC-PACE\s+\w+\b", " ", t)                    # the "Location" column of C-PACE LLP lists
        t = re.sub(r"\s+", " ", t).strip(" .,:;|-")
        if len(t) >= 3 and t.isascii() and re.search(r"[A-Za-z]{2}", t):
            return t
    return None


def month_first(head, raw_dates, issue_date):
    """True when the row dates of a notice are MM/DD/YYYY: the column header says so, a 'day' above 12 is in the month place,
    or reading them as DD/MM puts them after the gazette's own date while MM/DD does not."""
    if re.search(r"MM\s*/\s*DD", head, re.I):
        return True
    if re.search(r"DD\s*/\s*MM", head, re.I):
        return False
    pairs = [tuple(int(x) for x in DATE_NUM.search(d).group(1, 2)) for d in raw_dates if DATE_NUM.search(d)]
    if any(a > 12 for a, b in pairs):
        return False
    if any(b > 12 for a, b in pairs):
        return True
    if issue_date and raw_dates:
        late_dmy = sum(1 for d in raw_dates if (row_iso(d, False) or "") > issue_date)
        late_mdy = sum(1 for d in raw_dates if (row_iso(d, True) or "") > issue_date)
        return late_mdy < late_dmy
    return False


def row_iso(raw, mdy):
    if not raw:
        return None
    m = DATE_NUM.search(raw)
    if not m:
        return None
    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    d, mo = (b, a) if mdy else (a, b)
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def parse(pages, gazette):
    """[(record_id, data)]: one record per company or LLP per notice form in one gazette issue. `gazette` gives the issue's
    gazette_id, issue_date, source_url, pdf_path (copied into every record)."""
    best = {}
    issue = gazette.get("issue_date")
    for n in segment(pages):
        if not n.rows:
            continue
        place, notice_date, notice_no, struck_on, head = n.facts()
        form, final = kind_of(n, head)
        roc = "C-PACE" if CPACE.search(head) else (f"ROC {place}" if place else None)
        if not struck_on and final and re.search(r"from\s+the\s+date\s+of\s+(?:this\s+)?publication", head, re.I):
            struck_on = issue
        mdy = month_first(head, [r[2] for r in n.rows if r[2]], issue)
        for rid, name, raw_date, page in n.rows:
            row_date = row_iso(raw_date, mdy)
            llp = "-" in rid
            old_no = rid.startswith("#")             # a 1956 Act notice: the company number, not the CIN
            data = {
                "entity_type": "llp" if llp else "company",
                "cin": None if llp or old_no else rid, "llpin": rid if llp else None,
                "company_no": rid[1:] if old_no else None,
                "company_name": name,
                "form": form, "final": final,
                "roc": roc, "place": place,
                "notice_no": notice_no, "notice_date": notice_date,
                "struck_off_date": (row_date or struck_on or notice_date) if final else None,
                "page": page,
                **{k: gazette.get(k) for k in ("gazette_id", "issue_date", "part_section", "source_url", "pdf_path")},
            }
            key = f"{gazette['gazette_id']}:{(place or roc or '') + rid if old_no else rid}:{form}".replace(" ", "")
            old = best.get(key)
            # keep one per company and form: the English row (with a name) wins over the Hindi one, then the one with more facts
            score = (data["company_name"] is not None, data["notice_date"] is not None, data["roc"] is not None)
            if old is None or score > old[0]:
                best[key] = (score, data)
    return [(k, v[1]) for k, v in best.items()]
