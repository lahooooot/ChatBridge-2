# پرامپت دقیق طراحی و ساخت ChatBridge — نسخهٔ 2.60.0

## ۰) نقش، مأموریت، و حقِ خلاقیت تو

تو یک تیم توسعهٔ کامل هستی در یک نفر: مهندس دسکتاپ ویندوز (Python + pywebview + WebView2 + Win32)، توسعه‌دهندهٔ فرانت‌اند (HTML/CSS/JS خالص، RTL)، و مهندس ساخت/نصب.

مأموریت: طراحی و ساخت **ChatBridge نسخهٔ 2.60.0** دقیقاً طبق این مشخصات.

 «این متن، پیشنهادِ من است — اگر فکر می‌کنی بهتر از این هم می‌شود پیاده‌سازی کرد، انجامش بده. در همهٔ بخش‌ها می‌توانی نظر بدهی، خلاقیت به خرج بدهی و بهترش کنی.» یعنی:
- هر جزء این سند **پیشنهاد** است، نه زنجیر؛ جزئیات پیاده‌سازی آزاد است و راهِ هوشمندانه‌تر را انتخاب کن.
- فقط دو چیز مقدس است: **چک‌لیست پذیرش نهایی (بخش ۱۶)** و **بندهای «ممنوع»** که هر کدام تاریخِ یک باگ واقعی‌اند.
- اگر طراحیِ بهتری پیدا کردی: پیاده‌اش کن، در `worklog.md` بنویس «چه گفتی، چه ساختی، چرا بهتر است».

این مشخصات حاصل حدود ۲۶ دور تست واقعی کاربر است. هر بندِ «ممنوع»، باگِ دیده‌شده توسط کاربر است؛ نقضش یعنی شکست پروژه.

- زبان رابط کاربری: زبان انگلیسی
- زبان کد، کامنت‌ها و لاگ‌ها: انگلیسیِ ساده و قابل‌جست‌وجو.
- از روز اول یک `worklog.md` نگه دار: برای هر نسخه، فهرست باگ‌ها، علت ریشه‌ای، تغییرات و تصمیم‌های خلاقانه.

---

## ۱) تعریف محصول

**ChatBridge یک پنجرهٔ دسکتاپ ویندوزی با ظاهر یک IDE مدرن و زیبا و شیک  است** که کاربر بدون کپی-پیست بین پنجره‌ها با چت‌های تحت وب گفتگو می‌کند:

- پلتفرم‌های ساختی: **ChatGPT** (`chatgpt.com`)، **Claude** (`claude.ai`)، **z.ai** (`chat.z.ai`)، **DeepSeek** (`chat.deepseek.com`)، **Gemini** (`gemini.google.com/app`) + هر سایت چت دیگری که کاربر اضافه می‌کند.
- پیام کاربر از اپ به صفحهٔ چتِ وب تزریق می‌شود (اتوماسیون DOM)، پاسخِ زنده (استریم) خوانده می‌شود و در چتِ اپ نمایش می‌یابد.
- مدلِ وب می‌تواند **ابزارهای محلی** اجرا کند: `read_file` ، `write_file` ، `list_dir` ، `search_files` ، `run_command` — نتیجه به همان چتِ وب برمی‌گردد تا کار تا پاسخ نهایی ادامه یابد.
- فایل دوطرفه جابه‌جا می‌شود؛ پاسخ مدل می‌تواند فایل/تصویر برای دانلود داشته باشد.
- پنل‌های جانبی: **مرورگر داخلی (تنها روش اتصال)**، **درخت فایل‌های پروژه + ویرایشگر**، **ترمینال زنده**، **میزکار Git**، **مدیریت پروژه/چت‌ها**، **تنظیمات کامل**، و یک **سرور Provider سازگار با OpenAI**.

### 🔴 تصمیم معماری این نسخه: فقط مرورگر داخلی — بدون اکستنشن

- **اکستنشن کروم به‌کلی از معماری حذف شده است.** پوشهٔ `extension/`، manifest، service worker، content script، نصب اکستنشن، راهنمای اکستنشن — هیچ‌کدام وجود ندارند.
- **«روش مرورگر» و انتخاب بین دو روش هم حذف شده است** — `browser_mode` در config نیست؛ چیپ وضعیت در هدر حالتِ روش را عوض نمی‌کند؛ تنظیمات بخشِ انتخابِ روش ندارد.
- تنها راه اتصال به چت‌های تحت وب: **مرورگر داخلیِ سوارشده در پنل سمت راست** (بخش ۹) + عامل صفحه (بخش ۶) + درایور پایتونی (بخش ۴).
- پیامدِ حذف: سرور WS داخلی (8787) دیگر «دو کلاینتِ رقیب» ندارد — **تنها کلاینتِ آن، درایورِ مرورگر داخلی است**؛ کل منطقِ طبقه‌بندی/رقابتِ کلاینت‌ها ساده می‌شود (بخش ۴).

---

## ۲) استک و محیط

| لایه | انتخاب پیشنهادی |
|---|---|
| دسکتاپ | Python 3.10+ ، **pywebview 5/6** (بک‌اند EdgeChromium/WebView2)، `websockets`، pythonnet فقط برای Win32 (`SetParent`, `MoveWindow`, `SetWindowPos`, `GetClientRect`) |
| UI | HTML/CSS/JS **خالص** — بدون فریم‌ورک، بدون build step. یک فونت فارسی استاندارد + فونت مونو برای کد/ترمینال |
| پروتکل داخلی | سرور WS روی `ws://127.0.0.1:8787` (پورت قابل تغییر) + پاکت JSON `{"type": "...", ...}`. مرجع: `shared/protocol.json` |
| Provider | سرور HTTP سازگار با OpenAI روی `127.0.0.1:8788` |
| داده | `~/.chatbridge/config.json` ، `~/.chatbridge/ui_state.json` ، `~/.chatbridge/audit.db` ، `~/.chatbridge/logs/`؛ پروفایل WebView2: `%LOCALAPPDATA%\ChatBridge\WebView2` |
| ساخت | PyInstaller (onedir) + Inno Setup 6 |
| هدف | ویندوز ۱۰/۱۱ x64 (غیرویندوز نباید کرش کند؛ اسکریپت‌های ساخت ویندوزی‌اند) |
| تست | pytest + `ui_dom_check` (پین‌های DOM) + Playwright |

تنظیمات پیش‌فرض `config.json`: `ws_port: 8787` ، `full_access: true` ، `approval_timeout: 120` ، `provider_enabled: false` ، `provider_port: 8788` ، `provider_timeout: 600` ، `updates_seen: false` ، `custom_models: []` ، `agent_rules_on: true` ، `agent_rules: [پیش‌فرض‌های ساختی — بند ۷-۱]`.

---

## ۳) ساختار پروژه (درختِ کامل)

```
chatbridge/
├─ desktop/
│  ├─ app.py               # نقطهٔ ورود؛ کلاس Api (همهٔ JS-APIها)؛ webview.start(private_mode=False)
│  ├─ bridge.py            # سرور WS 8787 (تک‌کلاینت: درایور داخلی) + مسیر رخدادها به UI
│  ├─ internal_browser.py  # مرورگر داخلی: پنجرهٔ همراه + سوارسازی Win32 + درایور WS
│  ├─ agent_cb.js          # عامل صفحه — ۱۰۰٪ خوداتکا، بدون هیچ API اکستنشن، تزریق با evaluate_js
│  ├─ toolparse.py         # پارسرِ متعارف قرارداد ابزار: فنس/DSML/نجات/__parse_error__ (بخش ۵)
│  ├─ provider_server.py   # سرور 8788 سازگار OpenAI
│  ├─ config.py            # config.json + ارتقاهای یک‌باره + قوانین ایجنت
│  ├─ chatfolder.py        # پوشهٔ اختصاصی هر چتِ بدون پروژه در Documents\ChatBridge
│  ├─ project.py           # رجیستری پروژه‌ها + تشخیص گیت/برنچ
│  ├─ gittools.py          # عملیات گیت برای پنل GIT
│  ├─ fstree.py            # درخت فایل پروژه + خواندن/نوشتن امن (بخش ۸-ب)
│  ├─ safety.py / audit.py / logging_setup.py
│  ├─ tools/               # read_file.py ، write_file.py ، list_dir.py ، search_files.py ، run_command.py
│  ├─ translations/en.json
│  └─ ui/
│     ├─ index.html        # header / sidebar / chat / right block (مرورگر + فایل‌ها + ترمینال + گیت) / settings
│     ├─ app.js            # state + رندر + درگ مرزها + ارسال + تنظیمات + درخت فایل
│     ├─ style.css         # تم‌ها + چیدمان
│     └─ i18n.js
├─ shared/protocol.json    # قرارداد پیام‌ها — نسخه‌اش همیشه = نسخهٔ اپ
├─ tests/                  # test_bridge.py ، test_toolparse.py ، test_agent_rules.py ، test_fstree.py ،
│                          # test_provider_server.py ، test_terminal_stream.py ، test_git_panel.py
├─ scripts/                # ui_dom_check.py ، visual_check_*.py (Playwright) ، ver_*.py ، sync_installer_version.py ، package_*.sh
├─ ChatBridge.bat          # اجرا از سورس (اولین اجرا pywebview/websockets را خودش نصب می‌کند)
├─ build_exe.bat           # PyInstaller → dist\ChatBridge\ChatBridge.exe
├─ build_installer.bat     # venv → pyinstaller → ISCC → installer-output\ChatBridge-Setup-2.50.0.exe
├─ ChatBridge.spec / ChatBridge.iss / icon.ico
└─ README.md / README.html / worklog.md
```

