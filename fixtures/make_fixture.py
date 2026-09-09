"""產生示範資料 fixtures/sample-{am,pm}.json（隨機走勢，僅供測試版面，非真實行情）。

python3 fixtures/make_fixture.py
"""
from __future__ import annotations

import json
import math
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fetch.common import load_config, pct, rnd  # noqa: E402
from fetch.quotes import summarize  # noqa: E402

import pandas as pd  # noqa: E402

random.seed(42)
ROOT = Path(__file__).resolve().parent


def walk(start: float, days: int, vol: float, drift: float = 0.0003, end: datetime | None = None) -> pd.DataFrame:
    end = end or datetime(2026, 9, 8)
    dates = pd.bdate_range(end=end, periods=days)
    px = [start]
    for _ in range(days - 1):
        px.append(px[-1] * math.exp(random.gauss(drift, vol)))
    rows = []
    for d, c in zip(dates, px):
        o = c * (1 + random.gauss(0, vol / 2))
        h = max(o, c) * (1 + abs(random.gauss(0, vol / 2)))
        l = min(o, c) * (1 - abs(random.gauss(0, vol / 2)))
        v = abs(random.gauss(1, 0.3)) * 1e7
        rows.append({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v})
    return pd.DataFrame(rows, index=dates)


def series(sym: str, name: str, start: float, vol: float = 0.012, keep_hist: bool = True, days: int = 120):
    s = summarize(walk(start, days + 60, vol).tail(days), sym, name)
    if not keep_hist:
        s.pop("history", None)
    return s


def tw_stock(code: str, name: str, px: float, chg_pct: float, turnover: float):
    chg = px * chg_pct / 100
    return {"symbol": code, "name": name, "last": rnd(px), "change": rnd(chg), "change_pct": rnd(chg_pct),
            "turnover": turnover, "volume": turnover / px, "trades": int(turnover / px / 800),
            "open": rnd(px - chg * 0.6), "high": rnd(px + abs(chg) * 0.4), "low": rnd(px - abs(chg) * 0.9)}


