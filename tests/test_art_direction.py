"""Synthetic vision responses prove contracts, not subjective commercial quality."""
import asyncio
import base64
import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from business_prospector.application.art_direction import ArtDirectionService, assessment_schema
from business_prospector.application.config import ProspectingConfig
from business_prospector.application.first_website import FirstWebsiteProspectingService
from business_prospector.application.site_generation import PersistedSiteGenerationWorkflow, SiteGenerationService, SiteDraftService
from business_prospector.application.sales_preview import SalesPreviewLifecycleService
from business_prospector.application.stock_photography import StockPhotographyService
from business_prospector.application.site_assets import DownloadedImage
from business_prospector.application.visual_ports import VisualResponse, VisualImage, RenderCapture
from business_prospector.application.artifacts import capture_artifact
from business_prospector.domain.art_direction import ArtDirectionPlan, BENCHMARK_DIMENSIONS
from business_prospector.domain.exceptions import ValidationError
from business_prospector.infrastructure.design_store import DesignStore
from business_prospector.infrastructure.local_site_assets import LocalSiteAssetLibrary
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository
from business_prospector.infrastructure.mcp_vision import McpVisualEvaluator
from test_first_website import candidate, research, selected_research
from test_stock_photography import FakeStockProvider
from test_site_assets import PNG


def run(awaitable):
    return asyncio.run(awaitable)


class Vision:
    def __init__(self):
        self.response = None
        self.calls = []
    async def evaluate(self, prompt, images):
        self.calls.append((prompt, images))
        return VisualResponse(self.response, 'synthetic-test-vision') if self.response else None


class Browser:
    def capture(self, site):
        return RenderCapture((VisualImage('desktop', PNG), VisualImage('mobile', PNG)), {
            viewport: {'images_loaded': True, 'image_alts': True, 'headings': True, 'language': True,
                       'anchors': True, 'touch_targets': True, 'hero_cta_visible': True, 'overflow': False,
                       'external_requests': 0, 'page_errors': 0, 'duplicate_blocks': 0, 'mobile_menu': True}
            for viewport in ('desktop', 'mobile')})


@pytest.fixture
def design(tmp_path):
    repo = SQLiteLeadRepository(tmp_path / 'test.db')
    prospect = FirstWebsiteProspectingService(repo, ProspectingConfig())
    report = research()
    report['benchmarks'].append({**report['benchmarks'][0], 'name': 'Third benchmark',
        'website_url': 'https://third.example', 'external_place_id': 'third', 'rating': 4.7, 'review_count': 2000})
    for row in report['common_features']:
        row.update(observed_in=3, total=3)
    report = selected_research(prospect, candidate(), report)
    lead = prospect.qualify_and_save(candidate(), report, 'art-direction-tests').lead
    provider, vision = FakeStockProvider(), Vision()
    stock = StockPhotographyService(repo, provider, tmp_path)
    workflow = PersistedSiteGenerationWorkflow(repo, SiteGenerationService(tmp_path / 'sites'), LocalSiteAssetLibrary(tmp_path / 'reviewed-assets'))
    service = ArtDirectionService(repo, workflow, stock, DesignStore(tmp_path), vision, Browser(), tmp_path / 'sites')
    return service, lead, vision, provider


def verdict(kind='photo', fail=None, revisions=None):
    data = assessment_schema(kind)
    data['criteria'] = {k: {'verdict': 'fail' if k == fail else 'pass',
        'evidence': 'Synthetic visual response: bright red instruments conflict with the quiet sage plan.' if k == fail else 'Synthetic visual evidence for contract testing.'} for k in data['criteria']}
    data['rejection_reasons'] = ['Dominant red clinical instruments are inappropriate.'] if fail else []
    data['revisions'] = revisions or {}
    return data


def test_fallback_is_explicit_and_does_not_invent_services(design):
    service, lead, vision, _ = design
    before = service.repository.get(lead.id).to_dict()
    plan = run(service.plan(lead.id))
    assert not plan['visual_judgment'] and plan['evaluator'] == 'deterministic_fallback'
    assert plan['plan']['headline']['text'] == lead.name
    assert 'about' not in [r['kind'] for r in plan['plan']['sections']]
    assert service.repository.get(lead.id).to_dict() == before
    assert not vision.calls[0][1]


