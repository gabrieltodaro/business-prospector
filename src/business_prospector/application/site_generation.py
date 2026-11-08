from __future__ import annotations

import json
import hashlib
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.site_generation import FirstWebsiteSiteBrief, SITE_STRATEGY_VERSION
from business_prospector.domain.site_assets import SiteAsset
from business_prospector.application.ports import LeadRepository, ReviewedSiteAssetLibrary
from business_prospector.domain.models import Lead

GENERATOR_VERSION = "4.0.0"
REQUIRED_FILES = ("index.html", "styles.css", "site-manifest.json", "README.md")
GENERATED_FILES = ("index.html", "styles.css", "assets/", "site-manifest.json", "README.md")


def controlled_sites_root(data_dir: Path) -> Path:
    """Derive the non-user-selectable generated-sites root from plugin data."""
    return data_dir.expanduser().resolve() / "sites"


@dataclass(frozen=True, slots=True)
class SiteDraftInfo:
    exists: bool
    lead_slug: str
    site_path: Path | None = None
    generated_at: str | None = None
    generation_status: str = "missing"
    manifest: dict[str, Any] | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "exists": self.exists, "lead_slug": self.lead_slug,
            "generated_at": self.generated_at, "generation_status": self.generation_status,
            "manifest": self.manifest,
            "site_url": f"/sites/{self.lead_slug}/" if self.exists else None,
        }


class SiteDraftService:
    """Read-only boundary for validated generated artifacts."""

    def __init__(self, sites_root: Path) -> None:
        self._sites_root = sites_root.expanduser().resolve()

    @property
    def sites_root(self) -> Path:
        return self._sites_root

    def inspect(self, slug: str) -> SiteDraftInfo:
        try:
            site = self._site_directory(slug)
            if not site.is_dir():
                return SiteDraftInfo(False, slug)
            validate_generated_site(site)
            raw_manifest = json.loads((site / "site-manifest.json").read_text(encoding="utf-8"))
            if not isinstance(raw_manifest, dict):
                raise ValidationError("site manifest must be an object")
            identity = raw_manifest.get("lead_identity")
            if not isinstance(identity, dict) or identity.get("slug") != slug:
                raise ValidationError("site manifest identity does not match lead")
            generated_at = raw_manifest.get("generated_at")
            if not isinstance(generated_at, str) or not generated_at.strip():
                raise ValidationError("site manifest generated_at is invalid")
            safe_manifest = {
                key: raw_manifest.get(key) for key in (
                    "opportunity_type", "generated_at", "generator_version", "source_batch_id",
                    "benchmark_market", "strategy_version", "missing_information", "revision", "preview_kind",
                    "strategy", "indexing_policy", "outreach_image_context",
                )
            }
            return SiteDraftInfo(True, slug, site, generated_at, "generated", safe_manifest)
        except (ValidationError, ValueError, OSError, json.JSONDecodeError):
            return SiteDraftInfo(False, slug, generation_status="invalid")

    def resolve_file(self, slug: str, relative_parts: tuple[str, ...]) -> Path | None:
        info = self.inspect(slug)
        if not info.exists or info.site_path is None:
            return None
        if not relative_parts:
            relative_parts = ("index.html",)
        allowed = relative_parts in {("index.html",), ("styles.css",)}
        if relative_parts and relative_parts[0] == "assets" and len(relative_parts) > 1:
            allowed = all(part not in {"", ".", ".."} and "/" not in part and "\\" not in part for part in relative_parts)
        if not allowed:
            return None
        candidate = info.site_path.joinpath(*relative_parts).resolve()
        try:
            candidate.relative_to(info.site_path)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def _site_directory(self, slug: str) -> Path:
        try:
            from business_prospector.domain.normalization import slugify
            safe_slug = slugify(slug)
        except ValueError as exc:
            raise ValidationError("unsafe site slug") from exc
        if slug != safe_slug or slug in {"", ".", ".."}:
            raise ValidationError("unsafe site slug")
        site = (self._sites_root / slug).resolve()
        try:
            site.relative_to(self._sites_root)
        except ValueError as exc:
            raise ValidationError("unsafe site path") from exc
        return site


