// Settings — owned by the Settings session (web/README.md): this file,
// settings.css and desk_settings.py, and the Settings section of tests.py. A
// STUB until then: it says the place is still in the old desk. What it
// becomes: the eight tabs of settings.TABS, each in Dashboard.LAYOUT's
// order, a tab as the route's sub — #/settings/privacy
// (dashboard._screen_settings). Its data: usePlace("settings", args, pollMs)
// from ../kit (desk_settings.Place.read); its buttons: placeCall("settings",
// "act", {do, arg}) (desk_settings.Place.act). Its root is .place-settings,
// and every rule in settings.css starts with it.
import { Away } from "../kit";
import "./settings.css";

export default function SettingsPlace({ sub }: { sub: string }) {
  void sub;
  return (
    <div className="place-settings">
      <Away place="Settings" text="Everything you can change, in plain words." />
    </div>
  );
}
