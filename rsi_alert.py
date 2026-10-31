#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Binance SPOT / USDT  ---  RSI alert  ->  Telegram
Timeframes: 1h (every hour) and 4h (every 4h candle close).
Thresholds: 30 (normal) and 25 (marked with *).

Usage:
    python rsi_alert.py --tf 1h
    python rsi_alert.py --tf 4h
    python rsi_alert.py --tf 1h --dry
    python rsi_alert.py --tf 1h --thresholds 30,25

Secrets (optional, override config.json):
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
import datetime as dt
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "config.json")
LOG_PATH = os.path.join(HERE, "alert.log")

BASE = "https://api.binance.com"
UA = {"User-Agent": "Mozilla/5.0 (rsi-alert-bot)"}
TZ = dt.timezone(dt.timedelta(hours=3))  # Baghdad (no DST)

# ---------------------------------------------------------------- exclusions
CRYPTO_ENDING_IN_B = {"ARB", "BNB", "BB", "CKB", "DGB", "SHIB", "TRB", "GLMB", "OMB"}
COMMODITY = {"XAUT", "PAXG", "XAU", "XAG"}
STABLE = {
    "USDC", "FDUSD", "TUSD", "USDP", "DAI", "USDE", "XUSD", "EUR", "AEUR",
    "BUSD", "USDS", "PYUSD", "RLUSD", "USD1", "U", "EURI", "EURC", "USDQ",
    "BFUSD", "USDT",
}


def is_crypto_spot(base: str) -> bool:
    b = base.upper()
    if b in STABLE or b in COMMODITY:
        return False
    if b.endswith("B") and b not in CRYPTO_ENDING_IN_B:
        return False
    if b.endswith("UP") or b.endswith("DOWN") or b.endswith("BULL") or b.endswith("BEAR"):
        return False
    return True


# ---------------------------------------------------------------- http
HOSTS = ["https://api.binance.com", "https://data-api.binance.vision"]


def get(path: str, params: str = ""):
    suffix = path + (("?" + params) if params else "")
    last = None
    for attempt in range(4):
        host = HOSTS[attempt % len(HOSTS)]
        try:
            req = urllib.request.Request(host + suffix, headers=UA)
            with urllib.request.urlopen(req, timeout=12) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.5 * (attempt + 1))
    raise last


# ---------------------------------------------------------------- RSI (Wilder)
def rsi_wilder(closes, period=14):
    if len(closes) < period + 2:
        return None
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        if d > 0:
            gains += d
        else:
            losses -= d
    ag, al = gains / period, losses / period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (period - 1) + (d if d > 0 else 0.0)) / period
        al = (al * (period - 1) + (-d if d < 0 else 0.0)) / period
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def fmt_vol(v):
    if v >= 1e9:
        return f"{v/1e9:.2f}B"
    if v >= 1e6:
        return f"{v/1e6:.1f}M"
    if v >= 1e3:
        return f"{v/1e3:.0f}K"
    return f"{v:.0f}"


# ---------------------------------------------------------------- scan
def scan(cfg, interval, hist, period, workers):
    info = get("/api/v3/exchangeInfo", "permissions=SPOT")
    symbols = [
        s["symbol"]
        for s in info["symbols"]
        if s["quoteAsset"] == "USDT"
        and s["status"] == "TRADING"
        and s.get("isSpotTradingAllowed")
        and is_crypto_spot(s["baseAsset"])
    ]

    tick = {t["symbol"]: t for t in get("/api/v3/ticker/24hr")}
    server_ms = get("/api/v3/time")["serverTime"]

    def work(sym):
        try:
            k = get("/api/v3/klines", f"symbol={sym}&interval={interval}&limit={hist}")
            closed = [c for c in k if c[6] < server_ms]
            if len(closed) < period + 30:
                return None
            if server_ms - closed[-1][6] > 3 * 3600 * 1000:
                return None  # stale / delisted
            closes = [float(c[4]) for c in closed]
            r = rsi_wilder(closes, period)
            if r is None:
                return None
            t = tick.get(sym, {})
            return {
                "base": sym[:-4],
                "rsi": r,
                "chg": float(t.get("priceChangePercent", 0) or 0),
                "vol": float(t.get("quoteVolume", 0) or 0),
                "open_ms": closed[-1][0],
                "close_ms": closed[-1][6],
            }
        except Exception:  # noqa: BLE001
            return None

    out = [x for x in ThreadPoolExecutor(max_workers=workers).map(work, symbols) if x]
    out.sort(key=lambda x: x["rsi"])
    return out, server_ms


