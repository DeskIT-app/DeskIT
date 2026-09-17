# signing

**Question:** Windows code signing + SmartScreen for a solo indie/open-source developer in 2026 on a near-zero budget: what unsigned installers look like to users (SmartScreen, browser warnings, Defender), how reputation builds, Azure Trusted Signing current pricing and individual eligibility (identity validation, is Israel supported), SignPath Foundation free OSS signing (eligibility, process), OV/EV certificate prices, the Microsoft Store route (MSIX, one-time developer fee, does Store avoid SmartScreen, can a Python app be listed), and winget community submission (free? signing required?). Recommend one path.

Researched 2026-09-16.

## Findings (appended as sources are read)

### Search-round 1 (secondary summaries, to be verified on primary pages)
- Azure Trusted Signing was renamed **Azure Artifact Signing** (Jan 2026). Search summary: $9.99/mo Basic (5,000 sigs, 1 cert profile), $99.99/mo Premium. Individual identity validation reportedly limited to **US and Canada**; org validation lists Israel among supported countries. -> verify on FAQ.
- SignPath Foundation: free OSS signing, OSI licence, no dual-licensing, no proprietary components, actively maintained, already released; HSM-held key; application review days-to-weeks. -> verify on signpath.org/terms.
- SmartScreen: unsigned always warns; signed-but-new also warns until reputation; **EV no longer bypasses SmartScreen (since 2024)**; reputation is per-publisher-cert, and new intermediate CA migration Mar 2026 reset reputation for some. -> verify on Markdown Monster / ToDesktop posts.
- winget: MSIX/MSI/APPX/EXE accepted; manifests validated automatically + moderators; "must be signed" claim seen on Advanced Installer page (third party) -> verify on MS docs.
- Microsoft Store: individual developer registration free since Sept 2025; company fee ($99) removed May 2026; Store signs MSIX server-side. -> verify on learn.microsoft.com.
- OV certs: ~$215-260/yr from resellers (Sectigo/Certum/SSL.com); since June 2023 CA/B Forum requires keys on hardware token/HSM (so token or cloud HSM fee added).

### Primary source 1: Azure Artifact Signing FAQ (learn.microsoft.com/en-us/azure/artifact-signing/faq, updated 2026-08-14)
- "Artifact Signing doesn't support free, trial, or sponsored Azure subscriptions. To create an Artifact Signing account and certificate profiles, you must have a paid Azure subscription." -> a pay-as-you-go Azure subscription with a credit card is mandatory.
- "The pricing isn't calculated on a pro rata basis. The invoice is generated with the full amount for the SKU that you selected."
- "Artifact Signing doesn't issue Extended Validation (EV) certificates."
- Individual identity validation uses Microsoft Authenticator Verified ID + AU10TIX: government ID with address, FaceCheck; "Be sure to use a government-issued ID with an address on it."
- Supported countries list lives on the Quickstart prerequisites page (fetched separately below).
- "The Authenticode certificate that's used for signing with the profile is never given to you." Certificates are short-lived (3 days), rotated by the service; SmartScreen: "SmartScreen reputation builds up automatically. The prompt stops appearing once the file hash has sufficient download history."

### Primary source 2: SignPath Foundation terms (signpath.org/terms.html)
- "The project must use an OSI-approved Open Source license without commercial dual-licensing for all components"; "may not contain any proprietary, non open-source component"; "must be actively maintained"; "must already be released in the form that should be signed"; "functionality must be described on its download page".
- Obligations: signing team == dev team; only sign artifacts built from own source; "Binary artifacts must be built from source code in a verifiable way" (CI build on SignPath-connected pipeline, e.g. GitHub Actions/AppVeyor); "Every release needs manual approval for signing"; MFA for all team members on SignPath and repo; roles Authors/Reviewers/Approvers; "A code signing policy must be specified on the project's home page" with SignPath attribution + privacy policy; data collection needs privacy policy, install-time disclosure, opt-out; installer must include uninstaller; must not change system config without warning.
- Free of charge for qualifying OSS. Certificate subject is "SignPath Foundation" (OV), not the developer's name (per signpath.io; verify).
- Consequence for DeskIT: requires open-sourcing the whole app under an OSI licence (no proprietary parts), a public repo, CI build and a policy page. Telemetry/problem reports to Supabase must be opt-in with disclosure.

### Primary source 3: MS Store individual registration (learn.microsoft.com/en-us/windows/apps/publish/whats-new-individual-developer, updated 2026-04-18)
- "The new onboarding process is now live, allowing individual developers to publish apps to the Microsoft Store without any onboarding fees. This experience is available in nearly 200 markets worldwide."
- "The $19 registration fee is waived in the new flow." Requires "government-issued ID and selfie", entry only via https://storedeveloper.microsoft.com.
- Israel not named explicitly; "nearly 200 markets" -> very likely includes Israel (uncertainty, check the dropdown).

