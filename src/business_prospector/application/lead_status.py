from __future__ import annotations

from business_prospector.application.ports import LeadRepository
from business_prospector.domain.exceptions import LeadNotFoundError, ValidationError
from business_prospector.domain.models import PIPELINE_STATUSES, Lead


_LEGACY_STATUS = {"site_ready": "internal_website", "rejected": "discarded"}
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"qualified", "needs_review", "discarded"}),
    "needs_review": frozenset({"qualified", "discarded"}),
    "qualified": frozenset({"internal_website", "needs_review", "discarded"}),
    # Sales Preview is deliberately absent: only SalesPreviewLifecycleService approves it.
    "internal_website": frozenset({"needs_review", "discarded"}),
    "sales_preview": frozenset({"contacted", "needs_review", "discarded"}),
    "contacted": frozenset({"proposal", "needs_review", "discarded"}),
    "proposal": frozenset({"closed", "needs_review", "discarded"}),
    "closed": frozenset(),
    "discarded": frozenset({"needs_review"}),
}


def can_transition(current_status: str, target_status: str) -> bool:
    """Return whether a generic, human-directed pipeline move is allowed."""
    current = _LEGACY_STATUS.get(current_status, current_status)
    target = _LEGACY_STATUS.get(target_status, target_status)
    if current == target:
        return True
    return target in _ALLOWED_TRANSITIONS.get(current, frozenset())


class LeadStatusService:
    """The single application boundary for commercial pipeline movement."""

    def __init__(self, repository: LeadRepository) -> None:
        self._repository = repository

    @property
    def allowed_statuses(self) -> tuple[str, ...]:
        return PIPELINE_STATUSES

    def change(self, lead_id: int, status: str) -> Lead:
        if not isinstance(lead_id, int) or isinstance(lead_id, bool) or lead_id < 1:
            raise ValidationError("lead_id must be a positive integer")
        if status not in PIPELINE_STATUSES:
            raise ValidationError(f"invalid pipeline status: {status}")
        if status == "sales_preview":
            raise ValidationError("Sales Preview requires explicit approval")
        lead = self._repository.get(lead_id)
        if lead is None:
            raise LeadNotFoundError(f"lead not found: {lead_id}")
        if not can_transition(lead.status, status):
            raise ValidationError(
                f"pipeline transition is not allowed: {lead.status} -> {status}"
            )
        return self._repository.update(lead_id, {"status": status})
