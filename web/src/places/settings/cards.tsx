// The cards of a Settings tab that are not rows of the file — the Tk
// desk's blocks (dashboard._dot_block, _updates_block, _awake_block, ...),
// each drawn from what desk_settings answers.
import { useEffect, useRef } from "react";
import { Menu, RowView, Sw, keyOf } from "./controls";
import { GLYPHS, type Btn, type KeyRow, type Press, type Section } from "./model";

const ic = (name: string) => GLYPHS[name] ?? "";

type Go = (sub: string) => void;
type Props = { s: Section; press: Press; pressed: string; go: Go };

function Buttons({ list, press, pressed, go, className }: {
  list: Btn[]; press: Press; pressed: string; go: Go; className?: string;
}) {
  if (!list.length) return null;
  return (
    <div className={`ctls${className ? ` ${className}` : ""}`}>
      {list.map((b) => {
        const k = b.do ? keyOf(b.do, b.arg) : `go:${b.go ?? ""}`;
        return (
          <div key={`${b.label}${k}`} className={`btn${b.primary ? " primary" : ""}${pressed === k ? " down" : ""}`}
               onClick={() => (b.go ? go(b.go) : b.do ? void press({ do: b.do, arg: b.arg }, k) : undefined)}>
            {b.label}
          </div>
        );
      })}
    </div>
  );
}

