"""openBD access (bibliographic data by ISBN; free, no key).

openBD can only look up a known ISBN — there is no way to enumerate
books by publication date. In this repository it is used solely to
confirm a release that another source (Pageviews surge + MADB)
has already pointed at.
"""
import json
import urllib.parse
import urllib.request

API = "https://api.openbd.jp/v1/get"
UA = {"User-Agent": "SignboardFeeds/0.1 (personal hobby project; openBD)"}


def get_by_isbn(isbn: str) -> dict | None:
    """Summary dict for the ISBN, or None if openBD has no record."""
    url = API + "?" + urllib.parse.urlencode({"isbn": isbn})
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if not data or not data[0]:
        return None
    return data[0].get("summary") or None
