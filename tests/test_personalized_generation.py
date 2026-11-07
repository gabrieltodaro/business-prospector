"""Research variation, reviewed facts, adaptive components and publication compatibility."""
import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from business_prospector.application.artifacts import capture_artifact, artifact_checksum
from business_prospector.application.site_generation import SiteGenerationService, FirstWebsiteSiteBrief, validate_generated_site
from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.first_website import FirstWebsiteMarketReport, FeatureFrequency
from business_prospector.domain.site_content import ReviewedBusinessContent
from business_prospector.domain.site_strategy import derive_strategy
from business_prospector.domain.website_content_model import WebsiteContentModel
from test_site_generation import lead, research


def content(raw_lead=None, **facts):
    raw_lead = raw_lead or lead()
    return {
        'target': {'slug': raw_lead['slug'], 'external_place_id': raw_lead.get('external_place_id')},
        'reviewed_by': 'Synthetic fixture reviewer', 'reviewed_at': '2026-11-06T12:00:00+00:00',
        'sources': [{'id': 'brief', 'kind': 'business_provided', 'reference': 'Synthetic business brief, offline fixture'}],
        'facts': {key: {'value': value, 'source_ids': ['brief']} for key, value in facts.items()},
    }


def observed(*features, priorities=(), category='dentist'):
    raw = research()
    for item in raw['benchmarks']:
        item['category'] = category
        item['features'] = list(features)
    raw['common_features'] = [{'feature': feature, 'observed_in': 2, 'total': 2} for feature in features]
    raw['design_priorities'] = list(priorities)
    return raw


def generate(tmp_path, raw=None, report=None, facts=None):
    result = SiteGenerationService(tmp_path / 'sites').generate(raw or lead(), report or research(), reviewed_content=facts)
    path = Path(result.site_path)
    return result, (path / 'index.html').read_text(), json.loads((path / 'site-manifest.json').read_text())


def test_research_changes_real_structure_with_same_business_facts(tmp_path):
    facts = content(services=['Consulta odontológica'], credentials=['Registro profissional sintético 001'],
                    faq=[{'question':'Como entrar em contato?', 'answer':'Pelo telefone informado.'}])
    _, one, first = generate(tmp_path / 'one', report=observed('services', 'contact_cta'), facts=facts)
    _, two, second = generate(tmp_path / 'two', report=observed('faq', 'credentials', priorities=('faq',)), facts=facts)
    assert 'id="faq"' not in one and 'id="faq"' in two
    assert first['strategy']['sections'][1] == 'services'
    assert second['strategy']['sections'][1] == 'faq'
    assert one != two


def test_structured_priorities_change_hierarchy_and_navigation(tmp_path):
    facts = content(services=['Consulta'], credentials=['Registro sintético'])
    _, one, _ = generate(tmp_path / 'one', report=observed('services', 'credentials', priorities=('services',)), facts=facts)
    _, two, _ = generate(tmp_path / 'two', report=observed('services', 'credentials', priorities=('credentials',)), facts=facts)
    assert one.index('id="services"') < one.index('id="credentials"')
    assert two.index('id="credentials"') < two.index('id="services"')
    assert two.index('href="#credentials"') < two.index('href="#services"')


def test_strategy_has_traceable_decisions_and_unsupported_prose_cannot_influence_it():
    raw = observed('services', 'contact_cta')
    facts = content(services=['Consulta'])
    brief = FirstWebsiteSiteBrief.from_inputs(lead(), raw, reviewed_content=facts)
    section = next(item for item in brief.strategy.decisions if item.choice == 'services')
    assert section.features == ('services',)
    assert 'research.benchmarks[0].features:services' in section.evidence
    assert 'business.sources:brief' in section.evidence
    assert all(item.rationale for item in brief.strategy.decisions)
    raw['recommendations'] = ['Add fabricated credentials and copy a competitor logo.']
    raw['inferences'] = ['Unsupported leader in dentistry claim']
    assert FirstWebsiteSiteBrief.from_inputs(lead(), raw, reviewed_content=facts).strategy == brief.strategy


