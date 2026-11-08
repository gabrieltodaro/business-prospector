"""Provider-neutral stock search intent and reviewed license provenance."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
import re

from .exceptions import ValidationError
from .site_content import public_url, text
from .site_strategy import ALIASES

ILLUSTRATIVE_DISCLOSURE = "Imagem ilustrativa de banco de imagens. Não retrata este negócio, sua equipe ou seus clientes."


@dataclass(frozen=True, slots=True)
class StockSearchPlan:
    query: str
    orientation: str
    aspect_ratio: float
    relevance_terms: tuple[str, ...]
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def stock_search_plan(category: str, features: tuple[str, ...], verified_menu: tuple[str, ...] = ()) -> StockSearchPlan | None:
    category = ALIASES.get(category.casefold(), category.casefold())
    plans = {
        "dentist": ("dental instruments still life", ("dental", "dentist", "dentistry", "tooth", "teeth")),
        "restaurant": ("restaurant table food", ("food", "meal", "dish", "table", "restaurant")),
        "beauty_salon": ("hair salon styling tools", ("hair", "salon", "beauty", "styling")),
        "fitness": ("fitness gym equipment", ("fitness", "gym", "exercise", "weights", "workout")),
    }
    if category not in plans:
        return None
    query, terms = plans[category]
    # Cuisine is inferred only from reviewed target menu facts, never a listing name.
    menu = " ".join(verified_menu).casefold()
    for tokens, cuisine in ((('pizza',), 'pizza'), (('sushi', 'sashimi'), 'sushi'),
                            (('massa', 'pasta'), 'pasta'), (('vegetariano', 'vegetariana', 'vegan'), 'vegetarian')):
        if category == 'restaurant' and any(token in menu for token in tokens):
            query, terms = f"{cuisine} food table", (cuisine,)
            break
    portrait = category == "beauty_salon" or "gallery" in features
    return StockSearchPlan(query, "portrait" if portrait else "landscape", .8 if portrait else 1.5, terms,
                           "Category, reviewed menu and observed gallery emphasis; illustrative concepts only.")


@dataclass(frozen=True, slots=True)
class StockPhoto:
    provider: str
    photo_id: str
    source_page: str
    download_url: str
    photographer: str
    photographer_url: str
    license_url: str
    width: int
    height: int
    description: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r'[a-z0-9-]{1,40}', self.provider) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', self.photo_id):
            raise ValidationError('invalid stock provider identity')
        for name in ('source_page', 'download_url', 'photographer_url', 'license_url'):
            public_url(getattr(self, name), name)
        text(self.photographer, 'photographer', 200)
        text(self.description, 'stock description', 300)
        if any(type(v) is not int or v < 1 or v > 100000 for v in (self.width, self.height)):
            raise ValidationError('invalid stock dimensions')

    def matches(self, plan: StockSearchPlan) -> bool:
        if any(term in self.description.casefold() for term in ('non-dental', 'office meeting', 'business meeting', 'generic office')):
            return False
        words = set(re.findall(r'[a-z]+', self.description.casefold()))
        ratio = self.width / self.height
        orientation_matches = ((plan.orientation == 'portrait' and ratio < 1)
                               or (plan.orientation == 'landscape' and ratio > 1)
                               or (plan.orientation == 'square' and .9 <= ratio <= 1.1))
        return (orientation_matches and min(self.width, self.height) >= 800 and bool(words.intersection(plan.relevance_terms))
                and .65 <= ratio / plan.aspect_ratio <= 1.6)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StockProvenance:
    provider: str
    photo_id: str
    source_page: str
    photographer: str
    photographer_url: str
    license_url: str
    search_query: str
    reviewed_by: str
    reviewed_at: str
    illustrative: bool = True
    review_kind: str = "human_review"
    visual_assessment_id: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> StockProvenance:
        if not isinstance(value, dict):
            raise ValidationError('stock provenance must be an object')
        try:
            result = cls(**value)
            for name in ('provider', 'photo_id', 'photographer', 'search_query', 'reviewed_by', 'reviewed_at'):
                text(getattr(result, name), name, 200)
            for name in ('source_page', 'photographer_url', 'license_url'):
                public_url(getattr(result, name), name)
            if result.illustrative is not True or datetime.fromisoformat(result.reviewed_at.replace('Z', '+00:00')).tzinfo is None:
                raise ValueError('review timestamp and illustrative disclosure required')
            if result.review_kind not in {'human_review', 'agent_curation'}:
                raise ValueError('invalid stock review kind')
            if result.review_kind == 'agent_curation':
                from uuid import UUID
                if str(UUID(result.visual_assessment_id)) != result.visual_assessment_id:
                    raise ValueError('agent curation requires a visual assessment receipt')
            return result
        except (TypeError, ValueError) as exc:
            raise ValidationError('invalid reviewed stock provenance') from exc

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
