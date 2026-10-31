# Trading Alerts — Binance + USD News

بوتين يشتغلون على GitHub Actions ويرسلون تنبيهات على تيليكرام.

## 1) RSI Alert — `rsi_alert.py`
كل ساعة (فريم 1h) وكل 4 ساعات (فريم 4h): يفحص أزواج USDT السبوت في Binance
ويرسل كل عملة كريبتو RSI-14 ≤ 30 (و `*` للي تحت 25).

- الجدولة: `.github/workflows/rsi.yml` — كل ساعة عند :30 UTC
- مستثنى: الأسهم الموثقة، الذهب، الستيبل كوينز

## 2) USD News Alert — `news_alert.py`
يراقب تقويم TradingView الاقتصادي ويرسل لحظة نزول **Actual** لأي خبر أمريكي
**عالي التأثير (أحمر)** مع Actual / Forecast / Previous واتجاه الدولار المتوقع وأثره على الذهب.

- الجدولة: `.github/workflows/news.yml` — تشغيل كل 6 ساعات، كل تشغيل يستمر ~5:40
- الاستطلاع: كل 12 ثانية
- التصفية: `countries=US` + `importance=high`

## الأسرار
`TELEGRAM_TOKEN` و `TELEGRAM_CHAT_ID`

## تشغيل محلي (بدون فجوات)
```
python news_alert.py --duration 43200
```
أو من ملف `run_news.bat` على ويندوز.

## ملاحظات
- GitHub قد يتأخر 5–15 دقيقة عن وقت الجدولة، وفيه فجوة ~10 دقائق بين كل تشغيلين للنيوز.
- بعد ~60 يوم خمول توقف GitHub الجدولة: Actions → Run workflow.
- كل الأرقام محسوبة على شموع مقفلة (Wildin RSI-14) وبيانات TradingView لحظية.
<!-- keep-alive: 2026-10-31 20:07 -->
