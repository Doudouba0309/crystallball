"""LLM-backed extraction.

The library never imports or calls a model provider itself. Instead you pass a
completion callable, which keeps credentials, cost controls, and provider
choice entirely in the caller's hands — and keeps the test suite offline.

Example:
    >>> def complete(prompt: str) -> str:          # doctest: +SKIP
    ...     return my_client.chat(prompt)
    >>> extractor = LlmExtractor(complete, fields=["vendor", "total_amount"])
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from typing import Any

from ..errors import ExtractError
from ..models import Document, ExtractionResult
from .base import Extractor

#: A function that maps a prompt to a model's raw text response.
CompletionFn = Callable[[str], str]

#: Default character budget for document text sent to the model.
DEFAULT_MAX_CHARS = 12_000

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def build_prompt(
    document: Document,
    fields: Sequence[str],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    instructions: str = "",
) -> str:
    """Build a strict-JSON extraction prompt for one document."""
    text = document.text[:max_chars]
    truncated = len(document.text) > max_chars
    field_list = ", ".join(fields) if fields else "any salient fields"

    lines = [
        "You extract structured data from unstructured documents.",
        "",
        f"Return ONLY a JSON object with these keys: {field_list}.",
        "Rules:",
        "- Use null for any field you cannot determine from the text.",
        "- Do not invent values, and do not add commentary outside the JSON.",
        "- Preserve values verbatim; do not translate or reformat them.",
    ]
    if instructions:
        lines.extend(["", f"Additional instructions: {instructions}"])
    lines.extend(
        [
            "",
            f"Source file: {document.source.name}",
            f"Media type: {document.source.media_type}",
        ]
    )
    if truncated:
        lines.append(f"Note: the text below is truncated to {max_chars} characters.")
    lines.extend(["", "--- BEGIN DOCUMENT ---", text, "--- END DOCUMENT ---"])
    return "\n".join(lines)


def parse_json_response(raw: str) -> dict[str, Any]:
    """Parse a model response into a dict, tolerating code fences and prose."""
    cleaned = _FENCE_RE.sub("", raw.strip())
    if not cleaned:
        raise ExtractError("model returned an empty response")
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ExtractError(
                f"model response contained no JSON object: {cleaned[:200]!r}"
            ) from None
        try:
            payload = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ExtractError(f"could not parse model JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ExtractError(f"expected a JSON object, got {type(payload).__name__}")
    return payload


class LlmExtractor(Extractor):
    """Extract fields using a caller-supplied language model.

    Args:
        complete: callable mapping a prompt to raw model text.
        fields: field names the model should return.
        name: registry name, so several configured instances can coexist.
        max_chars: document character budget per call.
        confidence: confidence recorded for values from this extractor. Keep it
            below deterministic extractors so provenance stays meaningful.
        instructions: extra domain guidance appended to the prompt.
    """

    def __init__(
        self,
        complete: CompletionFn,
        fields: Sequence[str],
        *,
        name: str = "llm",
        max_chars: int = DEFAULT_MAX_CHARS,
        confidence: float = 0.6,
        instructions: str = "",
    ) -> None:
        if not callable(complete):
            raise ExtractError("'complete' must be callable")
        if not fields:
            raise ExtractError("at least one target field is required")
        self.complete = complete
        self.name = name
        self.fields = tuple(fields)
        self.max_chars = max_chars
        self.confidence = confidence
        self.instructions = instructions

    def extract(self, document: Document) -> ExtractionResult | None:
        if not document.text.strip():
            return None

        prompt = build_prompt(
            document,
            self.fields,
            max_chars=self.max_chars,
            instructions=self.instructions,
        )
        try:
            raw = self.complete(prompt)
        except Exception as exc:  # noqa: BLE001 - provider errors are opaque
            raise ExtractError(f"completion call failed: {exc}") from exc

        payload = parse_json_response(raw)
        fields = {
            key: payload.get(key)
            for key in self.fields
            if key in payload and payload.get(key) is not None
        }
        if not fields:
            return None
        fields["llm_fields_returned"] = len(fields)
        return ExtractionResult(
            extractor=self.name, fields=fields, confidence=self.confidence
        )
