// What one row is, on every screen. The Python side builds it
// (dev/master/rows.py) and the window only draws it: a screen that wants
// something new adds a field there, never a shape of its own here.

export type Evidence = { kind: string; word: string; path: string };

export type Row = {
  id: string;
  screen: string;
  title: string;
  under: string;
  body: string;
  body_title: string;
  body_from: string;
  rtl: boolean;
  tone: "q" | "ok" | "warn" | "bad" | "iris";
  glyph: string;
  when: string;
  when_small: string;
  at: string;
  fig: string;
  fig_small: string;
  pct: number | null;
  meter_tone: string;
  evidence: Evidence[];
  facts: Record<string, unknown>;
  came_from: string[];
  ticked: boolean;
  ticked_at: string;
  took: string;
  took_folder: string;
};

export type Count = { n: string | number; word: string };

export type ScreenReply = {
  ok: boolean;
  screen: string;
  read_at: string;
  rows: Row[];
  counts?: Record<string, Count>;
  error?: string;
};

export type Preview = {
  ok: boolean;
  id: string;
  title: string;
  under: string;
  folder: string;
  files: { name: string; word: string; kind: string }[];
  error?: string;
};

export type Took = {
  ok: boolean;
  folder: string;
  copied: boolean;
  files: { name: string; failed?: string }[];
  error?: string;
};
