"""Simulated approval -> UAPI -> public DNS/TLS/HTTP -> durable publication."""
import asyncio
import json
import sqlite3
from dataclasses import replace
from pathlib import PurePosixPath

import pytest

from business_prospector.application.artifacts import capture_artifact
from business_prospector.application.deployment import SalesPreviewDeploymentService
from business_prospector.application.preview_verification import PublicPreviewVerifier, PublicResponse
from business_prospector.application.sales_preview import SalesPreviewLifecycleService
from business_prospector.application.site_generation import SiteDraftService
from business_prospector.domain.exceptions import ValidationError
from business_prospector.infrastructure.cpanel import CPanelError, HostGatorPreviewDeploymentProvider
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository
from test_cpanel_deployment import approved_service, config
from test_preview_verification import FakeDns


class FakeHosting:
    def __init__(self):
        self.base = 'public_html/sales-previews'
        self.dirs = {'public_html', self.base}
        self.files, self.domains, self.links = {}, [], set()
        self.writes = []
        self.fail_upload = None
        self.lose_ack = False
        self.uploads = 0

    def account_home_information(self):
        return {'home': '/home/prospector'}

    def file_information(self, path):
        assert path != '.', 'HostGator rejects dot as a Fileman path'
        if path.startswith('/') and path != '/':
            raise CPanelError('not_found', 'relative directory not found')
        if path == '/':
            return {'type': 'dir', 'fullpath': '/home/prospector', 'exists': 1}
        return {'type': 'link' if path in self.links else 'dir', 'fullpath': '/home/prospector/' + path,
                'exists': int(path in self.dirs or path in self.links)}

    def list_files(self, path):
        if path not in self.dirs:
            raise CPanelError('not_found', 'directory missing')
        entries = {str(PurePosixPath(item).name): 'dir' for item in self.dirs if str(PurePosixPath(item).parent) == path}
        entries.update({str(PurePosixPath(item).name): 'file' for item in self.files if str(PurePosixPath(item).parent) == path})
        entries.update({str(PurePosixPath(item).name): 'link' for item in self.links if str(PurePosixPath(item).parent) == path})
        return [{'file': name, 'type': kind} for name, kind in entries.items()]

    def domains_data(self):
        return self.domains

    def add_subdomain(self, slug, root, path):
        self.writes.append(('domain', slug))
        self.domains.append({'domain': slug + '.' + root, 'documentroot': path})
        self.dirs.add(path)

    def upload_files(self, path, files):
        self.uploads += 1
        if self.fail_upload == self.uploads:
            raise CPanelError('upload_failed', 'synthetic upload failure')
        self.dirs.add(path)
        for upload in files:
            name = path + '/' + upload.filename
            assert name not in self.files, 'overwrite is forbidden'
            self.files[name] = upload.content
            self.writes.append(('file', name))
        if self.lose_ack and files[0].filename == 'index.html':
            raise CPanelError('timeout', 'synthetic lost acknowledgement')
        return {'succeeded': len(files), 'failed': 0}

    def installed_ssl_hosts(self):
        return []  # Public TLS, not installed_hosts, is authoritative.

    def get(self, hostname, address, path, limit, timeout):
        slug = hostname.split('.')[0]
        relative = 'index.html' if path == '/' else path.lstrip('/')
        content = self.files.get(self.base + '/' + slug + '/' + relative)
        mime = 'text/html' if relative == 'index.html' else 'text/css' if relative == 'styles.css' else 'image/svg+xml'
        return PublicResponse(200 if content is not None else 404, mime, (content or b'')[:limit])


def setup(tmp_path):
    repository, lead, path, _, _ = approved_service(tmp_path, 'sales_preview')
    hosting = FakeHosting()
    dns = FakeDns()
    provider = HostGatorPreviewDeploymentProvider(config(), hosting, PublicPreviewVerifier(dns, hosting))
    service = SalesPreviewDeploymentService(repository, SiteDraftService(path.parent), provider)
    return repository, lead, path, hosting, dns, provider, service


