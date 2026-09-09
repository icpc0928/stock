"""抓取入口：python3 -m fetch.run --session am|pm [--fixture] [--wait]

產出 data/YYYY-MM-DD-{am,pm}.json，給 Claude 分析與 build 組版用。
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime

from .common import (ANALYSIS_DIR, FIXTURES_DIR, data_path, dump_json, load_config, load_json, now_tw, report_key, rnd)

log = logging.getLogger("fetch.run")


def _derived(us: dict, tw: dict) -> dict:
    """跨市場衍生指標：台積電 ADR 溢價、美元台幣。"""
    out = {}
    tsm = (us.get("watchlist") or {}).get("TSM") or {}
    twd = (us.get("macro") or {}).get("TWD=X") or {}
    t2330 = (tw.get("watchlist") or {}).get("2330") or {}
    if tsm.get("last") and twd.get("last") and t2330.get("last"):
        implied = tsm["last"] * twd["last"] / 5.0  # 1 ADR = 5 股
        out["tsm_adr"] = {
            "adr_usd": tsm["last"],
            "adr_change_pct": tsm.get("change_pct"),
            "usdtwd": twd["last"],
            "implied_twd": rnd(implied),
            "local_close": t2330["last"],
            "premium_pct": rnd((implied / t2330["last"] - 1) * 100),
        }
    return out


def _fixture(session: str, cfg: dict) -> dict:
    p = FIXTURES_DIR / f"sample-{session}.json"
    d = load_json(p)
    now = now_tw(cfg)
    d["meta"]["generated_at"] = now.isoformat(timespec="seconds")
    d["meta"]["key"] = report_key(session, now, cfg)
    d["meta"]["is_sample"] = True
    # 連示範評論一起放進去，讓 --fixture 能看到完整版面
    sample_a = FIXTURES_DIR / f"sample-analysis-{session}.json"
    target = ANALYSIS_DIR / f"{d['meta']['key']}.json"
    if sample_a.exists() and not target.exists():
        a = load_json(sample_a)
        a["key"] = d["meta"]["key"]
        dump_json(target, a)
    return d


def _wait_for_pm_data(cfg: dict) -> None:
    """午報：等 TWSE 今日資料出現，最多等 pm_wait_for_data_minutes。"""
    from .tw import fetch_mi_index
    deadline = time.time() + 60 * int(cfg.get("pm_wait_for_data_minutes", 30))
    today = now_tw(cfg)
    while True:
        try:
            p, d = fetch_mi_index(today)
            if p and d.date() == today.date():
                return
        except Exception as e:  # noqa: BLE001
            log.warning("等待資料時發生錯誤: %s", e)
        if time.time() > deadline:
            log.warning("等不到今日 TWSE 資料，改用最近一個交易日")
            return
        log.info("TWSE 今日資料尚未公布，60 秒後再試…")
        time.sleep(60)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", choices=["am", "pm"], required=True)
    ap.add_argument("--fixture", action="store_true", help="用 fixtures/ 的示範資料，不連網")
    ap.add_argument("--wait", action="store_true", help="午報：等 TWSE 今日資料公布再抓")
    ap.add_argument("--skip-news", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    cfg = load_config()
    now = now_tw(cfg)
    key = report_key(args.session, now, cfg)

    if args.fixture:
        data = _fixture(args.session, cfg)
    else:
        from .news import fetch_news
        from .tw import fetch_tw
        from .us import fetch_us

        if args.session == "pm" and args.wait:
            _wait_for_pm_data(cfg)
        errors = []
        us, tw, news = {}, {}, {"general": [], "watchlist": {}}
        try:
            us = fetch_us(cfg, args.session)
        except Exception as e:  # noqa: BLE001
            log.exception("美股抓取失敗")
            errors.append(f"us: {e}")
        try:
            tw = fetch_tw(cfg, args.session)
        except Exception as e:  # noqa: BLE001
            log.exception("台股抓取失敗")
            errors.append(f"tw: {e}")
        if not args.skip_news:
            try:
                names = {k: v.get("name", k) for k, v in (tw.get("watchlist") or {}).items()}
                names.update({k: v.get("name", k) for k, v in (us.get("watchlist") or {}).items()})
                news = fetch_news(cfg, names)
            except Exception as e:  # noqa: BLE001
                log.exception("新聞抓取失敗")
                errors.append(f"news: {e}")
        if not us and not tw:
            log.error("美股與台股皆抓取失敗，中止")
            return 2
        data = {
            "meta": {
                "key": key,
                "session": args.session,
                "date": now.strftime("%Y-%m-%d"),
                "generated_at": now.isoformat(timespec="seconds"),
                "is_sample": False,
                "errors": errors,
                "watchlist": cfg["watchlist"],
            },
            "us": us,
            "tw": tw,
            "derived": _derived(us, tw),
            "news": news,
        }

    out = data_path(key)
    dump_json(out, data)
    log.info("已寫入 %s", out)
    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
