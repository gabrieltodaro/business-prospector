import asyncio
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path

import pytest

from business_prospector.application.config import ProspectingConfig
from business_prospector.application.first_website import FirstWebsiteProspectingService
from business_prospector.application.stock_photography import StockPhotographyService
from business_prospector.application.site_assets import DownloadedImage
from business_prospector.application.site_generation import SiteGenerationService, PersistedSiteGenerationWorkflow, SiteDraftService
from business_prospector.application.sales_preview import SalesPreviewLifecycleService
from business_prospector.application.artifacts import capture_artifact
from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.stock_photography import StockPhoto, StockProvenance, stock_search_plan
from business_prospector.infrastructure.pexels import PexelsStockPhotoProvider, StockProviderUnavailable, _NoRedirects
from business_prospector.infrastructure.local_site_assets import LocalSiteAssetLibrary
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository
from business_prospector.mcp import server
from test_first_website import candidate, research, selected_research
from test_site_assets import PNG


def photo(**changes):
    value = StockPhoto('pexels', '123', 'https://www.pexels.com/photo/123/',
        'https://images.pexels.com/photos/123/test.jpg', 'Synthetic Photographer',
        'https://www.pexels.com/@synthetic/', 'https://www.pexels.com/license/', 1600, 1100,
        'Dental instruments on a table')
    return replace(value, **changes)


class FakeStockProvider:
    display_name = "Pexels"
    attribution_url = "https://www.pexels.com"

    def __init__(self):
        self.photos, self.downloads = (photo(),), 0
        self.image = DownloadedImage(PNG, 'image/png')
    def search(self, plan):
        return self.photos
    def download(self, selected):
        self.downloads += 1
        return self.image


@pytest.fixture
def setup(tmp_path):
    repo = SQLiteLeadRepository(tmp_path / 'test.db')
    prospecting = FirstWebsiteProspectingService(repo, ProspectingConfig())
    report = selected_research(prospecting, candidate(), research())
    lead = prospecting.qualify_and_save(candidate(), report, 'stock-tests').lead
    provider = FakeStockProvider()
    return repo, lead, provider, StockPhotographyService(repo, provider, tmp_path), tmp_path


def approve(setup):
    _, lead, _, service, _ = setup
    results = service.search(lead.id)
    return service.approve_for_draft(lead.id, results['selection_id'], '123', reviewed_by='Test reviewer', review_confirmed=True)


@pytest.mark.parametrize('category,terms,orientation', [('dentista', ('dental',), 'landscape'),
    ('restaurant', ('food',), 'landscape'), ('salão de beleza', ('salon',), 'portrait'), ('academia', ('gym',), 'landscape')])
def test_category_search_is_bounded_and_contextual(category, terms, orientation):
    plan = stock_search_plan(category, ())
    assert any(t in plan.query for t in terms) and plan.orientation == orientation
    assert stock_search_plan('unknown niche', ()) is None
    assert stock_search_plan('restaurant', (), ('Sushi e sashimi',)).query == 'sushi food table'


@pytest.mark.parametrize('changes', [{'description':'Generic office workers'}, {'width':300}, {'width':4000,'height':1000}, {'description':'Non-dental business office'}])
def test_relevance_and_crop_filter(changes):
    value = photo(**changes)
    plan = stock_search_plan('dentist', ())
    assert not value.matches(plan)


def test_search_does_not_download_or_approve(setup):
    _, lead, provider, service, root = setup
    result = service.search(lead.id)
    assert result['status'] == 'candidates' and len(result['photos']) == 1
    assert result['attribution']['url'] == 'https://www.pexels.com'
    assert provider.downloads == 0 and not (root / 'reviewed-assets').exists()


