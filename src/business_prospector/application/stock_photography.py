"""Explicit stock selection, human draft review and immutable local asset ingestion."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.models import Lead
from business_prospector.domain.site_assets import SiteAsset
from business_prospector.domain.site_generation import FirstWebsiteSiteBrief
from business_prospector.domain.stock_photography import StockPhoto, StockProvenance, stock_search_plan
from .artifacts import read_local_manifest, site_operation_lock
from .ports import LeadRepository, StockPhotoProvider
from .site_assets import SiteAssetIngestionService


class StockPhotographyService:
    def __init__(self, repository: LeadRepository, provider: StockPhotoProvider | None, data_root: Path) -> None:
        self._repository, self._provider, self._root = repository, provider, data_root

    def _lead(self, lead_id: int) -> Lead:
        if type(lead_id) is not int or lead_id < 1:
            raise ValidationError('persisted lead id is required')
        lead = self._repository.get(lead_id)
        if lead is None or lead.opportunity_type != 'first_website' or lead.status not in {'qualified', 'internal_website', 'site_ready', 'sales_preview'}:
            raise ValidationError('stock selection requires an eligible first_website lead')
        if self._repository.get_deployment(lead_id) is not None:
            raise ValidationError('reserved deployment assets cannot be changed')
        return lead

    def search(self, lead_id: int, reviewed_content: dict[str, Any] | None = None) -> dict[str, Any]:
        lead = self._lead(lead_id)
        brief = FirstWebsiteSiteBrief.from_inputs(lead.to_dict(), lead.market_research, reviewed_content=reviewed_content, allow_revision=True)
        plan = stock_search_plan(brief.category, tuple(f.feature for f in brief.market_research.common_features), brief.reviewed_content.values('menu'))
        attribution = {'label': f'Photos provided by {self._provider.display_name}', 'url': self._provider.attribution_url} if self._provider else None
        base = {'attribution': attribution, 'photos': [], 'selection_id': None}
        if self._provider is None or plan is None:
            return {**base, 'status': 'unconfigured' if self._provider is None else 'unsupported_category', 'fallback': 'minimal_typography'}
        photos = tuple(photo for photo in self._provider.search(plan) if photo.matches(plan))[:6]
        selection = str(uuid4())
        folder = self._safe_directory(self._root / 'stock-selections')
        receipt = {'lead_identity': {'id': lead.id, 'slug': lead.slug, 'external_place_id': lead.external_place_id},
                   'plan': plan.to_dict(), 'photos': [p.to_dict() for p in photos], 'created_at': datetime.now(timezone.utc).isoformat()}
        (folder / (selection + '.json')).write_text(json.dumps(receipt, ensure_ascii=False))
        return {**base, 'status': 'candidates' if photos else 'no_matches', 'selection_id': selection,
                'plan': plan.to_dict(), 'photos': receipt['photos'], 'fallback': 'minimal_typography'}

    @staticmethod
    def _safe_directory(path: Path) -> Path:
        if path.is_symlink():
            raise ValidationError('stock inventory directory cannot be a symlink')
        path.mkdir(parents=True, exist_ok=True)
        return path

    def approve_for_draft(self, lead_id: int, selection_id: str, photo_id: str, *,
                          reviewed_by: str, review_confirmed: bool) -> SiteAsset:
        from uuid import UUID
        if review_confirmed is not True or not isinstance(reviewed_by, str) or not reviewed_by.strip() or len(reviewed_by) > 200:
            raise ValidationError('explicit relevance, license and illustrative-use review is required')
        try:
            if str(UUID(selection_id)) != selection_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValidationError('invalid stock selection id') from None
        if self._provider is None:
            raise ValidationError('stock provider is not configured')
        lead = self._lead(lead_id)
        with site_operation_lock(self._root / 'sites', lead.slug or ''):
            if self._lead(lead_id).to_dict() != lead.to_dict():
                raise ValidationError('lead changed during stock review')
            receipt = read_local_manifest(self._root / 'stock-selections', selection_id + '.json')
            if receipt.get('lead_identity') != {'id': lead.id, 'slug': lead.slug, 'external_place_id': lead.external_place_id}:
                raise ValidationError('stock selection belongs to another lead')
            age = datetime.now(timezone.utc) - datetime.fromisoformat(receipt['created_at'])
            if not 0 <= age.total_seconds() <= 86400:
                raise ValidationError('stock selection expired; search again')
            matches = [p for p in receipt['photos'] if p['photo_id'] == photo_id]
            if len(matches) != 1:
                raise ValidationError('photo was not selected by this stock search')
            photo = StockPhoto(**matches[0])
            stock = StockProvenance(photo.provider, photo.photo_id, photo.source_page, photo.photographer,
                photo.photographer_url, photo.license_url, receipt['plan']['query'], reviewed_by.strip(), datetime.now(timezone.utc).isoformat())
            stock = StockProvenance.from_dict(stock.to_dict())
            library = self._safe_directory(self._root / 'reviewed-assets')
            root = self._safe_directory(library / lead.slug)
            assets = self._safe_directory(root / 'assets')
            path = root / 'asset-manifest.json'
            identity = {'slug': lead.slug, 'external_place_id': lead.external_place_id}
            manifest = read_local_manifest(root, path.name) if path.exists() or path.is_symlink() else {'lead_identity': identity, 'assets': []}
            if manifest.get('lead_identity') != identity or not isinstance(manifest.get('assets'), list) or len(manifest['assets']) >= 30:
                raise ValidationError('invalid or full reviewed asset inventory')
            for existing in manifest['assets']:
                SiteAsset.from_manifest(existing)
            key = photo.provider + '-' + hashlib.sha256(photo.photo_id.encode()).hexdigest()[:12] + '-' + uuid4().hex[:10]
            # Downloaded MIME is checked against the ingestion signatures before persistence.
            downloaded = self._provider.download(photo)
            candidate = SiteAsset(key, 'photo', 'licensed_stock', photo.download_url, photo.source_page, False,
                                  'licensed', 'approved_for_draft', 'Imagem ilustrativa: ' + photo.description[:260],
                                  photo.width, photo.height, downloaded.mime_type, len(downloaded.content), stock=stock)
            ingested = SiteAssetIngestionService(lambda _: downloaded).ingest(candidate, assets)
            temporary = root / ('.manifest-' + uuid4().hex + '.json')
            try:
                manifest['assets'].append(ingested.to_dict())
                temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
                temporary.replace(path)
            except BaseException:
                (root / ingested.local_file).unlink(missing_ok=True)
                raise
            finally:
                temporary.unlink(missing_ok=True)
            return ingested
