// Home — owned by the Home session (web/README.md). Everything it shows is
// deskweb.Model.home(): the frame polls it every 800 ms for the bar, and
// Home draws the same answer (useHome) — one read for both. A press here
// is the desk's own act(), answered with Home again and drawn at once.
//
// Nothing on Home sends him to the old desk (2026-10-24): the report
// sheet, the account lock's answers, the model / pack / update rows'
// buttons and the sign-in landing are all here. The words are the Tk
// desk's (deskweb.py carries them); the look is design/2026-09-22/rev/home.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { call } from "../bridge";
import { Caps, IC, Segs, useDesk, useHome } from "../kit";
import type { Acted, Button, DayLine, Door, Home, PileRow } from "../types";
import "./home.css";

// ------------------------------------------------- what Home adds to types.ts
// (types.ts is shared and frozen while the places are built; these move
// there at the merge)

/** A button that is a way in rather than a press: "settings/privacy". */
type HomeButton = Button & { go?: string };
type Row = Omit<PileRow, "buttons"> & {
  buttons: HomeButton[];
  /** the recovery key, shown once (lock:fresh) */
  code?: string;
  /** a field in the row: "recovery" on the waiting row */
  field?: string;
};
type Piece = { what: string; size: string };
type Preview = { pieces: Piece[]; row: string; thumb: string };
type ReportView = {
  stage: "write" | "consent" | "sending" | "done";
  attach: string;
  on: string;
  off: string;
  limit: number;
  done: { tone: "ok" | "bad" | "q"; text: string } | null;
  preview: Preview | null;
  consent?: { title: string; lines: { k: string; v: string }[] };
};
type LandingView = { title: string; sentence: string; stored: string; line: string; tone: string };
type HomeMore = Omit<Home, "pile"> & {
  pile: Row[];
  report: ReportView | null;
  report_on: boolean;
  landing: LandingView | null;
};

type Press = (b: HomeButton, rowId?: string) => void;

const HEBREW = /[֐-׿]/;
// a row the press answers leaves at once; the answer redraws the pile
const LEAVES = /^(notify\.dismiss|review\.|consent\.|keys\.later|hardware\.(seen|retry|remove)|lock\.(done|decline))/;

