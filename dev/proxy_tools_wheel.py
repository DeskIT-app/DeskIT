"""The proxy_tools wheel the builds install (2026-10-23, the web desk).

pywebview imports proxy_tools at its top (`webview/__init__.py`), and
proxy_tools 0.1.0 (2014, MIT, one module of 6,409 bytes) exists on PyPI
only as an sdist. Both builds install wheels only — `--only-binary=:all:`
in release.yml, build_local.ps1 and ci.yml — and building the sdist at
install time is what the 2026-09-22 spike did: pip fetched setuptools
into an isolated build environment, outside --require-hashes, and the
wheel it made had no hash anyone could have written down beforehand.

So the wheel is made HERE, once, from the sdist's own bytes, and
committed: packaging/wheels/proxy_tools-0.1.0-py3-none-any.whl, its
SHA-256 in requirements.lock like every other wheel's, and the lock's
`--find-links packaging/wheels` is where pip finds it. Nothing is
compiled and nothing is run from the sdist — the module is copied byte
for byte, the metadata is the sdist's PKG-INFO restated — and the file is
the same on any PC with any Python: entries STORED (no zlib, whose output
differs between builds of the library), one fixed timestamp, one order.
`test_proxy_tools_wheel_is_the_sdist_and_rebuilds_byte_for_byte` rebuilds
it from the module inside it and compares.

    pip download --no-deps --no-binary=:all: --no-build-isolation proxy_tools==0.1.0 -d X
        (or any copy of proxy_tools-0.1.0.tar.gz; its SHA-256 is checked)
    python dev/proxy_tools_wheel.py X/proxy_tools-0.1.0.tar.gz [--out packaging/wheels]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import sys
import tarfile
import zipfile
from pathlib import Path

NAME, VERSION = "proxy_tools", "0.1.0"
WHEEL = f"{NAME}-{VERSION}-py3-none-any.whl"
#: PyPI's own digest of the one file of the release (the JSON API's
#: urls[0].digests.sha256, read 2026-10-23 — the sdist, 2,978 bytes).
SDIST_SHA256 = "ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010"
#: proxy_tools-0.1.0/proxy_tools/__init__.py inside that sdist.
MODULE_SHA256 = "d1539d95e1a713c068ca81d42e047b2c76568964cf277596d4e19efb22f476be"
#: Every entry's timestamp: the sdist's own (2014-05-05), so nothing of
#: the day the wheel was made is in it.
STAMP = (2014, 5, 5, 0, 0, 0)

METADATA = """\
Metadata-Version: 2.1
Name: proxy_tools
Version: 0.1.0
Summary: Proxy Implementation
Home-page: http://github.com/jtushman/proxy_tools
Author: Jonathan Tushman
Author-email: jonathan@zefr.com
License: MIT
Classifier: Intended Audience :: Developers
Classifier: License :: OSI Approved :: MIT License
Classifier: Programming Language :: Python :: 2.7
Classifier: Programming Language :: Python :: 3

The proxy_tools 0.1.0 sdist from PyPI (sha256 """ + SDIST_SHA256 + """),
repackaged as a wheel by DeskIT's dev/proxy_tools_wheel.py: the module is
the sdist's, byte for byte.
"""

WHEEL_FILE = """\
Wheel-Version: 1.0
Generator: DeskIT dev/proxy_tools_wheel.py
Root-Is-Purelib: true
Tag: py3-none-any
"""


def _record_hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def build(module: bytes) -> bytes:
    """The wheel's bytes, from the module's bytes. Raises if the module is
    not the sdist's."""
    got = hashlib.sha256(module).hexdigest()
    if got != MODULE_SHA256:
        raise ValueError(f"proxy_tools/__init__.py is {got}, the sdist's is {MODULE_SHA256}")
    info = f"{NAME}-{VERSION}.dist-info"
    files = [
        (f"{NAME}/__init__.py", module),
        (f"{info}/METADATA", METADATA.encode()),
        (f"{info}/WHEEL", WHEEL_FILE.encode()),
        (f"{info}/top_level.txt", f"{NAME}\n".encode()),
    ]
    record = "".join(f"{name},{_record_hash(data)},{len(data)}\n" for name, data in files)
    record += f"{info}/RECORD,,\n"
    files.append((f"{info}/RECORD", record.encode()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for name, data in files:
            entry = zipfile.ZipInfo(name, STAMP)
            entry.compress_type = zipfile.ZIP_STORED
            entry.create_system = 0
            entry.external_attr = 0o644 << 16
            z.writestr(entry, data)
    return out.getvalue()


def module_from_sdist(sdist: Path) -> bytes:
    data = Path(sdist).read_bytes()
    got = hashlib.sha256(data).hexdigest()
    if got != SDIST_SHA256:
        raise ValueError(f"{sdist} is {got}, PyPI's sdist is {SDIST_SHA256}")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
        member = t.extractfile(f"{NAME}-{VERSION}/{NAME}/__init__.py")
        return member.read()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sdist", help="proxy_tools-0.1.0.tar.gz")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent.parent
                                             / "packaging" / "wheels"))
    ns = parser.parse_args(argv)
    wheel = build(module_from_sdist(Path(ns.sdist)))
    out = Path(ns.out) / WHEEL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(wheel)
    print(f"{out}: {len(wheel)} bytes, sha256 {hashlib.sha256(wheel).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
