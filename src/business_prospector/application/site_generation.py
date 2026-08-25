from __future__ import annotations

import json
import hashlib
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
from business_prospector.domain.site_assets import SiteAsset
from business_prospector.application.ports import LeadRepository

GENERATOR_VERSION = "2.0.0"
REQUIRED_FILES = ("index.html", "styles.css", "site-manifest.json", "README.md")
GENERATED_FILES = ("index.html", "styles.css", "assets/", "site-manifest.json", "README.md")


def controlled_sites_root(data_dir: Path) -> Path:
    """Derive the non-user-selectable generated-sites root from plugin data."""
    return data_dir.expanduser().resolve() / "sites"


@dataclass(frozen=True, slots=True)
class SiteDraftInfo:
    exists: bool
    lead_slug: str
    site_path: Path | None = None
    generated_at: str | None = None
    generation_status: str = "missing"
    manifest: dict[str, Any] | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "exists": self.exists, "lead_slug": self.lead_slug,
            "generated_at": self.generated_at, "generation_status": self.generation_status,
            "manifest": self.manifest,
            "site_url": f"/sites/{self.lead_slug}/" if self.exists else None,
        }


class SiteDraftService:
    """Read-only boundary for validated generated artifacts."""

    def __init__(self, sites_root: Path) -> None:
        self._sites_root = sites_root.expanduser().resolve()

    def inspect(self, slug: str) -> SiteDraftInfo:
        try:
            site = self._site_directory(slug)
            if not site.is_dir():
                return SiteDraftInfo(False, slug)
            validate_generated_site(site)
            raw_manifest = json.loads((site / "site-manifest.json").read_text(encoding="utf-8"))
            if not isinstance(raw_manifest, dict):
                raise ValidationError("site manifest must be an object")
            identity = raw_manifest.get("lead_identity")
            if not isinstance(identity, dict) or identity.get("slug") != slug:
                raise ValidationError("site manifest identity does not match lead")
            generated_at = raw_manifest.get("generated_at")
            if not isinstance(generated_at, str) or not generated_at.strip():
                raise ValidationError("site manifest generated_at is invalid")
            safe_manifest = {
                key: raw_manifest.get(key) for key in (
                    "opportunity_type", "generated_at", "generator_version", "source_batch_id",
                    "benchmark_market", "strategy_version", "missing_information",
                )
            }
            return SiteDraftInfo(True, slug, site, generated_at, "generated", safe_manifest)
        except (ValidationError, ValueError, OSError, json.JSONDecodeError):
            return SiteDraftInfo(False, slug, generation_status="invalid")

    def resolve_file(self, slug: str, relative_parts: tuple[str, ...]) -> Path | None:
        info = self.inspect(slug)
        if not info.exists or info.site_path is None:
            return None
        if not relative_parts:
            relative_parts = ("index.html",)
        allowed = relative_parts in {("index.html",), ("styles.css",)}
        if relative_parts and relative_parts[0] == "assets" and len(relative_parts) > 1:
            allowed = all(part not in {"", ".", ".."} and "/" not in part and "\\" not in part for part in relative_parts)
        if not allowed:
            return None
        candidate = info.site_path.joinpath(*relative_parts).resolve()
        try:
            candidate.relative_to(info.site_path)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def _site_directory(self, slug: str) -> Path:
        try:
            from business_prospector.domain.normalization import slugify
            safe_slug = slugify(slug)
        except ValueError as exc:
            raise ValidationError("unsafe site slug") from exc
        if slug != safe_slug or slug in {"", ".", ".."}:
            raise ValidationError("unsafe site slug")
        site = (self._sites_root / slug).resolve()
        try:
            site.relative_to(self._sites_root)
        except ValueError as exc:
            raise ValidationError("unsafe site path") from exc
        return site


class CategorySitePolicy(Protocol):
    def introduction(self, brief: FirstWebsiteSiteBrief) -> str: ...
    def local_heading(self, brief: FirstWebsiteSiteBrief) -> str: ...
    def local_copy(self, brief: FirstWebsiteSiteBrief) -> str: ...


