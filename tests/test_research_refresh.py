"""Research replacement uses synthetic records, never operational data."""
import asyncio
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

from business_prospector.application.config import ProspectingConfig
from business_prospector.application.first_website import FirstWebsiteProspectingService
from business_prospector.application.research_refresh import ResearchRefreshService
from business_prospector.application.sales_preview import SalesPreviewLifecycleService
from business_prospector.application.site_generation import (
    PersistedSiteGenerationWorkflow, SiteDraftService, SiteGenerationService,
)
from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.first_website import FirstWebsiteMarketReport
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository, SCHEMA_VERSION
from business_prospector.mcp import server
from test_first_website import candidate, research, selected_research
from test_draft_revisions import snapshot as artifact_snapshot


@pytest.fixture
def setup(tmp_path):
    repository = SQLiteLeadRepository(tmp_path / 'data' / 'test.db')
    prospecting = FirstWebsiteProspectingService(repository, ProspectingConfig())
    initial = selected_research(prospecting, candidate(), research())
    outcome = prospecting.qualify_and_save(candidate(), initial, 'original-batch')
    assert outcome.outcome == 'saved_qualified_first_website'
    lead = outcome.lead
    replacement = selected_research(prospecting, candidate(), research())
    replacement['recommendations'] = ['Priorizar contato com conteúdo original']
    sites = tmp_path / 'data' / 'sites'
    service = ResearchRefreshService(repository, ProspectingConfig(), sites)
    return repository, lead, replacement, sites, service


def row(repository, lead_id):
    with repository._connect() as connection:
        return dict(connection.execute('SELECT * FROM leads WHERE id = ?', (lead_id,)).fetchone())


def set_legacy_research(repository, lead_id, raw):
    with repository._connect() as connection:
        connection.execute('UPDATE leads SET market_research_json = ? WHERE id = ?', (raw, lead_id))


def stale_approved_draft(setup):
    repository, lead, _, sites, _ = setup
    result, _ = PersistedSiteGenerationWorkflow(repository, SiteGenerationService(sites)).generate(
        lead.id, lead.market_research,
    )
    SalesPreviewLifecycleService(repository, SiteDraftService(sites)).approve(
        lead.id, content_review_acknowledged=True, asset_keys_approved_for_publish=[], approved_by='Test reviewer',
    )
    # Reproduce a historical qualified row with stale approval/artifact metadata.
    repository.update(lead.id, {'status': 'qualified'})
    return Path(result.site_path)


@pytest.mark.parametrize('legacy', ['missing_selection', 'invalid_frequency', 'invalid_json', 'missing_research'])
def test_refresh_legacy_preserves_all_unrelated_columns_and_needs_no_migration(setup, legacy):
    repository, lead, replacement, _, service = setup
    old = research()
    if legacy == 'invalid_frequency':
        old['common_features'][0]['total'] = 99
    raw = json.dumps(old)
    if legacy == 'invalid_json':
        raw = '{broken'
    if legacy == 'missing_research':
        raw = None
    set_legacy_research(repository, lead.id, raw)
    before = row(repository, lead.id)
    result = service.refresh(lead.id, replacement)
    after = row(repository, lead.id)
    changed = {'market_research_json', 'market_research_status', 'market_research_checked_at'}
    assert {k: v for k, v in before.items() if k not in changed} == {k: v for k, v in after.items() if k not in changed}
    assert result.lead.market_research == FirstWebsiteMarketReport.from_dict(replacement).to_dict()
    assert result.lead.status == 'qualified' and result.previous_artifact_path is None
    assert result.lead.market_research_checked_at
    assert SQLiteLeadRepository(repository.database_path).get(lead.id).to_dict() == result.lead.to_dict()
    with repository._connect() as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION == 8


@pytest.mark.parametrize('invalid', ['missing_selection', 'unknown_selection', 'wrong_target', 'changed_benchmark',
                                    'unsupported_frequency', 'incomplete', 'wrong_market', 'low_rating'])
