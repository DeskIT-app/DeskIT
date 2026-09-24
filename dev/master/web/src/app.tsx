// The master's six screens. Every screen is a list, every line is a Row,
// every Row carries a box only his hand ticks and one button that takes
// it to a chat — the picture he approved on 2026-09-23, drawn live.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { call, inDesk } from "./bridge";
import type { Count, Preview, Row, ScreenReply, Took } from "./types";

const PLACES = ["Home", "Reports", "Tests", "Code", "Server", "Data"] as const;
type Place = (typeof PLACES)[number];

// Segoe Fluent glyphs, each one checked by eye on this PC before it was used
const IC: Record<string, string> = {
  chat: "", refresh: "", pic: "", mic: "", tick: "",
  warn: "", ok: "", bad: "", idea: "", person: "",
  cloud: "", chart: "", stack: "", doc: "", folder: "",
  link: "", clock: "", info: "", star: "", pulse: "",
  copy: "",
};

const SUB: Record<Place, [string, string]> = {
  Home: ["Home", "What wants your eye today."],
  Reports: ["Reports", "Yours and other people's, in one list."],
  Tests: ["Tests", "Last night here, and the CI on GitHub."],
  Code: ["Code", "What is on this PC and not on GitHub."],
  Server: ["Server", "Where people's settings, words and history travel between their own PCs."],
  Data: ["Data", "On this computer only: your voice, and what it learned from it."],
};

const FOOT: Record<Place, string> = {
  Home: "Nothing here ticks itself. You tick what you have handled.",
  Reports: "Nothing ticks a box but you.",
  Tests: "The nightly run files its own report. Nothing on this screen does anything.",
  Code: "It does not push, merge or tag. That stays in the terminal.",
  Server: "Read only — nothing here writes to the server. The free plan holds 500 MB and 50,000 people a month.",
  Data: "None of this can be made again, and this copy never deletes any of it. The screen watches the ceilings.",
};

// which rows belong under which heading, per screen
const SECTIONS: Partial<Record<Place, { word: string; is: (id: string) => boolean }[]>> = {
  Tests: [
    { word: "Last night, on this PC", is: (id) => id.startsWith("tests:night") || id.startsWith("tests:clean") },
    { word: "On GitHub", is: (id) => id.startsWith("tests:ci") },
  ],
  Code: [
    { word: "Waiting for the weekly merge", is: (id) => id.startsWith("code:branch") },
    { word: "Releases", is: (id) => id.startsWith("code:release") },
  ],
  Server: [
    { word: "Who is on it", is: (id) => id.startsWith("server:who") },
    { word: "What it keeps for them — sealed, the server cannot read it",
      is: (id) => id.startsWith("server:kept") },
    { word: "Waiting for you", is: (id) => id.startsWith("server:wait") },
  ],
};

