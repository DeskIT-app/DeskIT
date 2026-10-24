// What every place draws with and asks through. One copy of each piece:
// a place that needs something two places draw takes it from here, and a
// piece only one place draws stays in that place's file.
//
//   IC          the Segoe Fluent glyphs (bplus.css .ic), by name
//   Caps        a key as keycaps: ["Ctrl", "Alt", "M"], or lit caps
//   Switch      the B+ switch: a soft track when on, a hollow ring when off
//   Seg         a track of choices with ONE bubble that slides to the lit one
//   Change      one change: the heard pill, an arrow, the proposal pill
//   Segs        a sentence with every change in its place
//   placeCall   one call to a place's Python module (deskweb.Api.place)
//   usePlace    a place's data: read on mount, polled while visible
//   useDesk     the frame's say(note) and go(place, sub?), and its act()
//   useHome     Home as the frame's poll last read it (the bar's, Home's)
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState,
  type KeyboardEvent } from "react";
import { call } from "./bridge";
import type { Acted, Home, Seg } from "./types";
import "./kit.css";

// Segoe Fluent glyphs (bplus.css .ic), by what they mean on the desk.
// up / down / left / right are ARROWS (a keycap's, a change's); the
// chevron is the menu's and Show more's; download is "a newer version".
export const IC: Record<string, string> = {
  // the desk's own
  bell: "", edit: "", globe: "", key: "", download: "",
  chip: "", lock: "", history: "", keyboard: "",
  settings: "", close: "", tick: "",
  up: "", down: "", left: "", right: "", chevron: "",
  stop: "", moon: "", sun: "", pause: "", play: "",
  info: "", open: "", add: "", search: "", mic: "",
  copy: "", folder: "", file: "", sync: "", undo: "",
  warning: "", send: "", help: "", laptop: "", power: "",
  eye: "", message: "", link: "", phone: "",
  // Said: what each kind of line was (history.KINDS' icons)
  translate: "", punctuate: "", learned: "", error: "",
  discarded: "", dic: "",
  // Settings: the sections' discs
  monitor: "", video: "", volume: "", contact: "",
  book: "", camera: "",
};

// ------------------------------------------------------------ the frame's

/** What the frame (app.tsx) gives every place. Stable: a place that only
 *  uses these is not drawn again when Home's poll brings something new. */
export type Desk = {
  /** one line at the foot of the window, for a moment ("" hides it) */
  say: (note: string) => void;
  /** to a place, and to a part of it: go("settings", "privacy") is
   *  #/settings/privacy. The place that is lit already, with no sub, is
   *  left as it is — the bar's own rule (dashboard._nav_go). */
  go: (place: string, sub?: string) => void;
  /** a button of the desk's own (deskweb.Model._do — Home's verbs and the
   *  bar's): the answer is Home, which the frame draws at once. A place's
   *  own buttons go through placeCall(name, "act", ...). */
  act: (b: { act: string; arg?: unknown }) => Promise<Acted | null>;
};

export const DeskContext = createContext<Desk>({
  say: () => undefined,
  go: () => undefined,
  act: () => Promise.resolve(null),
});

export function useDesk(): Desk {
  return useContext(DeskContext);
}

/** Home as the frame's 800 ms poll last read it, and the desk button
 *  being answered ("act:arg", drawn pressed until the answer lands). */
export type HomeRead = { home: Home | null; pressed: string };

export const HomeContext = createContext<HomeRead>({ home: null, pressed: "" });

export function useHome(): HomeRead {
  return useContext(HomeContext);
}

// ---------------------------------------------------------- a place's data

/** What every place answer carries: ok, and the words when it is not. */
export type PlaceAnswer = { ok: boolean; error?: string };

/** One call to a place's module: deskweb.Api.place(name, op, args) —
 *  op "read" is Place.read(**payload), op "act" is Place.act(do, arg)
 *  with payload {do, arg}. An answer {ok: false, error} rejects, with the
 *  error as the message (words for a refusal, a type name for a crash). */