def test_review_ingestion_generation_and_approval_invalidation(setup):
    repo, lead, provider, _, root = setup
    before = repo.get(lead.id).to_dict()
    asset = approve(setup)
    assert repo.get(lead.id).to_dict() == before
    assert asset.approval_status == 'approved_for_draft' and not asset.business_identity_match
    assert asset.stock.photographer == 'Synthetic Photographer' and provider.downloads == 1
    library = LocalSiteAssetLibrary(root / 'reviewed-assets')
    assert library.load(lead, [asset.key])[0][0] == asset
    workflow = PersistedSiteGenerationWorkflow(repo, SiteGenerationService(root / 'sites'), library)
    result, updated = workflow.generate(lead.id, lead.market_research, asset_keys=[asset.key])
    path = Path(result.site_path)
    html = (path / 'index.html').read_text()
    assert 'Imagem ilustrativa de banco' in html and 'Photos provided by Pexels' in html
    assert 'Synthetic Photographer' in html and '<img src="https:' not in html
    manifest = json.loads((path / 'site-manifest.json').read_text())
    assert manifest['outreach_image_context']['contains_illustrative_stock'] is True
    assert manifest['outreach_image_context']['depicts_actual_business'] is False
    lifecycle = SalesPreviewLifecycleService(repo, SiteDraftService(root / 'sites'))
    assert not lifecycle.readiness(updated, content_review_acknowledged=True).ready
    lifecycle.approve(lead.id, content_review_acknowledged=True, asset_keys_approved_for_publish=[asset.key], approved_by='Publisher')
    assert 'sales_preview' in json.loads((path / 'site-manifest.json').read_text())
    workflow.revise(lead.id, asset_keys=[])
    manifest = json.loads((path / 'site-manifest.json').read_text())
    assert 'sales_preview' not in manifest and manifest['assets'] == []
    assert manifest['outreach_image_context']['contains_illustrative_stock'] is False
    assert capture_artifact(path).identity()['files']


@pytest.mark.parametrize('damage', ['ack', 'reviewer', 'id', 'unknown_photo', 'wrong_lead', 'expired', 'symlink', 'unsafe_image'])
def test_review_boundary_rejects_untrusted_requests_without_inventory_changes(setup, damage):
    repo, lead, provider, service, root = setup
    receipt = service.search(lead.id)
    selection, selected, reviewer, confirmed = receipt['selection_id'], '123', 'Reviewer', True
    path = root / 'stock-selections' / (selection + '.json')
    if damage == 'ack': confirmed = False
    elif damage == 'reviewer': reviewer = ''
    elif damage == 'id': selection = '../escape'
    elif damage == 'unknown_photo': selected = '999'
    elif damage in {'wrong_lead', 'expired'}:
        raw = json.loads(path.read_text())
        if damage == 'wrong_lead': raw['lead_identity']['id'] = 999
        else: raw['created_at'] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        path.write_text(json.dumps(raw))
    elif damage == 'symlink':
        (root / 'reviewed-assets').symlink_to(root / 'stock-selections', target_is_directory=True)
    else: provider.image = DownloadedImage(b'<script>not an image</script>', 'image/png')
    with pytest.raises(ValidationError):
        service.approve_for_draft(lead.id, selection, selected, reviewed_by=reviewer, review_confirmed=confirmed)
    assert not list(root.rglob('asset-manifest.json'))


def test_inventory_failure_preserves_existing_approved_bytes(setup, monkeypatch):
    _, _, _, _, root = setup
    first = approve(setup)
    files = {p: p.read_bytes() for p in (root / 'reviewed-assets').rglob('*') if p.is_file()}
    original = Path.replace
    def fail_manifest(source, destination):
        if source.name.startswith('.manifest-'):
            raise OSError('controlled failure')
        return original(source, destination)
    monkeypatch.setattr(Path, 'replace', fail_manifest)
    with pytest.raises(OSError): approve(setup)
    assert files == {p: p.read_bytes() for p in (root / 'reviewed-assets').rglob('*') if p.is_file()}


def response_photo(**changes):
    value = {'id':123,'url':'https://www.pexels.com/photo/123/', 'width':1600,'height':1100,
             'photographer':'Photographer','photographer_url':'https://www.pexels.com/@photographer/',
             'alt':'Dental tools and instruments', 'src':{'large2x':'https://images.pexels.com/photos/123/test.jpg'}}
    value.update(changes)
    return value