# ---------------------------------------------------------------- message
def build_messages(cfg, tf_label, rows, server_ms, thresholds, demo_note):
    main_thr = max(thresholds)
    deep_thr = min(thresholds) if len(thresholds) > 1 else None

    now = dt.datetime.fromtimestamp(server_ms / 1000, TZ)
    if rows:
        o = dt.datetime.fromtimestamp(rows[0]["open_ms"] / 1000, TZ)
        c = dt.datetime.fromtimestamp(rows[0]["close_ms"] / 1000, TZ)
        candle_txt = f"{o:%H:%M} → {c:%H:%M}"
    else:
        candle_txt = now.strftime("%H:%M")

    hits = [r for r in rows if r["rsi"] <= main_thr]
    deep = [r for r in hits if deep_thr is not None and r["rsi"] <= deep_thr]
    near = [r for r in rows if main_thr < r["rsi"] <= main_thr + 3][:3]

    head = (
        f"🔔 <b>تنبيه RSI — فريم {tf_label}</b>\n"
        f"🕐 <b>{now:%Y-%m-%d %H:%M}</b> (بغداد)\n"
        f"🕯 شمعة مقفلة: <code>{candle_txt}</code>\n"
        f"📉 وصلوا ≤ {main_thr:g}: <b>{len(hits)}</b> عملة"
        + (f"  |  🔥 ≤ {deep_thr:g}: <b>{len(deep)}</b>" if deep_thr is not None else "")
        + "\n\n"
    )
    if demo_note:
        head += "🔧 <i>رسالة تجريبية لعرض التصميم — مو تنبيه حقيقي</i>\n\n"

    footer_tip = (
        "\n\n<i>Wilder RSI-14 على إغلاقات الشموع — Binance Spot.</i>\n"
        "<i>مستثنى: الأسهم الموثقة، الذهب، الستيبل كوينز.</i>"
    )

    if not hits:
        body = "😴 <b>ماكو ولا عملة كريبتو تحت " + f"{main_thr:g}" + " هذي الشمعة</b>\n"
        if near:
            body += "\n🔎 الأقرب للحد:\n" + "\n".join(
                f"• <code>{r['base']}</code> — RSI {r['rsi']:.1f}" for r in near
            )
        return [head + body + footer_tip]

    header = f"{'#':>3}  {'PAIR':<10} {'RSI':>6} {'24h%':>7} {'VOL':>8}"
    lines = [header, "─" * len(header)]
    for i, r in enumerate(hits, 1):
        star = "*" if (deep_thr is not None and r["rsi"] <= deep_thr) else " "
        lines.append(
            f"{i:>3}  {r['base']:<10} {r['rsi']:>5.1f}{star} {r['chg']:>7.1f}% {fmt_vol(r['vol']):>8}"
        )

    foot = ""
    if deep_thr is not None and deep:
        foot += f"\n🔥 ≤ {deep_thr:g} (*): " + " · ".join(r["base"] for r in deep)
    if near:
        foot += "\n🔎 الأقرب للحد: " + " · ".join(f"{r['base']} {r['rsi']:.1f}" for r in near)

    msgs, chunk = [], []
    for line in lines:
        probe = "\n".join(chunk + [line])
        if len(head) + len(probe) + len(foot) + len(footer_tip) + 80 > 3700 and chunk:
            msgs.append(head + "<pre>" + "\n".join(chunk) + "</pre>")
            chunk = [header, "─" * len(header), line]
        else:
            chunk.append(line)
    if chunk:
        msgs.append(head + "<pre>" + "\n".join(chunk) + "</pre>" + foot + footer_tip)
    if len(msgs) > 1:
        msgs[0] += "\n<i>(يكمل بالرسالة التالية)</i>"
    return msgs


# ---------------------------------------------------------------- telegram
def send(cfg, text):
    url = f"https://api.telegram.org/bot{cfg['token']}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": cfg["chat_id"],
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(url, data=data, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{dt.datetime.now(TZ):%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def arg(flag, default=None):
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def main():
    cfg = json.load(open(CFG_PATH, encoding="utf-8-sig")) if os.path.exists(CFG_PATH) else {}
    cfg["token"] = os.environ.get("TELEGRAM_TOKEN") or cfg.get("token")
    cfg["chat_id"] = os.environ.get("TELEGRAM_CHAT_ID") or cfg.get("chat_id")

    tf = arg("--tf", "1h")
    if tf not in ("1h", "4h"):
        print("bad --tf"); return 2
    tf_label = "1 ساعة" if tf == "1h" else "4 ساعات"

    thr_raw = arg("--thresholds", cfg.get("thresholds", "30,25"))
    thresholds = [float(x) for x in str(thr_raw).split(",") if x.strip()]
    thresholds.sort()

    period = int(cfg.get("rsi_period", 14))
    hist = int(cfg.get("history_4h", 400)) if tf == "4h" else int(cfg.get("history_1h", 200))
    workers = int(cfg.get("workers", 8))

    t0 = time.time()
    rows = server_ms = None
    for attempt in range(2):
        try:
            rows, server_ms = scan(cfg, tf, hist, period, workers)
            break
        except Exception as e:  # noqa: BLE001
            log(f"SCAN FAILED tf={tf} try={attempt+1}: {e!r}")
            print("scan failed:", e)
            time.sleep(3)
    if rows is None:
        return 1

    # for 4h: only report right after a 4h candle actually closed
    if tf == "4h" and rows:
        age = server_ms - rows[0]["close_ms"]
        if age > 25 * 60 * 1000 and "--dry" not in sys.argv:
            log(f"4h: no fresh close (age {age/60000:.0f}m) - skipped")
            print("4h: no fresh close - skipped"); return 0

    msgs = build_messages(cfg, tf_label, rows, server_ms, thresholds, "--demo" in sys.argv)
    n = len([r for r in rows if r["rsi"] <= max(thresholds)])

    if "--dry" in sys.argv:
        for m in msgs:
            print(m); print("\n" + "=" * 60 + "\n")
        print(f"tf={tf} pairs={len(rows)} hits={n} {time.time()-t0:.1f}s")
        return 0

    if n == 0 and not cfg.get("send_when_empty", True):
        log(f"tf={tf} no hits ({len(rows)} pairs) - skipped")
        return 0

    try:
        for m in msgs:
            send(cfg, m)
            time.sleep(1.0)
    except Exception as e:  # noqa: BLE001
        log(f"SEND FAILED tf={tf}: {e!r}")
        print("send failed:", e); return 1

    log(f"OK tf={tf} pairs={len(rows)} hits={n} msgs={len(msgs)} took={time.time()-t0:.1f}s")
    print(f"OK tf={tf} pairs={len(rows)} hits={n} msgs={len(msgs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
