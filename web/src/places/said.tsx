// Said — owned by the Said session (web/README.md): this file, said.css and
// desk_said.py, and the Said section of tests.py. A STUB until then: it says
// the place is still in the old desk. What it becomes: transcripts.log read
// back, the search and the filters, SAID_PAGE rows at a time
// (dashboard._screen_said). Its data: usePlace("said", args, pollMs) from
// ../kit (desk_said.Place.read); its buttons: placeCall("said", "act", {do,
// arg}) (desk_said.Place.act). Its root is .place-said, and every rule in
// said.css starts with it.
import { Away } from "../kit";
import "./said.css";

export default function SaidPlace({ sub }: { sub: string }) {
  void sub;
  return (
    <div className="place-said">
      <Away place="Said" text="Everything you said, with the search over it." />
    </div>
  );
}
