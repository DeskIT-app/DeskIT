"""The exam: his own dictations with the words he really said.

A model is better only if it makes fewer mistakes on HIS speech, and that
needs recordings whose text he vouched for. corpus\\read had one (67 s);
the "gold" in corpus\\ is pipeline text with one approved word in it.
So this takes his recent dictations, shows each with the text that was
pasted and the second reading's three other hearings, and he fixes the
text while listening. What he saves is the label.

    python dev\\exam.py --prepare     copy recent\\ clips (>= 3 s) into corpus\\exam\\
    python dev\\exam.py               serve the page on http://127.0.0.1:8771

recent\\ is a ring that drops its oldest recording on every dictation, so
--prepare COPIES first; nothing in recent\\ is changed or removed. In
corpus\\exam\\ each clip is <stem>.wav + <stem>.draft.json (what the app
had) and, once he saved it, <stem>.json (what he vouched for). Nothing
here ever deletes a file. Owner tool: dev\\, not in the build.
"""
from __future__ import annotations

import difflib
import html
import json
import os
import shutil
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECENT = ROOT / "recent"
EXAM = ROOT / "corpus" / "exam"
PORT = 8771
MIN_S = 3.0


def prepare() -> int:
    EXAM.mkdir(parents=True, exist_ok=True)
    copied = 0
    for side in sorted(RECENT.glob("*.json")):
        wav = side.with_suffix(".wav")
        stem = side.stem
        if not wav.exists() or (EXAM / f"{stem}.wav").exists():
            continue
        try:
            meta = json.loads(side.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if float(meta.get("seconds") or 0) < MIN_S or not (meta.get("text") or "").strip():
            continue
        shutil.copy2(wav, EXAM / f"{stem}.wav")
        draft = {"draft": meta.get("text", ""), "raw": meta.get("raw", ""),
                 "seconds": meta.get("seconds"), "saved": meta.get("saved"),
                 "variants": (meta.get("review") or {}).get("variants") or []}
        _write(EXAM / f"{stem}.draft.json", draft)
        copied += 1
    return copied


def _write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, path)


def clips() -> list[dict]:
    out = []
    for d in sorted(EXAM.glob("*.draft.json")):
        stem = d.name[:-len(".draft.json")]
        draft = json.loads(d.read_text("utf-8"))
        done = EXAM / f"{stem}.json"
        vouched = json.loads(done.read_text("utf-8")) if done.exists() else None
        out.append({"stem": stem, **draft, "vouched": vouched})
    return out


def _doubts(draft: str, variants: list[str]) -> str:
    """The draft with every word the other hearings disagree on marked:
    gold when two or more of them heard something else there."""
    words = draft.split()
    against = [0] * len(words)
    for v in variants:
        m = difflib.SequenceMatcher(a=words, b=v.split(), autojunk=False)
        for op, i1, i2, _j1, _j2 in m.get_opcodes():
            if op != "equal":
                for i in range(i1, max(i2, i1 + 1)):
                    if i < len(words):
                        against[i] += 1
    out = []
    for w, n in zip(words, against):
        w = html.escape(w)
        out.append(f'<b class="d2">{w}</b>' if n >= 2 else
                   f'<b class="d1">{w}</b>' if n == 1 else w)
    return " ".join(out)


def _marked(variant: str, draft: str) -> str:
    """The variant with every word the draft does not have in bold."""
    a, b = draft.split(), variant.split()
    m = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    parts = []
    for op, _i1, _i2, j1, j2 in m.get_opcodes():
        words = html.escape(" ".join(b[j1:j2]))
        if not words:
            continue
        parts.append(words if op == "equal" else f"<b>{words}</b>")
    return " ".join(parts)


