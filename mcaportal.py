"""Read documents from www.mca.gov.in's document store (DMS), the store behind the site's "Data & Reports" pages.

- www.mca.gov.in is behind Akamai, which answers 403 "Access Denied" to python-requests and to curl from every network (the box,
  the Indian proxies, the India servers). It lets a client in whose TLS and HTTP/2 fingerprint is a browser's, so this module uses
  curl_cffi with `impersonate="chrome"` (no browser, no captcha). It works from the box in Germany and through the Indian proxies.
- A page's file list comes from `/bin/dms/searchDocList` (JSON; the page's dmslist component sends `dialog` = the folder number from
  the page's `data-dialog`). Each document has an opaque `docID`; `/bin/dms/getdocument?mds=<docID>&type=download` gives the file.
- Some old documents are listed but the store answers them with 200 and an empty body (for F03: every file up to June 2021).
"""
import json
import os
import time

from curl_cffi import requests as cr

SITE = os.environ.get("MCA_SITE", "https://www.mca.gov.in").rstrip("/")
IMPERSONATE = os.environ.get("MCA_IMPERSONATE", "chrome")
MONTHLY_PAGE = "/content/mca/global/en/data-and-reports/company-llp-info/incorporated-closed-month.html"
FOLDER_REGISTERED = "403"     # "Master Details of Companies Registered" on MONTHLY_PAGE ("402" is "Companies/LLPs Struck off/Closed")


class SiteError(Exception):
    pass


class EmptyDocument(SiteError):
    """The store lists the document but answers it with an empty body."""


class Portal:
    """One session on www.mca.gov.in. Every request reports the hub's standard counters (n_http, t_http_s, http_<code>,
    http_error) to `hub` (a HubClient or a stand-in with metric/block/error and settings)."""

    def __init__(self, hub, referer=MONTHLY_PAGE):
        self.hub = hub
        self.referer = SITE + referer
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        self.s = cr.Session(impersonate=IMPERSONATE, proxies={"https": proxy, "http": proxy} if proxy else None)
        self.warm = False

    def get(self, path, timeout=120, **kw):
        time.sleep(max(0.5, self.hub.settings.get("delay_ms", 0) / 1000))
        t = time.time()
        try:
            r = self.s.get(SITE + path, timeout=timeout, headers={"Referer": self.referer}, **kw)
        except cr.RequestsError as e:
            self.hub.metric("http_error")
            self.hub.error()
            raise SiteError(f"{path[:60]}: {type(e).__name__}: {e}"[:200]) from e
        self.hub.metric("n_http")
        self.hub.metric("t_http_s", time.time() - t)
        if r.status_code != 200:
            self.hub.metric(f"http_{r.status_code}")
            if r.status_code in (403, 429, 503):
                self.hub.block()
            raise SiteError(f"{path[:60]}: HTTP {r.status_code}")
        return r

    def start(self):
        """Open the page once (cookies, as a browser does) before the store's endpoints."""
        if not self.warm:
            self.get(self.referer[len(SITE):], timeout=60)
            self.warm = True

    def documents(self, folder, per_page=500):
        """All documents of a DMS folder, newest first: [{"column1": title, "column2": date, "docType", "docSize", "docDate",
        "docID"}]."""
        self.start()
        dialog = {"folder": folder, "language": "English", "totalColumns": 2, "columns": ["Title", "Date"]}
        out, page = [], 1
        while True:
            r = self.get("/bin/dms/searchDocList", timeout=60, params={
                "page": page, "perPage": per_page, "sortField": "Date", "sortOrder": "D", "searchField": "",
                "searchKeyword": "", "startDate": "", "endDate": "", "filter": "", "dialog": json.dumps(dialog)})
            body = r.json()
            docs = json.loads(body.get("documentDetails") or "[]")
            out += docs
            if not docs or len(out) >= int(body.get("totalResults") or 0):
                return out
            page += 1

    def document(self, doc_id):
        """(file name, bytes) of one DMS document. EmptyDocument when the store has no content for it."""
        self.start()
        r = self.get(f"/bin/dms/getdocument?mds={doc_id}&type=download")
        if not r.content:
            raise EmptyDocument("the store answered 200 with an empty body")
        cd = r.headers.get("content-disposition") or ""
        name = cd.split("filename=", 1)[1].strip('"; ') if "filename=" in cd else ""
        return name, r.content
