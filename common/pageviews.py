"""Wikimedia Pageviews access with explicit fallback.

The daily "top articles" data is published with a lag: asking for
yesterday (or even the day before) can legitimately return 404.
Callers must never assume a fixed date exists. These helpers walk
backwards day by day until data is found, and report WHICH date the
data actually belongs to, so feed text can state it honestly.
"""
import json
import urllib.error
import urllib.request
from datetime import date, timedelta

API = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
UA = {"User-Agent": "SignboardFeeds/0.1 (personal hobby project; Wikimedia Pageviews API)"}
PROJECT = "ja.wikipedia"


def fetch_top(day: date) -> list[dict] | None:
    """Top articles for one exact day, or None if not published yet."""
    url = f"{API}/top/{PROJECT}/all-access/{day:%Y/%m/%d}"
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # not published yet: a normal, expected state
        raise
    return data["items"][0]["articles"]


def latest_top(today: date, max_back: int = 7) -> tuple[date, list[dict]] | None:
    """(data_date, articles) for the newest published day.

    Starts from yesterday and walks back up to max_back days.
    Returns None only if no day in that window has data.
    """
    for back in range(1, max_back + 1):
        day = today - timedelta(days=back)
        articles = fetch_top(day)
        if articles:
            return day, articles
    return None


def top_near(day: date, max_back: int = 3) -> tuple[date, list[dict]] | None:
    """Top articles for `day`, falling back to earlier days if needed.

    Used for the comparison baseline: the exact day matters less than
    having a baseline from roughly the same distance in the past.
    """
    for back in range(0, max_back + 1):
        d = day - timedelta(days=back)
        articles = fetch_top(d)
        if articles:
            return d, articles
    return None
