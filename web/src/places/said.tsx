// Said — owned by the Said session (web/README.md): this file, said.css and
// desk_said.py, and the Said section of tests.py. transcripts.log read back
// (dashboard._screen_said): the search, the filters, SAID_PAGE rows at a
// time behind a Show more, the other PCs' rows as "from <device>", the
// vocabulary beside the list, a click on a row that copies it, and the
// log's own file. Every word is desk_said.Place.read's; the page draws it.
//
// What a place keeps between visits (the Tk desk keeps its places built):
// the filter, the search, how many rows, where the list was scrolled to,
// and the last answer — so a revisit draws at once, and the read that
// follows changes only what moved.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Caps, Change, IC, Seg, placeCall, useDesk, usePlace } from "../kit";
import "./said.css";

type Tag = { t: string; g?: "pip" | "phone" | "laptop" };
type Pair = { heard: string; meant: string; rtl: boolean };
type Row = {
  id: string; kind: string; glyph: string; label: string; when: string; secs: string;
  tags: Tag[]; meta: string[]; text: string; rtl: boolean; dim: boolean; pairs: Pair[];
  copy: boolean;
};
type Day = { key: string; date: string; day: string; facts: string[]; rows: Row[] };
type Vocab = {
  eyebrow: string; count: string; w: string; w2: string; teach: string[]; teach_words: string;
  lately: string; pairs: Pair[]; nothing: string; foot: string;
};
type Said = {
  ok: boolean; head: string; sub: string; placeholder: string;
  filters: { name: string; key: string }[]; filter: string; q: string; shown: number;
  days: Day[]; more: { words: string; left: string } | null; empty: string;
  vocab: Vocab; older: string; open: string;
};
type Acted = { ok: boolean; note: string; copied?: boolean };

const PAGE = 25;          // desk_said.SAID_PAGE
const ROWS = 5000;        // desk_said.SHOWN_MOST: All stops at the hundred by itself
const POLL_MS = 800;      // the Tk desk's cadence
const COPIED_MS = 1600;   // how long a row says it was copied

// this window's memory of the place, across visits
const kept = { filter: "", q: "", shown: PAGE, scroll: 0, answer: null as Said | null };

