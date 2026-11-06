"""Regression coverage for public interfaces; all storage and providers are synthetic."""
import asyncio
import json
from pathlib import Path

import pytest

from business_prospector.application.batch import BatchProspectingService
from business_prospector.application.config import ProspectingConfig
from business_prospector.application.first_website import FirstWebsiteProspectingService
from business_prospector.application.lead_status import LeadStatusService
from business_prospector.application.sales_preview import SalesPreviewLifecycleService
from business_prospector.application.site_generation import SiteDraftService, PersistedSiteGenerationWorkflow, SiteGenerationService
from business_prospector.dashboard import DashboardApplication
from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.first_website import FirstWebsiteMarketReport
from business_prospector.domain.models import BusinessCandidate
from business_prospector.domain.website_assessment import WebsiteAssessmentReport
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository
from business_prospector.mcp import server
from test_batch import candidate, report
from test_first_website import candidate as first_candidate, research, selected_research
from test_sales_preview import internal_lead, generated_artifact
from test_cpanel_deployment import FakeProvider
from test_site_generation import persisted_first_website, research as generation_research


@pytest.fixture
def boundary(tmp_path, monkeypatch):
    repository = SQLiteLeadRepository(tmp_path / 'data' / 'leads.db')
    monkeypatch.setattr(server, '_repository', lambda: repository)
    monkeypatch.setattr(server, '_sites_root', lambda: tmp_path / 'sites')
    return repository


def qualified(repository):
    result = BatchProspectingService(repository, ProspectingConfig()).qualify_and_save(candidate(), report(), 'regression')
    assert result.lead is not None
    return result.lead


def test_actual_registered_mcp_lifecycle_dispatch(boundary, tmp_path):
    stored = internal_lead(boundary)
    generated_artifact(tmp_path, stored)
    result = asyncio.run(server.mcp.call_tool('get_sales_preview_readiness', {'lead_id': stored.id}))
    # The MCP dispatch must return the application result, not NameError/tool failure.
    rendered = str(result)
    assert 'artifact_valid' in rendered and 'NameError' not in rendered
    readiness = server.get_sales_preview_readiness(stored.id)
    assert readiness['ok'] and readiness['data']['artifact_valid']
    denied = server.approve_sales_preview(stored.id, False, [], 'reviewer')
    assert not denied['ok'] and boundary.get(stored.id).status == 'internal_website'
    approved = server.approve_sales_preview(stored.id, True, [], 'reviewer')
    assert approved['ok'] and boundary.get(stored.id).status == 'sales_preview'


def test_mcp_deployment_construction_and_authorization(boundary, tmp_path, monkeypatch):
    stored = internal_lead(boundary)
    generated_artifact(tmp_path, stored)
    assert server.approve_sales_preview(stored.id, True, [], 'reviewer')['ok']
    provider = FakeProvider()
    monkeypatch.setattr(server, 'HostGatorPreviewDeploymentProvider', lambda *args: provider)
    service = server._deployment_service()
    with pytest.raises(ValidationError, match='authorization'):
        service.publish(stored.id, explicitly_authorized=False)
    assert provider.publish_calls == 0
    assert server.publish_sales_preview(stored.id, explicitly_authorized=True)['ok']
    assert provider.publish_calls == 1


def test_mcp_internal_transition_requires_artifact(boundary, tmp_path):
    stored = qualified(boundary)
    assert not server.update_lead(stored.id, status='internal_website')['ok']
    generated_artifact(tmp_path, stored)
    assert server.update_lead(stored.id, status='internal_website')['ok']
    assert boundary.get(stored.id).status == 'internal_website'


@pytest.mark.parametrize('target', ['closed', 'contacted', 'proposal', 'sales_preview'])
def test_mcp_dashboard_invalid_transitions_are_atomic(boundary, target):
    stored = qualified(boundary)
    before = boundary.get(stored.id).to_dict()
    assert not server.update_lead(stored.id, status=target, name='Uncommitted name')['ok']
    with pytest.raises(ValidationError):
        DashboardApplication(boundary).change_status(stored.id, target)
    assert boundary.get(stored.id).to_dict() == before


