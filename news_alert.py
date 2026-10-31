#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USD high-impact news alert  (TradingView economic calendar -> Telegram)

Polls the TradingView economic-calendar API and fires the moment a US
high-impact event gets an `actual` value.

Usage:
    python news_alert.py --test              # send a sample message, exit
    python news_alert.py --once              # one poll, exit
    python news_alert.py --duration 21000    # continuous loop for N seconds
    python news_alert.py --dry               # one poll, print instead of send
"""

import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "config.json")
STATE_PATH = os.path.join(HERE, "seen.json")
LOG_PATH = os.path.join(HERE, "news.log")

API = "https://economic-calendar.tradingview.com/events"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
    "Accept": "application/json, text/plain, */*",
}
TZ = dt.timezone(dt.timedelta(hours=3))  # Baghdad

# indicators where a HIGHER number is USD-negative
INVERTED = ("unemployment", "jobless", "claims", "continuing", "dole")


def log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{dt.datetime.now(TZ):%Y-%m-%d %H:%M:%S}] {msg}\n")
    except OSError:
        pass


def get_json(url, tries=3):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2)
    raise last


def fetch_events(now_utc):
    # window: a bit in the past (catch delayed releases) .. tomorrow
    frm = (now_utc - dt.timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    to = (now_utc + dt.timedelta(hours=18)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    url = f"{API}?from={frm}&to={to}&countries=US"
    data = get_json(url)
    return data.get("result", [])


def num(x):
    if x is None or x == "":
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace("%", "").replace(",", "").strip()
    m = re.match(r"^-?\d+(\.\d+)?$", s)
    return float(m.group(0)) if m else None


def fmt_val(x, unit):
    if x is None or x == "":
        return "—"
    try:
        f = float(x)
        txt = f"{f:g}"
    except (TypeError, ValueError):
        txt = str(x)
    return txt + (unit or "")


def direction(title, actual, forecast):
    """Return ('up'|'down'|None, surprise_pct) for USD strength."""
    a, f = num(actual), num(forecast)
    if a is None or f is None:
        return None, None
    diff = a - f
    if abs(diff) < 1e-12:
        return "inline", 0.0
    positive = diff > 0
    if any(k in title.lower() for k in INVERTED):
        positive = not positive
    return ("up" if positive else "down"), diff


def build_message(ev, now_utc):
    title = ev.get("title", "")
    unit = ev.get("unit") or ""
    actual, forecast, previous = ev.get("actual"), ev.get("forecast"), ev.get("previous")
    date = dt.datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(TZ)

    d, diff = direction(title, actual, forecast)

    lines = [
        "🚨 <b>خبر أحمر — USD</b>",
        f"🕐 <b>{date:%H:%M}</b> بغداد · <i>{html.escape(title)}</i>",
        "",
        f"🔴 <b>Actual:</b> <code>{html.escape(fmt_val(actual, unit))}</code>",
        f"⚪ Forecast: <code>{html.escape(fmt_val(forecast, unit))}</code>",
        f"⚫ Previous: <code>{html.escape(fmt_val(previous, unit))}</code>",
    ]

    if d == "up":
        lines += ["", "📈 الدولار <b>أقوى</b> من المتوقع → الذهب <b>غالباً يهبط</b>"]
    elif d == "down":
        lines += ["", "📉 الدولار <b>أضعف</b> من المتوقع → الذهب <b>غالباً يصعد</b>"]
    elif d == "inline":
        lines += ["", "➖ مطابق للمتوقع — الحركة غالباً محدودة/متذبذبة"]

    return "\n".join(lines)


def send(cfg, text):
    url = f"https://api.telegram.org/bot{cfg['token']}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": cfg["chat_id"],
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def load_seen():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:  # noqa: BLE001
        return set()


def save_seen(seen):
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(sorted(seen)[-500:], f)
    except OSError:
        pass


def should_alert(ev, now_utc, window_s=900):
    """Event already released (has actual) and recent enough to be news."""
    if not ev.get("actual"):
        return False
    try:
        when = dt.datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return False
    age = (now_utc - when).total_seconds()
    return -60 <= age <= window_s


def poll_once(cfg, seen, dry=False):
    now = dt.datetime.now(dt.timezone.utc)
    events = fetch_events(now)
    fired = []
    for ev in events:
        if ev.get("importance") != 1 or ev.get("currency") != "USD":
            continue
        eid = str(ev.get("id") or f"{ev.get('title')}|{ev.get('date')}")
        if eid in seen:
            continue
        if not should_alert(ev, now):
            continue
        msg = build_message(ev, now)
        if dry:
            print(msg, "\n" + "-" * 50)
        else:
            send(cfg, msg)
            time.sleep(0.7)
        seen.add(eid)
        fired.append(ev.get("title"))
        log(f"ALERT {eid} {ev.get('title')} A={ev.get('actual')} F={ev.get('forecast')}")
    return fired


def main():
    cfg = json.load(open(CFG_PATH, encoding="utf-8-sig")) if os.path.exists(CFG_PATH) else {}
    cfg["token"] = os.environ.get("TELEGRAM_TOKEN") or cfg.get("token")
    cfg["chat_id"] = os.environ.get("TELEGRAM_CHAT_ID") or cfg.get("chat_id")

    if "--test" in sys.argv:
        sample = {
            "title": "Core CPI m/m",
            "date": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
            "actual": 0.4, "forecast": 0.3, "previous": 0.2, "unit": "%",
            "importance": 1, "currency": "USD",
        }
        msg = "🧪 <b>رسالة تجريبية</b>\n\n" + build_message(sample, dt.datetime.now(dt.timezone.utc))
        if "--dry" in sys.argv:
            print(msg)
        else:
            send(cfg, msg)
            print("sent")
        return 0

    seen = load_seen()
    interval = 12
    duration = int(next((sys.argv[i + 1] for i, a in enumerate(sys.argv)
                         if a == "--duration"), 0))

    if "--once" in sys.argv or "--dry" in sys.argv or duration == 0:
        fired = poll_once(cfg, seen, dry="--dry" in sys.argv)
        save_seen(seen)
        print("fired:", fired)
        return 0

    t_end = time.time() + duration
    log(f"loop start duration={duration}s interval={interval}s")
    while time.time() < t_end:
        try:
            poll_once(cfg, seen)
            save_seen(seen)
        except Exception as e:  # noqa: BLE001
            log(f"poll error: {e!r}")
        time.sleep(interval)
    log("loop end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