def test_invalid_replacement_leaves_research_and_approval_untouched(setup, invalid):
    repository, lead, replacement, _, service = setup
    path = stale_approved_draft(setup)
    before, files = row(repository, lead.id), artifact_snapshot(path)
    if invalid == 'missing_selection':
        replacement.pop('selection_id')
    elif invalid == 'unknown_selection':
        replacement['selection_id'] = 'does-not-exist'
    elif invalid == 'wrong_target':
        replacement = selected_research(FirstWebsiteProspectingService(repository, ProspectingConfig()),
                                        candidate(name='Different business'), replacement)
    elif invalid == 'changed_benchmark':
        replacement['benchmarks'][0]['website_url'] = 'https://unselected.example'
    elif invalid == 'unsupported_frequency':
        replacement['common_features'][0]['observed_in'] = 1
    elif invalid == 'incomplete':
        replacement = research(status='insufficient')
    elif invalid == 'wrong_market':
        replacement['benchmark_market'] = 'Other market'
    else:
        replacement['benchmarks'][0]['rating'] = 1
    with pytest.raises(ValidationError):
        service.refresh(lead.id, replacement)
    assert row(repository, lead.id) == before
    assert artifact_snapshot(path) == files


def test_refresh_archives_stale_approval_then_normal_generation_requires_fresh_approval(setup):
    repository, lead, replacement, sites, service = setup
    path = stale_approved_draft(setup)
    before = artifact_snapshot(path)
    refreshed = service.refresh(lead.id, replacement)
    assert artifact_snapshot(refreshed.previous_artifact_path) == before
    assert not path.exists() and not SiteDraftService(sites).inspect(lead.slug).exists
    with pytest.raises(ValidationError):
        SalesPreviewLifecycleService(repository, SiteDraftService(sites)).approve(
            lead.id, content_review_acknowledged=True, asset_keys_approved_for_publish=[], approved_by='Test reviewer',
        )
    result, updated = PersistedSiteGenerationWorkflow(repository, SiteGenerationService(sites)).generate(
        lead.id, refreshed.lead.market_research,
    )
    assert result.ok and updated.status == 'internal_website'
    manifest = json.loads((path / 'site-manifest.json').read_text())
    assert 'sales_preview' not in manifest and 'deployment' not in manifest
    assert manifest['preview_kind'] == 'internal_draft'
    # Synthetic historical state: old research still cannot substitute for the refreshed report.
    repository.update(lead.id, {'status': 'qualified'})
    with pytest.raises(ValidationError, match='match the persisted'):
        PersistedSiteGenerationWorkflow(repository, SiteGenerationService(sites)).generate(lead.id, lead.market_research)


@pytest.mark.parametrize('failure', ['update', 'commit', 'archive'])
def test_failures_restore_database_and_entire_previous_artifact(setup, monkeypatch, failure):
    repository, lead, replacement, _, service = setup
    path = stale_approved_draft(setup)
    before, files = row(repository, lead.id), artifact_snapshot(path)
    if failure == 'update':
        with repository._connect() as connection:
            connection.execute("CREATE TRIGGER fail_refresh AFTER UPDATE OF market_research_json ON leads "
                               "BEGIN SELECT RAISE(ABORT, 'controlled update failure'); END")
    elif failure == 'commit':
        original = repository._connect
        @contextmanager
        def fail_commit():
            with original() as connection:
                yield connection
                if connection.in_transaction:
                    raise sqlite3.OperationalError('controlled commit failure')
        monkeypatch.setattr(repository, '_connect', fail_commit)
    else:
        original = Path.rename
        def fail_archive(source, target):
            if source == path:
                raise OSError('controlled archive failure')
            return original(source, target)
        monkeypatch.setattr(Path, 'rename', fail_archive)
    with pytest.raises((sqlite3.Error, OSError)):
        service.refresh(lead.id, replacement)
    assert row(repository, lead.id) == before
    assert artifact_snapshot(path) == files


@pytest.mark.parametrize('field,value', [('status', 'needs_review'), ('phone', '17988888888'),
                                         ('market_research_json', '{concurrent legacy edit')])
def test_concurrent_changes_are_not_overwritten_and_artifacts_are_restored(setup, monkeypatch, field, value):
    repository, lead, replacement, _, service = setup
    path = stale_approved_draft(setup)
    files = artifact_snapshot(path)
    original = repository.replace_market_research
    def concurrent_change(expected, report):
        with repository._connect() as connection:
            connection.execute(f'UPDATE leads SET {field} = ? WHERE id = ?', (value, lead.id))
        return original(expected, report)
    monkeypatch.setattr(repository, 'replace_market_research', concurrent_change)
    with pytest.raises(ValidationError, match='lead changed'):
        service.refresh(lead.id, replacement)
    assert row(repository, lead.id)[field] == value
    assert artifact_snapshot(path) == files


@pytest.mark.parametrize('status', ['new', 'needs_review', 'internal_website', 'site_ready', 'sales_preview',
                                    'contacted', 'proposal', 'closed', 'discarded'])
