# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

<#
    .SYNOPSIS
    Validates the manually-provisioned Microsoft Fabric deployment for the FinOps OneLake pilot.

    .DESCRIPTION
    Test-PilotDeployment is the fail-loud preflight gate for the pilot's manual deployment path (Decision 3).
    It loads the customer-supplied parameters file, validates every value against the deployment parameter
    contract (deploy-parameters.schema.json), and confirms the values are internally consistent (for example,
    that the Lakehouse name embedded in the OneLake endpoint matches the declared Lakehouse name).

    The command is idempotent and safe to re-run: it performs read-only validation and emits a resolved,
    normalized parameter object. It throws a terminating error on the first hard-fail so a broken manual setup
    stops the pipeline instead of silently degrading a later notebook run.

    Live connectivity checks against Fabric are intentionally optional (-TestConnectivity) so the preflight can
    run in CI or offline. The structural and consistency checks always run.

    .PARAMETER ParametersPath
    Required. Path to the JSON parameters file produced after manually creating the Fabric workspace and Lakehouse.

    .PARAMETER SchemaPath
    Optional. Path to the deployment parameter contract. Defaults to deploy-parameters.schema.json next to this script.

    .PARAMETER TestConnectivity
    Optional. When set, attempts a lightweight reachability check against the OneLake and SQL endpoints. Requires
    network access and an authenticated context. Off by default so the preflight is usable in CI.

    .EXAMPLE
    Test-PilotDeployment -ParametersPath ./my-deployment.json

    Validates the parameters file structurally and for internal consistency, returning the resolved parameters.

    .EXAMPLE
    Test-PilotDeployment -ParametersPath ./my-deployment.json -TestConnectivity

    Also attempts to reach the OneLake and SQL endpoints.

    .OUTPUTS
    System.Collections.Hashtable. The resolved, normalized parameters when validation succeeds.
