// Keys — owned by the Keys session (web/README.md): this file, keys.css and
// desk_keys.py, and the Keys section of tests.py. A STUB until then: it says
// the place is still in the old desk. What it becomes: every binding lit on
// a drawn keyboard; click a cap, or press a real key, to see it and rebind
// it (dashboard._screen_keys). Its data: usePlace("keys", args, pollMs) from
// ../kit (desk_keys.Place.read); its buttons: placeCall("keys", "act", {do,
// arg}) (desk_keys.Place.act). Its root is .place-keys, and every rule in
// keys.css starts with it.
import { Away } from "../kit";
import "./keys.css";

export default function KeysPlace({ sub }: { sub: string }) {
  void sub;
  return (
    <div className="place-keys">
      <Away place="Keys" text="Every key lit on a drawn keyboard — click one to see it or change it." />
    </div>
  );
}