> نکته: `agent_cb.js` یک فایل JS خوداتکاست که هم در مرورگر داخلی تزریق می‌شود؛ چون اکستنشن حذف شده، **تمامِ منطقِ DOM که قبلاً در content scriptها بود، در همین عامل صفحه + درایور پایتونی زندگی می‌کند** (بخش ۶).

---

## ۴) معماری پیام — قراردادِ کاملِ سیم (بازگوِی کامل)

سرور WS روی `127.0.0.1:8787`؛ تنها کلاینت: **درایورِ مرورگر داخلی** (درایور، `agent_cb.js` را با `evaluate_js` می‌رانَد و از توابع `window.__CB__` تغذیه می‌شود). قوانینِ اسلات:

- یک اسلاتِ فعال برای درایور؛ `hello` تازه بعد از قطع‌شدن، اسلاتِ مرده را پس می‌گیرد؛
- هیچ کلاینت دیگری به آن وصل نمی‌شود (پورت در تنظیمات قابل تغییر است)؛
- UI رخدادها را از صفِ `UISink` با `Api.drain_events()` می‌گیرد؛ هیچ Api‌ای thread اصلی UI را بلاک نمی‌کند.

### جدول کامل رخدادها (۲۶ نوع — همه باید پیاده شوند)

**d→b** = دسکتاپ→درایور، **b→d** = درایور→دسکتاپ، **p→d** = عامل صفحه→(via driver)→دسکتاپ:

| نوع پیام | جهت | فیلدها | توضیح |
|---|---|---|---|
| `hello` | b→d | `version`, `agent` | دست‌دادن اولیه؛ پل پاسخ آماده‌شدن می‌دهد |
| `cs_ready` | b→d | `platform`, `page_url` | صفحهٔ چت آماده است؛ تحویلِ پیام‌های صف‌شده |
| `user_message` | d→b | `text`, `platform`, `request_id`, `conv_url?`, `attachment?{name,mime,data_url}` | ارسال پیام کاربر به چت وب (بعد از تعیین baseline) |
| `prompt_error` | b→d | `platform`, `request_id`, `reason: no-tab\|no-input\|send-failed\|send-dropped\|attach-failed` | پیام نرسید؛ دسکتاپ خطای صادقانه نشان می‌دهد |
| `assistant_stream` | b→d | `platform`, `text`, `request_id`, `think?`, `think_active?`, `page_url` | استریم زندهٔ پاسخ (هر ~۵۰۰ms) |
| `assistant_waiting` | b→d | `platform`, `request_id`, `waited_ms`, `has_text`, `stage: loading\|thinking\|writing\|waiting` | ضربان حیات در فازهای بی‌متن (تایمرِ انتظارِ دسکتاپ را re-arm می‌کند) |
| `assistant_response` | b→d | `platform`, `text`, `request_id`, `think?`, `page_url`, `files?[{name,url,image}]` | پاسخ کامل (markdown استاندارد؛ سقف ۲۰۰هزار کاراکتر) |
| `assistant_capture_failed` | b→d | `platform`, `request_id`, `reason: empty\|stale` | هیچ پاسخی نیامد — حبابِ بازیابی به‌جای «(پاسخ خالی)» |
| `stop_generation` | d→b | `platform`, `request_id` | توقف: کپچر فوری رفع می‌شود + کنترل stop خودِ سایت کلیک می‌شود |
| `platform_busy` | b→d | `platform`, `busy: bool` | رصدِ flip خودِ سایت بین send↔stop (debounced دوخوانی)؛ دسکتاپ دکمه‌اش را آینه می‌کند + watchdog |
| `limit_reached` | b→d | `platform`, `kind: soft\|hard`, `snippet?`, `where: dialog\|assistant\|page-notice` | اطلاعِ محدودیت (هیچ handoff خودکار؛ فقط بنر + کارتِ راهنما؛ چتِ جدید فقط با کلیک کاربر) |
| `new_chat` | d→b | `platform`, `resume?`, `request_id` | چت تازه؛ `resume` به‌عنوان اولین پیام تزریق می‌شود |
| `tool_call` | p→d | `id`, `tool`, `args`, `platform`, `request_id`, `page_url` | درخواستِ ابزارِ استخراج‌شده از پاسخ (بخش ۵) |
| `tool_result` | d→b | `id`, `ok`, `result`, `error?`, `platform`, `request_id`, `attachment?` | نتیجه؛ به‌صورت دسته‌ای (debounce 700ms) به composer تزریق می‌شود |
| `tool_delivery` | b→d | `platform`, `request_id`, `count`, `tools[]`, `verdict: sent\|accepted\|stuck\|dropped`, `ok` | گواهِ تحویلِ بلاکِ نتیجه در چت وب |
| `approval_required` | d→p | `id`, `tool`, `summary`, `detail?` | کارت تأیید (مودال RTL در صفحهٔ وب + کارت در UI دسکتاپ؛ تایم‌اوت ۱۲۰s = رد) |
| `approval_response` | p→d | `id`, `approved` | تصمیم کاربر |
| `file_upload` | d→b | `id`, `name`, `mime`, `data_url` (سقف ~۱۵MB) | پیوستِ فایل به composer خودِ سایت — با تأیید چیپ (بخش ۱۰) |
| `upload_result` | b→d | `id`, `ok`, `error?`, `size?` | فقط «چیپ واقعاً ظاهر شد» = ok |
| `file_fetch` | d→b | `id`, `url`, `name?` | دانلود فایلِ ساخته‌شدهٔ سایت (همان origin + blob: با کوکی کاربر) |
| `file_data` | b→d | `id`, `ok`, `data_url?`, `error?` | بایت‌ها برای ذخیره/نمایش |
| `list_chats` | d→b | `platform`, `request_id` | لیست مکالمه‌های سایدبارِ سایت (سقف ۶۰) |
| `chat_list` | b→d | `request_id`, `ok`, `chats?[{title,url,active}]`, `reason?` | پاسخ لیست |
| `read_chat` | d→b | `platform`, `url`, `request_id`, `limit?` (پیش‌فرض ۴۰، سقف ۲۰۰) | ورود به یک مکالمهٔ سایت |
| `load_older` | d→b | `platform`, `url`, `request_id` | lazy-load با اسکرول به بالا |
| `chat_content` | b→d | `request_id`, `url`, `ok`, `messages?[{role,text,files?}]`, `can_older?`, `full?`, `reason?` | ترنسکریپت؛ `messages` به ترتیب مکالمه؛ تصاویر با `image:true` |

- `request_id` مسیرِ برگشتِ هر پاسخ به چتِ مالکِ آن است؛ چت‌های Provider با پیشوند `prov-` از حلقهٔ ابزار داخلی مستثنی‌اند (کلاینتِ خارجی خودش ابزار اجرا می‌کند).
- `conv_url`/`page_url` چتِ دسکتاپ را به مکالمهٔ وب می‌بندد — پیامِ بعدیِ همان چت در همان مکالمه ادامه می‌یابد؛ `sameConversation` = برابر بودن آخرین سگمنتِ path.

---

## ۵) قرارداد ابزار — فنس‌ها، نام‌ها، و پارسرِ متعارف (اصلاح‌شده)

### ۵-۱) نام‌های مقدس

- ابزارها **دقیقاً** این پنج‌اند: `read_file` ، `write_file` ، `list_dir` ، `search_files` ، `run_command` — هیچ نام دیگری ابزار نیست (هرچیز دیگر = خطای steering با لیستِ دقیقِ ابزارها).
- شبه‌فراخوانِ سیستمی: `__parse_error__` (فقط از پارسر، هرگز از مدل).
- نامِ ابزار باید با `^[\w.:-]{1,64}$` سالم باشد — `""` / `[object Object]` / JSON رشته‌شده = صفحه‌مُلف‌شده، drop + راهنمای ارسالِ مجدد.

### ۵-۲) فنسِ درخواست (مدل می‌نویسد)

````
```chatbridge-tool-call
{"tool": "read_file", "args": {"path": "src/app.py"}}
```
````

