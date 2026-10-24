// The Network screen (dashboard._screen_network), reached from EVERY
// CONNECTION on Settings > Privacy: every request this app made, newest
// first, from network.log — during plain dictation the table stays empty.
import { useState } from "react";
import { placeCall, useDesk, usePlace } from "../../kit";
import { GLYPHS, type Net } from "./model";

export function NetworkScreen({ back }: { back: () => void }) {
  const { say } = useDesk();
  const [host, setHost] = useState("All");
  const [loopback, setLoopback] = useState(false);
  const { data } = usePlace<Net>("settings", { net: 1, host, loopback }, 1000);
  const openLog = () => {
    placeCall<{ note: string }>("settings", "act", { do: "net.log", arg: null })
      .then((r) => say(r.note))
      .catch((e: Error) => say(e.message));
  };
  return (
    <div className="net">
      <div className="title">Network</div>
      <div className="nsub">{data?.sub ?? "every request, newest first · network.log"}</div>
      <div className="chips">
        {(data?.hosts ?? ["All"]).map((h) => (
          <div key={h} className={`chip-h${h === (data?.host ?? host) ? " on" : ""}`} onClick={() => setHost(h)}>{h}</div>
        ))}
      </div>
      {data?.banner ? <div className="banner"><i className="ic">{GLYPHS.warning}</i>{data.banner}</div> : null}
      <div className="table card glass">
        <div className="th">{(data?.columns ?? []).map((c) => <span key={c} className={`c ${c}`}>{c}</span>)}</div>
        <div className="tb">
          {data && data.rows.length ? data.rows.map((r, i) => (
            <div key={`${i}${r[0]}`} className="tr">
              {r.map((v, j) => (
                <span key={j} className={`c ${data.columns[j] ?? ""}${data.columns[j] === "result" && !v.startsWith("2") ? " odd" : ""}`}
                      title={v}>{v}</span>
              ))}
            </div>
          )) : <div className="empty">{data?.empty ?? ""}</div>}
        </div>
      </div>
      <div className="foot">
        <span className="line">{data?.line ?? ""}</span>
        <div className="btn" onClick={back}><i className="ic">{GLYPHS.left}</i>Back to Privacy</div>
        <div className="btn" onClick={openLog}>Open network.log</div>
        <div className="btn" onClick={() => setLoopback(!loopback)}>{data?.toggle ?? "Show loopback (phone)"}</div>
      </div>
    </div>
  );
}
