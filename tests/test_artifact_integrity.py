import hashlib
import json
from pathlib import Path

import pytest

from business_prospector.application.artifacts import capture_artifact, artifact_checksum
from business_prospector.application.sales_preview import SalesPreviewLifecycleService
from business_prospector.application.site_generation import SiteDraftService
from business_prospector.domain.exceptions import ValidationError
from business_prospector.infrastructure.cpanel import HostGatorPreviewDeploymentProvider, CPanelUapiClient
from test_cpanel_deployment import approved_service, config, FakeTransport, site, publish_transport


def manifest(path):
    return json.loads((path / 'site-manifest.json').read_text())


def write_manifest(path, value):
    (path / 'site-manifest.json').write_text(json.dumps(value))


@pytest.mark.parametrize('change', ['html','css','asset','extra_asset','extra_root','remove','manifest_approval','readiness','legacy'])
def test_invalid_or_stale_approval_never_invokes_provider(tmp_path, change):
    repository, stored, path, provider, service = approved_service(tmp_path, 'sales_preview')
    metadata = manifest(path)
    if change == 'html':
        with (path / 'index.html').open('a') as stream: stream.write('<!-- changed -->')
    if change == 'css':
        with (path / 'styles.css').open('a') as stream: stream.write('\nbody{color:red}')
    if change == 'asset':
        asset = metadata['assets'][0]
        target = path / asset['local_file']
        target.write_bytes(target.read_bytes() + b'\n')
        asset['checksum'] = hashlib.sha256(target.read_bytes()).hexdigest()
        write_manifest(path, metadata)  # Even updating the inventory cannot refresh approval.
    if change == 'extra_asset': (path / 'assets' / 'hidden.php').write_text('<?php echo 1;')
    if change == 'extra_root': (path / 'hidden.txt').write_text('private')
    if change == 'remove': (path / metadata['assets'][0]['local_file']).unlink()
    if change == 'manifest_approval':
        metadata['sales_preview']['content_review_acknowledged'] = False
        write_manifest(path, metadata)
    if change == 'readiness':
        metadata['opportunity_type'] = 'redesign'
        write_manifest(path, metadata)
    if change == 'legacy':
        metadata['sales_preview'].pop('approved_artifact')
        write_manifest(path, metadata)
    with pytest.raises(ValidationError): service.publish(stored.id, explicitly_authorized=True)
    assert provider.publish_calls == 0 and repository.get(stored.id).status == 'sales_preview'
    assert 'deployment' not in manifest(path)


def test_approval_contains_exact_inventory_hashes_and_unchanged_publishes(tmp_path):
    _, stored, path, provider, service = approved_service(tmp_path, 'sales_preview')
    identity = manifest(path)['sales_preview']['approved_artifact']
    artifact = capture_artifact(path)
    assert identity == artifact.identity()
    assert {item['path'] for item in identity['files']} == {'index.html','styles.css',*[a['local_file'] for a in manifest(path)['assets']]}
    for item in identity['files']:
        assert item['sha256'] == hashlib.sha256((path / item['path']).read_bytes()).hexdigest()
    assert service.publish(stored.id, explicitly_authorized=True).artifact_checksum == identity['checksum']
    assert service.publish(stored.id, explicitly_authorized=True).artifact_checksum == identity['checksum']
    assert provider.publish_calls == 1


def test_draft_changes_during_provider_call_do_not_change_uploaded_bytes(tmp_path, monkeypatch):
    _, stored, path, provider, service = approved_service(tmp_path, 'sales_preview')
    expected = (path / 'styles.css').read_bytes()
    publish = provider.publish
    def mutate_source(snapshot, slug):
        assert snapshot != path
        (path / 'styles.css').write_bytes(b'changed while publishing')
        assert (snapshot / 'styles.css').read_bytes() == expected
        return publish(snapshot, slug)
    monkeypatch.setattr(provider, 'publish', mutate_source)
    result = service.publish(stored.id, explicitly_authorized=True)
    assert result.artifact_checksum == manifest(path)['sales_preview']['approved_artifact']['checksum']
    with pytest.raises(ValidationError): service.publish(stored.id, explicitly_authorized=True)
    assert provider.publish_calls == 1