def test_pexels_transport_cache_expiration_and_secret_separation(tmp_path):
    calls, now = [], [100000.0]
    def request(url, headers, maximum):
        calls.append((url, headers, maximum))
        return (json.dumps({'photos':[response_photo()]}).encode(), 'application/json') if 'api.pexels.com' in url else (PNG, 'image/png')
    provider = PexelsStockPhotoProvider('test-only-private', tmp_path, request=request, clock=lambda:now[0])
    plan = stock_search_plan('dentist', ())
    selected = provider.search(plan)[0]
    assert provider.search(plan) == (selected,) and len(calls) == 1
    assert 'orientation=landscape' in calls[0][0] and 'per_page=15' in calls[0][0]
    provider.download(selected)
    assert calls[1][1] == {} and calls[0][1] == {'Authorization':'test-only-private'}
    assert all('test-only-private' not in p.read_text() for p in tmp_path.iterdir())
    now[0] += 86401
    provider.search(plan)
    assert len(calls) == 3


@pytest.mark.parametrize('url', ['http://images.pexels.com/a', 'https://evil.example/a',
    'https://images.pexels.com.evil.example/a', 'https://user:pass@images.pexels.com/a', 'https://images.pexels.com:444/a'])
def test_provider_rejects_unexpected_origins_before_download(tmp_path, url):
    calls = []
    provider = PexelsStockPhotoProvider('test', tmp_path, request=lambda *a: calls.append(a))
    with pytest.raises(ValidationError): provider.download(photo(download_url=url))
    assert not calls


def test_bad_provider_results_and_outages_fall_back_without_retry_storm(tmp_path):
    calls = []
    def unavailable(*args):
        calls.append(args)
        raise StockProviderUnavailable('safe failure')
    provider = PexelsStockPhotoProvider('test', tmp_path, request=unavailable)
    for _ in range(2):
        with pytest.raises(StockProviderUnavailable): provider.search(stock_search_plan('dentist', ()))
    assert len(calls) == 1
    assert _NoRedirects().redirect_request(None,None,302,'',{},'https://evil.example') is None


def test_empty_and_irrelevant_results_are_not_approved(setup):
    _, lead, provider, service, root = setup
    provider.photos = (photo(description='An office meeting'),)
    assert service.search(lead.id)['status'] == 'no_matches'
    assert StockPhotographyService(setup[0], None, root).search(lead.id)['status'] == 'unconfigured'


def test_mcp_stock_tools_registered_and_offline_fallback(setup, monkeypatch):
    _, lead, _, service, _ = setup
    monkeypatch.setattr(server, '_stock_service', lambda: service)
    result = server.search_stock_photos(lead.id)
    denied = server.approve_stock_photo_for_draft(lead.id, result['data']['selection_id'], '123', 'Reviewer')
    assert not denied['ok']
    allowed = server.approve_stock_photo_for_draft(lead.id, result['data']['selection_id'], '123', 'Reviewer', True)
    assert allowed['ok'] and allowed['data']['asset']['approval_status'] == 'approved_for_draft'
    names = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
    assert {'search_stock_photos', 'approve_stock_photo_for_draft'} <= names


def test_stock_metadata_tampering_invalidates_inventory(setup):
    repo, lead, _, _, root = setup
    asset = approve(setup)
    result, _ = PersistedSiteGenerationWorkflow(repo, SiteGenerationService(root / 'sites'), LocalSiteAssetLibrary(root / 'reviewed-assets')).generate(
        lead.id, lead.market_research, asset_keys=[asset.key])
    path = Path(result.site_path) / 'site-manifest.json'
    raw = json.loads(path.read_text())
    raw['assets'][0]['stock']['illustrative'] = False
    path.write_text(json.dumps(raw))
    with pytest.raises(ValidationError): capture_artifact(path.parent)