def test_refresh_cannot_bypass_lifecycle(setup, status):
    repository, lead, replacement, _, service = setup
    repository.update(lead.id, {'status': status})
    before = row(repository, lead.id)
    with pytest.raises(ValidationError, match='qualified first_website'):
        service.refresh(lead.id, replacement)
    assert row(repository, lead.id) == before


@pytest.mark.parametrize('guard', ['reservation', 'deployment_manifest', 'published_manifest', 'malformed_metadata',
                                   'wrong_identity', 'site_symlink', 'archive_symlink'])
def test_refresh_preserves_publication_identity_and_path_guards(setup, tmp_path, guard):
    repository, lead, replacement, sites, service = setup
    path = stale_approved_draft(setup)
    manifest_path = path / 'site-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if guard == 'reservation':
        repository.claim_deployment(lead.id, 'test-target', 'https://preview.example.test/lead/', 'lead', 'a' * 64)
    elif guard == 'deployment_manifest':
        manifest['deployment'] = {'deployment_status': 'failed'}
    elif guard == 'published_manifest':
        manifest['sales_preview']['preview_status'] = 'published'
    elif guard == 'malformed_metadata':
        manifest['deployment'] = []
    elif guard == 'wrong_identity':
        manifest['lead_identity']['external_place_id'] = 'other'
    manifest_path.write_text(json.dumps(manifest))
    if guard == 'site_symlink':
        moved = tmp_path / 'original'
        path.rename(moved)
        path.symlink_to(moved, target_is_directory=True)
    elif guard == 'archive_symlink':
        (sites.parent / 'site-revisions').symlink_to(tmp_path, target_is_directory=True)
    before, files = row(repository, lead.id), artifact_snapshot(path)
    with pytest.raises(ValidationError):
        service.refresh(lead.id, replacement)
    assert row(repository, lead.id) == before and artifact_snapshot(path) == files


def test_mcp_refresh_legacy_then_generate_and_discover_tool(setup, monkeypatch):
    repository, lead, replacement, sites, _ = setup
    monkeypatch.setattr(server, '_repository', lambda: repository)
    monkeypatch.setattr(server, '_sites_root', lambda: sites)
    set_legacy_research(repository, lead.id, '{unparseable legacy research')
    failed = server.refresh_first_website_research(lead.id, research())
    assert not failed['ok'] and 'selection' in failed['error']
    refreshed = server.refresh_first_website_research(lead.id, replacement)
    assert refreshed['ok'] and refreshed['action'] == 'refresh_first_website_research'
    updated = refreshed['data']['lead']
    generated = server.generate_first_website_draft(updated, updated['market_research'])
    assert generated['ok'] and generated['data']['lead_status'] == 'internal_website'
    assert 'refresh_first_website_research' in {tool.name for tool in asyncio.run(server.mcp.list_tools())}
    assert not server.refresh_first_website_research(9999, replacement)['ok']


@pytest.mark.parametrize('lead_id', [True, 0, -1, '1', None])
def test_invalid_identity_is_rejected(setup, lead_id):
    _, _, replacement, _, service = setup
    with pytest.raises(ValidationError, match='persisted lead id'):
        service.refresh(lead_id, replacement)


@pytest.mark.parametrize('field,value,message', [('opportunity_type', 'redesign', 'qualified first_website'),
                                                ('rating', 1.0, 'threshold'),
                                                ('website_url', 'https://owned.example', 'threshold'),
                                                ('slug', '../escape', 'unsafe')])
def test_existing_lead_context_is_validated_without_requalification(setup, field, value, message):
    repository, lead, replacement, _, service = setup
    with repository._connect() as connection:
        connection.execute(f'UPDATE leads SET {field} = ? WHERE id = ?', (value, lead.id))
    before = row(repository, lead.id)
    with pytest.raises(ValidationError, match=message):
        service.refresh(lead.id, replacement)
    assert row(repository, lead.id) == before


def test_reservation_created_before_transaction_blocks_refresh_and_restores_draft(setup, monkeypatch):
    repository, lead, replacement, _, service = setup
    path = stale_approved_draft(setup)
    before, files = row(repository, lead.id), artifact_snapshot(path)
    original = repository.replace_market_research
    def reserve_before_write(expected, report):
        repository.claim_deployment(lead.id, 'test-target', 'https://preview.example.test/lead/', 'lead', 'a' * 64)
        return original(expected, report)
    monkeypatch.setattr(repository, 'replace_market_research', reserve_before_write)
    with pytest.raises(ValidationError, match='reserved deployment'):
        service.refresh(lead.id, replacement)
    assert row(repository, lead.id) == before and artifact_snapshot(path) == files
