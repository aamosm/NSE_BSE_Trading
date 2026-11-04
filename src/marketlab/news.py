from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from .common import now, timestamp
from .kite import NoRedirect

APPROVED_HOSTS = {"nsearchives.nseindia.com", "www.nseindia.com", "www.bseindia.com"}
MAX_XML = 2 * 1024 * 1024


def parse_feed(raw: bytes):
    if len(raw) > MAX_XML or b"\x00" in raw or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("Feed is too large or uses unsupported XML declarations")
    root = ET.fromstring(raw)
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    for item in items[:500]:
        def value(name):
            return item.findtext(name) or item.findtext("{http://www.w3.org/2005/Atom}" + name) or ""
        title, link = value("title"), value("link")
        if not link:
            node = item.find("{http://www.w3.org/2005/Atom}link")
            link = node.attrib.get("href", "") if node is not None else ""
        if urlsplit(link).scheme not in ("http", "https"):
            link = ""
        raw_date = value("pubDate") or value("published") or value("updated")
        published = None
        if raw_date:
            try:
                published = timestamp(raw_date)
            except ValueError:
                try:
                    published = timestamp(parsedate_to_datetime(raw_date))
                except (ValueError, TypeError):
                    pass
        yield {"title": title[:2000], "url": link, "published_at": published,
               "text": (value("description") or value("summary"))[:12000],
               "verification": "unreviewed", "subject_isin": None}


def ingest_feed(store, raw: bytes, source: str, received_at=None):
    received = received_at or now()
    return [store.append("news", source, "UNMAPPED", item,
                         published_at=item["published_at"], received_at=received)
            for item in parse_feed(raw)]


def fetch_feed(url):
    u = urlsplit(url)
    if u.scheme != "https" or u.hostname not in APPROVED_HOSTS or u.port not in (None, 443) or u.username:
        raise ValueError("Use an official HTTPS exchange feed or import a saved XML file")
    with build_opener(NoRedirect()).open(Request(url, headers={"User-Agent": "MarketLabResearch/0.2"}), timeout=20) as r:
        raw = r.read(MAX_XML + 1)
    if len(raw) > MAX_XML:
        raise ValueError("Feed exceeds size budget")
    return raw
