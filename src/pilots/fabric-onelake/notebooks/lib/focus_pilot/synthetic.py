"""Deterministic bounded fixtures; expected totals are computed outside Spark."""

from datetime import datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path

from .schema_bridge import _CONTRACTS


def sample_fixture(schema_contract_path: str | Path = _CONTRACTS / "focus-schema.contract.json"):
    from contract_validator import load_schema_contract, resolve_column_source

    contract = load_schema_contract(schema_contract_path)
    source = resolve_column_source(schema_contract_path, contract)
    types = {
        c["ColumnName"]: contract["typeMapping"][c["DataType"]]
        for c in source["Columns"]
    }
    required = set(contract["requiredColumns"]["columns"])
    fields = sorted(required | {"SubAccountId"} | {
        name for name, dtype in types.items() if dtype in ("decimal", "double")
    })
    rows = []
    expected = {}
    with localcontext() as context:
        context.prec = 50
        for month in (4, 5, 6):
            for scope in ("scope-a", "scope-b"):
                for currency in ("USD", "EUR"):
                    for index, amount in enumerate((
                        Decimal("12.345678901234567890"),
                        Decimal("-0.125"),
                        Decimal("0.000000000000000001"),
                    )):
                        start = datetime(2025, month, 1, tzinfo=timezone.utc)
                        end = datetime(2025, month + 1, 1, tzinfo=timezone.utc)
                        record = {}
                        for name in fields:
                            dtype = types[name]
                            if dtype == "decimal":
                                record[name] = (
                                    None if index == 2 and name not in required else amount
                                )
                            elif dtype == "double":
                                record[name] = 1.5
                            elif dtype == "timestamp":
                                record[name] = end if name.endswith("End") else start
                            elif dtype == "boolean":
                                record[name] = False
                            else:
                                record[name] = "synthetic"
                        record.update(
                            BillingAccountId="account-synthetic",
                            SubAccountId=scope,
                            BillingCurrency=currency,
                            ChargeCategory="Credit" if amount < 0 else "Usage",
                            ChargeDescription=f"{month}-{scope}-{currency}-{index}",
                        )
                        rows.append(record)
                        key = (f"2025-{month:02}", scope, currency)
                        group = expected.setdefault(key, {"rowCount": 0, "totals": {}})
                        group["rowCount"] += 1
                        for name in fields:
                            if types[name] == "decimal" and record[name] is not None:
                                group["totals"][name] = group["totals"].get(name, Decimal(0)) + record[name]
    manifest = [
        {"chargeMonth": key[0], "scope": key[1], "currency": key[2],
         "rowCount": group["rowCount"],
         "totals": {name: str(total) for name, total in group["totals"].items()}}
        for key, group in sorted(expected.items())
    ]
    return rows, {name: types[name] for name in fields}, manifest