export default function SaidPlace({ sub }: { sub: string }) {
  void sub;                                  // Said has no parts
  const { say } = useDesk();
  const [filter, setFilter] = useState(kept.filter);
  const [q, setQ] = useState(kept.q);
  const [shown, setShown] = useState(kept.shown);
  const [copied, setCopied] = useState("");
  const [asking, setAsking] = useState("");
  const list = useRef<HTMLDivElement>(null);
  const copiedTimer = useRef(0);
  const { data } = usePlace<Said>("said", { filter, q, shown }, POLL_MS);
  const said = data ?? kept.answer;

  useEffect(() => {
    kept.filter = filter; kept.q = q; kept.shown = shown;
  }, [filter, q, shown]);
  useEffect(() => {
    if (data) kept.answer = data;
  }, [data]);

  // the sky, placed for Said (the picture's): a class on <body> while here
  useEffect(() => {
    document.body.classList.add("said-here");
    return () => {
      document.body.classList.remove("said-here");
      window.clearTimeout(copiedTimer.current);
    };
  }, []);

  // a new filter or a new search starts the list over, at its top
  const toTop = () => {
    if (list.current) list.current.scrollTop = 0;
    kept.scroll = 0;
  };
  const pick = (key: string) => {
    if (key === filter) return;
    setFilter(key);
    setShown(PAGE);
    toTop();
  };
  const search = (text: string) => {
    setQ(text);
    setShown(PAGE);
    toTop();
  };

  const copy = useCallback((row: Row) => {
    placeCall<Acted>("said", "act", { do: "copy", arg: row.id })
      .then((r) => {
        say(r.note);
        if (r.copied) {
          setCopied(row.id);
          window.clearTimeout(copiedTimer.current);
          copiedTimer.current = window.setTimeout(() => setCopied(""), COPIED_MS);
        }
      })
      .catch((e: Error) => say(e.message));
  }, [say]);

  const press = (what: string, run: () => Promise<unknown>) => {
    setAsking(what);
    run().finally(() => setAsking(""));
  };

  const open = () => press("open", () =>
    placeCall<Acted>("said", "act", { do: "open" })
      .then((r) => say(r.note))
      .catch((e: Error) => say(e.message)));

  const more = () => setShown((n) => Math.min(n + PAGE, ROWS));

  // the place appears whole, with its first answer — once per window (a
  // revisit has the last answer at once), as Home waits for its own
  if (!said) return <div className="place-said" />;
  return (
    <div className="place-said">
      <div className="head">
        <div className="title">{said.head}</div>
        <div className="sub">{said.sub}</div>
      </div>
      <label className="search">
        <i className="ic">{IC.search}</i>
        <input value={q} dir="auto" spellCheck={false} maxLength={200}
               placeholder={said.placeholder}
               onChange={(e) => search(e.target.value)} />
      </label>
      <Chips filters={said.filters} on={filter} pick={pick} />

      <List box={list} said={said} copied={copied} copy={copy} more={more}
            moreDown={said.shown < shown} />

      <VocabPanel v={said.vocab} />

      <div className="foot">
        <div className="l"><i className="ic">{IC.history}</i>{said.older}</div>
        <div className={`btn bare end${asking === "open" ? " down" : ""}`} onClick={open}>
          <i className="ic">{IC.file}</i>{said.open}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- the chips

/** history.FILTERS as the B+ track, its one bubble travelling to the
 *  filter that is on (the kit's Seg, the bar's own figure). */
function Chips({ filters, on, pick }: {
  filters: { name: string; key: string }[]; on: string; pick: (key: string) => void;
}) {
  return <div className="chips"><Seg items={filters} on={on} pick={pick} /></div>;
}

// ----------------------------------------------------------------- the list

/** Only the list scrolls; its ends fade into the floor, and a thumb of its
 *  own stands where the native bar would (the picture's .thumb). */
function List({ box, said, copied, copy, more, moreDown }: {
  box: React.RefObject<HTMLDivElement | null>; said: Said | null; copied: string;
  copy: (row: Row) => void; more: () => void; moreDown: boolean;
}) {
  const thumb = useRef<HTMLDivElement>(null);
  const inner = useRef<HTMLDivElement>(null);
  const [ends, setEnds] = useState({ top: true, end: true });
  const restored = useRef(false);

  const measure = useCallback(() => {
    const l = box.current;
    const t = thumb.current;
    if (!l || !t) return;
    const room = l.clientHeight;
    const all = l.scrollHeight;
    const top = l.scrollTop <= 1;
    const end = l.scrollTop + room >= all - 1;
    setEnds((old) => (old.top === top && old.end === end ? old : { top, end }));
    if (all <= room + 1) {
      t.style.visibility = "hidden";        // everything fits: no thumb to hold
      return;
    }
    const track = room - 12;
    const h = Math.max(48, Math.round(track * room / all));
    const y = Math.round((track - h) * (l.scrollTop / (all - room)));
    t.style.visibility = "";
    t.style.height = `${h}px`;
    t.style.transform = `translateY(${y}px)`;
  }, [box]);

  // where the last visit left the list, once its rows are drawn
  useLayoutEffect(() => {
    if (restored.current || !said || !box.current) return;
    restored.current = true;
    box.current.scrollTop = kept.scroll;
  }, [said, box]);

  useLayoutEffect(measure, [said, measure]);
  useEffect(() => {
    const l = box.current;
    const body = inner.current;
    if (!l || !body) return undefined;
    const watch = new ResizeObserver(() => measure());
    watch.observe(body);
    return () => watch.disconnect();
  }, [box, measure]);

  const scrolled = () => {
    if (box.current) kept.scroll = box.current.scrollTop;
    measure();
  };

  // the thumb can be held and dragged, as the native one could
  const grab = (e: React.PointerEvent<HTMLDivElement>) => {
    const l = box.current;
    if (!l) return;
    e.preventDefault();
    const from = e.clientY;
    const start = l.scrollTop;
    const room = l.clientHeight;
    const all = l.scrollHeight;
    const track = room - 12;
    const h = Math.max(48, Math.round(track * room / all));
    const per = (all - room) / Math.max(1, track - h);
    const target = e.currentTarget;
    target.setPointerCapture(e.pointerId);
    target.classList.add("held");
    const move = (ev: PointerEvent) => { l.scrollTop = start + (ev.clientY - from) * per; };
    const up = () => {
      target.classList.remove("held");
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", up);
      target.removeEventListener("pointercancel", up);
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", up);
    target.addEventListener("pointercancel", up);
  };

  return (
    <>
      <div className={`list${ends.top ? " at-top" : ""}${ends.end ? " at-end" : ""}`}
           ref={box} onScroll={scrolled}>
        <div className="inner" ref={inner}>
          {said && said.empty ? <div className="empty">{said.empty}</div> : null}
          {said?.days.map((d) => (
            <div className="dayset" key={d.key}>
              <div className="day">
                <span className="eyebrow">{d.day}</span>
                {d.facts.map((f) => <span key={f} className="facts num"><i>·</i>{f}</span>)}
              </div>
              <div className="card glass">
                {d.rows.map((r) => (
                  <RowView key={r.id} row={r} copied={copied === r.id} copy={copy} />
                ))}
              </div>
            </div>
          ))}
          {said?.more ? (
            <div className="more">
              <div className={`btn${moreDown ? " down" : ""}`} onClick={more}>
                <i className="ic">{IC.chevron}</i>{said.more.words}
              </div>
              <span className="left num">{said.more.left}</span>
            </div>
          ) : null}
        </div>
      </div>
      <div className="thumb" ref={thumb} onPointerDown={grab} />
    </>
  );
}

/** The room the Copy tag takes beside the tags, its gap included. */
const COPY_W = 80;

function RowView({ row, copied, copy }: { row: Row; copied: boolean; copy: (row: Row) => void }) {
  const two = !!(row.secs || row.meta.length);
  const marks = useRef<HTMLDivElement>(null);
  // tags that leave no room for Copy: under the pointer, Copy takes the
  // place of every tag after the first, so no word is cut in half
  const [tight, setTight] = useState(false);
  useLayoutEffect(() => {
    const m = marks.current;
    if (!m) return;
    let need = COPY_W;
    m.querySelectorAll<HTMLElement>(".tag:not(.copy)").forEach((t) => { need += t.offsetWidth + 6; });
    setTight(row.copy && need > m.clientWidth);
  }, [row.tags, row.copy]);
  // A Hebrew run on the left edge, cut at two lines: Chromium's own "…"
  // goes missing there whenever the cut falls after an English word
  // (measured 2026-10-24; it shows when the run is right-aligned), so the
  // row says it was cut itself — the Tk row's DT_END_ELLIPSIS, at the
  // line's end, which for a right-to-left line on the left edge is the left
  const say = useRef<HTMLDivElement>(null);
  const [cut, setCut] = useState(false);
  useLayoutEffect(() => {
    const el = say.current;
    setCut(!!el && row.rtl && el.scrollHeight > el.clientHeight + 1);
  }, [row.text, row.rtl]);
  return (
    <div className={`row${copied ? " copied" : ""}${tight ? " tight" : ""}`} onClick={() => copy(row)}>
      <div className="when">
        <b className="num">{row.when}</b>
        {row.secs ? <span className="num">{row.secs}</span> : null}
      </div>
      <div className={`kd ${row.kind}`}><i className="ic">{IC[row.glyph] ?? IC.mic}</i></div>
      <div className={`tags${two ? " two" : ""}`}>
        <div className="marks" ref={marks}>
          {row.tags.map((t, i) => (
            <span key={`${t.t}${i}`} className="tag">
              {t.g === "pip" ? <span className="pip" />
                : t.g ? <i className="ic">{IC[t.g]}</i> : null}
              <span className="tx">{t.t}</span>
            </span>
          ))}
          {row.copy ? (
            <span className="tag copy">
              <i className="ic">{copied ? IC.tick : IC.copy}</i>{copied ? "Copied" : "Copy"}
            </span>
          ) : null}
        </div>
        {row.meta.length ? (
          <div className="meta num">{row.meta.map((m, i) => (
            <span key={m}>{i ? <i>·</i> : null}{m}</span>
          ))}</div>
        ) : null}
      </div>
      {row.pairs.length ? (
        <div className="pairs" dir={row.pairs.some((p) => p.rtl) ? "rtl" : "ltr"}>
          {row.pairs.map((p, i) => <Change key={i} heard={p.heard} meant={p.meant} rtl={p.rtl} />)}
        </div>
      ) : (
        <div className={`sayw${cut ? " cut" : ""}`}>
          <div className={`say${row.rtl ? " he" : " en"}${row.dim ? " dim" : ""}`}
               dir={row.rtl ? "rtl" : "ltr"} ref={say}>{row.text}</div>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------ the vocabulary

function VocabPanel({ v }: { v: Vocab }) {
  return (
    <div className="voc">
      <div className="eyebrow">{v.eyebrow}</div>
      <i className="ic dic">{IC.dic}</i>
      <div className="top"><span className="n num">{v.count}</span><span className="w">{v.w}</span></div>
      <div className="w2">{v.w2}</div>
      <div className="teach"><Caps caps={v.teach} />{v.teach_words}</div>
      <div className="fade-rule rule" />
      <div className="eyebrow">{v.lately}</div>
      {v.pairs.length ? (
        <div className="lately">{v.pairs.map((p, i) => <Change key={i} heard={p.heard} meant={p.meant} rtl={p.rtl} />)}</div>
      ) : (
        <div className="nothing">{v.nothing}</div>
      )}
      <div className="foot2">{v.foot}</div>
    </div>
  );
}
