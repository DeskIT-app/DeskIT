// What Home is, as deskweb.Model.home() answers it. The Python side
// builds every word; the page only draws them.

export type Tone = "ok" | "q" | "bad" | "warn";

export type Button = {
  label: string;
  tone: "primary" | "quiet" | "close";
  act: string;
  arg?: unknown;
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

export type Home = {
  ok: boolean;
  locked: boolean;
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
  built: string[];
};

export type Acted = { ok: boolean; note: string; home: Home };
