# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

<#
    .SYNOPSIS
    Pester tests for Test-PilotDeployment (manual Fabric deployment preflight).

    .DESCRIPTION
    Validates that the preflight gate passes a well-formed parameters file and fails loudly on every
    contract violation: missing required fields, malformed endpoints, unknown properties, blob endpoints,
    and lakehouse/endpoint inconsistency. Connectivity is not exercised here (covered by -TestConnectivity).

    Run: Invoke-Pester -Path ./Test-PilotDeployment.Tests.ps1
#>

BeforeAll {
    . (Join-Path -Path $PSScriptRoot -ChildPath 'Test-PilotDeployment.ps1')
    $script:schemaPath = Join-Path -Path $PSScriptRoot -ChildPath 'deploy-parameters.schema.json'

    function New-TempParams
    {
        param ([hashtable] $Params)

        $path = Join-Path -Path $TestDrive -ChildPath ([System.IO.Path]::GetRandomFileName() + '.json')
        $Params | ConvertTo-Json -Depth 5 | Set-Content -Path $path -Encoding utf8
        return $path
    }

    function Get-GoodParams
    {
        return @{
            workspaceName   = 'FinOps Pilot'
            lakehouseName   = 'FinOpsHub'
            oneLakeEndpoint = 'abfss://FinOps Pilot@onelake.dfs.fabric.microsoft.com/FinOpsHub.Lakehouse'
            sqlEndpoint     = 'abc123xyz.datawarehouse.fabric.microsoft.com'
            environment     = 'pilot'
        }
    }
}

Describe 'Test-PilotDeployment' {

    Context 'Valid input' {
        It 'returns resolved parameters for a well-formed file' {
            $path = New-TempParams -Params (Get-GoodParams)
            $result = Test-PilotDeployment -ParametersPath $path -SchemaPath $script:schemaPath
            $result.workspaceName | Should -Be 'FinOps Pilot'
            $result.lakehouseName | Should -Be 'FinOpsHub'
            $result.environment | Should -Be 'pilot'
        }

        It 'is idempotent: re-running yields the same resolved output' {
            $path = New-TempParams -Params (Get-GoodParams)
            $first = Test-PilotDeployment -ParametersPath $path -SchemaPath $script:schemaPath
            $second = Test-PilotDeployment -ParametersPath $path -SchemaPath $script:schemaPath
            $first.oneLakeEndpoint | Should -Be $second.oneLakeEndpoint
        }

        It 'defaults environment to pilot when omitted' {
            $p = Get-GoodParams
            $p.Remove('environment')
            $path = New-TempParams -Params $p
            $result = Test-PilotDeployment -ParametersPath $path -SchemaPath $script:schemaPath
            $result.environment | Should -Be 'pilot'
        }

        It 'accepts privateNetworking set to false' {
            $p = Get-GoodParams
            $p['privateNetworking'] = $false
            $path = New-TempParams -Params $p
            $result = Test-PilotDeployment -ParametersPath $path -SchemaPath $script:schemaPath
            $result.privateNetworking | Should -Be $false
        }
    }

    Context 'Hard failures' {
        It 'throws when a required parameter is missing' {
            $p = Get-GoodParams
            $p.Remove('sqlEndpoint')
            $path = New-TempParams -Params $p
            { Test-PilotDeployment -ParametersPath $path -SchemaPath $script:schemaPath } |
            Should -Throw -ExpectedMessage '*sqlEndpoint*'
        }

        It 'throws on a malformed OneLake endpoint' {
            $p = Get-GoodParams
            $p.oneLakeEndpoint = 'https://contoso.blob.core.windows.net/FinOpsHub'
            $path = New-TempParams -Params $p
            { Test-PilotDeployment -ParametersPath $path -SchemaPath $script:schemaPath } |
            Should -Throw
        }

        It 'throws when a blob endpoint is supplied' {
            $p = Get-GoodParams
            # Passes the lakehouse segment but is a blob endpoint.
            $p.oneLakeEndpoint = 'abfss://ws@contoso.blob.core.windows.net/FinOpsHub.Lakehouse'
            $path = New-TempParams -Params $p
            { Test-PilotDeployment -ParametersPath $path -SchemaPath $script:schemaPath } |
            Should -Throw
        }

        It 'throws when lakehouseName and endpoint disagree' {
            $p = Get-GoodParams
            $p.lakehouseName = 'OtherName'
            $path = New-TempParams -Params $p
            { Test-PilotDeployment -ParametersPath $path -SchemaPath $script:schemaPath } |
            Should -Throw -ExpectedMessage '*Inconsistent*'
        }

        It 'throws on an unknown parameter' {
            $p = Get-GoodParams
            $p['unexpected'] = 'value'
            $path = New-TempParams -Params $p
            { Test-PilotDeployment -ParametersPath $path -SchemaPath $script:schemaPath } |
            Should -Throw -ExpectedMessage '*Unknown parameter*'
        }

        It 'throws on an invalid environment enum value' {
            $p = Get-GoodParams
            $p.environment = 'production'
            $path = New-TempParams -Params $p
            { Test-PilotDeployment -ParametersPath $path -SchemaPath $script:schemaPath } |
            Should -Throw
        }

        It 'throws when private networking is declared (issue #2061)' {
            $p = Get-GoodParams
            $p['privateNetworking'] = $true
            $path = New-TempParams -Params $p
            { Test-PilotDeployment -ParametersPath $path -SchemaPath $script:schemaPath } |
            Should -Throw -ExpectedMessage '*2061*'
        }

        It 'throws when the parameters file does not exist' {
            { Test-PilotDeployment -ParametersPath (Join-Path $TestDrive 'missing.json') -SchemaPath $script:schemaPath } |
            Should -Throw -ExpectedMessage '*not found*'
        }
    }
}
