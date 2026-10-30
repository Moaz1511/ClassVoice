"""Shared generation-text limits and Unicode safety checks."""

from __future__ import annotations

import unicodedata

MAX_GENERATION_TEXT_CHARACTERS = 10_000
_ALLOWED_CONTROL_CHARACTERS = frozenset({"\t", "\n", "\r"})


class GenerationTextValidationError(ValueError):
    """Text cannot be represented safely by the API, database, or worker."""


def normalize_generation_text(value: str) -> str:
    """Trim outer whitespace and reject unsafe or unencodable Unicode text."""

    text = value.strip()
    if not 1 <= len(text) <= MAX_GENERATION_TEXT_CHARACTERS:
        raise GenerationTextValidationError(
            "Text must be between 1 and 10,000 Unicode code points."
        )
    for character in text:
        category = unicodedata.category(character)
        if category == "Cs" or (
            category == "Cc" and character not in _ALLOWED_CONTROL_CHARACTERS
        ):
            raise GenerationTextValidationError("Text contains an unsafe control character.")
    try:
        text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise GenerationTextValidationError("Text is not valid UTF-8 Unicode.") from error
    return text
