# Changelog

The release workflow copies the section under the tag's heading into
the draft release and adds the fixed block itself (SHA-256, VirusTotal,
attestation, the previous version) — do not write those here. Hebrew
paragraph first (the owner's), English second (DISTRIBUTION_PLAN.md
11.11 step 2).

## 1.1.1

הסיבוב הראשון של משתמש מאפס (19.9.2026), על 1.1.0 המותקנת. "Open the desk" לא פתח כלום — כל קובץ שהעותק המותקן מפעיל לפי נתיב לא מצא את המודולים שלו (המפרש המבודד; תוקן בכולם, ולתהליכי־בת יש עכשיו spawn.log). האשף באנגלית פשוטה ובצבעי האפליקציה: שורה אחת לכל מיקרופון, ההסבר על חלונות פעם אחת ונכון, החשבון ככרטיס, המקשים ניתנים לשינוי כבר שם, ומשפט הבדיקה מראה את זמן הפענוח (0.5 שניות) ולא את טעינת המודל (8). הנקודה היא הסימן עצמו ונראית על כל רקע; מסך הטעינה וכרטיס המקשים צוירו מחדש; skia נכללת בהתקנה, אז העותק המותקן נראה כמו של המפתח. בלי מפתח ענן ההדבקה נוחתת מיד (0.6 שניות) והתיקון המקומי מציע בכרטיס; עם מפתח — התיקון לפני ההדבקה כמו קודם. המזהה האנגלי נטען אחרי שהאפליקציה כבר שמישה. דף "נכנסת" מעוצב, והחלון חוזר קדימה אחרי הכניסה. המתקין: דף פתיחה עם הסימן, שתי לחיצות. בדיקת העדכון: המארח החדש של GitHub להורדות.

The first walkthrough as a stranger (2026-09-19), on the installed 1.1.0. "Open the desk" did nothing — every script an installed copy starts by path could not import its own modules under the isolated interpreter (fixed in all of them; child processes now leave their last words in spawn.log). The wizard in plain English and the app's own colours: one row per microphone, the Windows-privacy help once and right, the account as a card, keys rebound on the page, and the test sentence shows the decode (0.5 s), not the model's load (8 s). The dot is the mark itself and reads on any wallpaper; the boot card and the keys card are redrawn; skia ships in the base, so an install looks like the developer's desk. Without a cloud key the paste lands at once (0.6 s) and the local repair proposes on the card; with a key the repair runs before the paste as before. The English detector loads after the app is usable. The sign-in page is designed and the window comes back in front. The installer: a Welcome page with the mark, two clicks. The update check: GitHub's new download host is allowed.

## 1.1.0

הגרסה הראשונה שמתקינים. מתקין למשתמש בלבד, נבנה כולו ב־GitHub מהתג; המודל העברי יורד פעם אחת בהפעלה הראשונה, עם הגודל על המסך והשהיה שממשיכה מאיפה שעצרה; המפתחות שלך ב־Windows Credential Manager; כל חיבור יוצא דרך דלת אחת ומופיע במסך הרשת (הגדרות > פרטיות); בדיקת עדכון שבועית ששואלת קודם. חשבון Google נדרש פעם אחת באשף; שני סנכרונים, כל אחד מאחורי כרטיס הסכמה משלו — המילים שלמדת וההגדרות ששינית, ומה שאמרת. אף פעם לא מפתחות, לא מקשים, לא אודיו.

An account — required: the first-run wizard asks for a Google sign-in
before the keys work, once, and this PC remembers you until you sign
out; signed out, the window is one landing card with the sign-in
button until you sign in again (an anonymous account exists for report-only use, on Settings >
Privacy). Two syncs behind their own consent cards — your learned words and changed settings, and what
you said, so the Said page is the same on every PC you sign into.
Never keys, hotkeys, devices, folders or positions; never audio. The
server's whole schema is published in the repository and no table in
it has a column that could hold a key.

Opening the desk brings the app up without the model — every key
that needs no model works at once — and Start loads the model when you
want to dictate. Stop in the desk unloads the model and nothing else: the screenshot,
the screen recording, the camera, translate, look up, the shelf and
every other key that needs no model keep working while it is off, and
Start loads it again in about 25 seconds. Quit DeskIT, on Settings >
The app, is the whole app.

The first installable DeskIT: a per-user installer built entirely on
GitHub from the tag, a hashed wheelhouse and a SHA-verified embeddable
Python; the Hebrew model downloaded once at first start, with the size
on the screen and a pause that resumes; NVIDIA's CUDA libraries as a
pack on request; keys in Windows Credential Manager; every connection
through one door and listed on the Network screen (Settings > Privacy);
the weekly update check
that asks first.
