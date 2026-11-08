"""Provider-neutral visual intelligence and browser capture boundaries."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class VisualImage:
    label: str
    content: bytes
    mime_type: str = 'image/png'


@dataclass(frozen=True)
class VisualResponse:
    data: dict[str, Any]
    evaluator: str


class VisualEvaluator(Protocol):
    async def evaluate(self, prompt: str, images: tuple[VisualImage, ...]) -> VisualResponse | None: ...


@dataclass(frozen=True)
class RenderCapture:
    images: tuple[VisualImage, ...]
    checks: dict[str, Any]


class PageCapture(Protocol):
    def capture(self, site: Path) -> RenderCapture: ...
