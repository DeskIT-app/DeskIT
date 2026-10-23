// Corrections — owned by the Corrections session (web/README.md): this file,
// corrections.css and desk_corrections.py, and the Corrections section of
// tests.py. A STUB until then: it says the place is still in the old desk.
// What it becomes: the second reading's proposals, with the vocabulary
// beside them (dashboard._screen_corrections). Its data:
// usePlace("corrections", args, pollMs) from ../kit
// (desk_corrections.Place.read); its buttons: placeCall("corrections",
// "act", {do, arg}) (desk_corrections.Place.act). Its root is
// .place-corrections, and every rule in corrections.css starts with it.
import { Away } from "../kit";
import "./corrections.css";

export default function CorrectionsPlace({ sub }: { sub: string }) {
  void sub;
  return (
    <div className="place-corrections">
      <Away place="Corrections" text="Every proposal of the second reading, and the words it has learned." />
    </div>
  );
}