def test_complete_simulated_lifecycle_persists_history_and_exact_bytes(tmp_path):
    repo, lead, path, host, dns, provider, service = setup(tmp_path)
    assert service.readiness(lead.id)['ready'] and not host.writes
    result = service.publish(lead.id, explicitly_authorized=True)
    assert result.deployment_status == 'published' and result.ssl_status == 'active'
    assert host.writes[-1][1].endswith('/index.html')
    assert {event['state'] for event in repo.deployment_history(lead.id)} == {'approved', 'deploying', 'uploaded', 'verifying', 'published'}
    assert repo.get(lead.id).status == 'sales_preview'
    assert len(host.files) == len(capture_artifact(path).files)
    writes = list(host.writes)
    assert service.publish(lead.id, explicitly_authorized=True).deployment_status == 'published'
    assert host.writes == writes
    reopened = SalesPreviewDeploymentService(SQLiteLeadRepository(repo.database_path), SiteDraftService(path.parent), provider)
    assert reopened.status(lead.id).to_dict()['verification']['state'] == 'published'
    assert reopened.verify(lead.id).deployment_status == 'published' and host.writes == writes


@pytest.mark.parametrize('failure', ['partial', 'lost_ack', 'dns'])
def test_recover_without_overwriting_files(tmp_path, failure):
    repo, lead, path, host, dns, _, service = setup(tmp_path)
    if failure == 'partial': host.fail_upload = 2
    if failure == 'lost_ack': host.lose_ack = True
    if failure == 'dns': dns.addresses = ()
    result = service.publish(lead.id, explicitly_authorized=True)
    assert result.deployment_status in {'partial_deployment', 'dns_failure'}
    writes = list(host.writes)
    if failure == 'partial':
        assert service.publish(lead.id, explicitly_authorized=True).deployment_status == 'partial_deployment'
        assert host.writes == writes
        # Simulate an explicitly authorized operator restoring the exact missing files.
        slug = result.preview_slug
        for item in capture_artifact(path).files:
            remote = host.base + '/' + slug + '/' + item.path
            host.files.setdefault(remote, item.content)
            host.dirs.add(str(PurePosixPath(remote).parent))
    dns.addresses = ('8.8.8.8',)
    assert service.verify(lead.id).deployment_status == 'published'
    assert host.writes == writes


def test_interruption_after_all_uploads_before_local_receipt_is_recovered(tmp_path, monkeypatch):
    repo, lead, path, host, _, provider, service = setup(tmp_path)
    original = provider.publish
    def crash(*args):
        original(*args)
        raise KeyboardInterrupt  # A process termination is not swallowed as a normal failure.
    monkeypatch.setattr(provider, 'publish', crash)
    with pytest.raises(KeyboardInterrupt): service.publish(lead.id, explicitly_authorized=True)
    assert repo.get_deployment(lead.id)['state'] == 'deploying'
    writes = list(host.writes)
    assert service.publish(lead.id, explicitly_authorized=True).deployment_status == 'published'
    assert host.writes == writes


def test_retry_after_operator_cleanup_and_unchanged_approval(tmp_path):
    _, lead, _, host, _, _, service = setup(tmp_path)
    host.fail_upload = 1
    assert service.publish(lead.id, explicitly_authorized=True).deployment_status == 'upload_failure'
    host.domains.clear()
    host.dirs = {'public_html', host.base}
    host.fail_upload = None
    assert service.publish(lead.id, explicitly_authorized=True).deployment_status == 'published'


