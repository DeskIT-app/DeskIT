// The controls a Settings line is drawn with (dashboard._control): a
// switch, a menu, a field, a folder with Browse…, a consent row, "In the
// file". Each one says it was pressed the frame it is pressed; the answer
// is the place again, drawn from the truth.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { GLYPHS, type Press, type Row } from "./model";

const ic = (name: string) => GLYPHS[name] ?? "";

/** The pressed key of a button: what it does and on what. */
export function keyOf(doName: string, arg?: unknown): string {
  return `${doName}:${typeof arg === "string" ? arg : JSON.stringify(arg ?? "")}`;
}

/** A switch: no accent — a soft lavender-grey track when on, a hollow
 *  ring when off (the approved picture). It moves the moment it is
 *  pressed; the answer puts it where the file says. */
export function Sw({ on, onFlip, busy, label }: {
  on: boolean; onFlip: (v: boolean) => void; busy?: boolean; label: string;
}) {
  const [shown, setShown] = useState(on);
  useEffect(() => setShown(on), [on]);
  return (
    <span className={`sw${shown ? " on" : ""}${busy ? " busy" : ""}`} role="switch"
          aria-checked={shown} aria-label={label} tabIndex={0}
          onClick={() => { setShown(!shown); onFlip(!shown); }}
          onKeyDown={(e) => {
            if (e.key === " " || e.key === "Enter") {
              e.preventDefault();
              setShown(!shown);
              onFlip(!shown);
            }
          }}>
      <i />
    </span>
  );
}

/** A menu: the pill with the value on it, and its choices on a pane of
 *  frost that opens under it — the window's own, never the system's. */
export function Menu({ value, options, onPick, width, glyph, label }: {
  value: string; options: { v: string; label: string }[]; onPick: (v: string) => void;
  width: number; glyph?: string; label: string;
}) {
  const pill = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [at, setAt] = useState({ left: 0, top: 0, width });
  const [lit, setLit] = useState(-1);
  const litRef = useRef(-1);
  litRef.current = lit;
  const [held, setHeld] = useState(value);
  useEffect(() => setHeld(value), [value]);
  const current = options.find((o) => o.v === held);

  useLayoutEffect(() => {
    if (!open || !pill.current) return;
    const r = pill.current.getBoundingClientRect();
    const w = Math.max(r.width, width);
    const room = window.innerHeight - r.bottom - 12;
    const tall = Math.min(options.length * 34 + 12, 320);
    const top = room >= tall ? r.bottom + 6 : Math.max(12, r.top - 6 - tall);
    setAt({ left: Math.min(r.right - w, window.innerWidth - w - 12), top, width: w });
    setLit(options.findIndex((o) => o.v === held));
  }, [open, options, held, width]);

  useEffect(() => {
    if (!open) return undefined;
    const shut = (e: Event) => {
      if (e.type === "keydown") {
        const k = (e as KeyboardEvent).key;
        if (k === "Escape") setOpen(false);
        else if (k === "ArrowDown") setLit((i) => Math.min(options.length - 1, i + 1));
        else if (k === "ArrowUp") setLit((i) => Math.max(0, i - 1));
        else if (k === "Enter") {
          const o = options[litRef.current];
          if (o) { setHeld(o.v); if (o.v !== value) onPick(o.v); }
          setOpen(false);
        } else return;
        e.preventDefault();
        return;
      }
      const t = e.target as Node | null;
      if (t && (pill.current?.contains(t) || document.querySelector(".place-settings .pop")?.contains(t))) return;
      setOpen(false);
    };
    const scroll = (e: Event) => {
      const t = e.target as Node | null;
      if (t && document.querySelector(".place-settings .pop")?.contains(t)) return;
      setOpen(false);
    };
    window.addEventListener("mousedown", shut, true);
    window.addEventListener("keydown", shut, true);
    window.addEventListener("scroll", scroll, true);
    window.addEventListener("blur", shut);
    return () => {
      window.removeEventListener("mousedown", shut, true);
      window.removeEventListener("keydown", shut, true);
      window.removeEventListener("scroll", scroll, true);
      window.removeEventListener("blur", shut);
    };
  }, [open, options, onPick, value]);

  return (
    <>
      <div ref={pill} className={`menu${open ? " open" : ""}`} style={{ width }} tabIndex={0}
           role="button" aria-haspopup="listbox" aria-label={label}
           onClick={() => setOpen(!open)}
           onKeyDown={(e) => { if (!open && (e.key === "Enter" || e.key === " " || e.key === "ArrowDown")) { e.preventDefault(); setOpen(true); } }}>
        {glyph ? <i className="ic lead">{ic(glyph)}</i> : null}
        <span className="v">{current ? current.label : held}</span>
        <i className="ic">{ic("down")}</i>
      </div>
      {open ? createPortal(
        <div className="place-settings">
          <div className="pop glass" role="listbox" style={{ left: at.left, top: at.top, width: at.width }}>
            {options.map((o, i) => (
              <div key={o.v} role="option" aria-selected={o.v === held}
                   className={`opt${o.v === held ? " on" : ""}${i === lit ? " lit" : ""}`}
                   onMouseEnter={() => setLit(i)}
                   onClick={() => { setHeld(o.v); setOpen(false); if (o.v !== value) onPick(o.v); }}>
                <span className="v">{o.label}</span>
                {o.v === held ? <i className="ic">{ic("tick")}</i> : null}
              </div>
            ))}
          </div>
        </div>, document.body) : null}
    </>
  );
}