function hashPlace(): Place {
  const want = window.location.hash.replace(/^#\/?/, "").toLowerCase();
  return (PLACES.find((p) => p.toLowerCase() === want) ?? "Home") as Place;
}

export default function App() {
  const [place, setPlace] = useState<Place>(hashPlace);
  const [reply, setReply] = useState<ScreenReply | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [sheet, setSheet] = useState<Preview | null>(null);
  const [took, setTook] = useState<Took | null>(null);
  const [readAt, setReadAt] = useState("");

  const load = useCallback((which: Place, refresh = false) => {
    setBusy(true);
    setError("");
    call<ScreenReply>("rows", { screen: which.toLowerCase(), refresh }, 60000)
      .then((r) => {
        if (!r.ok) throw new Error(r.error ?? "refused");
        setReply(r);
        setReadAt(r.read_at);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  }, []);

  useEffect(() => { load(place); }, [place, load]);

  useEffect(() => {
    const onHash = () => setPlace(hashPlace());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setSheet(null); setTook(null); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const go = (p: Place) => { window.location.hash = `#/${p.toLowerCase()}`; setPlace(p); };

  const tick = (row: Row) => {
    const want = !row.ticked;
    setReply((old) => old && {
      ...old,
      rows: old.rows.map((r) => (r.id === row.id ? { ...r, ticked: want } : r)),
    });
    call("tick", { id: row.id, on: want }).catch(() => load(place, true));
  };

  const askTake = (row: Row) => {
    setTook(null);
    call<Preview>("preview", { id: row.id }).then((p) => {
      if (p.ok) setSheet(p);
      else setError(p.error ?? "refused");
    }).catch((e: Error) => setError(e.message));
  };

  const doTake = () => {
    if (!sheet) return;
    call<Took>("take", { id: sheet.id, open: true }, 60000).then((t) => {
      setTook(t);
      if (t.ok) load(place, true);
    }).catch((e: Error) => setError(e.message));
  };

  const rows = reply?.rows ?? [];
  const [title, sub] = SUB[place];

  return (
    <>
      <div className="sky"><i className="indigo" /><i className="blue" /><i className="plum" /><i className="rib r1" /></div>
      <div className="grain" />
      <Bar place={place} go={go} readAt={readAt} busy={busy} refresh={() => load(place, true)} />
      <div className="page">
        <div className="title">{title}</div>
        <div className="sub" style={{ left: title.length * 15 + 26 }}>{sub}</div>
        {error ? <div className="headr" style={{ color: "var(--bad)" }}>{error}</div> : null}

        {place === "Home"
          ? <Home rows={rows} counts={reply?.counts} busy={busy} tick={tick} take={askTake} />
          : <Screen place={place} rows={rows} busy={busy} tick={tick} take={askTake} />}

        <div className="foot">
          <div className="l"><i className="ic">{IC.info}</i>{FOOT[place]}</div>
        </div>
      </div>
      {sheet ? <Sheet sheet={sheet} took={took} onTake={doTake}
                      onClose={() => { setSheet(null); setTook(null); }} /> : null}
    </>
  );
}

// ------------------------------------------------------------------ the bar

function Bar({ place, go, readAt, busy, refresh }: {
  place: Place; go: (p: Place) => void; readAt: string; busy: boolean; refresh: () => void;
}) {
  const track = useRef<HTMLDivElement>(null);
  const bubble = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    const on = track.current?.querySelector<HTMLElement>(".item.on");
    if (on && bubble.current) {
      bubble.current.style.left = `${on.offsetLeft}px`;
      bubble.current.style.width = `${on.offsetWidth}px`;
    }
  }, [place]);

  return (
    <div className="bar">
      <div className="mark">
        <svg width="26" height="26" viewBox="0 0 64 64">
          <rect width="64" height="64" rx="14" fill="#1c2143" />
          <path d="M10 14H30A20 20 0 0 1 50 34V54" stroke="var(--ink)" strokeWidth="8" fill="none" />
          <circle cx="30" cy="34" r="10" fill="var(--mark-lamp)" />
        </svg>
        <div className="dev master">MASTER</div>
      </div>
      <div className="seg places" ref={track}>
        <span className="bubble" ref={bubble} />
        {PLACES.map((p) => (
          <div key={p} className={`item${p === place ? " on" : ""}`} data-name={p}
               onClick={() => go(p)}>{p}</div>
        ))}
      </div>
      <div className="spacer" />
      <div className="read num">{busy ? "reading…" : readAt ? `read ${readAt}` : ""}</div>
      <div className="btn qq" onClick={refresh}><i className="ic">{IC.refresh}</i>Refresh</div>
    </div>
  );
}

// --------------------------------------------------------------- the screens

function Screen({ place, rows, busy, tick, take }: {
  place: Place; rows: Row[]; busy: boolean;
  tick: (r: Row) => void; take: (r: Row) => void;
}) {
  const sections = SECTIONS[place];
  return (
    <div className="stack low">
      <div className="scroll">
        {sections
          ? sections.map(({ word, is }) => {
              const mine = rows.filter((r) => is(r.id));
              if (!mine.length) return null;
              return (
                <div key={word}>
                  <div className="sect"><span className="eyebrow">{word}</span></div>
                  <Card rows={mine} tick={tick} take={take} />
                </div>
              );
            })
          : <Card rows={rows} tick={tick} take={take} />}
        {!rows.length && !busy ? <Nothing place={place} /> : null}
      </div>
    </div>
  );
}

function Home({ rows, counts, busy, tick, take }: {
  rows: Row[]; counts?: Record<string, Count>; busy: boolean;
  tick: (r: Row) => void; take: (r: Row) => void;
}) {
  const order = ["reports", "tests", "code", "server", "data"];
  return (
    <>
      <div className="pile">
        <div className="scroll">
          <Card rows={rows} tick={tick} take={take} />
          {!rows.length && !busy
            ? <div className="card glass"><div className="empty">Nothing wants your eye.
                <span>No open report, last night was clean, and nothing is near a ceiling.</span>
              </div></div>
            : null}
        </div>
      </div>
      <div className="side">
        {order.map((key) => {
          const c = counts?.[key];
          return (
            <div className="blk" key={key}>
              <div className="eyebrow">{key[0]!.toUpperCase() + key.slice(1)}</div>
              <div className="n num">{c ? c.n : "—"}<small>{c ? c.word : ""}</small></div>
            </div>
          );
        })}
      </div>
    </>
  );
}

function Nothing({ place }: { place: Place }) {
  return (
    <div className="card glass">
      <div className="empty">
        Nothing on this screen.
        <span>{place === "Reports"
          ? "No report of yours is open, and nobody has sent one."
          : "Press Refresh if you expected something here."}</span>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ the rows

function Card({ rows, tick, take }: {
  rows: Row[]; tick: (r: Row) => void; take: (r: Row) => void;
}) {
  if (!rows.length) return null;
  return (
    <div className="card glass">
      {rows.map((row) => (row.fig
        ? <MeterRow key={row.id} row={row} tick={tick} take={take} />
        : <Line key={row.id} row={row} tick={tick} take={take} />))}
    </div>
  );
}

function Tick({ row, tick }: { row: Row; tick: (r: Row) => void }) {
  return (
    <div className={`tick${row.ticked ? " on" : ""}`} title={row.ticked
      ? `you marked this handled ${row.ticked_at}` : "mark it handled — nothing else ever will"}
      onClick={() => tick(row)}><i className="ic">{IC.tick}</i></div>
  );
}

function Take({ row, take }: { row: Row; take: (r: Row) => void }) {
  if (row.took) {
    return (
      <span className="took" title={row.took_folder} onClick={() => take(row)}>
        <i className="ic">{IC.folder}</i>Taken to a chat · {row.took.slice(5, 16)}
      </span>
    );
  }
  return (
    <div className="take" onClick={() => take(row)}>
      <i className="ic">{IC.chat}</i>Take it to a chat
    </div>
  );
}

function Line({ row, tick, take }: {
  row: Row; tick: (r: Row) => void; take: (r: Row) => void;
}) {
  return (
    <div className={`row${row.ticked ? " done" : ""}`}>
      <Tick row={row} tick={tick} />
      <div className="when">
        <b className="num">{row.when}</b>
        {row.when_small ? <span>{row.when_small}</span> : null}
      </div>
      <div className={`kd ${row.tone}`}><i className="ic">{IC[row.glyph] ?? IC.doc}</i></div>
      <div className="what">
        <div className={`l1${row.rtl ? " he" : ""}`} dir={row.rtl ? "rtl" : undefined}>{row.title}</div>
        <div className="l2">{row.under}</div>
      </div>
      <div className="ev">
        {row.evidence.map((e, i) => (
          <span className="tag" key={i}>
            <i className="ic">{e.kind === "picture" ? IC.pic : e.kind === "recording" ? IC.mic : IC.doc}</i>
            {e.word}
          </span>
        ))}
      </div>
      <Take row={row} take={take} />
    </div>
  );
}

function MeterRow({ row, tick, take }: {
  row: Row; tick: (r: Row) => void; take: (r: Row) => void;
}) {
  return (
    <div className={`mrow${row.ticked ? " done" : ""}`}>
      <Tick row={row} tick={tick} />
      <div className="nm">{row.title}<span>{row.under}</span></div>
      <div className="fig num">{row.fig}<i>{row.fig_small}</i></div>
      {row.pct === null
        ? <div />
        : <div className={`meter ${row.meter_tone}`}><i style={{ width: `${row.pct}%` }} /></div>}
      <Take row={row} take={take} />
    </div>
  );
}

// ----------------------------------------------------------------- the sheet

function Sheet({ sheet, took, onTake, onClose }: {
  sheet: Preview; took: Took | null; onTake: () => void; onClose: () => void;
}) {
  return (
    <>
      <div className="dim" onClick={onClose} />
      <div className="sheet">
        <h2>Take it to a chat</h2>
        <div className="of">{sheet.title}</div>
        <div className="files">
          {sheet.files.map((f) => (
            <div className="f" key={f.name}>
              <i className="ic">{f.kind === "picture" ? IC.pic : f.kind === "recording" ? IC.mic : IC.doc}</i>
              {f.name} <span>— {f.word}</span>
            </div>
          ))}
        </div>
        <div className="where path">{took?.folder ?? sheet.folder}</div>
        <div className="note">
          Nothing is summarised and nothing is rewritten. The document is built around the
          row's own words, exactly as they arrived, and says plainly that they are a person's
          words — so the chat reads them as a quotation.
        </div>
        {took?.ok
          ? <div className="done-line">
              Written{took.copied ? ", and the document is on your clipboard" : ""}. The folder is open.
            </div>
          : null}
        <div className="acts">
          {took?.ok
            ? <div className="btn primary" onClick={onClose}>Done</div>
            : <div className="btn primary" onClick={onTake}>
                <i className="ic">{IC.chat}</i>Copy it and open the folder
              </div>}
          {took?.ok ? null : <div className="btn" onClick={onClose}>Not now</div>}
        </div>
      </div>
    </>
  );
}

// the window says so plainly when it is opened outside WebView2
export function NotInDesk() {
  return inDesk() ? null : (
    <div className="empty">This page only works inside the master's window.</div>
  );
}
