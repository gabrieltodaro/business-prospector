from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.site_generation import FirstWebsiteSiteBrief, SITE_STRATEGY_VERSION

GENERATOR_VERSION = "1.0.0"
REQUIRED_FILES = ("index.html", "styles.css", "site-manifest.json", "README.md")
GENERATED_FILES = ("index.html", "styles.css", "assets/", "site-manifest.json", "README.md")


def controlled_sites_root(data_dir: Path) -> Path:
    """Derive the non-user-selectable generated-sites root from plugin data."""
    return data_dir.expanduser().resolve() / "sites"


class CategorySitePolicy(Protocol):
    def introduction(self, brief: FirstWebsiteSiteBrief) -> str: ...
    def services_heading(self) -> str: ...
    def services_placeholder(self) -> str: ...


class GenericSitePolicy:
    def introduction(self, brief: FirstWebsiteSiteBrief) -> str:
        return f"Uma presença digital inicial para facilitar o contato com {brief.business_name}."

    def services_heading(self) -> str:
        return "Serviços"

    def services_placeholder(self) -> str:
        return "As informações sobre serviços serão incluídas após confirmação com o negócio."


class DentistSitePolicy(GenericSitePolicy):
    def introduction(self, brief: FirstWebsiteSiteBrief) -> str:
        return f"Um espaço digital para conhecer e entrar em contato com {brief.business_name}."

    def services_heading(self) -> str:
        return "Atendimentos"

    def services_placeholder(self) -> str:
        return "Os tratamentos e áreas de atendimento serão apresentados após validação profissional."


POLICIES: dict[str, CategorySitePolicy] = {
    "dentist": DentistSitePolicy(), "dentista": DentistSitePolicy(), "dental_clinic": DentistSitePolicy(),
}


@dataclass(frozen=True, slots=True)
class SiteGenerationResult:
    ok: bool
    lead_slug: str
    site_path: str | None
    files: tuple[str, ...]
    warnings: tuple[str, ...]
    missing_information: tuple[str, ...]
    generation_status: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "lead_slug": self.lead_slug, "site_path": self.site_path,
            "files": list(self.files), "warnings": list(self.warnings),
            "missing_information": list(self.missing_information),
            "generation_status": self.generation_status, "error": self.error,
        }


