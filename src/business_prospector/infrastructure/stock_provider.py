"""Runtime stock provider selection; no network calls or automatic failure failover."""
from collections.abc import Mapping
from pathlib import Path

from business_prospector.application.ports import StockPhotoProvider
from business_prospector.domain.exceptions import ValidationError
from .pexels import PexelsStockPhotoProvider
from .pixabay import PixabayStockPhotoProvider


def configured_stock_provider(environment: Mapping[str, str], cache_root: Path) -> StockPhotoProvider | None:
    selected = environment.get('BUSINESS_PROSPECTOR_STOCK_PROVIDER', 'auto').strip().lower()
    if selected not in {'auto', 'pixabay', 'pexels', 'none'}:
        raise ValidationError('stock provider must be auto, pixabay, pexels or none')
    if selected == 'auto':
        selected = 'pixabay' if environment.get('PIXABAY_API_KEY') else 'pexels'
    if selected == 'pixabay':
        key = environment.get('PIXABAY_API_KEY', '')
        if key and cache_root.is_symlink():
            raise ValidationError('stock cache cannot be a symlink')
        return PixabayStockPhotoProvider(key, cache_root / 'pixabay') if key else None
    if selected == 'pexels':
        key = environment.get('PEXELS_API_KEY', '')
        # Preserve the original Pexels cache location; Pixabay has its own namespace.
        return PexelsStockPhotoProvider(key, cache_root) if key else None
    return None
