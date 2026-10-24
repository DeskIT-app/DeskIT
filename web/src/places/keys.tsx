// Keys — owned by the Keys session (web/README.md): this file, keys.css,
// desk_keys.py and the Keys section of tests.py. Every binding lit on the
// drawn keyboard (dashboard._screen_keys); click a cap, or press a real
// key, to see what it does; change it by listening for a new one.
//
// Everything drawn is desk_keys.Place.read(): the board's caps already
// laid out from keycaps.py, every word, which caps are lit and how. What
// stays here is what has to be instant: which cap is picked (a click is
// drawn the next frame, no round trip) and the listening itself — the
// page hears the key (keyCode is the Windows virtual-key code the hook
// matches on, code says which side), and Python names it, checks it and
// binds it. The app is paused while it listens; desk_keys resumes it on
// every way out, this page's own included (Esc, Cancel, leaving the
// place, the window hidden) and the ones it cannot say (a lease the page
// renews every second).
import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { IC, placeCall, useDesk, usePlace } from "../kit";
import "./keys.css";

type Lit = "hold" | "tap" | "held-too" | "chord" | "soft" | "sometimes";
type BoardCap = {
  id: string; label: string; x: number; y: number; w: number; h: number; title: string;
  heb?: string; state?: Lit; caption?: string; on?: string[]; numlock?: boolean;
};
type RowCap = { t: string; k: "hold" | "tap" | "soft" | "off"; name?: string };
type Field = {
  what: string; how: string; note: string; said: string; shown: string; raw: string;
  caps: RowCap[]; cap: string | null; state: "hold" | "tap" | "off"; kind: string; may_off: boolean;
};
type Words = {
  eyebrow: string; none: string; free: string; two: string; numlock: string; change: string;
  listen: string; modifier: string; unusable: string; esc: string; off: string; cancel: string;
  chord: string; bare: string; tap: string;
};
type Keys = {
  ok: boolean; title: string; sub: string;
  legend: { title: string; state: string | null; lines: string[] }[];
  board: { caps: BoardCap[]; w: number; h: number; u: number };
  fields: Record<string, Field>;
  columns: { name: string; rows: string[] }[][];
  foot: { lead: string; caps: string[]; tail: string; missing: string };
  words: Words;
  codes: Record<string, string>;
  vks: Record<string, string>;
  start: string | null;
  capture: { field: string; listening: string; may_off: boolean } | null;
  running: boolean;
  note?: string; chosen?: string | null; refused?: string;
};

/** The four arrow caps, as the picture draws them (Segoe Fluent). */
const ARROW: Record<string, string> = { up: "", down: "", left: "", right: "" };
/** A modifier key, by the event's code: its group, and its side. */
const MOD: Record<string, [string, string]> = {
  ControlLeft: ["ctrl", "left"], ControlRight: ["ctrl", "right"],
  ShiftLeft: ["shift", "left"], ShiftRight: ["shift", "right"],
  AltLeft: ["alt", "left"], AltRight: ["alt", "right"],
  MetaLeft: ["win", "left"], MetaRight: ["win", "right"],
};
/** How often the page says it is still listening (desk_keys.LEASE_S is 4 s). */
const ALIVE_MS = 1000;
const POLL_MS = 2000;

function litClass(state?: string | null): string {
  if (state === "hold") return "hold";
  if (state === "tap" || state === "held-too" || state === "chord") return "tap";
  if (state === "soft") return "soft";
  if (state === "sometimes") return "some";
  return "";
}

/** The last answer, kept for the next visit: a place is built again on
 *  every switch (app.tsx), and drawn from this at once the board is there
 *  the frame it is asked for — the fresh read lands a few ms later, and
 *  draws nothing if nothing moved. Plain data, never a node. */
let kept: Keys | null = null;