@pytest.mark.parametrize('bad', ['foreign_domain', 'foreign_directory', 'symlink_base', 'symlink_root', 'file_instead_of_directory'])
def test_preexisting_or_escaping_destinations_never_receive_writes(tmp_path, bad):
    _, lead, path, host, _, provider, service = setup(tmp_path)
    slug = json.loads((path / 'site-manifest.json').read_text())['sales_preview']['preview_slug']
    root = host.base + '/' + slug
    if bad == 'foreign_domain': host.domains.append({'domain': slug + '.gapps.test', 'documentroot': root})
    if bad == 'foreign_directory': host.dirs.add(root)
    if bad == 'symlink_base': host.links.add(host.base)
    if bad == 'symlink_root': host.links.add(root)
    if bad == 'file_instead_of_directory': host.files[root] = b'foreign'
    assert service.publish(lead.id, explicitly_authorized=True).deployment_status == 'unknown_remote_state'
    assert not host.writes


@pytest.mark.parametrize('bad', ['extra', 'missing', 'symlink', 'stale'])
def test_reverification_rejects_drift_without_losing_publication_guard(tmp_path, bad):
    repo, lead, path, host, _, _, service = setup(tmp_path)
    published = service.publish(lead.id, explicitly_authorized=True)
    root = host.base + '/' + published.preview_slug
    if bad == 'extra': host.files[root + '/secret.txt'] = b'private'
    if bad == 'missing': del host.files[root + '/styles.css']
    if bad == 'symlink': host.links.add(root + '/assets')
    if bad == 'stale': host.files[root + '/index.html'] = b'old'
    writes = list(host.writes)
    assert service.verify(lead.id).deployment_status in {'partial_deployment', 'unknown_remote_state', 'content_mismatch'}
    assert host.writes == writes
    with pytest.raises(ValidationError, match='published'):
        SalesPreviewLifecycleService(repo, SiteDraftService(path.parent)).approve(
            lead.id, content_review_acknowledged=True, asset_keys_approved_for_publish=[], approved_by='reviewer')


def test_destination_reservation_is_unique_and_cannot_change(tmp_path):
    repo, lead, _, _, _, _, service = setup(tmp_path)
    service.publish(lead.id, explicitly_authorized=True)
    current = repo.get_deployment(lead.id)
    other = replace(lead, id=None, slug='other-business', external_place_id='other-place')
    other = repo.save(other)
    with pytest.raises(ValidationError, match='another lead'):
        repo.claim_deployment(other.id, current['target_key'], current['preview_url'], current['preview_slug'], current['artifact_checksum'])
    with pytest.raises(ValidationError, match='identity changed'):
        repo.claim_deployment(lead.id, 'other', current['preview_url'], current['preview_slug'], current['artifact_checksum'])


def test_v7_migration_preserves_six_synthetic_rows_and_research(tmp_path):
    repo, lead, _, _, _, _, _ = setup(tmp_path)
    for i in range(5):
        repo.save(replace(lead, id=None, slug=f'business-{i}', external_place_id=f'place-{i}'))
    before = [item.to_dict() for item in repo.list()]
    with sqlite3.connect(repo.database_path) as connection:
        connection.execute('DROP TABLE deployment_events')
        connection.execute('DROP TABLE preview_deployments')
        connection.execute('PRAGMA user_version = 7')
    migrated = SQLiteLeadRepository(repo.database_path)
    assert [item.to_dict() for item in migrated.list()] == before
    with sqlite3.connect(repo.database_path) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 8
        assert connection.execute('SELECT count(*) FROM preview_deployments').fetchone()[0] == 0
    assert SQLiteLeadRepository(repo.database_path).list() == migrated.list()


def test_registered_mcp_tools_and_authorization(tmp_path, monkeypatch):
    from business_prospector.mcp import server
    repo, lead, _, host, _, _, service = setup(tmp_path)
    monkeypatch.setattr(server, '_deployment_service', lambda: service)
    tools = asyncio.run(server.mcp.list_tools())
    names = {tool.name for tool in tools}
    assert {'sales_preview_deployment_readiness', 'verify_sales_preview_deployment',
            'sales_preview_deployment_status', 'publish_sales_preview'} <= names
    assert server.sales_preview_deployment_readiness(lead.id)['data']['ready']
    assert not server.publish_sales_preview(lead.id, False)['ok'] and not host.writes
    assert not server.verify_sales_preview_deployment(lead.id)['ok'] and not host.writes
    dispatched = asyncio.run(server.mcp.call_tool('publish_sales_preview', {'lead_id': lead.id, 'explicitly_authorized': True}))
    assert 'published' in str(dispatched)
    assert server.verify_sales_preview_deployment(lead.id)['data']['verification']['state'] == 'published'