@pytest.mark.parametrize('damage', ['invented_reference', 'section', 'duplicate', 'unsafe_enum', 'focal', 'extra', 'unsafe_cta'])
def test_untrusted_plan_is_bounded(design, damage):
    service, lead, _, _ = design
    baseline = run(service.plan(lead.id))
    plan = copy.deepcopy(baseline['plan'])
    if damage == 'invented_reference': plan['headline']['evidence'] = ['competitor:credentials']
    if damage == 'section': plan['sections'].insert(1, {'kind': 'credentials', 'purpose': 'Fabrication', 'emphasis': 'feature'})
    if damage == 'duplicate': plan['sections'].insert(1, plan['sections'][0])
    if damage == 'unsafe_enum': plan['palette'] = 'red; background:url(https://evil.example)'
    if damage == 'focal': plan['focal_point'] = [float('nan'), 0]
    if damage == 'extra': plan['css'] = 'unsafe'
    if damage == 'unsafe_cta': plan['primary_action'] = '<script>alert(1)</script>'
    if damage == 'unsafe_cta':
        changed = run(service.plan(lead.id, proposed=plan))
        result = service.generate(changed['plan_id'])
        assert '<script>' not in Path(result['result']['site_path']).joinpath('index.html').read_text()
    else:
        with pytest.raises(ValidationError): run(service.plan(lead.id, proposed=plan))


def test_photo_pixels_rejected_without_asset_or_fake_human_approval(design):
    service, lead, vision, _ = design
    plan = run(service.plan(lead.id))
    selection = service.stock.search(lead.id)
    vision.response = verdict(fail='color_harmony')
    review = run(service.photo(plan['plan_id'], selection['selection_id'], '123'))
    assert vision.calls[-1][1][0].content == PNG
    assert not review['assessment']['accepted']
    with pytest.raises(ValidationError, match='accepted pixel'): service.curate(review['review_id'])
    assert not service.store.root.parent.joinpath('reviewed-assets').exists()


def test_agent_curation_exact_bytes_provenance_and_publication_boundary(design):
    service, lead, vision, _ = design
    plan = run(service.plan(lead.id))
    selection = service.stock.search(lead.id)
    vision.response = verdict()
    review = run(service.photo(plan['plan_id'], selection['selection_id'], '123'))
    curated = service.curate(review['review_id'])
    assert curated['asset']['approval_status'] == 'agent_curated_draft'
    assert curated['asset']['stock']['review_kind'] == 'agent_curation'
    assert curated['asset']['stock']['visual_assessment_id'] == review['review_id']
    assert not curated['publication_approved']
    result = service.generate(plan['plan_id'], [curated['asset_key']])
    assert result['lead']['status'] == 'internal_website'
    manifest = json.loads(Path(result['result']['site_path']).joinpath('site-manifest.json').read_text())
    assert not manifest.get('commercial_approval')
    assert manifest['assets'][0]['rights_status'] == 'licensed'


def test_changed_photo_bytes_never_inherit_visual_acceptance(design):
    service, lead, vision, provider = design
    plan = run(service.plan(lead.id))
    selection = service.stock.search(lead.id)
    vision.response = verdict()
    review = run(service.photo(plan['plan_id'], selection['selection_id'], '123'))
    provider.image = DownloadedImage(PNG + b'changed', 'image/png')
    with pytest.raises(ValidationError, match='changed after'): service.curate(review['review_id'])
    assert not list(service.store.root.parent.glob('reviewed-assets/*/asset-manifest.json'))


def test_unavailable_vision_handoff_preserves_exact_images_and_stale_evidence(design):
    service, lead, _, _ = design
    plan = run(service.plan(lead.id))
    service.generate(plan['plan_id'])
    job = run(service.review(plan['plan_id']))
    assert job['status'] == 'vision_unavailable'
    record, images = service.job(job['job_id'])
    assert len(images) == 2 and all(i.content == PNG for i in images)
    review = service.complete(job['job_id'], verdict('page', fail='composition', revisions={'density': 'balanced'}), 'client-vision')
    revised = service.revise(review['review_id'])
    assert revised['status'] == 'revised'
    with pytest.raises(ValidationError, match='stale'): service.revise(review['review_id'])
    assert list(service.sites_root.glob('.revisions/**/*')) or list(service.sites_root.parent.glob('**/*revision*'))


