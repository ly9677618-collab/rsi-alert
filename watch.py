#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Continuous watcher:
  - polls USD high-impact news every 12s  (TradingView)
  - runs the RSI scan at every hour boundary (1h) and at 4h boundaries
  - at the end of its life it dispatches the next run of this same workflow
    (GitHub Actions cron is unreliable, so the job re-arms itself)

Env: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, GH_TOKEN (github.token), GITHUB_REPOSITORY
"""

import json
import os
import sys
import time
import datetime as dt
import threading
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import news_alert as N  # noqa: E402
import rsi_alert as R   # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=3))
UTC = dt.timezone.utc


def env_cfg():
    return {
        "token": os.environ.get("TELEGRAM_TOKEN"),
        "chat_id": os.environ.get("TELEGRAM_CHAT_ID"),
        "rsi_period": 14,
        "history_1h": 200,
        "history_4h": 300,
        "workers": 8,
        "send_when_empty": True,
    }


def run_rsi(cfg, tf):
    label = "1 ساعة" if tf == "1h" else "4 ساعات"
    hist = 200 if tf == "1h" else 300
    rows, server_ms = R.scan(cfg, tf, hist, int(cfg["rsi_period"]), int(cfg["workers"]))
    if not rows:
        return
    if tf == "4h" and server_ms - rows[0]["close_ms"] > 25 * 60 * 1000:
        print("4h: no fresh close - skipped", flush=True)
        return
    msgs = R.build_messages(cfg, label, rows, server_ms, [30.0, 25.0], False)
    for m in msgs:
        R.send(cfg, m)
        time.sleep(1)
    hits = sum(1 for r in rows if r["rsi"] <= 30)
    print(f"RSI {tf}: pairs={len(rows)} hits={hits} msgs={len(msgs)}", flush=True)


def rsi_thread(cfg, stop_at):
    """Wait for each hour boundary (:00:30) then scan."""
    time.sleep(20)  # let the news thread settle
    while time.time() < stop_at:
        now = dt.datetime.now(UTC)
        nxt = (now.replace(minute=0, second=0, microsecond=0)
               + dt.timedelta(hours=1, seconds=30))
        while time.time() < nxt.timestamp() and time.time() < stop_at:
            time.sleep(5)
        if time.time() >= stop_at:
            break
        try:
            run_rsi(cfg, "1h")
            if dt.datetime.now(UTC).hour % 4 == 0:
                run_rsi(cfg, "4h")
        except Exception as e:  # noqa: BLE001
            print("rsi error:", repr(e), flush=True)
            time.sleep(30)


def dispatch_next(reason):
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    wf = os.environ.get("WORKFLOW_FILE", "watch.yml")
    ref = os.environ.get("GITHUB_REF_NAME", "main")
    if not token or not repo:
        print("dispatch skipped (no token/repo)", flush=True)
        return False
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/dispatches"
    body = json.dumps({"ref": ref}).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "watch-bot",
        })
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            print(f"dispatch next: {r.status} ({reason})", flush=True)
            return True
    except Exception as e:  # noqa: BLE001
        print("dispatch failed:", repr(e), flush=True)
        return False


def main():
    duration = 0
    for i, a in enumerate(sys.argv):
        if a == "--duration" and i + 1 < len(sys.argv):
            duration = int(sys.argv[i + 1])
    if duration <= 0:
        duration = 20400  # 5h40m

    cfg = env_cfg()
    started = time.time()
    stop_at = started + duration
    print(f"watch start duration={duration}s", flush=True)

    seen = N.load_seen()
    t = threading.Thread(target=rsi_thread, args=(cfg, stop_at), daemon=True)
    t.start()

    # dispatch the successor a bit before we die, so there is no gap
    handoff_at = stop_at - 90
    handed = False

    while time.time() < stop_at:
        try:
            N.poll_once(cfg, seen)
            N.save_seen(seen)
        except Exception as e:  # noqa: BLE001
            print("news poll error:", repr(e), flush=True)
        if not handed and time.time() >= handoff_at:
            handed = dispatch_next("handoff")
        time.sleep(12)

    if not handed:
        dispatch_next("end")
    print("watch end", flush=True)


if __name__ == "__main__":
    main()
