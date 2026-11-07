"""Pure, deterministic decisions from observed patterns and reviewed target facts."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .first_website import FirstWebsiteMarketReport
from .site_content import ReviewedBusinessContent

# Features are a bounded vocabulary, not instructions or competitor prose.
FEATURE_SECTIONS = {
    "services": "services", "treatments": "services", "service_list": "services",
    "menu": "menu", "menu_information": "menu", "opening_hours": "hours", "hours": "hours",
    "about": "about", "biography": "about", "team": "team", "credentials": "credentials",
    "professional_credentials": "credentials", "differentiators": "differentiators",
    "faq": "faq", "patient_information": "faq", "location": "location", "address": "location",
    "map": "location", "gallery": "gallery", "photos": "gallery",
    "reviews": "reputation", "reputation": "reputation", "social_proof": "reputation",
    "contact_cta": "contact", "whatsapp_cta": "contact", "booking": "contact",
    "appointments": "contact", "reservations": "contact", "ordering": "contact",
}
SECTION_LABELS = {"hero": "Início", "about": "Sobre", "services": "Serviços", "menu": "Cardápio",
                  "hours": "Horários", "team": "Equipe", "credentials": "Qualificações",
                  "differentiators": "Detalhes", "faq": "Perguntas", "location": "Localização",
                  "gallery": "Imagens", "reputation": "Reputação", "contact": "Contato"}


@dataclass(frozen=True, slots=True)
class CategoryPolicy:
    name: str
    sections: tuple[str, ...]
    essential: tuple[str, ...]
    palette: str
    guidance: str


POLICIES = {
    "dentist": CategoryPolicy("dentist", ("services", "credentials", "team", "about", "faq", "hours", "location", "reputation", "gallery"),
                              ("services", "credentials", "about", "location", "reputation"), "sage",
                              "Orientar o visitante com informações verificadas de atendimento e contato."),
    "restaurant": CategoryPolicy("restaurant", ("menu", "hours", "location", "about", "differentiators", "gallery", "reputation", "faq"),
                                 ("menu", "hours", "location", "about", "reputation"), "terracotta",
                                 "Facilitar a consulta ao cardápio, aos horários e aos canais de contato disponíveis."),
    "beauty_salon": CategoryPolicy("beauty_salon", ("services", "gallery", "about", "differentiators", "hours", "location", "reputation", "faq"),
                                  ("services", "about", "location", "reputation"), "rose",
                                  "Facilitar a escolha de serviços verificados e o contato com o salão."),
    "fitness": CategoryPolicy("fitness", ("services", "about", "hours", "location", "gallery", "reputation", "faq"),
                             ("services", "location", "reputation"), "slate",
                             "Apresentar modalidades verificadas e canais de contato."),
    "generic": CategoryPolicy("generic", ("services", "about", "hours", "location", "team", "credentials", "differentiators", "faq", "reputation", "gallery"),
                              ("services", "about", "location", "reputation"), "slate",
                              "Apresentar somente informações verificadas e canais públicos de contato."),
}
ALIASES = {"dentista": "dentist", "dental_clinic": "dentist", "restaurante": "restaurant", "cafe": "restaurant", "café": "restaurant", "salão de beleza": "beauty_salon", "salao de beleza": "beauty_salon", "beauty salon": "beauty_salon", "hair_salon": "beauty_salon", "academia": "fitness", "gym": "fitness", "fitness_studio": "fitness"}


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    subject: str
    choice: str
    rationale: str
    features: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"subject": self.subject, "choice": self.choice, "rationale": self.rationale,
                "features": list(self.features), "evidence": list(self.evidence)}


@dataclass(frozen=True, slots=True)
class WebsiteStrategy:
    primary_goal: str
    primary_cta: str
    sections: tuple[str, ...]
    trust_strategy: str
    contact_strategy: str
    mobile_priorities: tuple[str, ...]
    content_assumptions: tuple[str, ...]
    category_policy: str
    palette: str
    typography: str
    hero_composition: str
    navigation: tuple[str, ...]
    decisions: tuple[StrategyDecision, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("sections", "mobile_priorities", "content_assumptions", "navigation"):
            result[key] = list(result[key])
        result["decisions"] = [decision.to_dict() for decision in self.decisions]
        return result


def derive_strategy(
    lead: dict[str, Any], report: FirstWebsiteMarketReport,
    content: ReviewedBusinessContent, image_count: int = 0, hero_aspect_ratio: float | None = None,
) -> WebsiteStrategy:
    # Reparse even typed reports so a manually constructed object cannot invent frequencies.
    report = FirstWebsiteMarketReport.from_dict(report.to_dict())
    category = str(lead["category"]).casefold()
    policy = POLICIES.get(ALIASES.get(category, category), POLICIES["generic"])
    observed: dict[str, tuple[str, ...]] = {
        feature: tuple(f"research.benchmarks[{index}].features:{feature}"
                       for index, benchmark in enumerate(report.benchmarks) if feature in benchmark.features)
        for feature in sorted({feature for item in report.benchmarks for feature in item.features})
        if feature in FEATURE_SECTIONS
    }
    decisions: list[StrategyDecision] = []
    available = {
        "services": bool(content.values("services")), "menu": bool(content.values("menu")),
        "hours": bool(content.values("opening_hours")), "about": bool(content.values("biography")),
        "team": bool(content.values("team")), "credentials": bool(content.values("credentials")),
        "differentiators": bool(content.values("differentiators")), "faq": bool(content.values("faq")),
        "location": bool(lead.get("address") or lead.get("maps_url")),
        "reputation": lead["review_count"] > 0, "gallery": image_count > 1,
    }
    fact_keys = {"hours": "opening_hours", "about": "biography"}
    priorities = set(report.design_priorities)
    scores: dict[str, int] = {}
    for section in policy.sections:
        features = tuple(feature for feature in observed if FEATURE_SECTIONS[feature] == section)
        evidence = tuple(item for feature in features for item in observed[feature])
        requested = bool(features) or section in policy.essential or section == "gallery" and image_count > 1
        if not available[section]:
            if requested:
                decisions.append(StrategyDecision("section", f"omit:{section}", "Required target facts or approved assets are absent; benchmark data cannot fill this gap.", features, evidence))
            continue
        if not requested:
            decisions.append(StrategyDecision("section", f"omit:{section}", f"Optional information is not prioritized by observed patterns or {policy.name} policy."))
            continue
        key = fact_keys.get(section, section)
        target_evidence = tuple(f"business.sources:{item}" for item in content.provenance(key))
        if not target_evidence:
            target_evidence = (f"lead:{section}" if section != "gallery" else "assets:reviewed_local_inventory",)
        scores[section] = sum(len(observed[feature]) for feature in features) + 10 * sum(feature in priorities for feature in features)
        decisions.append(StrategyDecision("section", section,
            f"Supported patterns determine emphasis; {policy.name} policy supplies the tie-break order. Only target facts are rendered.",
            features, evidence + target_evidence))
    ordered = tuple(sorted(scores, key=lambda key: (-scores[key], policy.sections.index(key))))
    if content.values("ordering_url") and "ordering" in observed and policy.name == "restaurant":
        contact, label = "ordering", "Consultar pedidos"
    elif content.values("booking_url") and any(feature in observed for feature in ("booking", "appointments", "reservations")):
        contact, label = "booking", "Consultar reservas" if policy.name == "restaurant" else "Consultar agendamento"
    elif lead.get("whatsapp_confirmed") is True and lead.get("whatsapp"):
        contact, label = "confirmed_whatsapp", "Conversar pelo WhatsApp"
    elif lead.get("phone"):
        contact, label = "public_phone", "Entrar em contato"
    elif lead.get("maps_url"):
        contact, label = "public_location", "Ver localização"
    else:
        contact, label = "on_page", "Ver informações"
    closing = ("contact",) if contact != "on_page" or lead.get("instagram") else ()
    sections = ("hero", *ordered, *closing)
    contact_features = tuple(feature for feature in observed if FEATURE_SECTIONS[feature] == "contact")
    decisions.append(StrategyDecision("cta", contact,
        "Use an observed booking/ordering pattern only with its reviewed URL; otherwise choose a confirmed available contact channel.",
        contact_features, tuple(item for feature in contact_features for item in observed[feature]) +
        tuple(f"business.sources:{item}" for item in content.provenance("booking_url", "ordering_url")) + (f"lead:{contact}",)))
    palette = next(iter(content.values("palette")), policy.palette)
    typography = next(iter(content.values("typography")), "modern" if policy.name == "fitness" else "display" if policy.name == "restaurant" else "editorial")
    if not image_count:
        composition = "minimal_typography"
    elif "gallery" in priorities or "photos" in priorities:
        composition = "image_led"
    elif policy.name == "restaurant" and "menu" in scores and (hero_aspect_ratio is None or hero_aspect_ratio >= 1.2):
        composition = "full_width_photography"
    elif policy.name == "beauty_salon" or "differentiators" in priorities:
        composition = "asymmetric_photography"
    else:
        composition = "editorial_split"
    decisions.extend((
        StrategyDecision("palette", palette, "Reviewed palette selection." if content.values("palette") else f"Original {policy.name} demonstration palette; not inferred official branding.", evidence=content.provenance("palette")),
        StrategyDecision("typography", typography, "Reviewed typography selection." if content.values("typography") else "Local system serif/sans pair; no external font requests.", evidence=content.provenance("typography")),
        StrategyDecision("hero", composition, f"Composition follows available imagery ({image_count}), category ({policy.name}) and observed priorities ({",".join(report.design_priorities)}); original layout, never a benchmark design copy."),
        StrategyDecision("navigation", ",".join(ordered), "Navigation follows rendered content hierarchy, with all destinations reachable on mobile."),
        StrategyDecision("disclosure", "independent_demo_noindex", "Every generated page identifies the independent demonstration and requests no indexing."),
    ))
    return WebsiteStrategy(policy.guidance, label, sections, "Somente reputação pública e fatos do negócio",
                           contact, ("Navegação acessível", "Contato visível", "Leitura sem rolagem horizontal"),
                           ("Orientação de categoria não comprova serviços ou credenciais do negócio.",),
                           policy.name, palette, typography, composition, (*ordered, *closing), tuple(decisions))
