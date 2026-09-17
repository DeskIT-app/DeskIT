# android

**Question:** Distributing the DeskIT companion Android keyboard (Kotlin IME, today a debug APK sideloaded from the PC) to strangers in 2026 and pairing it with the user's own PC. Google Play requirements now (fee, identity verification, closed-testing 12-testers rule for personal accounts, target SDK, IME/mic data-safety implications, Play App Signing); alternatives (signed APK on GitHub Releases + Obtainium, F-Droid, Galaxy Store); LAN pairing without Tailscale (mDNS/NSD + QR + self-signed cert pinned via network security config) vs relay (Supabase Realtime, Cloudflare tunnel), Tailscale as optional documented path; how the PC app offers the APK/Play link; versionCode/versionName scheme and in-IME update prompts. Recommend the least-friction path for a free app by a solo developer.

Research date: 2026-09-16. Findings appended as sources are read.

## Findings (running log)

### Search round 1 (2026-09-16) — headline findings, to be verified on primary pages below
- Play closed-testing rule: personal accounts created after 2023-11-13 must run a closed test with >=12 testers opted in continuously for >=14 days before applying for production access (reduced from 20 in Dec 2024). Source: https://support.google.com/googleplay/android-developer/answer/14151465
- Play target API: since 2025-08-31 new apps/updates must target API 35; from 2026-08-31 must target API 36 (Android 16); extension possible to 2026-11-01. Source: https://support.google.com/googleplay/android-developer/answer/11926878
- Android developer verification (sideloading): all apps installed on certified Android devices must come from verified developers; enforcement starts 2026-09-30 in Brazil/Indonesia/Singapore/Thailand, global in 2027; unverified apps => "advanced flow" with a 24-hour wait. Personal full-distribution account: legal name, address, email, phone, ID check, one-time $25. Source: https://support.google.com/android-developer-console/answer/16561738 ; timeline: https://www.androidauthority.com/android-sideloading-changes-timeline-3679204/
- Network security config lets an app trust a specific self-signed cert (trust-anchors / pin-set); native apps have no browser secure-context problem. Source: https://developer.android.com/privacy-and-security/security-config
- Data safety: every Play app (incl. keyboards) must fill the Data safety form and link a privacy policy even if it collects nothing; microphone counts as sensitive user data under the User Data policy. Source: https://support.google.com/googleplay/android-developer/answer/10787469 , https://support.google.com/googleplay/android-developer/answer/10144311

### Primary source 1 — Play closed-testing rule (verified)
URL: https://support.google.com/googleplay/android-developer/answer/14151465
Quote: "Developers with personal accounts created after November 13, 2023, must run a closed test for their app with a minimum of 12 testers who have been opted in continuously for at least 14 days."
Quote: "When you meet these criteria, you can apply for production access on the Dashboard in Play Console ... you answer questions to help clarify your app design, testing process, and production readiness."
Implication for DeskIT: a NEW personal Play account cannot ship the keyboard to production until 12 strangers/friends stay opted in for 14 days; an "organization" account avoids this but needs a D-U-N-S number (owner has no company => not available).

### Primary source 2 — Android developer verification for ALL installs incl. sideloading (verified)
URL: https://support.google.com/android-developer-console/answer/16561738
Timeline (page): Nov 2025 early access verification; Mar 2026 full Android Developer Console access; Sep 2026: "Apps must be registered by verified developers in order to be installed from selected app stores to certified Android devices in Brazil, Indonesia, Singapore, and Thailand"; 2027 global expansion.
Quote (fee): "The $25 fee for a full distribution Android Developer Console account helps cover administrative costs."
Quote (hobbyist tier): "There is no registration fee, and users can distribute an unlimited number of apps to up to 20 devices without needing to provide a government ID."
Quote (ADB): "Developers and power users can still use Android Debug Bridge (ADB) to build, test, and install modified or unverified apps on their own devices, which remains the standard method for development work."
Implication: even the "signed APK on GitHub + Obtainium" route needs the owner to register the package name + signing key in the Android Developer Console (identity check, $25) before 2027 to keep installing on certified devices outside the 4 pilot countries; Israel is not in the Sep-2026 pilot but global enforcement is 2027. The free 20-device tier is useless for strangers. UNCERTAIN: exact 2027 date for Israel; whether the $25 Play Console fee and the $25 Android Developer Console fee are one and the same registration (page implies Play Console developers are verified through Play Console; needs confirmation).

