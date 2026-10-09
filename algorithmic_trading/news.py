"""Small RSS/Atom ingestion pipeline. Fetching is explicit, never on web startup."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, urljoin
import xml.etree.ElementTree as ET

import click
import requests
from sqlalchemy.exc import IntegrityError
from models import db, NewsArticle

# Only these publisher feeds can be fetched; API callers cannot supply URLs.
SOURCES = {
    "bbc-business": {
        "name": "BBC News — Business",
        "url": "https://feeds.bbci.co.uk/news/business/rss.xml",
        "domains": ("bbc.co.uk", "bbc.com"),
    },
    "cnbc-top": {
        "name": "CNBC — Top News",
        "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "domains": ("cnbc.com",),
    },
}
MAX_BYTES = 2_000_000
MAX_ITEMS = 500


class NewsError(ValueError):
    pass


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value, limit):
    parser = PlainText()
    parser.feed(value or "")
    return " ".join(" ".join(parser.parts).split())[:limit]


class NoDoctype(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise NewsError("Feed document types and entities are not supported")


def published_time(value):
    if not value:
        return None
    try:
        result = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            return None
    # Never invent a timezone or substitute retrieval time for publication time.
    if result.tzinfo is None:
        return None
    try:
        return result.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError):
        return None


def canonical_url(value, source):
    try:
        parts = urlsplit(urljoin(source["url"], value))
        host = (parts.hostname or "").lower()
        if parts.scheme not in ("http", "https") or parts.username or parts.password or parts.port not in (None, 80, 443):
            return None
        if not any(host == domain or host.endswith("." + domain) for domain in source["domains"]):
            return None
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid", "__source", "ocid")]
        return urlunsplit((parts.scheme, host, parts.path, urlencode(sorted(query)), ""))
    except ValueError:
        return None


def classify_mentions(title, summary):
    """Candidate entity mentions only; not claim attribution or sentiment."""
    text = title + " " + summary
    us_merck = re.search(r"\bMRK\b|\bMerck\s*(?:&|and)\s*Co\b|\bKeytruda\b|\bGardasil\b", text, re.I)
    other_merck = re.search(r"\bKGaA\b|\bDarmstadt\b|\bMerck\s+Group\b|\bEMD\s+Serono\b", text, re.I)
    if us_merck:
        match = "explicit"
    elif other_merck:
        match = None
    elif re.search(r"\bMerck\b", text, re.I):
        match = "ambiguous"
    else:
        match = None
    cramer = bool(re.search(r"\b(?:Jim\s+)?Cramer(?:['’]s)?\b", text, re.I))
    return match, cramer


def parse_feed(payload, source_id):
    if source_id not in SOURCES:
        raise NewsError("Unknown news source")
    if len(payload) > MAX_BYTES:
        raise NewsError("News feed exceeds the size limit")
    try:
        root = ET.fromstring(payload, parser=ET.XMLParser(target=NoDoctype()))
    except ET.ParseError:
        raise NewsError("News source returned invalid XML") from None
    atom = "{http://www.w3.org/2005/Atom}"
    if root.tag == "rss":
        entries = root.findall("./channel/item")
    elif root.tag == atom + "feed":
        entries = root.findall(atom + "entry")
    else:
        raise NewsError("Expected an RSS or Atom feed")
    source = SOURCES[source_id]
    parsed, skipped = [], 0
    for entry in entries[:MAX_ITEMS]:
        is_atom = entry.tag == atom + "entry"
        prefix = atom if is_atom else ""

        def field(name):
            element = entry.find(prefix + name)
            return "" if element is None else "".join(element.itertext())

        title = plain_text(field("title"), 500)
        link = field("link")
        if is_atom:
            link = next((element.get("href", "") for element in entry.findall(atom + "link")
                         if element.get("rel", "alternate") == "alternate"), "")
        url = canonical_url(link, source) if link else None
        if not title or not url:
            skipped += 1
            continue
        summary = plain_text(field("summary" if is_atom else "description"), 1000)
        published = field("published" if is_atom else "pubDate")
        mrk, cramer = classify_mentions(title, summary)
        parsed.append(dict(
            identity=sha256((source_id + "\n" + url).encode()).hexdigest(),
            source_id=source_id, source_name=source["name"], feed_url=source["url"],
            url=url, title=title, summary=summary, published_at=published_time(published),
            mrk_match=mrk, cramer_mention=cramer,
        ))
    return parsed, skipped + max(0, len(entries) - MAX_ITEMS)


def fetch_feed(source_id):
    if source_id not in SOURCES:
        raise NewsError("Unknown news source")
    try:
        with requests.get(SOURCES[source_id]["url"], timeout=(5, 20), stream=True,
                          allow_redirects=False, headers={"User-Agent": "QuantifyLocalNews/0.1", "Accept": "application/rss+xml, application/atom+xml, application/xml"}) as response:
            if response.status_code != 200:
                raise NewsError(f"News feed returned HTTP {response.status_code}")
            payload = bytearray()
            for chunk in response.iter_content(chunk_size=16384):
                payload.extend(chunk)
                if len(payload) > MAX_BYTES:
                    raise NewsError("News feed exceeds the size limit")
            return bytes(payload)
    except requests.RequestException:
        raise NewsError("News feed could not be reached") from None


def ingest_source(source_id, payload=None):
    rows, skipped = parse_feed(fetch_feed(source_id) if payload is None else payload, source_id)
    retrieved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    inserted = duplicates = 0
    try:
        known = {identity for (identity,) in db.session.query(NewsArticle.identity).filter(
            NewsArticle.identity.in_([row["identity"] for row in rows])).all()} if rows else set()
        for row in rows:
            if row["identity"] in known:
                duplicates += 1
                continue
            # A unique identity also protects concurrent collectors.
            try:
                with db.session.begin_nested():
                    db.session.add(NewsArticle(**row, retrieved_at=retrieved_at))
                    db.session.flush()
                inserted += 1
                known.add(row["identity"])
            except IntegrityError:
                if not NewsArticle.query.filter_by(identity=row["identity"]).first():
                    raise
                duplicates += 1
                known.add(row["identity"])
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return {"source": source_id, "inserted": inserted, "duplicates": duplicates, "skipped": skipped}


def serialize_article(row):
    return {
        "id": row.id, "source_id": row.source_id, "source": row.source_name,
        "feed_url": row.feed_url, "url": row.url, "title": row.title, "summary": row.summary,
        "published_at": row.published_at.isoformat() + "Z" if row.published_at else None,
        "retrieved_at": row.retrieved_at.isoformat() + "Z",
        "mrk_match": row.mrk_match, "cramer_mention": row.cramer_mention,
        "source_reliability": None, "claim_confidence": None,
        "market_relevance": None, "expected_impact": None,
    }


def register_commands(app):
    @app.cli.command("news-fetch")
    @click.option("--source", type=click.Choice(list(SOURCES)), multiple=True)
    def news_fetch(source):
        """Collect feed metadata once. No scheduler or full-article scraping."""
        failures = []
        for source_id in source or SOURCES:
            try:
                result = ingest_source(source_id)
                click.echo(f"{source_id}: {result['inserted']} new, {result['duplicates']} existing, {result['skipped']} skipped")
            except NewsError as exc:
                failures.append(source_id)
                click.echo(f"{source_id}: {exc}", err=True)
            except Exception:
                db.session.rollback()
                failures.append(source_id)
                click.echo(f"{source_id}: collection failed; no raw error details logged", err=True)
        if failures:
            raise click.ClickException("Collection failed for: " + ", ".join(failures))
