"""Local-only Chromium visual checks. Requires Playwright; never starts application storage."""
import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from html import escape
from pathlib import Path
import threading
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sites', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--chromium', default='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    parser.add_argument('--axe-script', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(args.sites.resolve())))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.chromium, headless=True,
                args=['--disable-background-networking', '--disable-component-update', '--no-first-run'])
            for site in sorted(args.sites.iterdir()):
                if not site.is_dir():
                    continue
                for label, width, height in [('desktop', 1440, 1000), ('mobile', 390, 844), ('narrow', 320, 760)]:
                    context = browser.new_context(viewport={'width': width, 'height': height}, reduced_motion='reduce')
                    external = []
                    def route_request(route):
                        if urlsplit(route.request.url).hostname != '127.0.0.1':
                            external.append(route.request.url)
                            route.abort()
                        else:
                            route.continue_()
                    context.route('**/*', route_request)
                    context.add_init_script("""window.__layoutShift = 0;
                        new PerformanceObserver(list => { for (const entry of list.getEntries()) {
                            if (!entry.hadRecentInput) window.__layoutShift += entry.value;
                        }}).observe({type: 'layout-shift', buffered: true});""")
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/{site.name}/', wait_until='networkidle')
                    metrics = page.evaluate('''() => ({
                        overflow: document.documentElement.scrollWidth > innerWidth,
                        images: [...document.images].every(i => i.complete && i.naturalWidth > 0),
                        anchors: [...document.querySelectorAll('a[href^="#"]')].every(a => document.getElementById(a.hash.slice(1))),
                        headings: document.querySelectorAll('h1').length,
                        heroCTA: document.querySelector('.hero .button').getBoundingClientRect().bottom,
                        touchTargets: [...document.querySelectorAll('.button, nav a, summary')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().height >= 44),
                        transferBytes: performance.getEntriesByType('resource').reduce((s,r) => s + r.transferSize, 0),
                        layoutShifts: window.__layoutShift,
                        reducedMotion: getComputedStyle(document.querySelector('.hero-copy')).animationName === 'none'
                    })''')
                    if label == 'mobile':
                        page.locator('.mobile-menu summary').click()
                        metrics['menu'] = page.locator('.mobile-menu nav').is_visible()
                        page.locator('.mobile-menu summary').click()
                    violations = []
                    if args.axe_script:
                        page.add_script_tag(path=str(args.axe_script))
                        audit = page.evaluate("async () => await axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21aa']}})")
                        violations = [{'id': v['id'], 'impact': v['impact'], 'nodes': [n['target'] for n in v['nodes']]} for v in audit['violations']]
                    if label != 'narrow':
                        page.screenshot(path=str(args.output / f'{site.name}-{label}.png'), full_page=True)
                        page.screenshot(path=str(args.output / f'{site.name}-{label}-hero.png'))
                    results.append({'site': site.name, 'viewport': label, **metrics, 'axe_violations': violations,
                                    'page_errors': errors, 'external_requests': external})
                    context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    (args.output / 'browser-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    cards = []
    for site in sorted({r['site'] for r in results}):
        desktop = escape(site + '-desktop.png', quote=True)
        mobile = escape(site + '-mobile.png', quote=True)
        cards.append(f'<article><h2>{escape(site)}</h2><a href="{desktop}"><img src="{desktop}" alt="Desktop capture" loading="lazy"></a><p><a href="{mobile}">Mobile screenshot</a></p></article>')
    (args.output / 'index.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Premium generator visual validation</title><style>body{font:16px/1.6 system-ui;background:#f4f3eb;color:#183e37;margin:4vw}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:2rem}h2{font-size:1rem;overflow-wrap:anywhere}img{width:100%;height:auto}a{color:inherit}</style><h1>Premium generator · visual validation</h1><p>Three synthetic businesses. Real illustrative stock with attribution. Chromium at 1440, 390 and 320px. No public deployment.</p><p><a href="browser-results.json">Browser measurements and accessibility results</a></p><main>' + ''.join(cards) + '</main></html>')
    print(json.dumps(results, ensure_ascii=False, indent=2))
    assert all(not r['overflow'] and r['images'] and r['anchors'] and r['touchTargets'] and r['headings'] == 1
               and not r['axe_violations'] and not r['page_errors'] and not r['external_requests'] for r in results)


if __name__ == '__main__':
    main()
