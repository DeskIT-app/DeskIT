# legal

Question: Licensing/legal checklist for a free Windows Hebrew dictation app (DeskIT): exact licenses of Whisper, faster-whisper, CTranslate2, ivrit-ai fine-tunes, NVIDIA cuBLAS/cuDNN pip wheels, Ollama, Gemma 3, Llama 3.1, Gemini API + Groq API terms for third-party apps, Rubik OFL, skia-python, PyAV/FFmpeg, PortAudio, pywin32, Python, Tcl/Tk. App license choice (MIT / Apache-2.0 / AGPL / PolyForm NC / FSL). THIRD-PARTY-NOTICES content; EULA for a free app; privacy policy outline; Israel PPL Amendment 13 duties for a solo dev; Win+Shift+S takeover.

## TL;DR
- Everything DeskIT needs is MIT/Apache/BSD/OFL except two items: the PyPI `av` wheel (GPL FFmpeg build) and NVIDIA CUDA wheels (proprietary, redistributable but must stay a user-triggered download).
- Recommended app license: FSL-1.1-Apache-2.0; Apache-2.0 as runner-up. No EULA needed for the app; a short ToS only for the account service.
- Israel PPL after Amendment 13: no registration, notification or DPO for a small accounts DB; still owe an s11 privacy notice, a database definition document and basic security practice.
- Cloud is BYOK: Groq free tier does not train on inputs; Gemini free tier does and is barred for EEA/UK/CH users; both are 18+.

Researched 2026-09-16. Findings appended per source below.

## Findings (per source)

