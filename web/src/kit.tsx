// What every place draws with and asks through — SHARED, and frozen while
// the places are built in parallel (web/README.md): a place that wants
// something else here keeps it in its own file until the merge.
//
//   IC          the Segoe Fluent glyphs (bplus.css .ic), by name
//   Caps        a key as keycaps: ["Ctrl", "Alt", "M"]
//   Segs        a sentence with every change in its place: the heard
//               pill, an arrow, the proposal pill (dashboard's Change)
//   Away        "<Place> is still in the old desk", and the way there
//   placeCall   one call to a place's Python module (deskweb.Api.place)
//   usePlace    a place's data: read on mount, polled while visible
//   useDesk     the frame's say(note) and go(place, sub?), and its act()
//   useHome     Home as the frame's poll last read it (the bar's, Home's)
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { call } from "./bridge";
import type { Acted, Home, Seg } from "./types";
import "./kit.css";

// Segoe Fluent glyphs (bplus.css .ic). The second group are the ones the
// approved pictures of the four places draw (design/2026-09-22).
export const IC: Record<string, string> = {
  bell: "", edit: "", globe: "", key: "", up: "",
  chip: "", lock: "", history: "", keyboard: "",
  settings: "", close: "", tick: "", left: "", right: "",
  stop: "", moon: "", sun: "", pause: "", play: "",
  info: "", open: "",
  add: "", search: "", mic: "", down: "", copy: "",
  folder: "", file: "", sync: "", undo: "", warning: "",
  send: "", help: "", laptop: "", power: "", eye: "",
  message: "",
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
  /** a button of the desk's own (deskweb.Model._do — Home's verbs, the
   *  bar's, "old"): the answer is Home, which the frame draws at once.
   *  A place's own buttons go through placeCall(name, "act", ...). */
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

export function Caps({ caps }: { caps: string[] }) {
  return (
    <span className="keys">
      {caps.map((c, i) => (
        <span key={`${c}${i}`}>{i ? <span className="plus">+</span> : null}<span className="cap">{c}</span></span>
      ))}
    </span>
  );
}

/** The change in its place: contexts, the heard word on its red-edged
 *  pill, an arrow the way the line reads, the proposal on the iris pill
 *  with a tick; a deletion is the words that would go. */
export function Segs({ segs, rtl }: { segs: Seg[]; rtl: boolean }) {
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

/** A place that is still in the old desk: its title, one card that says
 *  so, and the button that opens the Tk desk there (deskweb "old").
 *  `plain`: the text alone, no button (the page outside the window). */
export function Away({ place, text, plain }: { place: string; text: string; plain?: boolean }) {
  const { act } = useDesk();
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
