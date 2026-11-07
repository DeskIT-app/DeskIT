# DeskIT — the phone link ("the phone plan")

Written 2026-11-06 with the owner, and approved by him the same day. **No code is written by this plan**; it is
the brief the code is written from, and the one place a session lands when he says *"the phone link"* /
*"הקשר לטלפון"* / *"בלי טיילסקייל"*. §12 says how it is being built.

His words, 2026-11-06, dictated: make phone transcription more efficient and cut it off from Tailscale;
everything Tailscale brings us today should live with us, disconnected from outside systems, so it depends
on nobody; for us locally, and as something people can download; very simple to set up and to get; if
possible no app to download, only a website, or both; researched in depth, clear, with no holes. Later the same
day: some people's PCs will be off, so if the link is not there, after about a second, an API key should do the
work in the background. And then: that backup stays ON unless the person turns it off; the key is not kept on
the phone but encrypted with the user, as on the computer; the phone gets the same add, change and delete screen
as the computer; a key already on the PC arrives by itself when the phone is linked to the user, and any change
on the phone reaches the computer by itself. *"Everything works around the account and not around the device."*

This supersedes item 15 of `notes/DeskIT-store-walk-2026-10-03.md` and replaces the transport half of D22.
`DISTRIBUTION_PLAN.md` chapter 12 stays the reference for the package identity, the keystore and versions.

## 0. In one paragraph

Everything hangs on the account. A phone is one more device of the person's DeskIT account: it signs in with
Google, one Approve on a PC lets it into the account's lock, and from then on all it needs follows the account,
sealed so the server cannot read it: where the PCs are, their certificates, the cloud keys. **Home:** the phone
talks straight to the PC on the same network, encrypted, with nobody in between and, after that first sign-in, no
internet needed. **Speed:** the phone sends the audio while he speaks and the PC decodes it as it arrives, the
desk's own machinery, so the text lands about a second after the release at any length. **The backup:** when the
PC cannot be reached, off or with no path, the recording goes to the person's own cloud key about a second later;
it is on unless they turn it off, and the key lives sealed in the account, added, changed and removed from the
same screen on the phone and the desk. **Anywhere:** the phone and PC exchange one sealed hello on the account's
own private channel and then connect directly, each using the browser engine it already has, so nothing new is
installed and no audio passes through any server. A web page gives the same with no install at all, and it is
the only free road for an iPhone, though no web page can type into another app. Tailscale comes out last, after
this has carried his real use for a week. The honest limits: the first sign-in needs the internet once; away from
home two devices need a third point to introduce them, and that point is his own account, which sees no content;
and at the moment of a cloud call the phone must hold the key in memory, because whoever calls the provider has to
present it.

## 1. What is true today — checked 2026-11-06

**The road.** The keyboard (`android/`, 1.2 MB, no dependencies) records 16 kHz PCM with
`AudioRecord`, waits for the release, and POSTs one WAV with `HttpURLConnection` to
his `ts.net` address. `tailscale serve` (Tailscale 1.102.2 on this PC) terminates TLS and
proxies to `127.0.0.1:8756`, where `server.py` answers inside the running app. One bearer token
(`secrets\phone_token.bin`, DPAPI) guards the routes. The PC decodes the WHOLE recording
(`_transcribe(wav, language=None)`): the rolling decode the desk has (`rolling.py`) is off for the
phone, so a long phone dictation waits for all of it after the release.

**It is barely used, and the road is why.** `tailscale status`: the phone (`S26 Ultra`) is offline,
last seen 2026-10-01, 36 days ago. `transcripts.log`, which starts 2026-09-17, holds 8 phone
dictations ever: five on 09-17, two on 09-22, one on 09-24. Nothing has been dictated from the phone
for six weeks. What `server.py` does all day now is take the Claude hook's `/notify` on loopback.

**A stranger cannot do it at all.**

- No release carries the keyboard. v1.0.0 to v1.0.6 all hold no APK (checked one by one): an installer,
  its hash, `latest.json`, the manifest and the notices. `release.yml` has no Android step (no `apk`, `gradle` or
  `keystore` anywhere in it). The guide promises `DeskIT-keyboard-x.y.z.apk`; `server.api_version()`
  points at `DeskIT-{v}.apk`. Neither exists, so the keyboard's update pill leads to a 404.
- The road itself is twelve steps: a Tailscale account, the app on the PC, the app on the phone, both
  signed in, the switch on the PC, a terminal command, a click on the link that command prints, a wait
  of ~30 s for the first certificate, the APK, a pasted line, the microphone, the keyboard enabled.
- A stranger's Claude hook depends on the phone switch without anyone knowing: `main.py:904` builds the listener
  only when `server.enabled` is true, its default is false, it is read at start, and Connect Claude writes only
  `notify.enabled`. With the switch off the hook posts to nothing, in silence.
- The guide's Trouble section says a busy port falls through to the next free one and Settings shows it.
  No code does that: `PhoneServer.start()` raises and `main.py` drops the phone. `notify_hook` reads a
  `server.port` from `state.json` that nothing writes. `paths.DEFAULT_PORT = 8757` for the Dev is also
  dead code: this Dev listens on 8756, measured today, so AGENTS.md's "port 8757" is wrong and a released
  copy beside it would collide.

**His own network, measured today.** These decide what works, so they come before any design.

| Fact | Reading | What it means |
|---|---|---|
| Two routers | PC → TP-Link Deco X50 `192.168.68.1` → `10.100.102.1` → the internet (traceroute) | Double NAT. A phone on the first router's own Wi-Fi is NOT on the PC's network |
| UPnP | The X50 answers, `GetExternalIPAddress` comes back EMPTY, NAT-PMP refuses | Opening a port by UPnP reaches only the second router. "Just open a port" does not work in his own home |
| Public address | A public IPv4, `IPv6: no` | No IPv6 road to the PC today. The Deco ships with IPv6 off, so this may be one toggle away (M10) |
| NAT behaviour | `MappingVariesByDestIP: false`, UDP works, and WebRTC's reflexive port equals the local port on two STUN servers | The home side is as easy as NAT gets for a direct connection: both routers keep the port |
| Windows network type | Ethernet = **Public** | D22 said "no rule on the public profile, the page says home Wi-Fi". On his own PC that would have blocked the phone |
| Firewall rules | `NotifyOnListen` on; an inbound allow exists for `python.exe` (Public only), none for `pythonw.exe`; the app runs under `pythonw.exe` | The first listen raises the Windows dialog, which needs his UAC yes |
| The real listener | `pythonw.exe` of the base Python 3.11, not the venv's launcher | A firewall rule must name the base interpreter; a rule on `.venv\Scripts\pythonw.exe` would do nothing |

**What exists of the old plan.** `DISTRIBUTION_PLAN.md` chapter 12 (D22, 2026-09) designed home-Wi-Fi
pairing with a QR and a pinned certificate. Of it, the package rename, `/health` = `{ok, version}`,
`/api/version`, the removal of the web page and `/app.apk`, and the signing lines in `build.gradle.kts` are
done. The keystore itself was never made: no `android/keystore.properties`, and `VT_API_KEY` is the repository's
only secret.
Nothing of the pairing exists: no `phone.py`, no `transport` key, no QR. Item 15 of
`notes/DeskIT-store-walk-2026-10-03.md` (2026-10-03) listed four options and a measurement session that
never ran.

**Proved today, on this PC, in the scratchpad (nothing in the repo touched):**

- An identity with no new package: a P-256 key and a hand-written self-signed X.509 certificate through
  Windows CNG (`bcrypt.dll`, as `vault.py` already does) in 1.0 ms, 300 bytes. Python's own `ssl` served
  TLS 1.3 with it. Chapter 12's open point 4 ("which wheel") is closed: none.
- A door that refuses before it reads: with `CERT_REQUIRED` and the paired phone's certificate as the
  only trust anchor, a client with no certificate and a client with the wrong one were both dropped in
  the handshake, so `http.server` never saw a byte from them. Handshake p50 1.8 ms, 1 MB round trip
  10.4 ms on loopback. A client pinning the wrong fingerprint stops before it sends anything.
- The home door from a keyboard, on the emulator (Android 14) against those doors on this PC: a non-exportable
  EC key made in Android Keystore in 74 ms, `HttpsURLConnection` to a bare IP with a pinned trust manager, a
  pin-checking hostname verifier and a custom key manager. The phone's 307-byte certificate went to the PC,
  `load_verify_locations` added it to the live context, and the door then took 1 MB three times, TLS 1.3,
  ~700-940 ms on the emulator. With no client certificate: dropped in the handshake.
  With a wrong pin: stopped before a byte of the body left.
- A phone joining the account, against the real `vault.py`, no library on the phone, emulator: the same
  `XXXXX-XXXXX` code on both sides, the account key out of the hand-over, a sealed Groq row opened, and an edit
  sealed on the phone that the PC opened. It also found a trap no reading would have: the shared secret's bytes come
  in opposite orders on the two platforms (stage 1). The same road in a browser, WebCrypto only, hidden: all of
  it passed, PBKDF2 in 21 ms, the account key then held as a non-extractable key.
