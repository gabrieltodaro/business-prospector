from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.normalization import slugify


def resolve_site_directory(sites_root: Path, slug: str) -> Path:
    root = sites_root.expanduser().resolve()
    try:
        safe_slug = slugify(slug)
    except ValueError as exc:
        raise ValidationError("unsafe site slug") from exc
    if slug != safe_slug or slug in {"", ".", ".."}:
        raise ValidationError("unsafe site slug")
    site = (root / slug).resolve()
    if site.parent != root or not (site / "index.html").is_file():
        raise ValidationError("generated site not found")
    return site


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview one generated site on localhost")
    parser.add_argument("slug")
    parser.add_argument("--sites-root", type=Path, default=Path.cwd() / "sites")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    site = resolve_site_directory(args.sites_root, args.slug)
    handler = partial(SimpleHTTPRequestHandler, directory=str(site))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Previewing {site.name} at http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
