"""Shared RSS 2.0 rendering for all feeds in this repository.

Every feed produces the same item shape:
    {"title", "link", "description", "category", "guid"}
and this module renders them identically, so a reader (e.g.
Signboard-Duo) sees one consistent format across all feeds.
Numbers and dates always come from the source data; this module
only escapes and assembles.
"""
from xml.sax.saxutils import escape


def render_rss(*, title: str, link: str, description: str,
               items: list[dict], pub_date: str) -> str:
    """pub_date is an RFC 822 string used for lastBuildDate and items."""
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        "<channel>",
        f"<title>{escape(title)}</title>",
        f"<link>{escape(link)}</link>",
        f"<description>{escape(description)}</description>",
        "<language>ja</language>",
        f"<lastBuildDate>{pub_date}</lastBuildDate>",
    ]
    for it in items:
        parts += [
            "<item>",
            f"<title>{escape(it['title'])}</title>",
            f"<link>{escape(it['link'])}</link>",
            f"<description>{escape(it['description'])}</description>",
            f"<category>{escape(it['category'])}</category>",
            f"<pubDate>{pub_date}</pubDate>",
            f'<guid isPermaLink="false">{escape(it["guid"])}</guid>',
            "</item>",
        ]
    parts += ["</channel>", "</rss>", ""]
    return "\n".join(parts)
