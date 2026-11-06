from __future__ import annotations

from dataclasses import replace
from typing import Any

from business_prospector.domain.exceptions import LeadNotFoundError, ValidationError
from business_prospector.domain.models import Lead, BusinessCandidate
from business_prospector.domain.first_website import FirstWebsiteMarketReport
from business_prospector.domain.scoring import calculate_score, calculate_first_website_score
from .config import ProspectingConfig
from .lead_status import LeadStatusService
from .ports import LeadRepository
from .qualification import validate_qualified_lead


class LeadUpdateService:
    """Validate the whole proposed edit before a single repository write."""

    def __init__(self, repository: LeadRepository, statuses: LeadStatusService, config: ProspectingConfig) -> None:
        self._repository, self._statuses, self._config = repository, statuses, config

    def update(self, lead_id: int, changes: dict[str, Any]) -> Lead:
        if isinstance(lead_id, bool) or not isinstance(lead_id, int) or lead_id < 1:
            raise ValidationError("lead_id must be a positive integer")
        current = self._repository.get(lead_id)
        if current is None:
            raise LeadNotFoundError("lead not found")
        proposed = replace(current, **changes)
        if "status" in changes:
            self._statuses.validate(current, changes["status"], proposed=proposed)
        if proposed.status == "qualified" and "status" not in changes:
            validate_qualified_lead(proposed, self._config, self._repository)
        if proposed.opportunity_type == "first_website" and proposed.market_research:
            candidate = BusinessCandidate(**{
                key: getattr(proposed, key) for key in BusinessCandidate.__dataclass_fields__
            })
            score = calculate_first_website_score(candidate, FirstWebsiteMarketReport.from_dict(
                proposed.market_research, allow_legacy=True,
            ), self._config.first_website.scoring).total
        else:
            score = calculate_score(proposed, self._config.scoring).total
        return self._repository.update(lead_id, {**changes, "score": score})
