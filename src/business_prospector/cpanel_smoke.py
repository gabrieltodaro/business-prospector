from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from business_prospector.application.site_generation import SiteDraftService, controlled_sites_root
from business_prospector.application.technical_deployment import TechnicalDeploymentSmokeService
from business_prospector.domain.exceptions import ProspectorError, ValidationError
from business_prospector.infrastructure.cpanel import (
    CPanelDeploymentConfig,
    CPanelError,
    CPanelUapiClient,
    HostGatorPreviewDeploymentProvider,
)


def _data_dir() -> Path:
    configured = os.environ.get("BUSINESS_PROSPECTOR_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".openclaw" / "data" / "business-prospector").resolve()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Controlled cPanel technical deployment test; dry-run is the default.",
    )
    parser.add_argument("--site-slug", help="Existing controlled generated-site slug")
    parser.add_argument("--preview-slug", required=True, help="Safe preview label only")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--dry-run", action="store_true", help="Validate and plan without cPanel calls")
    action.add_argument("--execute", action="store_true", help="Perform the explicitly confirmed test")
    action.add_argument("--status", action="store_true", help="Read provider status without a site")
    parser.add_argument("--confirm", help="Must exactly match --preview-slug with --execute")
    return parser


def run_command(
    args: argparse.Namespace, service: TechnicalDeploymentSmokeService,
) -> dict[str, object]:
    if args.status:
        if args.site_slug or args.confirm:
            raise ValidationError("--status accepts only --preview-slug")
        return service.status(args.preview_slug)
    if not args.site_slug:
        raise ValidationError("--site-slug is required for dry-run and execute")
    if args.execute:
        return service.execute(
            args.site_slug, args.preview_slug,
            explicitly_authorized=True, confirmation=args.confirm,
        )
    if args.confirm:
        raise ValidationError("--confirm is only accepted with --execute")
    return service.plan(args.site_slug, args.preview_slug).to_dict()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = CPanelDeploymentConfig.from_environment()
        if config is None:
            raise ValidationError("cPanel deployment configuration is not configured")
        provider = HostGatorPreviewDeploymentProvider(config, CPanelUapiClient(config))
        service = TechnicalDeploymentSmokeService(
            SiteDraftService(controlled_sites_root(_data_dir())), provider,
        )
        output = run_command(args, service)
    except (CPanelError, ProspectorError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, CPanelError) else "validation_error"
        print(json.dumps({
            "ok": False,
            "technical_deployment": True,
            "deployment_purpose": "technical_test",
            "error_code": code,
            "error": str(exc),
            **({"details": exc.safe_details} if isinstance(exc, CPanelError) and exc.safe_details else {}),
        }, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
