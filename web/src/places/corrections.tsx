// Corrections — owned by the Corrections session (web/README.md): this file,
// corrections.css and desk_corrections.py, and the Corrections section of
// tests.py. What the Tk desk's Corrections place is
// (dashboard._screen_corrections), in the approved picture
// (design/2026-09-22/design/rev/lists/corrections*.png): the second
// reading's proposals with Yes / No, then every learned pair with its
// pencil and cross, the search, the Use them switch and [+ Teach a word];
// the vocabulary panel beside them says what the Tk desk's head line and
// foot said. Every word comes from desk_corrections.Place.read; a press
// is Place.act, answered with the place again and drawn at once.
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type RefObject } from "react";
import { Caps, IC, Segs, Switch, placeCall, useDesk, usePlace } from "../kit";
import type { Seg } from "../types";
import "./corrections.css";

type Btn = { label: string; tone: "primary" | "quiet"; do: string; arg: string };

type Proposal = {
  id: string;
  rtl: boolean;
  count: string;
  why: string;
  why_rtl: boolean;
  more: string;
  segs: Seg[] | null;
  text: string;
  buttons: Btn[];
};

type Word = {
  heard: string;
  meant: string;
  rtl: boolean;
  dot: "fix" | "once" | "guess";
  said: string;
  rest: string;
  /** the Tk desk's whole line about the pair, kept under the pointer */
  whole: string;
  hot: boolean;
};

type Panel = {
  n: number;
  said: string;
  facts: { dot: string; n: number; said: string }[];
  teach: string[];
  /** what the teach key does: the bold half, and the rest */
  teach_said: [string, string];
  how: string[];
};

type Corr = {
  ok: boolean;
  about: string;
  proposals: Proposal[];
  waiting: string;
  learned: string;
  words: Word[];
  empty: string;
  query: string;
  use: boolean;
  teach_lit: boolean;
  panel: Panel;
};

type Acted = { ok: boolean; note: string; done: boolean; place: Corr };

/** The editor's three facts: the pair it opened on ("" for a new one),
 *  and the two fields as they stand. */
type Editing = { was: string; heard: string; meant: string };

/** How long typing has to stop before the list moves (dashboard.SEARCH_MS). */
const SEARCH_MS = 160;
/** How often the place is read while nothing is being typed into it — the
 *  Tk desk's _poll_corrections, once a second; never under the editor. */
const POLL_MS = 1000;
/** The editor's fields stop where desk_corrections.WORD_MAX does. */
const WORD_MAX = 200;
/** How many learned rows the first frame of a visit draws — more than the
 *  page shows; the rest follow a frame later. All 138 of his at once were
 *  30 ms to the drawn page against 6 ms for the place without them
 *  (dashboard.CORR_FIRST is the Tk desk's same split). */
const FIRST_ROWS = 24;

// The search outlives a visit, as the Tk desk's _words_query does: back on
// Corrections, the list is the one he left. So does the last answer: a
// visit draws it in the first frame, and the read that follows moves only
// what changed — the Tk desk kept the place built for the same reason.
let keptQuery = "";
let keptPlace: Corr | null = null;

