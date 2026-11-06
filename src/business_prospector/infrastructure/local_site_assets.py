"""Read reviewed assets from one business-scoped local library, without downloads."""
from pathlib import Path

from business_prospector.application.artifacts import read_local_manifest, read_local_asset
from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.models import Lead
from business_prospector.domain.site_assets import SiteAsset


class LocalSiteAssetLibrary:
    def __init__(self, root: Path) -> None:
        self.root = root

    def load(self, lead: Lead, keys: list[str]) -> tuple[tuple[SiteAsset, ...], Path]:
        if not isinstance(keys, list) or len(keys) > 30 or not all(isinstance(key, str) for key in keys) or len(set(keys)) != len(keys):
            raise ValidationError('asset_keys must be up to 30 distinct reviewed keys')
        if self.root.is_symlink():
            raise ValidationError("asset library cannot be a symlink")
        root = self.root / (lead.slug or '')
        manifest = read_local_manifest(root, 'asset-manifest.json')
        if manifest.get('lead_identity') != {'slug': lead.slug, 'external_place_id': lead.external_place_id}:
            raise ValidationError('asset library belongs to a different business')
        raw = manifest.get('assets')
        if not isinstance(raw, list) or len(raw) > 30:
            raise ValidationError('invalid reviewed asset library')
        assets = tuple(SiteAsset.from_manifest(item) for item in raw)
        by_key = {asset.key: asset for asset in assets}
        if len(by_key) != len(assets) or set(keys) - set(by_key):
            raise ValidationError('unknown or duplicate reviewed asset keys')
        selected = tuple(by_key[key] for key in keys)
        for asset in selected:
            if asset.approval_status not in {'approved_for_draft', 'approved_for_publish'}:
                raise ValidationError('selected asset is not approved for draft')
            read_local_asset(root, asset)
        return selected, root
