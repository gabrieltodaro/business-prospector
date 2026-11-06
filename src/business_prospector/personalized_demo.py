"""Generate two entirely synthetic, unpublished examples in an explicit new directory."""
from __future__ import annotations

import argparse
import json
from importlib.resources import files
from pathlib import Path

from business_prospector.application.config import ProspectingConfig
from business_prospector.application.first_website import FirstWebsiteProspectingService
from business_prospector.application.site_generation import PersistedSiteGenerationWorkflow, SiteGenerationService
from business_prospector.domain.models import BusinessCandidate
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository


def generate_demonstrations(output: Path) -> list[dict]:
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    fixtures = json.loads(files('business_prospector').joinpath('resources', 'personalized_site_demos.json').read_text(encoding='utf-8'))
    repository = SQLiteLeadRepository(output / 'synthetic.db')
    prospecting = FirstWebsiteProspectingService(repository, ProspectingConfig())
    workflow = PersistedSiteGenerationWorkflow(repository, SiteGenerationService(output / 'sites'))
    results = []
    for fixture in fixtures:
        target, research = fixture['business'], fixture['research']
        pool = [{key: value for key, value in benchmark.items() if key in BusinessCandidate.__dataclass_fields__}
                | {'city': 'São Paulo, SP'} for benchmark in research['benchmarks']]
        receipt = prospecting.select_benchmarks(target, pool)
        report = {**research, 'selection_id': receipt.selection_id}
        outcome = prospecting.qualify_and_save(target, report, 'synthetic-phase-2')
        if outcome.lead is None:
            raise RuntimeError(outcome.reason or outcome.outcome)
        reviewed = {**fixture['reviewed_content'], 'target': {'slug': outcome.lead.slug, 'external_place_id': outcome.lead.external_place_id}}
        result, _ = workflow.generate(outcome.lead.id, outcome.lead.market_research, reviewed_content=reviewed)
        if not result.ok:
            raise RuntimeError(result.error)
        results.append({'name': outcome.lead.name, 'industry': outcome.lead.category, **result.to_dict()})
    (output / 'demonstrations.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New isolated directory; never defaults to operational data')
    args = parser.parse_args()
    print(json.dumps(generate_demonstrations(args.output), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