- برچسبِ متعارف: `chatbridge-tool-call`؛ **تحملِ لنگر:** یک خطِ بازِ ``` `chatbridge` خالی هم بازشمار می‌آید (Claude گاهی همین را می‌فرستد). خطِ ``` `chatbridge-tool-result` هرگز بازِ call نیست.
- بدنه فقط JSON است؛ `id` اختیاری است (اگر نبود، پارسر/درایور `t_<uuid>` می‌سازد).
- چند call در یک پاسخ مجاز است؛ همه dispatch می‌شوند.

### ۵-۳) شِمای args هر ابزار (متعارف و مستند)

| ابزار | args اجباری | args اختیاری | خروجیِ result |
|---|---|---|---|
| `read_file` | `path: string` | `offset: int` ، `limit: int` | `{content, lines, truncated?}` |
| `write_file` | `path: string` + `content: string` (نوشتنِ کامل) یا `search: string` + `replace: string` (وصله → در UI با فعل `edit` رندر می‌شود) | — | `{written, lines, bytes}` |
| `list_dir` | `path: string` | `depth: int` (پیش‌فرض ۱) | `{entries: [{name, type, size?}]}` |
| `search_files` | `query: string` | `path: string` ، `regex: bool` ، `max: int` (پیش‌فرض ۵۰) | `{matches: [{file, line, text}]}` |
| `run_command` | `cmd: string` | `cwd: string` ، `timeout: int` (پیش‌فرض ۳۰۰s) | `{exit, stdout, stderr, duration}` |

### ۵-۴) فنسِ نتیجه (اپ تزریق می‌کند)

بلاکِ تزریقی به composer با این قالب است — هدرِ خودکار + فنسِ نتیجه:

````
[ChatBridge · automatic tool-result · executed on the user's machine just
 now · this block PROVES the bridge is connected — never say the connection
 is cut, never ask to reconnect]

chatbridge-tool-result
{"id": "…", "ok": true, "result": {…}, "error": null}
````

- چند نتیجه با هم (debounce 700ms) در **یک** پیام تزریق می‌شود؛ ارسالِ دسته باید **گواهِ تحویل** بگیرد (`tool_delivery`) و شکستش توسط re-send کپچر جبران شود.
- **سیاستِ حجم:** خروجیِ بزرگ → پیش‌نمایشِ کوتاه در composer + فایلِ کامل به‌عنوان پیوستِ واقعی (بخش ۱۰) + ذخیره در `<workspace>/.chatbridge/results/<id>.txt` تا مدل بتواند `read_file`ش کند.

### ۵-۵) پارسرِ متعارف — `desktop/toolparse.py` (یک حقیقت، دو مصرف‌کننده)

پارسر **در پایتون** زندگی می‌کند (درایورِ مرورگر داخلی + سرور Provider هر دو از همان استفاده می‌کنند) و دقیقاً این نردبانِ مقاوم‌سازی را پیاده می‌کند:

1. **استخراج فنس فقط با خط‌ها:** خطِ باز = `^\s*```+\s*chatbridge(?:-tool-call)?\s*$`؛ بدنه تا اولین خطِ ``` دیگر؛ فنسِ بسته‌نشده در حال استریم = «هنوز تمام نشده».
2. **JSON فقط با brace-matcher** (شمارندهٔ عمق + وضعیتِ رشته) — **هرگز regex با lookahead** (regex با `$`/lookahead جلوی متنِ بعد از JSON بی‌صدا می‌مرد — باگِ تاریخیِ پرامپت ۸).
3. **نردبانِ ترمیم:** `raw` → ترمیمِ رشته‌ها (کنترل‌کاراکترِ خام داخل رشته: `\n\r\t` واقعی → escape؛ نتیجهٔ شکستنِ بلاک بین پیام‌های z.ai) → حذفِ ویرگولِ انتهاییِ مزاحم → parse. علامت‌های bidi نامرئی (`U+200B/E/F, U+202A-E, U+2066-9, FEFF`) همه‌جا حذف **به‌جز ZWNJ (`U+200C`)** — حرفِ مجازِ فارسی در مسیرها.
4. **نجاتِ بلاکِ شکسته:** برچسب هست ولی بدنهٔ parse‌شدنی نمانده → از اولین جای برچسب تا آخر، همهٔ خط‌های فنس حذف، brace-match ریشه، ترمیم؛ فقط objectی که `tool` دارد dispatch می‌شود.
5. **قطعهٔ JSON لخت:** متنی که شکلِ taught-JSON دارد ولی فنس ندارد (`{"tool":"read_file","args":` یا drift کوتیشن دور نامِ ابزار) → `__parse_error__(tool-json-fragment)`.
6. **خانوادهٔ DSML دیپ‌سیک:** `<｜DSML｜tool_calls>` / `<｜DSML｜invoke name="…">` / `<｜DSML｜parameter name="…" string="false|true">` — همهٔ واریانت‌های بار (｜×۱/۲، `|`، `![`,`]`) روی هر دو طرف؛ `tool_calls`≡`calls`؛ alias: `terminal`/`bash`/`shell`/`execute_command`/`run_terminal_cmd` → `run_command`؛ `string="true"` = JSON داخل رشته (با نردبانِ ترمیم)؛ **نجاتِ قطع‌شدگی:** پارامترِ آویزان که JSON کامل دارد = بسته شود و اجرا؛ وگرنه حذف تا خطای بلندِ executor؛ پوستهٔ خالیِ کامل = `__parse_error__(dsml-empty)`؛ `hasUnterminatedDsml` = invoke می‌تواند در closerِ container تمام شود (DeepSeek اغلب `</invoke>` را حذف می‌کند).
7. **پادزهرِ سکوت:** برچسب هست ولی هیچ‌چیز parse نشد → `__parse_error__` با دلیل (`,`-join دلیل‌ها)؛ دسکتاپ راهنمای «یک بلاک استاندارد و فشرده را دوباره بفرست» را تزریق می‌کند — **پایانِ بی‌صدای مکالمه ممنوع**.
8. تستِ کامل در `tests/test_toolparse.py` (همهٔ مسیرهای بالا + نمونه‌های واقعیِ خراب).

---

## ۶) قوانین کامل کنترلِ DOM چت‌های تحت وب — برای همهٔ پلتفرم‌ها

> کاربر: «تمام قوانین مربوط به خواندن html چت تحت وب جهت به کنترل گرفتن آن، برای همهٔ چت‌ها — چیزی جا نیافته.» این بخش، استخراجِ کامل از موتورِ تست‌شده است.

### ۶-۱) موتور عمومی (برای هر پلتفرمی)

**کشفِ اجزا — هر لیست به‌ترتیب امتحان می‌شود، اولین عنصرِ «مرئی» برنده است:**
- مرئی = rect با عرض/ارتفاع ≥ ۶px و نه `disabled`؛ (`visibleEl` = offsetWidth/Height/ClientRects — برای fake-DOM).
- ویرایشگر: ابتدا سلکتورهای پلتفرم، سپس **همهٔ** `textarea, [contenteditable=true]`های مرئی — **پایین‌ترینِ صفحه** (کمپوزر) برنده.
- دکمهٔ ارسال: ابتدا سلکتورهای پلتفرم (آخری برنده اگر چندتا)، سپس عمومی: دکمه‌های مرئی نزدیکِ ویرایشگر (تا ۶ سطحِ پدر بالا)، مرتب بر اساس پایین‌تر بودن.
- توقف: سلکتورهای پلتفرم، سپس `STOP_SELECTORS` عمومی: `[data-testid="stop-button"]` ، `#composer-stop-button` ، `[data-testid*="stop" i]` ، `#send-message-button[class*="stop" i]` ، `form button[class*="stop" i]` ، `button[aria-label*="stop" i]` ، `button[title*="stop" i]` ، `button[class*="stop" i]`.

**تزریقِ متن — نردبانِ چهارمرحله‌ای با تأیید (هرگز «فرستادم» الکی):**
1. `execCommand("insertText")` بعد از focus + select-all (یک beforeinput/input واقعی می‌سازد)؛
2. **رویداد Paste واقعی** (`ClipboardEvent` + `DataTransfer`) — فریم‌ورک‌هایی که insertText سینتتیک را نادیده می‌گیرند paste را می‌خورند (ProseMirror/ری‌اکتِ ۲۰۲۶ ChatGPT)؛
3. textarea/input: native value setter + رویداد `input` (ری‌اکت‌سازگار)؛
4. contenteditable: `textContent` + `InputEvent(insertText)`.
- **تأییدِ فرود:** `inputCarriesText` — ۶۰ کاراکترِ اولِ متن باید واقعاً در value/textContent دیده شود؛ وگرنه مرحلهٔ بعد. فقط فرودِ تأییدشده جلو می‌رود.
- کلید Enter (fallback ارسال): `KeyboardEvent("keydown/keypress/keyup", {key:"Enter", code:"Enter", keyCode:13, which:13})` — فقط بعد از focus.
- بعد از هر drop فایل: `cbWaitComposerReady` — ۲.۲ ثانیه settle (آپلودِ چیپ async است و Enter را می‌بلعد).