def build(session: str) -> dict:
    cfg = load_config()
    us_idx = {"^GSPC": ("S&P 500", 6480), "^IXIC": ("Nasdaq", 21750), "^DJI": ("道瓊工業", 45200), "^SOX": ("費城半導體", 5850), "^RUT": ("羅素 2000", 2360)}
    macro = {"^VIX": ("VIX 恐慌指數", 15.2, 0.06), "^TNX": ("美債 10 年殖利率", 4.12, 0.012), "DX-Y.NYB": ("美元指數", 97.8, 0.004),
             "TWD=X": ("USD/TWD", 30.6, 0.004), "GC=F": ("黃金", 3560, 0.01), "CL=F": ("WTI 原油", 63.5, 0.02), "BTC-USD": ("比特幣", 111000, 0.03)}
    us = {
        "indices": {k: series(k, n, p) for k, (n, p) in us_idx.items()},
        "macro": {k: series(k, n, p, v) for k, (n, p, v) in macro.items()},
        "futures": {k: series(k, n, p, keep_hist=False) for k, (n, p) in {"ES=F": ("S&P 500 期貨", 6495), "NQ=F": ("Nasdaq 期貨", 23700)}.items()},
        "sectors": {k: series(k, n, 100 + random.random() * 50, keep_hist=False) for k, n in cfg["us_sectors"].items()},
        "watchlist": {k: series(k, n, p, 0.02) for k, (n, p) in {"NVDA": ("NVIDIA", 172), "TSM": ("Taiwan Semiconductor ADR", 245), "AAPL": ("Apple", 236), "MSFT": ("Microsoft", 502)}.items()},
    }
    uni = {k: series(k, k, 50 + random.random() * 400, 0.025, keep_hist=False) for k in cfg["us_universe"]}
    rows = sorted(uni.values(), key=lambda r: r["change_pct"], reverse=True)
    us["movers"] = {"gainers": rows[:5], "losers": list(reversed(rows[-5:])),
                    "volume_surge": sorted(rows, key=lambda r: r["volume_ratio"] or 0, reverse=True)[:5]}
    us["universe_count"] = len(uni)

    taiex = series("^TWII", "加權指數", 24800, 0.011)
    taiex.update({"symbol": None})
    sectors = [{"name": n, "last": rnd(300 + random.random() * 500), "change": 0, "change_pct": rnd(random.gauss(0.2, 1.2))} for n in cfg["tw_sectors"]]
    for s in sectors:
        s["change"] = rnd(s["last"] * s["change_pct"] / 100)
    names = {"2330": "台積電", "2317": "鴻海", "2454": "聯發科", "0050": "元大台灣50", "2382": "廣達", "3231": "緯創", "2308": "台達電",
             "2603": "長榮", "2881": "富邦金", "3017": "奇鋐", "2345": "智邦", "6669": "緯穎", "2412": "中華電", "1301": "台塑", "2002": "中鋼"}
    px = {"2330": 1180, "2317": 205, "2454": 1420, "0050": 56.8, "2382": 292, "3231": 118, "2308": 720, "2603": 210, "2881": 88.5,
          "3017": 1210, "2345": 940, "6669": 3150, "2412": 128, "1301": 42.1, "2002": 22.4}
    stocks = {c: tw_stock(c, n, px[c], random.gauss(0.3, 2.5), random.random() * 3e10 + 1e9) for c, n in names.items()}
    watch = {}
    for c in cfg["watchlist"]["tw"]:
        s = series(f"{c}.TW", names[c], px[c], 0.018)
        s.update(stocks[c])
        s["institutional"] = {"symbol": c, "name": names[c], "foreign_net_shares": random.randint(-20000000, 20000000),
                              "trust_net_shares": random.randint(-2000000, 2000000), "total_net_shares": random.randint(-20000000, 20000000)}
        watch[c] = s
    srt = sorted(stocks.values(), key=lambda r: r["change_pct"], reverse=True)
    inst_rows = [{"symbol": c, "name": n, "foreign_net_shares": random.randint(-30000000, 30000000)} for c, n in names.items()]
    inst_rows.sort(key=lambda r: r["foreign_net_shares"], reverse=True)
    trade_date = datetime(2026, 9, 9) if session == "pm" else datetime(2026, 9, 8)
    tw = {
        "trade_date": trade_date.strftime("%Y-%m-%d"), "is_today": session == "pm",
        "taiex": taiex,
        "turnover_ntd": 4.21e11, "turnover_ntd_stocks": 4.05e11,
        "breadth": {"up": 512, "down": 401, "flat": 98, "limit_up": 14, "limit_down": 3},
        "sectors": sectors,
        "institutional": {"date": trade_date.strftime("%Y-%m-%d"), "foreign_net": 8.63e9, "trust_net": 2.1e9, "dealer_net": -1.4e9, "total_net": 9.33e9},
        "foreign_buy_top": inst_rows[:5], "foreign_sell_top": list(reversed(inst_rows[-5:])),
        "movers": {"gainers": srt[:5], "losers": list(reversed(srt[-5:])), "turnover_top": sorted(stocks.values(), key=lambda r: r["turnover"], reverse=True)[:5]},
        "watchlist": watch, "listed_count": 1050,
    }
    tsm = us["watchlist"]["TSM"]["last"]; twd = us["macro"]["TWD=X"]["last"]; local = watch["2330"]["last"]
    derived = {"tsm_adr": {"adr_usd": tsm, "adr_change_pct": us["watchlist"]["TSM"]["change_pct"], "usdtwd": twd,
                           "implied_twd": rnd(tsm * twd / 5), "local_close": local, "premium_pct": rnd((tsm * twd / 5 / local - 1) * 100)}}
    news = {
        "general": [
            {"title": "【示範】台股早盤在權值股帶動下震盪走高，半導體族群強勢", "link": "https://example.com/1", "source": "示範新聞", "published": "2026-09-09 09:30", "query": "台股 大盤"},
            {"title": "【示範】外資連三日買超，資金回流電子權值股", "link": "https://example.com/2", "source": "示範新聞", "published": "2026-09-09 08:10", "query": "外資"},
            {"title": "[Sample] Stocks edge higher as investors await inflation data", "link": "https://example.com/3", "source": "Sample Wire", "published": "2026-09-08 22:05", "query": "stock market today"},
            {"title": "[Sample] Chipmakers rally on AI demand outlook", "link": "https://example.com/4", "source": "Sample Wire", "published": "2026-09-08 21:40", "query": "semiconductor"},
            {"title": "【示範】聯準會官員談話：通膨仍需觀察，降息路徑未定", "link": "https://example.com/5", "source": "示範新聞", "published": "2026-09-08 20:00", "query": "Fed"},
        ],
        "watchlist": {"2330": [{"title": "【示範】台積電 ADR 溢價擴大，法人看好先進製程需求", "link": "https://example.com/6", "source": "示範新聞", "published": "2026-09-09 07:50"}],
                      "NVDA": [{"title": "[Sample] Nvidia shares climb ahead of product event", "link": "https://example.com/7", "source": "Sample Wire", "published": "2026-09-08 21:00"}]},
    }
    return {"meta": {"key": f"2026-09-09-{session}", "session": session, "date": "2026-09-09", "generated_at": "2026-09-09T08:30:00+08:00",
                     "is_sample": True, "errors": [], "watchlist": cfg["watchlist"]},
            "us": us, "tw": tw, "derived": derived, "news": news}


if __name__ == "__main__":
    for s in ("am", "pm"):
        with open(ROOT / f"sample-{s}.json", "w", encoding="utf-8") as f:
            json.dump(build(s), f, ensure_ascii=False, default=str)
        print("wrote", ROOT / f"sample-{s}.json")
