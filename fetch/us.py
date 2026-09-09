"""美股：指數、總經指標、期貨、類股 ETF、自選股、自動漲跌榜。"""
from __future__ import annotations

import logging
from typing import Dict, List

from .quotes import fetch_many, strip_history

log = logging.getLogger("fetch.us")


def _movers(universe: Dict[str, dict], top_n: int) -> dict:
    rows = [strip_history(v) for v in universe.values() if v.get("change_pct") is not None]
    by_chg = sorted(rows, key=lambda r: r["change_pct"], reverse=True)
    by_volr = sorted([r for r in rows if r.get("volume_ratio")], key=lambda r: r["volume_ratio"], reverse=True)
    return {
        "gainers": by_chg[:top_n],
        "losers": list(reversed(by_chg[-top_n:])),
        "volume_surge": by_volr[:top_n],
    }


def fetch_us(cfg: dict, session: str) -> dict:
    days = cfg["report"].get("history_days", 120)
    idx_cfg = cfg["indices"]
    watch: List[str] = [s.upper() for s in cfg["watchlist"].get("us", [])]
    universe: List[str] = [s.upper() for s in cfg.get("us_universe", [])]
    sectors: Dict[str, str] = cfg.get("us_sectors", {})

    names = {**idx_cfg["us"], **idx_cfg["macro"], **idx_cfg.get("futures", {}), **sectors, **cfg.get("us_names", {})}
    all_syms = (list(idx_cfg["us"]) + list(idx_cfg["macro"]) + list(idx_cfg.get("futures", {}))
                + list(sectors) + watch + universe)
    data = fetch_many(all_syms, names, days=days)

    def pick(keys, keep_hist=False):
        out = {}
        for k in keys:
            if k in data:
                out[k] = data[k] if keep_hist else strip_history(data[k])
        return out

    uni = pick(universe)
    top_n = cfg["auto_movers"]["us"].get("top_n", 5)
    return {
        "indices": pick(idx_cfg["us"], keep_hist=True),
        "macro": pick(idx_cfg["macro"], keep_hist=True),
        "futures": pick(idx_cfg.get("futures", {})),
        "sectors": pick(sectors),
        "watchlist": pick(watch, keep_hist=True),
        "movers": _movers(uni, top_n),
        "universe_count": len(uni),
    }