### Primary source 3 — Play target API (verified)
URL: https://support.google.com/googleplay/android-developer/answer/11926878
Quote: "New apps and app updates must target Android 16 (API level 36) or higher" (as of Aug 31, 2026). Existing apps: "must target Android 15 (API level 35) or higher to remain available to new users". Extension to Nov 1, 2026 available on request.
Implication: build the IME with targetSdk 36 now; Play only.

### Primary source 4 — Network security config (verified)
URL: https://developer.android.com/privacy-and-security/security-config
- `<domain-config><domain>...</domain><trust-anchors><certificates src="@raw/my_ca"/></trust-anchors></domain-config>` trusts a self-signed cert for a domain; PEM/DER in res/raw. `<pin-set>` with SHA-256 digests pins leaf/CA; `cleartextTrafficPermitted="true"` can allow plain HTTP per domain (Android 9+ default is false).
- Config is STATIC XML at build time; no runtime API. => a per-user self-signed PC cert cannot be pinned via network security config (the cert does not exist at build time). Two workable paths: (a) ship ONE developer CA in the APK and have the PC generate a per-install leaf signed by... no, private CA key would have to ship with the PC app (bad). (b) Better: do TOFU/pinning in code with OkHttp `CertificatePinner` or a custom `X509TrustManager` that accepts exactly the SHA-256 fingerprint delivered by the QR code. That is code, not XML, and is the standard approach (e.g. KDE Connect, LocalSend use self-signed certs + fingerprint compare). Also works over raw IP (domain-config needs a hostname; IPs are matched by pinner code).
- Data safety: every Play app must fill the form + privacy-policy link even with zero collection (https://support.google.com/googleplay/android-developer/answer/10787469). Android system already warns that an IME "may be able to collect all the text you type"; audio recorded by the IME is sent to the user's own PC => declare "Audio: collected, not shared, processed ephemerally, optional" or argue on-device-only transfer; UNCERTAIN whether Play treats a transfer to the user's own LAN device as "collection" (Play's definition: data transmitted off the device = collected, with an exemption for end-to-end encrypted user-to-own-device? — needs check of the "ephemeral processing" and "user-to-user/E2E" exemptions).

### Search round 2 notes
- Play registration fee: one-time USD 25 (multiple 2026 guides; primary page still to quote). Personal accounts: government ID + address + phone verification.
- Obtainium (https://github.com/ImranR98/Obtainium, latest 1.6.15 on 2026-09-09): installs/updates straight from GitHub Releases; user adds the repo URL once. F-Droid main repo requires reproducible builds or F-Droid builds + signs with its own key (weeks of review). IzzyOnDroid repo accepts developer-signed APKs from GitHub releases (to verify).
- NSD/mDNS: https://developer.android.com/privacy-and-security/local-network-permission — a new local-network permission is coming (Android 16 opt-in/ future release mandatory); NsdManager DiscoveryRequest FLAG_SHOW_PICKER lets the system show a device picker without the broad permission. mDNS resolve of .local names needs the permission.

### Primary source 5 — Play registration (verified)
URL: https://support.google.com/googleplay/android-developer/answer/6112435
Quote: "There is a US$25 one-time registration fee that you can pay with the following credit or debit cards". Personal accounts: "you may be asked for a valid government ID and a credit card, both under your legal name." New personal accounts must also verify access to an Android device via the Play Console mobile app.

### Primary source 6 — Local network permission (verified)
URL: https://developer.android.com/privacy-and-security/local-network-permission
- Android 16: opt-in only. Android 17: "local network is blocked by default for all apps that update their target SDK" (targetSdk 37+). mDNS, NsdManager, .local resolution, any TCP/UDP to LAN addresses all count.
- Exit: `DiscoveryRequest.Builder("_http._tcp").setFlags(DiscoveryRequest.FLAG_SHOW_PICKER)` + `registerServiceInfoCallback` => system device picker, addresses returned "can now be connected to without ACCESS_LOCAL_NETWORK permission".
Implication: design the IME's PC discovery around the system picker (or QR-code-with-IP as fallback) so it survives the targetSdk-37 wall in 2027.

### Primary source 7 — Data safety definitions (verified)
URL: https://support.google.com/googleplay/android-developer/answer/10787469
- "'Collect' means transmitting data from your app off a user's device."
- Ephemeral: not disclosed if "only stored in memory and retained for no longer than necessary to service the specific request in real-time."
- E2E: data "unreadable by you or anyone other than the sender and recipient as a result of end-to-end encryption does not need to be disclosed."
- "Even developers with apps that do not collect any user data must complete this form and provide a link to their privacy policy."
Implication for DeskIT IME: audio goes phone -> user's own PC over TLS pinned to that PC; the developer never sees it => E2E exemption + ephemeral exemption arguably apply. Safer declaration: "Audio (voice) — collected, not shared, ephemeral, optional, encrypted in transit, user can request deletion (it is on their PC)". Privacy policy page (GitHub Pages) required regardless.

### Primary source 8 — versionCode/versionName (verified)
URL: https://developer.android.com/studio/publish/versioning
- versionCode: integer, max 2100000000, must strictly increase; "You can't upload an APK to the Play Store with a versionCode you have already used". versionName: free string, `<major>.<minor>.<point>` recommended.
Scheme for DeskIT: versionName = PC app's SemVer (e.g. 1.9.2); versionCode = MAJOR*10000 + MINOR*100 + PATCH (1.9.2 -> 10902); keep one shared VERSION file in the repo so PC and IME are released together; the PC /version endpoint returns {pc: "1.9.2", minIme: 10900}.

### Search round 3 notes (secondary sources; primary checks below)
- IzzyOnDroid (F-Droid-compatible repo): accepts developer-signed release APKs attached to GitHub releases, ~30 MB limit, needs Fastlane metadata (short/full description, icon, screenshots), no debuggable/testOnly. https://izzyondroid.org/docs/general/AppInclusionPolicy/
- Supabase free: 200 concurrent Realtime connections, 2M messages/month, 256 KB max message (secondary; to confirm on supabase.com/pricing).
- Cloudflare Tunnel: named tunnels need a domain on Cloudflare DNS (domain costs money => breaks zero-cost unless owner already has one); quick tunnels are random trycloudflare.com URLs, 200 concurrent requests, "not for production". Also the tunnel client would have to run on EVERY USER's PC and audio would traverse Cloudflare => violates "audio never leaves the machine" default.
- Play App Signing: required for all apps created after Aug 2021; upload AAB signed with upload key; Google holds/generates the app signing key; upload key can be reset. Consequence: the Play build and the GitHub APK build carry DIFFERENT signatures unless the owner uses the same key (Play lets you upload your own app signing key at enrolment) — otherwise users cannot switch between Play and GitHub builds without uninstalling.

### Primary source 9 — IzzyOnDroid inclusion policy (verified)
URL: https://izzyondroid.org/docs/general/AppInclusionPolicy/
"up to 30 megabytes per app", max 3 versions kept; APK "signed by its developer(s) using a release key, and not carry the flags android:debuggable or android:testOnly"; attached to GitHub/GitLab/Codeberg releases; licence "approved by OSI/FSF"; "Metadata ... must be available in the app's repo, using Fastlane structures. At least short description, full description, an icon, and some screenshots". Request via https://apt.izzysoft.de/fdroid/contributing/NewAppInclusions/ . => only works if the IME is open-sourced under an OSI licence.

### Primary source 10 — Supabase pricing (verified)
URL: https://supabase.com/pricing — Free: Realtime "200 included" peak concurrent connections, "2 Million included" messages/month, 256 KB max message; free projects "paused after 1 week of inactivity", 2 active projects. => A Supabase Realtime relay would be limited to 200 concurrent phone+PC sockets total (100 users online at once) and 256 KB frames (a 10-s 16 kHz PCM16 clip is ~320 KB; Opus ~20 KB fits). Pause-after-a-week would kill a relay for a low-traffic app unless a cron keeps it warm. Not recommended as the default transport.

### Primary source 11 — Play App Signing (verified)
URL: https://support.google.com/googleplay/android-developer/answer/9842756
New apps "automatically enrolled in quantum-ready, hybrid signing with Google-generated keys"; you may instead "Provide a copy of your app signing key" (PEPK tool) at enrolment; "For maximum security, your upload key and app signing key should be different"; "If you distribute via other app stores and want to use the same signing key everywhere" -> either download the universal APK from Play Console or give Google your own key.
Implication: to let a GitHub APK and the Play build update each other, either upload the owner's own release key to Play at enrolment (one-time, irreversible), or publish on GitHub the Play-signed universal APK downloaded from Play Console. Simplest: the latter.

### Secondary — Android developer verification for Play developers
https://developer.android.com/developer-verification/guides/google-play-console (search summary): a Play-verified developer is already verified; new apps created in Play Console get their package name registered automatically; unregistered packages can still be sideloaded via ADB or the "advanced flow". Verified quotes fetched below.
- LocalSend model (https://github.com/localsend/localsend): TLS cert generated on each device, SHA-256 fingerprint pinned per peer, server validates client fingerprint — the same pattern DeskIT should copy for PC<->IME.

### Primary source 12 — Android developer verification x Play Console (verified)
URL: https://developer.android.com/developer-verification/guides/google-play-console
Quote: "For most Play developers, no new action is required for identity verification. Your existing verified identity (such as for Play's developer verification requirements) meets this requirement."
Quote: "You can also use the Play Console to register apps you distribute outside of Google Play to ensure they remain installable on certified Android devices."
Quote: "Play developers must register their app package names, which may include proving ownership of the private signing keys used for those packages." Deadline for existing apps: Sep 30, 2026. No extra fee mentioned beyond the Play US$25.
Blog (https://android-developers.googleblog.com/2026/06/android-developer-verification.html): first phase Brazil/Indonesia/Singapore/Thailand from 2026-09-30 across 7 stores incl. Google Play and Galaxy Store; "we will expand these protections globally for all apps on certified Android devices in 2027"; "advanced flow" for sideloading unverified apps launched Aug 2026; limited-distribution accounts: "share your apps to up to 20 devices without a government-issued ID or a fee".
NET RESULT: one US$25 Play Console registration + ID check covers BOTH Play publishing and registering the GitHub-APK package/key for sideloading. There is no free path that reaches strangers on certified devices after 2027 without the ID check.

## Options compared

| Channel / mechanism | Owner cost | Owner friction | User friction | Updates | Verdict for DeskIT |
|---|---|---|---|---|---|
| Google Play (personal account) | US$25 once | ID + device verification; 12 testers x 14 days closed test before production; Data safety form + privacy-policy URL; targetSdk 36 (from 2026-08-31); AAB + Play App Signing | Lowest: store link, one tap | Automatic; Play In-App Updates API available | Target end state, but gated by the 12-tester rule; start the closed test early with the first users |
| Signed release APK on GitHub Releases (+ Obtainium optional) | 0 (same Play registration covers developer verification) | Keep a release keystore safe; register package+key in Play Console for sideload verification before 2027 global enforcement | "Install unknown apps" prompt; Obtainium is an extra app most people lack | Manual, or self-check against GitHub Releases API + prompt | Day-1 channel and permanent fallback; the PC installer points here |
| IzzyOnDroid (F-Droid-compatible repo) | 0 | OSI licence, Fastlane metadata, <=30 MB APK, request inclusion | Needs F-Droid client + repo added | Automatic via F-Droid client | Nice-to-have, only if the IME is open-sourced |
| F-Droid main repo | 0 | Reproducible build or F-Droid-built and F-Droid-signed; weeks-long review | Needs F-Droid client | Automatic | Skip for now (signature mismatch with Play/GitHub builds, slow) |
| Samsung Galaxy Store | 0 (seller registration reported free) | Separate seller portal + review; Samsung devices only; also in the verification pilot | Samsung only | Automatic | Skip; details UNVERIFIED |
| Pairing: LAN mDNS/NSD + QR + per-PC self-signed cert pinned by fingerprint (in code) | 0 | PC generates cert + pairing token; IME uses NsdManager picker (FLAG_SHOW_PICKER) or QR-carried IP:port:fingerprint | Scan one QR on the PC dashboard; same Wi-Fi | n/a | DEFAULT. Audio never leaves the LAN; no browser secure-context issue in a native IME |
| Tailscale (current path) | 0 (personal plan) | Document only | Install Tailscale on PC + phone, sign in | n/a | Keep as documented OPTIONAL path for "away from home Wi-Fi" |
| Relay: Supabase Realtime | 0 up to 200 concurrent conns / 2M msgs / 256 KB | Owner's project becomes a single point of failure; pauses after 1 week idle; audio transits owner's infra | Account login on both ends | n/a | Reject as default; violates "audio stays local" and free tier caps concurrency |
| Relay: Cloudflare Tunnel | Named tunnel needs a domain on Cloudflare (money); quick tunnels random, "not for production" | cloudflared on every user PC | Public URL exposure | n/a | Reject |

## Recommendation for DeskIT
1. Ship v1 of the keyboard as a **release-signed universal APK on GitHub Releases** (targetSdk 36, minSdk ~26, debuggable=false). The PC dashboard gets a "Phone keyboard" page with (a) a QR encoding the GitHub Releases latest-download URL (later the Play URL), (b) a QR encoding the pairing payload, (c) a Copy-link button. Reason: zero cost, no gate, works today; developer verification for sideloading is satisfied by the same US$25 Play registration the owner needs anyway.
2. In parallel open a **Google Play personal account** (US$25, government ID, card in legal name, Play Console phone-app device check), create the app (auto-registers the package name), upload the AAB to a **closed testing** track, and recruit the first 12 users from the same early adopters who install the PC app so the 14-day clock runs while the PC side matures. Data safety: audio = collected, optional, ephemeral, encrypted in transit, not shared, user-deletable; typed text not collected by the developer. Privacy policy + user guide on GitHub Pages. Once production access is granted, the PC page switches to the Play link and GitHub becomes the fallback. To keep the channels cross-updatable, publish on GitHub the Play-signed universal APK downloaded from Play Console (or hand Play the owner's own key via PEPK at enrolment).
3. **Pairing** copies LocalSend/KDE Connect: the PC generates a self-signed cert on first run (SHA-256 fingerprint = PC identity) plus a one-time pairing token, and advertises `_deskit._tcp` via mDNS (Python `zeroconf`). The IME discovers with `NsdManager` + `DiscoveryRequest.FLAG_SHOW_PICKER` (survives the Android 17 local-network permission) or reads IP:port:fingerprint from the QR. The IME pins the fingerprint in code (OkHttp `CertificatePinner` / custom trust manager, because network-security-config XML is static and cannot pin a per-user cert) and the PC stores the phone's client token; all later calls are HTTPS to the pinned cert + bearer token. Audio never leaves the user's LAN. Tailscale remains a documented optional path (same pairing works over the Tailscale IP).
4. **Versions**: one shared `VERSION` file; versionName = PC SemVer; versionCode = MAJOR*10000+MINOR*100+PATCH (max 2,100,000,000 leaves room). PC `/api/version` returns `{pc, imeMin, imeLatest, playUrl, apkUrl}`. On connect the IME compares: below `imeMin` => blocking "update the keyboard" notice; otherwise one dismissible prompt per version, opening Play when `installerPackageName == com.android.vending` (optionally Play In-App Updates API) and the GitHub APK URL otherwise. The PC app warns symmetrically when the phone speaks a newer protocol.

## What the owner must do by hand
- Pay the US$25 Play Console registration with a card in his legal name; complete government-ID verification and the Play Console phone-app device verification (personal account; no D-U-N-S possible without a company).
- Create the app entry (auto-registers the package name for Android developer verification); confirm registration on Play Console Home; register the sideload package/key if it differs.
- Generate and back up a release keystore (upload key); decide at enrolment whether to give Play his own signing key (PEPK) or accept Google-generated keys.
- Write and host: privacy policy, Data safety answers, store listing (icon, screenshots, descriptions), closed-testing tester list (12 e-mails or a Google Group), then the production-access questionnaire after 14 days.
- Accept the Play Developer Distribution Agreement; if pursuing IzzyOnDroid later, choose an OSI licence and add Fastlane metadata.

## Sources
- Play closed-testing rule: https://support.google.com/googleplay/android-developer/answer/14151465
- Play registration fee/ID: https://support.google.com/googleplay/android-developer/answer/6112435
- Play target API: https://support.google.com/googleplay/android-developer/answer/11926878
- Play App Signing: https://support.google.com/googleplay/android-developer/answer/9842756
- Data safety definitions: https://support.google.com/googleplay/android-developer/answer/10787469
- Android developer verification FAQ: https://support.google.com/android-developer-console/answer/16561738
- Verification via Play Console: https://developer.android.com/developer-verification/guides/google-play-console
- Verification blog (Jun 2026 timeline): https://android-developers.googleblog.com/2026/06/android-developer-verification.html
- Network security config: https://developer.android.com/privacy-and-security/security-config
- Local network permission / NSD picker: https://developer.android.com/privacy-and-security/local-network-permission
- Versioning: https://developer.android.com/studio/publish/versioning
- IzzyOnDroid policy: https://izzyondroid.org/docs/general/AppInclusionPolicy/
- Supabase pricing: https://supabase.com/pricing
- Obtainium: https://github.com/ImranR98/Obtainium ; LocalSend protocol model: https://github.com/localsend/localsend
- Cloudflare quick tunnels (secondary only): https://try.cloudflare.com

## Uncertainties
- Exact 2027 date when developer verification is enforced in Israel / globally; whether the "advanced flow" for unverified APKs involves a 24-hour wait (secondary sources only).
- Whether Play Data safety reviewers accept the E2E/ephemeral exemption for audio sent to the user's own PC; the conservative "collected, not shared, ephemeral" declaration is assumed.
- Galaxy Store seller registration cost and review rules not verified on a primary page.
- Whether Play production-access reviewers accept an IME whose value depends on a separate PC app; rejection risk unknown.
- Play In-App Updates API behaviour for an app installed from Play but also updated from GitHub with the same key (untested).
- Cloudflare named-tunnel domain cost not verified on Cloudflare's own pricing page; rejected on privacy grounds regardless.