**ارسالِ مطمئن — ۳ دور، هر دور با گواه:**
- ترتیب هر دور: settle پست-فایل → **focus کمپوزر** (Enter بدون focus = no-op) → کلیکِ دکمهٔ ارسالِ **فعال** (aria-disabled/disabled/class-check) → تأیید → fallback Enter → تأیید → انتظار تا ۴s برای فعال‌شدنِ دکمه و کلیک دوباره → تأیید.
- «پیام واقعاً رفت» وقتی است که: کمپوزر خالی شد **یا** شمارندهٔ پیامِ کاربر +۱ شد **یا** کنترل stop ظاهر شد. استثنای DeepSeek: «کمپوزر خالی + هیچ unit + صفحه idle» = **افتادگیِ خاموش** (PoW) → re-inject خودکار با پنجرهٔ رحمت؛ خروجی نهایی سه‌حالته: `accepted | stuck | dropped` — `dropped` = شکستِ فوریِ نوبت (`prompt_error: send-dropped`)، `stuck` = کپچر زنده می‌ماند (Enter دستی کاربر هنوز جواب می‌دهد).
- هر ارسالِ ناموفق → `prompt_error(send-failed)`؛ کپچر همچنان اجرا می‌شود تا Enter دستیِ کاربر جواب را به چتِ درست برساند.

**تشخیصِ باری (busy) — فلسفه: false-idle فقط هزینهٔ تأخیر دارد، false-bisY بی‌هزینه است** (پنجرهٔ stable جبران می‌کند):
- تعریفِ واحدِ busy برای همه‌جا (حلقهٔ ابزار، کپچر، watcher): کنترلِ stop مرئی، دات‌های loading، اسپینر/pulse، دکمهٔ فعال+کمپوزرِ خالی.
- `watchComposerBusy`: هر ~۱.۵s؛ **debounce دوخوانی** (یک reading باید دو بار پشت‌سرهم تکرار شود)؛ هر flip → `platform_busy`.
- **پاک‌سازیِ placeholder:** خط‌های خالصِ «Thinking… / Thought for 5 seconds / Searching… / Generating… / در حال فکر… / 思考中» از هر استخراجی حذف می‌شوند — state تا وقتی متنِ واقعی نیامده **خالی** می‌ماند؛ waiter هرگز روی متنِ خالی resolve نمی‌شود.

**ماشینِ کپچر (قلبِ کنترل):**
- state = `{count, text}` — count = تعداد unitها، text = markdownِ نوبتِ جاری (بخش ۶-۱-مارک‌داون).
- baseline قبل از ارسال؛ **حرکت** = رشدِ count ∨ تغییرِ متن در همین کپچر (`sawChange`) ∭ عبور از snapshotِ پیش-تزریق (`preText/preCount` — رندرِ optimisticِ ChatGPT و جوابِ سریعِ DeepSeek را پوشش می‌دهد).
- tick هر ۲۰۰ms؛ resolve وقتی: `moved && stable && !busy && len>0` که stable = ≥۱.۱s بی‌تغییر (z.ai/DeepSeek: ۱.۵s)؛ هرگز روی متنِ نوبتِ قبل.
- **نگهبانِ فنس:** فنس/DSMLِ باز = «هنوز پایدار نیست»؛ ولی اگر صفحه idle شد و برچسب ۱۰s باز ماند (`FENCE_IDLE_MS`) → resolve با متنِ ناقص + `__parse_error__` (مدل وسطِ بلاک توقف کرده — «درخواست رو با متن قاطی میکنه»).
- **استریم:** هر ۵۰۰ms دلتا → `assistant_stream`؛ **ضربان:** هر ۵s یا هر تغییرِ stage → `assistant_waiting` (تایم‌اوتِ دسکتاپ re-arm می‌شود).
- تایم‌اوت: ۱۸۰s (chatgpt/claude) / ۳۰۰s (z.ai/deepseek — فازِ loading تا ۱۵۰s+)؛ flush نهاییِ دلتا قبلِ resolve.
- **re-send خودکار (حداکثر ۱ بار):** پاسخِ خالی یا متنِ خطای پلتفرم (`No response, Please try again later` / `Something went wrong` / `SyntaxError: Unexpected token` / «خطایی رخ داد» / «دوباره تلاش کنید») → صبرِ آزادشدنِ busy (تا ۴۵s) → بررسیِ stop → re-inject همان محتوا → کپچرِ دوم با نصفِ پنجره (۹۰s). **هرگز بعد از stop کاربر دوباره ارسال نمی‌شود** و re-send در صفحهٔ هنوز-شاغل هم صف نمی‌شود.
- **نگهبانِ stale:** خروجیِ کپچر که «عیناً متنِ پیش-تزریق» باشد و unit تازه‌ای نفرستاده باشد = خواندنِ کهنه → drop + `assistant_capture_failed(stale)` (تکرارِ حباب/اجرای دوبارهٔ ابزار ممنوع).

**DOM → Markdown (خواندنِ پاسخ — قوانین کامل):**
- پیاده‌رویِ block/inline با بازسازی استاندارد: `h1..h6`→`#`، `ul/ol/li` با تودرتویی، `blockquote`→`>`، جدول→pipe (escape `|`)، `hr`→`---`، `strong/b`→`**`، `em/i`→`*`، `del/s`→`~~`، `code`→backtick، `a`→`[txt](href)` (بدون `javascript:`)، `br`→newline، `img`→alt.
- **shadow-DOM سوراخ‌خور** (`node.shadowRoot` هم خوانده شود — رندررِ «Dil»ی ChatGPT جواب را داخل shadow host نگه می‌دارد)؛ `deepText` به‌عنوان fallback متنِ خام.
- **سربارِ صفحه هرگز نشت نمی‌کند:** skip کاملِ `script/style/button/svg/input/select/textarea`، `aria-hidden`، `[hidden]`، `sr-only` (هدرِ «ChatGPT said:»!)، پنل‌های thinking/thought (جداگانه کپچر می‌شوند).
- **بلوکِ کد داخل ظرف:** `<pre>` در ظرفی با هدرِ کوتاه (زبان/کپی/دانلود ≤۸۰ کاراکترِ سربار) → فقط فنس‌ها حفظ شوند؛ **برچسبِ بنر درو شود قبل از دور ریختن** (DeepSeek برچسب `chatbridge-tool-call` را متنِ سادهٔ بنر می‌گذارد، بدون هیچ class) — برچسبِ صریح (`language-*`/`data-language`) همیشه بر بنر بر بنر بر تشخیص از محتوا (sniff) اولویت دارد؛ sniff فقط وقتی هیچ برچسبی نیست و محافظه‌کار است (فقط اثرِ انگشتِ قوی: `<?php`، `<!DOCTYPE html`، `def `/`import`، SQL، shebang bash، …). فنس با ```های اضافه escape می‌شود تا کدِ حاوی ``` نشکند.
- **پالایشِ نهایی متن:** حذفِ `<ds_safety>…</ds_safety>` (و «Safe»ی دنبالش؛ بلاکِ بسته‌نشده = برش از opener)؛ حذفِ «ChatGPT said:» (سرِ متن و وسط)؛ فشرده‌سازی newlineهای ۳+.
- بدنه از سلکتورهای body به ترتیب اولویت خوانده می‌شود؛ هیچ‌کدام نخورد → **کلونِ عاری از سربار** (حذفِ دکمه‌ها/sr-only/…)، هرگز unit خام.

**پنلِ Thinking (z.ai GLM و DeepThink دیپ‌سیک):** اولین عنصرِ مرئیِ `class*=think|thought` (نه sr-only)؛ متنِ پنل جدا کپچر و با `think` سوار بر stream/response می‌شود (سقف ۱۲k)؛ `active` فقط وقتی labelِ placeholder است («Thought for 3s» = تمام‌شده، نه فعال)؛ stage → `thinking`. در z.ai پنلِ جمع‌شده به‌آرامی باز می‌شود (فقط `aria-expanded=false` یا body نامرئی؛ هر عنصر یک‌بار؛ سقف ۳ کلیک در هر sweep).

**محدودیت‌ها (limit) — فقط scoped و مرئی:**
- strong-patternها روی دیالوگ/الرتِ مرئی (متنِ کوتاه ≤۶۰۰ کاراکتر) یا **فقط آخرین پیامِ assistant**: `You've reached/hit our limit`، `You're out of free credits/messages`، `conversation too long…start a new chat`، `usage cap`، `reached the maximum conversation length`، ChatGPT free-plan: `You're using the free version of ChatGPT` / `Upgrade for advanced models` (+ اسکنِ عمیقِ tail مکالمه برای همین دو رشته) + فارسی: «محدودیت طول گفتگو».
- نرم: مجموعِ کاراکترهای ترنسکریپت > ۲۰۰هزار (با هیسترزیس ۹۰٪)؛ MutationObserver با throttle ۵s و dedupe ۶۰s. **هیچ handoff خودکار نیست** — فقط بنر + یک نکته + کارتِ راهنمای پایانِ کار؛ چتِ جدید فقط با کلیک کاربر.
- سقفِ پاسخ روی سیم: ۲۰۰هزار کاراکتر (برشِ ۲۰k قدیمی، DSML را نصفه می‌کرد — ممنوع).

