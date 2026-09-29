"""Image loader.

Images carry no text of their own, so this loader extracts embedded metadata
(EXIF, dimensions, format) and delegates any text recovery to an injected OCR
callable. Wiring in an OCR engine is left to the caller so the core stays free
of heavyweight or model-dependent dependencies.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..errors import LoadError
from ..models import BLOCK_METADATA, BLOCK_PARAGRAPH, Document, SourceRef, TextBlock
from ._optional import require

#: Signature of an OCR backend: given a path, return recognised text.
OcrBackend = Callable[[Path], str]

#: EXIF tags worth promoting to first-class metadata.
EXIF_WHITELIST = frozenset(
    {
        "Make",
        "Model",
        "DateTime",
        "DateTimeOriginal",
        "Software",
        "Artist",
        "Copyright",
        "ImageDescription",
        "GPSInfo",
    }
)


class ImageLoader:
    """Loader for raster images.

    Args:
        ocr: optional callable that returns text for an image path. When
            omitted the document carries metadata only.
    """

    name = "image"
    media_types = ("image/*",)

    def __init__(self, ocr: OcrBackend | None = None) -> None:
        self.ocr = ocr

    def load(self, path: Path, source: SourceRef) -> Document:
        image_module = require("PIL.Image", "image", purpose="reading images")
        try:
            with image_module.open(path) as image:
                width, height = image.size
                metadata: dict[str, Any] = {
                    "format": image.format,
                    "mode": image.mode,
                    "width": width,
                    "height": height,
                    "megapixels": round(width * height / 1_000_000, 3),
                    "has_exif": bool(image.getexif()),
                }
                metadata.update(_exif_metadata(image))
                if "dpi" in image.info:
                    metadata["dpi"] = image.info["dpi"]
        except LoadError:
            raise
        except Exception as exc:  # noqa: BLE001 - Pillow raises varied types
            raise LoadError(f"could not open image {path}: {exc}") from exc

        blocks: list[TextBlock] = [
            TextBlock(
                kind=BLOCK_METADATA,
                text=f"{key}={value}",
                locator="metadata",
            )
            for key, value in sorted(metadata.items())
        ]

        text = ""
        if self.ocr is not None:
            try:
                text = self.ocr(path) or ""
            except Exception as exc:  # noqa: BLE001 - backend is user-supplied
                raise LoadError(f"OCR backend failed for {path}: {exc}") from exc
            if text.strip():
                blocks.append(
                    TextBlock(
                        kind=BLOCK_PARAGRAPH, text=text.strip(), locator="ocr"
                    )
                )

        metadata["ocr_applied"] = self.ocr is not None
        metadata["text_length"] = len(text)
        return Document(source=source, text=text, blocks=blocks, metadata=metadata)


def _exif_metadata(image: Any) -> dict[str, Any]:
    """Return whitelisted EXIF tags as plain strings."""
    from PIL import ExifTags

    result: dict[str, Any] = {}
    try:
        exif = image.getexif()
    except Exception:  # noqa: BLE001 - malformed EXIF should not fail the load
        return result
    for tag_id, value in exif.items():
        name = ExifTags.TAGS.get(tag_id, str(tag_id))
        if name in EXIF_WHITELIST:
            result[f"exif_{name}"] = str(value)
    return result