export default function CorrectionsPlace({ sub }: { sub: string }) {
  void sub;                                  // one tab is no tabs (dashboard.corr_tabs)
  const { say } = useDesk();
  const [typed, setTyped] = useState(keptQuery);
  const [query, setQuery] = useState(keptQuery);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [leaving, setLeaving] = useState<Set<string>>(new Set());
  const [pressed, setPressed] = useState("");
  const [useWant, setUseWant] = useState<boolean | null>(null);
  const main = useRef<HTMLDivElement>(null);
  const [upTo, setUpTo] = useState(FIRST_ROWS);

  // the rest of the rows, once the first frame of the visit is on the glass
  useEffect(() => {
    let timer = 0;
    const frame = requestAnimationFrame(() => { timer = window.setTimeout(() => setUpTo(Infinity), 0); });
    return () => { cancelAnimationFrame(frame); window.clearTimeout(timer); };
  }, []);
  const read = usePlace<Corr>("corrections", { q: query }, editing ? 0 : POLL_MS);
  const { error, reload } = read;
  const data = read.data ?? (keptPlace && keptPlace.query === query.split(/\s+/).filter(Boolean).join(" ") ? keptPlace : null);
  useEffect(() => { if (read.data) keptPlace = read.data; }, [read.data]);

  // the list moves once typing stops
  useEffect(() => {
    if (typed === query) return undefined;
    const timer = window.setTimeout(() => { setQuery(typed); keptQuery = typed; }, SEARCH_MS);
    return () => window.clearTimeout(timer);
  }, [typed, query]);

  /** One press: `leave` names the row that goes at once; the answer is
   *  the place again, drawn the moment it lands. Resolves to the answer,
   *  or null when it was refused. */
  const act = useCallback((d: string, arg: unknown, key: string, leave?: string): Promise<Acted | null> => {
    setPressed(key);
    if (leave) setLeaving((old) => new Set(old).add(leave));
    return placeCall<Acted>("corrections", "act", { do: d, arg }, 8000)
      .then((r) => {
        reload(r.place);
        if (r.note) say(r.note);
        return r;
      })
      .catch((e: Error) => {
        say(e.message);
        return null;
      })
      .finally(() => {
        // only this press's marks: another row answered meanwhile stays gone
        setPressed((now) => (now === key ? "" : now));
        if (leave) {
          setLeaving((old) => {
            const next = new Set(old);
            next.delete(leave);
            return next;
          });
        }
      });
  }, [reload, say]);

  const decide = useCallback((b: Btn) => {
    void act(b.do, b.arg, `${b.do}:${b.arg}`, `p:${b.arg}`);
  }, [act]);

  const forget = useCallback((w: Word) => {
    void act("forget", w.heard, `forget:${w.heard}`, `w:${w.heard.toLowerCase()}`);
  }, [act]);

  const save = useCallback((e: Editing) => {
    const d = e.was ? "edit" : "learn";
    const arg = e.was ? { was: e.was, heard: e.heard, meant: e.meant } : { heard: e.heard, meant: e.meant };
    void act(d, arg, "save").then((r) => {
      if (r && r.done) setEditing(null);
    });
  }, [act]);

  const toggleUse = useCallback(() => {
    if (!data) return;
    const want = !(useWant ?? data.use);
    setUseWant(want);
    void act("use", want, "use").finally(() => setUseWant(null));
  }, [act, data, useWant]);

  const teach = useCallback(() => setEditing({ was: "", heard: "", meant: "" }), []);

  const clearSearch = useCallback(() => {
    setTyped("");
    setQuery("");
    keptQuery = "";
  }, []);

  if (!data) {
    return (
      <div className="place-corrections">
        <div className="title">Corrections</div>
        {error ? <div className="about">{error}</div> : null}
      </div>
    );
  }

  const lit = data.teach_lit && !editing;
  const on = useWant ?? data.use;
  const words = data.words;
  // the row he is editing is in the list: the editor stands in its place;
  // it is not (a search hides it, or it is a new pair): at the top
  const inPlace = !!editing && !!editing.was
    && words.some((w) => w.heard.toLowerCase() === editing.was.toLowerCase());

  return (
    <div className="place-corrections">
      <div className="title">Corrections</div>
      <div className="about">{data.about}</div>

      <div className="toolrow">
        <label className="find">
          <i className="ic">{IC.search}</i>
          <input value={typed} placeholder="Find a word" maxLength={WORD_MAX} spellCheck={false} dir="auto"
                 onChange={(e) => setTyped(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Escape") clearSearch(); }} />
        </label>
        <div className="spacer" />
        <div className={`use${pressed === "use" ? " down" : ""}`} role="switch" aria-checked={on}
             onClick={toggleUse}>
          <Switch on={on} />Use them
        </div>
        <div className={`btn teach${lit ? " primary" : ""}`} onClick={teach}>
          <i className="ic">{IC.add}</i>Teach a word
        </div>
      </div>

      <div className="main" ref={main}>
        {data.proposals.length ? (
          <>
            <div className="eyeline"><span className="eyebrow">Waiting on you</span>
              <span className="n">·&nbsp; {data.waiting}</span></div>
            <div className="pile">
              {data.proposals.map((p, i) => (
                <Slip key={p.id} p={p} lead={i === 0} leaving={leaving.has(`p:${p.id}`)}
                      pressed={pressed} decide={decide} />
              ))}
            </div>
          </>
        ) : null}

        <div className={`eyeline${data.proposals.length ? " lhead" : ""}`}>
          <span className="eyebrow">Learned</span><span className="n">·&nbsp; {data.learned}</span>
        </div>

        {editing && !inPlace ? (
          <Editor key={editing.was || "+"} e={editing} set={setEditing} save={save}
                  cancel={() => setEditing(null)} saving={pressed === "save"} scrollTo={main} />
        ) : null}

        {data.empty ? <div className="empty">{data.empty}</div> : null}

        {words.length ? (
          <div className="lcard glass">
            {words.slice(0, upTo).map((w) => (editing && inPlace && w.heard.toLowerCase() === editing.was.toLowerCase()
              ? <Editor key={`e:${w.heard}`} e={editing} set={setEditing} save={save} inRow
                        cancel={() => setEditing(null)} saving={pressed === "save"} scrollTo={main} />
              : <Row key={w.heard} w={w} leaving={leaving.has(`w:${w.heard.toLowerCase()}`)}
                     calm={!!editing} edit={() => setEditing({ was: w.heard, heard: w.heard, meant: w.meant })}
                     forget={() => forget(w)} />))}
          </div>
        ) : null}
      </div>

      <Aside panel={data.panel} />
    </div>
  );
}

function Slip({ p, lead, leaving, pressed, decide }: {
  p: Proposal; lead: boolean; leaving: boolean; pressed: string; decide: (b: Btn) => void;
}) {
  return (
    <div className={`slip glass${lead ? " lead" : ""}${leaving ? " leaving" : ""}`}>
      <div className="mk q"><i className="ic">{IC.edit}</i></div>
      <div className="tx">
        <div className="eb">
          <b>Second reading</b>
          {p.count ? <span>{p.count}</span> : null}
          {p.why ? <><span className="dot">·</span>
            <span className={p.why_rtl ? "he" : ""} dir={p.why_rtl ? "rtl" : "ltr"}>{p.why}</span></> : null}
          {p.more ? <><span className="dot">·</span><span>{p.more}</span></> : null}
        </div>
        <div className={`s${p.rtl ? " he" : ""}`} dir={p.rtl ? "rtl" : "ltr"}>
          {p.segs ? <Segs segs={p.segs} rtl={p.rtl} /> : p.text}
        </div>
      </div>
      <div className="acts">
        {p.buttons.map((b) => (
          <div key={b.do} className={`btn${b.tone === "primary" ? " primary" : ""}${pressed === `${b.do}:${b.arg}` ? " down" : ""}`}
               onClick={() => decide(b)}>{b.label}</div>
        ))}
      </div>
    </div>
  );
}

function Pair({ w }: { w: Word }) {
  return (
    <span className="pc" dir={w.rtl ? "rtl" : "ltr"} title={`${w.heard} → ${w.meant}`}>
      <span className="h" dir="auto">{w.heard}</span>
      <i className="ic a">{w.rtl ? IC.left : IC.right}</i>
      <span className="m" dir="auto">{w.meant}</span>
    </span>
  );
}

function Row({ w, leaving, calm, edit, forget }: {
  w: Word; leaving: boolean; calm: boolean; edit: () => void; forget: () => void;
}) {
  return (
    <div className={`lr${leaving ? " leaving" : ""}${calm ? " calm" : ""}`}>
      <Pair w={w} />
      <span className="st" title={w.whole}><span className={`d ${w.dot}`} />{w.said}
        {w.rest ? <span className="q">·&nbsp;{w.rest}</span> : null}</span>
      <span className="ls">{w.hot ? <><span className="d li" />In the prompt</> : null}</span>
      <span className="ac">
        <i className="ic pen" role="button" aria-label="Change" onClick={edit}>{IC.edit}</i>
        <i className="ic x" role="button" aria-label="Forget" onClick={forget}>{IC.close}</i>
      </span>
    </div>
  );
}

function Editor({ e, set, save, cancel, saving, inRow, scrollTo }: {
  e: Editing; set: (e: Editing) => void; save: (e: Editing) => void; cancel: () => void;
  saving: boolean; inRow?: boolean; scrollTo: RefObject<HTMLDivElement | null>;
}) {
  const card = useRef<HTMLDivElement>(null);
  const heard = useRef<HTMLInputElement>(null);
  const meant = useRef<HTMLInputElement>(null);

  // the caret goes where the work is: what you mean on a pair that
  // exists, what it hears on a new one (dashboard._words_editor) — and
  // the card into sight, wherever in the list it opened
  useLayoutEffect(() => {
    (e.was ? meant : heard).current?.focus({ preventScroll: true });
    const box = card.current;
    const pane = scrollTo.current;
    if (box && pane) {
      // where the card is in the list, whatever it sits in (a row's
      // editor is inside the card of rows)
      const at = box.getBoundingClientRect().top - pane.getBoundingClientRect().top + pane.scrollTop;
      const top = at - 24;
      const bottom = at + box.offsetHeight + 64 - pane.clientHeight;
      if (pane.scrollTop > top) pane.scrollTop = top;
      else if (pane.scrollTop < bottom) pane.scrollTop = bottom;
    }
    // once, when it opens
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const keys = (ev: KeyboardEvent<HTMLInputElement>) => {
    if (ev.key === "Enter") save(e);
    else if (ev.key === "Escape") cancel();
  };
  return (
    <div className={`editor${inRow ? " inrow" : " glass"}`} ref={card}>
      <div className="erow">
        <div className="pair-in" dir="rtl">
          <input ref={heard} className="fld hd" dir="auto" value={e.heard} placeholder="what it hears"
                 maxLength={WORD_MAX} spellCheck={false}
                 onChange={(ev) => set({ ...e, heard: ev.target.value })} onKeyDown={keys} />
          <i className="ic arrow">{IC.left}</i>
          <input ref={meant} className="fld" dir="auto" value={e.meant} placeholder="what you mean"
                 maxLength={WORD_MAX} spellCheck={false}
                 onChange={(ev) => set({ ...e, meant: ev.target.value })} onKeyDown={keys} />
        </div>
        <div className="spacer" />
        <div className="btn" onClick={cancel}>Cancel</div>
        <div className={`btn primary${saving ? " down" : ""}`} onClick={() => save(e)}>Save</div>
      </div>
      <div className="hint">A word you type here is fixed on every dictation from now on.</div>
    </div>
  );
}

function Aside({ panel }: { panel: Panel }) {
  return (
    <div className="aside glass">
      <div className="eyebrow">Vocabulary</div>
      <div className="big"><span className="n num">{panel.n}</span></div>
      <div className="bigw">{panel.said}</div>
      <div className="prule" />
      {panel.facts.map((f) => (
        <div key={f.said} className="fact"><span className={`d ${f.dot}`} /><b className="num">{f.n}</b>{f.said}</div>
      ))}
      {panel.teach.length ? (
        <>
          <div className="prule" />
          <div className="tk"><Caps caps={panel.teach} /><span className="lab">{panel.teach_said[0]}</span></div>
          <div className="tline">{panel.teach_said[1]}</div>
        </>
      ) : null}
      <div className="prule" />
      <div className="eyebrow">How it learns</div>
      <div className="how">
        {panel.how.map((h, i) => (
          <div key={h} className="hw"><span className="k">{i + 1}</span><span>{h}</span></div>
        ))}
      </div>
    </div>
  );
}