export default function HomePlace({ sub }: { sub: string }) {
  void sub;                                  // Home has no parts
  const { act, go } = useDesk();
  const read = useHome();
  const home = read.home as HomeMore | null;
  const { pressed } = read;
  const [leaving, setLeaving] = useState<Set<string>>(new Set());

  // One press: the row it belongs to leaves at once, the button shows it
  // was pressed, and the answer is Home again — drawn the moment it lands.
  // A button that is a way in (Add a key) goes there instead.
  const press = useCallback<Press>((b, rowId) => {
    if (b.go) {
      const [place = "", part] = b.go.split("/");
      go(place, part);
      return;
    }
    if (rowId && LEAVES.test(b.act)) setLeaving((old) => new Set(old).add(rowId));
    if (b.act === "notify.dismiss_all") {
      setLeaving((old) => {
        const next = new Set(old);
        home?.pile.filter((r) => r.kind === "notify").forEach((r) => next.add(r.id));
        return next;
      });
    }
    act(b).finally(() => setLeaving(new Set()));
  }, [act, go, home]);

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
        {home.report_on ? (
          <div className={`btn bare end report${pressed === "report.open:" ? " down" : ""}`}
               onClick={() => act({ act: "report.open" })}>
            <i className="ic">{IC.warning}</i>Report a problem
          </div>
        ) : null}
        {home.unread ? (
          <div className="dismiss">
            <span className="lnk" onClick={() => press({ act: "notify.dismiss_all", label: "", tone: "quiet" })}>
              Dismiss all
            </span>
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

      {home.report ? <ReportSheet view={home.report} holdKey={home.hold_key} /> : null}
    </div>
  );
}

function Slip({ row, lead, leaving, pressed, act }: {
  row: Row; lead: boolean; leaving: boolean; pressed: string; act: Press;
}) {
  const { say } = useDesk();
  const showNote = !!row.note && row.kind !== "review" && row.kind !== "notify" && !row.field;
  // The recovery key typed into the waiting row goes to Python over the
  // bridge by itself — never through the frame's act(), whose "pressed"
  // mark would carry it as text — and the field is emptied the moment
  // it is sent. Nothing echoes it back.
  const [typed, setTyped] = useState("");
  const recover = () => {
    const key = typed;
    setTyped("");
    call<Acted>("act", { do: "lock.recover", arg: key }, 8000)
      .then((r) => say(r.note))
      .catch((e: Error) => say(e.message));
  };
  return (
    <div className={`slip glass${lead ? " lead" : ""}${leaving ? " leaving" : ""}`
                    + `${showNote || row.field ? " noted" : ""}`}
         title={row.kind === "review" && row.note ? row.note : undefined}>
      <div className={`mk ${row.tone}`}><i className="ic">{IC[row.glyph] ?? IC.info}</i></div>
      <div className="tx">
        <div className="eb"><b>{row.title}</b>{row.meta ? <span>{row.meta}</span> : null}</div>
        <div className={`s${row.rtl ? " he" : ""}`} dir={row.rtl ? "rtl" : "ltr"}>
          {row.code ? <span className="code">{row.code}</span> : null}
          {row.segs ? <Segs segs={row.segs} rtl={row.rtl} /> : row.text}
        </div>
        {showNote ? <div className="nt">{row.note}</div> : null}
        {row.field === "recovery" ? (
          <div className="rk">
            <div className="nt">{row.note}</div>
            <input className="field" value={typed} spellCheck={false} autoComplete="off" autoFocus
                   maxLength={64} placeholder="XXXX-XXXX-XXXX-XXXX-XXXX-XXXX"
                   onChange={(e) => setTyped(e.target.value)}
                   onKeyDown={(e) => { if (e.key === "Enter") recover(); }} />
          </div>
        ) : null}
      </div>
      <div className="acts">
        {row.buttons.map((b) => (row.field === "recovery" && b.act === "lock.recover"
          ? <div key={b.act} className="btn primary" onClick={recover}>{b.label}</div>
          : <SlipButton key={`${b.act}${String(b.arg ?? "")}${b.go ?? ""}`} b={b} row={row}
                        pressed={pressed} act={act} />))}
      </div>
    </div>
  );
}

function SlipButton({ b, row, pressed, act }: { b: HomeButton; row: Row; pressed: string; act: Press }) {
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

// ----------------------------------------------------------- the rest of Home

function Day({ lines, act, go }: { lines: DayLine[]; act: Press; go: (place: string) => void }) {
  return (
    <div className="day">
      <div className="eyebrow">The rest of the day</div>
      <div className="lines">
        {lines.length ? lines.map((l) => (
          <div key={l.label} className="line"
               onClick={() => (l.act ? act({ act: l.act, label: "", tone: "quiet" }) : l.go ? go(l.go) : undefined)}>
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

// ------------------------------------------------------- Report a problem
//
// dashboard._report on a sheet of glass over the dimmed desk (rev/home
// report.png, report-sent.png). The screen was photographed by Python
// before this sheet was drawn. The words are typed here, or dictated:
// the desk is another process than the app, so a dictation made while
// this field has the caret is pasted into it like into any window (the
// Tk desk's report box took it the same way). Enter sends, Shift+Enter
// is a new line, Esc and a click outside cancel (the Tk box's keys).

function ReportSheet({ view, holdKey }: { view: ReportView; holdKey: string }) {
  const { act } = useDesk();
  const { pressed } = useHome();
  const [text, setText] = useState("");
  const [attach, setAttach] = useState(false);
  const [details, setDetails] = useState(false);
  const [closing, setClosing] = useState(false);
  const field = useRef<HTMLTextAreaElement>(null);

  const stage = view.stage;
  const close = useCallback((verb: "report.cancel" | "report.close" | "report.keep") => {
    if (verb !== "report.keep") setClosing(true);
    act({ act: verb }).finally(() => setClosing(false));
  }, [act]);
  const send = useCallback(() => {
    if (pressed.startsWith("report.send:")) return;        // one Send, one report
    act({ act: "report.send", arg: { text, attach } });
  }, [act, text, attach, pressed]);
  const preview = useCallback(() => {
    act({ act: "report.preview", arg: { text, attach } }).then((r) => {
      if (r && !r.note) setDetails(true);
    });
  }, [act, text, attach]);

  // Esc and a click outside the sheet: "never mind" while writing, the
  // answer read while done, and KEEP while it asks — a question walked
  // away from must not turn into an upload (dashboard._report_preview)
  const away = useCallback(() => {
    if (details) return setDetails(false);
    if (stage === "write") return close("report.cancel");
    if (stage === "consent") return close("report.keep");
    return close("report.close");
  }, [details, stage, close]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); away(); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [away]);

  // the field grows with what is in it, three lines to five
  useLayoutEffect(() => {
    const el = field.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.max(81, Math.min(el.scrollHeight, 135))}px`;
  }, [text, stage, details]);
  useEffect(() => {
    if (stage === "write" && !details) field.current?.focus();
  }, [stage, details]);

  if (closing) return null;
  const he = HEBREW.test(text);
  const sending = pressed.startsWith("report.send:") ? " down" : "";

  if (stage === "sending" || stage === "done") {
    const tone = view.done?.tone ?? "q";
    return (
      <>
        <div className="scrim" onClick={away} />
        <div className="sheet done glass">
          <div className="done-row">
            <div className={`mk ${tone}`}>
              <i className={`ic${stage === "sending" ? " turning" : ""}`}>
                {stage === "sending" ? IC.sync : tone === "bad" ? IC.warning : IC.tick}
              </i>
            </div>
            <div className="done-t">{view.done?.text ?? ""}</div>
          </div>
          <div className="sh-acts"><div className="btn" onClick={() => close("report.close")}>Close</div></div>
        </div>
      </>
    );
  }

  if (stage === "consent") {
    const c = view.consent;
    return (
      <>
        <div className="scrim" onClick={away} />
        <div className="sheet write tall glass">
          <div className="sh-eb"><i className="ic">{IC.warning}</i>Report a problem</div>
          <div className="ask">{c?.title ?? "Send problem reports?"}</div>
          <div className="said">Filed on this PC. Sending it asks once:</div>
          <div className="terms">
            {(c?.lines ?? []).map((l) => (
              <div key={l.k} className="term"><span className="k">{l.k}</span><span className="v">{l.v}</span></div>
            ))}
          </div>
          {view.preview ? <Pieces preview={view.preview} /> : null}
          <div className="sh-acts">
            <div className={`btn wide${pressed === "report.keep:" ? " down" : ""}`} onClick={() => close("report.keep")}>
              Keep on this PC
            </div>
            <div className={`btn primary wide${pressed === "report.consent:" ? " down" : ""}`}
                 onClick={() => act({ act: "report.consent" })}>
              <i className="ic">{IC.send}</i>Turn on and send
            </div>
          </div>
        </div>
      </>
    );
  }

  if (details && view.preview) {
    return (
      <>
        <div className="scrim" onClick={away} />
        <div className="sheet write tall glass">
          <div className="sh-eb"><i className="ic">{IC.warning}</i>Report a problem</div>
          <div className="ask small">This is everything that leaves your PC. Nothing else.</div>
          <Pieces preview={view.preview} />
          <div className="eyebrow rowhead">The row</div>
          <pre className="row-json">{view.preview.row}</pre>
          <div className="sh-acts">
            <div className="btn" onClick={() => setDetails(false)}>Back</div>
            <div className={`btn primary${sending}`} onClick={send}><i className="ic">{IC.send}</i>Send</div>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="scrim" onClick={away} />
      {/* a press anywhere on the sheet but the field leaves the caret in
          the field: the switch flipped, he holds the key and speaks — and
          the paste must land where he was writing, not on the page */}
      <div className="sheet write glass"
           onMouseDown={(e) => { if (e.target !== field.current) e.preventDefault(); }}>
        <div className="sh-eb"><i className="ic">{IC.warning}</i>Report a problem</div>
        <div className="ask">What went wrong?</div>
        <div className="well">
          <textarea ref={field} className={`typed${he ? " he" : ""}`} dir="auto" value={text}
                    maxLength={view.limit} spellCheck={false}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                        e.preventDefault();
                        send();
                      }
                    }} />
        </div>
        <div className="hint">
          {holdKey !== "off" ? <>Type it, or hold<Caps caps={[holdKey]} />and say it.</> : "Type it."}
        </div>
        {view.attach ? (
          <div className="att" onClick={() => setAttach((v) => !v)}>
            <span className={`sw${attach ? " on" : ""}`}><i /></span>
            <div>
              <div className="att-t">{view.attach}</div>
              <div className="att-n">{attach ? view.on : view.off}</div>
            </div>
          </div>
        ) : <div className="att-n alone">{view.off}</div>}
        <div className="sh-acts">
          <div className={`btn bare more${pressed === "report.preview:[object Object]" ? " down" : ""}`}
               onClick={preview}>
            <i className="ic">{IC.eye}</i>Preview
          </div>
          <div className="btn" onClick={() => close("report.cancel")}>Cancel</div>
          <div className={`btn primary${sending}`} onClick={send}><i className="ic">{IC.send}</i>Send</div>
        </div>
      </div>
    </>
  );
}

/** What would leave, in plain words with a size each; the picture small. */
function Pieces({ preview }: { preview: Preview }) {
  return (
    <div className="pieces">
      {preview.thumb ? <img className="thumb" src={preview.thumb} alt="" /> : null}
      <div className="plist">
        {preview.pieces.map((p) => (
          <div key={p.what} className="piece"><span className="w">{p.what}</span><span className="z num">{p.size}</span></div>
        ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------ the landing

/** The sign-in landing (dashboard._landing / _screen_landing): the frame
 *  draws it instead of every place while there is no account on this PC,
 *  and takes the places off the bar. One card, one way in — through the
 *  running app, or in this window when nothing runs. */
export function Landing() {
  const { act } = useDesk();
  const read = useHome();
  const home = read.home as HomeMore | null;
  const land = home?.landing;
  const pressed = read.pressed === "landing.signin:";
  return (
    <div className="place-home">
      <div className="landing glass">
        <div className="lmark">
          <svg width="56" height="56" viewBox="0 0 64 64">
            <rect width="64" height="64" rx="14" fill="#1c2143" />
            <path d="M10 14H30A20 20 0 0 1 50 34V54" stroke="var(--ink)" strokeWidth="8" fill="none" />
            <circle cx="30" cy="34" r="10" fill="var(--mark-lamp)" />
          </svg>
          <div className="lname">{land?.title ?? "DeskIT"}</div>
        </div>
        <div className="lsent">{land?.sentence ?? ""}</div>
        <div className="lonce">Sign in once; this PC remembers you until you sign out.</div>
        <div className={`btn primary lgo${pressed ? " down" : ""}`} onClick={() => act({ act: "landing.signin" })}>
          Sign in with Google
        </div>
        <div className={`lline ${land?.tone ?? ""}`}>{land?.line ?? ""}</div>
        <div className="lstored">{land?.stored ?? ""}</div>
      </div>
    </div>
  );
}
