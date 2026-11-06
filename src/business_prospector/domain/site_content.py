"""Reviewed target facts. Benchmark observations are never business facts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, parse_qsl

from .exceptions import ValidationError

LIST_FIELDS = {"services", "opening_hours", "credentials", "team", "differentiators", "menu"}
TEXT_FIELDS = {"biography", "booking_url", "ordering_url", "palette", "typography"}
FACT_FIELDS = LIST_FIELDS | TEXT_FIELDS | {"faq"}
SOURCE_KINDS = {"business_provided", "business_website", "public_business_profile", "professional_register"}


def text(value: Any, field: str, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValidationError(f"{field} must be non-empty text up to {maximum} characters")
    return value.strip()


def public_url(value: Any, field: str) -> str:
    value = text(value, field, 2000)
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValidationError(f"{field} must be a public HTTP(S) URL without credentials")
    if any(key.casefold() in {"token", "key", "api_key", "signature", "x-amz-signature"}
           for key, _ in parse_qsl(parsed.query)):
        raise ValidationError(f"{field} cannot contain private query parameters")
    return value


@dataclass(frozen=True, slots=True)
class ContentSource:
    id: str
    kind: str
    reference: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "kind": self.kind, "reference": self.reference}


@dataclass(frozen=True, slots=True)
class VerifiedFact:
    key: str
    values: tuple[str, ...]
    source_ids: tuple[str, ...]
    # FAQ values alternate question/answer; all other values are scalar/list text.

    def to_dict(self) -> dict[str, Any]:
        if self.key == "faq":
            value: Any = [{"question": self.values[i], "answer": self.values[i + 1]}
                          for i in range(0, len(self.values), 2)]
        elif self.key in TEXT_FIELDS:
            value = self.values[0]
        else:
            value = list(self.values)
        return {"value": value, "source_ids": list(self.source_ids)}


@dataclass(frozen=True, slots=True)
class ReviewedBusinessContent:
    target_slug: str
    target_place_id: str | None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    sources: tuple[ContentSource, ...] = ()
    facts: tuple[VerifiedFact, ...] = ()

    @classmethod
    def from_inputs(cls, lead: dict[str, Any], payload: dict[str, Any] | None) -> "ReviewedBusinessContent":
        slug, place = lead["slug"], lead.get("external_place_id") or None
        if payload is None or payload == {}:
            return cls(slug, place)
        if not isinstance(payload, dict) or set(payload) - {"target", "reviewed_by", "reviewed_at", "sources", "facts"}:
            raise ValidationError("reviewed content contains unsupported fields")
        target = payload.get("target")
        if not isinstance(target, dict) or target.get("slug") != slug or (target.get("external_place_id") or None) != place:
            raise ValidationError("reviewed content belongs to a different business")
        raw_facts, raw_sources = payload.get("facts"), payload.get("sources")
        if raw_facts == {} and raw_sources == [] and not payload.get("reviewed_by"):
            return cls(slug, place)
        reviewer = text(payload.get("reviewed_by"), "reviewed_by", 100)
        reviewed_at = text(payload.get("reviewed_at"), "reviewed_at", 64)
        try:
            timestamp = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError
        except ValueError as exc:
            raise ValidationError("reviewed_at must be an ISO timestamp with timezone") from exc
        if not isinstance(raw_sources, list) or not 1 <= len(raw_sources) <= 20:
            raise ValidationError("reviewed content requires 1-20 sources")
        sources: list[ContentSource] = []
        for raw in raw_sources:
            if not isinstance(raw, dict) or set(raw) != {"id", "kind", "reference"}:
                raise ValidationError("invalid business evidence source")
            identifier = text(raw["id"], "source id", 80)
            if raw["kind"] not in SOURCE_KINDS:
                raise ValidationError("benchmark or generic guidance cannot substantiate business facts")
            reference = text(raw["reference"], "source reference", 2000)
            if raw["kind"] != "business_provided":
                reference = public_url(reference, "source reference")
            sources.append(ContentSource(identifier, raw["kind"], reference))
        ids = {source.id for source in sources}
        if len(ids) != len(sources):
            raise ValidationError("duplicate content source id")
        if not isinstance(raw_facts, dict) or set(raw_facts) - FACT_FIELDS:
            raise ValidationError("unsupported business fact")
        facts: list[VerifiedFact] = []
        for key, raw in sorted(raw_facts.items()):
            if not isinstance(raw, dict) or set(raw) != {"value", "source_ids"}:
                raise ValidationError("each business fact requires value and source_ids")
            references = raw["source_ids"]
            if (not isinstance(references, list) or not references or len(references) > 20
                    or not all(isinstance(item, str) and item in ids for item in references)):
                raise ValidationError("business fact references an unknown or missing source")
            value = raw["value"]
            if key == "faq":
                if not isinstance(value, list) or not 1 <= len(value) <= 8:
                    raise ValidationError("faq requires 1-8 verified question/answer pairs")
                values = []
                for item in value:
                    if not isinstance(item, dict) or set(item) != {"question", "answer"}:
                        raise ValidationError("invalid verified FAQ")
                    values.extend((text(item["question"], "question", 200), text(item["answer"], "answer", 800)))
            elif key in LIST_FIELDS:
                if not isinstance(value, list) or not 1 <= len(value) <= 12:
                    raise ValidationError(f"{key} requires 1-12 verified items")
                values = [text(item, key) for item in value]
            else:
                values = [text(value, key, 1500 if key == "biography" else 2000)]
                if key.endswith("_url"):
                    values = [public_url(value, key)]
                if key == "palette" and value not in {"sage", "terracotta", "slate"}:
                    raise ValidationError("approved palette must be sage, terracotta or slate")
                if key == "typography" and value not in {"editorial", "modern"}:
                    raise ValidationError("approved typography must be editorial or modern")
            facts.append(VerifiedFact(key, tuple(values), tuple(sorted(set(references)))))
        return cls(slug, place, reviewer, reviewed_at, tuple(sources), tuple(facts))

    def values(self, key: str) -> tuple[str, ...]:
        return next((fact.values for fact in self.facts if fact.key == key), ())

    def provenance(self, *keys: str) -> tuple[str, ...]:
        return tuple(sorted({source for fact in self.facts if fact.key in keys for source in fact.source_ids}))

    def to_dict(self) -> dict[str, Any]:
        return {"target": {"slug": self.target_slug, "external_place_id": self.target_place_id},
                "reviewed_by": self.reviewed_by, "reviewed_at": self.reviewed_at,
                "sources": [source.to_dict() for source in self.sources],
                "facts": {fact.key: fact.to_dict() for fact in self.facts}}
