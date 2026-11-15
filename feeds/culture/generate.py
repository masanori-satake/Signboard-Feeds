#!/usr/bin/env python3
"""Culture feed generator.

Builds one RSS 2.0 file for today (JST) with two halves:

- "Now": topics surging on Japanese Wikipedia (Wikimedia Pageviews).
  A surging manga series whose newest volume is confirmed via MADB
  and openBD is promoted to a "new release" row; anything that cannot
  be confirmed is only ever called "trending", never a release.
- Anniversaries: films/games released on this day and birthdays of
  notable culture figures, from Wikidata (CC0) only.

Editorial rule (mechanical): within each kind, rank by a published
score and cap the rows per kind. Numbers and dates come from the
data only; nothing is invented. Every "now" source is optional:
if Pageviews, MADB or openBD fails, those rows are skipped and the
anniversary rows are still published.
"""
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common import madb, openbd, pageviews
from common.rss import render_rss
from common.wikidata import sparql

JST = timezone(timedelta(hours=9))

FILMS_Q = "wd:Q11424"   # film
GAMES_Q = "wd:Q7889"    # video game

CULTURE_KEYWORDS = (
    "作家", "小説家", "詩人", "劇作家", "脚本", "映画", "俳優", "女優",
    "歌手", "作曲", "音楽", "ミュージシャン", "漫画", "画家", "イラスト",
    "監督", "ゲーム", "声優", "落語", "写真家", "建築家", "デザイナー",
    "舞踊", "バレエ", "指揮者", "ピアニスト", "ギタリスト", "ドラマー",
    "ラッパー", "シンガー", "アーティスト", "彫刻", "陶芸", "書道",
    "エッセイスト", "評論家", "翻訳家", "編集者", "プロデューサー",
)

TREND_KEYWORDS = CULTURE_KEYWORDS + ("アニメ",)


def anniversary_query(type_qid: str, month: int, day: int, min_sitelinks: int) -> list[dict]:
    q = f"""
SELECT ?item ?itemLabel (MIN(?d) AS ?date) (MAX(?s) AS ?sl)
       (MAX(?ja) AS ?hasJa) WHERE {{
  ?item wdt:P31/wdt:P279* {type_qid} ; wdt:P577 ?d ; wikibase:sitelinks ?s .
  FILTER(MONTH(?d) = {month} && DAY(?d) = {day} && ?s >= {min_sitelinks})
  OPTIONAL {{
    ?article schema:about ?item ; schema:isPartOf <https://ja.wikipedia.org/> .
    BIND(1 AS ?ja)
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ja,en" }}
}}
GROUP BY ?item ?itemLabel
LIMIT 120
"""
    return sparql(q)


def births_query(month: int, day: int, min_sitelinks: int) -> list[dict]:
    q = f"""
SELECT ?item ?itemLabel ?itemDescription (MIN(?d) AS ?date) (MAX(?s) AS ?sl)
       (MAX(?ja) AS ?hasJa) WHERE {{
  ?item p:P569/psv:P569 ?node .
  ?node wikibase:timeValue ?d ; wikibase:timePrecision 11 .
  FILTER(MONTH(?d) = {month} && DAY(?d) = {day})
  ?item wikibase:sitelinks ?s .
  FILTER(?s >= {min_sitelinks})
  OPTIONAL {{
    ?article schema:about ?item ; schema:isPartOf <https://ja.wikipedia.org/> .
    BIND(1 AS ?ja)
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ja,en" }}
}}
GROUP BY ?item ?itemLabel ?itemDescription
LIMIT 120
"""
    return sparql(q)


def parse_rows(bindings: list[dict]) -> list[dict]:
    rows = []
    for b in bindings:
        label = b["itemLabel"]["value"]
        if label.startswith("Q") and label[1:].isdigit():
            continue  # unlabeled item
        date_raw = b["date"]["value"]
        try:
            year = int(date_raw[:4]) if not date_raw.startswith("-") else -int(date_raw[1:5])
        except ValueError:
            continue
        if year < 1000:
            continue  # ancient/odd dates are not board material
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        rows.append({
            "qid": qid,
            "label": label,
            "year": year,
            "sitelinks": int(b["sl"]["value"]),
            "has_ja": b.get("hasJa", {}).get("value") == "1",
            "description": b.get("itemDescription", {}).get("value", ""),
        })
    return rows


