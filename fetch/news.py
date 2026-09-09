"""新聞：Google News RSS（不需 API key）。"""
from __future__ import annotations

import logging
import time
from typing import Dict, List
from urllib.parse import quote

import feedparser

log = logging.getLogger("fetch.news")

LANG = {
    "zh-TW": {"hl": "zh-TW", "gl": "TW", "ceid": "TW:zh-Hant"},
    "en-US": {"hl": "en-US", "gl": "US", "ceid": "US:en"},
}


def _rss(query: str, lang: str, limit: int) -> List[dict]:
    p = LANG.get(lang, LANG["zh-TW"])
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl={p['hl']}&gl={p['gl']}&ceid={p['ceid']}"
    try:
        feed = feedparser.parse(url)
    except Exception as e:  # noqa: BLE001
        log.warning("RSS 失敗 %s: %s", query, e)
        return []
    items = []
    for e in feed.entries[:limit]:
        published = ""
        if getattr(e, "published_parsed", None):
            published = time.strftime("%Y-%m-%d %H:%M", e.published_parsed)
        source = ""
        if getattr(e, "source", None):
            source = e.source.get("title", "")
        title = e.get("title", "")
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        items.append({"title": title, "link": e.get("link", ""), "source": source, "published": published, "query": query})
    return items


def fetch_news(cfg: dict, watch_names: Dict[str, str]) -> dict:
    ncfg = cfg.get("news", {})
    limit = int(ncfg.get("max_per_query", 8))
    general: List[dict] = []
    seen = set()
    for q in ncfg.get("queries", []):
        for it in _rss(q["q"], q.get("lang", "zh-TW"), limit):
            if it["title"] in seen:
                continue
            seen.add(it["title"])
            general.append(it)

    per_symbol: Dict[str, List[dict]] = {}
    if ncfg.get("watchlist_news", True):
        n = int(ncfg.get("watchlist_news_per_symbol", 3))
        for sym, name in watch_names.items():
            lang = "zh-TW" if sym.isdigit() else "en-US"
            q = f"{name} 股票" if sym.isdigit() else f"{name} stock"
            per_symbol[sym] = _rss(q, lang, n)
    log.info("新聞 %d 則、自選股新聞 %d 檔", len(general), len(per_symbol))
    return {"general": general, "watchlist": per_symbol}
