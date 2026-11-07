"""Install a fully validated replacement; retain previous artifacts outside public roots."""
from __future__ import annotations

import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from business_prospector.domain.exceptions import ValidationError


@contextmanager
def archive_draft(destination: Path) -> Iterator[Path | None]:
    """Remove a draft from active use, restoring it if the dependent operation fails."""
    previous: Path | None = None
    if destination.is_symlink():
        raise ValidationError('draft destination cannot be a symlink')
    if destination.exists():
        history = destination.parent.parent / 'site-revisions' / destination.name
        for directory in (history.parent, history):
            if directory.is_symlink():
                raise ValidationError('revision history cannot be a symlink')
        history.mkdir(parents=True, exist_ok=True)
        previous = history / str(uuid4())
        destination.rename(previous)
    try:
        yield previous
    except BaseException:
        if previous is not None:
            previous.replace(destination)
        raise


@contextmanager
def install_validated_draft(staging: Path, destination: Path) -> Iterator[Path | None]:
    with archive_draft(destination) as previous:
        installed = False
        try:
            staging.replace(destination)
            installed = True
            yield previous
        except BaseException:
            if installed and destination.exists():
                shutil.rmtree(destination)
            raise