class _SiteHTMLValidator(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: set[str] = set()
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.add(tag)
        values = dict(attrs)
        for key in ("href", "src"):
            value = values.get(key)
            if value and value.strip().lower().startswith("javascript:"):
                self.errors.append("unsafe javascript URL")
        href = values.get("href")
        if href and urlsplit(href).scheme and urlsplit(href).scheme not in {"http", "https", "tel"}:
            self.errors.append("unsupported external URL scheme")
        if values.get("target") == "_blank":
            rel = set((values.get("rel") or "").split())
            if not {"noopener", "noreferrer"} <= rel:
                self.errors.append("target=_blank requires noopener noreferrer")


def validate_generated_site(site_dir: Path, competitor_domains: tuple[str, ...] = ()) -> None:
    for name in REQUIRED_FILES:
        if not (site_dir / name).is_file():
            raise ValidationError(f"generated site is missing {name}")
    html = (site_dir / "index.html").read_text(encoding="utf-8")
    if '<html lang="pt-BR">' not in html:
        raise ValidationError("generated HTML must use pt-BR")
    parser = _SiteHTMLValidator()
    parser.feed(html)
    required = {"header", "main", "footer", "h1"}
    if not required <= parser.tags:
        raise ValidationError("generated HTML is missing semantic structure")
    if parser.errors:
        raise ValidationError(parser.errors[0])
    lowered = html.lower()
    if any(domain and domain.lower() in lowered for domain in competitor_domains):
        raise ValidationError("competitor domain leaked into generated output")
    if re.search(r"(?:api[_-]?key|secret|token)\s*[:=]", lowered):
        raise ValidationError("possible secret material in generated output")


class SiteGenerationService:
    def __init__(self, sites_root: Path) -> None:
        self._sites_root = sites_root.expanduser().resolve()

    def generate(
        self, lead: dict[str, Any], research: dict[str, Any], *, overwrite: bool = False,
    ) -> SiteGenerationResult:
        brief = FirstWebsiteSiteBrief.from_inputs(lead, research)
        destination = (self._sites_root / brief.lead_slug).resolve()
        if destination.parent != self._sites_root:
            raise ValidationError("unsafe generated site destination")
        if destination.exists() and not overwrite:
            return SiteGenerationResult(
                False, brief.lead_slug, str(destination), (), (), brief.missing_information,
                "conflict", "site directory already exists",
            )
        self._sites_root.mkdir(parents=True, exist_ok=True)
        temp = Path(tempfile.mkdtemp(prefix=f".{brief.lead_slug}-", dir=self._sites_root))
        try:
            self._write_site(temp, brief)
            domains = tuple(urlsplit(item.website_url).hostname or "" for item in brief.market_research.benchmarks)
            validate_generated_site(temp, domains)
            if destination.exists():
                shutil.rmtree(destination)
            temp.replace(destination)
        except Exception:
            shutil.rmtree(temp, ignore_errors=True)
            raise
        warnings = tuple(f"Informação pendente: {item}" for item in brief.missing_information)
        return SiteGenerationResult(
            True, brief.lead_slug, str(destination), GENERATED_FILES, warnings,
            brief.missing_information, "regenerated" if overwrite else "generated",
        )

    def _write_site(self, directory: Path, brief: FirstWebsiteSiteBrief) -> None:
        (directory / "assets").mkdir()
        policy = POLICIES.get(brief.category.casefold(), GenericSitePolicy())
        (directory / "index.html").write_text(self._html(brief, policy), encoding="utf-8")
        (directory / "styles.css").write_text(_CSS, encoding="utf-8")
        files = list(GENERATED_FILES)
        manifest = {
            "lead_identity": {"slug": brief.lead_slug, "external_place_id": brief.external_place_id},
            "opportunity_type": brief.opportunity_type,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "generator_version": GENERATOR_VERSION, "source_batch_id": brief.batch_id,
            "benchmark_market": brief.market_research.benchmark_market,
            "strategy_version": SITE_STRATEGY_VERSION,
            "missing_information": list(brief.missing_information), "generated_files": files,
        }
        (directory / "site-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        (directory / "README.md").write_text(
            "# Rascunho local\n\nSite demonstrativo para revisão interna. Não publicado e não aprovado pelo cliente.\n",
            encoding="utf-8",
        )

    @staticmethod
    def _html(brief: FirstWebsiteSiteBrief, policy: CategorySitePolicy) -> str:
        name, city = escape(brief.business_name), escape(brief.city)
        description = escape(f"Conheça {brief.business_name} em {brief.city} e consulte os canais públicos de contato.")
        contact_links: list[str] = []
        if brief.whatsapp_confirmed and brief.whatsapp:
            digits = "".join(char for char in brief.whatsapp if char.isdigit())
            contact_links.append(f'<a class="button" href="https://wa.me/{digits}" target="_blank" rel="noopener noreferrer">Conversar pelo WhatsApp</a>')
        elif brief.phone:
            contact_links.append(f'<a class="button" href="tel:{quote(brief.phone, safe="+")}">Ligar para contato público</a>')
        if brief.maps_url:
            contact_links.append(f'<a class="button button--quiet" href="{escape(brief.maps_url, quote=True)}" target="_blank" rel="noopener noreferrer">Ver no mapa</a>')
        if brief.instagram:
            contact_links.append(f'<a class="text-link" href="{escape(brief.instagram, quote=True)}" target="_blank" rel="noopener noreferrer">Instagram público</a>')
        address = f'<p>{escape(brief.address)}</p>' if brief.address else '<p class="pending">Endereço a confirmar.</p>'
        contacts = "\n".join(contact_links) or '<p class="pending">Canais de contato aguardam confirmação.</p>'
        return f'''<!doctype html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} | {city}</title><meta name="description" content="{description}">
<meta property="og:title" content="{name}"><meta property="og:description" content="{description}">
<link rel="stylesheet" href="styles.css"></head>
<body><header class="site-header"><a class="brand" href="#inicio">{name}</a><nav aria-label="Navegação principal"><a href="#sobre">Sobre</a><a href="#contato">Contato</a></nav></header>
<main id="inicio"><section class="hero"><div><p class="eyebrow">Atendimento em {city}</p><h1>{name}</h1><p>{escape(policy.introduction(brief))}</p><div class="actions">{contacts}</div></div><div class="visual" role="img" aria-label="Espaço reservado para identidade visual aprovada"><span>Identidade visual<br>em definição</span></div></section>
<section id="sobre"><p class="eyebrow">Apresentação</p><h2>Informação clara para um contato mais simples</h2><p>Este espaço reúne dados públicos essenciais. Informações profissionais específicas serão publicadas somente após confirmação.</p></section>
<section><p class="eyebrow">{escape(policy.services_heading())}</p><h2>Conteúdo a validar</h2><div class="card"><h3>Em preparação</h3><p>{escape(policy.services_placeholder())}</p></div></section>
<section class="reputation"><div><p class="eyebrow">Reputação pública</p><h2>{brief.rating:.1f} de 5</h2><p>Com base em {brief.review_count} avaliações públicas.</p></div></section>
<section id="contato"><p class="eyebrow">Localização e contato</p><h2>Fale com {name}</h2>{address}<div class="actions">{contacts}</div></section></main>
<footer><p>{name} · {city}</p><p>Rascunho demonstrativo — informações sujeitas a confirmação.</p></footer></body></html>'''


_CSS = """\
:root{--color-bg:#f6f7f4;--color-surface:#fff;--color-text:#17211f;--color-muted:#586461;--color-accent:#176b5b;--color-accent-dark:#0e4d42;--space-1:.5rem;--space-2:1rem;--space-3:1.5rem;--space-4:2.5rem;--space-5:4rem;--radius:1rem;--max:70rem;font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:var(--color-text);background:var(--color-bg)}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;line-height:1.6}a{color:inherit}a:focus-visible{outline:3px solid #e29b42;outline-offset:3px}.site-header{max-width:var(--max);margin:auto;padding:var(--space-2);display:flex;justify-content:space-between;gap:var(--space-2);align-items:center}.brand{font-weight:800;text-decoration:none}.site-header nav{display:flex;gap:var(--space-2)}main section,footer{max-width:var(--max);margin:auto;padding:var(--space-5) var(--space-2)}.hero{display:grid;gap:var(--space-4);align-items:center;min-height:72vh}.hero h1{font-size:clamp(2.4rem,8vw,5.5rem);line-height:1;letter-spacing:-.04em;margin:.4rem 0 1.25rem}.eyebrow{text-transform:uppercase;letter-spacing:.12em;font-weight:800;color:var(--color-accent);font-size:.78rem}.visual{min-height:20rem;border-radius:var(--radius);background:linear-gradient(145deg,#cce2da,#f2d9b6);display:grid;place-items:center;text-align:center;font-weight:700;color:var(--color-accent-dark)}h2{font-size:clamp(1.8rem,5vw,3rem);line-height:1.1;max-width:18ch}.actions{display:flex;flex-wrap:wrap;gap:var(--space-2);align-items:center;margin-top:var(--space-3)}.button{display:inline-block;background:var(--color-accent);color:#fff;padding:.85rem 1.15rem;border-radius:999px;text-decoration:none;font-weight:750}.button:hover{background:var(--color-accent-dark)}.button--quiet{background:var(--color-surface);color:var(--color-text);border:1px solid #c8d0cd}.card,.reputation{background:var(--color-surface);border-radius:var(--radius);padding:var(--space-3);box-shadow:0 .5rem 2rem #17211f12}.pending{color:var(--color-muted);font-style:italic}footer{border-top:1px solid #d8dedb;color:var(--color-muted)}@media(min-width:48rem){.site-header{padding:var(--space-3) var(--space-2)}.hero{grid-template-columns:1.25fr .75fr}.card{max-width:38rem}}@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}\n"""
