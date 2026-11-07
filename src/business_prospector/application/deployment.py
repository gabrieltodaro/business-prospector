from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Protocol
from contextlib import contextmanager
from uuid import uuid4

from business_prospector.application.artifacts import (
    artifact_checksum, public_artifact_files, artifact_snapshot, site_operation_lock, PublicArtifact,
)
from business_prospector.application.ports import LeadRepository
from business_prospector.application.site_generation import SiteDraftService
from business_prospector.domain.models import Lead
from business_prospector.domain.normalization import normalize_domain
from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.deployment import CORRECTIVE_ACTIONS, FAILURE_STATES, VerificationResult, DeploymentTarget


@dataclass(frozen=True, slots=True)
class DeploymentResult:
    deployment_status: str
    preview_slug: str
    preview_url: str
    files_uploaded: int
    domain_status: str
    ssl_status: str
    deployment_id: str
    artifact_checksum: str
    warnings: tuple[str, ...] = ()
    deployment_mode: str = "direct_first_publish"
    cleanup: str = "manual_required"
    uploaded_files: tuple[str, ...] = ()
    verification: dict[str, Any] | None = None
    corrective_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_status": self.deployment_status,
            "preview_slug": self.preview_slug,
            "preview_url": self.preview_url,
            "files_uploaded": self.files_uploaded,
            "domain_status": self.domain_status,
            "ssl_status": self.ssl_status,
            "deployment_id": self.deployment_id,
            "artifact_checksum": self.artifact_checksum,
            "warnings": list(self.warnings),
            "deployment_mode": self.deployment_mode,
            "cleanup": self.cleanup,
            "uploaded_files": list(self.uploaded_files),
            "verification": self.verification,
            "corrective_action": self.corrective_action,
        }


@dataclass(frozen=True, slots=True)
class DeploymentStatus:
    deployment_status: str
    preview_slug: str
    preview_url: str
    domain_configured: bool
    document_root_matches: bool
    expected_files_present: bool
    ssl_status: str
    warnings: tuple[str, ...] = ()
    public_files: tuple[str, ...] = ()
    staging_residual_present: bool | None = None
    document_root_present: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_status": self.deployment_status,
            "preview_slug": self.preview_slug,
            "preview_url": self.preview_url,
            "domain_configured": self.domain_configured,
            "document_root_matches": self.document_root_matches,
            "expected_files_present": self.expected_files_present,
            "ssl_status": self.ssl_status,
            "warnings": list(self.warnings),
            "public_files": list(self.public_files),
            "staging_residual_present": self.staging_residual_present,
            "document_root_present": self.document_root_present,
        }


@dataclass(frozen=True, slots=True)
class UnpublishResult:
    deployment_status: str
    preview_slug: str
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_status": self.deployment_status,
            "preview_slug": self.preview_slug,
            "warnings": list(self.warnings),
        }


class PreviewDeploymentProvider(Protocol):
    def target(self, preview_slug: str) -> DeploymentTarget: ...
    def safe_to_retry(self, preview_slug: str) -> bool: ...
    def publish(self, site_path: Path, preview_slug: str) -> DeploymentResult: ...
    def verify(self, artifact: PublicArtifact, preview_slug: str) -> VerificationResult: ...
    def unpublish(self, preview_slug: str) -> UnpublishResult: ...
    def status(self, preview_slug: str) -> DeploymentStatus: ...


@dataclass(frozen=True, slots=True)
class PersistedDeploymentStatus:
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.data


