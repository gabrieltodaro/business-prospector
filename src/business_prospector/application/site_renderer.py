"""Static editorial components; verified content and reviewed assets only."""
from __future__ import annotations

from html import escape
from importlib.resources import files
from typing import Any

from business_prospector.domain.site_assets import SiteAsset
from business_prospector.domain.site_generation import FirstWebsiteSiteBrief
from business_prospector.domain.site_strategy import SECTION_LABELS
from business_prospector.domain.stock_photography import ILLUSTRATIVE_DISCLOSURE
from business_prospector.domain.website_content_model import WebsiteContentModel, ContentSection, ContactAction


def action_link(action: ContactAction, secondary: bool = False) -> str:
    external = ' target="_blank" rel="noopener noreferrer"' if action.external else ''
    style = 'button button--quiet' if secondary else 'button'
    return f'<a class="{style}" href="{escape(action.url, quote=True)}"{external}>{escape(action.label)}<span aria-hidden="true"> ↗</span></a>'


def image(asset: SiteAsset, *, hero: bool = False) -> str:
    dimensions = f' width="{asset.width}" height="{asset.height}"' if asset.width and asset.height else ''
    loading = ' fetchpriority="high"' if hero else ' loading="lazy"'
    return f'<img src="{escape(asset.local_file or "", quote=True)}" alt="{escape(asset.alt_text or "", quote=True)}"{dimensions}{loading} decoding="async">'


def photo_caption(asset: SiteAsset) -> str:
    if asset.source_type != 'licensed_stock':
        return ''
    stock = asset.stock
    credit = ''
    if stock:
        credit = (f' Foto: <a href="{escape(stock.source_page, quote=True)}" target="_blank" rel="noopener noreferrer">'
                  f'{escape(stock.photographer)} / {escape(stock.provider.title())}</a>.')
    return f'<figcaption class="photo-credit">{ILLUSTRATIVE_DISCLOSURE}{credit}</figcaption>'


def stock_outreach_context(assets: tuple[SiteAsset, ...]) -> dict[str, Any]:
    stock = [a for a in assets if a.source_type == 'licensed_stock']
    return {'contains_illustrative_stock': bool(stock), 'depicts_actual_business': False if stock else None,
            'message': ('Esta prévia usa fotografias ilustrativas de banco de imagens, que não representam necessariamente o negócio. '
                        'O site final pode incorporar fotografias e materiais fornecidos pelo proprietário.') if stock else None,
            'images': [{'asset_key': a.key, 'provenance': a.stock.to_dict() if a.stock else None} for a in stock]}


def section_html(section: ContentSection, model: WebsiteContentModel, assets: tuple[SiteAsset, ...], index: int) -> str:
    body = ''.join(f'<p>{escape(paragraph)}</p>' for paragraph in section.paragraphs)
    if section.kind == 'faq':
        body += ''.join(f'<details class="faq-item"><summary>{escape(question)}</summary><p>{escape(answer)}</p></details>'
                        for question, answer in section.items)
    elif section.items:
        body += '<ul class="content-list">' + ''.join(f'<li><span class="item-number" aria-hidden="true">{i:02d}</span><span>{escape(label)}</span><span class="item-arrow" aria-hidden="true">↗</span></li>'
                                                      for i, (label, _) in enumerate(section.items, 1)) + '</ul>'
    if section.kind == 'gallery':
        body += '<div class="gallery">' + ''.join(f'<figure>{image(asset)}{photo_caption(asset)}</figure>' for asset in assets[1:]) + '</div>'
    if section.kind == 'location':
        location_action = next((a for a in (model.primary_action, *model.secondary_actions) if a.label in {'Ver no mapa', 'Ver localização'}), None)
        if location_action:
            body += action_link(ContactAction('Traçar meu caminho', location_action.url, True))
        body = '<div class="location-detail"><span class="location-mark" aria-hidden="true">↗</span>' + body + '</div>'
    if section.kind == 'contact':
        body = '<p class="contact-intro">O próximo passo é uma conversa.</p>' + body
        body += '<div class="actions">' + (action_link(model.primary_action) if model.primary_action.url != '#contato' else '') + ''.join(action_link(action, True) for action in model.secondary_actions if action.label != 'Ver no mapa') + '</div>'
    return (f'<section id="{section.id}" class="content-section {section.kind}" aria-labelledby="heading-{section.id}">'
            f'<div class="section-heading"><p class="eyebrow">{index:02d} / {escape(SECTION_LABELS[section.kind])}</p>'
            f'<h2 id="heading-{section.id}">{escape(section.title)}</h2></div><div class="section-body">{body}</div></section>')