def test_context_change_invalidates_plan_and_unrelated_fields_preserved(design):
    service, lead, _, _ = design
    before = lead.to_dict()
    plan = run(service.plan(lead.id))
    service.generate(plan['plan_id'])
    after = service.repository.get(lead.id).to_dict()
    for key in before:
        if key not in {'status', 'updated_at'}: assert before[key] == after[key]
    service.repository.update(lead.id, {'phone': '17123456789'})
    with pytest.raises(ValidationError, match='evidence changed'): service.generate(plan['plan_id'])


def test_bounded_cycle_stops_when_score_stalls(design):
    service, lead, vision, _ = design
    plan = run(service.plan(lead.id))
    vision.response = verdict('page', fail='composition', revisions={'density': 'balanced'})
    result = run(service.cycle(plan['plan_id']))
    assert len(result['history']) == 2 and not result['ready_for_human_review']
    assert not result['publication_approved']
    assert service.store.read(result['cycle_id'])['kind'] == 'cycle'


@pytest.mark.parametrize('limit', [0, 4, True, '3'])
def test_cycle_budget_rejected_before_generation(design, limit):
    service, lead, _, _ = design
    plan = run(service.plan(lead.id))
    with pytest.raises(ValidationError): run(service.cycle(plan['plan_id'], max_iterations=limit))
    assert not service.sites_root.exists()


def test_benchmark_pixels_sources_inform_plan_without_becoming_business_facts(design):
    service, lead, vision, _ = design
    selection = service.repository.get_benchmark_selection(lead.market_research['selection_id'])
    screenshots = [{'source_url': b['website_url'], 'viewport': v, 'png_base64': base64.b64encode(PNG).decode()}
                   for b in selection['selected'] for v in ('desktop', 'mobile')]
    vision.response = {'websites': [{'source_url': b['website_url'], 'observations': {k: 'Visible test evidence: compact hero and readable mobile navigation.' for k in BENCHMARK_DIMENSIONS}} for b in selection['selected']]}
    review = run(service.benchmark(lead.id, screenshots))
    assert len(vision.calls[-1][1]) == 6
    vision.response = None
    plan = run(service.plan(lead.id, benchmark_ids=[review['review_id']]))
    assert plan['research_status'] == 'three_visual_references'
    assert 'compact hero' in vision.calls[-1][0]
    assert plan['plan']['headline']['evidence'] == ['lead:name']
    screenshots[0]['source_url'] = 'https://unselected.example'
    with pytest.raises(ValidationError): run(service.benchmark(lead.id, screenshots))


def test_private_store_rejects_traversal_symlinks_and_changed_pixels(tmp_path):
    store = DesignStore(tmp_path)
    with pytest.raises(ValidationError): store.read('../private')
    rows = store.save_images((VisualImage('mobile', PNG),))
    (store.root / rows[0]['file']).write_bytes(b'altered')
    with pytest.raises(ValidationError): store.load_images(rows)
    (store.root / rows[0]['file']).unlink()
    (store.root / rows[0]['file']).symlink_to(tmp_path / 'secret')
    with pytest.raises(ValidationError): store.load_images(rows)


def test_sampling_unavailable_is_not_visual_acceptance():
    session = Mock()
    session.check_client_capability.return_value = False
    assert run(McpVisualEvaluator(session).evaluate('Inspect', (VisualImage('photo', PNG),))) is None
    session.create_message.assert_not_called()


def test_mcp_design_tools_registered_without_context_in_schema():
    from business_prospector.mcp.server import mcp
    tools = {t.name: t for t in run(mcp.list_tools())}
    names = {'analyze_benchmark_design', 'create_art_direction_plan', 'search_stock_photos_for_plan', 'evaluate_stock_photo', 'get_visual_evaluation_job',
             'submit_visual_evaluation', 'curate_stock_photo_for_draft', 'generate_art_directed_website',
             'review_website_design', 'revise_website_design', 'run_visual_design_cycle'}
    assert names <= tools.keys()
    assert all('ctx' not in tools[n].inputSchema.get('properties', {}) for n in names)