- A browser may call Groq: the preflight from `deskit-app.github.io` answers `access-control-allow-origin: *`.
- WebRTC with no new binary: the WebView2 the desk already ships, hidden, on a hidden desktop, opened a
  data channel 1.9 s from a cold process, carried 4.8 MB/s, and cost 222 MB private (8 processes,
  including the probe's own PowerShell). Its host candidates are mDNS names (`….local`), a thing to deal
  with (§6.3).
- Sizes over the 50 recordings in `recent\` (14.1 min): WAV 1,920 KB/min, Opus 16 kbps 97 KB/min, 24 kbps
  139, 32 kbps 201, FLAC 616. Opus at 24 kbps is 7.2% of the WAV. What it does to accuracy is NOT measured
  yet (§5, stage 2).
- A WebRTC channel out of a keyboard, with no new library: a WebView owned by a real `InputMethodService`
  on the emulator reached a hidden WebView2 on this PC through the emulator's NAT, channel open 2.34 s
  after the keyboard view was created, 1 MiB up and an answer back in 682 ms (§6.3).
- The hello's road: two sockets on a Realtime topic, 66 ms p50 for 2 KB, 83 ms for 60 KB (§6.2).
- `rolling.Roller` takes a `chunks_since(mark)` callable, not a recorder, so a phone's stream can feed it
  with no change to that module.

## 2. Everything Tailscale gives us, and what takes each thing over

Only two devices are on his tailnet, and only one thing is served on it: `/` → `127.0.0.1:8756`. So this
list is the whole of what has to be replaced.

| # | What Tailscale gives | Who does it after this plan | What changes for him |
|---|---|---|---|
| 1 | Reach from the same house | The phone connects straight to the PC's LAN address (stage 1) | Faster, and works with the internet down |
| 2 | Reach from anywhere | A direct connection the two devices punch themselves (stage 3) | Works wherever a direct path exists; §3.1 says where it cannot |
| 3 | A relay (DERP) when direct fails | The cloud-key backup (stage 2b), on unless turned off | Weaker words for that dictation, and nothing to do |
| 4 | Choosing the path by itself | The keyboard's `Link.kt` and `link.js`: last good address, then LAN race, then direct, then the backup | Nothing to do |
| 5 | A stable name (`<pc>.<tailnet>.ts.net`) | A device's identity is its certificate; its addresses live sealed in the account and are found, never typed | Nothing to remember |
| 6 | A real TLS certificate (Let's Encrypt, via Serve) | Not needed: both ends pin the other's certificate from the account | The ~30 s first-certificate wait goes |
| 7 | Encryption on the wire (WireGuard + TLS) | TLS at home, DTLS away, both pinned at both ends | Same strength, nobody else holds a key |
| 8 | Who may connect (being on the tailnet) | Being a device of the account: the lock admits it once, on a device the person is at, and any device of the account can remove it | Finer than today's one shared token, and one Approve for the whole account. Windows' own yes is still asked once on each PC that listens |
| 9 | Sign-in and key exchange (its control plane) | The account he already has, and the account lock (`vault.py`) | No Tailscale account |
| 10 | Opening holes in the router (UPnP etc.) | Not relied on: measured useless on his double NAT (§1) | |
| 11 | Survives switching Wi-Fi ↔ mobile data | The link reconnects on the next press; the recording stays on the phone until the text lands | A moment's reconnect instead of none |
| 12 | Nothing listens on the LAN | At home, one door that drops anything but a device of the account in the handshake; away, nothing listens at all | A deliberate, documented change (D12) |
| 13 | Costs the phone a VPN slot, an always-on service | Nothing runs on the phone unless the keyboard is up | A gain, not a loss |

## 3. What "depends on nobody" can honestly mean

Two devices behind home and mobile routers cannot find each other with no third point on the public
internet. That is physics, not a product choice: neither has an address the other can reach. Every
"from anywhere" product has such a point: the air conditioner's maker, Tailscale's control plane,
Syncthing's discovery servers. So the honest promise has levels, and this plan keeps them apart.

| Where | Who is needed | What they see | When they die |
|---|---|---|---|
| **Setting up** a new device, once | His account server, to sign in and to carry the lock's sealed hand-over | That a device joined; never a key or a word | No new device can join; every device already in keeps working |
| **Home** (same network) | Nobody. Not us, not the internet | Nothing | Nothing happens |
| **Away, direct** | The account's own private channel for one small sealed message each way, and a public address-check (STUN) | The channel: that two devices spoke, and sizes, never content. STUN: an IP address | Home keeps working; away falls to the backup |
| **PC off, or no direct path** (some mobile networks, §3.1) | The provider of the person's own cloud key (stage 2b) | The provider hears that recording | The recording waits on the phone |

The account server is the one he already owns, and every signed-in copy with a sync on already holds a socket to
it, 0.15-0.30 s measured 2026-09-20; from stage 1 every signed-in copy does. This plan adds no new company to the
app's account road. It leans on that server harder than the first version did, on purpose and at his word: the
account is the centre. Nothing this plan puts there is readable, and what stops without it is only what could not
work anyway. (The learned words and settings that sync are plain text on it today, `vocab_sync` and `settings_sync`,
as they have been since 0001; 0004 sealed what he said and the cloud keys. This plan leaves that as it is.)

**The one road with no third point at all** is to make the PC itself reachable from the internet: IPv6 (M10), or
a port forwarded by hand on both of his routers, or the first router put in bridge mode. Then the phone dials the
PC's public address and nobody introduces anyone, until the provider changes that address. Stage 1's
client-certificate door is what makes this safe to do. It is open to him, by hand, as one more address in the
account's list. No stranger will ever do it, so it is not the plan's road.

### 3.1 How often a direct path exists

Nobody can promise this; the published numbers say what to expect.

- Tailscale, which tries much harder than WebRTC, reports direct connections "well north of 90%" overall,
  and says phones on different carriers often end up relayed; its own table relays easy-to-hard NAT.
- libp2p's hole punching: 70% ± 7.1% success over 4.4 million attempts on 85,000 networks (IMC 2026).
- Cellular: over 90% of cellular networks sat behind carrier NAT in a 2016 study, about 40% of those of the
  hard (symmetric) kind and about 20% of the easiest, and a 2026 Israeli guide says almost every private plan here is behind one
  (secondary; no carrier publishes this). M2 measures his.

**The home side is good, and IPv6 may settle it.** His home NAT is the easy kind (§1), so hole punching
has a fair chance. IPv6 is better still: with no NAT in the way, WebRTC reaches the other side directly
through both firewalls. APNIC, IPv6-capable share, 2026-11-03: Pelephone 92.8%, HOT Mobile 71.5%, Partner
68.1%, Cellcom 41.4%; home lines: Bezeq 84.1%, HOT 82.6%. His home shows no IPv6, and TP-Link's Deco ships
with it off (M10). For a stranger on an Israeli home line and a mobile network, the direct road may be IPv6
far more often than the 2016 numbers suggest, but no one has measured that pair.

**What this means for stage 3.** It must be built to fail honestly. When no path exists the keyboard says so
and does not lose the words. What it does next is stage 2b, or Q2.

## 4. The design

### 4.1 Three rungs, tried in order, nothing to choose

| Rung | When | Keyboard | Web page | Who is in the path |
|---|---|---|---|---|
| 1. Home | Same network | TLS straight to the LAN address, both ends pinned | Rung 2's road | Nobody, and no internet needed |
| 2. Direct | Anywhere a path exists: IPv6, or punched IPv4 | WebRTC in a hidden WebView | WebRTC in the page | Nobody. The account's channel and STUN only before it starts |
| 3. Backup | PC off, or no path, known within about a second | The person's own cloud key, unless turned off | The same | The provider hears that recording; nobody else is involved |

He sees none of this. The keyboard says ready, or says why not, and the status line says when the words came from
the cloud. With no key and no PC the recording waits on the phone.

### 4.2 The account is the link

This is the change of 2026-11-06, his: *everything around the account, not around the device.* It also makes the
plan smaller. Nothing is paired per PC and per phone any more. A device joins the account once, and the account
holds what the others need, sealed under the account key, which the server cannot open.

| In the account | What it holds | State |
|---|---|---|
| `vault` | The cloud keys, one sealed row per name | Exists, syncs between PCs today |
| `pairings` | A new device's request to join the lock | Exists; migration 0004 says "the phone will use the same table when it joins" |
| `devices.link`, `devices.session_id` | For each device, sealed: its certificate, its addresses, its port, the protocol it speaks. Beside it, in the clear, the id of its session, so Forget can end it | New columns, migration 0007 |
| `vault` row `forgotten` | The devices that were forgotten, sealed, read by every device | A new row in a table that exists; `vault.import_keys` skips a name it does not know |
| `user:<uid>` Realtime topic | "Something changed", and the sealed hello | Exists since 0003, private to the account |

**How a phone joins, the whole of it:**

1. Install the keyboard. A QR on Settings > Phone points at the download; it is only an address and holds no secret.
2. Open it and sign in with Google, in the phone's browser, the same account as the PC.
3. The phone asks to join the lock. Home on every PC that holds the key shows the row it already shows for a new PC:
   the device's name, a code, **Approve** / **Not now**. The phone shows the same code. He presses Approve on the PC and
   **Same code** on the phone, one press on each side, the way Bluetooth pairs. The code binds the phone's key and the
   account's lock together (stage 1), so that one look protects both directions.
4. The account key crosses wrapped to the phone's own key pair. The phone writes its `link` row, the PCs add it, the
   phone reads theirs. Done for the account: the PC he pressed Approve on opens its door at once, and any other PC
   asks with one row on its own Home, because Windows wants its own yes on each PC that listens (stage 1).

Proved today against the real `vault.py`, with no library on the phone (§1). Home's row, its code and its Approve
are built, tested and in use between PCs.

**What this removes from the first version of this plan:** the one-time QR secret, the pairing door, the Pair panel
and its Allow prompt, per-phone link keys and a separate topic, anonymous sessions and public Realtime channels,
App Links and their `assetlinks.json`, and mDNS. Every hole that came with them goes too. What it costs: the
phone needs its own Google sign-in, and joining needs the internet and a device that holds the key, once.

### 4.3 A stranger's whole setup

Today: twelve steps, two apps, an extra account, a terminal, and an APK that does not exist.

| Road | Steps |
|---|---|
| Keyboard | Install the APK (Auto Blocker off, once). Sign in with Google. Compare the code: Approve on the PC, Same code on the phone. Enable the keyboard in Android's settings, allow the microphone |
| Web page (stage 4) | Open the address. Sign in with Google. Compare the code: Approve on the PC, Same code in the page. Allow the microphone |

No second account, no second app, no terminal, no address, no port. The cloud key, if the person has one, is already
there. A second PC of the account needs one press on its own Home before it listens, because Windows asks each PC, and
none at all on the away road (stage 3).

### 4.4 What "no holes" cannot mean

Five things the plan will not pretend away. The good model lives on the PC, so with the PC off the words go to a
weaker one; Tailscale had no answer at all there. On some networks no direct path exists: §3.1 says how often that
may be, M1 and M2 measure his, and the backup catches it. A new device can only join through a device that already
holds the key, or the recovery key; that is what keeps the server out. And whoever calls a provider has to present
the key, so at that moment it is in the phone's memory; §5, stage 2b, says exactly where it is the rest of the time.
And a device that once held the account key cannot be made to forget it: Forget stops the app and ends the session, and
§8 says what is left after that.

## 5. The stages

Each stage is a branch, its tests, his check in the Dev copy, and only then a PR (house rule 9). Each one
is worth having if the next never happens.

| Stage | What he gets | Size | Needs |
|---|---|---|---|
| 0 | Numbers instead of guesses | An evening | Five minutes of his phone |
| 1 | The phone joins the account; home with no Tailscale | Large | The Settings picture approved, the sign-in address allowed on the project |
| 2 | About one second from release to text at any length | Medium | Stage 1 |
| 2b | Keys on the phone, tied to the account, and the backup when the PC cannot be reached | Medium | Stage 1 |
| 3 | From anywhere, directly | Large | Stage 0's answers |
| 4 | A web page: no install, and the only road for an iPhone | Medium | Stage 3 |
| 5 | The phone's own model: no PC, no network | Large | Q2, the model session |
| 6 | Tailscale gone from the code and the guide | Small | His "works" on 1-3 |
| 7 | A stranger can do it: the Google side of Android | Small | Q3 |

### Stage 0 — Measure first

Nothing here touches the product. Every result is written into this file. M3 and M16 are stage 1's first step and M15
is stage 2b's, a few minutes each. M4, M11 and M13 are checked while stage 1 is built. The rest decide stage 3 or later.

| # | Who | What | What it decides |
|---|---|---|---|
| M1 | He, 1 min | Tailscale on the phone, on mobile data, away from the Wi-Fi. I run `tailscale ping` and read `tailscale status` on the PC: direct or relayed? | Whether a direct path exists from his carrier at all (Tailscale tries harder than WebRTC, so a direct here does not prove stage 3, while a relay here nearly disproves it) |
| M2 | He, 1 min | On mobile data, the WebRTC project's Trickle ICE page with two STUN servers: do the two reflexive ports match? A screenshot is enough | Whether his carrier's NAT is the hard kind (§3.1) |
| M3 | Done 2026-11-06 | At home: the phone's Wi-Fi address. His phone is on `192.168.68.x`, the PC's network, not on the first router's | Stage 1 works as it stands in his own home. This is a check of one home; nothing in the product depends on it |
| M4 | Me, with his UAC yes | A throwaway TLS listener on the LAN and the phone's browser opening it: what the firewall dialog offers on a Public network, and what a Cancel leaves behind. Beside it, on a self-signed Store package: which executable the manifest rule must name | Stage 1's wording and whether `netsh` is needed |
| M6 | Done 2026-11-06 | `RTCPeerConnection` in a WebView owned by the keyboard, to a hidden WebView2 on the PC: works on the emulator (§6.3) | Stage 3 can stay free of native libraries, pending M8 |
| M7 | Done 2026-11-06 | A browser page meeting a hidden WebView2 through Realtime and STUN, the whole road in 1.06 s (§6.2). A public topic, for the probe; the real one is private | The hello's road |
| M8 | Me and his phone | The first real direct connection: phone on mobile data, a throwaway page, hidden WebView2 at home. Nothing is published for it: the page loads over Tailscale one last time (`tailscale serve --set-path`), Tailscale goes off, the page connects. Also watched for: no firewall dialog on his screen from the engine | The proof of stage 3, or its end |
| M9 | Me, at night | Opus 16/24/32 kbps against WAV on the six public sets, more than one run each | Stage 2's compression |
| M10 | He, 2 min | The Deco app's IPv6 setting: is it off? With another router in front, TP-Link's FAQ for its routers says Pass-Through (Bridge); it does not name the Deco, so the app's words may differ. I re-run `tailscale netcheck` | Whether his home has IPv6. If it does, most Israeli mobile networks reach it directly with no NAT at all (§3.1) |
| M11 | Partly done 2026-11-06 | Auto Blocker was on and stopped the APK with its own message, naming where to turn it off (Settings > Security and privacy > Auto Blocker). With it off the APK installed, and One UI asked nothing more. The mic in it is still to check | The guide's first step on a Galaxy is Auto Blocker, as written |
| M12 | A borrowed iPhone, 10 min | The throwaway page, tab and Home Screen, on plain Wi-Fi and on mobile data: does the channel open, does the mic ask every launch, does the text copy | Whether stage 4's iPhone promise is true |
| M13 | He, 2 min | The second router's uplink unplugged, mobile data on: does the keyboard still reach the PC over Wi-Fi | Whether "no internet needed" is true on his phone (stage 1, the bound Wi-Fi network) |
| M14 | Done 2026-11-06 | A phone (Kotlin, no library) and a page (WebCrypto only) joining the lock against the real `vault.py`: same code on both sides, the key out of the hand-over, a vault row opened, an edit the PC could read. Not run: a removal, and the code as stage 1 changes it; test vectors hold both | The whole account road of stages 1, 2b and 4 (§1) |
| M15 | He and I, with his yes | One real Hebrew clip from the phone through his Groq key, the free tier's real limits read off his console, `language` set and unset, and a real POST from a browser origin (the preflight already passes) | Stage 2b's words and the web page's backup |
| M16 | Done 2026-11-06 | The Google sign-in on his S26 (Android 17, SDK 37), debug build: the browser, the return through `deskit://auth`, a session sealed on the phone. The join's code in 146 ms. The client key made in 9 ms, signing in 4 ms, in secure hardware, unlocked only | Stage 1's first step stands. `deskit://auth` is on the project's allowed list |

M1, M2 and M10 take him five minutes and decide stage 3. They do not hold up stages 1, 2 and 2b.

### Stage 1 — Home: the phone joins the account and reaches the PC directly

*Acceptance: "I install the keyboard, sign in, press Approve on the PC, and dictate from the couch with no Tailscale
installed." And then with the house's internet unplugged.* This stage alone ends the dependence at home. It has two
halves, and they ship together.

#### The first half: the phone becomes a device of the account

All in Kotlin with no library: REST through `HttpURLConnection` and the platform's own crypto.

- **`Account.kt`, the sign-in.** The phone's browser opens Supabase's `/auth/v1/authorize` for Google with a PKCE
  challenge, the same request `sb.sign_in_google` makes, and the answer returns to the custom scheme `deskit://auth`,
  which one activity catches. The plain browser, no Custom Tabs library; Google refuses embedded WebViews.
  `POST /auth/v1/token?grant_type=pkce`, then refresh the way `sb._fresh` does. The session is kept sealed by a
  Keystore AES-GCM key. `deskit://auth` has to go on the project's list of allowed addresses: one setting, and M16.
- **`Lock.kt`, the join, in the order `_request_pairing` does it.** Read `profiles.lock_id`. Delete this device's own
  open requests: two open requests from one device are twins, and Home offers nothing to approve. Make a P-256 pair,
  compute the code, and only then write the `pairings` row (`p1.` + the raw X‖Y point), because its `code` column is not
  null (`code_hint` of the code) and `device_name` stops at 40 characters, so the name is clipped. Post the `pairing`
  broadcast, or a PC hears of the request only at its next pass, up to 15 minutes later, just as the request expires.
  Poll the row every 3 s. Once the person has pressed **Same code**, take the key out of `handed`, check it against the
  `lock_id` the code was made with, delete the row, and keep the key wrapped by the Keystore. Every format is `vault.py`'s; M14 ran them all against the real thing.
- **The code binds the lock.** Today the code proves the asking device to the approver, and nothing proves the approver
  to the asking device. `hand_over` is unauthenticated, the only check afterwards is the fingerprint against `lock_id`,
  and the server writes both of those. So a dishonest server could hand a joining device a key of its own, then forge
  `link` rows and read any key typed there; a PC joining today has the same hole. `vault.pairing_code` gains the lock in
  its material: the asking device uses the `lock_id` it read, the approver the fingerprint of the key it holds, never
  the server's column. If the server lied to the device, the two screens differ; if it told the truth, a key of its own
  fails the fingerprint, unless it finds a second key with the same 64 bits. That is worth something only if the asking
  device waits for its person: otherwise a dishonest server writes `handed` itself, with no PC at all, under a lock it
  named. So both sides press, as in Bluetooth pairing. The approver presses Approve; the asking device presses **Same
  code** on the screen that shows the code, and it neither opens nor keeps what it received until then. The press may
  come before or after the Approve. One code, one press on each side. Every copy changes together; an older copy shows
  another code, which fails safe.
- **The request survives the process.** He walks away from the phone to press Approve, and Android may kill a keyboard
  meanwhile. The PC keeps the private half in memory because its process stays up; the phone keeps it sealed by a
  Keystore AES-GCM key for the request's 15 minutes, beside the request's id and code, so the same code is on screen
  when he is back and the answer still opens. (A true ECDH key in Keystore needs API 31; `minSdk` is 26.)
- **The trap M14 found.** The hand-over failed at first with `AEADBadTagException` while the code matched: CNG's
  `TRUNCATE` hands the ECDH secret in the opposite byte order to Android's `KeyAgreement`. The PC's code stays as it
  is, since every PC depends on it, and the phone reverses the 32 bytes. WebCrypto will need the same. A test vector
  holds it, because nothing else would say why a join fails.
- **The code takes a moment.** PBKDF2 at 2^17 rounds is 50 ms on his PC and took 1.7-5.1 s on the emulator, through a
  hand loop over `Mac` (`PBEKeySpec` takes characters and the material is binary). It runs on a thread, behind a
  "preparing" line. On his S26 it took 146 ms (M16).
- **`devices.link`, migration 0007.** One sealed column on the table that already exists, under `is_sealed()` and
  a new AAD, `device/{uid}/{device_id}`. JSON inside: for a PC its certificate's SHA-256, its addresses, its port, the
  protocol, and whether its words sync is on; for a phone its client certificate, the protocol, and whether its backup
  is on. Each device writes only its own row: that is the app's rule, since the server knows only the account. **A row
  that does not open under the account key is ignored, so the server cannot add a device.** Rows change with a
  `changed: devices` broadcast on the account's channel, which `_live_once` must learn to read (it drops any name outside
  `STORES` today), and the PC re-reads them on every account pass. A phone's `platform` is `android-<n>`, and the master
  app's count of installs (`dev\master\sources\server.py`) filters to Windows.
