import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { call } from "./bridge";
import "./styles.css";

// A probe the Python side reads with ExecuteScript (webdesk.Desk.js):
// what the page measured about itself, and two things it can be asked
// to do and time. Plain data only — nothing here reaches the app.
interface DeskProbe {
  results: Record<string, unknown>;
  /** Switch to a route; results.switch[route] = ms from the call to the
   * frame after the new view is on screen. */
  switchTo(route: string): void;
  /** n round trips of `ping` over the desk's channel; results.rtt = ms[]. */
  rtt(n: number): void;
  metrics(): Record<string, unknown>;
}

declare global {
  interface Window {
    __desk: DeskProbe;
  }
}

function frame(): Promise<number> {
  return new Promise((resolve) => requestAnimationFrame((t) => resolve(t)));
}

window.__desk = {
  results: { switch: {} as Record<string, number> },
  switchTo(route: string) {
    const t0 = performance.now();
    const want = route === "said" ? "Said" : "Home";
    window.location.hash = `#/${route}`;
    const wait = async () => {
      for (let i = 0; i < 600; i++) {
        await frame();
        const view = document.querySelector("main section.view");
        if (view && view.getAttribute("aria-label") === want) {
          await frame(); // the frame after the one that painted it
          (window.__desk.results.switch as Record<string, number>)[route] = performance.now() - t0;
          return;
        }
      }
      (window.__desk.results.switch as Record<string, number>)[route] = -1;
    };
    void wait();
  },
  rtt(n: number) {
    const out: number[] = [];
    const go = async () => {
      for (let i = 0; i < n; i++) {
        const t0 = performance.now();
        await call("ping");
        out.push(performance.now() - t0);
      }
      window.__desk.results.rtt = out;
    };
    go().catch((e: Error) => {
      window.__desk.results.rtt = String(e.message);
    });
  },
  metrics() {
    const paint: Record<string, number> = {};
    for (const e of performance.getEntriesByType("paint")) paint[e.name] = e.startTime;
    const nav = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
    return {
      timeOrigin: performance.timeOrigin,
      paint,
      domContentLoaded: nav?.domContentLoadedEventEnd,
      load: nav?.loadEventEnd,
      rubik: document.fonts.check("16px Rubik"),
      rubikHebrew: document.fonts.check("16px Rubik", "שלום"),
      dir: getComputedStyle(document.querySelector(".line.he") ?? document.body).direction,
      origin: window.location.origin,
      ...window.__desk.results,
    };
  },
};

void document.fonts.ready.then(() => {
  window.__desk.results.fontsReadyMs = performance.now();
});

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
