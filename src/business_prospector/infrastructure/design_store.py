"""Private lead-bound design receipts. No database migration and no public artifacts."""
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from business_prospector.application.artifacts import read_local_manifest
from business_prospector.domain.exceptions import ValidationError


class DesignStore:
    def __init__(self, data_root: Path) -> None:
        self.root = data_root / 'design-reviews'

    def _folder(self) -> Path:
        if self.root.is_symlink():
            raise ValidationError('design review directory cannot be a symlink')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        return self.root

    @staticmethod
    def identifier(value: str) -> str:
        try:
            if str(UUID(value)) != value:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValidationError('invalid design receipt id') from None
        return value

    def write(self, value: dict) -> str:
        encoded = json.dumps(value, ensure_ascii=False).encode('utf-8')
        if len(encoded) > 1024 * 1024:
            raise ValidationError('design receipt exceeds the 1 MiB budget')
        identifier = str(uuid4())
        folder = self._folder()
        path = folder / (identifier + '.json')
        # Exclusive creation; receipts are immutable, never overwritten by model output.
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
            stream.write(encoded)
        return identifier

    def read(self, identifier: str) -> dict:
        return read_local_manifest(self._folder(), self.identifier(identifier) + '.json')

    def save_images(self, images):
        from hashlib import sha256
        rows = []
        for image in images:
            if len(image.content) > 8 * 1024 * 1024:
                raise ValidationError('visual image exceeds byte budget')
            name = str(uuid4()) + '.image'
            with os.fdopen(os.open(self._folder() / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
                stream.write(image.content)
            rows.append({'file': name, 'sha256': sha256(image.content).hexdigest(),
                         'label': image.label, 'mime_type': image.mime_type})
        return rows

    def load_images(self, rows):
        from hashlib import sha256
        from business_prospector.application.artifacts import _read
        from business_prospector.application.visual_ports import VisualImage
        images = []
        for row in rows:
            self.identifier(row['file'].removesuffix('.image'))
            data = _read(self._folder(), row['file'], 8 * 1024 * 1024)
            if sha256(data).hexdigest() != row['sha256']:
                raise ValidationError('visual image changed')
            images.append(VisualImage(row['label'], data, row['mime_type']))
        return tuple(images)