def render_html(brief: FirstWebsiteSiteBrief, assets: tuple[SiteAsset, ...], model: WebsiteContentModel) -> str:
    strategy = brief.strategy
    names = {section.kind: section.id for section in model.sections}
    def links(keys: tuple[str, ...]) -> str:
        return ''.join(f'<a href="#{names[key]}">{escape(SECTION_LABELS[key])}</a>' for key in keys if key in names)
    desktop = tuple(key for key in strategy.navigation if key != 'contact')[:3] + ('contact',)
    logo = next((asset for asset in assets if asset.asset_type == 'logo'), None)
    photos = tuple(asset for asset in assets if asset.asset_type != 'logo')
    body = ''.join(section_html(section, model, photos, i) for i, section in enumerate(model.sections[1:], 1))
    name, city = escape(model.name), escape(model.city)
    description = escape(f'Demonstração independente para {model.name}, em {model.city}. Não é o site oficial.', quote=True)
    brand = (f'<span class="brand-logo">{image(logo)}</span>' if logo else '') + escape(model.display_name)
    visual = f'<figure class="hero-media">{image(photos[0], hero=True)}{photo_caption(photos[0])}</figure>' if photos else ''
    headline = '<br>'.join(escape(part) for part in model.headline.split('\n'))
    # Preview branding is distinct from the business identity; no implied client endorsement.
    credits = ('<a class="provider-credit" href="https://www.pexels.com" target="_blank" rel="noopener noreferrer">Photos provided by Pexels</a>'
               if any(a.stock and a.stock.provider == 'pexels' for a in assets) else '')
    return f'''<!doctype html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive"><meta name="referrer" content="no-referrer">
<title>{name} | Demonstração independente</title><meta name="description" content="{description}">
<meta property="og:title" content="{name} — Demonstração"><meta property="og:description" content="{description}">
<link rel="stylesheet" href="styles.css"></head>
<body class="palette-{strategy.palette} type-{strategy.typography} layout-{strategy.hero_composition} category-{strategy.category_policy}">
<a class="skip-link" href="#inicio">Ir para o conteúdo</a>
<aside class="preview-disclosure" aria-label="Aviso de demonstração"><span>Gapps.Tech / Prévia independente</span><p>{escape(model.disclosure)}</p></aside>
<header class="site-header"><a class="brand" href="#inicio">{brand}</a><nav class="desktop-nav" aria-label="Navegação principal">{links(desktop)}</nav>
<details class="mobile-menu"><summary>Menu <span aria-hidden="true">＋</span></summary><nav aria-label="Navegação móvel">{links(strategy.navigation)}</nav></details></header>
<main id="inicio"><section class="hero" aria-labelledby="hero-headline"><div class="hero-copy"><p class="eyebrow">{escape(model.category_label)} <span aria-hidden="true"> / </span> {city}</p>
<p class="hero-brand">{escape(model.display_name)}</p><h1 id="hero-headline">{headline}</h1>
<p class="lede">{escape(model.lead_text)}</p><div class="actions">{action_link(model.primary_action)}</div></div>{visual}</section>
{body}</main><footer><div><p class="footer-brand">{name}</p><p>{city}</p></div><div><p class="footer-disclosure">{escape(model.disclosure)}</p>{credits}</div><a href="#inicio">Voltar ao início ↑</a></footer></body></html>'''


def render_css() -> str:
    return files('business_prospector').joinpath('resources', 'preview.css').read_text(encoding='utf-8')
