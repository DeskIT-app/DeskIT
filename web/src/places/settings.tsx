// Settings — owned by the Settings session (web/README.md): this file, the
// files under ./settings/, settings.css, desk_settings*.py and the Settings
// section of tests.py. The forty-odd lines of defaults.toml a person
// changes, on eight tabs, each in Dashboard.LAYOUT's order with the cards
// between them (dashboard._screen_settings); a tab is the route's sub —
// #/settings/privacy — and #/settings/network is the Network screen
// behind EVERY CONNECTION. Every tab comes in ONE answer
// (desk_settings.Place.read), so a tab switch asks Python nothing; a
// press is placeCall("settings", "act", {do, arg}) and is answered with
// the place again, drawn the moment it lands.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { IC, Seg, placeCall, useDesk, usePlace } from "../kit";
import { Card } from "./settings/cards";
import { RowView } from "./settings/controls";
import type { Acted, Answer, Found, Press, Section } from "./settings/model";
import { NetworkScreen } from "./settings/network";
import "./settings.css";

const POLL_MS = 1000;
const SEARCH_MS = 160;                 // dashboard.SEARCH_MS
/** A press that waits on a person (a folder dialog) may take minutes. */
const LONG_MS: Record<string, number> = { browse: 15 * 60 * 1000 };

// The last answer and the last note this window has seen: back on
// Settings, the tab is drawn at once from it while the read is on its way,
// and a note already shown is not shown again.
let kept: Answer | null = null;
let noteSeen = -1;

export default function SettingsPlace({ sub }: { sub: string }) {
  const { say, go } = useDesk();
  const { data, reload } = usePlace<Answer>("settings", {}, POLL_MS);
  const answer = data ?? kept;
  if (data) kept = data;
  const [pressed, setPressed] = useState("");
  const [searching, setSearching] = useState(false);
  const list = useRef<HTMLDivElement>(null);

  const slugs = answer?.tabs.map((t) => t.slug) ?? [];
  const network = sub === "network";
  const tab = slugs.includes(sub) ? sub : "general";

  // the sky, placed for Settings (the approved picture's own placement)
  useEffect(() => {
    document.body.classList.add("settings-on");
    return () => document.body.classList.remove("settings-on");
  }, []);

  // a note the place has for the toast: a check that finished, a key the
  // provider answered, the dot back where it was dropped
  useEffect(() => {
    if (!answer) return;
    if (noteSeen < 0) noteSeen = answer.note.id;
    else if (answer.note.id > noteSeen) {
      noteSeen = answer.note.id;
      say(answer.note.text);
    }
  }, [answer, say]);

  // the slow half of a first look is still coming: ask again soon
  useEffect(() => {
    if (!data?.warming) return undefined;
    const t = window.setTimeout(() => reload(), 200);
    return () => window.clearTimeout(t);
  }, [data, reload]);

  useLayoutEffect(() => { list.current?.scrollTo({ top: 0 }); }, [tab, network, searching]);

  const press = useCallback<Press>((b, key) => {
    const k = key ?? b.do;
    setPressed(k);
    return placeCall<Acted>("settings", "act", { do: b.do, arg: b.arg ?? null }, LONG_MS[b.do] ?? 8000)
      .then((r) => {
        if (r.place) reload(r.place);
        if (r.note) say(r.note);
      })
      .catch((e: Error) => {
        say(e.message);
        reload();
      })
      .finally(() => setPressed((now) => (now === k ? "" : now)));
  }, [reload, say]);

  const toTab = useCallback((slug: string) => go("settings", slug), [go]);

  if (network) {
    return (
      <div className="place-settings">
        <NetworkScreen back={() => toTab("privacy")} />
      </div>
    );
  }
  return (
    <div className="place-settings">
      <div className="head">
        <div className="title">Settings</div>
        <div className="saved"><i className="ic">{IC.tick}</i>{answer?.saved ?? ""}</div>
        {searching ? (
          <Search close={() => setSearching(false)} />
        ) : (
          <Tabs tabs={answer?.tabs ?? []} on={tab} pick={toTab} />
        )}
        {searching ? null : (
          <div className="find" role="button" aria-label="Search the settings" tabIndex={0}
               onClick={() => setSearching(true)}
               onKeyDown={(e) => { if (e.key === "Enter") setSearching(true); }}>
            <i className="ic">{IC.search}</i>
          </div>
        )}
      </div>
      <div className="list" ref={list}>
        {searching ? <Found press={press} pressed={pressed} go={toTab} /> : (
          (answer?.pages[tab] ?? []).map((s) => (
            <Sec key={s.id} s={s} press={press} pressed={pressed} go={toTab} />
          ))
        )}
      </div>
    </div>
  );
}

