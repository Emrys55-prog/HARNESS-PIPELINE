import json
import re
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]

FIELD_CACHE = PROJECT_ROOT / "data" / "field_cache" / "fields_USA_TOP3000_d1.json"

NUMERIC_TYPES = {"MATRIX", "VECTOR"}

SPECIAL_SCALARS = {
    "cap",
    "returns",
    "close",
    "open",
    "high",
    "low",
    "volume",
    "vwap",
    "adv20",
}


def load_field_metadata() -> dict[str, dict[str, Any]]:
    if not FIELD_CACHE.exists():
        return {}

    rows = json.loads(
        FIELD_CACHE.read_text(encoding="utf-8")
    )

    return {
        str(row.get("id")): row
        for row in rows
        if row.get("id")
    }


def field_type(field: str, metadata: dict[str, dict[str, Any]] | None = None) -> str:
    metadata = metadata or load_field_metadata()

    if field in SPECIAL_SCALARS:
        return "SPECIAL"

    return str(
        (metadata.get(field) or {}).get("type") or "UNKNOWN"
    ).upper()


def is_numeric_field(field: str, metadata: dict[str, dict[str, Any]] | None = None) -> bool:
    return (
        field_type(field, metadata) in NUMERIC_TYPES
        or field in SPECIAL_SCALARS
    )


def operand(field: str, metadata: dict[str, dict[str, Any]] | None = None) -> str:
    """
    VECTOR -> vec_avg(field)
    MATRIX/SPECIAL -> field unchanged
    """

    metadata = metadata or load_field_metadata()

    if field_type(field, metadata) == "VECTOR":
        return f"vec_avg({field})"

    return field


def numeric_fields(metadata: dict[str, dict[str, Any]] | None = None) -> list[str]:
    metadata = metadata or load_field_metadata()

    return [
        field_id
        for field_id, row in metadata.items()
        if str(row.get("type", "")).upper() in NUMERIC_TYPES
    ]


def normalize_expression(expression: str, metadata: dict[str, dict[str, Any]] | None = None) -> str:
    """
    Automatically wrap bare VECTOR fields with vec_avg(...).

    Example:

        ts_rank(vector_field, 20)

    becomes:

        ts_rank(vec_avg(vector_field), 20)
    """

    metadata = metadata or load_field_metadata()

    vector_fields = sorted(
        [
            field_id
            for field_id, row in metadata.items()
            if str(row.get("type", "")).upper() == "VECTOR"
        ],
        key=len,
        reverse=True,
    )

    result = expression

    for field in vector_fields:

        pattern = re.compile(
            r"(?<![A-Za-z0-9_])"
            + re.escape(field)
            + r"(?![A-Za-z0-9_])"
        )

        def replacement(match: re.Match[str]) -> str:
            start = match.start()

            before = result[:start]

            # Already wrapped in vec_avg(...)
            if re.search(r"vec_avg\(\s*$", before):
                return field

            return f"vec_avg({field})"

        result = pattern.sub(replacement, result)

    return result


def validate_fields(expression: str, metadata: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """
    Return identifiers that look like fields but are not present
    in the metadata cache.
    """

    metadata = metadata or load_field_metadata()

    identifiers = set(
        re.findall(
            r"\b[A-Za-z_][A-Za-z0-9_]*\b",
            expression,
        )
    )

    functions = set(
        re.findall(
            r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(",
            expression,
        )
    )

    ignored = functions | {
        "subindustry",
        "industry",
        "sector",
        "market",
    } | SPECIAL_SCALARS

    return sorted(
        identifier
        for identifier in identifiers
        if identifier not in ignored
        and identifier not in metadata
    )