/** A field: a line of plain text, written when Enter is pressed or the
 *  caret leaves it, and only if it changed (dashboard._entry_done). */
export function TextField({ value, onDone, width, num, label }: {
  value: string; onDone: (v: string) => void; width: number; num?: boolean; label: string;
}) {
  const [text, setText] = useState(value);
  const focused = useRef(false);
  useEffect(() => { if (!focused.current) setText(value); }, [value]);
  const done = () => {
    focused.current = false;
    if (text.trim() !== value.trim()) onDone(text);
    else setText(value);
  };
  return (
    <div className="field" style={{ width }}>
      <input className={num ? "num" : ""} value={text} spellCheck={false} autoComplete="off"
             aria-label={label} dir="auto" maxLength={300}
             onFocus={() => { focused.current = true; }}
             onChange={(e) => setText(e.target.value)}
             onBlur={done}
             onKeyDown={(e) => {
               if (e.key === "Enter") (e.target as HTMLInputElement).blur();
               if (e.key === "Escape") { setText(value); focused.current = false; (e.target as HTMLInputElement).blur(); }
             }} />
    </div>
  );
}

/** One line of a group's card: its plain label, its one sentence, and
 *  its control on the right. */
export function RowView({ row, press, pressed }: { row: Row; press: Press; pressed: string }) {
  const set = (value: unknown) => press({ do: "set", arg: { path: row.path, value } }, keyOf("set", row.path));
  const busy = pressed === keyOf("set", row.path);
  let control = null;
  if (row.ctl === "switch") {
    control = <Sw on={row.value === true} busy={busy} label={row.label} onFlip={(v) => void set(v)} />;
  } else if (row.ctl === "menu") {
    const mic = row.path === "audio.device";
    control = <Menu value={String(row.value ?? "")} options={row.options ?? []} width={mic ? 304 : 236}
                    glyph={mic ? "mic" : undefined} label={row.label} onPick={(v) => void set(v)} />;
  } else if (row.ctl === "field") {
    control = <TextField value={String(row.value ?? "")} num={row.num} width={row.num ? 120 : 236}
                         label={row.label} onDone={(v) => void set(v)} />;
  } else if (row.ctl === "folder") {
    const down = pressed === keyOf("browse", row.path) ? " down" : "";
    control = (
      <>
        <div className="field folder" title={String(row.value ?? "")}>
          <i className="ic">{ic("folder")}</i><span className="v">{String(row.value ?? "")}</span>
        </div>
        <div className={`btn${down}`} onClick={() => void press({ do: "browse", arg: row.path }, keyOf("browse", row.path))}>
          Browse…
        </div>
      </>
    );
  } else if (row.ctl === "consent" && row.consent) {
    const c = row.consent;
    const b = c.button;
    control = (
      <>
        <span className={`consent ${c.tone}`}>{c.text}</span>
        {b ? (
          <div className={`btn${pressed === keyOf(b.do, b.arg) ? " down" : ""}`}
               onClick={() => void press({ do: b.do, arg: b.arg }, keyOf(b.do, b.arg))}>{b.label}</div>
        ) : null}
      </>
    );
  } else if (row.ctl === "file") {
    control = (
      <div className="btn" onClick={() => void press({ do: "file.open", arg: null })}>
        <i className="ic">{ic("settings")}</i>In the file
      </div>
    );
  }
  return (
    <div className="r" data-path={row.path}>
      <div className="t">
        <div className="lab"><Label text={row.label} /></div>
        {row.help ? <div className="help">{row.help}</div> : null}
      </div>
      <div className="ctl">{control}</div>
    </div>
  );
}

/** "Mark the cursor with … while it listens": the marker as the keycap
 *  the approved picture draws it in. */
function Label({ text }: { text: string }) {
  const at = text.indexOf("…");
  if (at < 0) return <>{text}</>;
  return <>{text.slice(0, at)}<span className="cap">…</span>{text.slice(at + 1)}</>;
}