function Sec({ s, press, pressed, go }: { s: Section; press: Press; pressed: string; go: (sub: string) => void }) {
  return (
    <div className={`sec k-${s.kind}`} data-id={s.id}>
      <div className="name"><i className="ic">{IC[s.glyph] ?? IC.settings}</i>{s.title}</div>
      <Card s={s} press={press} pressed={pressed} go={go} />
    </div>
  );
}

/** The eight tabs on a track of their own, with ONE bubble that slides to
 *  the lit tab — the bar's way (the kit's Seg), never a jump. */
function Tabs({ tabs, on, pick }: { tabs: { name: string; slug: string }[]; on: string; pick: (s: string) => void }) {
  return (
    <div className="tabs">
      <Seg tabs items={tabs.map((t) => ({ key: t.slug, name: t.name }))} on={on} pick={pick} />
    </div>
  );
}

// ------------------------------------------------------------- the search

let query = "";

/** The magnifier's field, where the tabs were: a word from a setting's
 *  name, its sentence or the file's own comment — Esc brings the tabs back. */
function Search({ close }: { close: () => void }) {
  const [text, setText] = useState(query);
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => { field.current?.focus(); }, []);
  useEffect(() => {
    const t = window.setTimeout(() => {
      query = text;
      window.dispatchEvent(new Event("settings-query"));
    }, SEARCH_MS);
    return () => window.clearTimeout(t);
  }, [text]);
  const done = () => {
    query = "";
    window.dispatchEvent(new Event("settings-query"));
    close();
  };
  return (
    <div className="searchbox">
      <i className="ic">{IC.search}</i>
      <input ref={field} value={text} spellCheck={false} autoComplete="off" dir="auto"
             aria-label="Search the settings" maxLength={120}
             placeholder="a word from a setting's name, its sentence or the file's own comment — Esc brings the tabs back"
             onChange={(e) => setText(e.target.value)}
             onKeyDown={(e) => { if (e.key === "Escape") done(); }} />
      <span className="x" role="button" aria-label="Back to the tabs" onClick={done}><i className="ic">{IC.close}</i></span>
    </div>
  );
}

function Found({ press, pressed, go }: { press: Press; pressed: string; go: (sub: string) => void }) {
  const [q, setQ] = useState(query);
  useEffect(() => {
    const on = () => setQ(query);
    window.addEventListener("settings-query", on);
    return () => window.removeEventListener("settings-query", on);
  }, []);
  // polled like the tabs, so a switch flipped among the results is
  // drawn as the file now has it
  const { data } = usePlace<Found>("settings", { q }, POLL_MS);
  if (!data || data.q !== q) return null;
  if (!data.found.length) return <div className="nomatch card glass">{data.none}</div>;
  return (
    <>
      {data.found.map((s) => (
        <div key={s.id} className="sec k-rows">
          <div className="name"><i className="ic">{IC.search}</i>{s.title}</div>
          {s.kind === "rows" ? (
            <div className="card glass">
              {s.rows.map((r) => <RowView key={r.path} row={r} press={press} pressed={pressed} />)}
            </div>
          ) : <Card s={s} press={press} pressed={pressed} go={go} />}
        </div>
      ))}
    </>
  );
}
