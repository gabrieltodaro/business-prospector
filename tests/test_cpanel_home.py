"""HostGator home discovery regression: offline UAPI requests and path boundaries."""
from urllib.parse import parse_qs, urlsplit

import pytest

from business_prospector.infrastructure.cpanel import (
    CPanelError, CPanelUapiClient, HostGatorPreviewDeploymentProvider,
)
from test_cpanel_deployment import config, response, flattened_response, publish_transport, site


class ScriptedTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        # Reproduce HostGator's rejection, even if a test forgets to assert the URL.
        path = parse_qs(urlsplit(request.url).query).get('path', [''])[0]
        if path == '.':
            return response(None, status=0, errors=['invalid Fileman path'])
        if path.startswith('/') and path != '/':
            return response(None, status=0, errors=['relative directory not found'])
        assert self.responses, 'unexpected UAPI call'
        return self.responses.pop(0)


def provider_for(transport):
    return HostGatorPreviewDeploymentProvider(config(), CPanelUapiClient(config(), transport))


def directory(path, **changes):
    return {'exists': 1, 'type': 'dir', 'fullpath': path, **changes}


@pytest.mark.parametrize('home', ['/home/prospector', '/home2/prospector', '/srv/accounts/prospector'])
@pytest.mark.parametrize('encode', [response, flattened_response])
def test_home_uses_scoped_uapi_lookup_and_account_root_fileman_path(home, encode):
    transport = ScriptedTransport(encode({'home': home}), encode(directory(home)))
    provider = provider_for(transport)
    assert provider._account_home() == home
    assert provider._account_home() == home  # Cache only a validated result.
    assert len(transport.requests) == 2
    first, second = transport.requests
    assert first.method == second.method == 'GET'
    assert urlsplit(first.url).path == '/execute/Variables/get_user_information'
    assert parse_qs(urlsplit(first.url).query) == {'name': ['home']}
    assert urlsplit(second.url).path == '/execute/Fileman/get_file_information'
    assert parse_qs(urlsplit(second.url).query) == {'path': ['/'], 'show_hidden': ['1']}


@pytest.mark.parametrize('data', [
    None, [], 'home', {}, {'home': None}, {'home': 1}, {'home': {}},
    {'home': ''}, {'home': '.'}, {'home': 'home/prospector'},
    {'home': '/'}, {'home': '/home/other'}, {'home': '/home/prospector-extra'},
    {'home': '/home/../prospector'}, {'home': '/home/./prospector'},
    {'home': '/home//prospector'}, {'home': '//home/prospector'},
    {'home': '/home/prospector/'}, {'home': '/home\\other/prospector'},
    {'home': '/home\x00/prospector'}, {'home': '/home\n/prospector'},
    {'home': '/home\x7f/prospector'},
])
def test_malformed_or_unsafe_home_fails_before_filesystem_requests(data):
    transport = ScriptedTransport(response(data))
    with pytest.raises(CPanelError, match='cannot establish account home directory') as caught:
        provider_for(transport)._account_home()
    assert caught.value.code == 'unsafe_path'
    assert len(transport.requests) == 1


@pytest.mark.parametrize('info', [
    None, [], {}, directory('/home/prospector', exists=0),
    directory('/home/prospector', exists=[]), directory('/home/prospector', exists={}),
    directory('/home/prospector', type='link'), directory('/home/prospector', type='file'),
    directory('/home/other'), directory('/outside/home/prospector'),
    directory('/home/prospector/'), directory('/home/prospector/../prospector'),
])
def test_home_must_exist_and_be_a_regular_directory_with_exact_path(info):
    transport = ScriptedTransport(response({'home': '/home/prospector'}), response(info))
    provider = provider_for(transport)
    with pytest.raises(CPanelError) as caught:
        provider._account_home()
    assert caught.value.code == 'unsafe_path' and provider._home is None
    assert len(transport.requests) == 2


@pytest.mark.parametrize('bad_component', ['public_html', 'public_html/sales-previews'])
@pytest.mark.parametrize('damage', ['link', 'escape', 'prefix_collision'])
def test_discovered_home_does_not_weaken_preview_ancestor_checks(bad_component, damage):
    home = '/home2/prospector'
    responses = [response({'home': home}), response(directory(home))]
    for component in ['public_html', 'public_html/sales-previews']:
        info = directory(home + '/' + component)
        if component == bad_component:
            if damage == 'link': info['type'] = 'link'
            if damage == 'escape': info['fullpath'] = '/home/other/' + component
            if damage == 'prefix_collision': info['fullpath'] = home + '-other/' + component
            responses.append(response(info))
            break
        responses.append(response(info))
    transport = ScriptedTransport(*responses)
    with pytest.raises(CPanelError) as caught:
        provider_for(transport)._assert_safe_path('public_html/sales-previews/drlaura')
    assert caught.value.code == 'unsafe_path'
    assert all('/get_' in item.url for item in transport.requests)


@pytest.mark.parametrize('actual,matches', [
    ('public_html/sales-previews/drlaura', True),
    ('/home2/prospector/public_html/sales-previews/drlaura', True),
    ('/home/prospector/public_html/sales-previews/drlaura', False),
    ('/other/home2/prospector/public_html/sales-previews/drlaura', False),
    ('/home2/prospector-other/public_html/sales-previews/drlaura', False),
    ('/home2/prospector/public_html/sales-previews/../drlaura', False),
])
def test_document_root_requires_exact_discovered_home(actual, matches):
    transport = ScriptedTransport(response({'home': '/home2/prospector'}), response(directory('/home2/prospector')))
    provider = provider_for(transport)
    assert provider._root_matches(actual, 'public_html/sales-previews/drlaura') is matches


def test_home_discovery_failure_has_no_fallback_or_mutation(tmp_path):
    transport = ScriptedTransport(response(None, status=0, errors=['feature disabled']))
    with pytest.raises(CPanelError):
        provider_for(transport).publish(site(tmp_path), 'drlaura')
    assert len(transport.requests) == 1
    assert '/Variables/get_user_information?' in transport.requests[0].url


def test_publish_succeeds_when_hostgator_requires_account_root(tmp_path):
    transport = publish_transport()
    result = provider_for(transport).publish(site(tmp_path), 'drlaura')
    assert result.deployment_status == 'uploaded'
    calls = transport.safety_requests + transport.requests
    home_calls = [item for item in calls if '/Variables/get_user_information?' in item.url]
    assert len(home_calls) == 1
    assert all(parse_qs(urlsplit(item.url).query).get('path') != ['.'] for item in calls)
    fileman_paths = [parse_qs(urlsplit(item.url).query)['path'][0]
                     for item in calls if '/Fileman/get_file_information?' in item.url]
    assert fileman_paths[0] == '/'
    assert all(path == '/' or not path.startswith('/') for path in fileman_paths)
    assert result.files_uploaded == 3


def test_absolute_home_is_rejected_but_account_root_resolves_to_same_home():
    home = '/home2/prospector'
    transport = ScriptedTransport(response({'home': home}), response(directory(home)))
    client = CPanelUapiClient(config(), transport)
    with pytest.raises(CPanelError) as caught:
        client.file_information(home)
    assert caught.value.code == 'not_found'
    provider = HostGatorPreviewDeploymentProvider(config(), client)
    assert provider._account_home() == home
    assert parse_qs(urlsplit(transport.requests[-1].url).query)['path'] == ['/']