### Search round 1 (search-engine summaries, to be verified on primary pages)
- ivrit-ai: HF listing shows ivrit-ai/whisper-large-v3-turbo-ggml as apache-2.0; main ivrit-ai/whisper-large-v3 / -turbo / -ct2 cards to verify directly. https://huggingface.co/ivrit-ai/whisper-large-v3-turbo
- NVIDIA CUDA EULA (https://docs.nvidia.com/cuda/eula/index.html): distributable portions may be redistributed "incorporated in object code format into software applications" provided the app has "material additional functionality" and only the app accesses them; cuDNN has its own SLA (https://docs.nvidia.com/deeplearning/cudnn/latest/reference/eula.html). NOTE: the pip route (user's own `pip install nvidia-cublas-cu12`) means the USER downloads from PyPI under NVIDIA's terms — the owner never redistributes. Prefer that.
- Israel Amendment 13 (in force 14 Aug 2025): registration only for >10,000 subjects AND primary purpose is data provision to others / direct mailing, or public bodies. Notification (not registration) to PPA only when "especially sensitive data" on >100,000 subjects. Sources: DLA Piper https://www.dlapiperdataprotection.com/index.html?t=registration&c=IL ; LoC https://www.loc.gov/item/global-legal-monitor/2025-11-17/israel-amendment-to-privacy-protection-law-goes-into-effect/
- PyAV: upstream binary wheels bundle FFmpeg built WITH x264/x265 => wheel is effectively GPL; forks (JScheumann/pyav-ffmpeg-lgpl) publish LGPL-only wheels. https://github.com/PyAV-Org/pyav-ffmpeg ; https://github.com/JScheumann/pyav-ffmpeg-lgpl
- Gemini API terms (https://ai.google.dev/gemini-api/terms): Unpaid Services => Google uses prompts/responses to improve products, human reviewers may read; Paid => not used. EEA/UK/CH: paid-tier data terms apply even to free quota. Google says do not submit sensitive/personal info to Unpaid Services.
- Gemma Terms of Use (https://ai.google.dev/gemma/terms): distributing Gemma/derivatives requires passing on the Section 3.2 use restrictions + notice + copy of agreement. Gemma 4 reportedly Apache-2.0 (verify). DeskIT pulls Gemma via Ollama on the user's machine => the owner does not distribute the weights; but if DeskIT "recommends" a model the guide should link the terms.

### Primary sources read (round 2)
- ivrit-ai/whisper-large-v3-turbo-ct2 (https://huggingface.co/ivrit-ai/whisper-large-v3-turbo-ct2): license tag "apache-2.0"; base openai/whisper-large-v3-turbo; trained on ivrit-ai/crowd-transcribe-v5 (295h) + 93h pro. No extra restrictions on card. => Attribution + license copy in NOTICES; cite ivrit.ai paper (arXiv 2307.08720) as courtesy.
- Gemini API Additional Terms (https://ai.google.dev/gemini-api/terms, last updated 2026-04-28): Unpaid: "Google uses the content you submit to the Services and any generated responses to provide, improve, and develop Google products and services." Paid: "Google doesn't use your prompts...or responses to improve our products". "You must be 18 years of age or older to use the APIs." "You must comply with our Prohibited Use Policy". KEY CLAUSE: "You may use only Paid Services when making API Clients available to users in the European Economic Area, Switzerland, or the United Kingdom." No explicit BYOK clause found. => DeskIT's BYOK design: each user's own key = user is the API customer; the guide must tell EEA/UK/CH users the free tier is not allowed for them (or DeskIT must not advertise Gemini there), and warn that free-tier text is used for training.
- Gemma Terms of Use (https://ai.google.dev/gemma/terms, updated 2026-04-01): Gemma 3 covered; Gemma 4 has a separate Apache-2.0 license. Distribution of Gemma/derivatives requires: use restrictions in agreement, copy of Agreement, prominent modification notices, Notice file "Gemma is provided under and subject to the Gemma Terms of Use found at ai.google.dev/gemma/terms". "Google claims no rights in Outputs". => DeskIT never ships weights (Ollama pulls them on the user's PC), so DeskIT is NOT a distributor; still add the Notice line + link if the guide recommends Gemma 3. Prefer recommending Gemma 4 (Apache-2.0) to avoid the question entirely.
- pyav-ffmpeg (https://github.com/PyAV-Org/pyav-ffmpeg): bundled FFmpeg includes x264, x265, libvmaf (all GPL) => the PyPI `av` wheel's FFmpeg is a GPL build. README has no explicit license statement (uncertainty on exact flags, but x264 requires --enable-gpl). => If DeskIT ships the standard `av` wheel inside an installer, the bundle is GPL-tainted; options: (a) user's pip installs it (still "distribution" arguably not by owner), (b) use JScheumann/pyav-ffmpeg-lgpl wheels, (c) drop PyAV — faster-whisper >=1.1 can decode via its own path? (verify), or feed 16k PCM WAV from PortAudio directly so no decoder is needed.
- Llama 3.1 Community License (https://www.llama.com/llama3_1/license/): if you "distribute or make available ... a product or service that contains any of them" you must provide a copy of the license and "prominently display 'Built with Llama'" on website/UI/docs. Groq-hosted Llama: DeskIT calls Groq's API; conservative reading = show "Built with Llama" in About + copy the license in NOTICES when a Llama model is the default repair model. 700M MAU clause irrelevant.
- Win+Shift+S: OS handles it as the "Screen Snip" hotkey (ms-screenclip: protocol). Third-party apps (Flameshot docs https://flameshot.org/docs/guide/windows-help/) register as the default handler for the ms-screenclip link type via Settings > Default apps; or users disable via HKCU\...\Explorer\Advanced DisabledHotkeys="S". No Microsoft policy forbids a desktop app from being chosen as the ms-screenclip default; a low-level keyboard hook that swallows Win+Shift+S is legal but user-hostile; Microsoft Store policy 10.x only applies if DeskIT is submitted to the Store. => Make the hotkey configurable, default to a non-OS key, and offer the ms-screenclip protocol handler route as the "proper" opt-in.
- FSL (https://fsl.software/): source-available, converts to Apache-2.0/MIT after 2 years; blocks competing use only; not OSI open source. PolyForm NC: blocks all commercial use by users. AGPL: OSI, copyleft, scares businesses but keeps source open; a paid tier is still possible via dual licensing since sole author holds copyright.
- Israel Data Security Regulations 2017 (in force 2018-05-08): four tiers — "database managed by an individual" (single controller, up to 2 authorized users?), basic, medium, high. Level set by sensitivity, # subjects, # access holders. Verify tier for DeskIT below.

### Primary sources read (round 3)
- Groq Services Agreement (https://console.groq.com/docs/legal/services-agreement, last modified 2026-06-22): s4.2 "Groq is not permitted to use Inputs or Outputs for training or fine-tuning any AI Model Services or other models, unless explicitly granted permission or instructed by Customer." s3.1 grants right "to make the Cloud Services and AI Model Services available to End Users" via a Customer Application. s3.2 customer responsible for security of API keys. s5.1 fee-free services "for a limited time or based on usage limits". s2 "You must be 18 years of age or older". => BYOK: each DeskIT user is a Groq Customer with their own account/key; DeskIT is their Customer Application. Groq free tier does not train on data (better than Gemini free).
- Ollama LICENSE (https://github.com/ollama/ollama/blob/main/LICENSE): MIT, (c) Ollama. DeskIT only talks to a locally installed Ollama over HTTP; no redistribution needed; if the installer downloads Ollama's installer, the MIT notice is enough.
- skia-python LICENSE: BSD-3-Clause (c) 2020 Kota Yamaguchi; bundled Skia itself is BSD-3 (Google) — include both notices.
- pywin32 License.txt: BSD-3-style (c) 1994-2008 Mark Hammond; retain notice.
- Tcl/Tk license (https://www.tcl-lang.org/software/tcltk/license.html): BSD-style; "provided that existing copyright notices are retained in all copies and that this notice is included verbatim in any distributions."
- faster-whisper: MIT (https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE, (c) SYSTRAN). CTranslate2: MIT (OpenNMT). OpenAI Whisper code + weights: MIT (github.com/openai/whisper LICENSE) — well known, not re-fetched.
- Israel PPL s11 (DLA Piper + LoC): notice at collection must state: whether there is a legal duty to provide the data or it is voluntary; purpose; recipients and purposes of transfer; consequences of refusal; controller name + contact; rights of access and rectification. DPO only for public bodies, data brokers >10k subjects, large-scale systematic monitoring / large-scale sensitive data => a solo dev with a small accounts DB does NOT need a DPO, registration, or notification. Amendment 13 in force 2025-08-14; PPA can levy administrative fines; statutory damages without proof of harm.
- Data Security Regulations 2017: gov.il page 403'd; per IAPP tutorial (https://iapp.org/news/a/the-new-israeli-data-security-regulations-a-tutorial) tiers = "managed by an individual" (owner is a single natural person or 1-person company AND at most 2 authorised access holders... [verify]), basic, medium, high. Medium requires sensitive data OR (>100k subjects...) ; DeskIT accounts DB (email + problem reports, no sensitive data) => "individual-managed" or "basic" level. Duties at that level: database definition document, written security procedure (basic), access authorisation list, physical security, documentation of security incidents, backups, and (basic and up) periodic review. Exact per-tier duty list is an UNCERTAINTY — confirm on gov.il.

### Primary sources read (round 4)
- NVIDIA CUDA EULA (https://docs.nvidia.com/cuda/eula/index.html, updated 2026-01-26): redistribution "as incorporated in object code format"; "Your application must have material additional functionality, beyond the included portions of the SDK. The distributable portions of the SDK shall only be accessed by your application." Attachment A lists cudart, cublas as distributable; cuDNN is under its own SLA (https://docs.nvidia.com/deeplearning/cudnn/latest/reference/eula.html) with a similar redistributable clause. Pip wheels not mentioned; PyPI wheels carry the same EULA in their METADATA. Restriction: "You may not use the SDK in any manner that would cause it to become subject to an open source software license" — matters if DeskIT itself is (A)GPL and bundles the DLLs: keep CUDA libs as a separate, user-triggered pip download, not inside an AGPL installer.
- Rubik OFL (https://github.com/googlefonts/rubik/blob/main/OFL.txt): "Copyright 2015 The Rubik Project Authors", SIL OFL 1.1; "Neither the Font Software nor any of its individual components ... may be sold by itself"; OFL text must accompany the font; bundling with software (even sold software) is allowed.
- IAPP tutorial: categories = individual/sole-proprietor-managed (special lighter rules unless a risk threshold crossed), basic (residual), intermediate (medical/genetic/biometric/financial/criminal/comms-metadata, etc.), high (intermediate + >100,000 subjects or >100 authorised users). Author: "get yourself a decent lawyer" for the per-tier duty list (s21(3)). DeskIT accounts DB: emails + problem-report text, one authorised user (Yoav) => individual-managed tier, unless problem reports contain sensitive data (they may include transcripts => treat as "basic" and strip transcripts by default).
- Not re-fetched (well-known, stable): Python = PSF License 2.0 (permissive, notice required); PortAudio = MIT-style (notice); OpenAI Whisper code/weights = MIT.

## Component license table (what DeskIT ships or depends on)
| Component | License | Ships in installer? | Obligation |
|---|---|---|---|
| OpenAI Whisper (code+weights) | MIT | no (weights via HF) | notice |
| faster-whisper (SYSTRAN) | MIT | yes (pip) | notice |
| CTranslate2 (OpenNMT) | MIT | yes (pip) | notice |
| ivrit-ai whisper-large-v3-turbo-ct2 | Apache-2.0 | no (downloaded by user from HF) | notice + attribution + link to LICENSE |
| nvidia-cublas-cu12 / cudnn-cu12 wheels | NVIDIA SDK EULA / cuDNN SLA (proprietary, redistributable object code) | NO - user-triggered pip download | show EULA link at download time; never inside an (A)GPL bundle |
| Ollama | MIT | no (user installs) | notice |
| Gemma 3 (via Ollama) | Gemma Terms of Use (custom) | no | not distributed by DeskIT; add Notice line if recommended; prefer Gemma 4 (Apache-2.0) |
| Llama 3.1 (via Groq) | Llama 3.1 Community License | no | "Built with Llama" + license copy if a Llama model is the shipped default |
| Gemini API | Gemini API Additional ToS (2026-04-28) | n/a | BYOK; 18+; free tier trains on data; EEA/UK/CH free tier not allowed |
| Groq API | Groq Services Agreement (2026-06-22) | n/a | BYOK; 18+; no training on inputs |
| Rubik font | SIL OFL 1.1 | yes | ship OFL.txt; do not sell font alone |
| skia-python + Skia | BSD-3 + BSD-3 | yes | notices |
| PyAV `av` wheel (FFmpeg w/ x264, x265) | GPL-tainted build | AVOID | drop or use LGPL wheel |
| PortAudio (via sounddevice/pyaudio) | MIT-style | yes | notice |
| pywin32 | BSD-3-style | yes | notice |
| Python | PSF-2.0 | yes (embedded) | notice + LICENSE.txt |
| Tcl/Tk | BSD-style | yes | notice verbatim |

## Options compared (app license)
| License | Users run free | Source readable | Blocks competitors reselling | Paid tier later | OSI | Friction |
|---|---|---|---|---|---|---|
| MIT / Apache-2.0 | yes | yes | no (anyone can fork+sell) | via services only | yes | none; NVIDIA/Gemma fine |
| AGPL-3.0 | yes | yes | forks must stay AGPL | dual-license (sole author) | yes | keep proprietary CUDA DLLs out of the bundle; corporates avoid |
| PolyForm Noncommercial 1.0 | personal yes, business no | yes | yes | yes (commercial license = paid tier) | no | "free for users" breaks for anyone dictating at work |
| FSL-1.1-Apache-2.0 | yes, any use except a competing product | yes | yes for 2 years, then Apache | yes | no (Fair Source) | small; each version auto-opens after 2 years |
| Proprietary + published source | yes | yes | yes | yes | no | must write bespoke terms |

## Recommendation for DeskIT
- App license: FSL-1.1-Apache-2.0 (https://fsl.software). Reason: users (including at work) may run it free; the full source is public so the "keys never reach the owner" claim is verifiable; only a competing DeskIT-as-a-product is blocked; each release becomes Apache-2.0 after 2 years, keeping the goodwill of an open project while leaving a paid tier open. It is permissive-compatible, so the proprietary NVIDIA wheels and Gemma/Llama terms create no conflict (AGPL would). Runner-up if Yoav wants plain open source: Apache-2.0. Avoid PolyForm-NC (kills "free for users" at work) and AGPL (bundle/DLL friction).
- Inference chain is all MIT/Apache => clean. Two dirty spots: (1) the PyPI `av` wheel (GPL FFmpeg) -- remove PyAV and feed 16 kHz PCM from PortAudio directly (faster-whisper accepts numpy arrays), or pin the LGPL wheel; (2) NVIDIA CUDA wheels -- never bundle; a first-run "Enable GPU" button runs pip in the user's venv and shows the NVIDIA EULA link.
- Cloud passes: BYOK only. Store keys with Windows DPAPI in %LOCALAPPDATA%\DeskIT, never in the Supabase schema. PROOF = public source + documented network allow-list (huggingface.co, api.groq.com, generativelanguage.googleapis.com, the Supabase project host) + Supabase table DDL published in the repo with no key column + RLS + a "what left my PC" log in the dashboard. Gemini free tier: settings dialog must say Google trains on free-tier text and that EEA/UK/CH users need a paid key. Groq free tier: no training (s4.2). Both require 18+.
- Llama on Groq: if the default repair model is a Llama, show "Built with Llama" in About and ship the Llama 3.1 license in NOTICES. Gemma via Ollama: recommend Gemma 4 (Apache-2.0); if Gemma 3 stays in the docs, add the one-line Gemma Notice and link.
- THIRD-PARTY-NOTICES.txt must contain, per component: name, version, copyright line, license name, full license text (MIT/BSD/Apache/OFL/PSF/Tcl verbatim), any upstream NOTICE file, the Gemma Notice line and Llama license when applicable, and the NVIDIA EULA URL for on-demand components. Generate with `pip-licenses --with-license-file --format=plain-vertical` at build time so it never drifts.
- EULA: a free app does not legally need one; the FSL LICENSE already carries the warranty disclaimer. Add a short "Terms of service" only for the Supabase account/problem-report service (acceptable use, account deletion, no warranty, Israeli law, 18+ for cloud features). Show once at sign-up, not as an installer click-through.
- Privacy policy outline (Hebrew + English, one page): 1) Who: Yoav Shimron, contact email, no company. 2) Local by default: audio, transcripts, history, screenshots, keys stay in %LOCALAPPDATA%\DeskIT; nothing sent unless a feature is switched on. 3) Optional BYOK cloud: which text goes to Groq/Gemini, under the user's own account, links to their terms, the Gemini free-tier training warning, EEA note. 4) Optional account (Supabase): data = email, auth id, app version, OS build, problem-report text and attachments the user chooses, timestamps; purpose = login + fixing problems; recipient = Supabase Inc (processor, region named); retention; rights = access, correction, deletion. Covers PPL s11: voluntary provision, purpose, recipients, consequences of refusal, controller contact, access/rectify. 5) Phone app: audio travels PC<->phone over the user's own Tailscale; never seen by the owner. 6) Screenshot/camera keys: local files only. 7) Update checks: what is sent (version, OS) to GitHub Releases. 8) Security: DPAPI, TLS, RLS, breach notice. 9) 18+ for cloud features. 10) Changes/contact.
- Israel PPL (Amendment 13, in force 2025-08-14) for the accounts DB: registration NOT required (only >10k subjects with a data-brokering purpose, or public bodies); notification NOT required (<100k subjects with especially-sensitive data); DPO NOT required. Still required: s11 notice at sign-up (the policy above), a written database definition document and basic security procedure under the 2017 Data Security Regulations (individual-managed/basic tier), access list, backups, incident log, breach reporting for serious incidents, purpose limitation, honouring access/deletion requests. Keep problem reports transcript-free by default so the DB never holds especially-sensitive content.
- Win+Shift+S: no Microsoft policy forbids a desktop (non-Store) app from taking it; the supported route is registering as the `ms-screenclip` protocol handler so Windows itself asks the user to pick DeskIT (Flameshot does this). A global keyboard hook that swallows the key works but silently breaks OneNote/Snipping Tool. Ship: default hotkeys that do not collide with the OS, an opt-in "Replace Windows screen snip" toggle that registers the protocol handler, and a note in the guide. If DeskIT ever goes to the Microsoft Store, the hook route is a rejection risk under the "must not interfere with other software" rule.

## What the owner must do by hand
1. Pick the license (FSL recommended); add LICENSE.md with copyright "Yoav Shimron" (copyright vests in the individual; no company needed).
2. Write THIRD-PARTY-NOTICES.txt (generate via pip-licenses, then add Rubik OFL, Tcl/Tk, Python, ivrit-ai, Llama/Gemma lines).
3. Write the privacy policy + short service terms (Hebrew + English); publish on GitHub Pages/README; link from installer and sign-up.
4. Create the Supabase project (free tier), choose region, name it in the policy; keep a one-page database definition document (purpose, data types, subject count, access holders = 1, processor = Supabase, retention).
5. Keep own Groq and Google AI Studio accounts only for testing; never ship a key. Add the EEA/free-tier warning text to the Gemini settings dialog.
6. Remove PyAV or switch to the LGPL wheel; make CUDA an on-demand install with the NVIDIA EULA link.
7. Optional: one-hour review of the policy by an Israeli privacy lawyer (the only likely non-zero cost; can wait until after launch).
8. Code-signing certificate is a money item (SmartScreen); not researched here but it affects the installer plan.

## Sources
- https://huggingface.co/ivrit-ai/whisper-large-v3-turbo-ct2 (Apache-2.0)
- https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE (MIT)
- https://docs.nvidia.com/cuda/eula/index.html (updated 2026-01-26) ; https://docs.nvidia.com/deeplearning/cudnn/latest/reference/eula.html
- https://github.com/ollama/ollama/blob/main/LICENSE (MIT)
- https://ai.google.dev/gemma/terms (updated 2026-04-01)
- https://ai.google.dev/gemini-api/terms (updated 2026-04-28)
- https://console.groq.com/docs/legal/services-agreement (modified 2026-06-22)
- https://www.llama.com/llama3_1/license/
- https://github.com/googlefonts/rubik/blob/main/OFL.txt
- https://github.com/kyamagu/skia-python/blob/main/LICENSE ; https://github.com/mhammond/pywin32/blob/main/win32/License.txt ; https://www.tcl-lang.org/software/tcltk/license.html
- https://github.com/PyAV-Org/pyav-ffmpeg ; https://github.com/JScheumann/pyav-ffmpeg-lgpl
- https://fsl.software/ ; https://lucumr.pocoo.org/2024/9/23/fsl-agpl-open-source-businesses/
- https://www.dlapiperdataprotection.com/index.html?t=registration&c=IL ; https://www.loc.gov/item/global-legal-monitor/2025-11-17/israel-amendment-to-privacy-protection-law-goes-into-effect/ ; https://iapp.org/news/a/the-new-israeli-data-security-regulations-a-tutorial
- https://flameshot.org/docs/guide/windows-help/ ; https://learn.microsoft.com/en-au/answers/questions/5824558/unable-to-block-screenclippinghost-triggered-by-wi

## Uncertainties
- Exact build flags of the PyPI `av` wheel (README lists x264/x265 but no license statement) -- treat as GPL until the wheel's bundled LICENSE is inspected.
- Which ivrit-ai checkpoint DeskIT uses; the -turbo-ct2 and -ggml cards say Apache-2.0, the older whisper-large-v3 card was not opened.
- gov.il Data Security Regulations text returned 403; whether DeskIT's DB is "individual-managed" or "basic" tier and the per-tier duty list were not verified on the primary source.
- Gemini ToS has no explicit BYOK/third-party-client clause; the EEA "Paid Services only" clause targets API Clients, so whether it binds a BYOK app whose user is the account holder is a judgement call -- warn anyway.
- Groq free-tier limits and any separate Groq privacy policy for free accounts were not read.
- Whether "Built with Llama" applies when the model is reached only through Groq's API (conservative: yes).
- Code-signing cost and Microsoft Store policy text were not researched.
