# RSI Alert — Binance Spot (USDT)

بوت يفحص **كل أزواج USDT في السبوت** على Binance ويُرسل تنبيه تيليكرام بكل عملة كريبتو وصلت
**RSI-14 ≤ 30**، مع تمييز اللي تحت **25**.

- **فريم 1h:** كل ساعة عند الدقيقة 30 (UTC)
- **فريم 4h:** عند إغلاق شمعة الأربع ساعات فقط
- **مستثنى:** الأسهم الموثقة (tokenized stocks)، الذهب (XAUT/PAXG)، الستيبل كوينز، التوكنات المضاعفة

## الملفات
- `rsi_alert.py` — السكربت (بايثون، مكتبات قياسية فقط)
- `.github/workflows/rsi.yml` — الجدولة

## الأسرار المطلوبة
`TELEGRAM_TOKEN` و `TELEGRAM_CHAT_ID` (Settings → Secrets and variables → Actions)

## إيقاف مؤقت
Actions → RSI Alert → Disable workflow

## ملاحظات
- GitHub قد يتأخر 5–15 دقيقة عن الوقت المحدد.
- إذا توقف الجدولة تلقائياً بعد ~60 يوم خمول: Actions → Run workflow مرة واحدة.
- كل الأرقام محسوبة على **شمعة مقفلة** (Wilder RSI-14).