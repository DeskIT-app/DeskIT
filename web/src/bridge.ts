// The page's one way to the Python side: DeskIT's own channel.
//
// webdesk.py's DeskEdgeChrome reads every web message itself: a message
// shaped {deskit: 1, id, fn, args} is ours, it is accepted only from our
// virtual host's origin and only for a name on Api.CALLS, and the answer
// comes back as a web message ({deskit: 1, id, ok, value | error}, a
// failure as its exception's type) — no eval, no global object, nothing
// injected into the page.
//
// pywebview's own road (window.pywebview.api.*) is closed: the shell hands
// pywebview no api (js_api=None) and drops every pywebview-shaped message,
// because that road answered a call that raised with its message and the
// whole traceback (the foundation's review, 2026-10-23).

type Reply = { deskit: 1; id: number; ok: boolean; value?: unknown; error?: string };

interface WebViewChannel {
  postMessage(message: unknown): void;
  addEventListener(type: "message", listener: (e: MessageEvent) => void): void;
}

declare global {
  interface Window {
    chrome?: { webview?: WebViewChannel };
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

export function inDesk(): boolean {
  return channel() !== undefined;
}