export function Card({ s, press, pressed, go }: Props) {
  switch (s.kind) {
    case "rows":
      return (
        <div className="card glass">
          {s.rows.map((r) => <RowView key={r.path} row={r} press={press} pressed={pressed} />)}
        </div>
      );
    case "dot":
      return <DotCard s={s} press={press} pressed={pressed} />;
    case "updates":
      return (
        <div className="card glass">
          <div className="r">
            <div className="t">
              <div className="status">{s.fresh ? <span className="okdot" /> : <span className="okdot idle" />}{s.line}</div>
            </div>
            <Buttons list={s.buttons} press={press} pressed={pressed} go={go} className="ctl" />
          </div>
          {s.row ? <RowView row={s.row} press={press} pressed={pressed} /> : null}
        </div>
      );
    case "awake":
      return <AwakeCard s={s} press={press} pressed={pressed} />;
    case "model":
      return (
        <div className="card glass pad">
          {s.lines.map((l) => (
            <div key={l.name} className="kv"><span className="k">{l.name}</span><span className="v">{l.text}</span></div>
          ))}
          <Buttons list={s.buttons} press={press} pressed={pressed} go={go} className="under" />
        </div>
      );
    case "line":
      return (
        <div className="card glass">
          <div className="r">
            <div className="t">
              <div className={`lab${s.tone ? ` ${s.tone}` : ""}`}>
                {s.ready ? <span className="okdot" /> : null}{s.line}
              </div>
              {s.small ? <div className="help">{s.small}</div> : null}
            </div>
            <Buttons list={s.buttons} press={press} pressed={pressed} go={go} className="ctl" />
          </div>
        </div>
      );
    case "switch": {
      const k = keyOf(s.do, "");
      return (
        <div className="card glass">
          <div className="r">
            <div className="t">
              <div className="lab">{s.label}</div>
              <div className={`help${s.tone === "warn" ? " warn" : ""}`}>{s.help}</div>
              {s.buttons && s.buttons.length
                ? <Buttons list={s.buttons} press={press} pressed={pressed} go={go} className="under" /> : null}
            </div>
            <div className="ctl">
              <Sw on={s.on} busy={pressed === k} label={s.label} onFlip={(v) => void press({ do: s.do, arg: v }, k)} />
            </div>
          </div>
        </div>
      );
    }
    case "sounds":
      return (
        <div className="card glass pad">
          <div className="head-row">
            <div className={`btn${pressed === keyOf("notify.test", "") ? " down" : ""}`}
                 onClick={() => void press({ do: "notify.test" }, keyOf("notify.test", ""))}>
              <i className="ic">{ic("bell")}</i>{s.test}
            </div>
          </div>
          <div className="cues">
            {s.cues.map((c) => (
              <div key={c.kind} className="cue" onClick={() => void press({ do: "cue.play", arg: c.kind }, keyOf("cue.play", c.kind))}>
                <span className={`play${pressed === keyOf("cue.play", c.kind) ? " down" : ""}`}><i className="ic">{ic("play")}</i></span>
                <span className="w">{c.label}</span>
              </div>
            ))}
          </div>
        </div>
      );
    case "phone":
      return (
        <div className="card glass">
          <div className="r">
            <div className="t">
              <div className={`url${s.url ? "" : " none"}`}>{s.url || s.none}</div>
              <div className="help">{s.said}</div>
            </div>
            <div className="ctl">
              <div className={`btn${pressed === keyOf("phone.copy", "") ? " down" : ""}`}
                   onClick={() => void press({ do: "phone.copy" }, keyOf("phone.copy", ""))}>
                <i className="ic">{ic("link")}</i>Copy link
              </div>
            </div>
          </div>
        </div>
      );
    case "lines":
      return <LinesCard s={s} press={press} pressed={pressed} go={go} />;
    case "keys":
      return <KeysCard s={s} press={press} pressed={pressed} go={go} />;
    case "version":
      return (
        <div className="card glass pad version">
          <div className="t">
            <div className="hl">{s.name}</div>
            <div className="mt">{s.line}</div>
            <div className="help">{s.machine}</div>
          </div>
          <div className="side">
            <div className={`btn${pressed === keyOf("quit", "") ? " down" : ""}`}
                 onClick={() => void press({ do: "quit" }, keyOf("quit", ""))}>
              <i className="ic">{ic("stop")}</i>{s.quit}
            </div>
            <div className="note">{s.quit_line}</div>
            <div className={`btn${pressed === keyOf("tour", "") ? " down" : ""}`}
                 onClick={() => void press({ do: "tour" }, keyOf("tour", ""))}>{s.tour}</div>
          </div>
        </div>
      );
    case "about":
      return (
        <div className="card glass pad">
          <div className="lab">{s.line}</div>
          <div className="help link" onClick={() => void press({ do: "url", arg: "model" })}>{s.model}</div>
          <div className="ctls papers">
            {s.papers.map((p) => (
              <div key={p} className={`btn${pressed === keyOf("paper", p) ? " down" : ""}`}
                   onClick={() => void press({ do: "paper", arg: p }, keyOf("paper", p))}>{p}</div>
            ))}
          </div>
        </div>
      );
    case "files":
      return (
        <div className="card glass">
          {s.rows.map((f) => (
            <div key={f.file} className="r">
              <i className="ic fglyph">{ic(f.glyph)}</i>
              <div className="t">
                <div className="lab">{f.name}</div>
                <div className="help">{f.hint}</div>
              </div>
              <div className="ctl">
                <div className={`btn${pressed === keyOf("file.open", f.file) ? " down" : ""}`}
                     onClick={() => void press({ do: "file.open", arg: f.file }, keyOf("file.open", f.file))}>Open</div>
              </div>
            </div>
          ))}
        </div>
      );
    default:
      return null;
  }
}

/** The dot: a little screen with the real dot in its corner, lit the way
 *  the real one is; where it is; the corner menu; Move the dot. */
