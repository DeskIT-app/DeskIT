"""CycloneDX 1.5 SBOM of what the installer carries (release.yml, 2026-11-10).

Standard library only. It lists the distributions installed in the STAGED
site-packages (importlib.metadata over that one folder, so the runner's
own packages never appear), plus the embeddable Python the stage carries,
and writes one JSON file. release.yml attaches it to the draft release and
attests it with actions/attest-sbom against the installer.

    python packaging/make_sbom.py --site stage/python/Lib/site-packages \
        --python 3.11.9 --version 1.0.7 --out sbom.cdx.json

Not shipped: packaging/ is never in the archive.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _license(dist) -> str:
    meta = dist.metadata
    expr = meta.get("License-Expression")
    if expr:
        return expr
    for c in meta.get_all("Classifier") or []:
        if c.startswith("License ::"):
            return c.split("::")[-1].strip()
    text = (meta.get("License") or "").strip()
    # a whole licence text in the field is not a name; keep a short one only
    return text if 0 < len(text) < 80 and "\n" not in text else ""


def components(site: Path) -> list[dict]:
    seen: dict[str, dict] = {}
    for dist in metadata.distributions(path=[str(site)]):
        name = dist.metadata.get("Name")
        if not name:
            continue
        key = _norm(name)
        version = dist.version
        purl = f"pkg:pypi/{key}@{version}"
        comp = {"type": "library", "bom-ref": purl, "name": name,
                "version": version, "purl": purl}
        lic = _license(dist)
        if lic:
            comp["licenses"] = [{"license": {"name": lic}}]
        seen[key] = comp
    return [seen[k] for k in sorted(seen)]


def build(site: Path, python: str, version: str) -> dict:
    py_ref = f"pkg:generic/python@{python}"
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "component": {"type": "application", "bom-ref": f"deskit@{version}",
                          "name": "DeskIT", "version": version},
        },
        "components": [{"type": "platform", "bom-ref": py_ref,
                        "name": "Python (embeddable)", "version": python,
                        "purl": py_ref}] + components(site),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--site", required=True, type=Path)
    ap.add_argument("--python", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    if not a.site.is_dir():
        print(f"no such folder: {a.site}", file=sys.stderr)
        return 2
    doc = build(a.site, a.python, a.version)
    if len(doc["components"]) < 2:
        print("the staged site-packages holds no distribution", file=sys.stderr)
        return 1
    a.out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"sbom: {len(doc['components'])} components -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