def test_revision_invalidates_human_approval_and_preserves_previous_artifact_on_failure(design, monkeypatch):
    service, lead, vision, _ = design
    plan = run(service.plan(lead.id))
    service.generate(plan['plan_id'])
    lifecycle = SalesPreviewLifecycleService(service.repository, SiteDraftService(service.sites_root))
    lifecycle.approve(lead.id, content_review_acknowledged=True, asset_keys_approved_for_publish=[], approved_by='Synthetic human approval fixture')
    site = service.sites_root / lead.slug
    original = capture_artifact(site)
    vision.response = verdict('page', fail='hierarchy', revisions={'density': 'balanced'})
    review = run(service.review(plan['plan_id']))
    update = service.repository.update
    def failure(*args, **kwargs):
        raise RuntimeError('synthetic transaction failure')
    monkeypatch.setattr(service.repository, 'update', failure)
    with pytest.raises(RuntimeError, match='transaction failure'): service.revise(review['review_id'])
    assert capture_artifact(site) == original
    assert service.repository.get(lead.id).status == 'sales_preview'
    monkeypatch.setattr(service.repository, 'update', update)
    service.revise(review['review_id'])
    assert 'sales_preview' not in json.loads(capture_artifact(site).manifest_bytes)
    assert service.repository.get(lead.id).status == 'internal_website'


def test_concurrent_artifact_change_rejected_under_generation_lock(design, monkeypatch):
    service, lead, vision, _ = design
    plan = run(service.plan(lead.id))
    service.generate(plan['plan_id'])
    vision.response = verdict('page', fail='hierarchy', revisions={'density': 'balanced'})
    review = run(service.review(plan['plan_id']))
    generate = service.generate
    site = service.sites_root / lead.slug
    def concurrent_change(*args, **kwargs):
        (site / 'styles.css').write_text((site / 'styles.css').read_text() + '\n/* concurrent edit */')
        return generate(*args, **kwargs)
    monkeypatch.setattr(service, 'generate', concurrent_change)
    with pytest.raises(ValidationError, match='stale'): service.revise(review['review_id'])


def test_model_cannot_revise_business_facts_or_add_unsupported_claim_references(design):
    service, lead, vision, _ = design
    plan = run(service.plan(lead.id))
    service.generate(plan['plan_id'])
    vision.response = verdict('page', fail='content', revisions={'headline': {'text': 'Invented credentials', 'evidence': ['benchmark:credentials']}})
    review = run(service.review(plan['plan_id']))
    original = capture_artifact(service.sites_root / lead.slug)
    with pytest.raises(ValidationError, match='unsupported business evidence'): service.revise(review['review_id'])
    assert capture_artifact(service.sites_root / lead.slug) == original
    vision.response = verdict('page', revisions={'approved_by': 'model'})
    with pytest.raises(ValidationError, match='unsupported visual revision'): run(service.review(plan['plan_id']))


def test_plan_controls_hierarchy_copy_focal_and_selection(design):
    service, lead, vision, _ = design
    baseline = run(service.plan(lead.id))
    selection = service.stock.search(lead.id)
    vision.response = verdict()
    review = run(service.photo(baseline['plan_id'], selection['selection_id'], '123'))
    key = service.curate(review['review_id'])['asset_key']
    plan = baseline['plan']
    plan.update(hero_composition='asymmetric_photography', image_placement='hero', hero_asset_key=key,
                focal_point=[.25,.7], typography='display', density='airy', responsive_composition='image_first')
    plan['headline'] = {'text': 'Nome verificado: ' + lead.name, 'evidence': ['lead:name']}
    planned = run(service.plan(lead.id, proposed=plan))
    generated = service.generate(planned['plan_id'], [key])
    html = Path(generated['result']['site_path']).joinpath('index.html').read_text()
    assert 'layout-asymmetric_photography' in html and 'density-airy' in html and 'type-display' in html
    assert 'object-position:25% 70%' in html and 'responsive-image_first' in html
    assert 'Nome verificado:' in html
    plan['image_placement'] = 'detail'
    detail = run(service.plan(lead.id, proposed=plan))
    service.generate(detail['plan_id'])
    html = Path(generated['result']['site_path']).joinpath('index.html').read_text()
    assert 'class="detail-media"' in html and 'class="hero-media"' not in html