**فایل (خواندن/نوشتن در صفحه):**
- آپلود: S1) `input[type=file]` داخل form/main → `input.files = DataTransfer.files` + change/input؛ S2) درگِ کامل روی کمپوزر (`dragenter→dragover→drop`)؛ S3) paste با فایل. بعد از **هر** استراتژی: پولِ چیپ (نامِ فایل/پایه‌اش در متنِ ناحیهٔ کمپوزر، هر ۳۰۰ms تا ۲.۶s)؛ فقط چیپِ دیده‌شده = ok؛ شکستِ همه = `attach-verify` صادقانه.
- دانلود: `fetch(credentials:include)` در بستر صفحه (blob: و same-origin با کوکی کاربر)، سقف ۱۵MB → data_url؛ منبعِ درستِ MIME از پسوند (`.text` ≠ octet-stream — بعضی composerها نوعِ ناشناس را بی‌صدا می‌اندازند).
- دارایی‌های پاسخ: لینک‌های download/پسونددار (max ۸) + تصاویرِ بزرگ (≥۲۲۰×۱۶۰ یا پسونددار) با `image:true` — سوار بر `assistant_response`.

**ترنسکریپت (لیست مکالمه‌ها + ورود + lazy):**
- لیست: همهٔ `a[href]` مرئی که href با الگوی پلتفرم بخورد، dedupe با URL مطلق، سقف ۶۰، `active` از `aria-current`/class/sameConversation.
- ورود: کلیکِ لینکِ سایدبارِ همان مکالمه (SPA زنده می‌ماند)؛ آخرین راه: `location.assign`؛ بعد از ناوبری ۱.۴s settle تا مدیا هم mount شود.
- خواندن: unitها به ترتیب سند؛ classify با فیلدهای پلتفرم؛ assistant = markdown (همان walker)، user = textContent؛ **dedupe همسایه‌های هم‌نقش/هم‌متن**؛ خواندنِ خالی بعد از SPA: ۲ بارِ دیگر با فاصلهٔ ۲.۲s (richer برنده).
- lazy: پیدا کردن scroller (scrollHeight ≫ clientHeight در ۱۴ سطحِ پدر)، `scrollTop=0` تا ۸ دور؛ `can_older` = محتوایی بالای viewport یا سرریزِ cap.
- تصاویرِ ترنسکریپت (≥۹۶px یا بدون سایزِ صریح، بدون avatar) + لینک‌های فایل (download attr/پسوند/`blob:` غیرتصویری/`/mnt/data/`، `/files/`) — سقف ۶ در unit، dedupe با URL؛ دسکتاپ خودش بایت‌ها را با `file_fetch` می‌گیرد.

### ۶-۲) جدولِ پلتفرم‌ها (سلکتورهای دقیق — از موتورِ تست‌شده)

هر پلتفرم یک **HINTS object** با همین پنج لیست دارد: `editor[]` ، `send[]` ، `stop[]` ، `unit[]` ، + `isAssistant(el)` و `busy()`. همیشه در بالای `agent_cb.js` — یک جدول واحد، قابل‌به‌روزرسانیِ ساده.

**ChatGPT (chatgpt.com):**
- editor: `div[contenteditable="true"]#prompt-textarea` → `form div[contenteditable="true"]` → `form textarea[data-id]` → `textarea[data-id="root"]` → `#prompt-textarea`
- send: `button[data-testid="send-button"]` → `button[aria-label*="send" i]` (نه stop) → `form button[type="submit"]`
- stop: `button[data-testid="stop-button"]` → `button[aria-label*="stop" i]`؛ **busy = مرئی‌بودنِ کنترل stop**
- unit: `[data-turn-key]` (turn) / `[data-content-search-unit-key$=":assistant"]` (assistant)؛ بدنه به ترتیب: `[data-markdown-text-style]` (رندرر جدید) → `.markdown` (قدیمی) → `[data-message-author-role="assistant"]` → کلونِ عاری‌ازسربار
- ترنسکریپت: unit = عناصرِ search-unit (dedupe با کلید؛ classify با پسوندِ `:user`/`:assistant`)، fallback = turnها؛ تصاویر در wrapperِ turn (بالای unit برو)؛ لینک چت: `/c/` روی chatgpt.com
- عرف‌ها: رندرِ optimistic (unitِ placeholder قبل از ارسال ساخته می‌شود → حرکت با متن هم می‌شمارد)؛ کمپوزرِ ۲۰۲۶ insertText سینتتیک را نادیده می‌گیرد → مسیر paste حیاتی است؛ هدرِ `sr-only` حذف؛ اسکنِ tail برای اعلانِ free-plan.

**Claude (claude.ai):**
- editor: `div.ProseMirror[contenteditable="true"]` → `div[contenteditable="true"].font-claude-message` → `fieldset div[contenteditable="true"]`
- send: `button[aria-label="Send Message"]` / `aria-label*="send" i` / `button[data-testid="send-button"]`؛ stop: `button[aria-label*="stop" i]` (busy = همین)
- unit: `[data-testid="assistant-message"]` → `.claude-message` / `[data-testid="conversation-turn"]` (legacy) → ردیف‌های `[data-testid="transcript-row"][data-perf-row="assistant"]` (زنجیرهٔ ۳سطحیه)
- ترنسکریپت: ردیف‌های transcript-row با `data-perf-row="human|assistant"`؛ fallback: user+assistant testidها با ترتیب سند؛ لینک چت: `claude.ai/chat/`
- عرف‌ها: **ProseMirror به paste اعتماد می‌کند** — تزریق paste-اول؛ چیپِ برچسبِ کدِ لخت («chatbridge» کنار فنس) حذف؛ خواندنِ خالی = probeِ رانشِ سلکتور (تعدادها در لاگ).

**z.ai (chat.z.ai):**
- editor: `textarea#chat-input` → `textarea[placeholder*="message" i]` → `textarea` (textarea واقعی — injectText مستقیم)
- send: `#send-message-button` → `button.sendMessageButton` → `form button[type="submit"]`؛ stop: کنترلِ send خودش swap می‌شود (class/aria) — fallbackِ توقف = کلیکِ همان کنترل
- busy (پوششِ کامل): دات‌های `.chat-assistant .dot` و `#response-content-container .dot` و `dot-flashing/dots-flashing/dot-pulse`؛ دات‌های **پیش-جواب** که بیرونِ unit اند (سطحِ لیستِ پیام)؛ اسپینر/pulse/animate-bounce؛ کنترلِ stop-swapped
- unit: `.chat-user` / `.chat-assistant`؛ بدنه: `.markdown-prose` → `.chat-assistant`؛ **نوبتِ جاری = همهٔ assistantهای بعد از آخرین user** (۳ لایه: خواهر-فرزندی → compareDocumentPosition → همه) — z.ai یک نوبت را چند unit می‌کند و وسطِ بلوکِ کد هم می‌شکند
- ترنسکریپت: `.chat-user, .chat-assistant` با classify کلاس؛ لینک چت: `z.ai/c/`؛ سقف‌ها: stableMs ۱۵۰۰، تایم‌اوت ۳۰۰s، busyClearMs ۴۵s، انتظارِ idle قبلِ تزریقِ پرامپت تا ۹۰s (فاز Thinking طولانی است)

**DeepSeek (chat.deepseek.com):**
- editor: `textarea[placeholder*="deepseek" i]` → `textarea[name="search"]` → `form textarea`
- send/stop: **یک کنترل** — `div[role="button"].ds-button--primary` (از کمپوزر ۸ سطح بالا برو، آخرین primary صفحه fallback): حالتِ ارسال = فلشِ بالا (svg با path)، حالتِ توقف = **مربع (svg با rect)**؛ `ds-button--disabled` = غیرفعال
- busy: svg-rect مرئی ∨ **فعال + کمپوزرِ خالی** (idle+خالی همیشه disabled است → این حالت فقط «در حال تولید» است)
- unit: `.ds-message`؛ assistant = آن‌که `.ds-markdown.ds-assistant-message-main-content` دارد؛ بدنه به همان ترتیب؛ نوبتِ جاری = assistantهای بعد از آخرین non-assistant (الگوی z.ai)
- عرف‌ها: ارسالِ **optimistic با PoW** — کمپوزر فوراً خالی می‌شود و حقیقی‌شدنِ ارسال به WASM/شبکه وابسته است → ارسالِ سه‌حالته‌ی verdict-based با پنجرهٔ رحمت (بخش ۶-۱)؛ placeholderهای «Thought for N seconds / Searching…» حذف؛ برچسبِ فنس در **بنر** است (بخش ۶-۱ مارک‌داون)؛ DeepThink = پنل thinking (extractThinkBlock مشترک)؛ stableMs ۱۵۰۰، تایم‌اوت ۳۰۰s؛ لینک چت: `/a/chat/s/`