- **The account pass: what runs with every sync off.** Today a person with both syncs off cannot be reached at all.
  `_ensure_lock` runs inside `sync_now`, which returns at once with the gates shut. The worker reads `pending_pairings`
  only once the lock says `have`. `_live_purpose()` answers None, so there is no socket. And `_broadcast` is hard-wired to
  the purpose `sync`, so the lock's own events are refused too. Stage 1 adds `sb.account_pass()` on the same worker,
  ahead of `sync_now`, needing only the `account` gate a signed-in copy already has: the profile, the lock, the pending
  requests, this PC's `link` row and the others'. No store moves in it. `_live_purpose()` answers `account` for any
  signed-in copy, so every PC holds the socket whatever its syncs say, and the events that are no store's (`pairing`,
  `paired`, `signed_out`, `changed: devices`, later `link`) go out under that purpose.
- **What a PC with both syncs off does with the lock.** It makes one if the account has none and holds the one it has,
  unseen. It asks to join another PC's lock only once the account has a phone, so no "Waiting for your other PC" lands on
  the Home of someone who asked for nothing, and Home's "make a recovery key" row waits for a sync or a phone too. A
  phone that finds no lock says "Open DeskIT on your PC" and waits.
- **Home's row** is reused as it stands, in both desks (`deskweb.py:850`, `dashboard._waiting_lock`). Only its words
  change: they say "PC" and now mean any device. `pairings_guard` and the twin check need nothing; the code compare gains
  the lock, above.
- **A phone can approve.** A person with one PC who reinstalls it has no other PC to press Approve, and the phone, which
  holds the key, has no recovery key to offer. Without this that PC waits for ever, never writes its `link` row, and the
  phone loses it. So Settings on the phone reads the open requests whenever it opens and shows Home's row: the name, the
  computed code, **Approve** and **Not now**, with `approve_pairing`'s same checks. `hand_over` in Kotlin is ECDH, HKDF and
  one seal, no new format, and a vector holds it. The waiting PC's row adds "or open DeskIT on your phone". Not the web
  page: its key cannot leave it, on purpose.
- **Forget.** A new RPC, `forget_device(id)`, in 0007: it deletes the row and that device's session, which 0006 makes
  effective at once, and it answers true when no session of that row is left, ended here or over already, as on a PC that
  signed out. A copy older than 0007 never named one, so its row goes and it stays signed in, and whoever pressed Forget
  is told so and pointed at Sign out of every PC. Every device writes its `session_id` claim beside its row for this, `ensure_profile` on a PC, and
  because that column is the client's word, the RPC ends only a session that belongs to `auth.uid()`. Any device of the
  account can do it, a PC or the phone, so it no longer needs that one PC. The PCs drop the anchor on the broadcast.
- **A forgotten device stays forgotten.** A row that opens is not enough. A forgotten phone still holds the account key,
  so a new sign-in could write its row back, and the server could restore a deleted row unchanged, since a seal holds no
  version. So the device that presses Forget adds the target's id and certificate fingerprint to the sealed `forgotten`
  row, and every PC keeps that list in a local file that never shrinks; a device on it gets no anchor, whatever its row
  says. A phone that finds itself on the list wipes the account key, its certificate and its cached rows, and starts
  again as a new device, from sign-in and Approve. A PC that finds itself on it moves its key aside (`vault.set_aside`),
  stops writing its row, which `ensure_profile` would otherwise bring back within a day, and asks to join the same way,
  under a new device id and a new certificate, because the list never lets the old ones back.
- **Sign out on a phone is leaving.** A phone is lent and sold as a PC is not, so it does not copy the PC's "the key file
  stays". Sign out is Forget on itself: its row and session go, the wrapped key, the certificate and the cached rows are
  wiped, and the next sign-in is a new device, with a new Approve. Recordings still in the spool are named first. The
  press is written down before anything else, the words and the recordings go before the first network call, and the
  next `look` finishes a leave the process died under.
- **Out of the account, nothing of the person stays on the phone.** `Traces.kt` is the one wipe and every road out calls
  it: Sign out, Use another account and finding itself forgotten take the Said list, the proposals in the shade and on
  Home, a sentence copied under our label, the pasted line, and the recordings. A session the server ended takes the
  words and the line and leaves the recordings, because they are the only copy and the same account's next sign-in
  finds them; so does a screen lock taken away. Another account signing in wipes too, and the first's key moves aside.
  What `phone-keyboard-door` adds that holds words or an address goes in `Traces.wipe`, the addresses `Link` remembers
  above all, and a send out of the spool stops when `Traces.wipes` moves. The app's own backup and phone-to-phone
  transfer carry none of it (`dataExtractionRules`, measured on Android 14: 3,072 bytes with Said and the token before,
  112 after).
- **The whole phone app moved to the desk's look** (his word, 2026-11-06): space dark, iris purple, one Rubik variable
  file (157 KB in the APK), far fewer words, pages that move instead of jump.
- **Sign out of every PC reaches the door.** The door checks a certificate, not a session, so ending sessions alone would
  leave a phone's door open, and this is Home's answer to a stranger. So the PC that presses it first deletes every other
  device's `link` row, and the doors drop what they cached (`sb.SIGNED_OUT_HOOKS`). A device that signs in again writes
  its row back, unless it is on the list. A phone has no idle socket, so it hears of this at its next request (0006: a
  401, then a refused refresh), not by broadcast.
- **The lock changed.** `Lock.kt` carries `_ensure_lock`'s states, not only the join: it compares `lock_id` on every
  account read. On a difference it stops reading and writing anything sealed and asks on its own screen, with the PC's two
  answers: It was me (the key moves aside, a new request, a new Approve) and It wasn't me (nothing moves, and the screen
  points to Sign out of every PC). Without this every row would fail to open, and "ignored" would make the PCs and the
  keys vanish with no word.
- **The keyboard's other doors.** `Prefs.token` gates `DictationIme.kt:706,797`, `LookupActivity.kt:87` and
  `Notify.kt:61`; they become `Link.ready()`. Until stage 6 the old URL and token keep working beside it.
- **Recovery key on the phone:** not in this stage. It needs scrypt at 128 MiB in Kotlin and in JS, for the rare person
  with no PC to approve from. Such a person has a PC problem first.

#### The second half: the door

**One switch, no transport menu.** D22's `server.transport = off | lan | tailscale` radio is dropped. `server.enabled`
stays the one switch, on the desk's Settings > Phone, and its default becomes on: the phone door now waits for a phone by
itself, so the switch no longer has to be what keeps it shut. `[server]` stays on this PC (`sync.LOCAL_SECTIONS`), so each
PC keeps its own no. It starts and stops
the doors live: `server` is not in `LIVE_SECTIONS` today, so a switch would wait for a restart. The loopback door on
8756 keeps its behaviour, so `tailscale serve` works untouched beside the new road until stage 6 and nothing has to be
cut over on a given day. Two exceptions, both on purpose. The line pasted into the phone for the old road is a key to the
PC, so it goes on every road out of the account, and whoever is still on that road pastes it again. And with the switch
off the door answers only `/health` and `/notify`, so a person's no is not undone by the hook. It also stops depending on
the phone: it runs when the switch is on OR the Claude hook is connected, which closes today's silent hole (§1).

**Two doors, each with one job.**

