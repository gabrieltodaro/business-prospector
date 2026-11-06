import json
from dataclasses import replace
from pathlib import Path

import pytest

from business_prospector.application.site_generation import SiteGenerationService, PersistedSiteGenerationWorkflow, SiteDraftService
from business_prospector.application.sales_preview import SalesPreviewLifecycleService
from business_prospector.application.artifacts import artifact_checksum
from business_prospector.application.deployment import SalesPreviewDeploymentService
from business_prospector.domain.exceptions import ValidationError
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository
from business_prospector.infrastructure.local_site_assets import LocalSiteAssetLibrary
from business_prospector.application.site_assets import SiteAssetCandidateValidator, SiteAssetIngestionService, DownloadedImage
from business_prospector.mcp import server
from test_site_generation import lead, research, persisted_first_website
from test_personalized_generation import content
from test_cpanel_deployment import FakeProvider
from test_site_assets import PNG, observation, redesign_lead


@pytest.fixture
def draft(tmp_path):
    repository = SQLiteLeadRepository(tmp_path / 'data' / 'test.db')
    stored = persisted_first_website(repository)
    generator = SiteGenerationService(tmp_path / 'data' / 'sites')
    workflow = PersistedSiteGenerationWorkflow(repository, generator)
    result, updated = workflow.generate(stored.id, stored.market_research)
    return repository, updated, generator, workflow, Path(result.site_path)


def snapshot(path):
    return {item.relative_to(path).as_posix(): item.read_bytes() for item in path.rglob('*') if item.is_file()}


def test_revision_preserves_identity_archives_previous_and_changes_integrity(draft):
    repository, lead, generator, workflow, path = draft
    before, checksum = snapshot(path), artifact_checksum(path)
    result, updated = workflow.revise(lead.id, reviewed_content=content(lead.to_dict(), services=['Consulta revisada']))
    assert updated.status == 'internal_website' and updated.id == lead.id and updated.slug == lead.slug
    assert snapshot(Path(result.previous_artifact_path)) == before
    assert result.artifact_identity['checksum'] != checksum and result.revision_number == 2
    assert artifact_checksum(path) == result.artifact_identity['checksum']
    assert 'Consulta revisada' in (path / 'index.html').read_text()
    assert not SiteDraftService(generator.sites_root).resolve_file(lead.slug, ('..','site-revisions'))


@pytest.mark.parametrize('failure', ['render','validation','install','database'])
def test_failed_revision_restores_entire_previous_artifact_and_status(draft, monkeypatch, failure):
    repository, lead, generator, workflow, path = draft
    before, row = snapshot(path), repository.get(lead.id).to_dict()
    if failure == 'render':
        monkeypatch.setattr(generator, '_write_site', lambda *args: (_ for _ in ()).throw(RuntimeError('render failed')))
    if failure == 'validation':
        original = generator._write_site
        def broken(*args):
            result = original(*args)
            (args[0] / 'index.html').write_text('<script>invalid</script>')
            return result
        monkeypatch.setattr(generator, '_write_site', broken)
    if failure == 'install':
        original = Path.replace
        def fail_install(source, target):
            if source.name.startswith('.' + lead.slug + '-'):
                raise OSError('controlled installation failure')
            return original(source, target)
        monkeypatch.setattr(Path, 'replace', fail_install)
    if failure == 'database':
        monkeypatch.setattr(repository, 'update', lambda *args: (_ for _ in ()).throw(RuntimeError('database failure')))
    with pytest.raises((RuntimeError, ValidationError, OSError)):
        workflow.revise(lead.id, reviewed_content=content(lead.to_dict(), services=['Changed']))
    assert snapshot(path) == before and repository.get(lead.id).to_dict() == row
    assert not list(generator.sites_root.glob('.' + lead.slug + '-*'))


def test_revising_approved_preview_invalidates_approval_and_returns_to_internal(draft):
    repository, lead, generator, workflow, path = draft
    drafts = SiteDraftService(generator.sites_root)
    lifecycle = SalesPreviewLifecycleService(repository, drafts)
    lifecycle.approve(lead.id, content_review_acknowledged=True, asset_keys_approved_for_publish=[], approved_by='test reviewer')
    approved = json.loads((path / 'site-manifest.json').read_text())['sales_preview']['approved_artifact']
    result, _ = workflow.revise(lead.id, reviewed_content=content(lead.to_dict(), biography='Biografia sintética revisada.'))
    manifest = json.loads((path / 'site-manifest.json').read_text())
    assert 'sales_preview' not in manifest and 'deployment' not in manifest
    assert manifest['preview_kind'] == 'internal_draft' and result.artifact_identity != approved
    assert 'sales_preview' in json.loads((Path(result.previous_artifact_path) / 'site-manifest.json').read_text())
    provider = FakeProvider()
    with pytest.raises(ValidationError):
        SalesPreviewDeploymentService(repository, drafts, provider).publish(lead.id, explicitly_authorized=True)
    assert provider.publish_calls == 0
    lifecycle.approve(lead.id, content_review_acknowledged=True, asset_keys_approved_for_publish=[], approved_by='new reviewer')
    assert json.loads((path / 'site-manifest.json').read_text())['sales_preview']['approved_artifact'] == result.artifact_identity
    assert 'noindex,nofollow,noarchive' in (path / 'index.html').read_text()