@pytest.mark.parametrize('source,target', [('qualified','needs_review'), ('site_ready','discarded'), ('rejected','needs_review')])
def test_mcp_dashboard_share_valid_and_legacy_transitions(boundary, source, target):
    stored = qualified(boundary)
    boundary.update(stored.id, {'status': source})
    assert server.update_lead(stored.id, status=target)['ok']
    boundary.update(stored.id, {'status': source})
    assert DashboardApplication(boundary).change_status(stored.id, target).status == target


@pytest.mark.parametrize('changes', [{'rating': 1.0, 'review_count': 1}, {'review_count': True}, {'rating': True}, {'review_count': 100.5}, {'website_url': 'https://instagram.com/clinic'}])
def test_qualification_rejects_bad_reputation_types_and_presence(boundary, changes):
    result = server.qualify_and_save_candidate(candidate(**changes), report(), 'regression')
    if result['ok']:
        assert result['data']['lead'] is None
    assert boundary.list() == []


@pytest.mark.parametrize('changes', [{'rating': 1.0}, {'review_count': True}, {'review_count': 100.5}, {'website_url': 'https://elsewhere.example'}])
def test_mcp_qualified_edit_cannot_invalidate_qualification(boundary, changes):
    stored = qualified(boundary)
    before = boundary.get(stored.id).to_dict()
    assert not server.update_lead(stored.id, **changes)['ok']
    assert boundary.get(stored.id).to_dict() == before


def test_qualification_status_requires_structured_evidence(boundary):
    stored = internal_lead(boundary, 'redesign')
    boundary.update(stored.id, {'status': 'needs_review', 'rating': 4.9, 'review_count': 120})
    assert not server.update_lead(stored.id, status='qualified')['ok']
    with pytest.raises(ValidationError, match='structured'):
        DashboardApplication(boundary).change_status(stored.id, 'qualified')


def test_direct_save_requires_matching_evidence_and_reputation(boundary):
    assessment = WebsiteAssessmentReport.from_dict(report()).to_website_assessment()
    fields = {**candidate(), **{name + '_issue': getattr(assessment, name) for name in ('layout','mobile','cta','content','social_proof','platform')}, 'qualification_reason': assessment.reason}
    assert not server.save_lead(**fields)['ok']
    assert not server.save_lead(**{**fields, 'rating': 1.0, 'review_count': 1}, website_assessment=report())['ok']
    assert not server.save_lead(**{**fields, 'layout_issue': True}, website_assessment=report())['ok']
    assert server.save_lead(**fields, website_assessment=report())['ok']
    assert len(boundary.list()) == 1


@pytest.mark.parametrize('damage', ['domain', 'place_id', 'facts', 'features', 'count', 'boolean', 'unsupported', 'duplicate_feature'])
def test_adversarial_benchmark_reports(damage):
    raw = research()
    if damage == 'domain': raw['benchmarks'][1]['website_url'] = 'https://a.example.com/another'
    if damage == 'place_id': raw['benchmarks'][1]['external_place_id'] = raw['benchmarks'][0]['external_place_id']
    if damage in {'facts', 'features'}: raw['benchmarks'][0][damage] = []
    if damage == 'count': raw['common_features'][0]['observed_in'] = 1
    if damage == 'boolean': raw['common_features'][0]['observed_in'] = True
    if damage == 'unsupported': raw['common_features'][0]['feature'] = 'invented'
    if damage == 'duplicate_feature': raw['common_features'].append(raw['common_features'][0])
    with pytest.raises(ValidationError): FirstWebsiteMarketReport.from_dict(raw)