#>
function Test-PilotDeployment
{
    [CmdletBinding()]
    [OutputType([hashtable])]
    param
    (
        [Parameter(Mandatory = $true)]
        [string]
        $ParametersPath,

        [Parameter(Mandatory = $false)]
        [string]
        $SchemaPath = (Join-Path -Path $PSScriptRoot -ChildPath 'deploy-parameters.schema.json'),

        [Parameter(Mandatory = $false)]
        [switch]
        $TestConnectivity
    )

    if (-not (Test-Path -Path $ParametersPath))
    {
        throw "Parameters file not found: $ParametersPath"
    }

    if (-not (Test-Path -Path $SchemaPath))
    {
        throw "Schema contract not found: $SchemaPath"
    }

    $schema = Get-Content -Path $SchemaPath -Raw | ConvertFrom-Json

    try
    {
        $params = Get-Content -Path $ParametersPath -Raw | ConvertFrom-Json
    }
    catch
    {
        throw "Parameters file is not valid JSON: $($_.Exception.Message)"
    }

    # --- Required properties -------------------------------------------------
    foreach ($required in $schema.required)
    {
        $value = $params.$required
        if ($null -eq $value -or ([string]::IsNullOrWhiteSpace([string]$value)))
        {
            throw "Required parameter '$required' is missing or empty."
        }
    }

    # --- Reject unknown properties (additionalProperties: false) -------------
    if (-not $schema.additionalProperties)
    {
        $known = $schema.properties.PSObject.Properties.Name
        foreach ($prop in $params.PSObject.Properties.Name)
        {
            if ($known -notcontains $prop)
            {
                throw "Unknown parameter '$prop' is not allowed by the contract."
            }
        }
    }

    # --- Per-property pattern / enum validation ------------------------------
    foreach ($prop in $params.PSObject.Properties.Name)
    {
        $rule = $schema.properties.$prop
        if ($null -eq $rule)
        {
            continue
        }

        $value = [string]$params.$prop

        if ($rule.pattern -and $value -notmatch $rule.pattern)
        {
            throw "Parameter '$prop' value '$value' does not match the required format."
        }

        if ($rule.enum -and $rule.enum -notcontains $value)
        {
            throw "Parameter '$prop' value '$value' is not one of: $($rule.enum -join ', ')."
        }

        if ($rule.maxLength -and $value.Length -gt $rule.maxLength)
        {
            throw "Parameter '$prop' exceeds maximum length of $($rule.maxLength)."
        }
    }

    # --- Cross-field consistency: OneLake endpoint must reference the lakehouse
    # Form: abfss://{workspace}@onelake.dfs.fabric.microsoft.com/{lakehouse}.Lakehouse[/...]
    if ($params.oneLakeEndpoint -match '/([^/]+)\.Lakehouse(?:/|$)')
    {
        $endpointLakehouse = $Matches[1]
        if ($endpointLakehouse -ne $params.lakehouseName)
        {
            throw "Inconsistent parameters: OneLake endpoint references Lakehouse '$endpointLakehouse' but lakehouseName is '$($params.lakehouseName)'."
        }
    }
    else
    {
        throw "OneLake endpoint does not contain a '{lakehouse}.Lakehouse' segment: $($params.oneLakeEndpoint)"
    }

    # --- Guard against a blob endpoint being supplied instead of OneLake DFS --
    if ($params.oneLakeEndpoint -match 'blob\.core\.windows\.net')
    {
        throw "OneLake endpoint must be the OneLake DFS endpoint, not a blob endpoint."
    }

    # --- Optional live connectivity ------------------------------------------
    if ($TestConnectivity)
    {
        Test-PilotEndpointReachability -OneLakeEndpoint $params.oneLakeEndpoint -SqlEndpoint $params.sqlEndpoint
    }

    # --- Resolved, normalized output -----------------------------------------
    $resolved = @{
        workspaceName   = $params.workspaceName
        lakehouseName   = $params.lakehouseName
        oneLakeEndpoint = $params.oneLakeEndpoint.TrimEnd('/')
        sqlEndpoint     = $params.sqlEndpoint
        capacityId      = $params.capacityId
        environment     = if ($params.environment) { $params.environment } else { 'pilot' }
    }

    Write-Verbose "Preflight validation succeeded for workspace '$($resolved.workspaceName)'."
    return $resolved
}

<#
    .SYNOPSIS
    Performs a lightweight reachability check against the OneLake and SQL endpoints.

    .DESCRIPTION
    Test-PilotEndpointReachability resolves the endpoint hosts to confirm they are reachable from the current
    network. It does not authenticate or read data; it is a connectivity smoke test only. Throws on failure.

    .PARAMETER OneLakeEndpoint
    Required. The ABFSS OneLake endpoint to check.

    .PARAMETER SqlEndpoint
    Required. The Fabric SQL analytics endpoint host to check.
#>
function Test-PilotEndpointReachability
{
    [CmdletBinding()]
    param
    (
        [Parameter(Mandatory = $true)]
        [string]
        $OneLakeEndpoint,

        [Parameter(Mandatory = $true)]
        [string]
        $SqlEndpoint
    )

    # Derive the OneLake host from the supplied endpoint so a malformed value fails the smoke test
    # rather than silently resolving a hardcoded host. Format: abfss://{workspace}@{host}/{lakehouse}.Lakehouse
    if ($OneLakeEndpoint -match '@([^/]+)')
    {
        $oneLakeHost = $Matches[1]
    }
    else
    {
        throw "OneLakeEndpoint '$OneLakeEndpoint' is missing the '@{host}' segment; cannot determine the host to resolve."
    }

    foreach ($targetHost in @($oneLakeHost, $SqlEndpoint))
    {
        try
        {
            $null = [System.Net.Dns]::GetHostEntry($targetHost)
            Write-Verbose "Resolved host: $targetHost"
        }
        catch
        {
            throw "Endpoint host '$targetHost' could not be resolved. Check the value and network egress."
        }
    }
}
