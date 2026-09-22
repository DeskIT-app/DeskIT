import { useEffect, useState } from "react";
import { call, inDesk, pywebviewApi } from "./bridge";

export type Route = "home" | "said";

const ROUTES: Route[] = ["home", "said"];

export function routeOf(hash: string): Route {
  const name = hash.replace(/^#\/?/, "");
  return (ROUTES as string[]).includes(name) ? (name as Route) : "home";
}

type Status = { state: string; detail: string };

/** What status() said, in one line — never the reply itself. */
function summarise(reply: unknown): Status {
  if (reply === null || reply === undefined) return { state: "no app", detail: "nothing answered on the pipe" };
  if (typeof reply !== "object") return { state: "odd", detail: String(reply) };
  const r = reply as Record<string, unknown>;
  const keys = Object.keys(r).sort();
  const state = typeof r.state === "string" ? r.state : typeof r.model === "string" ? `model ${r.model}` : "answered";
  return { state, detail: `${keys.length} fields: ${keys.slice(0, 8).join(", ")}${keys.length > 8 ? ", …" : ""}` };
}

function Home({ status, apiKeys }: { status: Status; apiKeys: string[] }) {
  return (
    <section className="view" aria-label="Home">
      <div className="card">
        <div className="label">status() through the desk's channel</div>
        <div className="value" data-testid="status">{status.state}</div>
        <div className="detail">{status.detail}</div>
      </div>
      <div className="card">
        <div className="label">pywebview's js_api under this CSP</div>
        <div className="value" data-testid="pywebview-api">{apiKeys.length ? apiKeys.join(", ") : "not built"}</div>
      </div>
      <div className="lines">
        <p className="line" dir="ltr" lang="en">
          The desk is listening — hold Right Ctrl and speak.
        </p>
        <p className="line he" dir="rtl" lang="he">
          המחשב מקשיב — החזק את Right Ctrl ודבר, והטקסט יופיע איפה שהסמן עומד.
        </p>
      </div>
    </section>
  );
}

const SAMPLE = [
  "פגישה עם הצוות ביום שלישי בעשר",
  "Push the branch and open a PR on GitHub",
  "תזכיר לי לקנות חלב בדרך הביתה",
  "The Groq repair pass took 0.4 s",
  "שלחתי את הקובץ ל־Claude לבדיקה",
];

function Said() {
  const rows = Array.from({ length: 120 }, (_, i) => ({
    id: i,
    text: SAMPLE[i % SAMPLE.length] ?? "",
    at: `${String(8 + (i % 12)).padStart(2, "0")}:${String((i * 7) % 60).padStart(2, "0")}`,
  }));
  return (
    <section className="view" aria-label="Said">
      <ol className="said">
        {rows.map((r) => (
          <li key={r.id} className="row">
            <span className="at">{r.at}</span>
            <span className="text" dir="auto">{r.text}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function App() {
  const [route, setRoute] = useState<Route>(() => routeOf(window.location.hash));
  const [status, setStatus] = useState<Status>({ state: "…", detail: inDesk() ? "asking" : "not inside the desk" });
  const [apiKeys, setApiKeys] = useState<string[]>([]);

  useEffect(() => {
    const onHash = () => setRoute(routeOf(window.location.hash));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    if (!inDesk()) return;
    const t0 = performance.now();
    call("status")
      .then((reply) => {
        window.__desk.results.firstStatusMs = performance.now() - t0;
        setStatus(summarise(reply));
      })
      .catch((e: Error) => setStatus({ state: "error", detail: e.message }));
    // pywebview injects its api after the load event; look once it had time.
    const probe = window.setTimeout(() => setApiKeys(pywebviewApi()), 1500);
    return () => window.clearTimeout(probe);
  }, []);

  return (
    <div className="desk">
      <header className="bar">
        <h1 className="title">DeskIT</h1>
        <nav className="places">
          {ROUTES.map((r) => (
            <a key={r} href={`#/${r}`} className={r === route ? "place on" : "place"}>
              {r === "home" ? "Home" : "Said"}
            </a>
          ))}
        </nav>
      </header>
      <main>{route === "home" ? <Home status={status} apiKeys={apiKeys} /> : <Said />}</main>
    </div>
  );
}