def test_art_direction_search_keeps_category_filter_and_bounded_query(design):
    service, lead, _, provider = design
    plan = run(service.plan(lead.id))
    selection = service.search_photos(plan['plan_id'], 'dental care natural light', 'landscape')
    assert selection['plan']['query'] == 'dental care natural light'
    assert 'dental' in selection['plan']['relevance_terms']
    with pytest.raises(ValidationError): service.search_photos(plan['plan_id'], 'https://private.example/?key=secret')
    with pytest.raises(ValidationError): service.search_photos(plan['plan_id'], 'dental', 'giant')


def test_sampling_transmits_pixels_and_handles_client_denial():
    from mcp import types
    from unittest.mock import AsyncMock
    session = Mock()
    session.check_client_capability.return_value = True
    session.create_message = AsyncMock(return_value=types.CreateMessageResult(role='assistant',
        content=types.TextContent(type='text', text=json.dumps(verdict())), model='authorized-client-model', stopReason='endTurn'))
    result = run(McpVisualEvaluator(session).evaluate('Inspect pixels', (VisualImage('photo', PNG),)))
    assert result.evaluator == 'authorized-client-model'
    messages = session.create_message.call_args.args[0]
    assert base64.b64decode(messages[-1].content.data) == PNG
    session.create_message.side_effect = RuntimeError('private provider diagnostics')
    assert run(McpVisualEvaluator(session).evaluate('Inspect', ())) is None


def test_capture_unavailable_never_claims_readiness(design):
    service, lead, _, _ = design
    plan = run(service.plan(lead.id))
    service.generate(plan['plan_id'])
    service.capture = Mock()
    service.capture.capture.side_effect = RuntimeError('browser missing')
    result = run(service.review(plan['plan_id']))
    assert result == {'status': 'capture_unavailable', 'ready_for_human_review': False, 'reason': 'RuntimeError'}


def test_mcp_job_returns_native_images(design):
    from mcp.server.fastmcp import FastMCP
    from mcp import types
    from business_prospector.mcp.design_tools import register_design_tools
    service, lead, _, _ = design
    plan = run(service.plan(lead.id))
    service.generate(plan['plan_id'])
    job = run(service.review(plan['plan_id']))
    mcp = FastMCP('isolated-design-tools-test')
    register_design_tools(mcp, lambda ctx: service)
    result = run(mcp.call_tool('get_visual_evaluation_job', {'job_id': job['job_id']}))
    # FastMCP normalizes list[TextContent|ImageContent] to native protocol content.
    blocks = result[0] if isinstance(result, tuple) else result
    assert sum(isinstance(b, types.ImageContent) for b in blocks) == 2
    assert any(isinstance(b, types.TextContent) and 'PLAN' in b.text for b in blocks)


def test_existing_two_benchmark_draft_can_add_visual_research_without_mutating_legacy_report(design):
    from business_prospector.domain.models import BusinessCandidate
    service, _, vision, _ = design
    prospect = FirstWebsiteProspectingService(service.repository, ProspectingConfig())
    target = candidate(name='Legacy visual fixture', external_place_id='legacy-visual', phone='17111111111')
    legacy_report = selected_research(prospect, target, research())
    legacy = prospect.qualify_and_save(target, legacy_report, 'legacy-visual').lead
    plan = run(service.plan(legacy.id))
    service.generate(plan['plan_id'])
    before = service.repository.get(legacy.id).to_dict()
    references = [{k:v for k,v in b.items() if k in BusinessCandidate.__dataclass_fields__} | {'city':'São Paulo, SP'} for b in legacy_report['benchmarks']]
    references.append({**references[0], 'name':'New visual reference', 'external_place_id':'new-visual', 'website_url':'https://new-visual.example'})
    selection = prospect.select_benchmarks(target, references)
    screenshots = [{'source_url': b.website_url, 'viewport':v, 'png_base64':base64.b64encode(PNG).decode()} for b in selection.selected for v in ('desktop','mobile')]
    vision.response = {'websites':[{'source_url':b.website_url, 'observations':{k:'Synthetic pixel evidence.' for k in BENCHMARK_DIMENSIONS}} for b in selection.selected]}
    result = run(service.benchmark(legacy.id, screenshots, selection_id=selection.selection_id))
    assert result['status'] == 'assessed'
    assert service.repository.get(legacy.id).to_dict() == before
    foreign = prospect.select_benchmarks(candidate(name='Other', external_place_id='foreign'), references)
    with pytest.raises(ValidationError, match='different target'):
        run(service.benchmark(legacy.id, screenshots, selection_id=foreign.selection_id))
