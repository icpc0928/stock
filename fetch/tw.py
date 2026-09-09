"""台股：TWSE 官方 JSON（大盤、類股指數、漲跌家數、三大法人、全市場個股）+ yfinance 走勢。

資料來源：
  - https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX   每日收盤行情（指數、統計、全部個股）
  - https://www.twse.com.tw/rwd/zh/fund/BFI82U             三大法人買賣金額統計
  - https://www.twse.com.tw/rwd/zh/fund/T86                三大法人買賣超（個股）
  - yfinance ^TWII / 2330.TW                                走勢圖
（不含櫃買：依 Leo 需求省略）
TWSE 資料在收盤後約 15:00 起陸續更新；早報抓的是「最近一個交易日」。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

from .common import now_tw, pct, previous_weekday, retry, rnd
from .quotes import fetch_many, strip_history

log = logging.getLogger("fetch.tw")

TWSE = "https://www.twse.com.tw/rwd/zh"
HEADERS = {"User-Agent": "Mozilla/5.0 (daily-market-report; personal use)", "Accept": "application/json"}


def _num(s) -> Optional[float]:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = re.sub(r"<[^>]+>", "", str(s)).replace(",", "").strip()
    if t in ("", "--", "---", "X", "除權息"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _sign(s) -> int:
    t = re.sub(r"<[^>]+>", "", str(s or "")).strip()
    return -1 if t == "-" else (1 if t == "+" else 0)


def _get(url: str, params: dict) -> dict:
    def go():
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return r.json()
    return retry(go, label=url.rsplit("/", 1)[-1])


def _table(payload: dict, title_kw: str) -> Optional[dict]:
    for t in payload.get("tables", []):
        if title_kw in (t.get("title") or ""):
            return t
    return None


def _rows(t: Optional[dict]) -> List[dict]:
    if not t:
        return []
    fields = t.get("fields", [])
    return [dict(zip(fields, row)) for row in t.get("data", [])]


# ------------------------------------------------------------------ MI_INDEX
def fetch_mi_index(date: datetime) -> Tuple[Optional[dict], datetime]:
    """回傳 (payload, 實際交易日)。遇到假日自動往前找最多 7 天。"""
    d = date
    for _ in range(7):
        p = _get(f"{TWSE}/afterTrading/MI_INDEX", {"date": d.strftime("%Y%m%d"), "type": "ALL", "response": "json"})
        if p.get("stat") == "OK" and p.get("tables"):
            return p, d
        log.info("%s 無交易資料 (%s)，往前一天", d.date(), p.get("stat"))
        d = previous_weekday(d)
    return None, date


def parse_mi_index(p: dict, sector_names: List[str]) -> dict:
    # 價格指數
    idx_rows = _rows(_table(p, "價格指數"))
    indices = {}
    for r in idx_rows:
        name = (r.get("指數") or "").strip()
        close = _num(r.get("收盤指數"))
        if not name or close is None:
            continue
        sign = _sign(r.get("漲跌(+/-)"))
        chg = abs(_num(r.get("漲跌點數")) or 0) * sign
        pct_raw = _num(r.get("漲跌百分比(%)"))
        indices[name] = {
            "name": name,
            "last": rnd(close),
            "change": rnd(chg),
            "change_pct": rnd(abs(pct_raw) * sign) if pct_raw is not None else None,
        }
    taiex = indices.get("發行量加權股價指數")
    sectors = [indices[n] for n in sector_names if n in indices]

    # 大盤統計資訊
    stats = {}
    for r in _rows(_table(p, "大盤統計資訊")):
        stats[(r.get("成交統計") or "").strip()] = {
            "amount": _num(r.get("成交金額(元)")),
            "shares": _num(r.get("成交股數(股)")),
            "trades": _num(r.get("成交筆數")),
        }
    total = stats.get("1.一般股票") or stats.get("合計") or next(iter(stats.values()), {})
    market_total = stats.get("合計") or total

    # 漲跌證券數
    breadth = {}
    for r in _rows(_table(p, "漲跌證券數")):
        k = (r.get("類型") or "").strip()
        v = r.get("股票") if "股票" in r else r.get("整體市場")
        m = re.match(r"([\d,]+)", str(v or ""))
        n = int(m.group(1).replace(",", "")) if m else None
        if "上漲" in k:
            breadth["up"] = n
            breadth["limit_up"] = int(re.search(r"\((\d+)\)", str(v)).group(1)) if re.search(r"\((\d+)\)", str(v)) else None
        elif "下跌" in k:
            breadth["down"] = n
            breadth["limit_down"] = int(re.search(r"\((\d+)\)", str(v)).group(1)) if re.search(r"\((\d+)\)", str(v)) else None
        elif "持平" in k:
            breadth["flat"] = n

    # 全部個股
    stocks = {}
    for r in _rows(_table(p, "每日收盤行情")):
        code = (r.get("證券代號") or "").strip()
        if not code:
            continue
        close = _num(r.get("收盤價"))
        chg = (_num(r.get("漲跌價差")) or 0) * _sign(r.get("漲跌(+/-)"))
        prev = close - chg if close is not None else None
        stocks[code] = {
            "symbol": code,
            "name": (r.get("證券名稱") or "").strip(),
            "last": rnd(close),
            "change": rnd(chg),
            "change_pct": pct(close, prev),
            "turnover": _num(r.get("成交金額")),
            "volume": _num(r.get("成交股數")),
            "trades": _num(r.get("成交筆數")),
            "open": _num(r.get("開盤價")),
            "high": _num(r.get("最高價")),
            "low": _num(r.get("最低價")),
        }
    return {
        "taiex": taiex,
        "sectors": sectors,
        "turnover_ntd": (market_total or {}).get("amount"),
        "turnover_ntd_stocks": (total or {}).get("amount"),
        "breadth": breadth,
        "stocks": stocks,
    }


# ------------------------------------------------------------------ 三大法人
def fetch_institutional(date: datetime) -> Optional[dict]:
    p = _get(f"{TWSE}/fund/BFI82U", {"dayDate": date.strftime("%Y%m%d"), "type": "day", "response": "json"})
    if p.get("stat") != "OK":
        return None
    out = {}
    for row in p.get("data", []):
        name = str(row[0]).strip()
        buy, sell, net = _num(row[1]), _num(row[2]), _num(row[3])
        out[name] = {"buy": buy, "sell": sell, "net": net}
    # 統一成三大分類 + 合計（單位：元）
    def get(*keys):
        return sum((out.get(k, {}).get("net") or 0) for k in keys)
    return {
        "date": date.strftime("%Y-%m-%d"),
        "foreign_net": get("外資及陸資(不含外資自營商)", "外資自營商"),
        "trust_net": get("投信"),
        "dealer_net": get("自營商(自行買賣)", "自營商(避險)"),
        "total_net": get("合計"),
        "raw": out,
    }


def fetch_t86(date: datetime, top_n: int = 5) -> Optional[dict]:
    """個股三大法人買賣超 → 外資買超/賣超前 N（股數）。"""
    p = _get(f"{TWSE}/fund/T86", {"date": date.strftime("%Y%m%d"), "selectType": "ALL", "response": "json"})
    if p.get("stat") != "OK":
        return None
    fields = p.get("fields", [])
    rows = [dict(zip(fields, r)) for r in p.get("data", [])]

    def col(r, kw):
        for k, v in r.items():
            if kw in k:
                return _num(v)
        return None

    items = []
    for r in rows:
        code = (r.get("證券代號") or "").strip()
        if not code:
            continue
        items.append({
            "symbol": code,
            "name": (r.get("證券名稱") or "").strip(),
            "foreign_net_shares": col(r, "外陸資買賣超股數(不含外資自營商)") or col(r, "外資買賣超股數"),
            "trust_net_shares": col(r, "投信買賣超股數"),
            "total_net_shares": col(r, "三大法人買賣超股數"),
        })
    by_symbol = {i["symbol"]: i for i in items}
    f = [i for i in items if i["foreign_net_shares"] is not None]
    f.sort(key=lambda i: i["foreign_net_shares"], reverse=True)
    return {
        "foreign_buy_top": f[:top_n],
        "foreign_sell_top": list(reversed(f[-top_n:])),
        "by_symbol": by_symbol,
    }


# ------------------------------------------------------------------ 主流程
def _movers(stocks: Dict[str, dict], top_n: int, min_turnover: float) -> dict:
    rows = [s for s in stocks.values() if s.get("change_pct") is not None and (s.get("turnover") or 0) >= min_turnover
            and len(s["symbol"]) == 4 and s["symbol"].isdigit()]
    by_chg = sorted(rows, key=lambda r: r["change_pct"], reverse=True)
    by_turn = sorted(rows, key=lambda r: r.get("turnover") or 0, reverse=True)
    return {"gainers": by_chg[:top_n], "losers": list(reversed(by_chg[-top_n:])), "turnover_top": by_turn[:top_n]}


def fetch_tw(cfg: dict, session: str) -> dict:
    now = now_tw(cfg)
    # 早報：抓最近一個交易日（通常是昨天）；午報：抓今天
    base = now if session == "pm" else previous_weekday(now)
    payload, trade_date = fetch_mi_index(base)
    if payload is None:
        raise RuntimeError("TWSE MI_INDEX 連續 7 天無資料")
    mi = parse_mi_index(payload, cfg.get("tw_sectors", []))

    inst = None
    t86 = None
    try:
        inst = fetch_institutional(trade_date)
        t86 = fetch_t86(trade_date, cfg["auto_movers"]["tw"].get("top_n", 5))
    except Exception as e:  # noqa: BLE001
        log.warning("三大法人資料抓取失敗: %s", e)

    all_stocks = mi["stocks"]

    top_n = cfg["auto_movers"]["tw"].get("top_n", 5)
    min_turn = float(cfg["auto_movers"]["tw"].get("min_turnover_ntd", 1e9))
    movers = _movers(all_stocks, top_n, min_turn)

    # 自選股：今日快照 + yfinance 走勢
    watch = [str(s) for s in cfg["watchlist"].get("tw", [])]
    days = cfg["report"].get("history_days", 120)
    yf_syms = {s: f"{s}.TW" for s in watch}
    yf_names = {v: all_stocks.get(k, {}).get("name", k) for k, v in yf_syms.items()}
    idx_syms = dict(cfg["indices"].get("tw", {}))
    hist = fetch_many(list(yf_syms.values()) + list(idx_syms), {**yf_names, **idx_syms}, days=days,
                      end=trade_date.strftime("%Y-%m-%d"))

    watchlist = {}
    for code, ysym in yf_syms.items():
        snap = all_stocks.get(code, {"symbol": code, "name": code})
        h = hist.get(ysym)
        merged = {**(h or {}), **snap}
        if h:
            merged["history"] = h["history"]
            for k in ("chg_5d_pct", "chg_1m_pct", "chg_ytd_pct", "high_52w", "low_52w", "pos_52w_pct",
                      "ma20", "ma60", "vs_ma20_pct", "vs_ma60_pct", "rsi14", "volume_ratio"):
                merged[k] = h.get(k)
        if t86 and code in t86["by_symbol"]:
            merged["institutional"] = t86["by_symbol"][code]
        watchlist[code] = merged

    # 指數：以 TWSE 當日數字為準，走勢用 yfinance
    taiex = dict(mi["taiex"] or {})
    if "^TWII" in hist:
        taiex["history"] = hist["^TWII"]["history"]
        for k in ("chg_5d_pct", "chg_1m_pct", "chg_ytd_pct", "high_52w", "low_52w", "pos_52w_pct", "ma20", "ma60", "vs_ma20_pct", "vs_ma60_pct", "rsi14"):
            taiex[k] = hist["^TWII"].get(k)
    taiex.setdefault("name", "加權指數")

    return {
        "trade_date": trade_date.strftime("%Y-%m-%d"),
        "is_today": trade_date.date() == now.date(),
        "taiex": taiex,
        "turnover_ntd": mi["turnover_ntd"],
        "turnover_ntd_stocks": mi["turnover_ntd_stocks"],
        "breadth": mi["breadth"],
        "sectors": mi["sectors"],
        "institutional": inst,
        "foreign_buy_top": (t86 or {}).get("foreign_buy_top", []),
        "foreign_sell_top": (t86 or {}).get("foreign_sell_top", []),
        "movers": movers,
        "watchlist": watchlist,
        "listed_count": len(mi["stocks"]),
    }