@pytest.mark.parametrize('metadata', ['deployment','sales_preview'])
def test_published_artifacts_protected_even_from_low_level_overwrite(draft, metadata):
    _, lead, generator, workflow, path = draft
    manifest_path = path / 'site-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest[metadata] = {'deployment_status' if metadata=='deployment' else 'preview_status':'published'}
    manifest_path.write_text(json.dumps(manifest))
    before = snapshot(path)
    with pytest.raises(ValidationError, match='published'):
        workflow.revise(lead.id)
    with pytest.raises(ValidationError, match='published'):
        generator.generate({**lead.to_dict(), 'status':'qualified'}, lead.market_research, overwrite=True)
    assert snapshot(path) == before


def test_revisions_reuse_reviewed_facts_when_omitted(draft):
    _, lead, _, workflow, path = draft
    result, _ = workflow.revise(lead.id, reviewed_content=content(lead.to_dict(), services=['Serviço verificado']))
    unchanged, _ = workflow.revise(lead.id)
    assert unchanged.artifact_identity == result.artifact_identity and unchanged.revision_number == 3
    empty, _ = workflow.revise(lead.id, reviewed_content={})
    assert empty.artifact_identity != unchanged.artifact_identity
    assert 'Serviço verificado' not in (path / 'index.html').read_text()


def test_revision_rejects_different_business_and_redesign(draft):
    _, stored, generator, workflow, path = draft
    before = snapshot(path)
    with pytest.raises(ValidationError, match='different business'):
        workflow.revise(stored.id, reviewed_content=content(lead(slug='someone-else')))
    with pytest.raises(ValidationError, match='identity'):
        generator.generate({**stored.to_dict(), 'external_place_id':'other'}, stored.market_research, overwrite=True)
    with pytest.raises(ValidationError, match='first_website'):
        generator.generate({**stored.to_dict(), 'opportunity_type':'redesign'}, stored.market_research, overwrite=True)
    assert snapshot(path) == before


def test_mcp_generation_and_revision_share_authoritative_state(draft, monkeypatch):
    repository, stored, generator, _, path = draft
    monkeypatch.setattr(server, '_repository', lambda: repository)
    monkeypatch.setattr(server, '_sites_root', lambda: generator.sites_root)
    result = server.revise_first_website_draft(stored.id, reviewed_content=content(stored.to_dict(), services=['Via MCP']))
    assert result['ok'] and result['data']['revision_number'] == 2
    assert result['data']['lead_status'] == 'internal_website'
    assert not server.generate_first_website_draft({'id':stored.id,'status':'qualified'}, stored.market_research)['ok']
    assert 'Via MCP' in (path / 'index.html').read_text()


def local_asset(tmp_path):
    asset = SiteAssetCandidateValidator().validate(redesign_lead(), [observation()]).accepted[0]
    return SiteAssetIngestionService(lambda _: DownloadedImage(PNG, 'image/png')).ingest(asset, tmp_path / 'assets')


def test_reviewed_asset_library_provenance_and_approval_are_preserved(draft, tmp_path):
    repository, stored, generator, _, _ = draft
    library = LocalSiteAssetLibrary(tmp_path / 'reviewed-assets')
    root = library.root / stored.slug
    asset = local_asset(root)
    (root / 'asset-manifest.json').write_text(json.dumps({'lead_identity':{'slug':stored.slug,'external_place_id':stored.external_place_id}, 'assets':[asset.to_dict()]}))
    result, _ = PersistedSiteGenerationWorkflow(repository, generator, library).revise(stored.id, asset_keys=['hero'])
    path = Path(result.site_path)
    manifest = json.loads((path / 'site-manifest.json').read_text())
    assert manifest['assets'][0] == asset.to_dict()
    assert (path / 'assets' / 'hero.png').read_bytes() == PNG
    readiness = SalesPreviewLifecycleService(repository, SiteDraftService(generator.sites_root)).readiness(repository.get(stored.id), content_review_acknowledged=True)
    assert not readiness.ready and readiness.assets_not_approved == ('hero',)


