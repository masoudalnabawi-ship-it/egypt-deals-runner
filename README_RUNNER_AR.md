# Egypt Deals — GitHub Runner V2 (Amazon First)

نسخة تشغيل عامة منزوعة الأسرار، مصممة للعمل مع Cloudflare Worker/D1 الحاليين.

## السياسة المؤقتة الحالية
- Amazon: الأولوية الأولى في دورة التشغيل والمراجعة.
- Noon: بعد Amazon.
- B.TECH: بعد Noon.
- جميع المتاجر الأخرى معطلة مؤقتًا ولا يتم فحصها.
- الحد الأدنى للعروض العامة الحقيقية: 5%.

## صور المراجعة
قبل إرسال العرض إلى Cloudflare، يحاول الـRunner إنشاء لقطة حقيقية من صفحة المنتج.
تُرفع اللقطة لحظيًا إلى Telegram للحصول على `file_id` ثم تُحذف رسالة التخزين فورًا، وبعدها يمرر الـRunner نفس `file_id` إلى Cloudflare حتى يستطيع إرسال الصورة مع بطاقة المراجعة، من غير استضافة عامة للصورة.

## Secrets المطلوبة
- `CLOUD_API_URL`
- `CLOUD_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_MEDIA_STAGE_CHAT_ID`

لا توجد أي Token أو API Key داخل ملفات المستودع.

## الجدولة
كل 10 دقائق، ويمكن تشغيل Workflow يدويًا من Actions.
