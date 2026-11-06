"""Small static components; only the verified content model reaches HTML."""
from __future__ import annotations

from html import escape
from importlib.resources import files

from business_prospector.domain.site_assets import SiteAsset
from business_prospector.domain.site_generation import FirstWebsiteSiteBrief
from business_prospector.domain.site_strategy import SECTION_LABELS
from business_prospector.domain.website_content_model import WebsiteContentModel, ContentSection, ContactAction, SECTION_IDS


def action_link(action: ContactAction, secondary: bool = False) -> str:
    external = ' target="_blank" rel="noopener noreferrer"' if action.external else ''
    style = 'button button--quiet' if secondary else 'button'
    return f'<a class="{style}" href="{escape(action.url, quote=True)}"{external}>{escape(action.label)}<span aria-hidden="true"> ↗</span></a>'


def image(asset: SiteAsset, *, hero: bool = False) -> str:
    dimensions = f' width="{asset.width}" height="{asset.height}"' if asset.width and asset.height else ''
    loading = ' fetchpriority="high"' if hero else ' loading="lazy"'
    return f'<img src="{escape(asset.local_file or "", quote=True)}" alt="{escape(asset.alt_text or "", quote=True)}"{dimensions}{loading}>'


def section_html(section: ContentSection, model: WebsiteContentModel, assets: tuple[SiteAsset, ...], index: int) -> str:
    body = ''.join(f'<p>{escape(paragraph)}</p>' for paragraph in section.paragraphs)
    if section.kind == 'faq':
        body += ''.join(f'<details class="faq-item"><summary>{escape(question)}</summary><p>{escape(answer)}</p></details>'
                        for question, answer in section.items)
    elif section.items:
        body += '<ul class="content-list">' + ''.join(f'<li><span class="item-number" aria-hidden="true">{i:02d}</span><span>{escape(label)}</span></li>'
                                                      for i, (label, _) in enumerate(section.items, 1)) + '</ul>'
    if section.kind == 'gallery':
        body += '<div class="gallery">' + ''.join(f'<figure>{image(asset)}</figure>' for asset in assets[1:]) + '</div>'
    if section.kind == 'contact':
        body += '<div class="actions">' + action_link(model.primary_action) + ''.join(action_link(action, True) for action in model.secondary_actions) + '</div>'
    return (f'<section id="{section.id}" class="content-section {section.kind}" aria-labelledby="heading-{section.id}">'
            f'<div class="section-heading"><p class="eyebrow">{index:02d} / {escape(SECTION_LABELS[section.kind])}</p>'
            f'<h2 id="heading-{section.id}">{escape(section.title)}</h2></div><div class="section-body">{body}</div></section>')


def render_html(brief: FirstWebsiteSiteBrief, assets: tuple[SiteAsset, ...], model: WebsiteContentModel) -> str:
    strategy = brief.strategy
    names = {section.kind: section.id for section in model.sections}
    def links(keys: tuple[str, ...]) -> str:
        return ''.join(f'<a href="#{names[key]}">{escape(SECTION_LABELS[key])}</a>' for key in keys)
    desktop = tuple(key for key in strategy.navigation if key != 'contact')[:4] + ('contact',)
    navigation = links(strategy.navigation)
    logo = next((asset for asset in assets if asset.asset_type == 'logo'), None)
    visual = next((asset for asset in assets if asset.asset_type != 'logo'), assets[0])
    photos = tuple(asset for asset in assets if asset.asset_type != 'logo')
    body = ''.join(section_html(section, model, photos, i) for i, section in enumerate(model.sections[1:], 1))
    name, city = escape(model.name), escape(model.city)
    description = escape(f'Demonstração independente para {model.name}, em {model.city}. Não é o site oficial.', quote=True)
    brand = (f'<span class="brand-logo">{image(logo)}</span>' if logo else '') + name
    return f'''<!doctype html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive"><meta name="referrer" content="no-referrer">
<title>{name} | Demonstração independente</title><meta name="description" content="{description}">
<meta property="og:title" content="{name} — Demonstração"><meta property="og:description" content="{description}">
<link rel="stylesheet" href="styles.css"></head>
<body class="palette-{strategy.palette} type-{strategy.typography} layout-{strategy.hero_composition}">
<a class="skip-link" href="#inicio">Ir para o conteúdo</a>
<aside class="preview-disclosure" aria-label="Aviso de demonstração"><span>Gapps.Tech / Prévia independente</span><p>{escape(model.disclosure)}</p></aside>
<header class="site-header"><a class="brand" href="#inicio">{brand}</a><nav class="desktop-nav" aria-label="Navegação principal">{links(desktop)}</nav>
<details class="mobile-menu"><summary>Menu <span aria-hidden="true">＋</span></summary><nav aria-label="Navegação móvel">{navigation}</nav></details></header>
<main id="inicio"><section class="hero" aria-labelledby="business-name"><div class="hero-copy"><p class="eyebrow">{city}</p><h1 id="business-name">{name}</h1>
<p class="lede">{escape(model.lead_text)}</p><div class="actions">{action_link(model.primary_action)}</div><p class="hero-note">Conceito visual para demonstração</p></div>
<div class="hero-media">{image(visual, hero=True)}<span class="image-caption">{city} <span aria-hidden="true">↗</span></span></div></section>
{body}</main><footer><div><p class="footer-brand">{name}</p><p>{city}</p></div><p class="footer-disclosure">{escape(model.disclosure)}</p><a href="#inicio">Voltar ao início ↑</a></footer></body></html>'''


def render_css() -> str:
    return files('business_prospector').joinpath('resources', 'preview.css').read_text(encoding='utf-8')