@pytest.mark.parametrize('damage', ['checksum','size','file_symlink','directory_symlink','unsafe_type','traversal','rights','identity','social'])
def test_generation_revalidates_local_assets_before_touching_existing_draft(draft, tmp_path, damage):
    _, stored, generator, _, path = draft
    staging = tmp_path / 'staging'
    asset = local_asset(staging)
    if damage == 'checksum': asset = replace(asset, checksum='0'*64)
    if damage == 'size': asset = replace(asset, byte_size=1)
    if damage == 'file_symlink':
        (staging / asset.local_file).unlink()
        outside = tmp_path / 'outside.png'
        outside.write_bytes(PNG)
        (staging / asset.local_file).symlink_to(outside)
    if damage == 'directory_symlink':
        (staging / 'assets').rename(staging / 'other')
        (staging / 'assets').symlink_to(staging / 'other')
    if damage == 'unsafe_type': asset = replace(asset, local_file='assets/hero.php', mime_type='application/x-httpd-php')
    if damage == 'traversal': asset = replace(asset, local_file='assets/../outside.png')
    if damage == 'rights': asset = replace(asset, rights_status='unknown')
    if damage == 'identity': asset = replace(asset, business_identity_match=False)
    if damage == 'social': asset = replace(asset, source_type='business_social_reference')
    before = snapshot(path)
    with pytest.raises(ValidationError):
        generator.generate(stored.to_dict(), stored.market_research, overwrite=True, assets=(asset,), asset_source_root=staging)
    assert snapshot(path) == before


def test_revision_symlink_and_malformed_manifest_fail_closed(draft):
    _, stored, _, workflow, path = draft
    manifest = path / 'site-manifest.json'
    manifest.write_text('{broken')
    before = snapshot(path)
    with pytest.raises(ValidationError): workflow.revise(stored.id)
    assert snapshot(path) == before


def test_lock_serializes_site_mutations(tmp_path):
    import threading
    from business_prospector.application.artifacts import site_operation_lock
    attempted, entered = threading.Event(), threading.Event()
    def second_operation():
        attempted.set()
        with site_operation_lock(tmp_path / 'sites', 'same-business'):
            entered.set()
    with site_operation_lock(tmp_path / 'sites', 'same-business'):
        thread = threading.Thread(target=second_operation)
        thread.start()
        assert attempted.wait(2)
        assert not entered.wait(.05)
    thread.join(2)
    assert entered.is_set() and not thread.is_alive()


def test_local_library_refuses_cross_business_and_unapproved_asset_keys(draft, tmp_path):
    _, stored, _, _, _ = draft
    library = LocalSiteAssetLibrary(tmp_path / 'library')
    root = library.root / stored.slug
    asset = local_asset(root)
    metadata = {'lead_identity':{'slug':stored.slug,'external_place_id':'different-business'},'assets':[asset.to_dict()]}
    (root / 'asset-manifest.json').write_text(json.dumps(metadata))
    with pytest.raises(ValidationError, match='different business'): library.load(stored, ['hero'])
    metadata['lead_identity']['external_place_id'] = stored.external_place_id
    metadata['assets'][0]['approval_status'] = 'candidate'
    (root / 'asset-manifest.json').write_text(json.dumps(metadata))
    with pytest.raises(ValidationError, match='not approved'): library.load(stored, ['hero'])
    with pytest.raises(ValidationError, match='unknown'): library.load(stored, ['missing'])


def test_mcp_initial_generation_accepts_reviewed_content_and_exposes_strategy(tmp_path, monkeypatch):
    repository = SQLiteLeadRepository(tmp_path / 'database.db')
    stored = persisted_first_website(repository)
    monkeypatch.setattr(server, '_repository', lambda: repository)
    monkeypatch.setattr(server, '_sites_root', lambda: tmp_path / 'sites')
    result = server.generate_first_website_draft({'id':stored.id,'name':'Untrusted override'}, stored.market_research,
        reviewed_content=content(stored.to_dict(), services=['Serviço via MCP']))
    assert result['ok'] and result['data']['strategy']['category_policy'] == 'dentist'
    assert 'Untrusted override' not in (Path(result['data']['site_path']) / 'index.html').read_text()
    assert repository.get(stored.id).status == 'internal_website'


def test_dashboard_reads_revision_and_renders_local_preview_without_new_routes(draft):
    from business_prospector.dashboard import DashboardApplication
    repository, lead, generator, workflow, _ = draft
    workflow.revise(lead.id, reviewed_content=content(lead.to_dict(), services=['Serviço revisado']))
    app = DashboardApplication(repository, sites_root=generator.sites_root)
    payload = app.lead_payload(repository.get(lead.id))
    assert payload['site_draft']['manifest']['revision']['number'] == 2
    assert payload['site_draft']['manifest']['preview_kind'] == 'internal_draft'
    assert payload['site_draft']['manifest']['strategy']['category_policy'] == 'dentist'
