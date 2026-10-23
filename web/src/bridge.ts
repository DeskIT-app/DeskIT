// The page's one way to the Python side.
//
// Two roads, and the page tries them in this order:
//
// 1. DeskIT's own channel. webdesk.py's DeskEdgeChrome reads every web
//    message itself: a message shaped {deskit: 1, id, fn, args} is ours,
//    it is accepted only from our virtual host's origin and only for a
//    name on Api.CALLS, and the answer comes back as a web message
//    ({deskit: 1, id, ok, value | error}) — no eval, no global object,
//    nothing injected into the page.
// 2. pywebview's js_api (window.pywebview.api.*), which pywebview builds
//    by injecting a script that calls `new Function`. It comes up even
//    under index.html's strict CSP (ExecuteScriptAsync is not governed by
//    it — measured 2026-09-22), and webdesk passes its calls on only for
//    a name in CALLS. It is kept as a probe; the desk's pages use call().

type Reply = { deskit: 1; id: number; ok: boolean; value?: unknown; error?: string };

interface WebViewChannel {
  postMessage(message: unknown): void;
  addEventListener(type: "message", listener: (e: MessageEvent) => void): void;
}

declare global {
  interface Window {
    chrome?: { webview?: WebViewChannel };
    pywebview?: { api?: Record<string, (...args: unknown[]) => Promise<unknown>> };
  }
}

const pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>();
let nextId = 1;
let listening = false;

function channel(): WebViewChannel | undefined {
  return window.chrome?.webview;
}

function listen(ch: WebViewChannel): void {
  if (listening) return;
  listening = true;
  ch.addEventListener("message", (e: MessageEvent) => {
    const data = e.data as Partial<Reply> | null;
    if (!data || data.deskit !== 1 || typeof data.id !== "number") return;
    const waiter = pending.get(data.id);
    if (!waiter) return;
    pending.delete(data.id);
    if (data.ok) waiter.resolve(data.value);
    else waiter.reject(new Error(data.error ?? "refused"));
  });
}

/** Call one of Api.CALLS over DeskIT's own channel. */
export function call<T = unknown>(fn: string, args: Record<string, unknown> = {}, timeoutMs = 5000): Promise<T> {
  const ch = channel();
  if (!ch) return Promise.reject(new Error("not inside the desk (no WebView2 channel)"));
  listen(ch);
  const id = nextId++;
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      pending.delete(id);
      reject(new Error(`${fn}: no answer in ${timeoutMs} ms`));
    }, timeoutMs);
    pending.set(id, {
      resolve: (v) => { window.clearTimeout(timer); resolve(v as T); },
      reject: (e) => { window.clearTimeout(timer); reject(e); },
    });
    ch.postMessage({ deskit: 1, id, fn, args });
  });
}

/** Whether pywebview managed to build window.pywebview.api under the CSP. */
export function pywebviewApi(): string[] {
  const api = window.pywebview?.api;
  return api ? Object.keys(api).sort() : [];
}

export function inDesk(): boolean {
  return channel() !== undefined;
}