def test_stale_approval_blocks_retries_and_verification(tmp_path):
    repo, lead, path, host, _, _, service = setup(tmp_path)
    service.publish(lead.id, explicitly_authorized=True)
    writes = list(host.writes)
    with (path / 'styles.css').open('a') as stream:
        stream.write('/* changed */')
    for action in [lambda: service.publish(lead.id, explicitly_authorized=True), lambda: service.verify(lead.id)]:
        with pytest.raises(ValidationError): action()
    assert host.writes == writes


def test_changed_host_account_cannot_reuse_reserved_destination(tmp_path):
    repo, lead, path, host, dns, provider, service = setup(tmp_path)
    service.publish(lead.id, explicitly_authorized=True)
    other = HostGatorPreviewDeploymentProvider(replace(config(), base_url='https://other.example.test:2083'), host,
                                              PublicPreviewVerifier(dns, host))
    changed = SalesPreviewDeploymentService(repo, SiteDraftService(path.parent), other)
    assert not changed.readiness(lead.id)['ready']
    with pytest.raises(ValidationError, match='identity changed'):
        changed.verify(lead.id)


def test_manifest_write_failure_retains_database_receipt_and_recovers(tmp_path, monkeypatch):
    repo, lead, path, host, _, _, service = setup(tmp_path)
    original = service._mirror
    def fail_once(path, manifest, result):
        if result.deployment_status == 'published':
            raise OSError('synthetic write failure')
        original(path, manifest, result)
    monkeypatch.setattr(service, '_mirror', fail_once)
    with pytest.raises(OSError): service.publish(lead.id, explicitly_authorized=True)
    assert repo.get_deployment(lead.id)['state'] == 'published'
    writes = list(host.writes)
    monkeypatch.setattr(service, '_mirror', original)
    assert service.publish(lead.id, explicitly_authorized=True).deployment_status == 'published'
    assert host.writes == writes
    assert json.loads((path / 'site-manifest.json').read_text())['deployment']['deployment_status'] == 'published'


def test_status_without_hosting_configuration_and_verify_after_contact(tmp_path):
    repo, lead, path, host, _, _, service = setup(tmp_path)
    service.publish(lead.id, explicitly_authorized=True)
    local = SalesPreviewDeploymentService(repo, SiteDraftService(path.parent))
    assert local.status(lead.id).to_dict()['deployment_status'] == 'published'
    repo.update(lead.id, {'status': 'contacted'})
    assert service.verify(lead.id).deployment_status == 'published'
    assert repo.get(lead.id).status == 'contacted'


