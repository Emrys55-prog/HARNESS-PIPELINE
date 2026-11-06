"""Central interface for WorldQuant BRAIN field metadata."""

from dataclasses import dataclass, field
from typing import Any

from .field_rules import (
    load_field_metadata,
    numeric_fields,
    field_type,
    is_numeric_field,
    operand,
    normalize_expression,
    validate_fields,
)


@dataclass
class FieldCatalog:
    """Loads and provides access to cached BRAIN field metadata."""

    metadata: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "FieldCatalog":
        metadata = load_field_metadata()

        if not metadata:
            raise RuntimeError(
                "Field metadata cache is missing or empty."
            )

        return cls(metadata=metadata)

    @property
    def total_fields(self) -> int:
        return len(self.metadata)

    @property
    def total_numeric_fields(self) -> int:
        return len(numeric_fields(self.metadata))

    def get(self, field_id: str) -> dict[str, Any] | None:
        return self.metadata.get(field_id)

    def exists(self, field_id: str) -> bool:
        return field_id in self.metadata

    def get_type(self, field_id: str) -> str:
        return field_type(field_id, self.metadata)

    def is_numeric(self, field_id: str) -> bool:
        return is_numeric_field(field_id, self.metadata)

    def prepare_operand(self, field_id: str) -> str:
        return operand(field_id, self.metadata)

    def normalize(self, expression: str) -> str:
        return normalize_expression(expression, self.metadata)

    def validate(self, expression: str) -> list[str]:
        return validate_fields(expression, self.metadata)

    def list_numeric_fields(self) -> list[str]:
        return numeric_fields(self.metadata)
