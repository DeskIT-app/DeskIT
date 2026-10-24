// Home — owned by the Home session (web/README.md). Everything it shows is
// deskweb.Model.home(): the frame polls it every 800 ms for the bar, and
// Home draws the same answer (useHome) — one read for both. A press here
// is the desk's own act(), answered with Home again and drawn at once.
import { useCallback, useEffect, useState } from "react";
import { Caps, IC, Segs, useDesk, useHome } from "../kit";
import type { Button, DayLine, Door, PileRow } from "../types";
import "./home.css";

type Press = (b: { act: string; arg?: unknown }, rowId?: string) => void;

export default function HomePlace({ sub }: { sub: string }) {
  void sub;                                  // Home has no parts yet
  const { act, go } = useDesk();
  const { home, pressed } = useHome();
  const [leaving, setLeaving] = useState<Set<string>>(new Set());

  // One press: the row it belongs to leaves at once, the button shows it
  // was pressed, and the answer is Home again — drawn the moment it lands.
  const press = useCallback<Press>((b, rowId) => {
    const goes = rowId && /^(notify\.dismiss|review\.|consent\.|keys\.later|hardware\.seen)/.test(b.act);
    if (goes && rowId) setLeaving((old) => new Set(old).add(rowId));
    if (b.act === "notify.dismiss_all") {
      setLeaving((old) => {
        const next = new Set(old);
        home?.pile.filter((r) => r.kind === "notify").forEach((r) => next.add(r.id));
        return next;
      });
    }
    act(b).finally(() => setLeaving(new Set()));
  }, [act, home]);

  const calm = !!home && home.pile.length === 0;
  useEffect(() => {
    document.body.classList.toggle("home-calm", calm);
  }, [calm]);
  useEffect(() => () => document.body.classList.remove("home-calm"), []);

  if (!home) return null;
  return (
    <div className="place-home">
      <div className="head">
        <div className="title">{home.head}</div>
        <div className="sub">{home.sub}</div>
        {home.unread ? (
          <div className="dismiss">
            <span className="lnk" onClick={() => press({ act: "notify.dismiss_all" })}>Dismiss all</span>
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
                    pressed={pressed} act={press} />
            ))}
          </div>
        )}
        {home.held ? <div className="held">{home.held}</div> : null}
        <Day lines={home.rest} act={press} go={go} />
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
    </div>
  );
}

function Slip({ row, lead, leaving, pressed, act }: {
  row: PileRow; lead: boolean; leaving: boolean; pressed: string; act: Press;
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

function SlipButton({ b, row, pressed, act }: { b: Button; row: PileRow; pressed: string; act: Press }) {
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

function Day({ lines, act, go }: { lines: DayLine[]; act: Press; go: (place: string) => void }) {
  return (
    <div className="day">
      <div className="eyebrow">The rest of the day</div>
      <div className="lines">
        {lines.length ? lines.map((l) => (
          <div key={l.label} className="line"
               onClick={() => (l.act ? act({ act: l.act }) : l.go ? go(l.go) : undefined)}>
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

function DoorTile({ door, go }: { door: Door; go: (place: string) => void }) {
  return (
    <div className={`door${door.n ? "" : " z"}`} onClick={() => go(door.place)}>
      <div className="top"><span className="n num">{door.n}</span><span className="w">{door.w}</span></div>
      <i className="ic dic">{IC[door.glyph] ?? IC.info}</i>
      <div className="note">{door.note}</div>
    </div>
  );
}

/** The sign-in landing: the frame draws it instead of every place while
 *  the account lock holds (home.locked), and hides the places on the bar.
 *  Home's to build; signing in is still in the old desk. */
export function Landing() {
  const { act } = useDesk();
  return (
    <div className="place-home">
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
    </div>
  );
}
