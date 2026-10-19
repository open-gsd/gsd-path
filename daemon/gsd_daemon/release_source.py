"""Plugin releases from the npm registry.

The plugin manager installs skills with the ``scripts/install.py`` of a
published ``@opengsd/gsd-path`` release. This module lists the releases,
downloads one tarball, checks it against the registry's sha512, and unpacks it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import shutil
import ssl
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Optional

REGISTRY_URL = "https://registry.npmjs.org/@opengsd%2Fgsd-path"
# The abbreviated metadata document: dist-tags and each version's dist block only.
REGISTRY_ACCEPT = "application/vnd.npm.install-v1+json"
FETCH_TIMEOUT_S = 30
# npm packs every file under this directory.
PACKAGE_PREFIX = "package"
# The macOS system root bundle. python.org macOS builds ship no CA certificates
# until "Install Certificates.command" runs, so every https request fails without it.
SYSTEM_CA_FILE = "/etc/ssl/cert.pem"

Fetch = Callable[[str], bytes]


class ReleaseError(RuntimeError):
    pass


def ssl_context() -> ssl.SSLContext:
    """The default verifying context, plus the system bundle when Python has no CA certificates."""
    context = ssl.create_default_context()
    paths = ssl.get_default_verify_paths()
    if not (paths.cafile or paths.capath) and os.path.isfile(SYSTEM_CA_FILE):
        context.load_verify_locations(cafile=SYSTEM_CA_FILE)
    return context


def default_fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": REGISTRY_ACCEPT})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_S, context=ssl_context()) as response:
        return response.read()


def fetch_index(fetch: Fetch) -> dict:
    """``{"latest": version or None, "versions": {version: {"tarball", "integrity"}}}``."""
    try:
        data = json.loads(fetch(REGISTRY_URL))
        tags = data.get("dist-tags") or {}
        versions: Dict[str, dict] = {}
        for version, entry in (data.get("versions") or {}).items():
            dist = entry.get("dist") or {}
            versions[version] = {"tarball": dist.get("tarball"), "integrity": dist.get("integrity")}
    except (ValueError, AttributeError) as error:
        raise ReleaseError(f"the npm registry answer could not be read: {error}") from error
    latest = tags.get("latest")
    return {"latest": latest if latest in versions else None, "versions": versions}


def verify(data: bytes, integrity: Optional[str]) -> None:
    """Refuse the tarball unless it matches the registry's sha512."""
    prefix = "sha512-"
    if not isinstance(integrity, str) or not integrity.startswith(prefix):
        raise ReleaseError("the release has no sha512 integrity value; it was not installed")
    expected = integrity[len(prefix):]
    actual = base64.b64encode(hashlib.sha512(data).digest()).decode("ascii")
    if not hmac.compare_digest(actual, expected):
        raise ReleaseError("the downloaded release does not match its sha512; it was not installed")


def _unpack(data: bytes, dest: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts
            if (not parts or parts[0] != PACKAGE_PREFIX or ".." in parts
                    or not (member.isfile() or member.isdir())):
                raise ReleaseError(f"the release holds an unsafe entry: {member.name}")
            target = dest.joinpath(*parts[1:])
            # On Windows a part such as "C:" or one with a backslash can still leave `dest`.
            if dest.resolve() != target.resolve() and dest.resolve() not in target.resolve().parents:
                raise ReleaseError(f"the release holds an unsafe entry: {member.name}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            with open(target, "wb") as handle:
                shutil.copyfileobj(source, handle)


def install_release(releases_dir: Path, version: str, entry: dict, fetch: Fetch) -> Path:
    """Download, verify, and unpack one release. Returns its directory.

    The directory appears only when every step passed, so a release directory
    that exists is always a verified one.
    """
    dest = Path(releases_dir) / version
    if dest.exists():
        return dest
    url = entry.get("tarball")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ReleaseError(f"release {version} has no https download address")
    data = fetch(url)
    verify(data, entry.get("integrity"))
    releases_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{version}.", dir=str(releases_dir)))
    try:
        _unpack(data, work / "package")
        os.replace(work / "package", dest)
    except (tarfile.TarError, OSError) as error:
        if dest.exists():
            return dest
        raise ReleaseError(f"release {version} could not be unpacked: {error}") from error
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return dest