export function placeCall<T = unknown>(name: string, op: "read" | "act",
                                       payload: Record<string, unknown> = {},
                                       timeoutMs = 5000): Promise<T> {
  return call<PlaceAnswer>("place", { name, op, args: payload }, timeoutMs).then((r) => {
    if (r && r.ok === false) throw new Error(r.error || `${name}: ${op} refused`);
    return r as unknown as T;
  });
}

export type PlaceRead<T> = {
  /** the last answer (null until the first) */
  data: T | null;
  /** the last read's failure, "" once one answers */
  error: string;
  /** read again now; or, given an answer (an act that answers with the
   *  place, as Home's does), draw that one — a read already on its way
   *  that lands after it is dropped as older */
  reload: (fresh?: T) => void;
};

/** A place's data: read on mount and every pollMs (0: once) while the
 *  window is visible — a minimised window asks nothing, and asks at once
 *  when it is back. An answer identical to the one drawn draws nothing
 *  (app.tsx's lastRead), and a poll never stacks on a read in flight. */
export function usePlace<T>(name: string, args: Record<string, unknown> = {},
                            pollMs = 0): PlaceRead<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const key = JSON.stringify(args);
  const lastRead = useRef("");    // what is drawn, as text
  const asked = useRef(0);        // every read, and every fresh answer, takes the next number
  const shown = useRef(0);        // the number of what is drawn
  const flying = useRef(0);       // reads not answered yet

  const take = useCallback((value: T, n: number) => {
    if (n < shown.current) return;            // older than what is drawn
    shown.current = n;
    setError("");
    const text = JSON.stringify(value);
    if (text === lastRead.current) return;
    lastRead.current = text;
    setData(value);
  }, []);

  const read = useCallback(() => {
    const n = ++asked.current;
    flying.current += 1;
    placeCall<T>(name, "read", JSON.parse(key) as Record<string, unknown>)
      .then((v) => take(v, n))
      .catch((e: Error) => { if (n >= shown.current) setError(e.message); })
      .finally(() => { flying.current -= 1; });
  }, [name, key, take]);

  const reload = useCallback((fresh?: T) => {
    if (fresh === undefined) read();
    else take(fresh, ++asked.current);
  }, [read, take]);

  useEffect(() => {
    // A new question (name or args): an answer to the old one that lands
    // after this is older than what is asked now, and is dropped.
    shown.current = ++asked.current;
    read();
    if (!(pollMs > 0)) return undefined;
    const tick = () => { if (!flying.current) read(); };
    let timer = document.hidden ? 0 : window.setInterval(tick, pollMs);
    const onVis = () => {
      window.clearInterval(timer);
      if (!document.hidden) {
        tick();
        timer = window.setInterval(tick, pollMs);
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [read, pollMs]);

  return { data, error, reload };
}

// ---------------------------------------------------------------- pieces

/** One keycap: its words, or an arrow drawn as the glyph (`arrow`: up,
 *  down, left or right), and a class of the place's own (how it is lit). */
export type Cap = string | { t: string; arrow?: string; cls?: string };

export function Caps({ caps }: { caps: Cap[] }) {
  // every cap and every "+" a child of .keys itself, so its gap falls on
  // both sides of the "+" — wrapped in a span each, the "+" sat 3 px after
  // one cap and touching the next (the foundation's pixel review)
  return (
    <span className="keys">
      {caps.flatMap((c, i) => {
        const cap = typeof c === "string" ? { t: c } : c;
        const glyph = cap.arrow ? IC[cap.arrow] : undefined;
        return [
          ...(i ? [<span key={`+${i}`} className="plus">+</span>] : []),
          <span key={`${cap.t}${i}`} className={`cap${cap.cls ? ` ${cap.cls}` : ""}${glyph ? " gl" : ""}`}>
            {glyph ? <i className="ic">{glyph}</i> : cap.t}
          </span>,
        ];
      })}
    </span>
  );
}

/** The B+ switch: no accent — a soft lavender-grey track when on, a
 *  hollow ring when off. Given `onFlip` it is a control of its own (a
 *  press, Space, Enter); without, it only shows a row's state and the row
 *  takes the press. */
export function Switch({ on, onFlip, busy, label }: {
  on: boolean; onFlip?: () => void; busy?: boolean; label?: string;
}) {
  if (!onFlip) return <span className={`sw${on ? " on" : ""}`}><i /></span>;
  return (
    <span className={`sw${on ? " on" : ""}${busy ? " busy" : ""}`} role="switch"
          aria-checked={on} aria-label={label} tabIndex={0}
          onClick={onFlip}
          onKeyDown={(e: KeyboardEvent) => {
            if (e.key === " " || e.key === "Enter") {
              e.preventDefault();
              onFlip();
            }
          }}>
      <i />
    </span>
  );
}

/** A track of choices with ONE bubble that slides to the lit one — the
 *  bar's places, Said's filters, Settings' tabs. The bubble travels
 *  instead of jumping (the first thing he named about this design), and
 *  its first placement does not slide in from nowhere: the slide is
 *  switched on once the bubble stands where it belongs, fonts settled. */
export function Seg({ items, on, pick, className, tabs }: {
  items: { key: string; name: string }[]; on: string; pick: (key: string) => void;
  className?: string; tabs?: boolean;
}) {
  const track = useRef<HTMLDivElement>(null);
  const bubble = useRef<HTMLSpanElement>(null);
  const [sliding, setSliding] = useState(false);
  const shape = items.map((i) => `${i.key}\u0001${i.name}`).join("\u0002");

  const place = useCallback(() => {
    const lit = track.current?.querySelector<HTMLElement>(":scope > .item.on");
    if (!lit || !bubble.current) return;
    bubble.current.style.left = `${lit.offsetLeft}px`;
    bubble.current.style.width = `${lit.offsetWidth}px`;
  }, []);

  useLayoutEffect(place, [on, shape, place]);
  useEffect(() => {
    if (sliding || !shape) return undefined;
    let live = true;
    document.fonts.ready.then(() => {
      if (!live) return;
      place();
      requestAnimationFrame(() => { if (live) setSliding(true); });
    });
    return () => { live = false; };
  }, [sliding, shape, place]);

  return (
    <div className={`seg${className ? ` ${className}` : ""}${sliding ? " sliding" : ""}`} ref={track}
         role={tabs ? "tablist" : undefined}>
      <span className="bubble" ref={bubble} />
      {items.map((it) => (
        <div key={it.key || "·"} className={`item${it.key === on ? " on" : ""}`}
             role={tabs ? "tab" : undefined} aria-selected={tabs ? it.key === on : undefined}
             tabIndex={tabs ? 0 : undefined}
             onClick={() => pick(it.key)}
             onKeyDown={tabs ? (e) => { if (e.key === "Enter") pick(it.key); } : undefined}>
          {it.name}
        </div>
      ))}
    </div>
  );
}

/** One change: the heard word on its red-edged pill, an arrow the way the
 *  line reads, the proposal on the iris pill with a tick. Each word sits
 *  in a span of its own, so a place may cut a long one at its end. */
export function Change({ heard, meant, rtl }: { heard: string; meant: string; rtl: boolean }) {
  return (
    <span className="chg" dir={rtl ? "rtl" : "ltr"}>
      <span className="pill heard"><span className="w" dir="auto">{heard}</span></span>
      <i className="ic arrow">{rtl ? IC.left : IC.right}</i>
      <span className="pill prop"><i className="ic">{IC.tick}</i><span className="w" dir="auto">{meant}</span></span>
    </span>
  );
}

/** The change in its place: contexts, then every change as Change draws
 *  it; a deletion is the words that would go, behind a cross. */
export function Segs({ segs, rtl }: { segs: Seg[]; rtl: boolean }) {
  return (
    <>
      {segs.map((s, i) => {
        if (s.t === "ctx") return <span key={i} className="ctx">{s.s}</span>;
        if (s.t === "drop") {
          return (
            <span key={i} className="chg">
              <span className="pill heard drop"><i className="ic">{IC.close}</i><span className="w" dir="auto">{s.s}</span></span>
            </span>
          );
        }
        return <Change key={i} heard={s.heard} meant={s.meant} rtl={rtl} />;
      })}
    </>
  );
}
