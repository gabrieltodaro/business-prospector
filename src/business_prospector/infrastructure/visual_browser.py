"""Isolated Chromium capture of an immutable public inventory; no external requests."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from urllib.parse import urlsplit

from business_prospector.application.artifacts import capture_artifact
from business_prospector.application.visual_ports import RenderCapture, VisualImage
from business_prospector.domain.exceptions import ValidationError


class ChromiumPageCapture:
    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable

    def capture(self, site: Path) -> RenderCapture:
        from playwright.sync_api import sync_playwright
        artifact = capture_artifact(site)
        inventory = {'/' + item.path: item.content for item in artifact.files}
        inventory['/'] = inventory['/index.html']
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                path = urlsplit(self.path).path
                data = inventory.get(path)
                if data is None:
                    self.send_error(404)
                    return
                suffix = Path(path).suffix
                mime = {'.css': 'text/css', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.svg': 'image/svg+xml'}.get(suffix, 'text/html')
                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        images, checks = [], {}
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=self.executable, headless=True,
                    args=['--disable-background-networking', '--disable-component-update', '--no-first-run'])
                try:
                    for label, width, height in [('desktop', 1440, 1000), ('mobile', 390, 844)]:
                        context = browser.new_context(viewport={'width': width, 'height': height}, reduced_motion='reduce', service_workers='block')
                        try:
                            blocked, errors = [], []
                            def route(request):
                                if request.request.url.startswith(origin + '/'):
                                    request.continue_()
                                else:
                                    blocked.append('external request blocked')
                                    request.abort()
                            context.route('**/*', route)
                            page = context.new_page()
                            page.set_default_timeout(10000)
                            page.on('pageerror', lambda error: errors.append('page error'))
                            page.goto(origin, wait_until='load', timeout=15000)
                            page.evaluate('document.fonts.ready')
                            measurements = page.evaluate('''() => {
                                const visible = e => e.getClientRects().length > 0;
                                const texts = [...document.querySelectorAll('main h1,main h2,main p:not(.hero-brand)')].map(e => e.textContent.trim()).filter(Boolean);
                                return {
                                    overflow: document.documentElement.scrollWidth > innerWidth,
                                    images_loaded: [...document.images].every(i => i.complete && i.naturalWidth > 0),
                                    image_alts: [...document.images].every(i => i.hasAttribute('alt')),
                                    headings: document.querySelectorAll('h1').length === 1,
                                    language: document.documentElement.lang === 'pt-BR',
                                    anchors: [...document.querySelectorAll('a[href^="#"]')].every(a => document.getElementById(a.hash.slice(1))),
                                    touch_targets: [...document.querySelectorAll('.button,nav a,summary')].filter(visible).every(e => e.getBoundingClientRect().height >= 44),
                                    hero_cta_visible: document.querySelector('.hero .button').getBoundingClientRect().bottom <= innerHeight,
                                    duplicate_blocks: texts.filter((t,i) => texts.indexOf(t) !== i && t.length > 40).length,
                                    height: document.documentElement.scrollHeight
                                };
                            }''')
                            if measurements['height'] > 12000:
                                raise ValidationError('page exceeds visual capture height budget')
                            if label == 'mobile':
                                page.locator('.mobile-menu summary').click()
                                measurements['mobile_menu'] = page.locator('.mobile-menu nav').is_visible()
                                page.locator('.mobile-menu summary').click()
                            checks[label] = {**measurements, 'external_requests': len(blocked), 'page_errors': len(errors)}
                            pixels = page.screenshot(full_page=True, timeout=15000)
                            if len(pixels) > 4 * 1024 * 1024:
                                raise ValidationError('screenshot exceeds visual evidence budget')
                            images.append(VisualImage(label, pixels))
                        finally:
                            context.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        return RenderCapture(tuple(images), checks)
