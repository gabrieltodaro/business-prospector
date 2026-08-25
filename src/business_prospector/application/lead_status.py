from __future__ import annotations

from business_prospector.application.ports import LeadRepository
from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.models import PIPELINE_STATUSES, Lead


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
        return self._repository.update(lead_id, {"status": status})
