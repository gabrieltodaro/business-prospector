"""Offline art-direction browser matrix. Synthetic businesses; optional local stock bytes.

Recorded photo judgments are development-agent observations, replayed for reproducibility;
this script does not pretend to run a live vision model or grant human approval.
"""
import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path

from business_prospector.application.art_direction import ArtDirectionService
from business_prospector.application.config import ProspectingConfig
from business_prospector.application.first_website import FirstWebsiteProspectingService
from business_prospector.application.site_generation import PersistedSiteGenerationWorkflow, SiteGenerationService
from business_prospector.application.stock_photography import StockPhotographyService
from business_prospector.domain.models import BusinessCandidate
from business_prospector.domain.stock_photography import StockPhoto
from business_prospector.infrastructure.design_store import DesignStore
from business_prospector.infrastructure.local_site_assets import LocalSiteAssetLibrary
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository
from business_prospector.infrastructure.visual_browser import ChromiumPageCapture
from business_prospector.premium_demo import LocalDemonstrationPhotos


class UnavailableVision:
    async def evaluate(self, prompt, images):
        return None


async def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    repo = SQLiteLeadRepository(args.output / 'synthetic.db')
    prospect = FirstWebsiteProspectingService(repo, ProspectingConfig())
    workflow = PersistedSiteGenerationWorkflow(repo, SiteGenerationService(args.output / 'sites'), LocalSiteAssetLibrary(args.output / 'reviewed-assets'))
    fixtures = json.loads(Path('src/business_prospector/resources/premium_site_demos.json').read_text())
    references = json.loads(Path('docs/design-reference-assessments.json').read_text())
    browser = ChromiumPageCapture(args.chromium)
    results = []
    for fixture in fixtures:
        for variant in range(2):
            target = copy.deepcopy(fixture['business'])
            category = target['category']
            target['name'] = {'dentist': ['Horizonte Preventivo Demo', 'Clínica Linha Demo'],
                'restaurant': ['Mesa de Oliva Demo', 'Cantina Alameda Demo'],
                'beauty_salon': ['Ateliê Aurora Demo', 'Estúdio Forma Demo']}[category][variant]
            target['external_place_id'] += '-' + str(variant)
            # Preserve deduplication protection: each synthetic business has distinct public identity.
            target['phone'] = '+55 11 0000-' + str(len(results) + 1000)
            target['maps_url'] = 'https://maps.google.com/?q=synthetic-' + str(len(results))
            target['address'] = 'Rua Fictícia ' + str(len(results)) + ', 100'
            research = copy.deepcopy(fixture['research'])
            third = {**research['benchmarks'][0], 'name': 'Terceira referência sintética',
                     'external_place_id': category + '-third', 'website_url': 'https://' + category + '-third.example', 'rating': 4.8, 'review_count': 1800}
            research['benchmarks'].append(third)
            for frequency in research['common_features']:
                frequency.update(observed_in=3, total=3)
            pool = [{k: v for k, v in b.items() if k in BusinessCandidate.__dataclass_fields__} | {'city': 'São Paulo, SP'} for b in research['benchmarks']]
            selection = prospect.select_benchmarks(target, pool, 3)
            research['selection_id'] = selection.selection_id
            outcome = prospect.qualify_and_save(target, research, 'offline-art-direction')
            if outcome.lead is None:
                raise RuntimeError(outcome.reason)
            lead = outcome.lead
            # The second dental example is deliberately sparse.
            content = copy.deepcopy(fixture['reviewed_content']) if not (category == 'dentist' and variant == 1) else None
            if content:
                content['target'] = {'slug': lead.slug, 'external_place_id': lead.external_place_id}
            photo = StockPhoto(**fixture['stock_photo'])
            provider = LocalDemonstrationPhotos(photo, args.stock_directory) if args.stock_directory else None
            service = ArtDirectionService(repo, workflow, StockPhotographyService(repo, provider, args.output),
                DesignStore(args.output), UnavailableVision(), browser, args.output / 'sites')
            fallback = await service.plan(lead.id, content)
            plan = fallback['plan']
            plan.update(typography='modern' if variant == 1 else 'editorial', density='compact',
                        palette={'dentist': ['sage', 'slate'], 'restaurant': ['terracotta', 'slate'], 'beauty_salon': ['rose', 'slate']}[category][variant],
                        hero_composition='minimal_typography', image_placement='none')
            if content:
                field = 'menu' if category == 'restaurant' else 'services'
                value = content['facts'][field]['value'][0]
                plan['headline'] = {'text': value + '.', 'evidence': ['fact:' + field + ':0']}
                plan['supporting_copy'] = {'text': 'Conheça ' + lead.name + ', em ' + lead.city + '.', 'evidence': ['lead:name', 'lead:city']}
                for section in plan['sections']:
                    section['emphasis'] = 'feature' if section['kind'] == field and variant == 0 else 'quiet'
                # Deliberate, meaningful hierarchy variation: information before reputation or vice versa.
                middle = plan['sections'][1:-1]
                if variant: middle.reverse()
                plan['sections'] = [plan['sections'][0], *middle, plan['sections'][-1]]
            plan['primary_action'] = 'Consultar horários' if content else 'Entrar em contato'
            prepared = await service.plan(lead.id, content, proposed=plan)
            keys, rejected = [], []
            if provider:
                selected = service.stock.search(lead.id, content)
                job = await service.photo(prepared['plan_id'], selected['selection_id'], photo.photo_id)
                reference = references['agent_photo_observations'][photo.photo_id]
                actual = hashlib.sha256((args.stock_directory / (photo.photo_id + '.jpg')).read_bytes()).hexdigest()
                if actual != reference['sha256']:
                    raise RuntimeError('local photo differs from visually inspected reference')
                review = service.complete(job['job_id'], reference['assessment'], 'development-agent-vision/replayed-reference')
                if review['assessment']['accepted']:
                    curated = service.curate(review['review_id'])
                    keys.append(curated['asset_key'])
                    plan.update(hero_asset_key=keys[0], focal_point=review['assessment']['focal_point'], image_placement='hero',
                                hero_composition=('full_width_photography' if variant == 0 else 'image_led') if category == 'restaurant' else ('asymmetric_photography' if variant == 0 else 'editorial_split'))
                    prepared = await service.plan(lead.id, content, proposed=plan)
                else:
                    rejected.append(review['review_id'])
            generated = service.generate(prepared['plan_id'], keys)
            review = await service.review(prepared['plan_id'])
            job, images = service.job(review['job_id'])
            screenshot_dir = args.output / 'screenshots' / lead.slug
            screenshot_dir.mkdir(parents=True)
            for image in images:
                (screenshot_dir / (image.label + '.png')).write_bytes(image.content)
            results.append({'name': lead.name, 'category': category, 'variant': variant, 'plan_id': prepared['plan_id'],
                'job_id': review['job_id'], 'checks': job['checks'], 'rejected_photo_reviews': rejected,
                'site_path': generated['result']['site_path'], 'artifact_checksum': job['artifact_checksum']})
    (args.output / 'validation.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps({'examples': len(results), 'output': str(args.output), 'checks': [r['checks'] for r in results]}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stock-directory', type=Path)
    parser.add_argument('--chromium', default='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    asyncio.run(main(parser.parse_args()))
