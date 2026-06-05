"""Bridge between Spark/Delta physical type names and the contract logical types.

Used by the ingestion notebook to translate an observed Spark DataFrame schema
into the {column: logical_type} mapping that the D1 contract validator checks,
and by the readiness gate to confirm no DirectLake-incompatible complex types
are present.
"""

from __future__ import annotations

from typing import Mapping

# Maps Spark simpleString type names to the contract's logical types
# (as defined in focus-schema.contract.json typeMapping values).
SPARK_TO_LOGICAL: dict[str, str] = {
    "string": "string",
    "double": "double",
    "float": "double",
    "decimal": "decimal",
    "timestamp": "timestamp",
    "timestamp_ntz": "timestamp",
    "date": "timestamp",
    "boolean": "boolean",
}

# Spark logical type categories that DirectLake does not support well. The pilot
# stores FOCUS Tags (JSON) as a string precisely to avoid these (Decision 4).
DIRECTLAKE_UNSUPPORTED_PREFIXES = ("struct", "array", "map")


def logical_type_for_spark_type(spark_type: str) -> str:
    """Translate a Spark simpleString type name to a contract logical type.

    Decimal types carry precision/scale (e.g. ``decimal(38,18)``); the prefix is
    used for the lookup.

    Raises:
        ValueError: if the Spark type has no known logical mapping.
    """
    normalized = spark_type.strip().lower()
    base = normalized.split("(", 1)[0]
    if base in SPARK_TO_LOGICAL:
        return SPARK_TO_LOGICAL[base]
    raise ValueError(f"Unmapped Spark type '{spark_type}'.")


def spark_schema_to_logical(fields: Mapping[str, str]) -> dict[str, str]:
    """Translate a {column: spark_type} mapping to {column: logical_type}.

    Args:
        fields: Column name to Spark simpleString type (e.g. from
            ``{f.name: f.dataType.simpleString() for f in df.schema}``).

    Raises:
        ValueError: if any column uses an unmapped Spark type.
    """
    return {name: logical_type_for_spark_type(stype) for name, stype in fields.items()}


def find_unsupported_directlake_types(fields: Mapping[str, str]) -> list[str]:
    """Return columns whose Spark type is not DirectLake-friendly.

    Complex/nested types (struct, array, map) fall back to DirectQuery or fail
    in DirectLake; the pilot keeps everything flat.
    """
    offenders = []
    for name, stype in fields.items():
        base = stype.strip().lower()
        if base.startswith(DIRECTLAKE_UNSUPPORTED_PREFIXES):
            offenders.append(name)
    return offenders