**Gemini (gemini.google.com/app):**
- editor: `div.ql-editor[contenteditable="true"]` (Quill) → `rich-textarea div[contenteditable="true"]` → `div[contenteditable="true"]`
- send: `button.send-button` → `button[aria-label*="send" i]` → `button[mattooltip*="send" i]` → `div[aria-label*="send" i]`؛ stop: `button[aria-label*="stop" i]`
- unit: `model-response` / `message-content` (عناصرِ سفارشی) → `.model-response-text` → `.conversation-container`؛ isAssistant با tagName
- busy: flip کنترل ارسال/توقف + رشدِ متن (دستگاهِ عمومی) — چون نشانگرِ اختصاصیِ پایدار ندارد، حرکتِ متن + پنجرهٔ stable تصمیم می‌گیرد

**Generic (مدل‌های دلخواه کاربر — هر سایت چت):**
- هیچ سلکتور از پیش؛ کشفِ کاملاً هیوریستیک: ویرایشگر = پایین‌ترینِ مرئی؛ ارسال = دکمهٔ نزدیکِ ویرایشگر؛ کپچر = **diff-based**: بلوک‌های متنیِ leaf-ish `main` (متن ≥۴۰ کاراکتر، نه خودِ ویرایشگر، بدون فرزندی که همان متن را دارد) → هر چیزی که بعد از baseline جدید/بزرگ‌تر شد = جواب.
- سلکتورهای پلتفرمی همیشه اول امتحان می‌شوند؛ generic فقط وقتی لیست‌ها خالی‌اند یا هیچ‌چیز نیافتند.

### ۶-۳) حکمرانیِ سلکتورها (درسِ ۲۶ دور تست)

- **سلکتورها فقط در جدولِ HINTS** بالای `agent_cb.js` — نه پخش در کد؛ به‌روزرسانیِ یک سایت = یک لیست.
- **کلاس‌های build-hash (`_9a3f2c`) هرگز** به‌عنوان سلکتور — فقط stable attribute ها: `data-testid`، `aria-label`، `contenteditable`، `placeholder`، `id`های معنایی، نام‌کلاس‌های design-system (`ds-button--primary`).
- `__CB__.probe()` خودآزماییِ زنده است (editor/send که چه چیزایی خوردند) — لاگِ استاندارد بعد از هر تزریق؛ کپچرِ خالی = probeِ رانش در لاگ (نامِ سلکتورِ مرده معلوم باشد).
- عامل صفحه باید **هیچ‌وقت از entry pointهایش throw نکند** — هر تابع، JSON ساده برمی‌گرداند؛ `evaluate_js` سریالیز می‌کند.
- **قرارِ `window.__CB__`** (بین عامل و درایور): `ping()→"pong"` ، `meta()` ، `probe()` ، `send(text)→{ok,how,…}` ، `enter()` ، `stop()→{ok,how}` ، `baseline()→{count,last}` ، `snap()→{busy,stage,text,composer,ready,url,title,probe}` — `text` = جوابِ جاریِ نوبت (تجمعی نسبت به baseline که در پایتون است).
- Pill کنترلِ کوچکِ داخل صفحه (dot + ⟳ + ⌂ + ×، قابل‌درگ، ذخیرهٔ hidden در localStorage) — هرگز نباید عامل/صفحه را بشکند.

---

## ۷) حلقهٔ ابزار ایجنت

- جریان: مدل داخل پاسخِ وب فنس/DSML می‌سازد → عاملِ صفحه متن را می‌خوانَد → درایور با `toolparse.py` استخراج می‌کند → `tool_call` → دسکتاپ اجرا → `tool_result` دسته‌ای به composer همان چت وب تزریق می‌شود → کپچرِ جوابِ بعدی با همان `request_id` → تکرار تا پاسخِ بی‌call.
- **سقف امن:** `MAX_TOOL_ROUNDS = 16` به‌ازای هر پرامپت (هر پرامپتِ جدید budget را re-arm می‌کند) + **دورِ رحمت**: در سقف، نتایجِ در صف تزریق و جوابِ نهایی کپچر می‌شود، فقط callهای جدید dispatch نمی‌شوند — نتیجهٔ در صف هرگز دور ریخته نمی‌شود.
- **کارت تأیید** برای write/run (مگر Full Access — پیش‌فرض ON، سوییچ سایدبار)؛ `approval_timeout` = ۱۲۰s (مودالِ RTL داخل صفحهٔ وب با شمارش معکوس + کارت در UI دسکتاپ؛ بدون پاسخ = رد)؛ همهٔ عملیات در `audit.db`.
- توقف (stop) سراسریِ قانون‌مند: stopِ نوبتِ جاری → کپچرِ در حال اجرا فوری resolve؛ نتایجِ صف‌شدهٔ همان نوبت دور ریخته می‌شوند؛ جوابِ بعدی به چت نمی‌رود و call نمی‌سازد؛ re-send بعد از stop ممنوع؛ پرچمِ stop نوبت‌محور (`request_id`) است، ۵ دقیقه می‌میرد و نوبت‌های بعدی را مسموم نمی‌کند.
- تزریقِ نتیجه هرگز وقتی صفحه stop-mode است انجام نمی‌شود (اول صبرِ آزادشدنِ busy — z.ai: تا ۴۵s)؛ پیوستِ نتیجهٔ بزرگ اول drop می‌شود، بعد متن، بعد ارسال با گواه.

### ۷-۱) قوانینِ تزریقی — لحنِ طبیعی + قابلِ ویرایش توسط کاربر (الزامی)

وقتی پیامِ کاربر به چتِ وب می‌رود، اپ یک «قراردادِ ایجنت» (چند قانونِ کوتاه) به پیام می‌چسباند تا مدل بداند چطور ابزار بخواهد. دو قانونِ سفت‌وسخت:

**الف) لحنِ طبیعی — چتِ تحت‌وب نباید حس کند نرم‌افزار به آن دستور می‌دهد:**
- متن مثل حرفِ **اول‌شخصِ خودِ کاربر** نوشته می‌شود («من یک پل محلی دارم که…»)؛ ممنوع: ALL-CAPS، «YOU MUST»، «SYSTEM»، برندِ ChatBridge در متنِ تزریقی.
- **سینتکسِ فنس ثابت و مقدس است** — پارسر فنس را می‌سنجد نه کلمات؛ لحنِ دورِ آن آزاد است.
- کوتاه: هر قانون ۱–۳ جمله؛ تزریق فقط وقتی چت به پروژه/پوشه‌ای وصل است که ابزارهایش فعال‌اند.

**ب) قابلِ ویرایش، کم‌وزیادشدنی (تنظیمات → قوانین ایجنت):**
- لیستِ ردیفی: هر ردیف = toggle فعال/غیرفعال + متنِ قابل ویرایش + حذف؛ + «افزودن قانون» + «بازنشانی به پیش‌فرض‌ها» + **«پیش‌نمایش پیامِ تزریقی»** (همان متنی که مدل می‌بیند) + **کلیدِ master** برای خاموش‌کردنِ کلِ تزریق.
- ذخیره: `agent_rules: [{id, text, enabled, builtin}]` + `agent_rules_on`؛ ارتقاء فقط قانون‌های ساختیِ دست‌نخورده را به‌روز می‌کند — ویرایشِ کاربر هرگز بازنویسی نمی‌شود.
- Api: `agent_rules_get` / `agent_rules_set` + `tests/test_agent_rules.py`.

### ۷-۲) رندرِ عملیات — «دستورها»، نه بلوکِ خام (الزامی)

**متنِ خامِ فنس هرگز در چتِ اپ دیده نمی‌شود.** پاسخ قبل از رندر با `toolparse.py` parse می‌شود: فنس‌ها بیرون کشیده و به ساختارِ عملیات تبدیل می‌شوند؛ فقط متنِ طبیعی در حباب می‌ماند. در صفحهٔ وب هم عاملِ صفحه بلوکِ فنس را به چیپِ خنثی فشرده می‌کند (متن در DOM می‌ماند تا کپچر نشکند).

هر عملیات = یک ردیفِ دستور — آیکن + فعل + هدف + زیرمجموعهٔ «چه کاری انجام شد»:

| فعل | ابزار | مثالِ زیرمجموعه |
|---|---|---|
| `read` | `read_file` | «src/app.py ← ۱۲۰ خط خوانده شد» · کلیک = متنِ واقعی در FILE |
| `write` | `write_file` (کامل) | «ui/app.js ← ذخیره شد، ۴۲ خط» · کلیک = محتوا در FILE |
| `edit` | `write_file` وصله‌ای | «app.py: خطوط ۳۰–۴۵ جایگزین شد» + diff |
| `run` | `run_command` | «pytest ← ۶۵ passed» · کلیک = ترمینالِ زندهٔ همان اجرا |
| `grep` | `search_files` | «"ibrowser_fit" ← ۵ نتیجه در ۳ فایل» |
| `list` | `list_dir` | «desktop/ ← ۱۲ مورد» |
| `tool` | ناشناخته/سفارشی | فعلِ عمومی + نامِ ابزار |

