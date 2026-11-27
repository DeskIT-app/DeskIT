"""The public half of the key every DeskIT update feed is signed with,
pinned in the shipped code (update_sig.py reads it, updates.py asks).

THIS FILE IS WRITTEN BY `dev\\sign_release.py --new-key` on the owner's
PC, once, and committed as the tool writes it. The private half stays in
that PC's Credential Manager and never touches GitHub, so whoever takes
over the GitHub account or the release job still cannot sign a feed.

The text is "ecdsa-p256:" and the standard base64 of the 64-byte public
point X || Y. A sceptic can check any release by hand with it:
`latest.json.sig` is the base64 of an ECDSA P-256 signature (r || s) over
the SHA-256 of latest.json's exact bytes.

While it says PLACEHOLDER no signature verifies, so a copy built from
this tree would refuse every update it is offered — which is why the
release build refuses to start with it (release.yml, "The update key is
pinned": `python dev/sign_release.py --check-pinned`).
"""

PUBLIC_KEY = "ecdsa-p256:PLACEHOLDER-no-key-yet-run-dev/sign_release.py--new-key"