class GenericSitePolicy:
    def introduction(self, brief: FirstWebsiteSiteBrief) -> str:
        return f"Informações essenciais e contato direto com {brief.business_name}, em {brief.city}."

    def local_heading(self, brief: FirstWebsiteSiteBrief) -> str:
        return f"Atendimento local em {brief.city}"

    def local_copy(self, brief: FirstWebsiteSiteBrief) -> str:
        return "Consulte os canais públicos para conhecer o atendimento e tirar dúvidas."


class DentistSitePolicy(GenericSitePolicy):
    def introduction(self, brief: FirstWebsiteSiteBrief) -> str:
        return f"Cuidado odontológico mais perto de você, com contato simples e informações claras."

    def local_heading(self, brief: FirstWebsiteSiteBrief) -> str:
        return f"Atendimento odontológico em {brief.city}"

    def local_copy(self, brief: FirstWebsiteSiteBrief) -> str:
        return "Entre em contato para conhecer as opções de atendimento disponíveis."


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
        if tag == "img":
            src = values.get("src") or ""
            if urlsplit(src).scheme or src.startswith("//"):
                self.errors.append("generated images must be local")
            if "alt" not in values:
                self.errors.append("generated images require alt text")


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
        assets: tuple[SiteAsset, ...] = (), asset_source_root: Path | None = None,
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
            rendered_assets = self._write_site(temp, brief, assets, asset_source_root)
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

    def _write_site(
        self, directory: Path, brief: FirstWebsiteSiteBrief, assets: tuple[SiteAsset, ...],
        asset_source_root: Path | None,
    ) -> tuple[SiteAsset, ...]:
        assets_dir = directory / "assets"
        assets_dir.mkdir()
        rendered_assets: list[SiteAsset] = []
        source_root = asset_source_root.expanduser().resolve() if asset_source_root else None
        for asset in assets:
            if asset.approval_status != "approved_for_draft" or not asset.local_file or source_root is None:
                continue
            source = (source_root / asset.local_file).resolve()
            try:
                source.relative_to(source_root)
            except ValueError as exc:
                raise ValidationError("asset source escapes the controlled root") from exc
            if not source.is_file():
                raise ValidationError("approved asset file is missing")
            destination = assets_dir / source.name
            shutil.copyfile(source, destination)
            rendered_assets.append(asset.with_local_file(
                f"assets/{destination.name}", asset.checksum or "", asset.mime_type or "", asset.byte_size or source.stat().st_size,
            ))
        if not rendered_assets:
            fallback = assets_dir / "hero-visual.svg"
            fallback.write_text(_HERO_SVG, encoding="utf-8")
            fallback_bytes = fallback.read_bytes()
            rendered_assets.append(SiteAsset(
                key="hero-visual", asset_type="illustration", source_type="generated",
                source_url=None, discovered_from=None, business_identity_match=True,
                rights_status="generated", approval_status="approved_for_publish", alt_text="",
                width=1200, height=900, mime_type="image/svg+xml", byte_size=len(fallback_bytes),
                local_file="assets/hero-visual.svg", checksum=hashlib.sha256(fallback_bytes).hexdigest(),
                notes="Authored decorative fallback; replace only with an approved business asset.",
            ))
        policy = POLICIES.get(brief.category.casefold(), GenericSitePolicy())
        (directory / "index.html").write_text(self._html(brief, policy, tuple(rendered_assets)), encoding="utf-8")
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
            "assets": [asset.to_dict() for asset in rendered_assets],
        }
        (directory / "site-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        (directory / "README.md").write_text(
            "# Rascunho local\n\nSite demonstrativo para revisão interna. Não publicado e não aprovado pelo cliente.\n\n"
            "Informações ausentes e proveniência dos assets estão em `site-manifest.json`. "
            "Aprovação para draft não representa aprovação para publicação.\n",
            encoding="utf-8",
        )
        return tuple(rendered_assets)

    @staticmethod
    def _html(
        brief: FirstWebsiteSiteBrief, policy: CategorySitePolicy, assets: tuple[SiteAsset, ...],
    ) -> str:
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
        address = f'<p>{escape(brief.address)}</p>' if brief.address else f'<p>{city}</p>'
        contacts = "\n".join(contact_links) or '<a class="button" href="#contato">Ver contato</a>'
        hero = assets[0]
        dimensions = (
            f' width="{hero.width}" height="{hero.height}"' if hero.width and hero.height else ""
        )
        hero_image = f'<img src="{escape(hero.local_file or "", quote=True)}" alt="{escape(hero.alt_text or "", quote=True)}"{dimensions} fetchpriority="high">'
        gallery_items = "".join(
            f'<figure><img src="{escape(asset.local_file or "", quote=True)}" alt="{escape(asset.alt_text or "", quote=True)}"'
            f'{f" width={asset.width} height={asset.height}" if asset.width and asset.height else ""} loading="lazy"></figure>'
            for asset in assets[1:]
        )
        gallery = f'<section class="gallery" aria-label="Imagens do negócio">{gallery_items}</section>' if gallery_items else ""
        return f'''<!doctype html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} | {city}</title><meta name="description" content="{description}">
<meta property="og:title" content="{name}"><meta property="og:description" content="{description}">
<link rel="stylesheet" href="styles.css"></head>
<body><header class="site-header"><a class="brand" href="#inicio">{name}</a><nav aria-label="Navegação principal"><a href="#sobre">Sobre</a><a href="#contato">Contato</a></nav></header>
<main id="inicio"><section class="hero"><div class="hero-copy"><p class="eyebrow">{city}</p><h1>{name}</h1><p class="lede">{escape(policy.introduction(brief))}</p><div class="actions">{contacts}</div></div><div class="hero-media">{hero_image}<span class="hero-mark" aria-hidden="true">✦</span></div></section>
<section class="trust-bar" aria-label="Reputação pública"><p><strong>{brief.rating:.1f}</strong> no Google</p><span aria-hidden="true"></span><p><strong>{brief.review_count}</strong> avaliações</p><span aria-hidden="true"></span><p><strong>{city}</strong></p></section>
<section id="sobre" class="intro section-grid"><p class="eyebrow">Perto de você</p><div><h2>{escape(policy.local_heading(brief))}</h2><p>{escape(policy.local_copy(brief))}</p></div></section>
{gallery}
<section class="reputation section-grid"><p class="eyebrow">Confiança pública</p><div><p class="rating-line"><strong>{brief.rating:.1f}</strong><span>de 5</span></p><h2>{brief.review_count} avaliações públicas</h2><p>Reputação pública consultada para facilitar sua escolha.</p></div></section>
<section id="contato" class="contact section-grid"><p class="eyebrow">Contato e localização</p><div><h2>Fale com {name}</h2>{address}<div class="actions">{contacts}</div></div></section>
<section class="closing"><p class="eyebrow">{city}</p><h2>Seu próximo contato pode começar aqui.</h2><div class="actions">{contacts}</div></section></main>
<footer><p class="footer-brand">{name}</p><p>{city}</p></footer></body></html>'''


