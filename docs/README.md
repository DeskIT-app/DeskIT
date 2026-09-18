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

Taken on the hidden desktop, 2026-09-18: the seven wizard pages
(`02-*.png`) and the ask card's three-button state
(`07-ollama-three-buttons.png`). Not yet — they need a real screen, an
installer or a phone: `01-smartscreen-more-info`, `01-smartscreen-run-anyway`,
`01-installer-language`, `01-installer-finish`, `03-dot-states`, `03-hint`,
`03-shelf`, `03-corrections`, `04-credential-manager`, `04-network-tab-loopback`,
`04-offline-refused-row`, `05-groq-console-create-key`, `05-aistudio-create-key`,
`05-your-cloud-keys`, `05-consent-cloud-text`, `06-settings-phone`, `06-ime-enable`,
`07-picker`, `07-ask-card`, `07-settings-screen`, `08-folder-explorer`,
`08-uninstall-question`, `09-report-card`. Name them so and link them
from the chapter that owns the screen; the test then requires them.

## The Hebrew pages

Drafted by the coder from the English on 2026-09-18 for the owner to
edit (chapter 16). The Hebrew Settings page is generated: fill
`strings/settings.he.json` and rerun the generator; until then every row
falls back to English and `settings.he.gaps.txt` lists the keys.