@pytest.mark.parametrize('payload', [{'photos':None}, {'photos':'bad'}, [], {'photos':[{}] * 16}])
def test_malformed_provider_payload_is_safe_and_bounded(tmp_path, payload):
    provider = PexelsStockPhotoProvider('test', tmp_path,
        request=lambda *args: (json.dumps(payload).encode(), 'application/json'))
    with pytest.raises(StockProviderUnavailable): provider.search(stock_search_plan('dentist', ()))


def test_retry_after_is_respected_across_provider_instances(tmp_path):
    now, calls = [10000], []
    def request(*args):
        calls.append(args)
        raise StockProviderUnavailable('quota', retry_after=7200)
    for moment in (10000, 14000, 17199, 17201):
        now[0] = moment
        provider = PexelsStockPhotoProvider('test', tmp_path, request=request, clock=lambda:now[0])
        with pytest.raises(StockProviderUnavailable): provider.search(stock_search_plan('dentist', ()))
    assert len(calls) == 2


def test_corrupt_cached_payload_is_replaced_by_valid_response(tmp_path):
    calls = []
    def request(*args):
        calls.append(args)
        return json.dumps({'photos':[response_photo()]}).encode(), 'application/json'
    provider = PexelsStockPhotoProvider('test', tmp_path, request=request)
    plan = stock_search_plan('dentist', ())
    assert provider.search(plan)
    path = next(tmp_path.glob('*.json'))
    raw = json.loads(path.read_text())
    raw['payload'] = ['bad']
    path.write_text(json.dumps(raw))
    assert provider.search(plan) and len(calls) == 2


def test_orientation_is_not_only_an_aspect_ratio_hint():
    assert not photo(width=1200, height=1000, description='Hair salon styling').matches(stock_search_plan('beauty_salon', ()))


def test_mcp_failure_returns_typography_fallback(setup, monkeypatch):
    _, lead, provider, service, _ = setup
    def fail(_): raise StockProviderUnavailable('safe')
    monkeypatch.setattr(provider, 'search', fail)
    monkeypatch.setattr(server, '_stock_service', lambda: service)
    result = server.search_stock_photos(lead.id)
    assert result['ok'] and result['data']['fallback'] == 'minimal_typography'


def test_http_errors_redact_payload_and_honor_retry_after(monkeypatch):
    from urllib.error import HTTPError
    from email.message import Message
    import io
    from business_prospector.infrastructure import pexels
    headers = Message()
    headers['Retry-After'] = '7200'
    class Opener:
        def open(self, *args, **kwargs):
            raise HTTPError('https://api.pexels.com/', 429, 'PRIVATE BODY', headers, io.BytesIO(b'PRIVATE BODY'))
    monkeypatch.setattr(pexels, 'build_opener', lambda *args: Opener())
    with pytest.raises(StockProviderUnavailable) as error:
        pexels._request('https://api.pexels.com/v1/search', {'Authorization':'PRIVATE KEY'}, 1024)
    assert error.value.retry_after == 7200
    assert 'PRIVATE' not in str(error.value)


def test_generation_removes_legacy_fallback_on_revision(tmp_path):
    from business_prospector.domain.site_assets import SiteAsset
    import hashlib
    from test_site_generation import lead as raw_lead, research as raw_research
    # Legacy decorative fallback supplied by an existing private manifest.
    svg = b'<svg></svg>'
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets' / 'hero-visual.svg').write_bytes(svg)
    asset = SiteAsset('hero-visual', 'illustration', 'generated', None, None, True,
        'generated', 'approved_for_publish', '', 1200, 900, 'image/svg+xml', len(svg),
        'assets/hero-visual.svg', hashlib.sha256(svg).hexdigest())
    result = SiteGenerationService(tmp_path / 'sites').generate(raw_lead(), raw_research(), assets=(asset,), asset_source_root=tmp_path)
    assert 'hero-visual' not in Path(result.site_path).joinpath('index.html').read_text()
    assert json.loads(Path(result.site_path).joinpath('site-manifest.json').read_text())['assets'] == []
