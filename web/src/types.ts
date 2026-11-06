// What Home is, as deskweb.Model.home() answers it. The Python side
// builds every word; the page only draws them.

export type Tone = "ok" | "q" | "bad" | "warn";

export type Button = {
  label: string;
  tone: "primary" | "quiet" | "close";
  act: string;
  arg?: unknown;
  /** a way in rather than a press: "settings/privacy" */
  go?: string;
};

export type Seg =
  | { t: "ctx"; s: string }
  | { t: "drop"; s: string }
  | { t: "chg"; heard: string; meant: string };

export type PileRow = {
  id: string;
  kind: string;
  at: number;
  tone: Tone;
  glyph: string;
  title: string;
  meta: string;
  text: string;
  rtl: boolean;
  segs?: Seg[];
  note?: string;
  buttons: Button[];
  /** the recovery key, shown once (lock:fresh) */
  code?: string;
  /** a field in the row: "recovery" on the waiting row */
  field?: string;
};

export type Door = { place: string; glyph: string; n: number; w: string; note: string };

export type DayLine = {
  label: string;
  when: string;
  text: string;
  rtl: boolean;
  meta: string;
  go?: string;
  act?: string;
};

export type Bar = {
  lamp: "listen" | "rec" | "write" | "idle";
  word: string;
  meta: string;
  run: string;
  stop: boolean;
  screens: string;
  dev: string;
};

/** The report sheet (Home's Report a problem): what would leave, in plain
 *  words with a size each, the exact row, the picture small. */
export type Piece = { what: string; size: string };
export type Preview = { pieces: Piece[]; row: string; thumb: string };
export type ReportView = {
  stage: "write" | "consent" | "sending" | "done";
  attach: string;
  on: string;
  off: string;
  limit: number;
  done: { tone: "ok" | "bad" | "q"; text: string } | null;
  preview: Preview | null;
  consent?: { title: string; lines: { k: string; v: string }[] };
};

/** The sign-in landing, drawn instead of every place while no account is
 *  signed in on this PC (dashboard._screen_landing). */
export type LandingView = { title: string; sentence: string; stored: string; line: string; tone: string };

/** The account lock asking for him, one line over every place but Home,
 *  which carries the same as a row (dashboard._lock_banner). */
export type Banner = { text: string; buttons: Button[] };

export type Home = {
  ok: boolean;
  locked: boolean;
  landing: LandingView | null;
  report: ReportView | null;
  report_on: boolean;
  banner: Banner | null;
  bar: Bar;
  head: string;
  sub: string;
  pile: PileRow[];
  unread: number;
  dismiss_key: string[];
  hold_key: string;
  held: string;
  doors: Door[];
  rest: DayLine[];
  strip: { awake: string; phone: boolean; facts: string[] };
  places: string[];
};

export type Acted = { ok: boolean; note: string; home: Home };