def score(row: dict, today_year: int) -> float:
    years = today_year - row["year"]
    bonus = 10 if years % 10 == 0 else 5 if years % 5 == 0 else 0
    if row.get("has_ja"):
        bonus += 8  # a Japanese Wikipedia article exists: local relevance
    return row["sitelinks"] + bonus


def pick(rows: list[dict], today_year: int, cap: int, min_years: int = 0) -> list[dict]:
    rows = [r for r in rows if today_year - r["year"] >= min_years]
    rows.sort(key=lambda r: score(r, today_year), reverse=True)
    return rows[:cap]


def wiki_qids(titles: list[str]) -> dict[str, str]:
    """ja.wikipedia article title -> Wikidata QID (one batched call)."""
    q = urllib.parse.urlencode({
        "action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
        "titles": "|".join(titles), "format": "json", "formatversion": "2",
    })
    req = urllib.request.Request(
        "https://ja.wikipedia.org/w/api.php?" + q,
        headers={"User-Agent": "SignboardFeeds/0.1 (personal hobby project)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    out = {}
    for page in data["query"]["pages"]:
        item = page.get("pageprops", {}).get("wikibase_item")
        if item:
            out[page["title"]] = item
    return out


def qid_descriptions(qids: list[str]) -> dict[str, dict]:
    """Description plus an is_person flag (instance of human, Q5).

    The flag drives the works-before-people ordering of trending
    rows: a surge caused by a TV appearance lands on the person,
    but the board prefers the works themselves.
    """
    values = " ".join(f"wd:{q}" for q in qids)
    q = f"""
SELECT ?item ?itemDescription (MAX(?h) AS ?human) WHERE {{
  VALUES ?item {{ {values} }}
  OPTIONAL {{ ?item wdt:P31 wd:Q5 . BIND(1 AS ?h) }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ja,en" }}
}}
GROUP BY ?item ?itemDescription
"""
    out = {}
    for b in sparql(q):
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        out[qid] = {
            "description": b.get("itemDescription", {}).get("value", ""),
            "is_person": b.get("human", {}).get("value") == "1",
        }
    return out


def confirm_newbook(cand: dict, today: datetime) -> dict | None:
    """Promote a surging manga series to a release row, if confirmed.

    Chain: MADB finds the newest volume and its ISBN; openBD must
    confirm that ISBN. If either step fails, this returns None and
    the caller falls back to a plain "trending" row — the feed never
    claims a release it could not confirm.
    """
    core = re.sub(r"[（(][^）)]*[）)]$", "", cand["title"]).strip()
    if len(core) < 2:
        return None
    vols = madb.latest_manga_volumes(core)
    if not vols:
        return None
    v = vols[0]
    digits = re.sub(r"\D", "", v["date"])
    if len(digits) < 6:
        return None
    y, m = int(digits[:4]), int(digits[4:6])
    d = int(digits[6:8]) if len(digits) >= 8 else 1
    try:
        pub = date(y, m, d)
    except ValueError:
        return None
    if not (0 <= (today.date() - pub).days <= 45):
        return None  # outside the "new release" window (MADB lags ~3 weeks)
    if not v["isbn"] or openbd.get_by_isbn(v["isbn"]) is None:
        return None
    vol_txt = f"最新{v['volume']}巻" if v["volume"] else "新刊"
    return {
        "title": f"マンガ『{core}』{vol_txt}が発売",
        "link": f"https://www.wikidata.org/wiki/{cand['qid']}",
        "category": "新刊",
        "guid": f"culture-newbook-{v['isbn']}",
        "description": f"{y}年{m}月{d}日発売（MADB・openBDで確認）。"
                       f"日本語版 Wikipedia で閲覧数が急上昇中",
    }


def build_trending_items(today: datetime) -> list[dict]:
    """'Now' rows from Pageviews surges, with dated fallback.

    Pageviews data is published with a lag, so the newest available
    day is found by walking back (common.pageviews.latest_top); the
    baseline is the day one week before THAT day, with its own
    fallback. The data date is stated in every row.
    """
    found = pageviews.latest_top(today.date())
    if not found:
        return []
    data_date, latest = found
    base = pageviews.top_near(data_date - timedelta(days=7))
    if not base:
        return []
    _, baseline = base
    base_views = {a["article"]: a["views"] for a in baseline}
    base_floor = min(base_views.values()) if base_views else 1

    cands = []
    for a in latest[:300]:
        title = a["article"]
        if title == "メインページ" or title.startswith("特別:"):
            continue
        views = a["views"]
        if views < 30000:
            continue
        prev = base_views.get(title)
        ratio = views / prev if prev else views / max(base_floor, 1)
        if ratio >= 2.5:
            cands.append({"title": title.replace("_", " "),
                          "views": views, "ratio": ratio})
    cands.sort(key=lambda c: c["views"] * c["ratio"], reverse=True)
    cands = cands[:40]
    if not cands:
        return []

    qids = wiki_qids([c["title"] for c in cands])
    descriptions = qid_descriptions(list(qids.values())) if qids else {}
    culture = []
    for c in cands:
        qid = qids.get(c["title"])
        if not qid:
            continue
        info = descriptions.get(qid)
        if not info:
            continue
        desc = info["description"]
        if not any(k in desc for k in TREND_KEYWORDS):
            continue
        culture.append({**c, "qid": qid, "description": desc,
                        "is_person": info["is_person"]})
    # Works before people: a TV appearance makes the person surge,
    # but the board prefers the works themselves. People still fill
    # any slots the works leave open.
    picked = ([c for c in culture if not c["is_person"]]
              + [c for c in culture if c["is_person"]])[:3]

    items = []
    newbook_done = False
    for c in picked:
        if not newbook_done and ("漫画" in c["description"] or "マンガ" in c["description"]):
            try:
                nb = confirm_newbook(c, today)
            except Exception:
                nb = None
            if nb:
                items.append(nb)
                newbook_done = True
                continue
        items.append({
            "title": f"いま話題『{c['title']}』",
            "link": f"https://www.wikidata.org/wiki/{c['qid']}",
            "category": "話題",
            "guid": f"culture-trending-{c['qid']}-{data_date:%Y%m%d}",
            "description": f"日本語版 Wikipedia の閲覧数 {c['views']:,} 回"
                           f"（{data_date.month}月{data_date.day}日時点）、"
                           f"1週間前と比べて約{int(c['ratio'] + 0.5)}倍",
        })
    return items


def build_items(today: datetime) -> list[dict]:
    y, m, d = today.year, today.month, today.day
    items = []
    try:
        items += build_trending_items(today)
    except Exception as e:  # "now" rows are optional; anniversaries must survive
        print(f"trending rows skipped: {e}", file=sys.stderr)

    films = pick(parse_rows(anniversary_query(FILMS_Q, m, d, 20)), y, cap=2, min_years=10)
    for r in films:
        n = y - r["year"]
        items.append({
            "title": f"映画『{r['label']}』公開から{n}年",
            "link": f"https://www.wikidata.org/wiki/{r['qid']}",
            "category": "映画",
            "guid": f"culture-{r['qid']}-{y}",
            "description": f"{r['year']}年{m}月{d}日公開（Wikidata）",
        })

    games = pick(parse_rows(anniversary_query(GAMES_Q, m, d, 10)), y, cap=2, min_years=10)
    for r in games:
        n = y - r["year"]
        items.append({
            "title": f"ゲーム『{r['label']}』発売から{n}年",
            "link": f"https://www.wikidata.org/wiki/{r['qid']}",
            "category": "ゲーム",
            "guid": f"culture-{r['qid']}-{y}",
            "description": f"{r['year']}年{m}月{d}日発売（Wikidata）",
        })

    births = parse_rows(births_query(m, d, 30))
    births = [r for r in births if any(k in r["description"] for k in CULTURE_KEYWORDS)]
    births = pick(births, y, cap=2)
    for r in births:
        items.append({
            "title": f"{r['label']} の誕生日",
            "link": f"https://www.wikidata.org/wiki/{r['qid']}",
            "category": "誕生日",
            "guid": f"culture-{r['qid']}-{y}",
            "description": f"{r['year']}年{m}月{d}日生まれ。{r['description']}（Wikidata）",
        })

    return items


def main() -> int:
    today = datetime.now(JST)
    items = build_items(today)
    pub = today.strftime("%a, %d %b %Y 06:00:00 +0900")
    xml = render_rss(
        title="MSatake Culture",
        link="https://www.wikidata.org/",
        description="カルチャーの記念日と、いま話題の作品（出典：Wikidata、Wikimedia Pageviews、MADB、openBD）",
        items=items,
        pub_date=pub,
    )
    out = sys.argv[1] if len(sys.argv) > 1 else "culture.xml"
    with open(out, "w", encoding="utf-8") as f:
        f.write(xml)
    for it in items:
        print(f"[{it['category']}] {it['title']}")
    print(f"-> {out} ({len(items)} items)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