function DotCard({ s, press, pressed }: { s: Extract<Section, { kind: "dot" }>; press: Press; pressed: string }) {
  const row = s.row;
  const spot = s.moved ? " free" : s.corner_at === "top-right" ? " tr" : " br";
  return (
    <div className="card glass dot">
      <div className="scr"><span className={`d${spot}${s.live ? "" : " off"}`} /></div>
      <div className="t">
        <div className={`hl${s.live ? "" : " faint"}`}>{s.where}</div>
        <div className="help">{s.said}</div>
        <div className="ctls">
          {row && row.ctl === "menu" ? (
            <>
              <span className="lbl">Corner</span>
              <Menu value={String(row.value ?? "")} options={row.options ?? []} width={172} label={row.label}
                    onPick={(v) => void press({ do: "set", arg: { path: row.path, value: v } }, keyOf("set", row.path))} />
            </>
          ) : null}
          <div className={`btn primary mv${s.move ? "" : " dis"}${pressed === keyOf("dot.move", "") ? " down" : ""}`}
               onClick={() => s.move && void press({ do: "dot.move" }, keyOf("dot.move", ""))}>Move the dot</div>
          <div className={`btn${s.home ? "" : " dis"}${pressed === keyOf("dot.corner", "") ? " down" : ""}`}
               onClick={() => s.home && void press({ do: "dot.corner" }, keyOf("dot.corner", ""))}>Back to the corner</div>
        </div>
      </div>
    </div>
  );
}

/** Awake: the hero (the hold, and what one press does), the strip of
 *  buttons, and the check's answer — every reason a machine that is awake
 *  could still be out of reach, a row each. */
function AwakeCard({ s, press, pressed }: { s: Extract<Section, { kind: "awake" }>; press: Press; pressed: string }) {
  const tk = keyOf("awake.screens", "toggle");
  const ag = keyOf("awake.screens", "again");
  // the check runs by itself when the card first opens, as the Tk
  // desk's does: a machine that would not stay reachable is found now
  const asked = useRef(false);
  useEffect(() => {
    if (asked.current || s.probed || s.probing) return;
    asked.current = true;
    void press({ do: "awake.check" }, keyOf("awake.check", ""));
  }, [s.probed, s.probing, press]);
  return (
    <div className="card glass">
      <div className="hero">
        <div className={`moon ${s.tone}`}><i className="ic">{ic("moon")}</i></div>
        <div className="t">
          <div className="st">{s.state}</div>
          <div className="mt num">{s.meta}</div>
          <div className="help">{s.hint}</div>
        </div>
      </div>
      <div className="strip">
        <div className={`btn${s.live ? "" : " dis"}${pressed === tk ? " down" : ""}`}
             onClick={() => s.live && void press({ do: "awake.screens", arg: "toggle" }, tk)}>
          <i className="ic">{ic(s.toggle === "Screens on" ? "sun" : "moon")}</i>{s.toggle}
        </div>
        <div className={`btn${s.live ? "" : " dis"}${pressed === ag ? " down" : ""}`}
             onClick={() => s.live && void press({ do: "awake.screens", arg: "again" }, ag)}>
          <i className="ic">{ic("power")}</i>Screens off again
        </div>
        <div className={`btn bare${s.probing ? " dis" : ""}`}
             onClick={() => !s.probing && void press({ do: "awake.check" }, keyOf("awake.check", ""))}>
          <i className="ic">{ic("tick")}</i>Check status
        </div>
        <span className="note num">{s.checked}</span>
      </div>
      <div className="check">
        <div className="ttl">Will it still be there when you are away</div>
        {s.probed ? s.rows.map((r) => (
          <div key={r.label} className="cr"><span className={`dt ${r.tone}`} /><span className="k">{r.label}</span><span className="v">{r.text}</span></div>
        )) : <div className="intro">{s.intro}</div>}
      </div>
    </div>
  );
}

/** A card that is a line or two that follow the app — the account, the
 *  lock, every connection — and the buttons the state earns. The lock
 *  card's recovery field takes the key straight to the press and keeps
 *  no copy of it. */