@dataclass(frozen=True, slots=True)
class SiteGenerationResult:
    ok: bool
    lead_slug: str
    site_path: str | None
    files: tuple[str, ...]
    warnings: tuple[str, ...]
    missing_information: tuple[str, ...]
    generation_status: str
    error: str | None = None
    artifact_identity: dict[str, Any] | None = None
    revision_number: int | None = None
    previous_artifact_path: str | None = None
    strategy: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "lead_slug": self.lead_slug, "site_path": self.site_path,
            "files": list(self.files), "warnings": list(self.warnings),
            "missing_information": list(self.missing_information),
            "generation_status": self.generation_status, "error": self.error,
            "artifact_identity": self.artifact_identity, "revision_number": self.revision_number,
            "previous_artifact_path": self.previous_artifact_path, "strategy": self.strategy,
        }


class _SiteHTMLValidator(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: set[str] = set()
        self.errors: list[str] = []
        self.local_images: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.add(tag)
        if tag in {"script", "iframe", "object", "embed", "base"}:
            self.errors.append("active embedded content is not allowed")
        if any(key.lower().startswith("on") for key, _ in attrs):
            self.errors.append("inline event handlers are not allowed")
        values = dict(attrs)
        for key in ("href", "src"):
            value = values.get(key)
            if value and value.strip().lower().startswith("javascript:"):
                self.errors.append("unsafe javascript URL")
        href = values.get("href")
        if href and urlsplit(href).scheme and urlsplit(href).scheme not in {"http", "https", "tel"}:
            self.errors.append("unsupported external URL scheme")
        if values.get("target") == "_blank":
            rel = set((values.get("rel") or "").split())
            if not {"noopener", "noreferrer"} <= rel:
                self.errors.append("target=_blank requires noopener noreferrer")
        if tag == "img":
            src = values.get("src") or ""
            self.local_images.append(src)
            if urlsplit(src).scheme or src.startswith("//"):
                self.errors.append("generated images must be local")
            if "alt" not in values:
                self.errors.append("generated images require alt text")


def validate_generated_site(site_dir: Path, competitor_domains: tuple[str, ...] = ()) -> None:
    for name in REQUIRED_FILES:
        if not (site_dir / name).is_file():
            raise ValidationError(f"generated site is missing {name}")
    html = (site_dir / "index.html").read_text(encoding="utf-8")
    if '<html lang="pt-BR">' not in html:
        raise ValidationError("generated HTML must use pt-BR")
    parser = _SiteHTMLValidator()
    parser.feed(html)
    required = {"header", "main", "footer", "h1"}
    if not required <= parser.tags:
        raise ValidationError("generated HTML is missing semantic structure")
    if parser.errors:
        raise ValidationError(parser.errors[0])
    for relative in parser.local_images:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or not relative.startswith("assets/"):
            raise ValidationError("unsafe generated image path")
        asset = site_dir / path
        if asset.is_symlink() or not asset.is_file():
            raise ValidationError("generated image is missing or unsafe")
    lowered = html.lower()
    if any(domain and domain.lower() in lowered for domain in competitor_domains):
        raise ValidationError("competitor domain leaked into generated output")
    if re.search(r"(?:api[_-]?key|secret|token)\s*[:=]", lowered):
        raise ValidationError("possible secret material in generated output")


class SiteGenerationService:
    def __init__(self, sites_root: Path) -> None:
        self._sites_root = sites_root.expanduser().resolve()

    @property
    def sites_root(self) -> Path:
        return self._sites_root

    def generate(
        self, lead: dict[str, Any], research: dict[str, Any], *, overwrite: bool = False,
        assets: tuple[SiteAsset, ...] | None = None, asset_source_root: Path | None = None,
        reviewed_content: dict[str, Any] | None = None, art_direction: dict[str, Any] | None = None,
        after_install: Callable[[], None] | None = None, expected_artifact_checksum: str | None = None,
    ) -> SiteGenerationResult:
        from .artifacts import site_operation_lock
        initial = FirstWebsiteSiteBrief.from_inputs(lead, research, allow_revision=overwrite)
        with site_operation_lock(self._sites_root, initial.lead_slug):
            if expected_artifact_checksum is not None:
                from .artifacts import capture_artifact
                if capture_artifact(self._sites_root / initial.lead_slug).checksum != expected_artifact_checksum:
                    raise ValidationError('visual review is stale; artifact changed before revision')
            return self._generate_locked(lead, research, initial, overwrite, assets, asset_source_root,
                                         reviewed_content, after_install, art_direction)

    def _generate_locked(
        self, lead: dict[str, Any], research: dict[str, Any], initial: FirstWebsiteSiteBrief,
        overwrite: bool, assets: tuple[SiteAsset, ...] | None, asset_source_root: Path | None,
        reviewed_content: dict[str, Any] | None, after_install: Callable[[], None] | None, art_direction: dict[str, Any] | None,
    ) -> SiteGenerationResult:
        from .artifacts import read_local_manifest, capture_artifact
        from .draft_revision import install_validated_draft
        destination = self._sites_root / initial.lead_slug
        if destination.is_symlink():
            raise ValidationError('draft destination cannot be a symlink')
        existing = None
        if destination.exists():
            if not overwrite:
                return SiteGenerationResult(False, initial.lead_slug, str(destination), (), (), initial.missing_information,
                                            'conflict', 'site directory already exists')
            existing = read_local_manifest(destination)
            identity = existing.get('lead_identity')
            if identity != {'slug': initial.lead_slug, 'external_place_id': initial.external_place_id}:
                raise ValidationError('replacement must preserve business identity')
            for key, status in (('deployment', 'deployment_status'), ('sales_preview', 'preview_status')):
                metadata = existing.get(key)
                if metadata is not None and not isinstance(metadata, dict):
                    raise ValidationError('invalid existing publication metadata')
                if metadata and (metadata.get(status) == 'published' or key == 'deployment'):
                    raise ValidationError('published previews cannot be replaced')
            if art_direction is None:
                art_direction = existing.get('art_direction')
            if reviewed_content is None:
                reviewed_content = existing.get('reviewed_content')
            if assets is None:
                raw_assets = existing.get('assets')
                if not isinstance(raw_assets, list) or len(raw_assets) > 30:
                    raise ValidationError('invalid existing asset inventory')
                assets = tuple(SiteAsset.from_manifest(item) for item in raw_assets)
                asset_source_root = destination
        assets = tuple(asset for asset in (assets or ()) if not (asset.key == 'hero-visual' and asset.source_type == 'generated' and asset.asset_type == 'illustration'))
        if len(assets) > 30 or len({asset.key for asset in assets}) != len(assets):
            raise ValidationError('draft supports up to 30 distinct assets')
        if art_direction and art_direction.get('hero_asset_key') and not any(a.key == art_direction['hero_asset_key'] and a.asset_type != 'logo' for a in assets):
            raise ValidationError('planned hero asset is not in the reviewed inventory')
        image_count = sum(asset.approval_status in {'approved_for_draft', 'agent_curated_draft', 'approved_for_publish'}
                          and asset.asset_type != 'logo' for asset in assets)
        hero_asset = next((asset for asset in assets if asset.asset_type != 'logo' and
                           asset.approval_status in {'approved_for_draft', 'agent_curated_draft', 'approved_for_publish'}), None)
        ratio = hero_asset.width / hero_asset.height if hero_asset and hero_asset.width and hero_asset.height else None
        brief = FirstWebsiteSiteBrief.from_inputs(lead, research, reviewed_content=reviewed_content,
                                                  image_count=image_count, hero_aspect_ratio=ratio, allow_revision=overwrite, art_direction=art_direction)
        self._sites_root.mkdir(parents=True, exist_ok=True)
        temp = Path(tempfile.mkdtemp(prefix=f'.{brief.lead_slug}-', dir=self._sites_root))
        try:
            self._write_site(temp, brief, assets, asset_source_root)
            domains = tuple(urlsplit(item.website_url).hostname or '' for item in brief.market_research.benchmarks)
            validate_generated_site(temp, domains)
            identity = capture_artifact(temp).identity()
            manifest = read_local_manifest(temp)
            previous_revision = existing.get('revision', {}) if existing else {}
            if not isinstance(previous_revision, dict):
                raise ValidationError('invalid revision metadata')
            number = previous_revision.get('number', 0)
            if type(number) is not int or number < 0:
                raise ValidationError('invalid revision number')
            previous_identity = previous_revision.get('artifact_identity', {})
            if not isinstance(previous_identity, dict):
                raise ValidationError('invalid previous artifact identity')
            manifest['revision'] = {'number': number + 1, 'artifact_identity': identity,
                                    'previous_revision_id': previous_identity.get('checksum')}
            (temp / 'site-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            # Validation is complete before either the old directory or database state moves.
            with install_validated_draft(temp, destination) as previous:
                if after_install:
                    after_install()
                result = SiteGenerationResult(
                    True, brief.lead_slug, str(destination), GENERATED_FILES,
                    tuple(f'Informação pendente: {item}' for item in brief.missing_information),
                    brief.missing_information, 'regenerated' if overwrite else 'generated',
                    artifact_identity=identity, revision_number=number + 1,
                    previous_artifact_path=str(previous) if previous else None, strategy=brief.strategy.to_dict(),
                )
        finally:
            if temp.exists():
                shutil.rmtree(temp)
        return result

    def _write_site(
        self, directory: Path, brief: FirstWebsiteSiteBrief, assets: tuple[SiteAsset, ...],
        asset_source_root: Path | None,
    ) -> tuple[SiteAsset, ...]:
        from .artifacts import read_local_asset
        from .site_renderer import render_html, render_css, stock_outreach_context
        from business_prospector.domain.website_content_model import WebsiteContentModel
        assets_dir = directory / 'assets'
        assets_dir.mkdir()
        rendered_assets: list[SiteAsset] = []
        for asset in assets:
            if asset.approval_status not in {'approved_for_draft', 'agent_curated_draft', 'approved_for_publish'}:
                continue
            if asset_source_root is None:
                raise ValidationError('approved local assets require a controlled source root')
            asset = SiteAsset.from_manifest(asset.to_dict())
            if asset.rights_status in {'unknown', 'do_not_use'} or asset.source_type in {'business_social_reference', 'unknown', 'placeholder'}:
                raise ValidationError('asset rights or provenance do not permit draft use')
            if asset.source_type == 'existing_business_site' and not asset.business_identity_match:
                raise ValidationError('asset business identity mismatch')
            content = read_local_asset(asset_source_root, asset)
            # Controlled keys avoid basename collisions; no caller path becomes a destination.
            name = asset.key + Path(asset.local_file or '').suffix.lower()
            (assets_dir / name).write_bytes(content)
            rendered_assets.append(asset.with_local_file(f'assets/{name}', asset.checksum or '', asset.mime_type or '', len(content)))
        model = WebsiteContentModel.from_brief(brief)
        (directory / 'index.html').write_text(render_html(brief, tuple(rendered_assets), model), encoding='utf-8')
        (directory / 'styles.css').write_text(render_css(), encoding='utf-8')
        manifest = {
            'lead_identity': {'slug': brief.lead_slug, 'external_place_id': brief.external_place_id},
            'opportunity_type': brief.opportunity_type,
            'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'generator_version': GENERATOR_VERSION, 'source_batch_id': brief.batch_id,
            'benchmark_market': brief.market_research.benchmark_market,
            'strategy_version': SITE_STRATEGY_VERSION, 'strategy': brief.strategy.to_dict(),
            'reviewed_content': brief.reviewed_content.to_dict(), 'content_model': model.to_dict(),
            'art_direction': brief.art_direction,
            'preview_kind': 'internal_draft', 'indexing_policy': 'noindex,nofollow,noarchive',
            'missing_information': list(brief.missing_information), 'generated_files': list(GENERATED_FILES),
            'assets': [asset.to_dict() for asset in rendered_assets],
            'visual_mode': 'photography' if any(a.asset_type == 'photo' for a in rendered_assets) else 'typography',
            'outreach_image_context': stock_outreach_context(tuple(rendered_assets)),
        }
        (directory / 'site-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (directory / 'README.md').write_text(
            '# Rascunho local\n\nDemonstração independente para revisão interna. Não é o site oficial.\n\n'
            'Estratégia, fontes de fatos, informações ausentes e proveniência dos assets estão no manifesto privado. '
            'Aprovação de draft não autoriza publicação.\n', encoding='utf-8',
        )
        return tuple(rendered_assets)


class PersistedSiteGenerationWorkflow:
    """Use authoritative lead/research and commit status inside recoverable artifact installation."""

    def __init__(self, repository: LeadRepository, generator: SiteGenerationService, asset_library: ReviewedSiteAssetLibrary | None = None) -> None:
        self._repository = repository
        self._generator = generator
        self._asset_library = asset_library

    def generate(
        self, lead_id: int, research: dict[str, Any], *, overwrite: bool = False,
        reviewed_content: dict[str, Any] | None = None, asset_keys: list[str] | None = None, art_direction: dict[str, Any] | None = None,
        expected_lead: dict[str, Any] | None = None, expected_artifact_checksum: str | None = None,
    ) -> tuple[SiteGenerationResult, Lead | None]:
        return self._run(lead_id, research, overwrite=overwrite, revision=False,
                         reviewed_content=reviewed_content, asset_keys=asset_keys, art_direction=art_direction,
                         expected_lead=expected_lead, expected_artifact_checksum=expected_artifact_checksum)

    def revise(
        self, lead_id: int, *, reviewed_content: dict[str, Any] | None = None,
        asset_keys: list[str] | None = None, art_direction: dict[str, Any] | None = None,
        expected_lead: dict[str, Any] | None = None, expected_artifact_checksum: str | None = None,
    ) -> tuple[SiteGenerationResult, Lead | None]:
        return self._run(lead_id, None, overwrite=True, revision=True,
                         reviewed_content=reviewed_content, asset_keys=asset_keys, art_direction=art_direction,
                         expected_lead=expected_lead, expected_artifact_checksum=expected_artifact_checksum)

    def _run(
        self, lead_id: int, research: dict[str, Any] | None, *, overwrite: bool, revision: bool,
        reviewed_content: dict[str, Any] | None, asset_keys: list[str] | None, art_direction: dict[str, Any] | None,
        expected_lead: dict[str, Any] | None, expected_artifact_checksum: str | None,
    ) -> tuple[SiteGenerationResult, Lead | None]:
        from business_prospector.domain.first_website import FirstWebsiteMarketReport
        if type(lead_id) is not int or lead_id < 1:
            raise ValidationError('persisted lead id is required')
        lead = self._repository.get(lead_id)
        if lead is None:
            raise ValidationError('persisted lead not found')
        if expected_lead is not None and lead.to_dict() != expected_lead:
            raise ValidationError('lead changed after art direction validation')
        allowed = {'internal_website', 'site_ready', 'sales_preview'} if revision else {'qualified'}
        if lead.status not in allowed:
            raise ValidationError('persisted lead must be an internal draft or unpublished preview' if revision else 'persisted lead must have qualified status')
        if revision and self._repository.get_deployment(lead.id) is not None:
            raise ValidationError('reserved deployment artifacts cannot be revised')
        if lead.opportunity_type != 'first_website':
            raise ValidationError('only first_website generation is supported; redesign remains unsupported')
        if revision and not SiteDraftService(self._generator.sites_root).inspect(lead.slug or '').exists:
            raise ValidationError('revision requires an existing valid internal draft')
        stored = FirstWebsiteMarketReport.from_dict(lead.market_research).to_dict()
        supplied = stored if research is None else FirstWebsiteMarketReport.from_dict(research).to_dict()
        if supplied != stored:
            raise ValidationError('generation research must match the persisted lead research')
        assets, source_root = None, None
        if asset_keys is not None:
            if not isinstance(asset_keys, list):
                raise ValidationError('asset_keys must be a list')
            if asset_keys:
                if self._asset_library is None:
                    raise ValidationError('reviewed local asset library is unavailable')
                assets, source_root = self._asset_library.load(lead, asset_keys)
            else:
                assets = ()
        updated = None
        def commit_status():
            nonlocal updated
            # Reject a concurrently changed lead instead of overwriting a later lifecycle decision.
            current = self._repository.get(lead_id)
            if self._repository.get_deployment(lead_id) is not None:
                raise ValidationError('reserved deployment artifacts cannot be revised')
            if current is None or current.to_dict() != lead.to_dict():
                raise ValidationError('lead changed during generation; retry with current data')
            updated = self._repository.update(lead_id, {'status': 'internal_website'})
        result = self._generator.generate(
            lead.to_dict(), supplied, overwrite=overwrite, reviewed_content=reviewed_content,
            assets=assets, asset_source_root=source_root, after_install=commit_status, art_direction=art_direction, expected_artifact_checksum=expected_artifact_checksum,
        )
        return result, updated
