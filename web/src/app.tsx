// The desk. Home is drawn here; the other four places say they are still
// in the old desk and open it there. Every word comes from deskweb.py —
// the page only draws, and asks again every POLL_MS.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { call, inDesk } from "./bridge";
import type { Acted, Bar, Button, DayLine, Door, Home, PileRow, Seg } from "./types";

const PLACES = ["Home", "Corrections", "Said", "Keys", "Settings"] as const;
type Place = (typeof PLACES)[number];
const POLL_MS = 800;
const NOTE_MS = 3600;

// Segoe Fluent glyphs (bplus.css .ic)
const IC: Record<string, string> = {
  bell: "", edit: "", globe: "", key: "", up: "",
  chip: "", lock: "", history: "", keyboard: "",
  settings: "", close: "", tick: "", left: "", right: "",
  stop: "", moon: "", sun: "", pause: "", play: "",
  info: "", open: "",
};

const AWAY: Record<string, string> = {
  Corrections: "Every proposal of the second reading, and the words it has learned.",
  Said: "Everything you said, with the search over it.",
  Keys: "Every key lit on a drawn keyboard — click one to see it or change it.",
  Settings: "Everything you can change, in plain words.",
};

function hashPlace(): Place {
  const want = window.location.hash.replace(/^#\/?/, "").toLowerCase();
  return (PLACES.find((p) => p.toLowerCase() === want) ?? "Home") as Place;
}

export default function App() {
  const [place, setPlace] = useState<Place>(hashPlace);
  const [home, setHome] = useState<Home | null>(null);
  const [leaving, setLeaving] = useState<Set<string>>(new Set());
  const [pressed, setPressed] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const acting = useRef(0);
  const noteTimer = useRef<number>(0);
  // the last answer as text: a poll that brings nothing new draws nothing
  const lastRead = useRef("");

  const say = useCallback((text: string) => {
    window.clearTimeout(noteTimer.current);
    setNote(text);
    if (text) noteTimer.current = window.setTimeout(() => setNote(""), NOTE_MS);
  }, []);

  const read = useCallback(() => {
    if (acting.current) return;              // a press is answering with Home itself
    call<Home>("home", {}, 4000)
      .then((h) => {
        if (acting.current) return;
        document.body.dataset.read = "1";
        const text = JSON.stringify(h);
        if (text === lastRead.current) return;
        lastRead.current = text;
        setHome(h);
        setError("");
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    read();
    let timer = window.setInterval(read, POLL_MS);
    // a minimised window asks nothing; it asks at once when it is back
    const onVis = () => {
      window.clearInterval(timer);
      if (!document.hidden) {
        read();
        timer = window.setInterval(read, POLL_MS);
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [read]);

  useEffect(() => {
    const onHash = () => setPlace(hashPlace());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = (p: Place) => {
    if (p === place) return;
    window.location.hash = p === "Home" ? "" : `#/${p.toLowerCase()}`;
    setPlace(p);
  };

  // One press: the row it belongs to leaves at once, the button shows it
  // was pressed, and the answer is Home again — drawn the moment it lands.
  const act = useCallback((b: { act: string; arg?: unknown }, rowId?: string) => {
    const key = `${b.act}:${String(b.arg ?? "")}`;
    acting.current += 1;
    setPressed(key);
    const goes = rowId && /^(notify\.dismiss|review\.|consent\.|keys\.later|hardware\.seen)/.test(b.act);
    if (goes && rowId) setLeaving((old) => new Set(old).add(rowId));
    if (b.act === "notify.dismiss_all") {
      setLeaving((old) => {
        const next = new Set(old);
        home?.pile.filter((r) => r.kind === "notify").forEach((r) => next.add(r.id));
        return next;
      });
    }
    call<Acted>("act", { do: b.act, arg: b.arg ?? null }, 8000)
      .then((r) => {
        lastRead.current = JSON.stringify(r.home);
        setHome(r.home);
        say(r.note);
      })
      .catch((e: Error) => say(e.message))
      .finally(() => {
        acting.current -= 1;
        setPressed("");
        setLeaving(new Set());
      });
  }, [home, say]);

  useEffect(() => {
    document.body.classList.toggle("calm", place === "Home" && !!home && !home.locked && home.pile.length === 0);
  }, [place, home]);

  return (
    <>
      <div className="sky"><i className="indigo" /><i className="blue" /><i className="plum" /><i className="teal" />
        <i className="lamp-light" /><i className="rib r1" /><i className="rib r2" /></div>
      <div className="grain" />
      <TopBar place={place} go={go} bar={home?.bar} locked={!!home?.locked} pressed={pressed} act={act} />
      <div className="page">
        {!inDesk() ? <Away place={place} text="This page only works inside the desk's window." act={act} plain />
          : home?.locked ? <Landing act={act} />
          : place === "Home" ? (home ? <HomePlace home={home} leaving={leaving} pressed={pressed} act={act} go={go} /> : null)
          : <Away place={place} text={AWAY[place] ?? ""} act={act} />}
      </div>
      <div className={`toast glass${note || error ? " up" : ""}`}>
        <i className="ic">{IC.info}</i>{note || error}
      </div>
    </>
  );
}

// ------------------------------------------------------------------ the bar

function Mark({ dev }: { dev: string }) {
  return (
    <div className="mark">
      <svg width="26" height="26" viewBox="0 0 64 64">
        <rect width="64" height="64" rx="14" fill="#1c2143" />
        <path d="M10 14H30A20 20 0 0 1 50 34V54" stroke="var(--ink)" strokeWidth="8" fill="none" />
        <circle cx="30" cy="34" r="10" fill="var(--mark-lamp)" />
      </svg>
      {dev ? <div className="dev">{dev}</div> : null}
    </div>
  );
}

function TopBar({ place, go, bar, locked, pressed, act }: {
  place: Place; go: (p: Place) => void; bar?: Bar; locked: boolean; pressed: string;
  act: (b: { act: string; arg?: unknown }) => void;
}) {
  const track = useRef<HTMLDivElement>(null);
  const bubble = useRef<HTMLSpanElement>(null);
  const [ready, setReady] = useState(false);

  useLayoutEffect(() => {
    const on = track.current?.querySelector<HTMLElement>(".item.on");
    if (on && bubble.current) {
      bubble.current.style.left = `${on.offsetLeft}px`;
      bubble.current.style.width = `${on.offsetWidth}px`;
    }
  }, [place, locked]);

  // the first placement does not slide in from nowhere: the transition
  // is switched on only once the bubble is where it belongs
  useEffect(() => {
    document.fonts.ready.then(() => {
      const on = track.current?.querySelector<HTMLElement>(".item.on");
      if (on && bubble.current) {
        bubble.current.style.left = `${on.offsetLeft}px`;
        bubble.current.style.width = `${on.offsetWidth}px`;
      }
      requestAnimationFrame(() => setReady(true));
    });
  }, []);

  const run = bar?.run ?? "Start";
  const runIcon = run === "Pause" ? IC.pause : IC.play;
  return (
    <div className="bar">
      <Mark dev={bar?.dev ?? ""} />
      {locked ? null : (
        <div className={`seg places${ready ? " sliding" : ""}`} ref={track}>
          <span className="bubble" ref={bubble} />
          {PLACES.map((p) => (
            <div key={p} className={`item${p === place ? " on" : ""}`} onClick={() => go(p)}>{p}</div>
          ))}
        </div>
      )}
      <div className="spacer" />
      <div className={`chip${bar && bar.lamp !== "listen" ? (bar.lamp === "rec" ? " rec" : " idle") : ""}`}>
        <span className={`lamp ${bar?.lamp ?? "idle"}`} />
        <span className="word">{bar?.word ?? "…"}</span>
        <span className="meta num">{bar?.meta ?? ""}</span>
      </div>
      <div className={`btn stop${bar?.stop ? "" : " gone"}${pressed === "stop:" ? " down" : ""}`}
           onClick={() => bar?.stop && act({ act: "stop" })}>
        <i className="ic">{IC.stop}</i>Stop
      </div>
      <div className={`btn gap8 scrk${bar?.stop ? "" : " gone"}${pressed === "screens:" ? " down" : ""}`}
           onClick={() => bar?.stop && act({ act: "screens" })}>
        <i className="ic">{bar?.screens === "Screens on" ? IC.sun : IC.moon}</i>{bar?.screens ?? "Screens off"}
      </div>
      <div className={`btn run${pressed === "run:" ? " down" : ""}`} onClick={() => act({ act: "run" })}>
        <i className="ic">{runIcon}</i>{run}
      </div>
    </div>
  );
}

// -------------------------------------------------------------------- Home

function HomePlace({ home, leaving, pressed, act, go }: {
  home: Home; leaving: Set<string>; pressed: string;
  act: (b: { act: string; arg?: unknown }, rowId?: string) => void; go: (p: Place) => void;
}) {
  const calm = home.pile.length === 0;
  return (
    <>
      <div className="head">
        <div className="title">{home.head}</div>
        <div className="sub">{home.sub}</div>
        {home.unread ? (
          <div className="dismiss">
            <span className="lnk" onClick={() => act({ act: "notify.dismiss_all" })}>Dismiss all</span>
            {home.dismiss_key.length ? <Caps caps={home.dismiss_key} /> : null}
          </div>
        ) : null}
      </div>

      {calm ? (
        <div className="quiet">
          <div className="big">Nothing is waiting.</div>
          <div className="sub2">Nothing else on the desk needs you right now.</div>
          <div className="state">
            <span className={`lamp ${home.bar.lamp}`} /><b>{home.bar.word}</b>
            {home.hold_key !== "off" ? (
              <><span>·</span><span>hold</span><Caps caps={[home.hold_key]} /><span>and speak.</span></>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="main">
        {calm ? null : (
          <div className="pile">
            {home.pile.map((row, i) => (
              <Slip key={row.id} row={row} lead={i === 0} leaving={leaving.has(row.id)}
                    pressed={pressed} act={act} />
            ))}
          </div>
        )}
        {home.held ? <div className="held">{home.held}</div> : null}
        <Day lines={home.rest} act={act} go={go} />
      </div>

      <div className="aside glass">
        {home.doors.map((d) => <DoorTile key={d.place} door={d} go={go} />)}
      </div>

      <div className="foot">
        <div className="l"><i className="ic">{IC.moon}</i><span>{home.strip.awake}</span></div>
        <div className="r">
          {home.strip.phone ? <span className="live" /> : null}
          {home.strip.phone ? "phone live" : "phone off"}
          {home.strip.facts.map((f) => <span key={f}><span className="sep">·</span>{f}</span>)}
        </div>
      </div>
    </>
  );
}

function Caps({ caps }: { caps: string[] }) {
  return (
    <span className="keys">
      {caps.map((c, i) => (
        <span key={`${c}${i}`}>{i ? <span className="plus">+</span> : null}<span className="cap">{c}</span></span>
      ))}
    </span>
  );
}

function Slip({ row, lead, leaving, pressed, act }: {
  row: PileRow; lead: boolean; leaving: boolean; pressed: string;
  act: (b: { act: string; arg?: unknown }, rowId?: string) => void;
}) {
  const showNote = !!row.note && row.kind !== "review" && row.kind !== "notify";
  return (
    <div className={`slip glass${lead ? " lead" : ""}${leaving ? " leaving" : ""}${showNote ? " noted" : ""}`}
         title={row.kind === "review" && row.note ? row.note : undefined}>
      <div className={`mk ${row.tone}`}><i className="ic">{IC[row.glyph] ?? IC.info}</i></div>
      <div className="tx">
        <div className="eb"><b>{row.title}</b>{row.meta ? <span>{row.meta}</span> : null}</div>
        <div className={`s${row.rtl ? " he" : ""}`} dir={row.rtl ? "rtl" : "ltr"}>
          {row.segs ? <Segs segs={row.segs} rtl={row.rtl} /> : row.text}
        </div>
        {showNote ? <div className="nt">{row.note}</div> : null}
      </div>
      <div className="acts">
        {row.buttons.map((b) => <SlipButton key={`${b.act}${String(b.arg ?? "")}`} b={b} row={row}
                                             pressed={pressed} act={act} />)}
      </div>
    </div>
  );
}

function SlipButton({ b, row, pressed, act }: {
  b: Button; row: PileRow; pressed: string;
  act: (b: { act: string; arg?: unknown }, rowId?: string) => void;
}) {
  const down = pressed === `${b.act}:${String(b.arg ?? "")}` ? " down" : "";
  if (b.tone === "close") {
    return <div className={`x${down}`} title="Dismiss" onClick={() => act(b, row.id)}><i className="ic">{IC.close}</i></div>;
  }
  return (
    <div className={`btn${b.tone === "primary" ? " primary" : ""}${down}`} onClick={() => act(b, row.id)}>
      {b.label}
    </div>
  );
}

function Segs({ segs, rtl }: { segs: Seg[]; rtl: boolean }) {
  return (
    <>
      {segs.map((s, i) => {
        if (s.t === "ctx") return <span key={i} className="ctx">{s.s}</span>;
        if (s.t === "drop") return <span key={i} className="chg"><span className="pill heard">{s.s}</span></span>;
        return (
          <span key={i} className="chg">
            <span className="pill heard" dir="auto">{s.heard}</span>
            <i className="ic arrow">{rtl ? IC.left : IC.right}</i>
            <span className="pill prop"><i className="ic">{IC.tick}</i><span dir="auto">{s.meant}</span></span>
          </span>
        );
      })}
    </>
  );
}

function Day({ lines, act, go }: {
  lines: DayLine[]; act: (b: { act: string; arg?: unknown }) => void; go: (p: Place) => void;
}) {
  return (
    <div className="day">
      <div className="eyebrow">The rest of the day</div>
      <div className="lines">
        {lines.length ? lines.map((l) => (
          <div key={l.label} className="line"
               onClick={() => (l.act ? act({ act: l.act }) : l.go ? go(l.go as Place) : undefined)}>
            <span className="l">{l.label}</span>
            <span className="t num">{l.when}</span>
            <span className={`x${l.rtl ? " he" : ""}`} dir={l.rtl ? "rtl" : "ltr"}>{l.text}</span>
            <span className="m">{l.meta}</span>
          </div>
        )) : <div className="line empty"><span className="x">Nothing dictated yet.</span></div>}
      </div>
    </div>
  );
}

function DoorTile({ door, go }: { door: Door; go: (p: Place) => void }) {
  return (
    <div className={`door${door.n ? "" : " z"}`} onClick={() => go(door.place as Place)}>
      <div className="top"><span className="n num">{door.n}</span><span className="w">{door.w}</span></div>
      <i className="ic dic">{IC[door.glyph] ?? IC.info}</i>
      <div className="note">{door.note}</div>
    </div>
  );
}

// ------------------------------------------------- places not moved yet

function Away({ place, text, act, plain }: {
  place: Place; text: string; act: (b: { act: string; arg?: unknown }) => void; plain?: boolean;
}) {
  return (
    <div className="away">
      <div className="title">{place}</div>
      <div className="card glass awaycard">
        <div className="a1">{plain ? text : `${place} is still in the old desk.`}</div>
        {plain ? null : <div className="a2">{text} It moves here next — one place at a time.</div>}
        {plain ? null : (
          <div className="btn" onClick={() => act({ act: "old", arg: place })}>
            <i className="ic">{IC.open}</i>Open it in the old desk
          </div>
        )}
      </div>
    </div>
  );
}

function Landing({ act }: { act: (b: { act: string; arg?: unknown }) => void }) {
  return (
    <div className="away">
      <div className="title">Sign in to DeskIT</div>
      <div className="card glass awaycard">
        <div className="a1">Dictation waits for an account on this PC.</div>
        <div className="a2">Signing in is still in the old desk.</div>
        <div className="btn primary" onClick={() => act({ act: "old", arg: "Home" })}>
          <i className="ic">{IC.open}</i>Open the old desk
        </div>
      </div>
    </div>
  );
}
