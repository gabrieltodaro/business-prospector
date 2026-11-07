from pathlib import Path
import json

import pytest

from business_prospector.application.site_generation import SiteGenerationService
from business_prospector.application.artifacts import capture_artifact
from business_prospector.domain.site_generation import FirstWebsiteSiteBrief
from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.website_content_model import WebsiteContentModel, display_name
from business_prospector.premium_demo import generate_premium_demonstrations
from test_site_generation import lead, research
from test_personalized_generation import content, observed


@pytest.mark.parametrize('category,features,facts,images,ratio,expected', [
    ('dentist', ('services',), {'services':['Consulta']}, 1, .7, 'editorial_split'),
    ('restaurant', ('menu',), {'menu':['Prato verificado']}, 1, 1.5, 'full_width_photography'),
    ('beauty_salon', ('services',), {'services':['Corte']}, 1, .7, 'asymmetric_photography'),
    ('dentist', ('gallery',), {}, 2, 1.5, 'image_led'),
    ('dentist', ('services',), {}, 0, None, 'minimal_typography'),
])
def test_composition_uses_evidence_category_and_available_assets(category, features, facts, images, ratio, expected):
    raw = lead(category=category)
    report = observed(*features, category=category)
    if 'gallery' in features:
        report['design_priorities'] = ['gallery']
    brief = FirstWebsiteSiteBrief.from_inputs(raw, report, reviewed_content=content(raw, **facts), image_count=images, hero_aspect_ratio=ratio)
    assert brief.strategy.hero_composition == expected
    assert brief.strategy == FirstWebsiteSiteBrief.from_inputs(raw, report, reviewed_content=content(raw, **facts), image_count=images, hero_aspect_ratio=ratio).strategy


def test_portrait_food_image_does_not_force_full_width_crop():
    raw = lead(category='restaurant')
    brief = FirstWebsiteSiteBrief.from_inputs(raw, observed('menu', category='restaurant'),
        reviewed_content=content(raw, menu=['Prato']), image_count=1, hero_aspect_ratio=.65)
    assert brief.strategy.hero_composition != 'full_width_photography'


def test_research_changes_same_business_art_direction():
    raw = lead()
    report = observed('services', 'gallery')
    report['design_priorities'] = ['gallery']
    first = FirstWebsiteSiteBrief.from_inputs(raw, report, image_count=2)
    report['design_priorities'] = ['services']
    second = FirstWebsiteSiteBrief.from_inputs(raw, report, image_count=2)
    assert first.strategy.hero_composition == 'image_led'
    assert second.strategy.hero_composition == 'editorial_split'


@pytest.mark.parametrize('name', ['Clínica Horizonte | Dentista, implantes e clínica em Cidade',
    'Nome muito longo ' * 10, '<script>alert(1)</script> & clínica', 'Dra. Exemplo — Informações comerciais'])
def test_listing_names_are_not_headlines_and_identity_remains_exact(tmp_path, name):
    raw = lead(name=name)
    result = SiteGenerationService(tmp_path / 'sites').generate(raw, research())
    path = Path(result.site_path)
    metadata = json.loads((path / 'site-manifest.json').read_text())
    model = metadata['content_model']
    assert model['name'] == name.strip() and model['headline'] != name
    assert len(model['display_name']) <= 52
    html = (path / 'index.html').read_text()
    assert '<script>' not in html and 'hero-visual.svg' not in html


def test_no_unverified_biography_or_empty_contact_or_repeated_address(tmp_path):
    raw = lead(address='Rua Única, 10', phone=None, maps_url=None, instagram=None, review_count=0)
    result = SiteGenerationService(tmp_path / 'sites').generate(raw, research())
    html = Path(result.site_path).joinpath('index.html').read_text()
    assert 'id="sobre"' not in html and 'id="contato"' not in html
    assert html.count('Rua Única, 10') == 1
    assert 'href="#location"' in html


def test_typography_inventory_is_explicit_and_cannot_hide_unlisted_files(tmp_path):
    result = SiteGenerationService(tmp_path / 'sites').generate(lead(), research())
    path = Path(result.site_path)
    metadata = json.loads((path / 'site-manifest.json').read_text())
    assert metadata['assets'] == [] and metadata['visual_mode'] == 'typography'
    snapshot = capture_artifact(path)
    assert {f.path for f in snapshot.files} == {'index.html', 'styles.css'}
    snapshot.write_to(tmp_path / 'snapshot')
    assert capture_artifact(tmp_path / 'snapshot').identity() == snapshot.identity()
    (path / 'assets' / 'private.txt').write_text('private')
    with pytest.raises(ValidationError): capture_artifact(path)


def test_three_synthetic_demos_without_network_and_no_production_defaults(tmp_path):
    results = generate_premium_demonstrations(tmp_path / 'demos')
    assert {r['category'] for r in results} == {'dentist', 'restaurant', 'beauty_salon'}
    assert all(r['status'] == 'internal_website' for r in results)
    assert len({r['strategy']['palette'] for r in results}) == 3
    for result in results:
        html = Path(result['site_path']).joinpath('index.html').read_text()
        assert 'inteiramente fictícios' in html and 'noindex,nofollow,noarchive' in html
        assert 'Gapps.Tech' in html
    with pytest.raises(FileExistsError): generate_premium_demonstrations(tmp_path / 'demos')