### Primary source 4: winget repository submission (learn.microsoft.com/en-us/windows/package-manager/package/repository)
- Free; PR to github.com/microsoft/winget-pkgs; automated pipeline + moderator; "Microsoft reserves the right to refuse a submission for any reason."
- Expectations: "The installer and application are virus free"; "installs and uninstalls correctly for both administrators and non-administrators"; "The installer supports non-interactive modes"; "The installer comes directly from the publisher's website" (GitHub Releases URLs are accepted in practice, no redirectors); HTTPS required; sha256 pinned per version.
- **No sentence on this page requires a code signature.** The "must be signed" claim came from a third-party (Advanced Installer) page; MS docs page does not state it. Many unsigned OSS packages exist in winget-pkgs. Multi-AV scan ("Installers Scan test") is run and PUA detections block.
- MSIX in winget: signature must be valid (MSIX cannot install unsigned), so EXE/MSI installer is the unsigned-friendly path.

### Primary source 5: Markdown Monster blog (2026-06-01) + ToDesktop PSA
- "Unsigned installer always trigger Windows SmartScreen." Dialog: blue "Windows protected your PC", only "Don't run" visible; user must click "More info" then "Run anyway".
- "Every time an update is shipped, the reputation cycle starts over. There's no continuity over the name of the binary or the certificate used - nothing." (author's experience; MS doc says reputation is per file hash AND per certificate/publisher, so signed publishers do carry some reputation across versions -- partially contradicts; treat as uncertainty.)
- Advice: "Publish on package managers (WinGet, Chocolatey) to bypass SmartScreen issues, and link these alternatives prominently on download pages." (winget install path does not show the SmartScreen dialog because the file is not marked with Mark-of-the-Web by a browser download.)
- ToDesktop: EV immediate reputation was removed in 2024; OV and Artifact Signing now equivalent; all new certs must build reputation.

### Primary source 6: Artifact Signing Quickstart prerequisites (learn.microsoft.com/en-us/azure/artifact-signing/quickstart, updated 2026-09-15)
- EXACT: "Public Trust certificates are available to organizations in the United States, Canada, the European Union, the United Kingdom, Australia, New Zealand, Japan, South Korea, Singapore, Switzerland, Norway, and Israel. Individual developers must be located in the United States or Canada. These geographic restrictions do not apply to Private Trust certificates."
- => **An Israeli individual with no company is NOT eligible for Azure Artifact Signing public-trust certs.** Israel is only in the organization list (needs a registered legal entity, business identifier, domain-owned email, website). Org validation "takes from 1 to 20 business days".
- Individual validation also requires Azure billing account of type Individual whose legal name + sold-to address match the government ID (AU10TIX + Microsoft Authenticator Verified ID).
- Pricing page (azure.microsoft.com/pricing/details/artifact-signing) rendered "$-" placeholders in the fetch; the MS SmartScreen doc states "Cost - Starts at $9.99/month" (Basic, 5,000 signatures/month; Premium 100,000/month). Requires paid pay-as-you-go subscription, billed full month, not pro-rated.

### Primary source 7: MS "SmartScreen reputation for Windows app developers" (learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation, dated 2026-05-04)
- "The simplest way to avoid SmartScreen warnings is to publish through the Microsoft Store. Store-distributed apps are signed by a Microsoft certificate and are never subject to SmartScreen download warnings."
- Table: Microsoft Store = "No warning"; Valid OV/EV = "Warning - app flagged as unrecognized until reputation accumulates; verified publisher name is displayed"; No signature = "Warning - 'Windows protected your PC'; User must choose 'Run anyway' ... Enterprise policy can prevent continuation entirely."; Self-signed = "Same behavior as no signature".
- "EV certificates no longer bypass SmartScreen... Paying a premium for EV solely to avoid SmartScreen warnings is no longer justified."
- "When a file is not signed, SmartScreen reputation must build for each new version of your files, starting with zero reputation. Reputation cannot transfer from previous versions unless both were signed using the same publisher identity."
- Timeline: "There is no exact threshold, but it can take several weeks and hundreds of clean installs from a wide audience."
- "There is no need (or mechanism) to manually submit a file for SmartScreen reputation review for consumer endpoints."
- Smart App Control (Win11, on by default on some new PCs): "will block execution of unsigned files unless the file has a positive reputation" -- applies to ALL executables, not just downloads. This is a hard block for unsigned apps on those machines (user must turn SAC off, which is one-way).

### Browser + Defender behaviour (search summaries; Edge doc learn.microsoft.com/en-us/deployedge/microsoft-edge-security-smartscreen, gHacks)
- Edge: "Microsoft Defender SmartScreen couldn't verify if this file is safe because it isn't commonly downloaded." User must open the download menu -> "Show more" -> "Keep anyway"; there is a "Report this file as safe" option. Criteria: "download traffic, download history, past anti-virus results, and URL reputation".
- Chrome: similar "isn't commonly downloaded and may be dangerous" using Google Safe Browsing (separate reputation; signing helps but is not required).
- Defender AV itself does not flag unsigned files per se; PyInstaller-built EXEs are a known false-positive magnet (Wacatac/Trojan:Win32 heuristics). Mitigation: sign, use --onedir not --onefile, submit false positives at microsoft.com/wdsi/filesubmission. (General knowledge + winget "Binary-Validation-Error" text; mark as moderate confidence.)

### Python apps on the Microsoft Store (search: 82phil.github.io 2025 MSIX+PyInstaller guide, dev.to Python-to-MSIX GitHub Actions, MLT-solutions/Py2MSIX)
- Yes: PyInstaller EXE folder -> MakeAppx MSIX -> Partner Center. The Store re-signs the package with Microsoft's cert (no developer cert needed for Store submission). Win32/desktop-bridge apps run with full trust, so Tk + Win32 hooks + local HTTP server + pythonw are allowed (needs runFullTrust capability; low-level keyboard hooks work in full-trust packaged apps).
- Caveats: MSIX apps get virtualised AppData/registry; a 1.6 GB model must be downloaded at first run, not shipped in the package (Store package size limit 25 GB, but keep it small); CUDA wheels (~2 GB) likewise downloaded on demand; Store certification takes ~1-3 business days per update.

### Certum Open Source Code Signing (search summaries, my-ssl.com / sslcertshop; primary shop page fetched next)
- Reported ~USD 50-116/yr, individuals only, subject line fixed to "Open Source Developer, <name>", may not sign commercial software, cloud (SimplySign) or card+reader. Still builds SmartScreen reputation like any OV cert. Not zero cost.

### Primary source 8: Certum shop (shop.certum.eu/code-signing.html, 2026)
- "Open Source Code Signing in the Cloud" EUR 49.00 gross (SimplySign, no card); "Open Source Code Signing - set" EUR 69.00 (card + reader); Standard (OV) cloud EUR 209; EV cloud EUR 379. "Starting from February 27, 2026, a single Code Signing certificate may be valid for a maximum of 459 days."
- Open Source variant: individuals only, project must be free/open source; subject reads "Open Source Developer, <name>" (per resellers). Cheapest real Authenticode cert for an Israeli individual.

### Primary source 9: 82phil MSIX+PyInstaller guide (2025-04-24)
- "Microsoft will sign the submitted MSIX packages for you." Manifest needs runFullTrust (mediumIL). "Full-Trust submissions mandate a privacy policy and written justification for the elevated permissions."
- signpath.io/solutions/open-source-community: "available at no cost", CI connectors GitHub/Jenkins/Azure DevOps; certificate subject not stated on that page (community reports: subject = "SignPath Foundation", not the developer) -> uncertainty.

## Options compared

| Path | Cost to owner | Israel + no company | SmartScreen on first run | Reputation carries to next version | Effort / conditions |
|---|---|---|---|---|---|
| Unsigned EXE installer (Inno/NSIS) on GitHub Releases | 0 | yes | "Windows protected your PC" every version; Edge "isn't commonly downloaded"; Smart App Control PCs hard-block | no (restarts at zero each release) | none; Defender false positives likely with PyInstaller |
| winget manifest for that installer | 0 | yes | no Mark-of-the-Web, so no SmartScreen dialog via winget install; multi-AV scan must pass | n/a | PR per version, silent install/uninstall, HTTPS direct URL; signing NOT required by MS docs |
| Microsoft Store (MSIX, individual account) | 0 (fee waived Sept 2025) | "nearly 200 markets" (Israel very likely; verify dropdown) | none - Store re-signs with Microsoft cert | yes | ID+selfie once; runFullTrust justification + privacy policy; model/CUDA downloaded at first run; 1-3 day certification per update |
| SignPath Foundation (free OSS OV signing) | 0 | yes | warning until cert reputation builds | yes (same cert) | must be fully OSI-licensed open source, public repo, CI build, policy page, manual approval per release, MFA, opt-in telemetry; weeks to approve |
| Certum Open Source cert | ~EUR 49-69/yr | yes (individual) | warning until reputation | yes | app must be open source; subject "Open Source Developer, Yoav ..." |
| Azure Artifact Signing | $9.99/mo + paid Azure sub | NO for individuals (US/Canada only); Israel only via registered company | warning until reputation | yes | blocked by eligibility |
| Commercial OV cert | ~$200-260/yr + token | yes | warning until reputation | yes | violates zero-cost; EV (~EUR 330-380) gives nothing extra for SmartScreen |

## Recommendation for DeskIT
**Primary: Microsoft Store as an individual developer (free), shipping an MSIX built from the PyInstaller folder. Secondary: the same build as a plain EXE installer on GitHub Releases plus a winget manifest for people who refuse the Store.**

Reasons: (1) it is the only route that is literally zero cost AND removes the SmartScreen dialog on day one (MS: Store apps "are never subject to SmartScreen download warnings"); (2) Azure Artifact Signing is closed to Israeli individuals, SignPath forces a full open-source licence plus heavy process, and any bought cert still shows the warning for weeks; (3) the Store gives versions and auto-updates for free, which the plan needs anyway; (4) winget install skips the download-time SmartScreen check, so the GitHub path is usable without a cert.

Design consequences: the installer must NOT bundle the 1.6 GB model or the CUDA wheels - download them on first run into %LOCALAPPDATA% with a progress dialog; keep the CPU path as default; the Store listing needs a privacy policy page (audio stays local, keys stay local, problem reports opt-in) and a written justification for runFullTrust (global push-to-talk hook, screenshot keys, local HTTP endpoint for the phone app). Do not spend on any certificate until user numbers justify it; if DeskIT later goes open source, apply to SignPath Foundation (or buy Certum OSS for EUR 49) to sign the GitHub build too.

## What the owner must do by hand
1. Go to https://storedeveloper.microsoft.com -> "Get started for free" -> Individual developer; sign in with a Microsoft account; pass government-ID + selfie verification on the phone (Israeli passport or photo ID card). Confirm Israel appears in the country list.
2. In Partner Center reserve the app name "DeskIT"; note the Package/Publisher identity it assigns (goes into the MSIX manifest).
3. Write and host a privacy policy page (GitHub Pages is fine) and a one-paragraph runFullTrust justification for the submission form.
4. Create a GitHub repo (public or private) + GitHub Releases for the EXE path; later fork microsoft/winget-pkgs and open the manifest PR (free, no signing).
5. Optional later: if the code is open-sourced, apply at signpath.org (needs MFA on GitHub and a code-signing policy page) or buy Certum Open Source Code Signing in the Cloud (EUR 49).
6. Do NOT open an Azure pay-as-you-go subscription for Artifact Signing - identity validation will fail for an Israeli individual.

## Sources
- https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart (prerequisites: countries; individual validation flow)
- https://learn.microsoft.com/en-us/azure/artifact-signing/faq (paid subscription only, no EV, cert never handed out)
- https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation (Store = no warning; OV=EV; timeline; Smart App Control)
- https://learn.microsoft.com/en-us/windows/apps/publish/whats-new-individual-developer (free individual registration, ID+selfie, ~200 markets)
- https://learn.microsoft.com/en-us/windows/package-manager/package/repository (winget submission, expectations, no signing clause)
- https://signpath.org/terms.html (SignPath Foundation conditions)
- https://signpath.io/solutions/open-source-community
- https://shop.certum.eu/code-signing.html (EUR 49 OSS cloud cert, 459-day max validity)
- https://markdownmonster.west-wind.com/blog/posts/2026/Jun/01/Windows-Protected-your-PC-Dealing-with-Windows-SmartScreen-on-Installation
- https://www.todesktop.com/blog/posts/windows-apps-psa-ev-certs-do-not-grant-immediate-reputation-anymore
- https://82phil.github.io/python/2025/04/24/msix_pyinstaller.html and https://dev.to/freerave/how-i-automating-python-to-msix-publishing-for-the-microsoft-store-using-github-actions-3dd6
- https://blogs.windows.com/windowsdeveloper/2026/05/07/publish-to-microsoft-store-as-a-company-now-with-free-registration-and-faster-onboarding/
- https://www.ghacks.net/2022/07/02/how-to-deal-with-microsoft-edges-isnt-commonly-downloaded-warning/

## Uncertainties
- Israel in the Store's individual-onboarding country list: MS says "nearly 200 markets" but does not list them; must be checked live in the sign-up form.
- Azure Artifact Signing exact prices: pricing page rendered placeholders; $9.99/mo Basic comes from the MS SmartScreen doc and press, not the pricing table.
- SignPath Foundation certificate subject name (reported as "SignPath Foundation") and approval time (community: days to weeks) not confirmed on a primary page.
- Whether a full-trust MSIX with a global keyboard hook, screen capture and a listening HTTP port passes Store certification without pushback; the phone-app endpoint may need explicit mention in the justification.
- Certum Open Source cert eligibility wording ("free to use" vs OSI licence) taken from the shop blurb; a freeware-but-closed DeskIT may or may not qualify.
- Defender false-positive rate for PyInstaller builds is from general community experience, not a 2026 measurement; winget's multi-AV scan can reject a build on a heuristic hit.
- Smart App Control prevalence among Israeli Windows 11 users is unknown; where it is on, the unsigned GitHub EXE will not run at all (Store build unaffected).
