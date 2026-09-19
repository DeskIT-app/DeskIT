# Changelog

The release workflow copies the section under the tag's heading into
the draft release and adds the fixed block itself (SHA-256, VirusTotal,
attestation, the previous version) — do not write those here. Hebrew
paragraph first (the owner's), English second (DISTRIBUTION_PLAN.md
11.11 step 2).

## 1.1.2

הסיבוב השני, הפעם מתוך ה-checkout שרץ כעותק מותקן (19.9.2026 בערב). האפליקציה קרסה 34 שניות לתוך ההכתבה הראשונה — חלונות האשף נקברו מחוט התמלול (Tcl_AsyncDelete); עכשיו הם נקברים לפני שהאפליקציה עולה. ההסכמה לענן נפתחת בתוך הכרטיס, מתחת לשורה שהדלקת — שלוש שורות, תנאי הספקים בלחיצה, הפעל / לא עכשיו — ואחריה שדה מעוגל למפתח Groq באותו מקום, עם הדרך למפתח חינמי; לא עוד חלון נפרד שנפתח על מסך אחר ולא זז. ה-X של הדסק סוגר את הכול. משפט ההמתנה בעמוד המשפט אומר אם ההורדה לא התחילה, רצה או נעצרה. המד של המיקרופון זז גם כשלא מקליטים; Next בעמוד המחשב מחכה להורדה; כפתור טעינת המודל לפני ההקלטה. הנקודה: העיגול עם ההילה, כמו תמיד (הסימן המרובע של אחר הצהריים הוסר). הסיבוב השני של אותו ערב: מתג הענן הוא ההסכמה — הדלקה פותחת שדה מפתח מעוגל מתחת לשורה, המפתח נבדק מול Groq ברגע השמירה, ו־Next מחכה עד שמפתח עובד או שהמתג כבוי; Start מפעיל ופותח את הדסק (כפתור Open the desk הוסר); הסיור ליד הנקודה באנגלית, שפת האשף; חבילת ההקלטה (PyAV) מוצעת בעמוד המחשב כברירת מחדל, אז אין מה להתקין באמצע; ב־Settings > Screen יש Browse… ליד שתי תיקיות השמירה. החלפת מסך בדסק: המסך החדש נבנה כשהגיליון מוסר מהחלון וחוזר שלם עם ההחלקה — לא עוד שבע תמונות־ביניים שקופצות אחת על השנייה; קובץ ההגדרות נקרא פעם אחת לגרסה ולא 13 פעמים בלחיצה (Home: 0.52 → 0.30 שניות, נמדד על השולחן הנסתר). המתקין מוריד בעצמו את מה שהאשף הוריד עד עכשיו — המודל העברי, ועם כרטיס אנבידיה גם ספריות ה־CUDA ומזהה האנגלית, וחבילת ההקלטה — בעמוד "הורדות" עם תיבות מסומנות מראש וקישורי הרישיון; מה שהגיע נבדק ומונח במקום, ועמוד המחשב באשף מדולג כשלא נשאר מה להוריד.

The second walk, this time from the checkout running as an installed copy (2026-09-19 evening). The app died 34 s into its first dictation — the wizard's windows were buried from the decode thread (Tcl_AsyncDelete); they are buried before the app starts now. The cloud consent opens on the card, under the row you flipped — three lines, the providers' terms one click away, Turn on / Not now — and then a rounded field for the Groq key in the same place, with the way to a free key; no more separate window on the wrong monitor that could not be moved. The desk's X closes everything. The sentence page says whether the download has not started, is running or stopped. The microphone meter moves while nothing is recorded; Next on the computer page waits for the download; a Load-model button before Record. The dot: the disc with its halo, as always (the afternoon's square mark is gone). The same evening's second round: the cloud switch is the consent — on, a rounded key field opens under the row, the key is checked with Groq the moment it is saved, and Next waits until a key works or the switch is off; Start starts the app and opens the desk (the Open-the-desk button is gone); the tour beside the dot is in English, the wizard's language; the Recording pack (PyAV) is offered on the computer page, on by default, so nothing is installed mid-use; Settings > Screen has Browse… beside the two save folders. Switching a screen on the desk: the new screen is built with the sheet off the window and comes back whole with the slide — no more seven half-built frames jumping on top of each other; the settings files are parsed once per version instead of 13 times a click (Home: 0.52 → 0.30 s, measured on the hidden desktop). The installer downloads what the wizard used to — the Hebrew model, and with an NVIDIA card its CUDA libraries and the English detector, and the Recording pack — on a Downloads page with the boxes ticked and the licences linked; what lands is hashed and put in place, and the wizard's computer page is skipped when nothing is left to download.

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