def test_explicit_reapproval_refreshes_unpublished_revision(tmp_path):
    repository, stored, path, provider, service = approved_service(tmp_path, 'sales_preview')
    before = manifest(path)['sales_preview']['approved_artifact']
    with (path / 'styles.css').open('a') as stream: stream.write('\n/* reviewed change */')
    lifecycle = SalesPreviewLifecycleService(repository, SiteDraftService(path.parent))
    lifecycle.approve(stored.id, content_review_acknowledged=True, asset_keys_approved_for_publish=[], approved_by='second reviewer')
    assert manifest(path)['sales_preview']['approved_artifact'] != before
    service.publish(stored.id, explicitly_authorized=True)
    with pytest.raises(ValidationError, match='published'):
        lifecycle.approve(stored.id, content_review_acknowledged=True, asset_keys_approved_for_publish=[], approved_by='reviewer')


@pytest.mark.parametrize('damage', ['unlisted','php','traversal','absolute','backslash','duplicate','symlink','directory_symlink','root_symlink','manifest_symlink','checksum','mime','svg_script','svg_external','svg_entity','oversize','too_many'])
def test_invalid_inventory_fails_before_any_remote_request(tmp_path, damage):
    path = site(tmp_path)
    metadata = manifest(path)
    asset = metadata['assets'][0]
    if damage == 'unlisted': (path / 'assets' / 'private.txt').write_text('private')
    if damage in {'php','traversal','absolute','backslash'}:
        asset['local_file'] = {'php':'assets/test.php','traversal':'assets/../README.md','absolute':'/tmp/test.svg','backslash':'assets\\test.svg'}[damage]
    if damage == 'duplicate': metadata['assets'].append(dict(asset))
    if damage == 'symlink':
        (path / 'assets' / 'hero.svg').unlink()
        (path / 'assets' / 'hero.svg').symlink_to(path / 'README.md')
    if damage == 'directory_symlink':
        (path / 'assets').rename(path / 'other')
        (path / 'assets').symlink_to(path / 'other', target_is_directory=True)
    if damage == 'checksum': asset['checksum'] = '0' * 64
    if damage == 'mime': asset['mime_type'] = 'text/html'
    if damage in {'svg_script','svg_external','svg_entity','oversize'}:
        content = {'svg_script': b'<svg><script>alert(1)</script></svg>', 'svg_external': b'<svg><path fill="url(https://example.test/a)"/></svg>', 'svg_entity': b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg>&x;</svg>', 'oversize': b'x' * (8 * 1024 * 1024 + 1)}[damage]
        (path / 'assets' / 'hero.svg').write_bytes(content)
        asset['checksum'] = hashlib.sha256(content).hexdigest()
    if damage == 'too_many':
        metadata['assets'] = [{**asset, 'key':str(i), 'local_file':f'assets/{i}.svg'} for i in range(99)]
    write_manifest(path, metadata)
    if damage == 'root_symlink':
        link = tmp_path / 'linked'
        link.symlink_to(path, target_is_directory=True)
        path = link
    if damage == 'manifest_symlink':
        source = path / 'site-manifest.json'
        source.rename(tmp_path / 'outside.json')
        source.symlink_to(tmp_path / 'outside.json')
    transport = FakeTransport()
    provider = HostGatorPreviewDeploymentProvider(config(), CPanelUapiClient(config(), transport))
    with pytest.raises(ValidationError): provider.publish(path, 'drlaura')
    assert not transport.requests


def test_provider_freezes_all_uploads_before_remote_calls(tmp_path, monkeypatch):
    path = site(tmp_path)
    expected = artifact_checksum(path)
    transport = publish_transport()
    original = transport.send
    def mutate_after_first_request(request):
        (path / 'styles.css').write_text('changed after network started')
        return original(request)
    monkeypatch.setattr(transport, 'send', mutate_after_first_request)
    result = HostGatorPreviewDeploymentProvider(config(), CPanelUapiClient(config(), transport)).publish(path, 'drlaura')
    assert result.artifact_checksum == expected
    bodies = [request.body for request in transport.requests if request.body]
    assert not any(b'changed after network started' in body for body in bodies)


def test_combined_public_size_limit_is_preserved(tmp_path):
    path = site(tmp_path)
    metadata = manifest(path)
    content = b'\x89PNG\r\n\x1a\n' + b'x' * (7 * 1024 * 1024)
    for i in range(4):
        relative = f'assets/image{i}.png'
        (path / relative).write_bytes(content)
        metadata['assets'].append({
            'key':f'image{i}', 'local_file':relative, 'mime_type':'image/png',
            'checksum':hashlib.sha256(content).hexdigest(),
        })
    write_manifest(path, metadata)
    transport = FakeTransport()
    provider = HostGatorPreviewDeploymentProvider(config(), CPanelUapiClient(config(), transport))
    with pytest.raises(ValidationError, match='upload size limit'): provider.publish(path, 'drlaura')
    assert not transport.requests