def test_future_schema_is_not_downgraded(tmp_path):
    database = tmp_path / 'future.db'
    with sqlite3.connect(database) as connection:
        connection.execute('PRAGMA user_version = 999')
    with pytest.raises(ValidationError, match='newer'):
        SQLiteLeadRepository(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 999
        assert not connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()


def test_legacy_publication_requires_real_verification(tmp_path):
    repo, lead, path, host, _, provider, service = setup(tmp_path)
    manifest = json.loads((path / 'site-manifest.json').read_text())
    manifest['deployment'] = {'deployment_status': 'published', 'preview_url': 'https://drlaura.gapps.test'}
    (path / 'site-manifest.json').write_text(json.dumps(manifest))
    from business_prospector.application.website_projection import WebsiteDeploymentProjectionService
    assert WebsiteDeploymentProjectionService(SiteDraftService(path.parent), repo).project(lead).deployment_status == 'uploaded'
    result = service.publish(lead.id, explicitly_authorized=True)
    assert result.deployment_status != 'published' and not host.writes


@pytest.mark.parametrize('website,preview_root', [
    ('customer.example', 'customer.example'), ('www.customer.example', 'customer.example'),
    ('shop.customer.example', 'customer.example'), ('customer.example', 'previews.customer.example'),
])
def test_customer_domain_is_never_used_as_preview(tmp_path, website, preview_root):
    repo, lead, path, host, dns, _, _ = setup(tmp_path)
    repo.update(lead.id, {'website_url': 'https://' + website})
    provider = HostGatorPreviewDeploymentProvider(replace(config(), root_domain=preview_root), host,
                                                 PublicPreviewVerifier(dns, host))
    service = SalesPreviewDeploymentService(repo, SiteDraftService(path.parent), provider)
    with pytest.raises(ValidationError, match='customer domain'):
        service.publish(lead.id, explicitly_authorized=True)
    assert not host.writes


def test_partial_upload_persists_only_confirmed_public_paths(tmp_path):
    repo, lead, path, host, _, _, service = setup(tmp_path)
    host.fail_upload = 2
    result = service.publish(lead.id, explicitly_authorized=True)
    assert result.files_uploaded == 1 and result.uploaded_files[0].startswith('assets/')
    serialized = json.dumps(repo.deployment_history(lead.id))
    assert 'site-manifest.json' not in serialized and 'api_token' not in serialized


def test_failed_v8_migration_rolls_back_and_can_be_retried(tmp_path, monkeypatch):
    repo, lead, _, _, _, _, _ = setup(tmp_path)
    before = repo.get(lead.id).to_dict()
    with sqlite3.connect(repo.database_path) as connection:
        connection.execute('DROP TABLE deployment_events')
        connection.execute('DROP TABLE preview_deployments')
        connection.execute('PRAGMA user_version = 7')
    original = SQLiteLeadRepository._migrate_deployments
    def fail(connection):
        original(connection)
        raise sqlite3.OperationalError('synthetic interrupted migration')
    with monkeypatch.context() as patch:
        patch.setattr(SQLiteLeadRepository, '_migrate_deployments', staticmethod(fail))
        with pytest.raises(sqlite3.OperationalError): SQLiteLeadRepository(repo.database_path)
    with sqlite3.connect(repo.database_path) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 7
        assert not connection.execute("SELECT name FROM sqlite_master WHERE name='preview_deployments'").fetchall()
    assert SQLiteLeadRepository(repo.database_path).get(lead.id).to_dict() == before


def test_dashboard_verify_route_rejects_infrastructure_arguments(tmp_path):
    from test_dashboard import running_server, call
    from business_prospector.dashboard import DashboardApplication
    repo, lead, path, host, _, provider, service = setup(tmp_path)
    service.publish(lead.id, explicitly_authorized=True)
    application = DashboardApplication(repo, sites_root=path.parent, deployment_provider=provider)
    writes = list(host.writes)
    with running_server(application) as address:
        rejected, _, _ = call(address, 'POST', f'/api/leads/{lead.id}/verify-deployment', {'url': 'https://foreign.test'})
        verified, _, body = call(address, 'POST', f'/api/leads/{lead.id}/verify-deployment', {})
    assert rejected == 400 and verified == 200
    assert json.loads(body)['deployment']['deployment_status'] == 'published'
    assert host.writes == writes


def test_interrupted_verification_can_resume_without_upload(tmp_path, monkeypatch):
    repo, lead, _, host, _, provider, service = setup(tmp_path)
    original = provider.verify
    def crash(*args):
        raise KeyboardInterrupt
    monkeypatch.setattr(provider, 'verify', crash)
    with pytest.raises(KeyboardInterrupt): service.publish(lead.id, explicitly_authorized=True)
    assert repo.get_deployment(lead.id)['state'] == 'verifying'
    writes = list(host.writes)
    monkeypatch.setattr(provider, 'verify', original)
    assert service.verify(lead.id).deployment_status == 'published'
    assert host.writes == writes
