"""Three synthetic premium sites, optionally using explicitly supplied local Pexels photos.

No API calls, production data or publication. See docs/premium-generation.md for sources.
"""
from __future__ import annotations

import argparse
import json
from importlib.resources import files
from pathlib import Path

from business_prospector.application.config import ProspectingConfig
from business_prospector.application.first_website import FirstWebsiteProspectingService
from business_prospector.application.site_assets import DownloadedImage
from business_prospector.application.site_generation import PersistedSiteGenerationWorkflow, SiteGenerationService
from business_prospector.application.stock_photography import StockPhotographyService
from business_prospector.domain.models import BusinessCandidate
from business_prospector.domain.stock_photography import StockPhoto, StockSearchPlan
from business_prospector.infrastructure.local_site_assets import LocalSiteAssetLibrary
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository


class LocalDemonstrationPhotos:
    display_name = "Pexels"
    attribution_url = "https://www.pexels.com"

    def __init__(self, photo: StockPhoto, directory: Path) -> None:
        self.photo, self.directory = photo, directory

    def search(self, plan: StockSearchPlan) -> tuple[StockPhoto, ...]:
        return (self.photo,) if self.photo.matches(plan) else ()

    def download(self, photo: StockPhoto) -> DownloadedImage:
        if photo != self.photo:
            raise ValueError('unknown demonstration photo')
        return DownloadedImage((self.directory / (photo.photo_id + '.jpg')).read_bytes(), 'image/jpeg')


def generate_premium_demonstrations(output: Path, stock_directory: Path | None = None) -> list[dict]:
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    fixtures = json.loads(files('business_prospector').joinpath('resources', 'premium_site_demos.json').read_text())
    repository = SQLiteLeadRepository(output / 'synthetic.db')
    prospecting = FirstWebsiteProspectingService(repository, ProspectingConfig())
    workflow = PersistedSiteGenerationWorkflow(repository, SiteGenerationService(output / 'sites'), LocalSiteAssetLibrary(output / 'reviewed-assets'))
    results = []
    for fixture in fixtures:
        target, research = fixture['business'], fixture['research']
        pool = [{key: value for key, value in benchmark.items() if key in BusinessCandidate.__dataclass_fields__}
                | {'city': 'São Paulo, SP'} for benchmark in research['benchmarks']]
        selection = prospecting.select_benchmarks(target, pool)
        report = {**research, 'selection_id': selection.selection_id}
        outcome = prospecting.qualify_and_save(target, report, 'synthetic-premium')
        if outcome.lead is None:
            raise RuntimeError(outcome.reason or outcome.outcome)
        lead = outcome.lead
        reviewed = {**fixture['reviewed_content'], 'target': {'slug': lead.slug, 'external_place_id': lead.external_place_id}}
        keys = []
        if stock_directory:
            provider = LocalDemonstrationPhotos(StockPhoto(**fixture['stock_photo']), stock_directory)
            stock = StockPhotographyService(repository, provider, output)
            candidates = stock.search(lead.id, reviewed)
            if not candidates['photos']:
                raise RuntimeError('demonstration photo does not match search intent')
            asset = stock.approve_for_draft(lead.id, candidates['selection_id'], provider.photo.photo_id,
                reviewed_by='Synthetic demonstration review; illustrative use only', review_confirmed=True)
            keys.append(asset.key)
        generated, updated = workflow.generate(lead.id, lead.market_research, reviewed_content=reviewed, asset_keys=keys)
        if not generated.ok:
            raise RuntimeError(generated.error)
        results.append({'category': lead.category, 'status': updated.status, **generated.to_dict()})
    (output / 'demonstrations.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stock-directory', type=Path, help='Explicit directory with the three reviewed photo-ID.jpg files; no downloads')
    args = parser.parse_args()
    print(json.dumps(generate_premium_demonstrations(args.output, args.stock_directory), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