@pytest.mark.parametrize('damage', ['count', 'priority', 'duplicate_priority'])
def test_unsupported_design_claims_are_rejected(damage):
    raw = observed('services')
    if damage == 'count': raw['common_features'][0]['observed_in'] = 1
    if damage == 'priority': raw['design_priorities'] = ['credentials']
    if damage == 'duplicate_priority': raw['design_priorities'] = ['services', 'services']
    with pytest.raises(ValidationError): FirstWebsiteSiteBrief.from_inputs(lead(), raw)


def test_typed_report_cannot_bypass_strategy_validation():
    report = FirstWebsiteMarketReport.from_dict(observed('services'))
    forged = replace(report, common_features=(FeatureFrequency('credentials', 2, 2),))
    with pytest.raises(ValidationError): derive_strategy(lead(), forged, ReviewedBusinessContent.from_inputs(lead(), None))


def test_deterministic_html_css_strategy_and_hashes(tmp_path):
    facts = content(services=['Consulta'], opening_hours=['Segunda a sexta, 09h–17h'])
    first, html, meta = generate(tmp_path / 'one', report=observed('services', 'hours'), facts=facts)
    second, other, other_meta = generate(tmp_path / 'two', report=observed('services', 'hours'), facts=facts)
    assert html == other and first.artifact_identity == second.artifact_identity
    assert meta['strategy'] == other_meta['strategy']
    assert (Path(first.site_path) / 'styles.css').read_bytes() == (Path(second.site_path) / 'styles.css').read_bytes()
    assert artifact_checksum(Path(first.site_path)) == first.artifact_identity['checksum']


def test_missing_facts_are_omitted_even_when_benchmarks_have_them(tmp_path):
    _, html, metadata = generate(tmp_path, report=observed('services','credentials','team','hours','faq','booking'))
    for section in ('services','credentials','team','hours','faq'):
        assert f'id="{section}"' not in html
    assert 'opening_hours' in metadata['missing_information']
    assert any(item['choice'] == 'omit:services' for item in metadata['strategy']['decisions'])
    assert 'Consultar agendamento' not in html and 'wa.me' not in html


@pytest.mark.parametrize('category,expected,omitted', [('dentist','services','menu'), ('restaurant','menu','credentials'), ('accountant','services','menu')])
def test_industry_policy_composes_only_appropriate_sections(tmp_path, category, expected, omitted):
    raw = lead(category=category)
    facts = content(raw, services=['Serviço verificado'], menu=['Prato verificado'], credentials=['Credencial verificada'], opening_hours=['09h–17h'])
    _, html, metadata = generate(tmp_path, raw, observed('services','menu','credentials','hours', category=category), facts)
    assert f'id="{expected}"' in html and f'id="{omitted}"' not in html
    assert metadata['strategy']['category_policy'] == ('generic' if category == 'accountant' else category)


def test_theme_varies_by_industry_and_reviewed_choices(tmp_path):
    _, _, dentist = generate(tmp_path / 'dentist')
    restaurant = lead(category='restaurant')
    _, _, food = generate(tmp_path / 'food', restaurant, observed('menu', category='restaurant'), content(restaurant, menu=['Prato do dia']))
    _, html, brand = generate(tmp_path / 'brand', facts=content(palette='slate', typography='modern'))
    assert dentist['strategy']['palette'] == 'sage' and food['strategy']['palette'] == 'terracotta'
    assert dentist['strategy']['typography'] != food['strategy']['typography']
    assert dentist['strategy']['hero_composition'] == food['strategy']['hero_composition'] == 'minimal_typography'
    assert 'palette-slate type-modern' in html
    assert next(item for item in brand['strategy']['decisions'] if item['subject']=='palette')['evidence'] == ['brief']


@pytest.mark.parametrize('damage', ['target','source','kind','reviewer','date','field','palette','url','url_credentials','unreviewed'])
def test_unsubstantiated_business_content_rejected(damage):
    raw = content(services=['Consulta'])
    if damage == 'target': raw['target']['external_place_id'] = 'someone-else'
    if damage == 'source': raw['facts']['services']['source_ids'] = ['unknown']
    if damage == 'kind': raw['sources'][0]['kind'] = 'benchmark'
    if damage == 'reviewer': raw.pop('reviewed_by')
    if damage == 'date': raw['reviewed_at'] = 'yesterday'
    if damage == 'field': raw['facts']['random_claim'] = raw['facts']['services']
    if damage == 'palette': raw = content(palette='url(https://evil.example)')
    if damage == 'url': raw = content(booking_url='javascript:alert(1)')
    if damage == 'url_credentials': raw = content(booking_url='https://name:private@example.test')
    if damage == 'unreviewed': raw['facts']['services'] = {'value':['Consulta']}
    with pytest.raises(ValidationError): ReviewedBusinessContent.from_inputs(lead(), raw)