class SalesPreviewDeploymentService:
    def __init__(self, repository: LeadRepository, drafts: SiteDraftService,
                 provider: PreviewDeploymentProvider | None = None) -> None:
        self._repository, self._drafts, self._provider = repository, drafts, provider

    @contextmanager
    def _approved(self, lead_id: int, *, existing_only: bool = False) -> Iterator[tuple[Lead, Path, PublicArtifact, Path, dict[str, Any], DeploymentTarget]]:
        lead = self._repository.get(lead_id)
        if lead is None:
            raise ValidationError('persisted lead not found')
        if lead.status != 'sales_preview' and not existing_only:
            raise ValidationError('lead must be an approved Sales Preview before publication')
        draft = self._drafts.inspect(lead.slug or '')
        if not draft.exists or draft.site_path is None:
            raise ValidationError('valid approved site artifact is required')
        with artifact_snapshot(draft.site_path) as (artifact, snapshot):
            manifest = json.loads(artifact.manifest_bytes)
            preview = manifest.get('sales_preview')
            legacy = manifest.get('deployment')
            if legacy is not None and not isinstance(legacy, dict):
                raise ValidationError('invalid deployment metadata')
            existing = self._repository.get_deployment(lead_id)
            if existing and existing['artifact_checksum'] != artifact.checksum:
                raise ValidationError('deployment artifact changed; safe replacement is not supported')
            if (not isinstance(preview, dict) or preview.get('preview_status') not in
                    {'approved_not_published', 'published'}):
                raise ValidationError('Sales Preview approval metadata is required')
            if preview.get('approved_artifact') != artifact.identity():
                raise ValidationError('stale or missing artifact approval; review and approve this revision again')
            slug = preview.get('preview_slug')
            if not isinstance(slug, str) or not slug:
                raise ValidationError('approved preview slug is required')
            from .sales_preview import SalesPreviewLifecycleService
            readiness = SalesPreviewLifecycleService(self._repository, SiteDraftService(snapshot.parent)).readiness(
                lead, content_review_acknowledged=preview.get('content_review_acknowledged') is True)
            if not readiness.ready:
                raise ValidationError('Sales Preview is not ready: ' + '; '.join(readiness.blocking_reasons))
            if self._provider is None:
                raise ValidationError('cPanel deployment is not configured')
            target = self._provider.target(slug)
            # A current customer website can never be the preview destination.
            customer_host = normalize_domain(lead.website_url)
            preview_root = target.fqdn.partition('.')[2]
            if customer_host and (customer_host == target.fqdn or customer_host == preview_root
                                  or customer_host.endswith('.' + preview_root)
                                  or preview_root.endswith('.' + customer_host)):
                raise ValidationError('customer domain cannot be used as a preview destination')
            yield lead, draft.site_path, artifact, snapshot, manifest, target

    def readiness(self, lead_id: int) -> dict[str, Any]:
        try:
            with self._approved(lead_id) as (_, _, artifact, _, _, target):
                record = self._repository.get_deployment(lead_id)
                owner = self._repository.deployment_owner(target.key, 'https://' + target.fqdn)
                if owner is not None and owner != lead_id:
                    raise ValidationError('preview destination is already owned by another lead')
                if record and (record['preview_url'] != 'https://' + target.fqdn or
                               record['target_key'] != target.key):
                    raise ValidationError('deployment configuration changed; reconcile the reserved destination')
                return {'ready': True, 'blocking_reasons': [], 'preview_url': 'https://' + target.fqdn,
                        'artifact_checksum': artifact.checksum, 'deployment_state': record['state'] if record else 'approved',
                        'explicit_publication_authorization_required': True}
        except (ValidationError, OSError, ValueError) as exc:
            return {'ready': False, 'blocking_reasons': [str(exc)], 'explicit_publication_authorization_required': True}

    def publish(self, lead_id: int, *, explicitly_authorized: bool) -> DeploymentResult:
        if explicitly_authorized is not True:
            raise ValidationError('explicit publication authorization is required')
        return self._run(lead_id, publish=True)

    def verify(self, lead_id: int) -> DeploymentResult:
        """Read remote state and persist verification; never upload or change hosting."""
        return self._run(lead_id, publish=False)

    def _run(self, lead_id: int, *, publish: bool) -> DeploymentResult:
        lead = self._repository.get(lead_id)
        if lead is None:
            raise ValidationError('persisted lead not found')
        with site_operation_lock(self._drafts.sites_root, lead.slug or ''):
            with self._approved(lead_id, existing_only=not publish) as (_, site_path, artifact, snapshot, manifest, target):
                assert self._provider is not None
                existing = self._repository.get_deployment(lead_id)
                legacy = manifest.get('deployment')
                if not publish and existing is None and not (isinstance(legacy, dict) and legacy.get('deployment_status') == 'published'):
                    raise ValidationError('no existing deployment to verify')
                record = self._repository.claim_deployment(
                    lead_id, target.key, 'https://' + target.fqdn,
                    target.preview_slug, artifact.checksum)
                attempt_id = uuid4().hex
                result = self._result(record)
                # Cached publication is evidence from the last verification, not a new network check.
                if record['state'] == 'published' and publish:
                    self._mirror(site_path, manifest, result)
                    return replace(result, warnings=('unchanged artifact was already published; use verify for a fresh check',))
                should_upload = publish and record['state'] == 'approved' and not legacy
                if publish and record['state'] in FAILURE_STATES:
                    try:
                        should_upload = self._provider.safe_to_retry(target.preview_slug)
                    except Exception:
                        should_upload = False
                if should_upload:
                    self._record(lead_id, site_path, manifest, replace(result, deployment_status='deploying'), attempt_id)
                    try:
                        uploaded = self._provider.publish(snapshot, target.preview_slug)
                        if (uploaded.artifact_checksum != artifact.checksum or uploaded.preview_url != result.preview_url
                                or uploaded.preview_slug != result.preview_slug):
                            raise ValidationError('provider result does not match approved destination or artifact')
                        result = replace(uploaded, deployment_status='uploaded', deployment_id=result.deployment_id)
                    except Exception as exc:
                        code = getattr(exc, 'code', '')
                        state = {'partial_deployment': 'partial_deployment', 'upload_failed': 'upload_failure',
                                 'timeout': 'timeout'}.get(code, 'unknown_remote_state')
                        safe_details = getattr(exc, 'safe_details', None) or {}
                        reported = safe_details.get('uploaded_files', [])
                        approved_paths = {item.path for item in artifact.files}
                        confirmed = tuple(item for item in reported if isinstance(item, str) and item in approved_paths) if isinstance(reported, list) else ()
                        result = replace(result, deployment_status=state, corrective_action=CORRECTIVE_ACTIONS[state],
                                         uploaded_files=confirmed, files_uploaded=len(confirmed))
                        self._record(lead_id, site_path, manifest, result, attempt_id)
                        return result
                    self._record(lead_id, site_path, manifest, result, attempt_id)
                # Any interrupted or failed attempt is reconciled by reads only. No
                # repeat write can overwrite a remotely successful but unacknowledged upload.
                result = replace(result, deployment_status='verifying', corrective_action='')
                self._record(lead_id, site_path, manifest, result, attempt_id)
                try:
                    verification = self._provider.verify(artifact, target.preview_slug)
                    if verification.state not in FAILURE_STATES | {'published'}:
                        raise ValidationError('invalid verification outcome')
                except Exception:
                    verification = VerificationResult('unknown_remote_state', datetime.now(timezone.utc).isoformat(),
                                                      error_code='verification_unavailable',
                                                      corrective_action=CORRECTIVE_ACTIONS['unknown_remote_state'])
                result = replace(result, deployment_status=verification.state, verification=verification.to_dict(),
                                 ssl_status='active' if verification.tls_status == 'verified' else 'unknown',
                                 domain_status=verification.dns_status, corrective_action=verification.corrective_action,
                                 files_uploaded=len(artifact.files) if verification.state == 'published' else result.files_uploaded,
                                 uploaded_files=tuple(item.path for item in artifact.files) if verification.state == 'published' else result.uploaded_files,
                                 warnings=() if verification.state == 'published' else result.warnings)
                self._record(lead_id, site_path, manifest, result, attempt_id)
                return result

    def _record(self, lead_id: int, site_path: Path, manifest: dict[str, Any],
                result: DeploymentResult, attempt_id: str) -> None:
        # Durable state precedes remote operations and the best-effort compatibility
        # projection. A failed manifest write cannot erase the database receipt.
        self._repository.record_deployment(lead_id, result.deployment_status, result.to_dict(), attempt_id)
        self._mirror(site_path, manifest, result)

    def _mirror(self, site_path: Path, manifest: dict[str, Any], result: DeploymentResult) -> None:
        previous = manifest.get('deployment') or {}
        verified_at = (result.verification or {}).get('checked_at')
        manifest['deployment'] = {**result.to_dict(), 'last_checked_at': verified_at,
                                  'published_at': (previous.get('published_at') or verified_at)
                                  if result.deployment_status == 'published' else previous.get('published_at')}
        preview = manifest['sales_preview']
        if result.deployment_status == 'published':
            preview['preview_status'] = 'published'
            preview['preview_url'] = result.preview_url
        # Retain the historical publication guard even if a later check fails.
        self._write_manifest(site_path / 'site-manifest.json', manifest)

    @staticmethod
    def _result(record: dict[str, Any]) -> DeploymentResult:
        details = record['details']
        return DeploymentResult(
            record['state'], record['preview_slug'], record['preview_url'], details.get('files_uploaded', 0),
            details.get('domain_status', 'unknown'), details.get('ssl_status', 'unknown'),
            details.get('deployment_id', record['artifact_checksum'][:16]), record['artifact_checksum'],
            tuple(details.get('warnings', [])), details.get('deployment_mode', 'direct_first_publish'),
            details.get('cleanup', 'manual_required'), tuple(details.get('uploaded_files', [])),
            details.get('verification'), details.get('corrective_action', ''))

    def status(self, lead_id: int) -> PersistedDeploymentStatus:
        if self._repository.get(lead_id) is None:
            raise ValidationError('persisted lead not found')
        record = self._repository.get_deployment(lead_id)
        if record is None:
            return PersistedDeploymentStatus({'deployment_status': 'not_started', 'verification': None})
        return PersistedDeploymentStatus({**self._result(record).to_dict(), 'updated_at': record['updated_at'],
                                          'history': self._repository.deployment_history(lead_id)})

    @staticmethod
    def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
        temporary_path = None
        staging = path.parent.parent.parent / '.deployment-manifest-updates'
        if staging.is_symlink():
            raise ValidationError('manifest staging directory cannot be a symlink')
        staging.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=staging,
                                             prefix='.manifest-', delete=False) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(manifest, temporary, ensure_ascii=False, indent=2)
                temporary.write('\n')
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.replace(path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
