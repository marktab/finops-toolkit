# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

<#
    .SYNOPSIS
    Guides and verifies the manual Microsoft Fabric provisioning for the FinOps OneLake pilot.

    .DESCRIPTION
    Invoke-PilotManualSetup is an executable runbook for the pilot's manual deployment path (Decision 3).
    The manual path is built and proven before any automated REST provisioning, so the automation later
    becomes a convenience layer over a known-good path rather than a single point of failure.

    The command prints the ordered manual provisioning steps the operator performs in the Fabric portal,
    then runs the fail-loud preflight (Test-PilotDeployment) against the parameters file the operator fills
    in afterward. It is idempotent: re-running re-validates the current parameters without side effects.

    .PARAMETER ParametersPath
    Required. Path to the JSON parameters file the operator completes after creating the workspace and Lakehouse.

    .PARAMETER TestConnectivity
    Optional. Passed through to the preflight to attempt endpoint reachability checks.

    .EXAMPLE
    Invoke-PilotManualSetup -ParametersPath ./my-deployment.json

    Prints the manual steps and validates the completed parameters file.
#>
function Invoke-PilotManualSetup
{
    [CmdletBinding()]
    [OutputType([hashtable])]
    param
    (
        [Parameter(Mandatory = $true)]
        [string]
        $ParametersPath,

        [Parameter(Mandatory = $false)]
        [switch]
        $TestConnectivity
    )

    . (Join-Path -Path $PSScriptRoot -ChildPath 'Test-PilotDeployment.ps1')

    $steps = @(
        'Create (or select) a Microsoft Fabric capacity in a non-production tenant. Record its resource id as capacityId.'
        'Create a Fabric workspace and assign it to that capacity. Record its display name as workspaceName.'
        'Create a Lakehouse in the workspace. Record its name as lakehouseName (must start with a letter; letters/digits/underscore only).'
        'Open the Lakehouse > Properties and copy the ABFSS OneLake path. It must look like abfss://{workspace}@onelake.dfs.fabric.microsoft.com/{lakehouse}.Lakehouse. Record it as oneLakeEndpoint.'
        'Open the Lakehouse SQL analytics endpoint > Settings and copy the connection host (….datawarehouse.fabric.microsoft.com). Record it as sqlEndpoint.'
        "Fill in the parameters file at '$ParametersPath' using deploy-parameters.sample.json as a template."
        'Grant the pilot service principal (or your account) Contributor on the workspace so the notebooks can write Delta.'
    )

    Write-Host ''
    Write-Host 'FinOps OneLake pilot - manual Fabric provisioning runbook' -ForegroundColor Cyan
    Write-Host '----------------------------------------------------------'
    for ($i = 0; $i -lt $steps.Count; $i++)
    {
        Write-Host ("  {0}. {1}" -f ($i + 1), $steps[$i])
    }
    Write-Host ''

    if (-not (Test-Path -Path $ParametersPath))
    {
        Write-Warning "Parameters file not found yet: $ParametersPath"
        Write-Warning 'Complete the steps above, create the parameters file, then re-run this command to validate.'
        return
    }

    Write-Host 'Running preflight validation...' -ForegroundColor Cyan
    $resolved = Test-PilotDeployment -ParametersPath $ParametersPath -TestConnectivity:$TestConnectivity

    Write-Host 'Preflight passed. Manual deployment path is verified end-to-end.' -ForegroundColor Green
    return $resolved
}