- فقط عملیاتِ جاری باز؛ تمام‌شده‌ها به شمارنده؛ کلیک = تاریخچه؛ خطا با وضعیت قرمز و دلیل صادقانه؛ نامِ خراب هرگز ردیفِ «{}» نمی‌سازد.
- معیار پذیرش: بعد از یک دورِ ابزار، در DOM چتِ اپ هیچ رشتهٔ خامِ `chatbridge-tool-call` نیست.

---

## ۸) رابط کاربری — چیدمان

### Header
- دکمهٔ جمع/بازِ سایدبار؛ **چیپ وضعیت اتصالِ مرورگر داخلی** (وصل/در حال آماده‌سازی/قطع — کلیک = reveal داک)؛ سوییچر مدلِ چتِ جاری؛ عنوان پروژه/برنچ.
- **دکمهٔ «مرورگر داخلی» `#ibOpenBtn` (کرهٔ زمین) — همیشه مرئی** (دیگر gated به mode نیست): نقطه‌اش سبز = درایور وصل؛ بسته = باز می‌کند، باز = reveal؛ منطقِ واحد با دکمهٔ بلوک و کارتِ حالت‌خالی: `window.__cbOpenInternalBrowser`.
- «What's new» فقط یک بار برای همیشه (`updates_seen` در config.json).

### سایدبار مینیمال
- جمع‌شونده به نوارِ فقط-آیکنی (~۴۸px)؛ دکمهٔ بازگشت در حالت مینیمال هم کار کند؛ ماندگار در `ui_state.json`؛ لیست مکالمه‌های سایت (`list_chats`) با ورود به هر کدام.

### بدنهٔ چت
- حباب‌ها + استریم زنده + ردیفِ «Thinking…» تاشو (`think`)؛ خطِ عملیاتِ دستوری (۷-۲)؛ کارت تأیید در `#approvalHost`؛ بنرِ limit + کارتِ راهنمای پایانِ کار؛ hint زیر composer.
- **composer تمیز:** textarea + ارسال/توقف (آینهٔ `platform_busy`)؛ پیوست با سه راه + تأییدِ چیپ؛ متنِ خیلی بلند خودکار به txt پیوست می‌شود (کمپوزرِ سایت فقط یادداشتِ کوتاه می‌گیرد).

### بلوک سمت راست (تب‌ها + دو مرزِ draggable)
- تب‌ها: **مرورگر** (`#ibDock` + حالت‌خالی `#ibDockEmpty` + نوار `#bbLog`) ، **فایل‌ها** (بند ۸-ب) ، **ترمینال زنده** (ANSI، kill، اجرای دوباره، «ارسال نتیجه به چت») ، **GIT** (برنچ/کامیت+Push/پول/diff/دیسکارد/قالب Jira) ، **FILE** (ویرایشگرِ فایلِ باز‌شده).
- **مرزِ اول** چت↔بلوک؛ **مرزِ دوم** مرورگر↔بقیه؛ هر دو draggable + «چیدمان پیش‌فرض».
- ریاضیِ درگ — قانون قطعی (باگِ سه‌نسخه‌ایِ جهتِ معکوس): `onRight = (innerWidth - pr.right) <= pr.left` (از rectِ خودِ بلوک، نه dir سند)؛ عرض = `br.right - clientX` (راست) / `clientX - br.left` (چپ)؛ در هر دو درگ داک زنده re-fit شود (`sendIbFit`).
- هر تغییر DOM که rect داک را عوض می‌کند → rect دوباره: `ResizeObserver(#ibDock)` + `window.resize` + درگ‌ها.

### ۸-ب) تبِ «فایل‌ها» — درختِ پروژه + ویرایشگر (درخواستِ صریحِ کاربر)

وقتی چت به یک **پروژه** وصل است، تبِ «فایل‌ها» فعال و پر می‌شود:

- **درختِ پوشه‌ها/فایل‌ها** از ریشهٔ پروژه: تاشو/بازشو، آیکنِ نوع، فایل‌های مخفیِ مزاحم پیش‌فرض جمع‌اند (`node_modules`، `.git`، `__pycache__`، `dist`، …)؛ دکمهٔ **Refresh** + refresh خودکار بعد از هر عملِ write/tool؛ جست‌وجوی نام در درخت (فیلترِ زنده).
- **کلیک روی فایل** → `fs_read`: اگر متنی و زیرِ سقف (~۲MB) است → در پنلِ ویرایشگر (سمتِ پایین/کنارِ درخت) باز می‌شود؛ باینری/بزرگ → کارتِ اطلاعِ صادقانه + دکمهٔ Reveal در Explorer.
- **ویرایش توسط کاربر:** textareaی مونو با شمارهٔ خط؛ **Save** (دکمه + `Ctrl+S`) → `fs_write` با همان مدلِ امنیتِ ابزارها (کارت تأیید مگر Full Access)؛ نشانگرِ dirty؛ پس از ذخیره: پیامِ موفقیت + refresh درخت + لاگ audit. فایلِ باز از `read_file`/`write_file` مدل هم همین‌جا باز/به‌روز می‌شود.
- Api جدید: `fs_tree(path?)` ، `fs_read(path)` ، `fs_write(path, content)` (+ `reveal_path` موجود) — پیاده‌سازی در `desktop/fstree.py` + `tests/test_fstree.py` (سقف سایز، تشخیص باینری، مسیرِ خارج از پروژه = رد).
- چتِ بدون پروژه: تب خالی با دکمهٔ «اتصال پروژه / ساخت پوشهٔ چت».

### تنظیمات تمام‌صفحه (`#settingsModal`)
- دسته‌ها: **عمومی، ظاهر، مدل‌ها، مرورگر داخلی، سرور Provider، قوانین ایجنت** — کلیک = فقط همان بخش.
- **«مرورگر داخلی»** (بخشِ انتخابِ روش حذف شده — بدون segmented control، بدون ردیفِ اکستنشن): ردیف‌های سادهٔ برچسب‌دار با hairline — وضعیتِ زندهٔ درایور (+ باز/بستن مرورگر)، لاگینِ ماندگار (+ پاک‌سازی پروفایل)، رفتار داک/چیدمان، پورتِ WS. **معیار: صفر radio در کل بخش** (کاربر دو بار radio-card را رد کرده).
- «قوانین ایجنت»: بند ۷-۱. «مدل‌ها»: ساختی‌ها + `{id:"c_<slug>", name, home}` با adapter عمومی؛ هر چت فقط به مدلِ خودش گوش می‌دهد؛ سوییچ دستیار کانتکست را منتقل می‌کند.

---

## ۹) مرورگر داخلی — قلب فنی (دقیقاً همین معماری)

### ممنوعیت‌های مطلق
1. **`private_mode` هرگز به `webview.create_window`** — فقط مالِ `webview.start` است؛ پاس‌دادن = کرشِ همهٔ باز شدن‌ها روی pywebview 5/6 (دو نسخه را فلج کرد).
2. **iframe ممنوع** — X-Frame-Options/CSP → صفحهٔ سیاه.
3. **پنجرهٔ شناور به‌عنوان رفتارِ پایه ممنوع** — داخل پنل سمت راست سوار شود.
4. **هر API اکستنشن (chrome.*) در عامل صفحه ممنوع** — وجود ندارد؛ کرش فوری. `agent_cb.js` ۱۰۰٪ vanilla و خوداتکاست.

### معماری درست
- ماندگاری لاگین: `webview.start(private_mode=False)` + `WEBVIEW2_USER_DATA_FOLDER = %LOCALAPPDATA%\ChatBridge\WebView2` — هر سایت یک بار لاگین، برای همیشه.
- پنجرهٔ همراه: `webview.create_window(url=PLATFORM_HOME[platform], hidden=True, frameless=True)` فقط از تردِ daemon → Win32 `SetParent` + `WS_CHILD` = بچهٔ واقعیِ پنجرهٔ اصلی (بدون پینِ تسک‌بار).
- `PLATFORM_HOME`: chatgpt→`https://chatgpt.com/` ، claude→`https://claude.ai/` ، zai→`https://chat.z.ai/` ، deepseek→`https://chat.deepseek.com/` ، gemini→`https://gemini.google.com/app` ، مدلِ دلخواه → `home` خودش.
- هندسه — **UI مالک است:** `window.__cbIbDockRect()` (CSS px + client size) → `Api.ibrowser_fit(x,y,w,h,visible,cw,ch)` با ضریب `GetClientRect` (**DPI-safe**) → `MoveWindow` + `ShowWindow(SW_SHOWNA/HIDE)`؛ pushها throttled ~۹۰ms.
- **fallback:** شکستِ هر مرحلهٔ Win32 → پنجرهٔ شناور؛ **مرورگرِ مرده ممنوع.**
- ناوبری: نوار URL داک واقعاً navigate کند (`browser_nav("navigate", url)`)؛ `browser_reinject` (تزریق دوبارهٔ عامل بعد از ناوبری/رفرش) و `browser_reset_profile` موجودند؛ عامل روی هر ناوبری دوباره تزریق می‌شود (`events.loaded` → spawn worker → reinject).
- قوانین تردینگ (آنچه 2.43/2.44 را Not Responding کرد): `create_window` فقط از daemon؛ `evaluate_js` فقط در worker با join timeout سخت؛ `events.loaded` فقط spawn؛ هیچ Api‌ای روی thread اصلی انتظار ندارد.
- دامِ پرچمِ مخفی‌سازی: prefِ «بلاک مخفی» فقط در boot و `hideBrowserBlock` اعمال شود؛ revealِ مربوط به مرورگر همیشه **با FORCE** — وگرنه مرورگرِ باز برای همیشه نامرئی می‌ماند (باگِ واقعی).