def test_features_derived_from_all_observations_deterministically():
    raw = research()
    raw['common_features'] = raw['common_features'][:1]
    raw['benchmarks'][0]['features'] += ['address', 'address']
    parsed = FirstWebsiteMarketReport.from_dict(raw)
    assert [(f.feature,f.observed_in,f.total) for f in parsed.common_features] == [('address',1,2),('services',2,2),('whatsapp_cta',2,2)]
    raw['benchmarks'].reverse()
    assert FirstWebsiteMarketReport.from_dict(raw).common_features == parsed.common_features


def test_selection_rejects_same_host_despite_distinct_place_ids(boundary):
    service = FirstWebsiteProspectingService(boundary, ProspectingConfig())
    pool = [first_candidate(name='Reference '+str(i), external_place_id='ref'+str(i), website_url='https://same.example/'+str(i)) for i in range(2)]
    result = service.select_benchmarks(first_candidate(), pool)
    assert len(result.selected) == 1 and result.rejected[0].reason == 'duplicate'


@pytest.mark.parametrize('damage', ['missing', 'target', 'reference'])
def test_research_receipt_binds_target_and_references(boundary, damage):
    service = FirstWebsiteProspectingService(boundary, ProspectingConfig())
    target = first_candidate()
    raw = selected_research(service, target, research())
    if damage == 'missing': raw.pop('selection_id')
    if damage == 'target': target['external_place_id'] = 'different-target'
    if damage == 'reference': raw['benchmarks'][0]['website_url'] = 'https://unselected.example'
    result = service.qualify_and_save(target, raw, 'regression')
    assert result.outcome == 'invalid' and not boundary.list()


def test_mcp_research_validation_and_persistence_use_receipt(boundary):
    service = FirstWebsiteProspectingService(boundary, ProspectingConfig())
    raw = selected_research(service, first_candidate(), research())
    assert server.validate_first_website_market_research(raw)['ok']
    assert not server.validate_first_website_market_research(research())['ok']
    result = server.qualify_and_save_first_website_candidate(first_candidate(), raw, 'regression')
    assert result['ok'] and result['data']['lead']['market_research']['selection_id'] == raw['selection_id']
    assert server.update_lead(result['data']['lead']['id'], phone='1712345678')['ok']


def test_generation_rejects_substituted_research(boundary, tmp_path):
    stored = persisted_first_website(boundary)
    other = generation_research()
    other['recommendations'] = ['Different target research']
    with pytest.raises(ValidationError, match='persisted lead research'):
        PersistedSiteGenerationWorkflow(boundary, SiteGenerationService(tmp_path / 'sites')).generate(stored.id, other)
    assert boundary.get(stored.id).status == 'qualified' and not (tmp_path / 'sites').exists()


def test_runtime_database_paths_and_explicit_override(tmp_path, monkeypatch):
    from business_prospector import dashboard
    monkeypatch.setenv('BUSINESS_PROSPECTOR_DATA_DIR', str(tmp_path / 'shared'))
    assert server._repository().database_path == dashboard._default_database()
    override = tmp_path / 'explicit.db'
    app = DashboardApplication(SQLiteLeadRepository(override))
    assert app.repository.database_path == override


def test_custom_qualification_policy_is_shared(boundary, tmp_path, monkeypatch):
    stored = qualified(boundary)
    boundary.update(stored.id, {'status': 'needs_review'})
    policy = json.loads(server._config_resource().read_text())
    # Use the existing configuration schema, then ensure both adapters load it.
    policy['minimum_rating'] = 5.0
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps(policy))
    monkeypatch.setenv('BUSINESS_PROSPECTOR_CONFIG', str(path))
    assert not server.update_lead(stored.id, status='qualified')['ok']
    with pytest.raises(ValidationError): DashboardApplication(boundary).change_status(stored.id, 'qualified')