PAGE = """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<title>Exam</title><style>
:root{--bg:#141414;--card:#1e1e1e;--ink:#eee;--dim:#9a9a9a;--gold:#d9a441;--ok:#5fb37a}
body{background:var(--bg);color:var(--ink);font:16px/1.6 Rubik,"Segoe UI",sans-serif;margin:0;padding:16px}
.top{position:sticky;top:0;background:var(--bg);padding:8px 0 12px;display:flex;gap:16px;align-items:center}
.bar{flex:1;height:6px;background:#333;border-radius:3px}.bar i{display:block;height:6px;background:var(--gold);border-radius:3px}
.card{background:var(--card);border-radius:10px;padding:14px 16px;margin:0 auto 14px;max-width:900px}
.card.done{opacity:.55}.card.done:focus-within{opacity:1}
textarea{width:100%;box-sizing:border-box;background:#111;color:var(--ink);border:1px solid #444;border-radius:8px;
 padding:10px;font:18px/1.6 Rubik,"Segoe UI",sans-serif;min-height:70px}
audio{width:100%;margin:6px 0}.alt{color:var(--dim);font-size:14px}.alt b{color:var(--gold);font-weight:600}
.doubts{font-size:17px;margin:4px 0 8px}.doubts b.d2{color:var(--gold)}.doubts b.d1{color:#c9b98f;font-weight:400;text-decoration:underline dotted}
details summary{color:var(--dim);font-size:14px;cursor:pointer;margin-top:6px}
button{background:#2c2c2c;color:var(--ink);border:1px solid #555;border-radius:8px;padding:6px 14px;font-size:15px;cursor:pointer;margin-inline-end:8px}
button.save{border-color:var(--gold)}.state{color:var(--ok);font-size:14px}.meta{color:var(--dim);font-size:13px}
.help{max-width:900px;margin:0 auto 14px;color:var(--dim)}
</style></head><body>
<div class="top"><b>מבחן</b><div class="bar"><i id="bar"></i></div><span id="count"></span></div>
<div class="help">תקשיב לכל הקלטה ותתקן את הטקסט בתיבה כך שיהיה בדיוק מה שאמרת, מילה במילה. "אממ" ומילים שהתחלת ועזבת - לא צריך לכתוב.
מעל התיבה: אותו טקסט, והמילים שהמחשב לא בטוח בהן צבועות בזהב - שם כנראה יש טעות. כל השאר עדיין צריך לבדוק באוזן.
Ctrl+Enter שומר ועובר לבאה. אפשר להפסיק באמצע: מה ששמרת נשמר.</div>
<div id="list"></div>
<script>
let clips=[];
async function load(){clips=await (await fetch('/clips')).json();draw();}
function count(){const n=clips.filter(c=>c.vouched).length;document.getElementById('count').textContent=n+' / '+clips.length;
 document.getElementById('bar').style.width=(100*n/clips.length)+'%';}
function draw(){const L=document.getElementById('list');L.innerHTML='';clips.forEach((c,i)=>{const d=document.createElement('div');
 d.className='card'+(c.vouched?' done':'');d.id='c'+i;
 const text=c.vouched?(c.vouched.skipped?c.draft:c.vouched.text):c.draft;
 d.innerHTML=`<div class="meta">${i+1}. ${c.saved||''} · ${(+c.seconds).toFixed(1)} שנ'</div>
 <audio controls preload="none" src="/audio/${c.stem}.wav"></audio>
 <div class="doubts">${c.doubts}</div>
 <textarea dir="auto"></textarea>
 <details><summary>עוד שלוש פעמים שהמחשב שמע את זה</summary><div class="alt">${c.alt.map(a=>'<div>'+a+'</div>').join('')}</div></details>
 <div style="margin-top:8px"><button class="save">שמור (Ctrl+Enter)</button><button class="skip">לא ברור / לא דיבור</button>
 <span class="state">${c.vouched?(c.vouched.skipped?'דילגת':'נשמר'):''}</span></div>`;
 const ta=d.querySelector('textarea');ta.value=text;L.appendChild(d);
 const fit=()=>{ta.style.height='auto';ta.style.height=(ta.scrollHeight+4)+'px';};fit();ta.oninput=fit;
 d.querySelector('.save').onclick=()=>save(i,false);d.querySelector('.skip').onclick=()=>save(i,true);
 d.querySelector('textarea').onkeydown=e=>{if(e.key==='Enter'&&e.ctrlKey){e.preventDefault();save(i,false);}};});
 count();}
async function save(i,skipped){const c=clips[i],d=document.getElementById('c'+i);
 const text=d.querySelector('textarea').value.trim();
 const r=await fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({stem:c.stem,text,skipped})});
 if(!r.ok){d.querySelector('.state').textContent='שגיאה בשמירה';return;}
 c.vouched=await r.json();d.classList.add('done');d.querySelector('.state').textContent=skipped?'דילגת':'נשמר';count();
 const n=document.getElementById('c'+(i+1));if(n){n.scrollIntoView({behavior:'smooth',block:'center'});
 const a=n.querySelector('audio');n.querySelector('textarea').focus();a.play().catch(()=>{});}}
load();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):            # the console stays quiet
        pass

    def _send(self, code, body: bytes, kind: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            return self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        if self.path == "/clips":
            data = [{"stem": c["stem"], "draft": c["draft"], "seconds": c["seconds"],
                     "saved": c["saved"], "vouched": c["vouched"],
                     "doubts": _doubts(c["draft"], c["variants"]),
                     "alt": [_marked(v, c["draft"]) for v in c["variants"]]}
                    for c in clips()]
            return self._send(200, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                              "application/json; charset=utf-8")
        if self.path.startswith("/audio/"):
            name = Path(self.path[len("/audio/"):]).name
            path = EXAM / name
            if path.suffix == ".wav" and path.exists():
                return self._send(200, path.read_bytes(), "audio/wav")
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/save":
            return self._send(404, b"not found", "text/plain")
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        stem = Path(str(body.get("stem", ""))).name
        draft_path = EXAM / f"{stem}.draft.json"
        if not draft_path.exists():
            return self._send(404, b"no such clip", "text/plain")
        draft = json.loads(draft_path.read_text("utf-8"))
        record = {"text": str(body.get("text", "")).strip(), "skipped": bool(body.get("skipped")),
                  "draft": draft.get("draft", ""), "seconds": draft.get("seconds"),
                  "source": "dictation", "tier": "exam",
                  "vouched": time.strftime("%Y-%m-%d %H:%M:%S")}
        _write(EXAM / f"{stem}.json", record)
        self._send(200, json.dumps(record, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")


def main() -> int:
    if "--prepare" in sys.argv:
        print(f"copied {prepare()} clip(s) into {EXAM}")
        return 0
    if not any(EXAM.glob("*.draft.json")):
        print(f"run with --prepare first ({EXAM} is empty)")
        return 1
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"exam on http://127.0.0.1:{PORT}  ({len(clips())} clips)", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
