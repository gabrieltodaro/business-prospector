"""Provider-independent deployment outcomes and recovery policy."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

FAILURE_STATES = frozenset({
    'upload_failure', 'partial_deployment', 'dns_failure', 'tls_failure',
    'http_failure', 'content_mismatch', 'timeout', 'unknown_remote_state',
})
DEPLOYMENT_STATES = frozenset({'approved', 'deploying', 'uploaded', 'verifying', 'published'}) | FAILURE_STATES


@dataclass(frozen=True, slots=True)
class DeploymentTarget:
    preview_slug: str
    fqdn: str
    document_root: str
    namespace: str = ''

    @property
    def key(self) -> str:
        return (self.namespace + ':' if self.namespace else '') + self.fqdn + '/' + self.document_root


def validate_transition(previous: str, current: str) -> None:
    from .exceptions import ValidationError
    allowed = {
        'approved': {'deploying', 'verifying'},
        'deploying': {'uploaded', 'verifying'} | FAILURE_STATES,
        'uploaded': {'verifying'},
        'verifying': {'verifying', 'published'} | FAILURE_STATES,
        'published': {'verifying'},
    }
    if current not in allowed.get(previous, {'deploying', 'verifying'} if previous in FAILURE_STATES else set()):
        raise ValidationError('invalid deployment state transition')


@dataclass(frozen=True, slots=True)
class VerificationResult:
    state: str
    checked_at: str
    files_verified: int = 0
    dns_status: str = 'unknown'
    tls_status: str = 'unknown'
    error_code: str | None = None
    corrective_action: str = ''

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CORRECTIVE_ACTIONS = {
    'upload_failure': 'Correct hosting permissions or quota, then retry. Existing destinations are never overwritten.',
    'partial_deployment': 'Incomplete remote files require operator reconciliation. Verify again after recovery; retries never overwrite files.',
    'dns_failure': 'Check preview DNS records and propagation, then verify again.',
    'tls_failure': 'Provision a trusted certificate covering the preview hostname, then verify again.',
    'http_failure': 'Check hosting responses, redirects and MIME types, then verify again.',
    'content_mismatch': 'Investigate stale caches or modified remote files. Do not replace the approved artifact automatically.',
    'timeout': 'Check connectivity and provider availability, then retry verification.',
    'unknown_remote_state': 'Reconcile remote domain and files before retrying. No automatic deletion or overwrite is allowed.',
}