export default function KeysPlace({ sub }: { sub: string }) {
  void sub;                                   // Keys has no parts
  const { say } = useDesk();
  const { data: read, reload } = usePlace<Keys>("keys", {}, POLL_MS);
  // kept without a listening in it: the next visit starts at rest
  if (read) kept = read.capture ? { ...read, capture: null } : read;
  const data = read ?? kept;
  // undefined: not picked yet, and the dictation key is (the picture)
  const [picked, setPicked] = useState<string | null | undefined>(undefined);
  const [prompt, setPrompt] = useState("");
  const selected = picked === undefined ? (data?.start ?? null) : picked;
  const capture = data?.capture ?? null;

  // the sky, placed for Keys (the picture's)
  useEffect(() => {
    document.body.classList.add("keys-place");
    return () => document.body.classList.remove("keys-place");
  }, []);

  const act = useCallback((what: string, arg?: unknown): Promise<Keys | null> =>
    placeCall<Keys>("keys", "act", { do: what, arg: arg ?? null }, 8000)
      .then((r) => {
        reload(r);
        if (r.refused) setPrompt(r.refused);
        if (r.note) say(r.note);
        if (r.chosen) setPicked(r.chosen);
        return r;
      })
      .catch((e: Error) => { say(e.message); return null; }), [reload, say]);

  const listen = useCallback((field: string) => {
    const cap = data?.fields[field]?.cap;
    if (cap) setPicked(cap);
    setPrompt("");
    void act("capture.start", field);
  }, [act, data]);

  // what the key handlers read, without being bound again on every answer
  const live = useRef({ data, capture, act });
  live.current = { data, capture, act };

  // A REAL KEY. Not listening, it picks the cap under the finger
  // (dashboard._key_pressed). Listening, it is the Tk dialog's on_key and
  // on_release: a modifier only waits — bound on its release if nothing
  // else came while it was down — and anything else is the key, with the
  // modifiers that were down; Esc cancels.
  useEffect(() => {
    const held = new Set<string>();
    let pending: { vk: number; code: string } | null = null;
    const mods = (e: KeyboardEvent) => {
      const out = new Set(held);
      if (e.ctrlKey) out.add("ctrl");
      if (e.shiftKey) out.add("shift");
      if (e.altKey) out.add("alt");
      if (e.metaKey) out.add("win");
      return [...out];
    };
    const down = (e: KeyboardEvent) => {
      const { data: d, capture: c, act: a } = live.current;
      if (!c) {
        const cap = d && (d.codes[e.code] ?? d.vks[String(e.keyCode)]);
        if (cap) setPicked(cap);
        return;
      }
      e.preventDefault();
      e.stopPropagation();
      if (e.repeat) return;
      if (e.key === "Escape") {
        pending = null;
        void a("capture.cancel");
        return;
      }
      const mod = MOD[e.code];
      if (mod) {
        held.add(mod[0]);
        pending = { vk: e.keyCode, code: e.code };
        setPrompt(d?.words.modifier ?? "");
        return;
      }
      pending = null;
      void a("capture.key", { vk: e.keyCode, side: "", mods: mods(e) });
    };
    const up = (e: KeyboardEvent) => {
      const { capture: c, act: a } = live.current;
      const mod = MOD[e.code];
      if (c) {
        e.preventDefault();
        e.stopPropagation();
        if (pending && pending.code === e.code) {
          const p = pending;
          pending = null;
          void a("capture.key", { vk: p.vk, side: mod ? mod[1] : "", mods: [] });
        }
      }
      if (mod) held.delete(mod[0]);
    };
    const lost = () => { held.clear(); pending = null; };
    window.addEventListener("keydown", down, true);
    window.addEventListener("keyup", up, true);
    window.addEventListener("blur", lost);
    return () => {
      window.removeEventListener("keydown", down, true);
      window.removeEventListener("keyup", up, true);
      window.removeEventListener("blur", lost);
    };
  }, []);

  // LISTENING: say so every second; and give the pause back the moment the
  // window is hidden or the place is left.
  const listening = !!capture;
  useEffect(() => {
    if (!listening) return undefined;
    const tick = window.setInterval(() => {
      placeCall<Keys>("keys", "act", { do: "capture.alive", arg: null }, 3000)
        .then((r) => { if (!r.capture) reload(r); })
        .catch(() => undefined);
    }, ALIVE_MS);
    const onVis = () => { if (document.hidden) void live.current.act("capture.cancel"); };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearInterval(tick);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [listening, reload]);
  useEffect(() => () => {
    if (live.current.capture) {
      void placeCall("keys", "act", { do: "capture.cancel", arg: null }, 3000).catch(() => undefined);
    }
  }, []);
  useEffect(() => { if (!listening) setPrompt(""); }, [listening]);

  // a caption too wide for its cap gets smaller, never cut (the picture's fit)
  const board = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    board.current?.querySelectorAll<HTMLElement>(".cp").forEach((el) => {
      el.style.fontSize = "";
      let size = 9;
      while (el.scrollWidth > el.clientWidth + 0.5 && size > 7.5) {
        size -= 0.25;
        el.style.fontSize = `${size}px`;
      }
    });
  }, [data?.board]);

  if (!data) return <div className="place-keys" />;
  const waiting = capture ? data.fields[capture.field]?.cap ?? null : null;

  return (
    <div className="place-keys">
      <div className="head">
        <div className="title">{data.title}</div>
        <div className="sub">{data.sub}</div>
        <div className="legend">
          {data.legend.map((item) => (
            <div className="lgi" key={item.title}>
              <Swatch state={item.state} />
              <div className="t"><b>{item.title}</b>
                <span>{item.lines.map((line, i) => <span key={i}>{i ? <br /> : null}{line}</span>)}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className={`slab glass${capture ? " wait" : ""}`}
           onClick={(e) => { if (!capture && e.target === e.currentTarget) setPicked(null); }}>
        <div className="kb" ref={board} style={{ width: data.board.w, height: data.board.h }}
             onClick={(e) => { if (!capture && e.target === e.currentTarget) setPicked(null); }}>
          {data.board.caps.map((c) => (
            <Cap key={c.id} cap={c} selected={c.id === selected} waiting={c.id === waiting}
                 pick={capture ? undefined : () => setPicked(c.id)} />
          ))}
        </div>
      </div>

      <div className="band">
        <div className="list">
          {data.columns.map((col, i) => (
            <div className="col" key={i}>
              {col.map((group) => (
                <div className="grp" key={group.name}>
                  <div className="eyebrow">{group.name}</div>
                  {group.rows.map((field) => {
                    const f = data.fields[field];
                    return f ? (
                      <Row key={field} f={f} on={capture?.field === field}
                           press={capture ? undefined : () => listen(field)} />
                    ) : null;
                  })}
                </div>
              ))}
            </div>
          ))}
        </div>
        <Panel data={data} selected={selected} prompt={prompt} listen={listen} act={act} />
      </div>

      <div className={`foot${data.foot.missing ? " more" : ""}`}>
        <span className="words">
          {data.foot.missing ? `${data.foot.missing} ` : ""}{data.foot.lead}
          <span className="gap" />
          {data.foot.caps.map((c, i) => <span className="cap" key={i}>{c}</span>)}
          <span className="gap" />
          {data.foot.tail}
        </span>
      </div>
    </div>
  );
}

// ------------------------------------------------------------- the board

function Swatch({ state }: { state: string | null }) {
  if (state === "chord") {
    return <i className="sw pair"><i className="sw k soft" /><i className="sw k tap" /></i>;
  }
  return <i className={`sw k ${litClass(state)}`} />;
}

function Cap({ cap, selected, waiting, pick }: {
  cap: BoardCap; selected: boolean; waiting: boolean; pick?: () => void;
}) {
  const arrow = ARROW[cap.id];
  const kind = /^f\d+$/.test(cap.id) ? " fn" : cap.label.length > 1 && !arrow ? " word" : "";
  const lit = litClass(cap.state);
  const two = cap.on && cap.on.length > 1 ? cap.on.length : 0;
  return (
    <div className={`k${kind}${lit ? ` ${lit}` : ""}${cap.caption ? " lit" : ""}${selected ? " sel" : ""}`
                    + `${waiting ? " wait" : ""}${pick ? " can" : ""}`}
         style={{ left: cap.x, top: cap.y, width: cap.w, height: cap.h }}
         onClick={pick ? (e) => { e.stopPropagation(); pick(); } : undefined}>
      <span className="lg">
        {arrow ? <span className="la ic ar">{arrow}</span>
          : cap.label ? <span className="la">{cap.label}</span> : null}
        {cap.heb ? <span className="hb" dir="rtl" lang="he">{cap.heb}</span> : null}
      </span>
      {cap.caption ? <span className="cp">{cap.caption}</span> : null}
      {two ? <span className="two">{two}</span> : null}
    </div>
  );
}

// -------------------------------------------------------------- the list

function RowCaps({ caps }: { caps: RowCap[] }) {
  return (
    // every cap and every "+" a child of the row's own flex, so the gap
    // falls on both sides of a "+" (kit's Caps wraps a "+" with its cap,
    // and the gap then lands on one side only)
    <span className="keys">
      {caps.map((c, i) => {
        const glyph = c.name ? ARROW[c.name] : undefined;
        return (
          <Fragment key={i}>
            {i ? <span className="plus">+</span> : null}
            <span className={`cap ${c.k}c${glyph ? " gl" : ""}`}>
              {glyph ? <i className="ic">{glyph}</i> : c.t}
            </span>
          </Fragment>
        );
      })}
    </span>
  );
}

function Row({ f, on, press }: { f: Field; on: boolean; press?: () => void }) {
  const two = !!f.note;
  return (
    <div className={`row${two ? " two" : ""}${on ? " on" : ""}${press ? " can" : ""}`} onClick={press}>
      <span className="n">{f.what}{f.how === "hold" ? <i>{f.how}</i> : null}{two ? <i>{f.note}</i> : null}</span>
      <RowCaps caps={f.caps} />
    </div>
  );
}

// ------------------------------------------------------------- the panel

/** One binding as the panel draws it: its key on a cap, what it does, how
 *  it is pressed — big, as the picture has it, or `small` with a button
 *  of its own on the right (the listening picture's row). */
function Binding({ f, w, small, button }: { f: Field; w: Words; small?: boolean; button?: ReactNode }) {
  return (
    <div className={`pk${small ? " small" : ""}`}>
      <div className={`k ${litClass(f.state)} lit`}><span className="lg"><span className="la">{f.shown}</span></span></div>
      <div className="nm"><div className="n">{f.what}</div><div className="m">{f.how || w.tap}<i>·</i>{f.kind}</div></div>
      {button}
    </div>
  );
}

function Panel({ data, selected, prompt, listen, act }: {
  data: Keys; selected: string | null; prompt: string;
  listen: (field: string) => void; act: (what: string, arg?: unknown) => Promise<Keys | null>;
}) {
  const w = data.words;
  const cap = selected ? data.board.caps.find((c) => c.id === selected) : undefined;
  const capture = data.capture;
  const heard = capture ? data.fields[capture.field] : undefined;
  let body: ReactNode;
  let mode = "rest";
  if (capture && heard) {
    // the panel's own copy of what the Tk dialog said, and its two buttons
    mode = "wait";
    const said = prompt || w.listen;
    body = (
      <>
        <div className="hear">
          <div className="l1"><b>{said}</b>{said === w.listen || said === w.modifier
            ? <span className="esc">{w.esc}</span> : null}</div>
          <span className="l2">{capture.listening}<i className="caret" /></span>
        </div>
        <Binding f={heard} w={w} small
                 button={<div className="btn chg" onClick={() => void act("capture.cancel")}>{w.cancel}</div>} />
        {capture.may_off ? (
          <div className="btn off" onClick={() => void act("capture.off")}>{w.off}</div>
        ) : null}
      </>
    );
  } else if (!cap) {
    mode = "none";
    body = <div className="says">{w.none}</div>;
  } else {
    const on = (cap.on ?? []).flatMap((field) => {
      const f = data.fields[field];
      return f ? [{ field, f }] : [];
    });
    const only = on.length === 1 ? on[0] : undefined;
    if (!on.length) {
      mode = "free";
      body = (
        <>
          <div className="nm big">{cap.title}</div>
          <div className="says">{w.free.replace("{name}", cap.title)}</div>
        </>
      );
    } else if (only && !only.f.said && !cap.numlock) {
      body = (
        <>
          <Binding f={only.f} w={w} />
          <div className="btn primary go" onClick={() => listen(only.field)}><i className="ic">{IC.keyboard}</i>{w.change}</div>
        </>
      );
    } else {
      mode = on.length > 1 ? "many" : "noted";
      const word = w.change.split(" ")[0] ?? w.change;
      body = (
        <>
          {on.map(({ field, f }) => (
            <div key={field}>
              <Binding f={f} w={w} small button={
                <div className={`btn chg${on.length === 1 ? " primary" : ""}`} onClick={() => listen(field)}>{word}</div>} />
              {f.said ? <div className="says sm">{f.said}</div> : null}
            </div>
          ))}
          {on.length > 1 ? <div className="says sm">{w.two}</div> : null}
        </>
      );
    }
    if (cap.numlock) body = <>{body}<div className="says sm">{w.numlock}</div></>;
  }
  return (
    <div className={`panel glass ${mode}`}>
      <div className="eyebrow"><i className="ic">{IC.keyboard}</i>{w.eyebrow}</div>
      {body}
    </div>
  );
}
