// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.
//
// ftk_FabricSql - connection-swap data source for the FinOps OneLake pilot (Decision 4).
//
// Power BI connects to the Fabric SQL analytics endpoint FIRST, before any DirectLake
// upgrade. This query is the drop-in replacement for ftk_Storage("focuscost"): it returns
// the same FOCUS-shaped Costs table so every downstream visual, measure, and relationship
// in the existing report is reused verbatim. Only the data acquisition changes.
//
// The Delta table read here is already FOCUS-normalized by the toolkit's KQL transform
// (which remains the single transform owner), so no schema fix-up is needed on the client.
//
// Connection mode is DirectQuery: immediate value, works with any license, and is insensitive
// to file layout. The DirectLake upgrade is gated separately by the readiness notebook (D4) and
// is not assumed here.
//
// Parameters consumed (defined as report parameters):
//   #"SQL Endpoint"     - host of the Fabric SQL analytics endpoint (….datawarehouse.fabric.microsoft.com)
//   #"SQL Database"     - Lakehouse (database) name on that endpoint
//   #"Number of Months" - lookback window (null = all)
//   RangeStart/RangeEnd - optional explicit date bounds
(optional datasetType as text) =>
let
    // Map the toolkit dataset alias to its Delta table name.
    data = if datasetType <> null and datasetType <> "" then Text.Lower(datasetType) else "focuscost",
    tableName =
        if data = "focuscost" then "Costs"
        else if data = "pricesheet" then "Prices"
        else if data = "reservationdetails" then "CommitmentDiscountUsage"
        else if data = "reservationrecommendations" then "Recommendations"
        else if data = "reservationtransactions" then "Transactions"
        else "Costs",

    // Resolve the date window the same way the storage variant does.
    end = if RangeEnd <> null then Date.From(RangeEnd, Culture.Current) else null,
    start =
        if RangeStart <> null then Date.From(RangeStart, Culture.Current)
        else if #"Number of Months" <> null and #"Number of Months" > 0
            then Date.AddMonths(if end <> null then end else Date.StartOfMonth(Date.From(DateTime.LocalNow())), -#"Number of Months")
        else null,

    // Connect to the Fabric SQL analytics endpoint (DirectQuery-foldable).
    Database = Sql.Database(#"SQL Endpoint", #"SQL Database"),
    Source = Database{[Schema = "dbo", Item = tableName]}[Data],

    // Filter to the requested charge-period window. Folds to the SQL endpoint.
    Filtered =
        if start = null and end = null then Source
        else Table.SelectRows(
            Source,
            each (start = null or [ChargePeriodStart] = null or [ChargePeriodStart] >= start)
                and (end = null or [ChargePeriodStart] = null or [ChargePeriodStart] < Date.EndOfMonth(end))
        )
in
    Filtered
