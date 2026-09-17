# The winget manifests (DISTRIBUTION_PLAN.md 10.6)

Three files as `wingetcreate` writes them, for `YoavShimron.DeskIT`, with
`x.y.z` and the SHA-256 left as placeholders. The FIRST submission is by
hand, once, so the owner reads every field (`wingetcreate new`, then a
PR from his fork of microsoft/winget-pkgs); every later release is
`.github/workflows/winget.yml`, which runs `wingetcreate update` with the
new URL and version when the release is published and carries these
values forward. The Hebrew locale is the one hand-maintained file.

Fixed forever: the identifier. `ProductCode` is Inno's `{AppId}_is1`
(packaging/DeskIT.iss), which is how `winget list` and `winget upgrade`
match the Apps entry. The silent switches pass `/CHANNEL=winget` so the
installed copy's Update card offers the winget one-liner instead of a
download (chapter 11).
