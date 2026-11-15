"""Shared Wikidata SPARQL access (CC0 data, official endpoint).

One query shape is used across feeds: filter by date and notability
(sitelinks). WDQS is occasionally slow, so queries retry twice.
"""
import json
import time
import urllib.parse
import urllib.request

ENDPOINT = "https://query.wikidata.org/sparql"
UA = {"User-Agent": "SignboardFeeds/0.1 (personal hobby project; Wikidata CC0)"}


def sparql(query: str) -> list[dict]:
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            return data["results"]["bindings"]
        except Exception as e:  # WDQS is occasionally slow; retry twice
            last_err = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"SPARQL failed: {last_err}")
