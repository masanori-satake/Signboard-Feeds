"""MADB (Media Arts Database, Agency for Cultural Affairs) access.

The real SPARQL endpoint is https://mediaarts-db.artmuseums.go.jp/sparql
(the MADB Lab page of a similar URL is only the query UI).
Use GET: POST requests timed out in testing (2026-11-15).
The schema is schema.org-based; manga volumes are class
data/class#MangaBook with schema:datePublished / schema:isbn.

Known limitation: registration lags publication by roughly 3 weeks,
so this source can confirm recent releases but never today's.
"""
import json
import urllib.parse
import urllib.request

ENDPOINT = "https://mediaarts-db.artmuseums.go.jp/sparql"
UA = {"User-Agent": "SignboardFeeds/0.1 (personal hobby project; MADB)"}
MANGA_BOOK = "<https://mediaarts-db.artmuseums.go.jp/data/class#MangaBook>"
SERIES_NAME = "<https://mediaarts-db.artmuseums.go.jp/data/property#seriesName>"


def sparql(query: str) -> list[dict]:
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
    req = urllib.request.Request(
        url, headers={**UA, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=50) as r:
        data = json.load(r)
    return data["results"]["bindings"]


def _literal(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def latest_manga_volumes(title_core: str, limit: int = 6) -> list[dict]:
    """Newest MangaBook rows whose series name or title contains the core.

    MADB stores each book under both its title and its kana reading;
    rows are deduplicated by ISBN (or title+date) here.
    """
    lit = _literal(title_core)
    q = f"""
SELECT ?name ?date ?isbn ?vol WHERE {{
  ?s a {MANGA_BOOK} ;
     <https://schema.org/name> ?name ;
     <https://schema.org/datePublished> ?date .
  OPTIONAL {{ ?s <https://schema.org/isbn> ?isbn }}
  OPTIONAL {{ ?s <https://schema.org/volumeNumber> ?vol }}
  OPTIONAL {{ ?s {SERIES_NAME} ?series }}
  FILTER(CONTAINS(?name, {lit}) || (BOUND(?series) && CONTAINS(?series, {lit})))
}}
ORDER BY DESC(?date)
LIMIT {limit * 2}
"""
    seen: set[str] = set()
    rows: list[dict] = []
    for b in sparql(q):
        isbn = b.get("isbn", {}).get("value", "")
        key = isbn or (b["name"]["value"] + "|" + b["date"]["value"])
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "name": b["name"]["value"],
            "date": b["date"]["value"],
            "isbn": isbn,
            "volume": b.get("vol", {}).get("value", ""),
        })
        if len(rows) >= limit:
            break
    return rows