def test_dashboard_cli_explicit_database_override(tmp_path, monkeypatch):
    import sys
    from business_prospector import dashboard
    database = tmp_path / 'explicit.db'
    monkeypatch.setattr(sys, 'argv', ['dashboard', '--database', str(database)])
    captured = []
    monkeypatch.setattr(dashboard, 'create_handler', lambda app, static: captured.append(app))
    monkeypatch.setattr(dashboard, 'preview_deployment_provider_from_environment', lambda: None)
    class FakeServer:
        def __init__(self, *args): pass
        def serve_forever(self): pass
        def server_close(self): pass
    monkeypatch.setattr(dashboard, 'ThreadingHTTPServer', FakeServer)
    assert dashboard.main() == 0
    assert captured[0].repository.database_path == database
    assert not dashboard._default_database().exists()


def test_compound_qualification_validates_proposed_values_atomically(boundary):
    stored = qualified(boundary)
    boundary.update(stored.id, {'status': 'needs_review', 'rating': 1.0})
    result = server.update_lead(stored.id, rating=4.9, status='qualified')
    assert result['ok'] and boundary.get(stored.id).rating == 4.9


@pytest.mark.parametrize('damage', ['issues', 'unknown', 'facts', 'inference_type', 'url_type'])
def test_bad_assessment_cannot_qualify(boundary, damage):
    raw = report(issues=1 if damage == 'issues' else 2, unknown=damage == 'unknown')
    if damage == 'facts': raw['criteria']['mobile']['facts'] = []
    if damage == 'inference_type': raw['criteria']['mobile']['inference'] = 42
    if damage == 'url_type': raw['website_url'] = True
    result = server.qualify_and_save_candidate(candidate(), raw, 'regression')
    assert not boundary.list()
    assert not result['ok'] or result['data']['lead'] is None


def test_legacy_repository_reports_remain_readable_without_receipt(boundary):
    stored = persisted_first_website(boundary)
    assert boundary.get(stored.id).market_research['selection_id'] is None
    assert DashboardApplication(boundary).get_lead(stored.id).id == stored.id


def test_benchmark_receipts_survive_repository_reopen_without_changing_leads(boundary):
    stored = qualified(boundary)
    before = stored.to_dict()
    service = FirstWebsiteProspectingService(boundary, ProspectingConfig())
    raw = selected_research(service, first_candidate(), research())
    reopened = SQLiteLeadRepository(boundary.database_path)
    assert reopened.get_benchmark_selection(raw['selection_id'])['target']['external_place_id'] == 'target-place'
    assert reopened.get(stored.id).to_dict() == before


def test_version_six_upgrade_adds_only_receipt_storage(boundary):
    import sqlite3
    stored = qualified(boundary)
    before = boundary.get(stored.id).to_dict()
    with sqlite3.connect(boundary.database_path) as connection:
        connection.execute('DROP TABLE benchmark_selections')
        connection.execute('PRAGMA user_version = 6')
    reopened = SQLiteLeadRepository(boundary.database_path)
    assert reopened.get(stored.id).to_dict() == before
    assert reopened.get_benchmark_selection('missing') is None
    with sqlite3.connect(boundary.database_path) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 7


def test_old_boolean_only_provider_cannot_write_qualified(boundary):
    from business_prospector.application.prospecting import ProspectingService
    from business_prospector.domain.models import WebsiteAssessment
    class Discovery:
        def search(self, query): return [BusinessCandidate(**candidate())]
    class OldAssessment:
        def assess(self, business): return WebsiteAssessment(layout=True, mobile=True)
    outcome = ProspectingService(Discovery(), OldAssessment(), boundary, ProspectingConfig()).prospect('dentista', 'Catanduva')
    assert outcome.rejected_website == 1 and not boundary.list()


@pytest.mark.parametrize('maximum', [True, 2.5, 0, -1])
def test_selection_count_requires_positive_integer(boundary, maximum):
    with pytest.raises(ValidationError):
        FirstWebsiteProspectingService(boundary, ProspectingConfig()).select_benchmarks(first_candidate(), [], maximum)


def test_derived_feature_names_round_trip_under_same_bounds():
    raw = research()
    raw['benchmarks'][0]['features'].append('x' * 101)
    with pytest.raises(ValidationError, match='100 characters'):
        FirstWebsiteMarketReport.from_dict(raw)