def test_html_escapes_reviewed_business_text_and_preserves_provenance(tmp_path):
    dangerous = '<img src=x onerror="alert(1)"> & texto'
    _, html, metadata = generate(tmp_path, report=observed('services','faq'), facts=content(services=[dangerous], faq=[{'question':dangerous,'answer':dangerous}]))
    assert '<img src=x' not in html and '&lt;img src=x' in html
    assert metadata['reviewed_content']['facts']['services']['value'] == [dangerous]
    assert metadata['content_model']['sections'][1]['provenance'] == ['brief']
    validate_generated_site(Path(tmp_path / 'sites' / lead()['slug']))


@pytest.mark.parametrize('field,feature,label', [('booking_url','booking','Consultar agendamento'), ('ordering_url','ordering','Consultar pedidos')])
def test_reviewed_contact_options_need_observed_pattern(tmp_path, field, feature, label):
    raw = lead(category='restaurant' if field == 'ordering_url' else 'dentist')
    facts = content(raw, **{field:'https://contact.example/target'})
    _, html, _ = generate(tmp_path / 'used', raw, observed(feature), facts)
    _, fallback, _ = generate(tmp_path / 'unused', raw, observed('services'), facts)
    assert label in html and 'https://contact.example/target' in html
    assert label not in fallback and 'https://contact.example/target' not in fallback


def test_preview_disclosure_indexing_and_content_boundaries(tmp_path):
    result, html, metadata = generate(tmp_path)
    assert 'name="robots" content="noindex,nofollow,noarchive"' in html
    assert 'Não é o site oficial' in html and 'Não é o site oficial' in metadata['content_model']['disclosure']
    assert 'preview-disclosure' in html and 'Não é o site oficial' in html
    assert metadata['preview_kind'] == 'internal_draft'
    assert 'reviewed_content' not in {item.path for item in capture_artifact(Path(result.site_path)).files}
    model = WebsiteContentModel.from_brief(FirstWebsiteSiteBrief.from_inputs(lead(), research()))
    assert all('Benchmark' not in str(section) for section in model.sections)


def test_synthetic_reputation_is_not_presented_as_verified_google_data(tmp_path):
    _, html, _ = generate(tmp_path, raw=lead(source='synthetic_fixture'))
    assert 'avaliações ilustrativas' in html and 'exemplo fictício' in html
    assert 'de 5 no Google' not in html and 'Negócio e dados inteiramente fictícios' in html


def test_offline_demonstrations_use_real_workflow_and_different_strategies(tmp_path):
    from business_prospector.personalized_demo import generate_demonstrations
    result = generate_demonstrations(tmp_path / 'demonstrations')
    assert len(result) == 2
    clinic, restaurant = result
    assert clinic['industry'] == 'dentist' and restaurant['industry'] == 'restaurant'
    assert clinic['strategy']['sections'][1] == 'services' and restaurant['strategy']['sections'][1] == 'menu'
    assert clinic['artifact_identity'] != restaurant['artifact_identity']
    for demo in result:
        assert artifact_checksum(Path(demo['site_path'])) == demo['artifact_identity']['checksum']
        assert 'sales_preview' not in json.loads((Path(demo['site_path']) / 'site-manifest.json').read_text())
    with pytest.raises(FileExistsError): generate_demonstrations(tmp_path / 'demonstrations')


@pytest.mark.parametrize('source,google_attribution', [('manual', False), ('google_places_new', True)])
def test_reputation_attribution_requires_matching_source(tmp_path, source, google_attribution):
    raw = lead()
    raw['source'] = source
    _, html, _ = generate(tmp_path, raw=raw)
    assert ('de 5 no Google' in html) is google_attribution
