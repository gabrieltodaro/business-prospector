"""Explicit public inventory and immutable bytes for review and deployment."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.site_assets import MAX_IMAGE_BYTES

MAX_FILES = 100
MAX_BYTES = 25 * 1024 * 1024
_MIMES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
          ".webp": "image/webp", ".svg": "image/svg+xml"}


def _relative(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", value):
        raise ValidationError("unsafe public artifact relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(p in {".", ".."} for p in value.split("/")):
        raise ValidationError("unsafe public artifact relative path")
    return value


def _read(root: Path, relative: str, maximum: int = MAX_BYTES) -> bytes:
    """Open each path component without following links, then read bounded regular bytes."""
    parts = PurePosixPath(_relative(relative)).parts
    descriptors: list[int] = []
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(directory)
        for part in parts[:-1]:
            directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            descriptors.append(directory)
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        descriptors.append(descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
            raise ValidationError("artifact is not a bounded regular file")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            content = stream.read(maximum + 1)
        if len(content) > maximum:
            raise ValidationError("artifact exceeds size limit")
        return content
    except OSError as exc:
        raise ValidationError("missing, unsafe or symlink artifact file") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _validate_image(content: bytes, suffix: str, asset: dict[str, Any]) -> None:
    if len(content) > MAX_IMAGE_BYTES:
        raise ValidationError("asset exceeds the 8 MiB limit")
    if asset.get("mime_type") != _MIMES[suffix]:
        raise ValidationError("asset MIME does not match its safe file type")
    signatures = {".png": content.startswith(b"\x89PNG\r\n\x1a\n"),
                  ".jpg": content.startswith(b"\xff\xd8\xff"),
                  ".jpeg": content.startswith(b"\xff\xd8\xff"),
                  ".webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP"}
    if suffix != ".svg":
        if not signatures[suffix]:
            raise ValidationError("asset bytes do not match image file type")
        return
    if b"<!" in content or b"<?" in content:
        raise ValidationError("unsafe SVG declaration")
    try:
        svg = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValidationError("invalid SVG") from exc
    safe_tags = {"svg", "g", "defs", "linearGradient", "radialGradient", "stop", "filter",
                 "feGaussianBlur", "rect", "circle", "ellipse", "path", "polygon", "polyline",
                 "line", "title", "desc"}
    for element in svg.iter():
        if element.tag.split("}")[-1] not in safe_tags:
            raise ValidationError("unsafe SVG element")
        for name, value in element.attrib.items():
            name = name.split("}")[-1].lower()
            if name.startswith("on") or name in {"href", "style"} or "javascript:" in value.lower():
                raise ValidationError("unsafe SVG attribute")
            if "url(" in value.lower() and not re.fullmatch(r"url\(#[A-Za-z0-9_-]+\)", value):
                raise ValidationError("unsafe SVG resource")


@dataclass(frozen=True)
class ArtifactFile:
    path: str
    content: bytes

    def identity(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": hashlib.sha256(self.content).hexdigest(), "size": len(self.content)}


@dataclass(frozen=True)
class PublicArtifact:
    files: tuple[ArtifactFile, ...]
    manifest_bytes: bytes
    readme_bytes: bytes

    @property
    def checksum(self) -> str:
        digest = hashlib.sha256()
        for item in self.files:
            digest.update(item.path.encode() + b"\0")
            digest.update(item.content)
        return digest.hexdigest()

    def identity(self) -> dict[str, Any]:
        return {"version": 1, "checksum": self.checksum, "files": [item.identity() for item in self.files]}

    def write_to(self, destination: Path) -> None:
        destination.mkdir(parents=True)
        (destination / "assets").mkdir()
        for item in self.files:
            file = destination / item.path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(item.content)
        (destination / "site-manifest.json").write_bytes(self.manifest_bytes)
        (destination / "README.md").write_bytes(self.readme_bytes)


def capture_artifact(site_path: Path) -> PublicArtifact:
    if site_path.is_symlink():
        raise ValidationError("artifact directory cannot be a symlink")
    root = site_path.absolute()
    manifest_bytes = _read(root, "site-manifest.json", 1024 * 1024)
    try:
        manifest = json.loads(manifest_bytes)
    except (ValueError, UnicodeError) as exc:
        raise ValidationError("invalid artifact manifest") from exc
    assets = manifest.get("assets") if isinstance(manifest, dict) else None
    if not isinstance(assets, list) or (not assets and manifest.get("visual_mode") != "typography"):
        raise ValidationError("explicit asset inventory is required")
    inventory: dict[str, dict[str, Any]] = {}
    keys: set[str] = set()
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("key"), str) or not asset["key"]:
            raise ValidationError("invalid asset inventory entry")
        if asset.get("source_type") == "licensed_stock":
            from business_prospector.domain.site_assets import SiteAsset
            SiteAsset.from_manifest(asset)
        relative = _relative(asset.get("local_file"))
        if not relative.startswith("assets/") or Path(relative).suffix.lower() not in _MIMES:
            raise ValidationError("unsafe public asset file type or path")
        if relative in inventory or asset["key"] in keys:
            raise ValidationError("duplicate public asset inventory entry")
        inventory[relative] = asset
        keys.add(asset["key"])
    paths = ("index.html", "styles.css", *sorted(inventory))
    if len(paths) > MAX_FILES:
        raise ValidationError("generated site contains too many public files")
    if not (root / "assets").is_dir():
        raise ValidationError("assets directory is required")
    expected = set(paths) | {"site-manifest.json", "README.md"}
    expected_dirs = {"assets"} | {str(parent) for path in inventory for parent in PurePosixPath(path).parents if str(parent) != "."}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValidationError("generated site contains a symlink")
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            if relative not in expected_dirs:
                raise ValidationError("unexpected artifact directory")
        elif relative not in expected or not path.is_file():
            raise ValidationError("unexpected or unlisted artifact file")
    files: list[ArtifactFile] = []
    total = 0
    for relative in paths:
        content = _read(root, relative)
        total += len(content)
        if total > MAX_BYTES:
            raise ValidationError("generated site exceeds public upload size limit")
        if relative in inventory:
            asset = inventory[relative]
            _validate_image(content, Path(relative).suffix.lower(), asset)
            if asset.get("checksum") != hashlib.sha256(content).hexdigest():
                raise ValidationError("asset checksum does not match inventory")
        files.append(ArtifactFile(relative, content))
    return PublicArtifact(tuple(files), manifest_bytes, _read(root, "README.md", 1024 * 1024))


def public_artifact_files(site_path: Path) -> tuple[Path, ...]:
    artifact = validated_artifact(site_path)
    return tuple(site_path / item.path for item in artifact.files)


def artifact_checksum(site_path: Path) -> str:
    return validated_artifact(site_path).checksum


@contextmanager
def artifact_snapshot(site_path: Path) -> Iterator[tuple[PublicArtifact, Path]]:
    from .site_generation import validate_generated_site
    artifact = capture_artifact(site_path)
    with tempfile.TemporaryDirectory(prefix="prospector-approved-") as directory:
        snapshot = Path(directory) / site_path.name
        artifact.write_to(snapshot)
        validate_generated_site(snapshot)
        yield artifact, snapshot


def validated_artifact(site_path: Path) -> PublicArtifact:
    """Return validated immutable bytes; discard the temporary validation directory."""
    with artifact_snapshot(site_path) as (artifact, _snapshot):
        return artifact


def read_local_asset(root: Path, asset: Any) -> bytes:
    """Reuse publication safety checks at generation's local asset boundary."""
    relative = _relative(asset.local_file)
    suffix = Path(relative).suffix.lower()
    if not relative.startswith('assets/') or suffix not in _MIMES:
        raise ValidationError('unsafe local asset path or type')
    content = _read(root, relative, MAX_IMAGE_BYTES)
    _validate_image(content, suffix, asset.to_dict())
    if asset.checksum != hashlib.sha256(content).hexdigest() or asset.byte_size != len(content):
        raise ValidationError('local asset checksum or size does not match reviewed inventory')
    return content


def read_local_manifest(root: Path, name: str = 'site-manifest.json') -> dict[str, Any]:
    try:
        result = json.loads(_read(root, name, 1024 * 1024))
    except (ValueError, UnicodeError) as exc:
        raise ValidationError('invalid local manifest') from exc
    if not isinstance(result, dict):
        raise ValidationError('local manifest must be an object')
    return result


@contextmanager
def site_operation_lock(sites_root: Path, slug: str) -> Iterator[None]:
    """Serialize revision, approval and publication for a single local draft (POSIX)."""
    import fcntl
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
        raise ValidationError('unsafe site lock identity')
    locks = sites_root.parent / '.site-operation-locks'
    if locks.is_symlink():
        raise ValidationError('site lock directory cannot be a symlink')
    locks.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(locks / (slug + '.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