---

## ۱۰) تبادل فایل دوطرفه

- دسکتاپ→وب: `file_upload` با نردبانِ S1/S2/S3 + **تأییدِ چیپِ پیوست اجباری** (بخش ۶-۱)؛ نرسیدن = خطای صادقانه (`attach-verify`).
- وب→دسکتاپ: دارایی‌های پاسخ و ترنسکریپت → `file_fetch` (session-دار) → نمایش inline (تصویر) / چیپِ دانلود (فایل) → دیالوگ Save یا `Documents\ChatBridge`.
- پیوستِ پیام‌های بلند دسکتاپ: متنِ > سقفِ کمپوزر → فایلِ txt واقعی + یادداشتِ کوتاه؛ پیوستِ ناموفق = `attach-failed` (هرگز «پیوست شد» الکی).

## ۱۱) پروژه‌ها، چت‌ها، مسیرها

- هر چت ↔ یک پروژهٔ لوکال (تشخیص گیت/برنچ، کانتکست پروژه)؛ چتِ بدون پروژه → پوشه در `Documents\ChatBridge\<نام>`؛ تاریخچه در `~/.chatbridge/ui_state.json` ماندگار.
- نتایجِ ابزارهای بزرگ: `<workspace>/.chatbridge/results/` (بخش ۵-۴).

## ۱۲) سرور Provider

- `desktop/provider_server.py` — HTTP سازگار OpenAI روی 8788؛ مدل‌ها: `web-chatgpt` ، `web-claude` ، `web-deepseek` ، `web-zai` (+gemini)؛ پیش‌فرض خاموش؛ کلیدِ خودزاد؛ `provider_timeout` = ۶۰۰s؛ نوبت‌های `prov-*` حلقهٔ ابزارِ داخلی را اجرا نمی‌کنند — از همان `toolparse.py` برای native tool_calls کلاینت استفاده می‌شود.

## ۱۳) چندزبانه، تم، ایمنی، لاگ

- i18n از JSON؛ فارسی RTL پیش‌فرض + English LTR؛ ۶ تم + ۴ اندازهٔ فونت + فونت کد.
- مودال تأیید write/run، سقف ذخیره‌سازی، `audit.db`، Log Viewer داخلی + دانلود zip لاگ‌ها.

## ۱۴) نسخه‌بندی و ساخت/نصب

- نسخهٔ اپ: **2.60.0** — یکسان در: `app.py` (APP_VERSION) ، `index.html` ، `shared/protocol.json` ، `agent_cb.js` (VER) ، READMEها ، `ChatBridge.iss` ، `ChatBridge.spec` ، `build_installer.bat` (sweep با `scripts/ver_*.py` + `sync_installer_version.py`).
- نسبت به 2.49/2.48: **اکستنشن و انتخابِ روش حذف**؛ پارسرِ قرارداد به پایتون (`toolparse.py`) منتقل شد؛ **تبِ فایل‌ها (درخت + ویرایشگر) اضافه**؛ قوانینِ DOMِ پنج پلتفرم به‌صورت کامل در `agent_cb.js` تمرکز یافت؛ بقیه = رفتارِ تست‌شدهٔ 2.48.
- `ChatBridge.bat` (اجرای سورس) ؛ `build_exe.bat` → `dist\ChatBridge\ChatBridge.exe` ؛ `build_installer.bat` → `installer-output\ChatBridge-Setup-2.50.0.exe` ؛ آیکن `icon.ico`.

## ۱۵) تست‌ها (شرطِ اتمام کار)

- pytest: `test_toolparse.py` (نردبانِ کاملِ بند ۵-۵) ، `test_bridge.py` (تک‌کلاینت، hello/reclaim، صف‌ها) ، `test_agent_rules.py` ، `test_fstree.py` ، `test_provider_server.py` ، `test_terminal_stream.py` ، `test_git_panel.py` — همه سبز.
- `scripts/ui_dom_check.py`: پین‌های DOM (`#ibOpenBtn` همیشه-مرئی، `#ibDock/#ibDockEmpty/#ibDockOpen/#bbLog`، مرزها، composer، `#settingsModal` بدون radio، ردیف‌های دستور، درختِ فایل‌ها، …) + پینِ «بدون فنسِ خام».
- Playwright (`scripts/visual_check_*.py`): داک سمت راست + fit زنده در درگ؛ درگِ راست = باریک‌تر شدن بلوکِ راست؛ تنظیمات بدون radio؛ ارسال/کپچر با ماکِ DOM هر پنج پلتفرم (کمپوزرِ textarea و contenteditable و ProseMirror/Quill + فنسِ بنریِ DeepSeek + optimistic render)؛ درختِ فایل: باز/ویرایش/ذخیره؛ قوانین: ویرایش → پیش‌نمایش عوض شود.
- `node --check` روی همهٔ JS و `py_compile` روی همهٔ py.

## ۱۶) چک‌لیست پذیرش نهایی (دستی، روی نسخهٔ ساخته‌شده)

1. دکمهٔ «مرورگر داخلی» در header همیشه هست؛ باز/reveal می‌کند؛ نقطهٔ اتصال دارد؛ چیپِ وضعیت، حالتِ روش را عوض نمی‌کند (چیزی برای عوض‌کردن نیست).
2. مرورگر **داخل پنلِ سمت راست** رندر می‌شود؛ با move/resize/درگ همگام می‌ماند؛ تسک‌بارِ جدا ندارد؛ لاگینِ هر سایت بعد از restart می‌ماند.
3. پیام از چت به مرورگر داخلی می‌رود؛ استریم + ضربان + stage در UI می‌آید؛ stop هر دو طرف را متوقف می‌کند.
4. **ارسال/کپچر روی هر پنج پلتفرم + مدلِ دلخواه (generic)** با قوانینِ بند ۶ تست و پاس می‌شود (کمپوزرها، ارسالِ سه‌حالتهٔ DeepSeek، paste-first Claude، multi-unit z.ai، optimistic ChatGPT، Quill Gemini).
5. حلقهٔ ابزار با نام‌های مقدسِ `read_file/write_file/list_dir/search_files/run_command` کار می‌کند؛ پارسر هر نمونهٔ خرابِ بند ۵-۵ را زنده نگه می‌دارد (`__parse_error__` → re-send، پایانِ بی‌صدا ممنوع).
6. **تبِ «فایل‌ها»:** درختِ پروژه، کلیک = باز شدن فایلِ متنی، ویرایش + Save با امنیتِ Full Access/تأیید؛ باینری/بزرگ = اطلاع صادقانه.
7. هیچ بلوکِ خامِ فنس در چتِ اپ نیست؛ عملیات‌ها به شکل `read/write/edit/run/grep/list` با زیرمجموعهٔ «چه کاری انجام شد» رندر می‌شوند.
8. فایل دوطرفه با تأییدِ چیپِ پیوست؛ دانلودِ فایل/تصویرِ پاسخ کار می‌کند.
9. درگِ هر دو مرز در هر دو جهت درست + «چیدمان پیش‌فرض»؛ سایدبار مینیمال + بازگشت؛ composer تمیز؛ بلاک‌ها جمع.
10. تنظیمات: دسته‌بندیِ کامل؛ «مرورگر داخلی» = ردیف‌های ساده با صفر radio؛ «قوانین ایجنت» = ویرایش/افزودن/حذف/toggle/پیش‌نمایش/master + ماندگاریِ ویرایش.
11. قوانینِ تزریقی لحنِ اول‌شخصِ طبیعی دارند — چتِ تحت‌وب حسِ نرم‌افزارِ دستوردهنده نمی‌گیرد.
12. UI هرگز هنگ نمی‌کند (قوانین تردینگ)؛ همهٔ خطاها صادقانه و قابل‌فهم فارسی‌اند.
13. `ChatBridge-Setup-2.50.0.exe` ساخته می‌شود و اپِ نصب‌شده اجرا می‌شود.
14. همهٔ تست‌های بخش ۱۵ سبز؛ worklogِ کاملِ تصمیم‌ها و خلاقیت‌ها نوشته شده است.