| Door | Bound to | Who gets in | Lives |
|---|---|---|---|
| Loopback (today's) | `127.0.0.1:8756`, plain HTTP, bearer | This PC only: the Claude hook, `/notify`, and `tailscale serve` until stage 6 | While the switch is on or the hook is connected |
| Phone | all interfaces, `server.phone_port` (8766), TLS 1.2 or newer | Only a certificate listed in the account; anything else is dropped in the handshake | While the switch is on, the account has a phone, and this PC gave its one yes |

So no unauthenticated byte ever reaches `http.server`. `/notify` is not on the phone door: the phone has never called
it (`Transcriber.kt` has no such route). TLS 1.2 stays allowed because Android only has 1.3 from API 29 and `minSdk`
is 26; 1.2 with a client certificate drops a stranger just the same.

**Nothing listens until there is a phone to listen for, and the first listen follows a press.** A copy with no phone in
its account has only the loopback door, as today. The first listen on a PC raises Windows' dialog, so it must never come
out of nowhere. On the PC where he pressed Approve it binds the moment the phone's row arrives, right after his press. Any
other PC of the account, then or whenever it next starts, shows one row on Home instead, "Your phone can use this PC too",
**Allow** and **Not now**, and binds on Allow. A state key remembers the yes, and from then on the door binds at every
start, from the cached rows, with no internet. A PC that stays at Not now simply has no home door; the away road (stage 3)
needs no listener.

**PC side.**

- `phone.py` (new). `identity()` makes the key and certificate once (proved in §1, no wheel), keeps the private key as
  an encrypted `secrets\phone_key.pem` with its passphrase in the secret store as `phone_key_pass`, and answers the
  SHA-256 fingerprint. `publish()` writes this PC's `link` row when anything in it changed. `anchors()` opens the phones'
  rows, leaves out the forgotten, and keeps the sealed rows in a file beside the key, because a PC restarted with the
  internet down must still open its door: §3's "Home: nobody" rests on this. Opening them needs only the account key,
  which is local. All inside `secrets\`, which is already gitignored, so no new folder appears in the checkout.
- `net.py` gains `serve_tls(...)`. `test_only_net_imports_transport` forbids `ssl` and `socket` anywhere else, and that
  rule stays; the listener lives in `net.py`, in its own commit, with one row per connection in the Network log
  (phone name, bytes, never a body). Python's `ssl` loads a private key only from a file path, so the passphrase comes
  through `load_cert_chain`'s password callback, by name. (The probe used a plain temporary file; the real thing must
  not.) The door sets `ssl.VERIFY_X509_PARTIAL_CHAIN`: measured today, three phones whose self-signed certificates
  share one subject give `[ok, SSLError, refused]` without it, because OpenSSL takes the first anchor of that name, and
  `[ok, ok, ok]` with it. Each phone also uses a random subject (Android's default is `CN=fake` for everyone).
- `server.py` gains the door and a route table per door. **The handshake runs on the handler thread, never in
  `accept`**: a peer that connects and sends nothing must not stop the next phone. Timeout 10 s, at most 16 handshakes
  at once. A device removed rebuilds the `SSLContext` (a context can gain an anchor but cannot lose one) and closes
  that phone's open connections.
- A port that is busy really falls through (20 tries) and lands in `state.json` as `server.phone_port`, and goes out in
  the `link` row. This makes the guide's sentence true, and it fixes `server.port` the same way. `paths.DEFAULT_PORT` is
  deleted and AGENTS.md's "port 8757" with it: wiring it up would move the Dev away from `tailscale serve` and the hook.
- `GET /review` is scoped to `source == "phone"` as D22 asked, with `[server] review_scope = "all"` as a developer line,
  which his own Dev sets to keep answering desk proposals from the sofa.
- `settings.py` / `defaults.toml`: the `[server]` comment stops saying "Reachability is Tailscale's job" (it feeds the
  Settings search). `server.phone_port` is a developer line, never on a screen.
- `status()["phone"]` stops being a URL with a token. It becomes `{on, phones: [...]}`. `webdesk._without_phone`,
  `desk_settings._card_phone`, `phone.copy` and the card in `web/src/places/settings/cards.tsx` all change with it.

**Which addresses go in the row.** Every private IPv4 of an adapter that is up, the default route's first, and never
Tailscale's `100.x`, Hyper-V's or WSL's virtual adapters. The phone tries them all at once and keeps the one that
answers. When they change, the PC rewrites its row and the phone reads it next time it is online. mDNS is dropped: the
one case it would save, an address that changed while the house has no internet, is rare and costs only a wait.

**Windows Firewall, which D22 got wrong.** D22 assumed a Private profile. His own PC says Public, and Windows 11 calls
every new network Public unless told otherwise, so most strangers will be there too.

- The first listen raises Windows' dialog, right after Approve, or after Allow on a further PC. A user who is an administrator can allow it, with a UAC
  yes. A standard user cannot, and their answer creates a block rule (Microsoft Learn, cited in item 15).
- The PC cannot test this itself: a connection to its own LAN address never crosses the firewall. Only the phone can
  tell. So when the phone sees the PC online in the account and cannot reach it on the LAN, it says so, and Settings >
  Phone carries **The phone can't connect?**, which runs one elevated `netsh advfirewall` for exactly the real
  interpreter (base `pythonw.exe`, not the venv's launcher) and this port, on the profile the network is on. It first
  deletes that program's block rules, because a block rule outranks any allow rule, so an earlier Cancel would
  otherwise beat the button.
- The per-user installer cannot remove that rule at uninstall (`PrivilegesRequired=lowest`). The card says it stays; it
  names one program and one port and does nothing once the program is gone.
- The Store copy declares the rule in its manifest (`desktop2:FirewallRules`); which executable it must name inside
  the package is M4.
- A rule on Public means the door also stands on a café's Wi-Fi. That is what the client-certificate door is for: a
  stranger there gets a dropped handshake. And when the door is off, nothing listens.
- If the firewall stays shut, stage 3's direct road still works at home, because it needs no listener.

**Keyboard side.**

- `Link.kt` (new): the account's PCs, from their `link` rows, cached so they need no internet, and the race.
  `HttpsURLConnection` with a custom `X509TrustManager` that accepts exactly one leaf (SHA-256 of the DER) and THROWS on
  anything else, and a `HostnameVerifier` that re-checks the same pin rather than returning true: Google's scanner flags
  an all-accepting verifier, and a real check is also simply correct.
- The client key: an EC key in Android Keystore with `PURPOSE_SIGN` and `DIGEST_NONE`, which gets a self-signed
  certificate by itself, handed over by a small custom `X509KeyManager`. No page documents this with
  `HttpsURLConnection`, so it was run: it works on the emulator (§1), and on his S26 the key is made and signs in secure
  hardware (M16); TLS with it on a real phone is the next lane's first test. If a phone refuses, a software key sealed by a
  Keystore AES-GCM key (no library) does the same job.
  `EncryptedSharedPreferences` (D22) is not used: `androidx.security-crypto` is deprecated, whole. The key is created
  with `setUnlockedDeviceRequired(true)` where the phone has it (API 28+), so a stolen, locked phone cannot use it.
- `Transcriber.kt` keeps every route but opens connections through `Link`. The address that answered is remembered per
  network, so the common case has no race at all.
- **The LAN race is bound to the Wi-Fi `Network`.** With mobile data on, Android does not route an app to a Wi-Fi that
  has no internet, so "no internet needed" fails without this: `ConnectivityManager` finds the Wi-Fi network and
  `Network.openConnection()` opens on it. It needs `ACCESS_NETWORK_STATE`, which the manifest lacks. M13.
- **The spool.** Today the audio is one in-memory slot: the next dictation overwrites it and a killed process loses it.
  Every recording goes to app-private storage until a PC has it: capped (50 MB, oldest first, with a notice), kept 7
  days, sent on the next link, and a text that returns to a field that is gone lands in Said with a notification. A
  dictation the cloud key answered stays too, for the PC (stage 2b). This is what "the recording stays safe" means
  everywhere in this plan.
- `SettingsActivity.kt`: the account, the devices it sees with **Forget**, a device asking to join, **Sign out**, and the
  URL and token fields behind "Other ways" until stage 6.
- `strings.xml`, `Recorder.kt`'s comment, `HomeActivity.kt`'s steps: no Tailscale. The error says what is true: "Your PC
  isn't reachable from this network."
- `network_security_config.xml` does not change: cleartext stays forbidden.

**Getting the keyboard (part of this stage, or no stranger ever reaches it).** `release.yml` gains an Android job: JDK
17, the committed `gradlew`, `assembleRelease`, an asset named `DeskIT-keyboard-<v>.apk`, and `apk_url`, `apk_sha256`,
`ime_version_code` in `latest.json`; `server.api_version()` reads those instead of inventing a URL. `ci.yml` gains the
same build on every push that touches `android/`. **The release keystore has to exist first:** his one-way hand-work,
generated once, backed up twice (chapter 12.7), then a GitHub secret. Until then his own phone runs a debug build, which
is all stages 1 to 3 need. If the keyboard installed on his phone today is the old debug-signed build of another key,
it must be uninstalled once. Settings > Phone gets a QR of the download address, made with `segno` (pure Python, no
dependencies, BSD, one small hashed wheel, justified against ~250 lines of QR encoder of our own). **Samsung's Auto
Blocker** stops installs from outside the Play and Galaxy stores, and updates to sideloaded apps, and Samsung's setup
wizard has it on by default (Settings > Security and privacy > Auto Blocker). Google Play Protect can still refuse
after that, so the guide's install page leads with both, and One UI 9, on the S26 since September, also refuses APKs it
judges high-risk, so a microphone keyboard from GitHub is tested on his phone before anyone else's (M11).

**Screens.** Settings > Phone changes and the phone gets a sign-in and a waiting screen, so prototypes photographed on
the hidden desktop go to him first, his standing rule. On the desk: the switch, the devices of the account with Forget,
the download QR, addresses and ports behind one "Details" link, plain words on the surface, as he asked of the
installer, and Home's **Allow** row. On the phone: Sign in with Google; "Approve this phone on your PC", with the code;
ready; the devices with Forget; a device asking to join; the lock changed. An anonymous account has no Google side for
the phone to sign in to, so Settings > Phone on such a PC says to sign in with Google first, which links it and keeps
everything. The Ready page's row
in `firstrun.py` ("…on your Tailscale address") changes with it, and the guide's two `06-phone.md`, `10-faq.md`,
`docs/privacy.md` and `NETWORK.md` follow. `docs/img/06-settings-phone.png` is retaken with the guide's own recipe;
`dev\test_docs.py` holds the guide to the screens the app draws.

**Tests.** `tests.py` (product suite): the phone door drops a client with no certificate before any route runs; a `link`
row that does not open adds no anchor; two phones whose certificates share a subject both get in, and removing one leaves
the other; a forgotten device stays out after its row comes back unchanged; a restart with no network still opens the
door; with both syncs off a phone's request reaches Home, and a further PC asks to join only once a phone exists; a server
that names another lock gives two different codes; no secret reaches `app.log`, `network.log`, `status()` or `problems.env()`; `/notify` answers on loopback and
404 on the phone door; the hook works with the phone switch off; the doors start and stop with no restart; port
fall-through lands in `state.json`. `vault` test vectors in Python, Kotlin and JS, the reversed secret among them. The
invariant at `tests.py:5695` (binds loopback) becomes "the loopback door is still loopback". `dev\user_sim.py` gets a
scenario for join, dictate, forget. Android: `PinnedTrustManagerTest` and a join flow against `dev/android/fake_pc`, with
the process killed between the request and the answer.

### Stage 2 — Faster: the same sentence, at the desk's speed

*Acceptance: a 60-second phone dictation lands about one second after the release, the way it does at the
desk.*

Today the whole recording crosses after the release and the whole of it is decoded then (a 70-95 s desk
clip took 2.05-4.9 s before rolling, 0.9-1.3 s after, `rolling.py`). The desk's answer fits the phone:

- The keyboard streams while he speaks. `Recorder.kt` hands its buffer to a sender thread, a chunked POST
  to `/stream` on the phone door, ending with an explicit end or cancel marker, because a cancel and a break
  look alike otherwise. At 32 KB/s, any link above 256 kbit/s keeps up, which is nearly every link there is,
  and the audio has already crossed when he lets go.
- `/stream` has a handler of its own: `do_POST` refuses a body with no Content-Length, and `handle()` (§6.4)
  takes a finished body.
- The PC feeds what arrives into a real `rolling.Roller` through a small `PhoneStream` class with the one
  method it needs, `chunks_since(mark)`, then finishes through `transcribe_with_head`, the same path as the
  desk: same trim, same repair, same `recent\` and second reading. The chunks must be int16 numpy arrays
  re-sliced to the desk's 10 ms: `rolling._peak` reads raw bytes as silence with no error, so every window would
  be skipped and the speed-up would quietly vanish, and the phone's 128 ms reads would blur where a cut lands.
  `_start_roller` is wired to `self.recorder` and takes the stream as an argument.
- `_last_windows` and `_last_words` are written under the model lock and read outside it (`main.py:6334`,
  `:3518`). Harmless while the phone writes `[]`; with stage 2 a phone dictation and a desk one can cross and one
  person's words be pasted as the other's. They come back from `_transcribe` as values, and a test crosses two
  threads.
- **It adds no new way to lose words.** The phone keeps the whole recording until the answer lands. If
  the stream breaks, it falls back to today's `/transcribe` with the whole WAV. Streaming is only ever an
  optimisation over a path that already works.
- Rules from the desk carry over: nothing reaches the field early, the transcript lands once, whole. The
  English decision is made on the whole recording, as it is now.

Measure before and after, per length, release to text, on Wi-Fi and on mobile data, and write the table
here (house rule 4).

**Compression, measured before it is believed.** Opus at 24 kbps is 7.2% of the WAV (§1). On Wi-Fi that
is worth nothing; on mobile data it saves 1.8 MB a minute and matters on a weak signal. It may cost words,
so it goes in only if the public sets (the six of `MODEL_PLAN.md`, never his recordings as a label source)
show no measurable loss through the real model at the chosen rate, more than one run each because a single
run is a draw (AGENTS.md, the decoder trap). The decoder on the PC has to come without PyAV on an installed
copy (D24). If the loss is real, WAV stays.

### Stage 2b — Keys on the phone, tied to the account, and the backup

*His asks, 2026-11-06: when the PC is off or the link is not there, after about a second an API key does the work;
that stays on unless the person turns it off; the key follows the account, not the device; the phone can add,
change and delete it as the computer can, and a change on either side reaches the other by itself. Acceptance: PC
off, any network with internet: hold, speak, release, and the text lands in the field. A key added on the phone
works on the PC within a second or two, and the other way round.*

Needs stage 1's account join and nothing of stage 3, so it comes first.

**The keys screen, the same on the phone and the desk.** Settings on the phone gets **Your cloud keys**, the desk's
card (`desk_settings_keys.py`, `keyrow.py`) in the phone's own widgets: a row per provider (`secretstore.CRED_NAMES`:
Groq, Gemini), dots when one is saved, never the value, **Change**, **Remove**, **Save and test** with the same one
small request. Nothing about it is the device's. Under it:

- **Add or change on the phone:** the key is tested, sealed under the account key with `vault`'s own format, written
  to its row, and a `changed: vault` broadcast goes out on the account's channel. A running PC hears it and pulls
  it into Credential Manager through `vault.import_keys`, as it does from another PC today (0.15-0.30 s). A PC that
  is off pulls it at its next pass. M14 proved the formats. One PC fix goes with it: `_live_once` calls `_names()` for its
  log line before it pulls, under the purpose `history`, so with words sync on and history sync off the call is refused
  (`net.EgressRefused`, run 2026-11-06), the socket drops and the pull waits for the 15-minute pass. That is a bug of
  today between PCs too. `_names()` moves to the purpose `account`.
- **Remove on the phone:** the row's value becomes `{"v": ""}` through `seal_json`, which `import_keys` reads as a removal.
  Not an empty plaintext: that fails `open_json`, is skipped with a log line, the cursor moves past it, and the key stays
  on the PC with no error. A test vector holds this.
- **Change on the PC:** as today. The phone reads the rows when it opens and at each link. A key already in the
  account is simply there the moment the phone joins, with nothing to press: his "the key moves by itself".
- **Two devices change one key at the same moment:** last writer wins per name, as between PCs.
- **The phone never pushes an empty on its own.** It writes a row only when the person presses something, so the
  trap AGENTS.md describes, a new empty slot read as "the key was removed", cannot happen here: it has no slot.

**Where the key actually is. This is the honest answer to "not on the phone".** The key's home is the account, sealed.
On the phone's storage there are only that sealed row and the account key, itself wrapped by a key in the phone's
security hardware that can never be taken out (Android Keystore), the same shape as DPAPI and Credential Manager on
the PC. When a dictation needs the backup, the row is opened in memory, used for that one request, and dropped.
Nothing readable is ever written down. It cannot go further than that: whoever calls Groq has to present the key,
so for the length of one call the phone holds it. Keeping it on a server instead and calling Groq from there is
worse on both counts (§9): the server could then read the key and hear the audio, which is what the lock exists to
prevent.

**On unless turned off, and seen once.** His call, and it fits a backup. It follows the rule the sync has followed on
the wizard's Ready page since 2026-09-20: what should be normal is on, with one line and the way off in plain sight,
and going on is the yes. The phone's last setup screen, or its first open after the update that brings this stage, shows
the switch already on: "If your PC can't be reached, your recording goes to Groq with your own
key. You can turn this off here or in Settings." **Done** records the `cloud_audio` words and version on the phone. That
consent is the phone's own, as every gate is the device's: the desk's `cloud_audio` governs the desk's calls and its
Withdraw does not reach the phone, so the desk's Settings > Phone shows the phone's switch, read from its `link` row, and
says where it is changed. With no key in the account the same place offers to add one. It is never silent: the status line says "from the
cloud" on every dictation that went that way. This does change the promise "audio never leaves" for the phone, so
house rule 2, `docs/privacy.md`, the guide's `06-phone.md`, `NETWORK.md` and the card's words change with it.

**The second is spent while he speaks, and the road is chosen at the release.** The recording starts at once, whatever
the link is doing. Beside it the keyboard keeps asking for as long as he speaks: the LAN door (milliseconds when it is
there) and, once stage 3 exists, a sealed ping on the account's channel each second, which the PC's Python answers with
no engine. An answer at any moment before the release means the PC, and the PC gets the whole dictation from the buffer,
so a link that wakes at 1.3 s does not lose a sixty-second dictation to the cloud. At the release, a full second of
asking with no answer means the key. For the ping that second counts from the socket having joined, because a cold
keyboard first builds the WebView (446 ms on the emulator), often refreshes its token and joins the topic; stage 3
measures that. So only a dictation shorter than the question itself waits past the release, and at home that is
milliseconds.

**A PC that answered and then went silent.** Link up at the press and no text some seconds after the release (a cold
model can take ~12 s, so the wait is on the link's silence, not on a fixed clock): the same recording goes to the key.
The first answer wins and the second is dropped, so text never lands twice.

**The call.** The keyboard itself, with the PC out of the picture, posts the WAV to
`https://api.groq.com/openai/v1/audio/transcriptions`, model `whisper-large-v3-turbo`, a few dozen lines of
`HttpURLConnection`, no library. Measured here 2026-09-01: 6.6 s of Hebrew in 0.30 s, `x-ratelimit-limit-requests: 2000`
on his free key. Groq's docs today: 25 MB a file on the free tier (a 5-minute WAV is 9.6 MB), and 20 a minute, 2,000
a day, 7,200 audio seconds an hour and 28,800 a day on a plan they call Developer; the free tier's own numbers are
behind a sign-in (M15). Hebrew is not named on that page, though it worked here. Catalogs drift (AGENTS.md), so M15
repeats the call before a line is written. With only a Gemini key, Gemini carries it instead (`transcribers/gemini.py`
is the PC's road for that, 20 a day per model).

**The price, which the setup line and the guide both name.** Accuracy: stock Whisper scores 12.8% against 7.1% on the
WhatsApp set and 8.4% against 5.3% on d1 (light plan, §2), nearly twice the errors, and none of the words DeskIT
learned. The audio is heard by the provider: Groq says it retains nothing by default, and may log inputs for up to 30
days to investigate abuse or reliability. That is why it is a backup and never the first road.

**What it does not do at that moment.** No repair pass, no learned words, no second reading. The recording stays in
the spool (stage 1) and goes to the PC when it is back, as `source: "phone-cloud"`, so `transcripts.log`, the second
reading and the learning still see it.

**"Everything", his word.** Dictation first. Punctuate, translate and lookup from the same key are text, and a second
small step: they need Groq's reasoning-model handling (AGENTS.md, the trap) and punctuation's letter-for-letter check
ported to Kotlin, because a prompt asking nicely is not a guarantee (rule 3).

**Against stage 5.** On the same sets the phone's own model scores 8.8% and 5.3%, better than the cloud on Hebrew and
with nothing leaving, but it is weak on English and heavy to ship. If stage 5 ever lands, it stands before the key on
the ladder, and the person chooses.

Tests: the road decision as a pure table (LAN up, LAN down, ping answered, ping answered late, silent, no key, switch off), first answer
wins, no key value in any log or file, a multipart body against a fake host, and a key added on one side arriving on
the other through a fake account.

### Stage 3 — From anywhere, directly

*Acceptance, in the words of 2026-10-03: "I dictate from my phone on mobile data, away from home, with nothing
installed but the keyboard", and the words came from the PC's model.*

Starts only after M1, M2, M8 and M10 say a direct path exists from his network. Until then the backup carries him away
from home, so nothing is lost by waiting.

- **`link/link.js`** (new, one file, no framework): runs `RTCPeerConnection` and moves frames, with the channel and the
  sealing behind two small hooks, because sealing is three implementations (§6.1): CNG, Kotlin and WebCrypto, held
  together by shared `v1.` test vectors. The PC reads it from `link/` in the product tree. `docs/` and `android/` are
  export-ignored and Pages builds from `docs/` alone, so `docs/link/link.js` and `android/app/src/main/assets/link.js`
  are committed copies, and a test fails when the three differ. One implementation of the connection, three places.
  Tests: two hidden WebView2 peers on the hidden desktop; CI skips them where the runner has no WebView2, and the
  nightly run does not.
- **PC:** `sb._live_once` learns one more event, `link`, on the account's topic; stage 1 already gave every signed-in copy
  the socket. Its read loop has to stay free: today it runs `sync_now` inline, so a ping landing during a pull waits for
  the pass, and the phone has gone to the cloud by then. Pulls move to a thread of their own and pings are answered from
  the loop. Sends go by REST (`_broadcast`) under a new purpose `link`, so `net.py` checks every one. `linkweb.py`
  is the on-demand engine (§6.3). `server.py`'s `handle()` serves the channel.
- **Consent:** `link` maps to the `account` gate. What crosses is sealed and the channel is the account's own, so this
  needs no card of its own. A plain switch on Settings > Phone, **Also from outside home**, on by default. STUN is a
  new party that sees an address, so `NETWORK.md`, the privacy page and Approve's line name it. Offline, or the switch
  off, kills the engine at once, so an open channel does not outlive the yes.
- **Network page:** `NETWORK.md` gains the STUN hosts and a section on the engine, the second thing beside the desk that
  is not `net.py`. Its UDP goes only to the phone's candidates and the listed STUN hosts. `dev\web_census.py` cannot show
  that (psutil sees no remote for an unconnected UDP socket), so a packet capture (`pktmon`, with his UAC yes) checks it
  once before shipping. `net.ALLOWED_HOSTS` gains the STUN names in their own commit, for the resolve only. STUN:
  `stun.cloudflare.com` (free and unlimited, Cloudflare's words) first, Google's second; both are commodities, and no
  terms were found for Google's.
- **Keyboard:** `LinkWeb.kt` puts a 1×1 WebView in the keyboard's view and loads `link.js` from assets with no network
  origin. It starts only when the LAN race fails, and it closes when the keyboard hides. Audio crosses to the page as
  base64 frames: 43 KB/s is nothing, and it needs no `androidx.webkit`. The recording starts at once and buffers,
  whatever the link is doing, so a 2-3 s connect costs no words. Kotlin seals; the page holds a short-lived access token
  for the socket and no key.
- **Survival:** a cellular NAT forgets an idle UDP mapping in about a minute (median 65 s, IMC 2016). ICE's own consent
  checks keep it alive while the keyboard is up, and when it is down there is nothing to keep.
- **Wi-Fi to mobile data mid-dictation:** the channel dies, the phone holds the recording, reconnects, and sends the
  whole WAV over the fall-back route. Slower, nothing lost.
- **Home too:** when the LAN door is blocked (a firewall answer, a guest network, the first router's Wi-Fi) the same road
  carries it, and it needs no listener and no firewall rule: outgoing UDP opens its own way. This is also the answer for
  a standard Windows user.
- **Public Realtime channels go off** on the project once M8 is done: they are on today with nothing using them, and
  anyone holding the public key could spend the project's quota on a topic of their own, which ends in a 402 on every
  API call, new sign-ins included.

**When there is no direct path,** the backup catches it. The other answer, kept open in Q1, is a sealed relay, for people
who want the PC's accuracy from a network with no direct path: `link.js` falls back to sending the same sealed frames on
the same channel. It is about 30 lines. The measured price is 83 ms p50 for a 60 KB frame. The budget is Supabase Free's,
shared by every DeskIT user: 5 GB of egress a month, 2 M messages, each broadcast counting sender plus receiver. Opus at
24 kbps in 3 s frames is about 185 KB and 40 counted messages per minute of speech, so egress binds first: ~27,000
minutes a month in all, or about 90 people at 10 away-minutes a day. WAV would divide that by 14, so a relay requires
stage 2's Opus. A Cloudflare Worker with a hibernating Durable Object has no egress bill (100,000 requests a day, incoming
frames counted 20:1, and it stops at the limit rather than charging), and it is the same 30 lines against another
endpoint: that is the road if strangers ever fill Supabase.

### Stage 4 — The web page: no install

*Acceptance: a phone with nothing installed: open the address, sign in, Approve on the PC, allow the microphone,
speak, and the text is on the clipboard. On an iPhone too.*

It is the same road as stage 3 with a different face: `link.js`, the same channel, the same engine. M8's throwaway
page is its seed, so if he wants the no-install road sooner, this can come right after the engine and before the
keyboard's half of stage 3. Why it does not come from the PC's own LAN address: §6.5.

- **Files:** `docs/link/` in this repository (`index.html`, `link.js`, `app.js`, `worklet.js`, `sw.js`,
  `manifest.webmanifest`), published by the existing `pages.yml`, plain files, no framework, no third-party script.
  The B+ look, words in the browser's language, Hebrew and English.
- **The account, in the page.** Google sign-in by the same PKCE road, returning to the page's own address (on the
  project's allowed list). Then the same request to join, and the same Approve. WebCrypto does all of it, proved
  against the real `vault.py` (M14). The account key is kept as a non-extractable `CryptoKey` in IndexedDB. So the page is a full
  device of the account, with one consequence stated in §6.1.
- **The keys screen and the backup** are the keyboard's, in the page. Groq's API answers a browser (the preflight
  passes from `deskit-app.github.io`: `access-control-allow-origin: *`), so the recording can go straight there.
  M15 confirms with a real POST.
- **The microphone first, then the connection.** A browser hides the phone's address behind an mDNS name until
  capture is granted; both Chromium and WebKit drop that once it is. Then the PC's outgoing checks open its own
  firewall and home traffic stays on the LAN.
- **Capture:** `AudioWorklet` at the default rate, resampled to 16 kHz in JS, PCM over the channel, into stage 2's
  stream. Not `MediaRecorder`: its output would need PyAV on the PC (`pcm.py` is WAV-only without it). The default
  rate stays because Safari's short-sample bug is at custom rates.
- **The text:** a big box, Copy and Share. The press that stops the recording starts a clipboard write with a
  promise, which Safari accepts, so on most phones the text is already copied when it lands. Share needs HTTPS and a
  tap.
- **Staying alive:** Wake Lock while recording. Foreground only: when the phone locks, capture ends, what was said so
  far is sent, and the page says so.

**What a web page can never do,** said plainly on the page: it cannot type into WhatsApp. No web API writes into
another app. So on Android the page offers the keyboard, once, and then stops asking.

**The iPhone** gets exactly this and no more, with three warts: a Home Screen app asks for the microphone at every
launch (WebKit bug 327237, open); a Home Screen app's storage is separate from Safari's, so it signs in and is
approved on its own; and storage can be evicted (`persist()` helps), which means signing in and Approve again. A real
keyboard on the iPhone is out: iOS keyboards get no microphone, the workaround bounces through the main app (Wispr
Flow's road; since iOS 26.4 the user swipes back by hand), and distribution costs US$99 a year, which rule 1 forbids.
He has no iPhone, so **M12** is a borrowed one: tab and Home Screen, home and away.

### Stage 5 — The phone's own model: no PC, no network, nobody

*Acceptance: airplane mode, the PC off, hold, speak, Hebrew text lands in the field.*

This is the only road that literally depends on nobody when away from home, and the only one that works
with the PC off. It stands apart from the link and needs Q2.

- **The model exists:** `ivrit-ai/zipformer2-66m-streaming-he`, CC-BY-4.0 (attribution in `NOTICE`), int8
  72.3 MB. Already wired to the PC on branch `zipformer-cpu` (stage 1 of the light plan, parked).
- **Its numbers (light plan, public sets):** about level with today's shipped model on spontaneous speech
  and podcasts, +25% words wrong on read text, English poor (276 of 916 words right, against night10's
  582). On 4 desktop threads 0.25 s for a 5-10 s clip. It is a streaming model: words can appear while he
  speaks, 1.28 s chunks. On a phone: unmeasured. Nobody has published Snapdragon numbers, so a throwaway
  build timed on the S26 comes before anything else here.
- **The runtime:** sherpa-onnx (Apache-2.0, Kotlin API, hotwords through `modified_beam_search`, untried).
  arm64 only: +9 MB in the APK as a compressed file, ~24 MB once installed. Compare 1.2 MB today. The model
  downloads on first use from a pinned commit with a SHA-256, the way `models.lock` works on the PC, and
  only if he says yes.
- **Rules:** when the PC answers, the PC decodes. The phone's model is a backup and never the default.
  `clean_text` only, no repair pass. The recording stays and goes to the PC when it is back, so the second
  reading and the learning do not lose it.
- **Learned words:** the desk's vocabulary is not on the phone. `vocab.json` can come over the link and
  `vocab.apply` be ported to Kotlin; later.
- **Who decides:** the model session (DeskIT 4) owns which model. Its zipformer training, or a smaller
  shipped model, may change these numbers.

### Stage 6 — Tailscale out

Only after his "works" on stages 1-3 for at least a week of real use. It deletes no data.

- `server.py`: `_tailscale_exe`, `tailscale_name`, the URL with a token, `run_utf8` (nothing else uses it,
  only its test), the comments; `load_token` stays for the hook.
- `tests.py`: `test_subprocess_output_survives_a_hebrew_locale`, the Tailscale half of
  `test_phone_endpoint_never_binds_anything_but_loopback`, `test_phone_host_setting_cannot_open_the_lan`.
- `Prefs.kt` URL, token and `parsePasted`, and "Other ways" in `SettingsActivity.kt`; `dev/android/emu.py`'s
  `-dns-server 100.100.100.100`.
- Words: `defaults.toml` (lines 1232, 1532-34), `config.py:1254-58`, `notify.py:12`, `firstrun.py:337`,
  `docs/strings/wizard.json`, the guide (`06-phone.md`, `10-faq.md`, both languages), `docs/privacy.md`,
  `dev/README-dev.md`, `DISTRIBUTION_PLAN.md` chapter 12 (a line at its head pointing here), D22.
- On his PC, handed to him: `tailscale serve reset`, and uninstalling Tailscale is his call. His global
  notes' "Tailscale is load-bearing" line and the memory files follow.

### Stage 7 — A stranger on Android: the Google side

Nothing here blocks stages 1-6 today. Sideloading is unchanged until Google's 2027 date (no month, Israel
not named).

- **Now:** the APK on GitHub Releases, Auto Blocker off, "install unknown apps". His own phone can always
  use ADB.
- **After Google's date on an unregistered APK:** ADB, or the "advanced flow": developer mode, a restart, a
  one-day wait, a biometric confirmation, a warning on every install, and updates fail if the flow lapses.
  No ordinary person gets through that, so this is the real deadline for strangers.
- **To stay simple after it:** register. Options: Google's US$25 once with a government ID, either a Play
  account or the Android Developer Console; or the free limited tier (no ID, a payments profile and 2-Step
  Verification, a device cap Google's own pages give as both 20 and 50), which covers friends and no one
  else. The account holder has to be an adult with an ID. Q3.
- **Play itself:** 12 testers for 14 straight days on a new personal account, target API 36 (the build is on
  34), a privacy policy, the Data safety form, where the account's data and stage 2b's backup both have to be declared. Target 36 and not 37: at 37 Android asks for the local-network
  permission, which is a runtime prompt with a Play declaration behind it. At 34 or 36 the phone gets it
  without a prompt, on Android 17 too. Not needed until someone wants Play.
- **The iPhone:** no free road for a keyboard. Stage 4's page is the answer (§6.5).

## 6. The details a builder needs

### 6.1 Who can get in, and what each party can learn

- **Identity is a key, and the account says whose.** Each device has its own certificate. A device is admitted by
  a person at a device that holds the key, comparing a code, once, through the lock. After that the two recognise each other on every
  connection: at home by TLS with both certificates taken from sealed rows of the account; away by a hello sealed under
  the account key, carrying that session's fresh DTLS fingerprints, so nobody can sit in the middle and no long-lived
  WebRTC certificate has to be kept or renewed. No bearer token on this road: that stays on the loopback door for the
  hook.
- **A phone is a holder of the account key.** That was his decision of 2026-09-20 ("the phone becomes a holder") and it is
  what makes keys and history follow the account. It means a phone can open what the account holds. On the phone the
  key is wrapped by a Keystore key that cannot leave the hardware and, where the phone has it, cannot be used while the
  phone is locked.
- **Keys stay where they were made, and move only sealed.** The PC's private key in `secrets\` under DPAPI, the phone's
  certificate key in Android Keystore, the web page's account key as a non-extractable `CryptoKey`. A secret goes into a
  variable only in `secretstore.py`, `net.py` and `vault.py` (AGENTS.md): `net.serve_tls` takes the passphrase by NAME,
  sealing happens in `vault.py`, and `phone.py` handles keys only the way `vault.py` does, with a test holding its
  imports narrow. The PC's engine never sees a key: it gets plain SDP from Python, and Python seals. On the keyboard
  Kotlin seals, so the WebView holds none either. Only the web page, which has nothing else, seals in JS.
- **The account server learns:** that a device joined, its name and platform, when devices spoke, sizes, and IP addresses
  as any server does. Of what this plan carries it never learns a key, a dictated word, a certificate's meaning, or a
  private address: all of that is sealed. (The learned words and settings that sync are plain there today; §3.) It cannot
  hand a joining device a lock of its own, since the device waits for its person's press on a code that binds the lock
  (stage 1). It cannot swap the
  lock later, since a device never trusts a changed `lock_id` without asking the person (2026-09-23). It cannot add a
  device, since a row that does not open is ignored, and it cannot bring back a forgotten one past a PC that saw the
  Forget. A PC that was off through a Forget learns of it from the server, so there a dishonest server could hide it: a
  limit, stated here.
- **A STUN server learns:** an IP address and port, and that WebRTC was used. Nothing else passes through it.
- **The provider of a cloud key learns:** that one recording, when the backup runs. Named at setup, on the status line
  and in the guide.
- **The web page is code served by GitHub, and it is a full device.** Whoever controls that repository could ship a page
  that listens, or that reads the account key out of use. That is no new kind of risk: the PC's updater trusts the same
  GitHub account. It is a faster one, because a page needs no install. So: two-factor sign-in on that account (to be
  confirmed, the API does not say), the page published from `main` by `pages.yml` and therefore through the same branch,
  PR and merge as everything else, no third-party script and no analytics on it ever, a strict Content-Security-Policy
  `<meta>`, and the guide says it plainly: the keyboard is the stronger road, and a page can be signed out.
- **The door on a Public network.** With the client-certificate door nothing is parsed before authentication, so a
  café's Wi-Fi gets a dropped handshake. A scanner learns that a TLS port asked for a certificate, and it sees the door's
  own certificate, as any client can: the name in it is random hex and says nothing of DeskIT, but it is the same one on
  every network, so the same PC can be told from others. Nothing there opens anything. Connection floods cost a thread
  for at most 10 s, capped at 16, and one address holds at most 4 of those.

### 6.2 The account's channel

Measured: `user:<uid>`, broadcast to arrival, 0.15-0.30 s between his two copies (2026-09-20). Today, two sockets on a
Realtime topic: 2 KB messages 20 of 20, p50 66 ms, p95 67 ms; 60 KB 12 of 12, p50 83 ms. Then the whole road from plain
browser JavaScript, two hidden windows on this PC, real Realtime, real STUN: joined, offer, answer, channel open 1.06 s
after the page started. Those probes used a public topic because a probe has no session. The real one is the account's.

- **Topic:** the existing private `user:<uid>`, with the policies of 0003 and the session check of 0006. Only the
  account's own devices can join or send, so nothing here needs anonymous sessions or public channels.
- **Messages:** one new event, `link`: `{from, to, s}`, where `s` is a `v1.` seal under the account key with the AAD
  `link/{uid}/{from}/{to}`, and inside it a protocol version (the page goes live at merge and PCs at release), a nonce, and
  a kind: `ping`, `pong`, `offer`, `answer`.
- **`ping` is what makes the one second possible.** The PC's Python answers it with no engine, so the phone learns the
  PC is there, or not, without starting anything.
- **No clocks:** a nonce already seen is dropped, and a replayed offer that gets through buys only an answer nobody can
  use, since the DTLS fingerprint in it belongs to the real phone.
- **Who hears what:** every device of the account hears every `link` broadcast and each counts against the monthly
  messages, sender plus receivers. A connection is about six messages per device online. Negligible, and said here so a
  chatty future feature does not assume otherwise.
- **The PC's end:** the live socket (`sb._live_once`), read only. Every send is a REST broadcast under the purpose `link`,
  so `net.py` asks the gate each time.
- **The phone's end:** the socket lives in the hidden WebView or the page, for as long as a connection is being made, with
  the access token. It does not stay open, and phones do not count against the cap of 200 while idle.
- **Moving away from Supabase** would mean a release: `net.ALLOWED_HOSTS` is frozen and `SUPABASE_HOST` is one value. The
  account would have to move anyway, so this is no separate risk.

### 6.3 The engine: WebRTC with nothing new installed

Both ends already own a WebRTC engine, and it was proved today:

| Probe (2026-11-06) | Result |
|---|---|
| Hidden WebView2, cold process to open data channel, two peers in one page | 1.9 s; 4.8 MB/s; 222 MB private while alive |
| A WebView owned by a real `InputMethodService`, emulator (WebView 113, Android 14), through the emulator's NAT, to a hidden WebView2 on this PC, meeting through a mailbox | Connected. Channel open 1.46 s after the page started, 2.34 s after the keyboard view was created; `WebView` built in 446 ms; 1 MiB up and the text back in 682 ms |
| The keyboard hidden and shown five times, the WebView kept, a new connection each time | Came back every time: channel open 0.4-1.6 s, the answer 20 ms later. The keyboard's process: 30 MB before the WebView, 70 MB with it, flat over the rounds |
| Candidates | The keyboard's WebView showed its real address with no flag. WebView2 shows a `….local` name unless started with `--disable-features=WebRtcHideLocalIpsWithMdns`; with it, `192.168.68.50` and no virtual adapter |
| The desk's exact flags (`webdesk.BASE_ARGS`, the feature merged into its one `--disable-features`), STUN given as IP literals | Reflexive address gathered: his public address, the SAME port as the local one on both STUN servers (65505 and 65507), so both routers preserve ports. By name, with the browser's DNS shut, only `host` came back, as intended |

So one file, `link.js`, does the connection in all three places: the web page, the keyboard's hidden WebView,
and a hidden WebView2 on the PC. The APK grows by a few KB of JavaScript and the installer by nothing. The
sealing around it is three implementations held together by test vectors (§6.1).

- **On the PC, on demand.** `linkweb.py`, a process of its own, because pywebview must own its main
  thread. `main.py` spawns it when a sealed offer opens, and it exits after five idle minutes. Idle cost:
  nothing. Cold cost: ~2 s, once, and the phone is buffering audio meanwhile.
- **Its flags** are `webdesk.BASE_ARGS` with the candidates feature added to its one `--disable-features`.
  `--host-resolver-rules="MAP * ~NOTFOUND"` stays: Python resolves the STUN hosts and hands the page IP
  literals, so the engine makes no DNS query of its own (measured above). Its cache is `paths.WEBVIEW_DIR`
  + `-link`: his open desk holds the normal one (0x800700AA otherwise). `dev\web_census.py` runs over it
  before it ships.
- **The bridge:** `pywebview.api` into the engine process, then a token-gated route on the loopback door to the
  app. Never `control.py`: its messages stop at 64 KB, its handlers must not block, and the whole-WAV fall-back
  is 9.6 MB while `/translate` can wait 180 s. The engine's page is a string in `linkweb.py` around `link.js`,
  because `*.html` is export-ignored: a `link/index.html` would work in the Dev and be missing once installed.
  `linkweb.py` is started by path, so it carries `main.py`'s four-line
  `sys.path` guard and joins `test_entry_points_put_their_own_folder_on_sys_path`, and it starts through
  `launch.py` so its stderr lands in `spawn.log`.
- **The firewall:** WebRTC opens its own way with outgoing UDP. The only inbound rules for `msedgewebview2.exe`
  on this PC are the ones its installer wrote, UDP 5353 for mDNS on every profile, 38 of them, one per version.
  So nothing else comes in unasked, the PC has to send first, and that is why it must know the phone's real
  address (stage 4, microphone first). No dialog is expected, as browsers do this all day; M8 watches.
- **If it fails a real phone.** The fallback is libdatachannel in a small DLL on the PC and a JNI build on
  Android: fewer megabytes of RAM, a few MB of binary, a build step on both sides, and a new thing for
  antivirus to look at. Only if WebView fails on real hardware.

**Things the probes did not prove,** all in stage 0's M8: a real phone on a real carrier; the mDNS name a
browser page offers at home; a WebView current enough to be representative (the emulator's is 113); Samsung's memory management on a
hidden WebView, which adds 40 MB to the keyboard only while it is away from home.

### 6.4 One set of routes, two roads

`server.py`'s handlers read `self.rfile` and write `self.wfile` today. Stage 1 splits them into
`handle(route, body, phone) -> (status, payload)`, which both the HTTP doors and the WebRTC channel call,
so `/translate`, `/punctuate`, `/review`, `/review/decide` and `/lookup` exist once; `/stream` has its own
handler on each road, around the same `PhoneStream`. On the channel: one reliable ordered data channel, JSON text frames `{id, route, body}`, binary frames for the
open stream's audio. Everything the keyboard does at home it does away.

### 6.5 Why the web page lives on GitHub and not on the PC

The obvious road is a page served by the PC at `https://192.168.x.y`. It fails, and the failure is the reason
for the whole design. Checked in browser source and specs, 2026-11-06 (Chrome Android 157, Safari 27.2):

| Road | Result |
|---|---|
| Plain `http://192.168.x.y` page | Not a secure context, so no microphone. Dead |
| Self-signed `https://192.168.x.y` page | Chrome: a secure context after a full-screen warning that returns every week; no service worker; not installable. iOS: reports disagree on whether it works at all. Rejected |
| A real certificate for each PC | §9 |
| Public page, `fetch` to `http://192.168.x.y` | Chrome 142+ on Android allows it after a permission prompt (Local Network Access), Safari blocks it, Firefox has no exemption. Android only, and a fourth door on the PC |
| Public page, WebTransport with a certificate hash | Certificates must live under two weeks, so a pinned hash goes stale; a real iPhone never reached ready; it needs a QUIC server. Rejected |
| **Public page, WebRTC data channel** | Not covered by mixed content. Chrome's Local Network Access check for WebRTC exists and is off by default; if it turns on, it is one prompt. A real iPhone on Safari 26.6.1, tab and Home Screen, opened a channel in 220-380 ms, 50 of 50 echoes (a public report of 2026-11-06, with signalling, over Tailscale addresses, so M12 still has to run on plain Wi-Fi). **This is the road** |

**"WebRTC Direct" (libp2p), noted for later.** A browser can open a channel knowing only an address and a
certificate hash, with no signalling at all; v2 of the trick is in go-libp2p and js-libp2p. That would make the
page work at home with no internet. It needs an ICE-lite server on a fixed UDP port, so a firewall rule and a
native library on the PC, and it is untested on a real iPhone. Not needed while the account's channel exists.

**In-browser speech recognition, also later.** sherpa-onnx has WASM builds (the `.wasm` is ~10 MB, threads were
removed upstream, so COOP/COEP is moot), so stage 5's model could run in a page with no PC at all. No published
phone speed exists, and iOS memory is a real risk (a 2 GB kill reported on an iPhone 16 Pro Max). Only after
stage 5 has numbers.

## 7. The house rules, one by one

| Rule | How this plan stands |
|---|---|
| 1. All-free | GitHub Pages, Supabase Free, public STUN, a person's own free Groq key, all no card as far as checked. No paid relay, no VPS, no domain. The one money question is Google's registration, Q3 |
| 2. Audio never leaves the machine | Stage 1: phone to own PC on the LAN. Stage 3: phone to own PC, encrypted end to end, no server in the path. Stage 5: nothing leaves the phone. Changed by him, 2026-11-06: the backup sends audio to the person's own provider when the PC cannot be reached, on unless turned off, shown once at setup and on the status line of every such dictation. This rule's wording, `docs/privacy.md` and the guide change with stage 2b. A relay would carry sealed audio, which is Q1, and Tailscale's DERP does exactly that today |
| 3. Never rewrite the user's words | The same `_improve` and `_is_safe` on the PC. Stage 5's model gets `clean_text` only, and no repair pass until that has its own guard |
| 4. Measure | Stage 0, and a before-and-after table per stage |
| 5. ~1 s to text | Stage 2's whole purpose; the home road must not add to it (TLS handshake measured 1.8 ms on loopback, re-measure on Wi-Fi) |
| 6. `config.toml` comments | `[server]`'s comment is rewritten by hand in `defaults.toml`, keeping its form; values only through `config.set_values()` |
| 7. No turn ends mid-task | Unchanged |
| 8. Hidden desktop, muted | Every probe above; the one thing that must show on his screen is M4's firewall dialog, and he is told first |
| 9. How a change travels | One branch per stage, his Dev check, a PR, a release on its own rhythm. A week that touches the installer gets a beta first |

## 8. Holes, one by one

Every way this can fail that we could think of, with what happens. "Stage" says who closes it.

**Network at home**

| Hole | What happens | Answer |
|---|---|---|
| Windows calls the home network Public (his does) | The listener is blocked or the dialog offers the wrong profile | Stage 1: the phone says so, **The phone can't connect?** on Settings > Phone fixes it, and the door refuses strangers on any network |
| A standard (non-admin) Windows user | The dialog cannot allow, and may write a block rule | Stage 1 says so plainly; stage 3's road needs no listener and no rule |
| The phone is on the first router's Wi-Fi, the PC behind the second (double NAT; his home could be this) | "Same house", different network, LAN addresses unreachable | Stage 0 checks his. Stage 3 treats it as "away" and it works. Until then the error says "not on the PC's network" |
| Guest Wi-Fi or AP isolation | The phone cannot see the PC at all | Same answer as above; the message names guest networks |
| The PC's address changes (DHCP) | The stored address stops answering | The PC rewrites its row and the phone reads it when online. With the house's internet down as well, it waits |
| Several adapters (VPN, Hyper-V, WSL, Tailscale) | A wrong address first | The row carries every private adapter, default route first, virtual ones excluded, and the phone races them |
| The PC moves networks (a laptop) | The PC is on a new subnet | A new address in the same way; identity is the certificate, never the address |
| The phone runs a VPN | LAN may be unreachable | Falls to stage 3; the message says a VPN may be in the way |
| Wi-Fi with no internet and mobile data on | Android keeps apps on mobile data, so LAN addresses fail | Stage 1 binds the race to the Wi-Fi `Network`; M13 |
| Port taken by something else | Today: the phone silently stops | Stage 1: real fall-through, recorded, in the `link` row |
| Dev and an installed copy on one PC | Both want 8756, as both hold the same default today | Each copy is a device of its own in the account, with its own row and port; the phone sees both and uses whichever answers. `paths.DEFAULT_PORT` is deleted in stage 1; AGENTS.md's "port 8757" is corrected |

**The PC's state**

| Hole | What happens | Answer |
|---|---|---|
| The PC is off or asleep | Nothing can answer; Tailscale could not either | Stage 2b's key about a second later, unless turned off; otherwise the spool holds the recording until the PC is back, and the keyboard says so before he speaks (`checkHealth` already does) |
| Hibernate or sleep at home | `awake.py` already holds the machine awake while the app runs | Wake-on-LAN from the phone is possible at home only, and only where the machine supports it: later, if he asks |
| DeskIT is not running | Same as off | Start with Windows covers it; nothing more |
| Model off / loading / unloading | `MODEL_OFF_WORDS` comes back as a typed error | The keyboard shows it; a **Start the model** button on the phone is small work over the existing `load` verb, on request |
| The desk's account lock (`locked()`) | The phone is refused with `LOCK_WORDS` | As today, and the backup carries that dictation |
| Paused for a game (`room.py`) | The English model and maybe more are gone | The phone gets the same answer as the desk |
| A phone dictation while he dictates at the desk | Two recordings want one decoder, and `_last_windows` is read outside the lock | Decodes queue under the model lock; stage 2 returns windows and words as values, and a test crosses two threads |
| Two PCs of the account both answer | The phone races them | Whichever answers first takes the dictation, and one with its model off is passed over for the other |
| A PC restarts with the internet down | It cannot read the account | The door binds from the cached rows (stage 1), and opening them needs only the local key |
| Both syncs off | Today no lock, no socket, and a phone's request never reaches Home | The account pass (stage 1): the lock, the requests and the `link` rows need only the `account` gate |
| A PC on an anonymous account | It has no Google side for the phone to sign in to | Settings > Phone says to sign in with Google first, which links the account and keeps everything |

**Identity and loss**

| Hole | What happens | Answer |
|---|---|---|
| Lost or stolen phone | It holds the account key and a key to the dictation door | Both are unusable while the phone is locked, where a screen lock existed when the keys were made, on Android 9 and up (`setUnlockedDeviceRequired`). A phone with no screen lock works in full and says nothing, because Android refuses such a key there; a lock added later protects the keys only after Sign out and back in, until `phone-keyboard-door` upgrades them by itself; Android 8 has no such key at all. **Forget** from any device of the account deletes its row and session at once: the door closes and the account stops answering it. What it already holds cannot be un-held: there is no way today to change the account key, so a phone taken while unlocked is a real loss, and the cloud keys should then be changed. Forget stops the app, not someone who took the key out of the phone and also holds his Google sign-in, so then his Google password changes too |
| Someone else asks to join | They need his Google sign-in first, and then his Approve against a code | Not me (**Not now**), as between PCs; the twin check holds |
| A dishonest server at the join | It could hand the new device a key of its own | The code binds the lock, so the two screens differ, and the new device keeps nothing until its person presses Same code (stage 1). This closes it for a PC joining too |
| A forgotten phone signs in again, or the server restores its row | The row still opens | The `forgotten` list, kept on every PC and never shrinking, and the phone wipes itself (stage 1) |
| The phone is sold or lent | The key, the door's certificate, the Said list, a pasted address and token would stay on it | Sign out on a phone takes all of them, and recordings still waiting are named first, then go too (stage 1, `Traces.kt`) |
| A second person signs in on a PC | The first's history, words, settings, cloud keys and queued reports would go up under the second, sealed to the second's devices | `sb._take_over`. The first account a PC ever has takes what is here, the same account back loses nothing, and a different one starts past everything: the history floor rises, left pairs and settings stay out of the rows and the blob, the cloud keys stay in the slot and are never sealed up, queued reports wait for their account. The PC's one copy is not kept per person: a second account's first pull replaces settings and words the first never synced (one `.bak`), and one slot holds one key. Consent stays per PC, so the second account inherits the gates the first opened, and its sign-in press is its yes to the syncs; a card of its own would be new, and it is left for a day someone needs it |
| Android kills the keyboard while he walks to the PC | The join's private half would be gone | Sealed by the Keystore for the request's 15 minutes, so the same code and the answer survive; the phone sweeps its own requests, so no twin appears |
| PC reinstalled | A new certificate, and no key until it rejoins | It joins the lock as a new PC: approved by another PC, by the recovery key, or by the phone (stage 1), which is the only other holder a one-PC person has. Then it writes its row and phones pick it up with nothing to do |
| Windows account reset | DPAPI cannot open the passphrase | Treated as a new identity, never a crash: `load_token()`'s existing pattern |
| Certificate expiry | The phone's pin compares a hash and ignores dates, and Android's self-signed certificate runs to 2048 | Nothing expires. `rotate()` exists for a lost key, not for time |
| Two phones | With one shared subject OpenSSL refuses the second (measured) | `VERIFY_X509_PARTIAL_CHAIN` and a random subject, stage 1 |
| The name on Home's row | `Build.MODEL` reads "SM-S948B" | The device's own name (`Settings.Global.DEVICE_NAME`, no permission) |
| A PC left waiting to join | A new request every 15 minutes is a card and a cue on every device, for as long as it is left, and a code that changes under whoever is comparing it | The same request goes up again: the same id, key and code in a new row, because `pairings_guard` freezes `expires_at`. Every device knocks once per id, so nobody is rung twice. Not now holds for the rest of the request's time, and what was handed over before the press stays where it is |
| A refresh on a locked phone | A refresh spends the old token on the server, and a phone that cannot seal could not keep the new one | It does not refresh. Keystore is asked first, with a one-byte seal, because KeyguardManager still reads "locked" for a moment after the unlock; the old token stays good until the phone is opened |
| A gateway's error during a refresh | Any 4xx used to end the session and take the person's words with it | Only the auth server's own refusal does, off its `error_code` or an older server's "Invalid Refresh Token", and a second 401 needs PostgREST's own code. A PC signs out on any 4xx there and loses no words; that is outside this plan |
| No device with the key is on when a phone joins | Nobody can approve | The request waits 15 minutes and asks again; the screen says to open the PC. Recovery key on the phone comes later |
| A phone signed in to another Google account | It sees no PCs | The screen names the account it is on |
| Months offline, the session expired | The account refuses the old session | The phone signs in again; the account key it holds stays, so no second Approve, the way a PC comes back, unless it was forgotten meanwhile |
| Sign out of every PC | The phone has no idle socket, and the door checks a certificate, not a session | The other devices' rows go first, so the doors drop them (stage 1). The phone learns at its next request (0006), stops and says so; signing in again brings it back, unless it was forgotten |
| The account's lock changed | `lock_id` no longer matches, and every sealed row stops opening | `Lock.kt` compares it on every account read. As on a PC: sealed stores pause and the phone asks, with the PC's two answers; the server never decides which key a device trusts |
| New keyboard, old PC | `/stream` answers 404 | The fall-back to `/transcribe` |
| Old keyboard, new PC | It speaks to the loopback door through Tailscale | Works until stage 6, which raises `ime_min` (12.9) |

**Things this plan must not break**

| Hole | Answer |
|---|---|
| The Claude hook posts to `127.0.0.1:8756` with the phone token | The door and its bearer stay. It now also runs when only the hook is connected (stage 1), which fixes a silent hole of today. Chapter 12's "hook token" split is not needed for this plan |
| `test_only_net_imports_transport` | The TLS listener lives in `net.py`, in its own commit |
| "A secret value goes into a variable in `secretstore.py` and `net.py` and nowhere else" | §6.1: by name into `net.py`, sealed in `vault.py`, never in the engine |
| `NETWORK.md`, `test_network_md_matches_net_py`, `net.PURPOSES` | Every new host and purpose lands in its own commit with the page |
| D12's promise that nothing listens beyond loopback | It changes on purpose. `docs/privacy.md`, `NETWORK.md` and the Settings page say so; the phone door opens only after a phone joined |
| `docs/privacy.md` says the lock's key is held by "your own PCs", and a syncs-off copy holds no socket today | Its words become "your own devices", and it says every signed-in copy keeps one socket that carries nothing personal |
| The vault's rule that a fresh slot must never push an empty | The phone has no slot and writes only on a press |
| Home's lock row says "PC" | Its words become "device"; nothing else in it changes |
| "Offline" (`net.offline`) | Offline stops every outgoing call, so the account's channel goes silent, while the LAN door keeps answering: it is inbound and local. The switch's sentence says this. So a Forget pressed on another device is heard here when Offline ends; a Forget pressed here, and the switch, work at once. Withdrawing the `account` consent does close the door, because that is a person saying no to what the door hears through |
| `paths.OWNER_DATA`, recordings, `corpus\` | No store is wiped or rewritten. Phone recordings go to `recent\` as they do today. Removing Tailscale deletes no data |
| The web desk's network census (`dev\web_census.py`) | It runs over the engine too, for TCP; UDP destinations need a packet capture (stage 3) |
| Tk has no bidi; a PNG QR is language-free | Words on the panel follow the desk's rules |

**Away from home**

| Hole | What happens | Answer |
|---|---|---|
| No direct path (hard NAT at both ends; UDP blocked at a café or office) | WebRTC gives up after ~10 s | The backup; with none, the spool. The status line names the cause |
| The account server is down, paused or full | A new connection cannot start; an open one keeps working; home does not notice; the backup still runs from the cached sealed key | `supabase-keepalive.yml` already stops the pause |
| Supabase's 200 concurrent connections | Every running PC with a sync on holds one socket today and every signed-in one does from stage 1, so that cap on DeskIT exists with or without the away road | Phones hold one only while connecting. A scale question for later |
| STUN down | No reflexive address | Two hosts; LAN and IPv6 candidates need none; the list can change with no update |
| WebView old or disabled on a phone | No away road | Home still works; the keyboard says so |
| WebView2 missing on a PC | No away road | Home still works; said on the panel |
| The engine crashes | The channel drops | The next sealed offer starts it again; the phone holds the audio |
| An update while the engine runs | Inno's Restart Manager has to close `linkweb.py` too | A stage 3 test, with `launch.py`'s spawn log for its stderr |
| The Store copy | A hidden WebView2 and a pipe inside the package | Walked on the Store copy before it ships; AppData is virtualised there |
| The second reading, Lookup and Keep / No away from home | The channel lives in the keyboard's view. `Notify.poll`, `LookupActivity` and `ReviewReceiver` run with the keyboard down, so away they have no road | At home they use the LAN door as before. Away, `LookupActivity` can host the same hidden WebView (a stage 3 test), or use the cloud key; polling waits for the next connection; a Keep / No on the notification is queued and sent then |
| A replayed hello | The PC opens it again | No clocks are trusted: a seen nonce is dropped, and the fingerprint inside belongs to the real phone |
| Offline, or the switch off, with a channel open | It would outlive the yes | Both kill the engine at once |
| Chrome turns on its WebRTC local-network check | One prompt on the web page at home | Accepted; the page has the words ready |
| `net.py`'s promise | WebRTC's UDP does not pass through `net.py` | Said in `NETWORK.md`; the engine has no DNS of its own; a packet capture checks the rest once |

**The cloud key and the backup**

| Hole | Answer |
|---|---|
| The person has no key | The setup line offers one; otherwise the plain message, and the recording waits in the spool |
| The free quota runs out, or the key is revoked | Groq's error in plain words; the recording waits |
| No internet at all | Nothing can run; the recording waits (only stage 5 would help) |
| The PC is only slow, not gone | The link is up, so the keyboard waits for the PC; only silence on the link moves it to the key |
| Both answer | The first wins; the second is dropped, and the text never lands twice |
| The person never meant audio to leave | It is shown once at setup and on every such dictation, and one switch stops it |
| A key changed while the phone is offline | It uses the sealed copy it has; a dead key fails in plain words and the next read fixes it |
| Two devices change one key at once | Last writer wins per name, as between PCs |
| Sync is off on the PC | The PC neither pushes nor pulls keys, so the phone and the PC do not share them; the phone's screen says so, read from that PC's `link` row, and its own edits still reach other phones |
| The key on a stolen phone | Sealed at rest and unusable while locked; Forget stops further reads; change the key at the provider if it was unlocked |
| The audio itself | Readable by the provider. It is a backup and never the first road, and the status line says so each time |

**The web page**

| Hole | Answer |
|---|---|
| It cannot type into other apps | Copy and Share. On Android it offers the keyboard once |
| The phone locks mid-sentence | Wake Lock; if it locks anyway, what was said is sent |
| A browser hides the phone's address | Ask for the microphone first (stage 4) |
| The page's address ever moves | Storage is per origin, so everyone re-pairs. It is chosen once: `deskit-app.github.io` |
| The cached page is stale | The service worker carries a version; a new one applies on the next launch, never mid-dictation |
| A malicious page update | §6.1: a stated risk, the same root as the PC's updater, and the keyboard is the stronger road |
| Data on a shared phone | The page is signed in to the account, so it signs out when told, and Forget works from any device |
| iPhone storage evicted | Sign in and Approve again |

**Android and getting the app**

| Hole | Answer |
|---|---|
| Auto Blocker on | The guide's first step on Galaxy phones; M11 |
| One UI 9 refuses the APK as high-risk | Tested on his S26 before anyone else (M11). If it refuses: ADB for him, and a real answer before strangers |
| The Android 17 local-network prompt | Only for targetSdk 37. Stay at 34-36: implicit grant, no prompt, on Android 17 too. A blocked LAN looks like a timeout, so never go to 37 without a plan |
| Samsung puts a sideloaded keyboard to sleep | A keyboard on screen is bound as foreground by the system. "Never sleeping" only if a real fault shows |
| `targetSdk 36` for Play | Not needed for sideloading; rides with stage 7 |
| Opus on the phone | Android 10+ only; older phones keep WAV, and the PC must take both |

## 9. What was looked at and left out

| Road | Why not |
|---|---|
| A secret QR per PC, a pairing door, per-phone link keys (the first version of this plan) | It worked, and it paired devices with each other. He asked for everything around the account. The account does the same with less: no new door, no second key system, and a second PC needs no step |
| Keeping the cloud key on a server, which calls the provider for the phone | Then "not on the phone" would be literally true, and the server would hold a readable key and hear the audio: exactly what the lock exists to prevent. It also makes every backup depend on one more machine |
| Keep Tailscale, one click (`tailscale serve` run by the app) | Still an account and a VPN app on both ends, which is the thing he asked to leave. It stays untouched until stage 6 only so nothing breaks meanwhile |
| Headscale, NetBird, ZeroTier, Nebula (a literal "our own Tailscale") | Each needs a public machine with a domain or fixed IP and a command line, and the phone still needs a VPN app. Headscale's HTTPS support is unreleased and needs a DNS provider. ZeroTier's controller is no longer open source and embedding it counts as commercial. A stranger could not do it |
| Iroh (a library that dials by public key) | The closest fit on paper. No Android artifact, a 14.8 MB DLL, and its free public relays are rate-limited and "not for production" |
| aiortc | `av` is a hard import even for data channels: 70.66 MB with x264/x265, which D24 keeps out of the installer |
| Bundling libwebrtc on Android | 5-6 MB compressed, against 0 MB through WebView (measured working). The fallback if real hardware disagrees, with libdatachannel (2.27 MB in OBS's build) first |
| Opening a router port (UPnP, NAT-PMP, PCP) | Measured useless on his double NAT. CERT/CC and the NSA advise UPnP off. Strangers vary. It can return as one more ICE candidate if measurement ever shows it matters |
| A public certificate for the PC (Let's Encrypt, DNS-01, Plex's way) | IP certificates need a CA that can reach the address, so never a LAN one, and they live 160 hours. DNS-01 needs a domain or a broker with a shared token. Plex has a CA deal. Every name lands in public CT logs. The keyboard does not need one and the page does not either |
| A page served by the PC itself, WebTransport, plain `fetch` to the LAN | §6.5, road by road |
| A private CA installed on the phone | A frightening prompt and many steps, and it trusts more than one PC |
| Cloudflare Tunnel | Cloudflare terminates TLS, so a third party could read the audio; `cloudflared` on every PC; quick tunnels' addresses change. Fails rule 2 outright |
| Mainline DHT as the meeting point | Truly ownerless, and it would answer "depends on nobody" for the introduction. It needs a DHT client and ed25519 in Python and Kotlin, has no browser route, and nobody has published latency or survival numbers. The account is the centre now, so it would buy little |
| A cloud decoder as the first road | Stock Whisper is the worst of the options on Hebrew (12.8% against 7.1% on the WhatsApp set, light plan). As the backup it is stage 2b, his ask |

Comparable products, for the record: Syncthing is the model this plan is closest to (a discovery server
that sees no content, third-party STUN, relays as a last resort). RustDesk does the same with its own
self-hostable pair. LocalSend and KDE Connect stop at the LAN, and pin self-signed certificates the way
stage 1 does. Immich and Moonlight tell the user to bring a VPN. Home Assistant sells the relay.

## 10. Decided, and what is still open

**His, 2026-11-06:**

| Decision | What it means here |
|---|---|
| Everything around the account, not the device | §4.2. A phone signs in and joins the lock. This also settles the old question of the introduction: it is the account's own channel |
| The backup stays on unless the person turns it off | Stage 2b, shown once at setup and on every such dictation, the sync's own pattern |
| The key is sealed with the user, and the phone has the desk's add, change and remove | Stage 2b. It travels through `vault`; a change on either side reaches the other by itself |
| The desk stays "no account, no dictation" (`sb.REQUIRED`) | It follows from the first line, so it is no longer a question |
| The first connection to a PC happens while he is at it, and the firewall dialog comes at that moment | Stage 1. On the PC he presses Approve on, at once. A further PC asks with its row on Home, so there too the dialog follows a press |
| Sign out on a phone removes the key from it | Stage 1. The next sign-in is a new device, with a new Approve |

**Mine, approved by him the same day with the rest of the plan:**

| Decision | Why |
|---|---|
| The phone holds the account key, wrapped by its hardware | His word of 2026-09-20, and the only way the key can open with the PC off |
| The web page is a full device of the account, not a lighter one | The iPhone has no other road, and a lighter key would mean a second sealed copy of every cloud key. The risk has the same root as the PC's updater (§6.1) |
| No secret QR; one Approve per device, never per PC | §4.2 |
| The join's code also binds the lock, and both sides press, for PCs too | One look protects both directions, as in Bluetooth pairing. One press on the joining device is the price |
| A phone can press Approve | The only way back for a person with one PC who never made a recovery key |
| Every signed-in PC keeps the account's socket, whatever its syncs say | A phone's request must reach a person with both syncs off, and the socket carries nothing personal |
| Groq first in the backup, Gemini only if it is the one key there | Groq was measured here; Gemini's Hebrew on phone audio was not (M15) |
| Stages 1, 2 and 2b wait only for their own first checks (M3, M16, M15), minutes each | The long ones decide stage 3, and until then the backup carries him away from home |

**Still open, none of it blocking stage 1:**

| # | The question | Recommendation |
|---|---|---|
| Q1 | PC on, no direct path: also offer a sealed relay through his account server, which keeps the PC's accuracy, ~30 lines, capped by the free tier, and needs Opus? | Decide after M1, M2, M10. If his own carrier needs it, yes as an opt-in: Tailscale's relays do the same thing today, and "nobody can read it" stays true though "it never leaves" would not |
| Q2 | Build the phone's own model (stage 5)? +9 to 24 MB in the app, 72 MB of model, weak on English, and the only road with no PC and no network; better than the cloud key on Hebrew, and nothing leaves | After stage 3's numbers, and after a throwaway build shows the speed on the S26 |
| Q3 | Google's registration before 2027: US$25 once and an adult's ID, against rule 1's "no card" | Not now. Decide when Google names a date or the first stranger asks |

## 11. Sources

Measured here, 2026-11-06: `tailscale status`, `netcheck`, `serve status`; UPnP `GetExternalIPAddress` on
the X50; `tracert`; `Get-NetConnectionProfile`, `Get-NetFirewallProfile`; `gh release view` on every tag;
the scratchpad probes `tls_probe.py`, `tls_door.py`, `wv2_rtc_probe.py`, `wv2_stun_probe.py`, `rtc_pc.py` with
the throwaway `imeprobe` keyboard, `join_server.py` with `lock_probe_Main.kt`, `two_phones.py`, `rt_probe.py`,
`audio_size.py`, `names_probe.py`, and `m8.html` with `m8_pc.py`,
the page M8 needs. All kept in `notes/phone-link-probes/` (local, not tracked). They are probes, not a start on
the code: a stage's first branch writes its own. Earlier work: `DISTRIBUTION_PLAN.md` chapter 12, `docs/distplan/map-phone.md`,
`docs/distplan/research-android.md`, `notes/DeskIT-store-walk-2026-10-03.md` item 15,
`notes/DeskIT-light-plan-2026-10-22.md`.

Tailscale: [how it works](https://tailscale.com/blog/how-tailscale-works),
[DERP](https://tailscale.com/kb/1232/derp-servers), [HTTPS](https://tailscale.com/kb/1153/enabling-https),
[NAT traversal 2025](https://tailscale.com/blog/nat-traversal-improvements-pt-1),
[connectivity table](https://tailscale.com/docs/reference/device-connectivity.md).
Self-hosting: [Headscale](https://headscale.net/stable/setup/requirements/),
[NetBird](https://docs.netbird.io/selfhosted/selfhosted-quickstart),
[ZeroTier notes](https://github.com/zerotier/ZeroTierOne/blob/main/RELEASE-NOTES.md),
[Nebula](https://github.com/slackhq/nebula).
Libraries: [libdatachannel](https://github.com/paullouisageneau/libdatachannel/blob/master/DOC.md),
[aiortc](https://pypi.org/project/aiortc/), [Iroh relays](https://docs.iroh.computer/concepts/relays).
Direct rates: [DCUtR, IMC 2026](https://arxiv.org/abs/2604.12484),
[CGN, IMC 2016](https://ar5iv.arxiv.org/html/1605.05606), [APNIC Israel](https://stats.labs.apnic.net/ipv6/IL).
Free tiers: [Supabase pricing](https://supabase.com/pricing),
[Realtime limits](https://supabase.com/docs/guides/realtime/limits),
[message counting](https://supabase.com/docs/guides/platform/manage-your-usage/realtime-messages),
[Durable Objects](https://developers.cloudflare.com/durable-objects/platform/pricing/),
[Cloudflare TURN](https://developers.cloudflare.com/realtime/pricing/) and
[its FAQ](https://developers.cloudflare.com/realtime/turn/faq/).
Certificates: [Let's Encrypt IP certificates](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability.html),
[Plex](https://words.filippo.io/how-plex-is-doing-https-for-all-its-users/).
Sign-in on a phone: [Supabase redirect URLs](https://supabase.com/docs/guides/auth/redirect-urls),
[mobile deep links](https://supabase.com/docs/guides/auth/native-mobile-deep-linking).
Cloud key: [Groq speech-to-text](https://console.groq.com/docs/speech-to-text),
[rate limits](https://console.groq.com/docs/rate-limits), [its data policy](https://console.groq.com/docs/your-data).
Ownerless: [BEP 44](https://www.bittorrent.org/beps/bep_0044.html), [Pkarr](https://github.com/pubky/pkarr).
Comparable: [Syncthing relaying](https://docs.syncthing.net/users/relaying.html),
[RustDesk](https://rustdesk.com/docs/en/self-host/), [LocalSend](https://github.com/localsend/protocol).
Android: [developer verification](https://developer.android.com/developer-verification/guides),
[its FAQ](https://developer.android.com/developer-verification/guides/faq),
[closed testing](https://support.google.com/googleplay/android-developer/answer/14151465?hl=en),
[target API](https://developer.android.com/google/play/requirements/target-sdk),
[local network permission](https://developer.android.com/privacy-and-security/local-network-permission),
[trust manager fix](https://support.google.com/faqs/answer/6346016?hl=en),
[hostname verifier](https://support.google.com/faqs/answer/7188426?hl=en),
[security-crypto](https://developer.android.com/jetpack/androidx/releases/security),
[supported formats](https://developer.android.com/media/platform/supported-formats),
[Auto Blocker](https://www.samsung.com/uk/support/mobile-devices/protect-your-galaxy-device-with-the-new-auto-blocker-feature/),
[Samsung on failed installs](https://www.samsung.com/us/support/troubleshoot/TSG10001914/).
Home routers: [TP-Link IPv6 behind another router](https://www.tp-link.com/us/support/faq/1525/),
[Deco modes](https://www.tp-link.com/us/support/faq/1432/).
Browsers: [Local Network Access](https://developer.chrome.com/docs/modern-web-guidance/guides/security/local-network-access),
[its spec](https://wicg.github.io/local-network-access/),
[chromestatus](https://chromestatus.com/feature/5152728072060928),
[Chromium's WebRTC gate](https://github.com/chromium/chromium/blob/main/services/network/public/cpp/features.cc),
[WebRTC Direct](https://github.com/libp2p/specs/blob/master/webrtc/webrtc-direct.md),
[WebTransport](https://www.w3.org/TR/webtransport/),
[Apple TN3179](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy),
[WebKit 327237](https://bugs.webkit.org/show_bug.cgi?id=327237),
[the iPhone transport report](https://github.com/djosh34/t3-optimizations/issues/22),
[clipboard in WebKit](https://webkit.org/blog/10855/async-clipboard-api/),
[iOS keyboards](https://developer.apple.com/library/archive/documentation/General/Conceptual/ExtensibilityPG/CustomKeyboard.html),
[Apple's memberships](https://developer.apple.com/support/compare-memberships),
[sherpa-onnx WASM](https://k2-fsa.github.io/sherpa/onnx/wasm/index.html).
On the phone: [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx),
[the model](https://hf.co/ivrit-ai/zipformer2-66m-streaming-he).
Windows: [new networks are Public](https://support.microsoft.com/en-us/windows/experience/connectivity-networking/essential-network-settings-and-tasks-in-windows),
[`desktop2:FirewallRules`](https://learn.microsoft.com/en-us/uwp/schemas/appxpackage/uapmanifestschema/element-desktop2-firewallrules),
[`DnsServiceRegister`](https://learn.microsoft.com/en-us/windows/win32/api/Windns/nf-windns-dnsserviceregister).

**Not verified, and said so where it matters:** the carrier NAT of any Israeli network; Israel's month for
developer verification; whether Auto Blocker is on by default on the S26 (it was on, on his); TLS with the
Keystore key on a real phone, and the join surviving a killed keyboard there; Opus's effect on Hebrew Whisper; the 66M model's speed on a
phone; the free tier's real Groq limits, Hebrew on its current page, and whether its API answers a browser;
Android routing on a Wi-Fi with no internet on his S26;
whether Cloudflare's sign-up really needs no card (its Workers pages say so, nobody walked it); Google's STUN terms; a real iPhone or Android Chrome
reaching a plain LAN address over WebRTC; whether Home Screen apps get Apple's Safari exemption; whether Chrome
has quietly turned its WebRTC check on server-side; a Samsung Internet device report.

## 12. How it is being built

He approved the plan on 2026-11-06 and asked that it be built in sessions under the one that wrote it, not all in one
conversation. That session, the coordinator, is the only one that talks to him. It merges, pushes, applies the
migration and keeps this file. A building session ends with commits on its own branch and a report. It never pushes,
never merges, and never asks him anything directly.

**Branches.** `phone-link` is the integration branch, cut from `dev-all`, because `main` is more than 200 commits behind
the desk these stages touch. Each lane is a worktree on a branch of its own, cut from `phone-link`. The coordinator reads
each lane's diff, merges it into `phone-link`, pushes that for CI, merges it into `dev-all` for his Dev check, and opens
the PR on his "works".

**The lanes of stage 1.**

| Lane | What | Its files | Waits for |
|---|---|---|---|
| `phone-account` | The first half on the PC: the code, migration 0007, the account pass, Forget and the `forgotten` list, the sign-outs, Home's lock rows | `vault.py`, `sb.py`, `supabase/`, the lock's rows in `deskweb.py` and `dashboard.py`, `dev/master/sources/server.py`, `docs/privacy.md` | Nothing |
| `phone-door` | The second half on the PC: `phone.py`, the door, the switch, the firewall, Settings > Phone, Home's Allow row | `phone.py`, `net.py`, `server.py`, `main.py`, `config.py`, `defaults.toml`, `paths.py`, the phone card on both desks, `web/`, `firstrun.py` | His look at the pictures, for the screens only; M4 |
| `phone-keyboard` | The first half on the phone: `Account.kt`, `Lock.kt`, the client key and its `link` row, approve, forget, sign out, the lock changed | `android/`, `dev/android/` | His look at the pictures, for the screens only; M16 |
| `phone-keyboard-door`, later | The second half on the phone: `Link.kt`, the bound Wi-Fi, the spool | `android/`, `dev/android/` | `phone-keyboard` merged |
| `phone-release`, later | The keyboard in a release, and the guide | `.github/workflows/`, `docs/`, `NETWORK.md` | The release keystore, his hand-work |

Stages 2 and 2b follow as lanes of their own once stage 1 stands.

**What the lanes share.** Written here so they can run at the same time.

- **The code.** `vault.pairing_code(uid, pairing_id, public, lock_id)`. Material: `b"\0".join((b"deskit pairing code v2",
  uid, pairing_id, point, lock_id))`, each string UTF-8, `point` the raw 64 bytes, salt `b"deskit pairing code v2"`. The
  rest as today: PBKDF2-HMAC-SHA256, 2^17 rounds, the first 50 bits of the digest, `XXXXX-XXXXX`, and `code_hint` its first
  8 characters. The asking device passes the `lock_id` it read, the approver `vault.fingerprint(key)`. Worked examples,
  made from this text on 2026-11-06, with the unchanged half checked against `vault.py`: `uid`
  `11111111-2222-3333-4444-555555555555`, `pairing_id` `aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee`, `point` 64 bytes of `0x41`.
  With `lock_id` `0123456789abcdef` the code is `WK0MS-7HN8C`; with `fedcba9876543210` it is `R85CJ-HRE9H`. A Python test and
  a Kotlin test hold both. The asking device opens nothing from `handed` until its person has pressed **Same code**.
- **`devices`, migration 0007.** `link text`, nullable, under `is_sealed()`. `session_id uuid`, nullable.
  `forget_device(target uuid) returns boolean` deletes the row and the session its `session_id` names, only where both
  belong to `auth.uid()`, and answers true when no session of that row is left, ended here or over already. False is a
  target that is not there, a row that named no session, or one that named somebody else's, which stays as it was.
  `platform` is `windows-…` as today, `android-<sdk>` on a phone, later `web`. Dry-run on the real project on 2026-11-06
  and twice on 2026-11-07, the last on the file as it stands, each in a block that rolls itself back: anon may not call it,
  an unsealed `link` is refused, another person's row and session stay, a session over already answers true, delete and
  insert under one `pairings` id pass the real policies while `expires_at` stays frozen, and nothing was left behind.
- **A `link` row.** `vault.seal_json(key, obj, "device/{uid}/{device_id}")`, the template named `vault.AAD_DEVICE`. A PC:
  `{"v": 1, "kind": "pc", "cert": "<SHA-256 of the DER, hex>", "addrs": ["192.168.68.50"], "port": 8766, "proto": 1,
  "words_sync": true}`. A phone: `{"v": 1, "kind": "phone", "cert": "<the DER, base64>", "proto": 1, "backup": true}`. An
  unknown field is ignored.
- **The `forgotten` row.** `vault` name `forgotten`, AAD `vault/{uid}/forgotten`, `seal_json` of `{"v": [{"device":
  "<uuid>", "cert": "<SHA-256 hex>", "at": "<ISO time>"}]}`, an entry unique by the pair (`device`, `cert`). Read, merged,
  written back. A PC also keeps the union, one file per account (`secrets\forgotten-<uid>.json`), that never shrinks, and a
  phone keeps it too.
- **Events.** `changed` with `stores: ["devices"]`, on the account's topic the way `_broadcast` sends it, when a device
  writes its row or forgets one. `pairing` as today: `device`, `id`, `code`, `name`.
- **What `sb.py` offers `phone.py`.** `devices() -> list[dict]`, every row of the account with `link` as stored.
  `write_link(sealed: str)`, this device's row, then the broadcast. `forget_device(device_id: str, cert: str) -> bool`.
  `forgotten() -> set[str]`, device ids and certificate fingerprints: the local list, which holds the account's as of the
  last account pass, and nothing with nobody signed in. `FORGOTTEN_HOOKS`, finished through the persisted `account.left`
  mark by `settle_left()`, because a leaving noticed in the desk must be finished by the app. `ACCOUNT_HOOKS`,
  callables taking `(key: bytes)`, run at the end of every account pass and on `changed: devices`, once the lock says
  `have`. `SIGNED_OUT_HOOKS` as today.

**The rules every lane keeps, on top of AGENTS.md.**

1. Your own worktree. The main checkout is his Dev, on `dev-all`, running: never switch it, never edit in it. A worktree has
   no venv: Python is `C:\Users\shimr\Desktop\Organized\Projects\DeskIT\.venv\Scripts\python.exe`. `web\node_modules` and
   `android\local.properties` are gitignored, so copy or link them from the main checkout when you need them.
2. Tests: only what you touched, by name, on the hidden desktop, below normal priority:
   `tests_quiet.run_hidden('start /b /belownormal /wait "" "<python>" tests.py <name> --no-screen > "<log>" 2>&1', <worktree>)`.
   One test run at a time on this PC: first look for a python process whose command line holds `tests_quiet.py`, `tests.py`,
   `tests_ops.py` or `user_sim`, and wait for it. The whole suite runs on CI after the coordinator pushes. `dev\user_sim.py`,
   hidden, after any change to start, stop, load, the dot, the hook or the bar. Never run `tests.py` or an app script in the
   open, not even to read its usage: every argument is a name filter.
3. Nothing of yours reaches his screen or his speakers. Probes and screenshots go through `tests_quiet.run_hidden`, muted at
   the source.
4. Never stop or restart his app. Never touch his `transcripts.log`, `recent\`, `corpus\`, `secrets\`, or any Credential
   Manager slot but `DeskIT.test/`. Never the live account server: tests use the fakes, and no lane applies a migration.
5. Stage by path, never `git add -A`. Do not push, and do not merge other lanes unless the coordinator says so. Do not edit
   `PHONE_LINK_PLAN.md`: what changed goes in your report and the coordinator writes it here.
6. Anything new on screen is a prototype in the real toolkit first, photographed, and waits for his look. Only those screens
   wait; the rest of the lane goes on.
7. The emulator is one lane at a time (`dev/android/emu.py`, no window). Build Android in the worktree, never in the main
   checkout's `android/app/build`.
8. Re-check every `file:line` here before relying on it: the tree moves. Where the plan and the code disagree, the code is
   the fact; do what the plan means, and say so in the report.
9. Your last message starts with one line: the verdict, the branch, the head commit. The whole report goes in
   `C:\Users\shimr\Desktop\Organized\Projects\DeskIT\notes\phone-link-build\<lane>.md` (local, not tracked): what was done,
   what was measured, where it differs from the plan, what the next lane or he must do. If you need him, or another lane, say
   so there and stop; the coordinator asks.
