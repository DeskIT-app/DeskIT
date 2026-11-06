// What the Settings place is answered — desk_settings.Place.read(), every
// word built in Python. The page only draws it.

export type Tone = "" | "ok" | "warn" | "bad" | "faint" | "dim" | "on";

export type Option = { v: string; label: string };

export type Consent = {
  text: string;
  tone: Tone;
  button: { label: string; do: string; arg: string } | null;
};

export type Row = {
  path: string;
  label: string;
  help: string;
  ctl: "switch" | "menu" | "field" | "folder" | "consent" | "file";
  value?: string | boolean;
  options?: Option[];
  num?: boolean;
  consent?: Consent;
};

export type Btn = { label: string; do?: string; arg?: unknown; go?: string; primary?: boolean };

export type KeyRow = {
  name: string;
  label: string;
  get: string;
  why: string;
  state: "locked" | "open" | "changing" | "testing";
  dots: string;
  placeholder: string;
  buttons: { label: string; do: string; primary: boolean }[];
  say: string;
  tone: Tone;
  storage: string;
};

type Head = { id: string; title: string; glyph: string };

export type Section = Head & (
  | { kind: "rows"; rows: Row[] }
  | { kind: "dot"; where: string; said: string; live: boolean; corner_at: string; moved: boolean;
      row: Row | null; move: boolean; home: boolean }
  | { kind: "updates"; line: string; fresh: boolean; newer: boolean; buttons: Btn[]; row: Row | null }
  | { kind: "awake"; state: string; meta: string; hint: string; tone: string; toggle: string;
      live: boolean; rows: { label: string; text: string; tone: Tone }[]; probed: boolean;
      probing: boolean; checked: string; intro: string }
  | { kind: "model"; lines: { name: string; text: string }[]; buttons: Btn[] }
  | { kind: "line"; line: string; small?: string; tone?: Tone; buttons: Btn[]; ready?: boolean }
  | { kind: "switch"; on: boolean; do: string; label: string; help: string; tone?: Tone; buttons?: Btn[] }
  | { kind: "sounds"; test: string; cues: { kind: string; label: string }[] }
  | { kind: "phone"; url: string; none: string; said: string }
  | { kind: "lines"; line: string; tone: Tone; sub?: string; code?: string; buttons: Btn[];
      typing?: boolean; placeholder?: string; signed_in?: boolean }
  | { kind: "keys"; rows: KeyRow[]; loading?: boolean }
  | { kind: "version"; name: string; line: string; machine: string; quit: string; quit_line: string;
      tour: string }
  | { kind: "about"; line: string; model: string; papers: string[] }
  | { kind: "files"; rows: { glyph: string; name: string; hint: string; file: string }[] }
);

export type Answer = {
  ok: boolean;
  running: boolean;
  warming: boolean;
  tabs: { name: string; slug: string }[];
  pages: Record<string, Section[]>;
  saved: string;
  note: { id: number; text: string };
};

export type Found = {
  ok: boolean;
  q: string;
  found: Section[];
  none: string;
};

export type Net = {
  ok: boolean;
  title: string;
  sub: string;
  hosts: string[];
  host: string;
  loopback: boolean;
  banner: string;
  columns: string[];
  rows: string[][];
  line: string;
  empty: string;
  toggle: string;
};

export type Acted = { ok: boolean; note: string; place: Answer };

/** One press of a button of this place: what it asks, and what to say. */
export type Press = (b: { do: string; arg?: unknown }, key?: string) => Promise<void>;