class PersistedSiteGenerationWorkflow:
    """Coordinates artifact generation and the post-validation pipeline transition."""

    def __init__(self, repository: LeadRepository, generator: SiteGenerationService) -> None:
        self._repository = repository
        self._generator = generator

    def generate(
        self, lead_id: int, research: dict[str, Any], *, overwrite: bool = False,
    ) -> tuple[SiteGenerationResult, Any | None]:
        if isinstance(lead_id, bool) or not isinstance(lead_id, int) or lead_id < 1:
            raise ValidationError("persisted lead id is required")
        lead = self._repository.get(lead_id)
        if lead is None:
            raise ValidationError("persisted lead not found")
        if lead.status != "qualified":
            raise ValidationError("persisted lead must have qualified status")
        result = self._generator.generate(lead.to_dict(), research, overwrite=overwrite)
        if not result.ok:
            return result, None
        updated = self._repository.update(lead_id, {"status": "internal_website"})
        return result, updated


_HERO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 900" role="img">
<defs><linearGradient id="a" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#d8ece5"/><stop offset="1" stop-color="#f1dfc5"/></linearGradient><filter id="b"><feGaussianBlur stdDeviation="28"/></filter></defs>
<rect width="1200" height="900" fill="url(#a)"/><circle cx="930" cy="210" r="245" fill="#fff" opacity=".58"/><circle cx="250" cy="720" r="310" fill="#2f7869" opacity=".18" filter="url(#b)"/><path d="M170 535c185-250 369-276 552-79 110 118 219 131 327 39v276H170z" fill="#fff" opacity=".72"/><path d="M650 166c76 65 116 155 120 269-102-49-204-47-307 5 18-123 80-214 187-274z" fill="#2f7869" opacity=".72"/></svg>"""

_CSS = """\
:root{--ink:#17302b;--muted:#5e6d68;--paper:#f4f2eb;--surface:#fff;--sage:#2f7869;--sage-dark:#1d5b50;--sand:#e9d8bd;--line:#d8ded8;--s1:.5rem;--s2:1rem;--s3:1.5rem;--s4:2.5rem;--s5:4rem;--s6:6rem;--r1:.75rem;--r2:1.5rem;--shadow:0 1.5rem 4rem #17302b18;--content:72rem;--narrow:42rem;font-family:Inter,Avenir,ui-sans-serif,system-ui,sans-serif;color:var(--ink);background:var(--paper)}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;line-height:1.55}img{display:block;max-width:100%;height:auto}a{color:inherit}a:focus-visible{outline:3px solid #c87c42;outline-offset:4px}.site-header{position:sticky;top:0;z-index:10;min-height:4.5rem;padding:var(--s2) max(var(--s2),calc((100vw - var(--content))/2));display:flex;align-items:center;justify-content:space-between;gap:var(--s2);background:#f4f2ebed;backdrop-filter:blur(14px);border-bottom:1px solid #ffffff8c}.brand{max-width:34rem;font-family:Georgia,serif;font-weight:700;line-height:1.1;text-decoration:none}.site-header nav{display:flex;gap:var(--s3);font-size:.9rem;font-weight:700}.site-header nav a{text-decoration:none}.site-header nav a:hover{color:var(--sage)}.hero{min-height:calc(100svh - 4.5rem);display:grid;align-items:center;gap:var(--s4);padding:var(--s4) max(var(--s2),calc((100vw - var(--content))/2)) var(--s5);overflow:hidden}.hero-copy{max-width:38rem;animation:rise .7s both}.eyebrow{margin:0 0 var(--s2);color:var(--sage);font-size:.72rem;font-weight:900;letter-spacing:.15em;text-transform:uppercase}.hero h1{margin:0;font-family:Georgia,serif;font-size:clamp(2.65rem,8vw,5.65rem);font-weight:500;letter-spacing:-.045em;line-height:.98}.lede{max-width:34rem;margin:var(--s3) 0 0;color:var(--muted);font-size:clamp(1.05rem,2vw,1.3rem)}.hero-media{position:relative;min-height:24rem;overflow:hidden;border-radius:var(--r2);box-shadow:var(--shadow);animation:reveal .85s .12s both}.hero-media img{width:100%;height:100%;min-height:24rem;object-fit:cover;transition:transform .7s ease}.hero-media:hover img{transform:scale(1.025)}.hero-mark{position:absolute;right:var(--s3);bottom:var(--s3);width:3.5rem;height:3.5rem;display:grid;place-items:center;border-radius:50%;background:#fff;color:var(--sage);font-size:1.5rem;box-shadow:0 .5rem 2rem #17302b22}.actions{display:flex;flex-wrap:wrap;align-items:center;gap:.75rem;margin-top:var(--s3)}.button{display:inline-flex;min-height:3rem;align-items:center;justify-content:center;padding:.75rem 1.2rem;border:1px solid var(--sage);border-radius:999px;background:var(--sage);color:#fff;font-weight:800;text-decoration:none;transition:transform .18s,background .18s}.button:hover{transform:translateY(-2px);background:var(--sage-dark)}.button--quiet{background:transparent;color:var(--ink);border-color:#8b9994}.text-link{font-weight:800;text-underline-offset:.25rem}.trust-bar{max-width:var(--content);margin:0 auto;padding:var(--s3) var(--s2);display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:var(--s2);border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.trust-bar p{margin:0;color:var(--muted)}.trust-bar strong{color:var(--ink)}.trust-bar span{width:4px;height:4px;border-radius:50%;background:var(--sage)}.section-grid{max-width:var(--content);margin:auto;padding:var(--s6) var(--s2);display:grid;gap:var(--s3);border-bottom:1px solid var(--line)}.section-grid h2,.closing h2{max-width:18ch;margin:0 0 var(--s2);font-family:Georgia,serif;font-size:clamp(2rem,5vw,3.8rem);font-weight:500;line-height:1.05;letter-spacing:-.035em}.section-grid>div>p{max-width:var(--narrow);color:var(--muted);font-size:1.08rem}.reputation{background:var(--ink);color:#fff;max-width:none;padding-inline:max(var(--s2),calc((100vw - var(--content))/2))}.reputation .eyebrow,.reputation div>p{color:#b8d8cf}.rating-line{display:flex;align-items:baseline;gap:.75rem;margin:0!important}.rating-line strong{font:500 clamp(4.5rem,13vw,9rem)/.8 Georgia,serif;color:#fff}.rating-line span{font-size:1.15rem}.gallery{max-width:var(--content);margin:auto;padding:var(--s2);display:grid;gap:var(--s2)}.gallery figure{margin:0;overflow:hidden;border-radius:var(--r2)}.gallery img{width:100%;aspect-ratio:4/3;object-fit:cover}.contact{background:var(--surface)}.closing{max-width:var(--content);margin:auto;padding:var(--s6) var(--s2);text-align:center}.closing h2{margin-inline:auto}.closing .actions{justify-content:center}footer{max-width:var(--content);margin:auto;padding:var(--s4) var(--s2);display:flex;justify-content:space-between;gap:var(--s2);border-top:1px solid var(--line);color:var(--muted)}footer p{margin:0}.footer-brand{font-family:Georgia,serif;color:var(--ink);font-weight:700}@media(min-width:48rem){.hero{grid-template-columns:minmax(0,1fr) minmax(22rem,.82fr)}.hero-media{height:min(68vh,42rem)}.section-grid{grid-template-columns:12rem 1fr}.gallery{grid-template-columns:repeat(2,1fr)}.gallery figure:first-child:last-child{grid-column:1/-1}.site-header{padding-block:var(--s3)}}@media(max-width:38rem){.site-header nav a:first-child{display:none}.hero{padding-top:var(--s3);min-height:auto}.hero h1{font-size:clamp(2.5rem,13vw,4rem)}.hero-media{min-height:20rem}.hero-media img{min-height:20rem}.trust-bar{justify-content:flex-start}.trust-bar span{display:none}.trust-bar p{flex:1 0 40%}.section-grid,.closing{padding-block:var(--s5)}footer{flex-direction:column}}@keyframes rise{from{opacity:0;transform:translateY(1.25rem)}to{opacity:1;transform:none}}@keyframes reveal{from{opacity:0;transform:translateY(1.5rem) scale(.98)}to{opacity:1;transform:none}}@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*::before,*::after{animation:none!important;transition:none!important}}\n"""
