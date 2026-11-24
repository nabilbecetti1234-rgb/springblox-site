# أدوات سبرينغ بلوكس: دليل النشر الكامل (ببلاش 100%)

## الخطة باختصار
| الجزء | فين | التكلفة |
|---|---|---|
| الكود والتحديث التلقائي للقيم كل 3 ساعات | **GitHub** (Actions) | ببلاش |
| استضافة الموقع | **Cloudflare Pages** (مسموح فيه إعلانات، وسريع) | ببلاش |
| التبرعات | **Gamepass روبلوكس** (زر "❤️ ادعمني" بالموقع) | ببلاش، وروبلوكس بياخد 30% من كل تبرع |
| الإعلانات (لاحقًا) | AdSense، بعد ما يصير عندك دومين وزيارات | الدومين حوالي 10 دولار بالسنة، أو مجاني إذا إنت طالب |

كل 3 ساعات، GitHub بيسحب القيم الجديدة وبيفحصها:
- **إذا سليمة**، بيحفظها، وCloudflare بينشر الموقع الجديد لحاله.
- **إذا خربانة** (المصدر واقف، أو نص الأغراض ناقصة، أو القيم صفر)، بيرفضها وبيخلي القيم القديمة السليمة، وبيبعتلك إيميل.

---

## الخطوة 1: ارفع المشروع على GitHub (حوالي 5 دقايق)
1. اعمل حساب على https://github.com.
2. نزّل **GitHub Desktop** من https://desktop.github.com وسجّل دخول فيه.
3. فك ضغط `springblox-site.zip`. بعدين من GitHub Desktop اختار **File ← Add local repository**، وحدد مجلد `springblox-site`. إذا قلك "not a git repository"، اكبس **create a repository**.
4. اكبس **Publish repository**، **وشيل الصح عن "Keep this code private"**، وبعدين Publish.
5. بموقع GitHub روح على الـ repository، وبعدين **Settings ← Actions ← General ← Workflow permissions**. اختار **Read and write permissions** واكبس Save.

## الخطوة 2: انشر على Cloudflare Pages (حوالي 5 دقايق)
1. اعمل حساب مجاني على https://dash.cloudflare.com.
2. من القائمة روح على **Workers & Pages ← Create ← Pages ← Connect to Git**، واربط حساب GitHub واختار الـ repository.
3. الإعدادات:
   - **Framework preset:** `None`
   - **Build command:** خليه فاضي
   - **Build output directory:** `site`
4. اكبس **Save and Deploy**. بعد دقيقة بيصير موقعك على **`https://اسم-المشروع.pages.dev`** 🎉

## الخطوة 3: شغّل التحديث التلقائي
بالـ repository روح على تبويب **Actions**، اختار **Update values**، واكبس **Run workflow**.
من هون ورايح كل شي بيشتغل لحاله كل 3 ساعات.

---

## ❤️ التبرعات بالروبوكس
### أ) اعمل Gamepasses (ببلاش)
1. روح على https://create.roblox.com، وبعدين **Create ← Experience**. اعمل لعبة فاضية وانشرها (Publish).
2. من صفحة اللعبة روح على **Monetization ← Passes ← Create a Pass**. حط صورة واسم متل "دعم 25"، وبعدين **Sale ← حط السعر** واحفظ.
3. اعمل 3 أو 4 Passes بأسعار مختلفة، مثلًا 25 و100 و500 و1000.
4. انسخ **رقم كل Pass**: هو الرقم اللي بالرابط `https://www.roblox.com/game-pass/`**`123456789`**`/...`

### ب) حط الأرقام بالموقع
بموقع GitHub افتح الملف `pipeline/data/support.json`، واكبس ✏️، وحط الأرقام هيك:
```json
{
  "gamepasses": [
    { "id": "123456789", "robux": 25 },
    { "id": "234567890", "robux": 100 },
    { "id": "345678901", "robux": 500 }
  ]
}
```
اكبس **Commit changes**. خلال دقيقتين بيطلع زر **"❤️ ادعمني"** فوق بالموقع وتحت بآخر الصفحة. وطول ما القائمة فاضية، الزر مخفي.

> **💡 الروبوكس اللي بيوصلك:** بتقدر تصرفهم على طول بروبلوكس. وإذا بدك تحولهم لمصاري حقيقية عن طريق DevEx، بيلزمك 30,000 روبوكس مكسوبة (حوالي 114 دولار)، وعمرك 13 أو أكتر، وإيميل مؤكد.

---

## إذا صار شي
- **إذا مصدر وقف أو غيّر تصميمه:** الموقع بيضل شغّال بآخر قيم سليمة، وبيوصلك إيميل من GitHub، وبتطلع ❌ حمرا بتبويب Actions. ابعتلي السجل.
- **تحديث فوري:** من **Actions ← Run workflow** حط صح على **force**.
- **إذا ما صار أي تعديل بالـ repository لمدة 60 يوم**، GitHub بيوقف المهام المجدولة. بس البوت بيعمل commit مع كل تغيير بالقيم، فبالعادة ما بيصير هالشي. وإذا صار، اكبس **Enable** بتبويب Actions.
- **دومين خاص لاحقًا:** من Cloudflare Pages روح على **Custom domains** وضيف الدومين تبعك.

## محتويات المجلد
| المسار | شو هو |
|---|---|
| `site/` | الموقع المنشور |
| `pipeline/update.py` | بيسحب القيم ويفحصها ويبني الموقع |
| `pipeline/scrape.py` | بيسحب القيم والصور من المصادر |
| `pipeline/build_site_v2.py` + `template_v3.html` | بيبني `index.html` |
| `pipeline/data/support.json` | أرقام الـ Gamepasses للتبرعات |
| `pipeline/data/` | سجل القيم (للأسهم ⬆⬇) وإصلاحات الصور |
| `.github/workflows/update-values.yml` | الجدول اللي بيشتغل كل 3 ساعات |