function LinesCard({ s, press, pressed, go }: { s: Extract<Section, { kind: "lines" }> } & Omit<Props, "s">) {
  const field = useRef<HTMLInputElement>(null);
  const recover = () => {
    const el = field.current;
    const key = el ? el.value : "";
    if (el) el.value = "";
    void press({ do: "lock.recover", arg: { key } }, keyOf("lock.recover", ""));
  };
  return (
    <div className="card glass pad">
      <div className={`lab big${s.tone ? ` ${s.tone}` : ""}`}>{s.line}</div>
      {s.code ? <div className="code num">{s.code}</div> : null}
      {s.sub ? <div className="help">{s.sub}</div> : null}
      {s.typing ? (
        <div className="field wide">
          <input ref={field} type="password" autoComplete="off" spellCheck={false} placeholder={s.placeholder}
                 aria-label={s.placeholder} maxLength={80}
                 onKeyDown={(e) => { if (e.key === "Enter") recover(); }} />
        </div>
      ) : null}
      <div className="ctls under">
        {s.buttons.map((b) => {
          if (b.do === "lock.recover") {
            return <div key="recover" className={`btn${pressed === keyOf("lock.recover", "") ? " down" : ""}`} onClick={recover}>{b.label}</div>;
          }
          const k = b.do ? keyOf(b.do, b.arg) : `go:${b.go ?? ""}`;
          return (
            <div key={`${b.label}${k}`} className={`btn${pressed === k ? " down" : ""}`}
                 onClick={() => (b.go ? go(b.go) : b.do ? void press({ do: b.do, arg: b.arg }, k) : undefined)}>
              {b.label}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** YOUR CLOUD KEYS: a row per provider (keyrow.KeyRow). A saved key is a
 *  fixed row of dots, never the key; the field takes a paste and hands it
 *  to the press, and is emptied the same instant — nothing on this page
 *  keeps it. */
function KeysCard({ s, press, pressed }: { s: Extract<Section, { kind: "keys" }> } & Omit<Props, "s">) {
  if (s.loading) return <div className="card glass pad"><div className="help">…</div></div>;
  return (
    <div className="card glass keyrows">
      {s.rows.map((k) => <KeyLine key={k.name} k={k} press={press} pressed={pressed} />)}
    </div>
  );
}

function KeyLine({ k, press, pressed }: { k: KeyRow; press: Press; pressed: string }) {
  const field = useRef<HTMLInputElement>(null);
  const open = k.state === "open" || k.state === "changing";
  const save = () => {
    const el = field.current;
    const value = el ? el.value : "";
    if (el) el.value = "";
    void press({ do: "key.save", arg: { name: k.name, value } }, keyOf("key.save", k.name));
  };
  return (
    <div className="kr">
      <div className="khead">
        <span className="kname">{k.label}</span>
        <span className="link" onClick={() => void press({ do: "url", arg: k.name })}>Get a free key</span>
      </div>
      <div className="why">{k.why}</div>
      <div className="kline">
        <div className={`field key${open ? "" : " locked"}`}>
          <i className="ic">{ic("key")}</i>
          {open ? (
            <input ref={field} type="password" autoComplete="off" spellCheck={false} placeholder={k.placeholder}
                   aria-label={k.placeholder}
                   onKeyDown={(e) => { if (e.key === "Enter") save(); }} />
          ) : <span className="v dots">{k.dots}</span>}
        </div>
        {k.buttons.map((b) => {
          const kk = keyOf(b.do, k.name);
          return (
            <div key={b.do} className={`btn${b.primary ? " primary" : ""}${pressed === kk ? " down" : ""}`}
                 onClick={() => (b.do === "key.save" ? save() : void press({ do: b.do, arg: { name: k.name } }, kk))}>
              {b.label}
            </div>
          );
        })}
        <div className={`btn${pressed === keyOf("key.remove", k.name) ? " down" : ""}`}
             onClick={() => void press({ do: "key.remove", arg: { name: k.name } }, keyOf("key.remove", k.name))}>Remove</div>
      </div>
      {k.say ? <div className={`ksay ${k.tone}`}>{k.say}</div> : null}
      <div className="store">{k.storage}</div>
    </div>
  );
}
