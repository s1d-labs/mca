"""Download one gazette PDF from egazette.gov.in (the central Gazette of India). Taken from the land-acquisition family's crawl.py
(s1d-labs/land-acquisition), where the site's quirks are worked out.

- Gazettes from 2014 on sit at WriteReadData/<year>/<serial>.pdf (year of publication, sometimes of issue).
- Older ones only come through the site's own path: the "Search by Publish Date" form (ASP.NET WebForms, view state, a Referer
  check), the row's download button, then ViewPDF.aspx, which names the file in an iframe.
- The site answers only from India (the pool runs this through the hub's Indian proxies, HTTPS_PROXY), and its TLS chain is
  incomplete, so certificates are not verified (VERIFY_TLS=1 turns it on).
"""
import html
import math
import os
import re
import time
from datetime import date
from urllib.parse import urljoin

import requests
import urllib3

SITE = os.environ.get("EGAZETTE_SITE", "https://egazette.gov.in").rstrip("/")
VERIFY = os.environ.get("VERIFY_TLS", "0") == "1"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
PER_PAGE = 15
if not VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HIDDEN = re.compile(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"')
CELL = re.compile(r'<span id="gvGazetteList_lbl_(\w+?)_(\d+)"[^>]*>(.*?)</span>', re.S)
BUTTON = re.compile(r'name="(gvGazetteList\$ctl\d+\$imgbtndownload)" id="gvGazetteList_imgbtndownload_(\d+)"')
TOTAL = re.compile(r'lbl_Result"[^>]*>[^<]*?Total No\. of Gazettes\s*:\s*(\d+)')
IFRAME = re.compile(r'<iframe[^>]+src="([^"]+\.pdf)"', re.I)
SERIAL = re.compile(r"-(\d+)\s*$|\(\s*(\d+)\s*\)")


class SiteError(Exception):
    pass


def hidden(page):
    return {n: html.unescape(v) for n, v in HIDDEN.findall(page)}


def pager_window(current, pages, count=10):
    first = (current - 1) // count * count
    if first + count > pages:
        first = max(0, pages - count)
    return first + 1, min(first + count, pages)


def buttons_by_serial(page):
    """{serial: download button name} for the rows of one result page."""
    cells = {}
    for name, idx, value in CELL.findall(page):
        cells.setdefault(int(idx), {})[name] = value
    out = {}
    for name, idx in BUTTON.findall(page):
        raw = re.sub(r"<[^>]+>", " ", cells.get(int(idx), {}).get("UGID", ""))
        m = SERIAL.search(html.unescape(raw).strip())
        if m:
            out[int(m.group(1) or m.group(2))] = name
    return out


def dmy(iso):
    return date.fromisoformat(iso).strftime("%d-%b-%Y")


class Site:
    """One browsing session. Every request reports the hub's standard counters (n_http, t_http_s, http_<code>, http_error)."""

    def __init__(self, hub):
        self.hub = hub
        self.s = requests.Session()
        self.s.verify = VERIFY
        self.s.headers["User-Agent"] = UA
        self.form = None

    def _req(self, method, url, referer=None, expect_pdf=False, **kw):
        time.sleep(max(0.2, self.hub.settings.get("delay_ms", 0) / 1000))
        t = time.time()
        try:
            r = self.s.request(method, url, timeout=(20, 300), headers={"Referer": referer or SITE + "/"}, **kw)
        except requests.RequestException as e:
            self.hub.metric("http_error")
            self.hub.error()
            raise SiteError(type(e).__name__) from e
        self.hub.metric("n_http")
        self.hub.metric("t_http_s", time.time() - t)
        if r.status_code != 200:
            self.hub.metric(f"http_{r.status_code}")
            if r.status_code in (403, 429, 503):
                self.hub.block()
            raise SiteError(f"HTTP {r.status_code}")
        if expect_pdf:
            if not r.content.startswith(b"%PDF"):
                raise SiteError("not a PDF")
            return r
        if "/error.aspx" in r.url.lower():
            self.hub.metric("site_error_page")
            raise SiteError("site error page")
        r.encoding = "utf-8"
        return r

    # ---- the direct path (2014 on)
    def direct(self, serial, years):
        for year in dict.fromkeys(y for y in years if y):
            url = f"{SITE}/WriteReadData/{year}/{serial}.pdf"
            try:
                return url, self._req("GET", url, expect_pdf=True).content
            except SiteError as e:
                if str(e) != "HTTP 404":
                    raise
                self.hub.metric("pdf_direct_miss")
        return None

    # ---- the site's own path (any year)
    def _search(self, day):
        home = self._req("GET", SITE + "/")
        f = hidden(home.text)
        f.update({"__EVENTTARGET": "sgzt", "__EVENTARGUMENT": ""})
        menu = self._req("POST", home.url, data=f, referer=home.url)
        f = hidden(menu.text)
        f["btnPublish"] = "Search by Publish Date"
        self.form = self._req("POST", menu.url, data=f, referer=menu.url)
        if "txtDateFrom" not in self.form.text:
            raise SiteError("search form not found")
        self.form = self._post({"ImgSubmit.x": "20", "ImgSubmit.y": "10"}, day)
        return self.form.text

    def _post(self, extra, day):
        f = hidden(self.form.text)
        f.update({"txtDateFrom": day, "txtDateTo": day})
        f.update(extra)
        return self._req("POST", self.form.url, data=f, referer=self.form.url)

    def _page(self, n, day):
        self.form = self._post({"__EVENTTARGET": "gvGazetteList", "__EVENTARGUMENT": f"Page${n}"}, day)
        return self.form.text

    def via_viewer(self, serial, publish_date):
        """Search the gazette's publish date, walk the result pages to its row, press its download button."""
        day = dmy(publish_date)
        page = self._search(day)
        m = TOTAL.search(page)
        pages = math.ceil(int(m.group(1)) / PER_PAGE) if m else 1
        n = 1
        while True:
            button = buttons_by_serial(page).get(int(serial))
            if button:
                break
            if n >= pages:
                raise SiteError(f"serial {serial} not in the results of {day}")
            lo, hi = pager_window(n, pages)
            n = n + 1 if n + 1 <= hi else hi + 1          # the next page, or the "..." after the pager's window
            page = self._page(n, day)
            self.hub.metric("pager_hops")
        self.form = self._post({f"{button}.x": "5", f"{button}.y": "5"}, day)
        if "ViewPDF.aspx" not in self.form.text:
            raise SiteError("download postback gave no viewer")
        viewer = self._req("GET", urljoin(self.form.url, "ViewPDF.aspx"), referer=self.form.url)
        src = IFRAME.search(viewer.text)
        if not src:
            raise SiteError("viewer has no PDF")
        url = urljoin(viewer.url, html.unescape(src.group(1)))
        return url, self._req("GET", url, referer=viewer.url, expect_pdf=True).content

    def pdf(self, serial, publish_date, issue_date=None):
        """(url, bytes) of one gazette."""
        got = self.direct(serial, [(publish_date or "")[:4], (issue_date or "")[:4]])
        if got:
            return got
        self.hub.metric("pdf_via_viewer")
        return self.via_viewer(serial, publish_date)
