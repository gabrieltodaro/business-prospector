"""Validated creative intent, separate from authoritative business facts and approvals."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .exceptions import ValidationError
from .site_content import text

COMPOSITIONS = {'minimal_typography', 'editorial_split', 'image_led', 'asymmetric_photography', 'full_width_photography'}
PALETTES = {'sage', 'terracotta', 'slate', 'rose'}
IMAGE_CRITERIA = ('subject_relevance', 'composition', 'lighting', 'color_harmony', 'emotional_tone', 'visual_clutter', 'hero_suitability', 'mobile_cropping')
PAGE_CRITERIA = ('identity', 'hierarchy', 'composition', 'photography', 'content', 'conversion', 'mobile')
BENCHMARK_DIMENSIONS = ('visual_identity', 'typography', 'layout_composition', 'photography', 'content_hierarchy', 'mobile_experience', 'section_purpose', 'conversion_strategy')


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def choice(value: Any, allowed: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValidationError(f'invalid art direction {field}')
    return value


def strings(value: Any, field: str, maximum: int = 12) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValidationError(f'invalid {field}')
    return [text(item, field, 500) for item in value]


def focal(value: Any) -> list[float]:
    if not isinstance(value, list) or len(value) != 2 or any(type(v) not in (int, float) or not 0 <= v <= 1 for v in value):
        raise ValidationError('focal point must contain two normalized coordinates')
    return [float(v) for v in value]


@dataclass(frozen=True)
class ArtDirectionPlan:
    data: dict[str, Any]

    @classmethod
    def parse(cls, raw: dict[str, Any], *, evidence: dict[str, str], sections: set[str]) -> ArtDirectionPlan:
        fields = {'brand_impression', 'target_visitor', 'primary_action', 'positioning', 'headline', 'supporting_copy',
                  'typography', 'color_strategy', 'palette', 'hero_composition', 'photography_direction', 'sections',
                  'density', 'responsive_composition', 'image_placement', 'hero_asset_key', 'focal_point'}
        if not isinstance(raw, dict) or set(raw) != fields:
            raise ValidationError('art direction must match the supported plan schema')
        result = {}
        for key in ('brand_impression', 'target_visitor', 'primary_action', 'color_strategy', 'photography_direction'):
            result[key] = text(raw[key], key, 500)
        for key, limit in (('positioning', 400), ('headline', 140), ('supporting_copy', 300)):
            item = raw[key]
            if not isinstance(item, dict) or set(item) != {'text', 'evidence'}:
                raise ValidationError(f'{key} requires text and evidence references')
            refs = strings(item['evidence'], 'evidence')
            if not refs or any(ref not in evidence for ref in refs):
                raise ValidationError('creative copy references unsupported business evidence')
            result[key] = {'text': text(item['text'], key, limit), 'evidence': refs}
        for key, allowed in {
            'typography': {'editorial', 'modern', 'display'}, 'palette': PALETTES,
            'hero_composition': COMPOSITIONS, 'density': {'compact', 'balanced', 'airy'},
            'responsive_composition': {'text_first', 'image_first'},
            'image_placement': {'hero', 'detail', 'none'},
        }.items():
            result[key] = choice(raw[key], allowed, key)
        rows = raw['sections']
        if not isinstance(rows, list) or not 1 <= len(rows) <= 12:
            raise ValidationError('art direction requires 1-12 purposeful sections')
        result['sections'] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {'kind', 'purpose', 'emphasis'}:
                raise ValidationError('invalid art direction section')
            result['sections'].append({'kind': choice(row['kind'], sections, 'section'),
                'purpose': text(row['purpose'], 'section purpose', 300),
                'emphasis': choice(row['emphasis'], {'quiet', 'standard', 'feature'}, 'emphasis')})
        kinds = [row['kind'] for row in result['sections']]
        if len(set(kinds)) != len(kinds) or kinds[0] != 'hero':
            raise ValidationError('sections must be unique and start with hero')
        if 'contact' in sections and (not kinds or kinds[-1] != 'contact'):
            raise ValidationError('available conversion action must close the composition')
        key = raw['hero_asset_key']
        if key is not None:
            key = text(key, 'hero asset key', 80)
        result['hero_asset_key'] = key
        result['focal_point'] = focal(raw['focal_point'])
        return cls(result)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.data))


def parse_visual_assessment(raw: Any, kind: str) -> dict[str, Any]:
    criteria = IMAGE_CRITERIA if kind == 'photo' else PAGE_CRITERIA
    if not isinstance(raw, dict) or set(raw) != {'criteria', 'rejection_reasons', 'focal_point', 'revisions'}:
        raise ValidationError('visual assessment must match the supported schema')
    ratings = raw['criteria']
    if not isinstance(ratings, dict) or set(ratings) != set(criteria):
        raise ValidationError('visual assessment criteria are incomplete')
    parsed = {}
    for key, item in ratings.items():
        if not isinstance(item, dict) or set(item) != {'verdict', 'evidence'}:
            raise ValidationError('visual criterion requires a verdict and pixel-grounded evidence')
        parsed[key] = {'verdict': choice(item['verdict'], {'pass', 'fail', 'uncertain'}, 'visual verdict'),
                       'evidence': text(item['evidence'], 'visual evidence', 500)}
    reasons = strings(raw['rejection_reasons'], 'rejection reasons')
    revisions = raw['revisions']
    allowed = {'density', 'hero_composition', 'image_placement', 'responsive_composition', 'typography', 'focal_point',
               'sections', 'headline', 'supporting_copy', 'palette', 'primary_action'}
    if not isinstance(revisions, dict) or set(revisions) - allowed or (kind == 'photo' and revisions):
        raise ValidationError('unsupported visual revision')
    # A model never returns approval, credentials, arbitrary CSS or filesystem instructions.
    return {'criteria': parsed, 'rejection_reasons': reasons, 'focal_point': focal(raw['focal_point']),
            'revisions': revisions, 'accepted': not reasons and all(item['verdict'] == 'pass' for item in parsed.values())}


def business_evidence(lead: dict, content) -> dict[str, str]:
    evidence = {f'lead:{key}': str(lead[key]) for key in ('name', 'category', 'city', 'address', 'phone', 'rating', 'review_count') if lead.get(key) is not None}
    for fact in content.facts:
        if fact.key not in {'palette', 'typography'}:
            for index, value in enumerate(fact.values):
                evidence[f'fact:{fact.key}:{index}'] = value
    return evidence
