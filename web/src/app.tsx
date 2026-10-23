// The desk's frame — SHARED, and frozen while the places are built in
// parallel (web/README.md): the bar with its sliding bubble, the router
// (#/place or #/place/sub), the toast, and Home's poll, which feeds the
// bar's state and Home itself. Each place is a file of its own under
// places/; every word comes from Python — the page only draws.
import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { call, inDesk } from "./bridge";
import { Away, DeskContext, HomeContext, IC, type Desk } from "./kit";
import CorrectionsPlace from "./places/corrections";
import HomePlace, { Landing } from "./places/home";
import KeysPlace from "./places/keys";
import SaidPlace from "./places/said";
import SettingsPlace from "./places/settings";
import type { Acted, Bar, Home } from "./types";

const PLACES = ["Home", "Corrections", "Said", "Keys", "Settings"] as const;
type Place = (typeof PLACES)[number];
type Route = { place: Place; sub: string };
const VIEWS: Record<Place, (props: { sub: string }) => ReactNode> = {
  Home: HomePlace, Corrections: CorrectionsPlace, Said: SaidPlace, Keys: KeysPlace,
  Settings: SettingsPlace,
};
const POLL_MS = 800;
const NOTE_MS = 3600;

function placeOf(name: string): Place | undefined {
  const want = name.toLowerCase();
  return PLACES.find((p) => p.toLowerCase() === want);
}

/** #/settings/privacy -> Settings, "privacy"; anything else is Home. */
function hashRoute(): Route {
  const [head = "", ...rest] = window.location.hash.replace(/^#\/?/, "").split("/");
  const place = placeOf(head);
  return place ? { place, sub: decodeURIComponent(rest.join("/")) } : { place: "Home", sub: "" };
}

function routeHash(r: Route): string {
  if (r.place === "Home" && !r.sub) return "";
  return `#/${r.place.toLowerCase()}${r.sub ? `/${encodeURIComponent(r.sub)}` : ""}`;
}

// The place's own view, drawn again only when the route changes: Home's
// poll redraws the frame, never a place that does not read it.
const PlaceView = memo(function PlaceView({ place, sub }: Route) {
  const View = VIEWS[place];
  return <View sub={sub} />;
});

export default function App() {
  const [route, setRoute] = useState<Route>(hashRoute);
  const [home, setHome] = useState<Home | null>(null);
  const [pressed, setPressed] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const acting = useRef(0);
  const noteTimer = useRef<number>(0);
  const where = useRef(route);
  where.current = route;
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
    const onHash = () => {
      const next = hashRoute();
      setRoute((old) => (old.place === next.place && old.sub === next.sub ? old : next));
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // The place that is lit, with no sub asked for, stays as it is — the
  // bar's own rule (dashboard._nav_go).
  const go = useCallback((name: string, sub?: string) => {
    const place = placeOf(name);
    if (!place) return;
    const now = where.current;
    if (place === now.place && (sub === undefined || sub === now.sub)) return;
    const next = { place, sub: sub ?? "" };
    window.location.hash = routeHash(next);
    setRoute(next);
  }, []);

  // One press of a desk button: it shows it was pressed, and the answer is
  // Home again — drawn the moment it lands.
  const act = useCallback((b: { act: string; arg?: unknown }): Promise<Acted | null> => {
    acting.current += 1;
    setPressed(`${b.act}:${String(b.arg ?? "")}`);
    return call<Acted>("act", { do: b.act, arg: b.arg ?? null }, 8000)
      .then((r) => {
        lastRead.current = JSON.stringify(r.home);
        setHome(r.home);
        say(r.note);
        return r;
      })
      .catch((e: Error) => {
        say(e.message);
        return null;
      })
      .finally(() => {
        acting.current -= 1;
        setPressed("");
      });
  }, [say]);

  const desk = useMemo<Desk>(() => ({ say, go, act }), [say, go, act]);
  const homeRead = useMemo(() => ({ home, pressed }), [home, pressed]);

  return (
    <DeskContext.Provider value={desk}>
      <HomeContext.Provider value={homeRead}>
        <div className="sky"><i className="indigo" /><i className="blue" /><i className="plum" /><i className="teal" />
          <i className="lamp-light" /><i className="rib r1" /><i className="rib r2" /></div>
        <div className="grain" />
        <TopBar place={route.place} go={go} bar={home?.bar} locked={!!home?.locked} pressed={pressed} act={act} />
        <div className="page">
          {!inDesk() ? <Away place={route.place} text="This page only works inside the desk's window." plain />
            : home?.locked ? <Landing />
            : <PlaceView place={route.place} sub={route.sub} />}
        </div>
        <div className={`toast glass${note || error ? " up" : ""}`}>
          <i className="ic">{IC.info}</i>{note || error}
        </div>
      </HomeContext.Provider>
    </DeskContext.Provider>
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
  place: Place; go: (place: string) => void; bar?: Bar; locked: boolean; pressed: string;
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
