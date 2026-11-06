"""Renderer-ready content, built without copying benchmark text."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from urllib.parse import quote
from typing import Any

from .site_generation import FirstWebsiteSiteBrief
from .site_strategy import SECTION_LABELS

SECTION_IDS = {"about": "sobre", "contact": "contato", "hero": "inicio"}


@dataclass(frozen=True, slots=True)
class ContentSection:
    kind: str
    title: str
    paragraphs: tuple[str, ...] = ()
    items: tuple[tuple[str, str], ...] = ()
    provenance: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return SECTION_IDS.get(self.kind, self.kind)


@dataclass(frozen=True, slots=True)
class ContactAction:
    label: str
    url: str
    external: bool = False


@dataclass(frozen=True, slots=True)
class WebsiteContentModel:
    name: str
    city: str
    lead_text: str
    sections: tuple[ContentSection, ...]
    primary_action: ContactAction
    secondary_actions: tuple[ContactAction, ...]
    disclosure: str = "Demonstração independente da Gapps.Tech. Não é o site oficial e não implica aprovação do negócio."

    @classmethod
    def from_brief(cls, brief: FirstWebsiteSiteBrief) -> "WebsiteContentModel":
        facts, strategy = brief.reviewed_content, brief.strategy
        cta = strategy.contact_strategy
        if cta in {"booking", "ordering"}:
            primary = ContactAction(strategy.primary_cta, facts.values(f"{cta}_url")[0], True)
        elif cta == "confirmed_whatsapp":
            digits = "".join(char for char in (brief.whatsapp or "") if char.isascii() and char.isdigit())
            primary = ContactAction(strategy.primary_cta, f"https://wa.me/{digits}", True)
        elif cta == "public_phone":
            primary = ContactAction("Ligar para contato público", f"tel:{quote(brief.phone or '', safe='+')}")
        elif cta == "public_location":
            primary = ContactAction(strategy.primary_cta, brief.maps_url or "#contato", True)
        else:
            primary = ContactAction(strategy.primary_cta, "#contato")
        secondary = []
        if brief.maps_url and primary.url != brief.maps_url:
            secondary.append(ContactAction("Ver no mapa", brief.maps_url, True))
        if brief.instagram:
            secondary.append(ContactAction("Instagram público", brief.instagram, True))
        about_title = (f"Atendimento odontológico em {brief.city}" if strategy.category_policy == "dentist"
                       else f"{brief.business_name}, em {brief.city}")
        about = facts.values("biography") or ("Consulte as informações disponíveis e os canais públicos de contato.",)
        sections = []
        for kind in strategy.sections:
            paragraphs: tuple[str, ...] = ()
            items: tuple[tuple[str, str], ...] = ()
            provenance: tuple[str, ...] = ()
            title = SECTION_LABELS[kind]
            if kind == "hero":
                title = brief.business_name
                provenance = ("lead:name", "lead:city")
            elif kind == "about":
                title, paragraphs = about_title, about
                provenance = facts.provenance("biography") or ("policy:generic_contact_guidance",)
            elif kind == "reputation":
                title = f"{brief.review_count} avaliações públicas"
                if brief.source == "synthetic_fixture":
                    title = f"{brief.review_count} avaliações ilustrativas"
                    paragraphs = (f"{brief.rating:.1f} de 5 — exemplo fictício", "Dados sintéticos para avaliação do layout; sem consulta ao Google.")
                elif brief.source == "google_places_new":
                    paragraphs = (f"{brief.rating:.1f} de 5 no Google", "Reputação pública consultada para facilitar sua escolha.")
                else:
                    paragraphs = (f"{brief.rating:.1f} de 5", "Reputação informada no cadastro do negócio.")
                provenance = ("lead:rating", "lead:review_count")
            elif kind in {"contact", "location"}:
                title = "Contato e localização" if kind == "contact" else "Como chegar"
                paragraphs = tuple(item for item in (brief.address, brief.city, brief.phone if kind == "contact" else None) if item)
                provenance = ("lead:address", "lead:city", "lead:phone", "lead:maps_url")
            elif kind == "faq":
                values = facts.values("faq")
                items = tuple((values[i], values[i + 1]) for i in range(0, len(values), 2))
                provenance = facts.provenance("faq")
            elif kind != "gallery":
                key = "opening_hours" if kind == "hours" else kind
                items = tuple((value, "") for value in facts.values(key))
                provenance = facts.provenance(key)
            else:
                provenance = ("assets:reviewed_local_inventory",)
            sections.append(ContentSection(kind, title, paragraphs, items, provenance))
        disclosure = "Demonstração independente da Gapps.Tech. Não é o site oficial e não implica aprovação do negócio."
        if brief.source == "synthetic_fixture":
            disclosure += " Negócio e dados inteiramente fictícios."
        return cls(brief.business_name, brief.city, f"Informações de {brief.business_name} e canais de contato em {brief.city}.",
                   tuple(sections), primary, tuple(secondary), disclosure)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
