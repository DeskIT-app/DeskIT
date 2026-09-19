# DeskIT

<div dir="rtl">

**הכתבה בעברית לחלונות שנשארת במחשב שלך.** ה־Win+H שעברית מעולם לא קיבלה.

מחזיקים מקש, מדברים, משחררים — הטקסט העברי מופיע אצל הסמן, בכל חלון. התמלול רץ על
המחשב שלך עם המודל העברי של ivrit.ai; שום דבר לא נשלח לשום מקום עד שתפעיל את זה
בעצמך, ואפשר לראות כל בקשה. קוד פתוח, Apache-2.0, חינם.

## להתקין

- **[להוריד את המתקין](https://github.com/DeskIT-app/DeskIT/releases/latest/download/DeskIT-Setup.exe)** — `DeskIT-Setup.exe`, בערך 60 מגה־בייט
  ([דף הגרסה](https://github.com/DeskIT-app/DeskIT/releases/latest): ה־SHA-256, סריקת VirusTotal, ה־attestation). מותקן למשתמש שלך בלבד, בלי סיסמת מנהל.
- או בטרמינל, אם יש לך winget: `winget install YoavShimron.DeskIT` (אחרי שהחבילה תאושר).

חלונות 10 (1809 ומעלה) או 11, 64 ביט. בהפעלה הראשונה אשף קצר ומודל העברית יורד פעם אחת
(1.6 ג'יגה־בייט). כרטיס NVIDIA הופך את התמלול למיידי; בלעדיו זה עובד, לאט יותר.
חלונות עשוי להזהיר פעם אחת שהמתקין לא חתום — [למה, ומה לעשות](https://deskit-app.github.io/DeskIT/he/01-install);
[מדיניות חתימת הקוד](CODE_SIGNING_POLICY.md).

## המדריך

**[התחלה מהירה](https://deskit-app.github.io/DeskIT/he/quickstart)** — חמישה צעדים. הגרסה
הארוכה: [המדריך המלא](https://deskit-app.github.io/DeskIT/) — התקנה, הפעלה ראשונה, הכתבה,
[פרטיות ואיך לבדוק בעצמך](https://deskit-app.github.io/DeskIT/he/04-privacy), תכונות ענן,
מקלדת הטלפון, צילומי מסך, הנתונים שלך, שאלות ותשובות.

## פרטיות

הקול והטקסט נשארים במחשב. תכונות שמדברות עם שירות בענן — תיקון מילים, תרגום, מה־שכתוב־על־המסך —
כבויות עד שתדביק מפתח משלך, ואז כל תכונה מבקשת הסכמה בנפרד ואומרת בדיוק מה נשלח ולאן.
המפתח שלך נשמר במנהל האישורים של חלונות ולא בשום קובץ. הרשימה המלאה של השרתים שהאפליקציה
בכלל מסוגלת לדבר איתם: [NETWORK.md](NETWORK.md). [מדיניות הפרטיות](https://deskit-app.github.io/DeskIT/privacy) ·
[תנאי השימוש](https://deskit-app.github.io/DeskIT/terms).

## משהו לא עובד?

**Ctrl+Alt+R** בכל מקום פותח תיבת דיווח קטנה; הדיווח נשמר במחשב הזה עם המסך, ההכתבה
האחרונה וההגדרות. כדי שנראה אותו:
[פותחים דיווח כאן](https://github.com/DeskIT-app/DeskIT/issues/new/choose) — הטופס מבקש את
בלוק האבחון (הגדרות, האפליקציה, "Copy diagnostics"), שאינו מכיל תמלולים ולא מפתחות ואפשר
לקרוא אותו לפני שמדביקים. בעיות אבטחה: [SECURITY.md](SECURITY.md).

</div>

---

**Hebrew dictation for Windows that stays on your PC.** The Win+H that Hebrew never got.

Hold a key, speak, release — the Hebrew text lands at your cursor in any window.
Transcription runs on your machine with ivrit.ai's Hebrew model; nothing is sent anywhere
until you turn it on yourself, and every request can be seen. Open source, Apache-2.0, free.

## Install

- **[Download the installer](https://github.com/DeskIT-app/DeskIT/releases/latest/download/DeskIT-Setup.exe)** — `DeskIT-Setup.exe`, about 60 MB
  ([the release page](https://github.com/DeskIT-app/DeskIT/releases/latest): SHA-256, the VirusTotal scan, the attestation). Installs for your user only, no admin password.
- Or, with winget: `winget install YoavShimron.DeskIT` (once the package is accepted).

Windows 10 (1809+) or 11, 64-bit. First start: a short wizard, and the Hebrew model downloads
once (1.6 GB). An NVIDIA card makes transcription instant; without one it works, slower.
Windows may warn once that the installer is unsigned —
[why, and what to do](https://deskit-app.github.io/DeskIT/en/01-install); [code signing policy](CODE_SIGNING_POLICY.md).

## The guide

**[Quick start](https://deskit-app.github.io/DeskIT/en/quickstart)** — five steps. The long
version: [the full guide](https://deskit-app.github.io/DeskIT/) — install, first run, dictating,
[privacy and how to check it yourself](https://deskit-app.github.io/DeskIT/en/04-privacy), cloud
features, the phone keyboard, screenshots, your data, FAQ.

## Privacy

Voice and text stay on the PC. Features that talk to a cloud service — word repair, translation,
what's-on-my-screen — are off until you paste a key of your own, and then each one asks for
consent separately and says exactly what is sent where. Your key lives in Windows Credential
Manager, never in a file. Every host the app is able to talk to at all:
[NETWORK.md](NETWORK.md). [Privacy policy](https://deskit-app.github.io/DeskIT/privacy) ·
[Terms](https://deskit-app.github.io/DeskIT/terms).

## Something wrong?

**Ctrl+Alt+R** anywhere opens a small report box; the report is saved on this PC with the
screen, the last dictation and your settings. For us to see it:
[open an issue](https://github.com/DeskIT-app/DeskIT/issues/new/choose) — the form asks for
the diagnostics block (Settings › The app › "Copy diagnostics"), which holds no transcripts
and no keys and can be read before pasting. Security: [SECURITY.md](SECURITY.md).

## For developers

The code is the product: a Python tree run by a stock python.org interpreter, no freezing,
every installed file listed in `MANIFEST.sha256` and reproducible from the tag. Start with
[AGENTS.md](AGENTS.md) (how the program is put together and the rules it keeps), then
[dev/README-dev.md](dev/README-dev.md) (the owner's working notes: every feature with its
measurements, the config reference, the dev checkout) and
[DISTRIBUTION_PLAN.md](DISTRIBUTION_PLAN.md) (how it ships, decisions D1–D36). Tests:
`python tests.py --no-screen`. Licence: [Apache-2.0](LICENSE); the name and mark:
[TRADEMARK.md](TRADEMARK.md); third-party notices ship in every install.
