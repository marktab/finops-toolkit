"""Bridge between Spark/Delta physical type names and the contract logical types.

Used by the ingestion notebook to translate an observed Spark DataFrame schema
into the {column: logical_type} mapping that the D1 contract validator checks,
and by the readiness gate to confirm no DirectLake-incompatible complex types
are present.
"""

from __future__ import annotations

import json
from pathlib import Path
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

    Complex/nested types need consumer-specific handling; the pilot keeps
    everything flat. This is not model eligibility or fallback validation.
    """
    offenders = []
    for name, stype in fields.items():
        base = stype.strip().lower()
        if base.startswith(DIRECTLAKE_UNSUPPORTED_PREFIXES):
            offenders.append(name)
    return offenders


_CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


def numeric_storage_types(
    schema_contract_path: str | Path = _CONTRACTS / "focus-schema.contract.json",
    storage_contract_path: str | Path = _CONTRACTS / "storage-layout.contract.json",
) -> dict[str, str]:
    """Resolve numeric fields from pinned canonical metadata, not a cost list."""
    from contract_validator import load_schema_contract, resolve_column_source

    contract = load_schema_contract(schema_contract_path)
    source = resolve_column_source(schema_contract_path, contract)
    storage = json.loads(Path(storage_contract_path).read_text(encoding="utf-8"))
    result = {}
    for column in source["Columns"]:
        logical = contract["typeMapping"][column[contract["columnSource"]["dataTypeField"]]]
        if logical in ("decimal", "double"):
            result[column[contract["columnSource"]["columnNameField"]]] = (
                storage["physicalTypeMapping"][logical]["deltaType"]
            )
    return result


def validate_numeric_target(
    fields: Mapping[str, str],
    schema_contract_path: str | Path = _CONTRACTS / "focus-schema.contract.json",
    storage_contract_path: str | Path = _CONTRACTS / "storage-layout.contract.json",
    *,
    case_sensitive: bool = True,
) -> None:
    from contract_validator import ContractViolation

    expected = numeric_storage_types(schema_contract_path, storage_contract_path)
    if not case_sensitive:
        expected = {name.lower(): dtype for name, dtype in expected.items()}
    mismatches = []
    for name, actual in fields.items():
        key = name if case_sensitive else name.lower()
        if key in expected and actual != expected[key]:
            mismatches.append(f"{name}: expected {expected[key]}, got {actual}")
    if mismatches:
        raise ContractViolation(
            "Incompatible existing Costs numeric schema: " + "; ".join(mismatches)
            + ". Use a new isolated table or an explicitly approved migration; "
            "automatic destructive conversion is not supported."
        )


def prepare_numeric_frame(
    df,
    schema_contract_path: str | Path = _CONTRACTS / "focus-schema.contract.json",
    storage_contract_path: str | Path = _CONTRACTS / "storage-layout.contract.json",
):
    """Validate values before conversion; preserve nulls and reject rounding."""
    from contract_validator import ContractViolation
    from pyspark.sql import functions as F

    targets = numeric_storage_types(schema_contract_path, storage_contract_path)
    expressions = []
    checks = []
    for field in df.schema:
        name, source_type = field.name, field.dataType.simpleString()
        quoted = "`" + name.replace("`", "``") + "`"
        value = F.col(quoted)
        target = targets.get(name)
        if target is None:
            expressions.append(value)
            continue
        if target.startswith("decimal("):
            if not source_type.startswith("decimal("):
                raise ContractViolation(
                    f"{name}: expected decimal input for exact {target} storage, got {source_type}."
                )
            converted = F.expr(f"try_cast({quoted} AS {target})")
            restored = F.expr(f"try_cast(try_cast({quoted} AS {target}) AS {source_type})")
            invalid = value.isNotNull() & (converted.isNull() | ~restored.eqNullSafe(value))
        else:
            if source_type not in ("double", "float"):
                raise ContractViolation(f"{name}: expected floating-point input, got {source_type}.")
            converted = value.cast(target)
            invalid = value.isNotNull() & (
                F.isnan(converted) | (F.abs(converted) == F.lit(float("inf")))
            )
        checks.append(F.max(invalid.cast("int")).alias(name))
        expressions.append(converted.alias(name))
    if checks:
        invalid_fields = [
            name for name, invalid in df.agg(*checks).first().asDict().items() if invalid
        ]
        if invalid_fields:
            raise ContractViolation(
                "Numeric overflow, rounding, or non-finite value in: "
                + ", ".join(sorted(invalid_fields))
                + ". Exact decimal conversion requires <=20 integer and <=18 fractional digits."
            )
    return df.select(*expressions)
