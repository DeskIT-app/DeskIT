# docs/ — the site (DISTRIBUTION_PLAN.md chapter 14, D26)

GitHub Pages serves this folder at `https://deskit-app.github.io/DeskIT/`
(`.github/workflows/pages.yml`, Jekyll, `_config.yml`). Export-ignored:
none of it reaches an installed copy; the app links to it (the wizard's
Welcome page, About, the Update card, the winget manifest).

| path | what |
|---|---|
| `he/` | the guide, Hebrew first: `quickstart.md`, `01-install.md` … `10-faq.md`, `settings.md` (generated) |
| `en/` | the English mirror, same names |
| `img/` | the pictures the pages name — every one must be referenced (dev/test_docs.py) |
| `privacy.md`, `terms.md` | chapter 13's drafts (English canonical; the Hebrew column is the owner's) |
| `strings/` | exported from the app by `dev/gen_settings_doc.py`: `wizard.json`, `consent.json`, `keys.json`, `retention.md`, `settings.he.json` (the owner's Hebrew sentences, key -> {label, help}) and `settings.he.gaps.txt` (what it lacks) |
| `distplan/` | the plan's research and decisions — not part of the site |

Regenerate after a change to `defaults.toml`, `settings.WORDS`,
`firstrun.WORDS`, `consent_card.TEXTS` or `secretstore.storage_sentence`:

    .venv\Scripts\python.exe dev\gen_settings_doc.py

`release.yml` runs it with `--check` and fails the release when a
committed page is stale; `dev/test_docs.py` holds the rest (tree
complete, pictures exist, the privacy chapter equals plan 5.10, the key
sentence is the app's, no owner words, every screen name is real).

## Pictures still to take (chapter 14.2)

Taken on the hidden desktop, 2026-09-18 (the account page 2026-09-20): the eight wizard pages
(`02-*.png`), the ask card's three-button state
(`07-ollama-three-buttons.png`), and the twelve screens of the app itself
— the dot's colours, the hint card, the shelf, Corrections, the offline
switch with its refused row, YOUR CLOUD KEYS, the consent card, Settings >
Phone / Screen, the picker, the ask card, the report box (`03-*`, `04-offline-
refused-row`, `05-*`, `06-settings-phone`, `07-*`, `09-report-card`) — every
one from a temporary `DESKIT_HOME` with invented content: no transcript,
no vocabulary and no key of anyone's. The shelf and the move frame
(`03-shelf`, `03-move`, 2026-09-21) are their own painters on a drawn
desktop corner — a layered window has nothing to photograph on a desktop
nobody is looking at — and were redrawn when Move joined the panel. Not
yet — they need a real screen,
an installer, a phone, Explorer, Credential Manager or a provider's
console: `01-smartscreen-more-info`, `01-smartscreen-run-anyway`,
`01-installer-language`, `01-installer-finish`, `04-credential-manager`,
`04-network-tab-loopback`, `05-groq-console-create-key`,
`05-aistudio-create-key`, `06-ime-enable`, `08-folder-explorer`,
`08-uninstall-question`. Name them so and link them from the chapter that
owns the screen; the test then requires them. Two of them have
conditions: SmartScreen shows only for a file that carries the Mark of
the Web (a browser download, or a zip Explorer extracted — never a file
`gh` or a USB stick brought), and the language dialog only on a Windows
whose display language is neither Hebrew nor English
(`ShowLanguageDialog=auto`); a Hebrew or English Windows goes straight to
the Install page.

## The Hebrew pages

Drafted by the coder from the English on 2026-09-18 for the owner to
edit (chapter 16). The Hebrew Settings page is generated: fill
`strings/settings.he.json` and rerun the generator; until then every row
falls back to English and `settings.he.gaps.txt` lists the keys.
