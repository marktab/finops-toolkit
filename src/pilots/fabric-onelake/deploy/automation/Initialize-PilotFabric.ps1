# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

<#
    .SYNOPSIS
    Provisions the Microsoft Fabric workspace and Lakehouse for the FinOps OneLake pilot via the Fabric REST API.

    .DESCRIPTION
    Initialize-PilotFabric is the OPTIONAL automation layer that sits on top of the proven manual deployment
    path (Decision 3). It is built only after the manual path works end-to-end, so it is a convenience over a
    known-good path rather than a single point of failure.

    The command is idempotent and re-runnable: it gets-or-creates the workspace and Lakehouse (never duplicating
    an existing one), resolves the OneLake and SQL endpoints, writes the deployment parameters file, and then
    runs the same fail-loud preflight (Test-PilotDeployment) the manual path uses. Every create is gated behind
    ShouldProcess so -WhatIf shows exactly what would change.

    Authentication uses the caller's current context. Supply an access token for the Fabric API
    (https://api.fabric.microsoft.com) via -AccessToken, or pipe one from Get-AzAccessToken.

    .PARAMETER WorkspaceName
    Required. Display name of the Fabric workspace to get-or-create.

    .PARAMETER LakehouseName
    Required. Name of the Lakehouse to get-or-create in the workspace.

    .PARAMETER CapacityId
    Optional. Fabric capacity object id to assign to a newly-created workspace.

    .PARAMETER AccessToken
    Required. Bearer token for https://api.fabric.microsoft.com. Obtain via:
    (Get-AzAccessToken -ResourceUrl 'https://api.fabric.microsoft.com').Token

    .PARAMETER ParametersPath
    Optional. Path to write the resolved deployment parameters file. Default: ./deploy-parameters.generated.json.

    .PARAMETER ApiBaseUrl
    Optional. Fabric REST API base URL. Default: https://api.fabric.microsoft.com/v1.

    .EXAMPLE
    $token = (Get-AzAccessToken -ResourceUrl 'https://api.fabric.microsoft.com').Token
    Initialize-PilotFabric -WorkspaceName 'FinOps Pilot' -LakehouseName 'FinOpsHub' -CapacityId $cap -AccessToken $token

    Gets-or-creates the workspace and Lakehouse, then writes and validates the parameters file.

    .EXAMPLE
    Initialize-PilotFabric -WorkspaceName 'FinOps Pilot' -LakehouseName 'FinOpsHub' -AccessToken $token -WhatIf

    Shows what would be created without making changes.

    .OUTPUTS
    System.Collections.Hashtable. The resolved, validated deployment parameters.
#>
function Initialize-PilotFabric
{
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
    [OutputType([hashtable])]
    param
    (
        [Parameter(Mandatory = $true)]
        [string]
        $WorkspaceName,

        [Parameter(Mandatory = $true)]
        [string]
        $LakehouseName,

        [Parameter(Mandatory = $false)]
        [string]
        $CapacityId,

        [Parameter(Mandatory = $true)]
        [string]
        $AccessToken,

        [Parameter(Mandatory = $false)]
        [string]
        $ParametersPath = (Join-Path -Path $PSScriptRoot -ChildPath 'deploy-parameters.generated.json'),

        [Parameter(Mandatory = $false)]
        [string]
        $ApiBaseUrl = 'https://api.fabric.microsoft.com/v1'
    )

    $headers = @{
        Authorization = "Bearer $AccessToken"
        'Content-Type' = 'application/json'
    }

    # --- Workspace: get-or-create ------------------------------------------------
    $workspace = Get-PilotFabricItem -Uri "$ApiBaseUrl/workspaces" -Headers $headers -DisplayName $WorkspaceName
    if (-not $workspace)
    {
        if ($PSCmdlet.ShouldProcess($WorkspaceName, 'Create Fabric workspace'))
        {
            $body = @{ displayName = $WorkspaceName }
            if ($CapacityId) { $body.capacityId = $CapacityId }
            $workspace = Invoke-RestMethod -Method Post -Uri "$ApiBaseUrl/workspaces" -Headers $headers -Body ($body | ConvertTo-Json)
            Write-Verbose "Created workspace '$WorkspaceName' ($($workspace.id))."
        }
    }
    else
    {
        Write-Verbose "Workspace '$WorkspaceName' already exists ($($workspace.id)); reusing."
    }

    if (-not $workspace)
    {
        # -WhatIf path: nothing was created, so stop before dependent calls.
        Write-Warning 'Workspace was not created (WhatIf). Skipping Lakehouse and validation.'
        return
    }

    $workspaceId = $workspace.id

    # --- Lakehouse: get-or-create -----------------------------------------------
    $lakehouse = Get-PilotFabricItem -Uri "$ApiBaseUrl/workspaces/$workspaceId/lakehouses" -Headers $headers -DisplayName $LakehouseName
    if (-not $lakehouse)
    {
        if ($PSCmdlet.ShouldProcess($LakehouseName, 'Create Fabric Lakehouse'))
        {
            $body = @{ displayName = $LakehouseName } | ConvertTo-Json
            $lakehouse = Invoke-RestMethod -Method Post -Uri "$ApiBaseUrl/workspaces/$workspaceId/lakehouses" -Headers $headers -Body $body
            Write-Verbose "Created Lakehouse '$LakehouseName' ($($lakehouse.id))."
        }
    }
    else
    {
        Write-Verbose "Lakehouse '$LakehouseName' already exists ($($lakehouse.id)); reusing."
    }

    if (-not $lakehouse)
    {
        Write-Warning 'Lakehouse was not created (WhatIf). Skipping validation.'
        return
    }

    # --- Resolve endpoints -------------------------------------------------------
    # OneLake ABFSS path is deterministic from workspace + lakehouse names.
    $oneLakeEndpoint = "abfss://$WorkspaceName@onelake.dfs.fabric.microsoft.com/$LakehouseName.Lakehouse"

    # SQL endpoint comes from the Lakehouse properties (may take a moment to provision).
    $sqlEndpoint = $lakehouse.properties.sqlEndpointProperties.connectionString
    if (-not $sqlEndpoint)
    {
        $detail = Invoke-RestMethod -Method Get -Uri "$ApiBaseUrl/workspaces/$workspaceId/lakehouses/$($lakehouse.id)" -Headers $headers
        $sqlEndpoint = $detail.properties.sqlEndpointProperties.connectionString
    }
    if (-not $sqlEndpoint)
    {
        throw "SQL analytics endpoint is not yet available for Lakehouse '$LakehouseName'. Re-run after provisioning completes."
    }

    # --- Write parameters file ---------------------------------------------------
    $params = [ordered]@{
        workspaceName   = $WorkspaceName
        lakehouseName   = $LakehouseName
        oneLakeEndpoint = $oneLakeEndpoint
        sqlEndpoint     = $sqlEndpoint
        capacityId      = $CapacityId
        environment     = 'pilot'
    }

    if ($PSCmdlet.ShouldProcess($ParametersPath, 'Write deployment parameters file'))
    {
        $params | ConvertTo-Json | Set-Content -Path $ParametersPath -Encoding utf8
        Write-Verbose "Wrote parameters to $ParametersPath."
    }

    # --- Validate via the same fail-loud preflight the manual path uses ---------
    . (Join-Path -Path $PSScriptRoot -ChildPath '..' -AdditionalChildPath @('manual', 'Test-PilotDeployment.ps1'))
    return Test-PilotDeployment -ParametersPath $ParametersPath
}

<#
    .SYNOPSIS
    Returns a Fabric item with the given display name from a list endpoint, or $null if absent.

    .DESCRIPTION
    Get-PilotFabricItem performs the get half of the get-or-create pattern. It enumerates a Fabric REST list
    endpoint (handling continuation tokens) and returns the first item whose displayName matches, enabling
    idempotent provisioning.

    .PARAMETER Uri
    Required. The Fabric REST list endpoint to query.

    .PARAMETER Headers
    Required. Request headers including the bearer token.

    .PARAMETER DisplayName
    Required. The display name to match.
#>
function Get-PilotFabricItem
{
    [CmdletBinding()]
    param
    (
        [Parameter(Mandatory = $true)]
        [string]
        $Uri,

        [Parameter(Mandatory = $true)]
        [hashtable]
        $Headers,

        [Parameter(Mandatory = $true)]
        [string]
        $DisplayName
    )

    $next = $Uri
    while ($next)
    {
        $response = Invoke-RestMethod -Method Get -Uri $next -Headers $Headers
        $match = $response.value | Where-Object { $_.displayName -eq $DisplayName } | Select-Object -First 1
        if ($match)
        {
            return $match
        }

        $next = if ($response.continuationUri) { $response.continuationUri } else { $null }
    }

    return $null
}
