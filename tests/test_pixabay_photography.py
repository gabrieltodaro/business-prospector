from dataclasses import replace
from email.message import Message
import io
import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.stock_photography import stock_search_plan
from business_prospector.infrastructure.pixabay import PixabayStockPhotoProvider, LICENSE_URL
from business_prospector.infrastructure.pexels import PexelsStockPhotoProvider
from business_prospector.infrastructure.stock_provider import configured_stock_provider
from business_prospector.infrastructure import stock_http
from test_site_assets import PNG


def hit(**changes):
    value = {'id': 123, 'type': 'photo', 'pageURL': 'https://pixabay.com/photos/dental-123/',
        'largeImageURL': 'https://pixabay.com/get/example_1280.jpg', 'imageWidth': 4000, 'imageHeight': 3000,
        'user': 'Synthetic Photographer', 'user_id': 42, 'tags': 'dental, instruments, still life'}
    return value | changes


def response(hits):
    return json.dumps({'hits': hits}).encode(), 'application/json'


def test_pixabay_cache_secret_isolation_orientation_and_local_download(tmp_path):
    calls, now = [], [100000.0]
    def request(url, headers, maximum):
        calls.append((url, headers, maximum))
        return response([hit(ignored='do not persist')]) if urlsplit(url).path == '/api/' else (PNG, 'image/png')
    provider = PixabayStockPhotoProvider('synthetic-private-key', tmp_path, request=request, clock=lambda: now[0])
    plan = stock_search_plan('dentist', ())
    selected = provider.search(plan)[0]
    assert (selected.width, selected.height) == (1280, 960)
    assert selected.provider == 'pixabay' and selected.license_url == LICENSE_URL
    assert selected.photographer_url == 'https://pixabay.com/users/Synthetic%20Photographer-42/'
    query = parse_qs(urlsplit(calls[0][0]).query)
    assert query['key'] == ['synthetic-private-key']
    assert query['orientation'] == ['horizontal'] and query['safesearch'] == ['true']
    assert query['per_page'] == ['15'] and query['image_type'] == ['photo']
    now[0] += 86399
    assert provider.search(plan) == (selected,) and len(calls) == 1
    assert provider.download(selected).content == PNG
    assert calls[1][1] == {} and 'key=' not in calls[1][0]
    assert all('synthetic-private-key' not in p.read_text() and 'do not persist' not in p.read_text() for p in tmp_path.iterdir())
    now[0] += 1
    assert provider.search(plan) and len(calls) == 3


@pytest.mark.parametrize('changes', [{'type': 'illustration'}, {'id': True}, {'user_id': 0},
    {'tags': 'generic office meeting'}, {'imageWidth': 1000, 'imageHeight': 500},
    {'imageWidth': 6000, 'imageHeight': 3000}, {'imageWidth': '4000'},
    {'largeImageURL': 'https://evil.example/photo.jpg'}, {'pageURL': 'https://evil.example/'},
    {'largeImageURL': 'https://pixabay.com/get/image.jpg?key=secret'}, {'tags': '<script>unknown</script>'}])
def test_rejects_unsuitable_or_malformed_candidates(tmp_path, changes):
    provider = PixabayStockPhotoProvider('test', tmp_path, request=lambda *a: response([hit(**changes)]))
    assert not provider.search(stock_search_plan('dentist', ()))


@pytest.mark.parametrize('url', ['http://cdn.pixabay.com/photo/a.jpg', 'https://cdn.pixabay.com.evil.example/photo/a.jpg',
    'https://user:pass@cdn.pixabay.com/photo/a.jpg', 'https://cdn.pixabay.com:444/photo/a.jpg',
    'https://pixabay.com/api/', 'https://cdn.pixabay.com/user/avatar.jpg', 'https://127.0.0.1/photo/a.jpg',
    'https://pixabay.com/get/image.jpg?token=secret'])
def test_download_origin_checks_precede_network(tmp_path, url):
    calls = []
    provider = PixabayStockPhotoProvider('test', tmp_path, request=lambda *a: response([hit()]))
    selected = provider.search(stock_search_plan('dentist', ()))[0]
    provider._request = lambda *a: calls.append(a)
    with pytest.raises(ValidationError):
        provider.download(replace(selected, download_url=url))
    assert not calls


@pytest.mark.parametrize('payload,mime', [({'hits': None}, 'application/json'), ({'hits': [{}] * 16}, 'application/json'),
    ([], 'application/json'), ({'hits': []}, 'text/html')])
def test_provider_failure_cooldown_survives_new_instances(tmp_path, payload, mime):
    calls = []
    def request(*a):
        calls.append(a)
        return json.dumps(payload).encode(), mime
    for _ in range(2):
        provider = PixabayStockPhotoProvider('test', tmp_path, request=request)
        with pytest.raises(stock_http.StockProviderUnavailable): provider.search(stock_search_plan('dentist', ()))
    assert len(calls) == 1


