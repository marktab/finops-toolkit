# Fabric notebook source
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

# MARKDOWN ********************

# # 00 - Generate sample FOCUS 1.2 data (pilot test helper)
#
# Creates a small synthetic FOCUS 1.2-compliant parquet file in
# `Files/sample-focus/` so notebook 01 has something to validate.
# Run this ONCE before the main pilot sequence; then delete or ignore it.
#
# **After running:** copy the printed `source_path` value into notebook 01's
# parameters cell.

# CELL ********************

import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from pyspark.sql import Row
from pyspark.sql import types as T

# ---------------------------------------------------------------------------
# Configuration — change MONTH to the period you want to simulate
# ---------------------------------------------------------------------------
MONTH = date(2025, 5, 1)          # billing/charge month
ROW_COUNT = 500                   # keep small for a trial capacity
OUTPUT_PATH = "Files/sample-focus"

# ABFSS root of your Lakehouse. Writing via ABFSS (instead of the local
# /lakehouse/default mount) is the reliable path on tenants where the local
# mount does not resolve — notably Microsoft-internal (msit) capacities.
#
# REQUIRED: copy the authoritative value from your Lakehouse > Properties ABFSS
# path. The host segment differs by cloud:
#   Commercial        : abfss://<ws>@onelake.dfs.fabric.microsoft.com/<lh>.Lakehouse
#   Microsoft (msit)  : abfss://<ws>@msit-onelake.dfs.fabric.microsoft.com/<lh>.Lakehouse
#   Sovereign clouds  : abfss://<ws>@<your-cloud-onelake-host>/<lh>.Lakehouse
ABFSS_ROOT = ""
# ---------------------------------------------------------------------------

if not ABFSS_ROOT:
    raise ValueError(
        "Set ABFSS_ROOT to your Lakehouse ABFSS path (Lakehouse > Properties) before running."
    )

random.seed(42)

SERVICES = [
    ("Compute", "Virtual Machines"),
    ("Compute", "Azure Kubernetes Service"),
    ("Storage", "Azure Blob Storage"),
    ("Storage", "Azure Files"),
    ("Networking", "Azure Virtual Network"),
    ("Networking", "Azure Load Balancer"),
    ("Databases", "Azure SQL Database"),
    ("Databases", "Azure Cosmos DB"),
    ("AI + Machine Learning", "Azure OpenAI"),
    ("Management", "Azure Monitor"),
]

CHARGE_CATEGORIES = ["Usage", "Purchase", "Tax", "Credit", "Adjustment"]
SUBSCRIPTION_IDS = [
    "11111111-aaaa-bbbb-cccc-000000000001",
    "22222222-aaaa-bbbb-cccc-000000000002",
]

period_start = datetime(MONTH.year, MONTH.month, 1, tzinfo=timezone.utc)
# Last day of the month
next_month = (MONTH.replace(day=28) + timedelta(days=4)).replace(day=1)
period_end = datetime(next_month.year, next_month.month, 1, tzinfo=timezone.utc)

rows = []
for i in range(ROW_COUNT):
    svc_cat, svc_name = random.choice(SERVICES)
    charge_cat = random.choices(CHARGE_CATEGORIES, weights=[70, 10, 5, 10, 5])[0]
    list_cost = Decimal(str(round(random.uniform(0.01, 500.0), 10)))
    contracted = Decimal(str(round(float(list_cost) * random.uniform(0.7, 1.0), 10)))
    effective = Decimal(str(round(float(contracted) * random.uniform(0.8, 1.0), 10)))
    billed = effective

    # Charge period: random day within the month
    day_offset = random.randint(0, (period_end - period_start).days - 1)
    charge_start = period_start + timedelta(days=day_offset)
    charge_end = charge_start + timedelta(hours=random.randint(1, 24))

    sub_id = random.choice(SUBSCRIPTION_IDS)
    rows.append(Row(
        BilledCost=billed,
        BillingAccountId="billing-account-001",
        BillingAccountName="FinOps Pilot Billing Account",
        BillingAccountType="Enterprise Agreement",
        BillingCurrency="USD",
        BillingPeriodEnd=period_end,
        BillingPeriodStart=period_start,
        ChargeCategory=charge_cat,
        ChargeDescription=f"{svc_name} - {charge_cat} charge {i:04d}",
        ChargePeriodEnd=charge_end,
        ChargePeriodStart=charge_start,
        ContractedCost=contracted,
        EffectiveCost=effective,
        ListCost=list_cost,
        ProviderName="Microsoft",
        PublisherName="Microsoft",
        RegionId=random.choice(["eastus", "westus2", "westeurope"]),
        RegionName=random.choice(["East US", "West US 2", "West Europe"]),
        ResourceId=f"/subscriptions/{sub_id}/resourceGroups/rg-pilot/providers/Microsoft.Compute/resource{i:04d}",
        ResourceName=f"resource{i:04d}",
        ServiceCategory=svc_cat,
        ServiceName=svc_name,
        SubAccountId=sub_id,
        SubAccountName=f"Subscription {sub_id[:8]}",
        Tags='{"environment":"pilot","costCenter":"12345"}',
    ))

schema = T.StructType([
    T.StructField("BilledCost",           T.DecimalType(19, 10), nullable=False),
    T.StructField("BillingAccountId",     T.StringType(),        nullable=False),
    T.StructField("BillingAccountName",   T.StringType(),        nullable=True),
    T.StructField("BillingAccountType",   T.StringType(),        nullable=True),
    T.StructField("BillingCurrency",      T.StringType(),        nullable=False),
    T.StructField("BillingPeriodEnd",     T.TimestampType(),     nullable=False),
    T.StructField("BillingPeriodStart",   T.TimestampType(),     nullable=False),
    T.StructField("ChargeCategory",       T.StringType(),        nullable=False),
    T.StructField("ChargeDescription",    T.StringType(),        nullable=True),
    T.StructField("ChargePeriodEnd",      T.TimestampType(),     nullable=False),
    T.StructField("ChargePeriodStart",    T.TimestampType(),     nullable=False),
    T.StructField("ContractedCost",       T.DecimalType(19, 10), nullable=False),
    T.StructField("EffectiveCost",        T.DecimalType(19, 10), nullable=False),
    T.StructField("ListCost",             T.DecimalType(19, 10), nullable=False),
    T.StructField("ProviderName",         T.StringType(),        nullable=False),
    T.StructField("PublisherName",        T.StringType(),        nullable=True),
    T.StructField("RegionId",             T.StringType(),        nullable=True),
    T.StructField("RegionName",           T.StringType(),        nullable=True),
    T.StructField("ResourceId",           T.StringType(),        nullable=True),
    T.StructField("ResourceName",         T.StringType(),        nullable=True),
    T.StructField("ServiceCategory",      T.StringType(),        nullable=True),
    T.StructField("ServiceName",          T.StringType(),        nullable=False),
    T.StructField("SubAccountId",         T.StringType(),        nullable=True),
    T.StructField("SubAccountName",       T.StringType(),        nullable=True),
    T.StructField("Tags",                 T.StringType(),        nullable=True),
])

df = spark.createDataFrame(rows, schema=schema)

# CELL ********************

out = f"{ABFSS_ROOT}/{OUTPUT_PATH}"
df.write.mode("overwrite").parquet(out)

print(f"Written {df.count()} rows.")
print()
print("Copy this value into notebook 01's source_path parameter:")
print()
print(f'source_path = "{ABFSS_ROOT}/{OUTPUT_PATH}"')