def test_api_url_and_error_body_never_leak(monkeypatch):
    headers = Message()
    headers['Retry-After'] = '7200'
    class Opener:
        def open(self, *args, **kwargs):
            raise HTTPError('https://pixabay.com/api/?key=PRIVATE', 429, 'PRIVATE', headers, io.BytesIO(b'PRIVATE'))
    monkeypatch.setattr(stock_http, 'build_opener', lambda *args: Opener())
    with pytest.raises(stock_http.StockProviderUnavailable) as error:
        stock_http._request('https://pixabay.com/api/?key=PRIVATE', {}, 1024)
    assert 'PRIVATE' not in str(error.value) and error.value.retry_after == 7200
    assert stock_http._NoRedirects().redirect_request(None, None, 302, '', {}, 'https://evil.example') is None


@pytest.mark.parametrize('selection,keys,expected', [
    ('auto', {}, None), ('auto', {'PEXELS_API_KEY': 'test'}, PexelsStockPhotoProvider),
    ('auto', {'PIXABAY_API_KEY': 'test', 'PEXELS_API_KEY': 'test'}, PixabayStockPhotoProvider),
    ('pexels', {'PIXABAY_API_KEY': 'test', 'PEXELS_API_KEY': 'test'}, PexelsStockPhotoProvider),
    ('pixabay', {'PEXELS_API_KEY': 'test'}, None), ('pexels', {'PIXABAY_API_KEY': 'test'}, None),
    ('none', {'PIXABAY_API_KEY': 'test'}, None)])
def test_provider_configuration_is_explicit_and_backward_compatible(tmp_path, selection, keys, expected):
    provider = configured_stock_provider(keys | {'BUSINESS_PROSPECTOR_STOCK_PROVIDER': selection}, tmp_path)
    assert provider is None if expected is None else isinstance(provider, expected)


def test_wrong_provider_receipt_cannot_download(tmp_path):
    from test_stock_photography import photo
    provider = PixabayStockPhotoProvider('test', tmp_path, request=lambda *a: pytest.fail('network must not run'))
    with pytest.raises(ValidationError): provider.download(photo())
    with pytest.raises(ValidationError): configured_stock_provider({'BUSINESS_PROSPECTOR_STOCK_PROVIDER': 'unsupported'}, tmp_path)


def test_cache_symlinks_are_refused(tmp_path):
    other = tmp_path / 'other'
    other.mkdir()
    cache = tmp_path / 'cache'
    cache.symlink_to(other, target_is_directory=True)
    provider = PixabayStockPhotoProvider('test', cache, request=lambda *a: pytest.fail('network must not run'))
    with pytest.raises(ValidationError): provider.search(stock_search_plan('dentist', ()))
    assert not list(other.iterdir())
    with pytest.raises(ValidationError):
        configured_stock_provider({'PIXABAY_API_KEY': 'test'}, cache)


def test_pixabay_adapter_through_review_generation_and_inventory(tmp_path):
    from pathlib import Path
    from business_prospector.application.config import ProspectingConfig
    from business_prospector.application.first_website import FirstWebsiteProspectingService
    from business_prospector.application.stock_photography import StockPhotographyService
    from business_prospector.application.site_generation import PersistedSiteGenerationWorkflow, SiteGenerationService
    from business_prospector.application.artifacts import capture_artifact
    from business_prospector.infrastructure.local_site_assets import LocalSiteAssetLibrary
    from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository
    from test_first_website import candidate, research, selected_research
    repo = SQLiteLeadRepository(tmp_path / 'test.db')
    prospecting = FirstWebsiteProspectingService(repo, ProspectingConfig())
    report = selected_research(prospecting, candidate(), research())
    lead = prospecting.qualify_and_save(candidate(), report, 'pixabay-tests').lead
    calls = []
    def request(url, headers, maximum):
        calls.append(url)
        return response([hit()]) if urlsplit(url).path == '/api/' else (PNG, 'image/png')
    provider = PixabayStockPhotoProvider('synthetic-private', tmp_path / 'cache', request=request)
    service = StockPhotographyService(repo, provider, tmp_path)
    selection = service.search(lead.id)
    assert len(calls) == 1 and selection['attribution']['url'] == 'https://pixabay.com'
    with pytest.raises(ValidationError):
        service.approve_for_draft(lead.id, selection['selection_id'], '123', reviewed_by='Reviewer', review_confirmed=False)
    before = repo.get(lead.id).to_dict()
    asset = service.approve_for_draft(lead.id, selection['selection_id'], '123', reviewed_by='Reviewer', review_confirmed=True)
    assert len(calls) == 2 and repo.get(lead.id).to_dict() == before
    assert asset.stock.license_url == LICENSE_URL and asset.approval_status == 'approved_for_draft'
    workflow = PersistedSiteGenerationWorkflow(repo, SiteGenerationService(tmp_path / 'sites'), LocalSiteAssetLibrary(tmp_path / 'reviewed-assets'))
    result, _ = workflow.generate(lead.id, report, asset_keys=[asset.key])
    path = Path(result.site_path)
    html = (path / 'index.html').read_text()
    assert 'Photos provided by Pixabay' in html and '<img src="https:' not in html
    assert 'Imagem ilustrativa de banco' in html
    capture_artifact(path)
    assert all('synthetic-private' not in p.read_text() for p in path.glob('*.json'))
    manifest_path = path / 'site-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['assets'][0]['stock']['illustrative'] = False
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValidationError): capture_artifact(path)
