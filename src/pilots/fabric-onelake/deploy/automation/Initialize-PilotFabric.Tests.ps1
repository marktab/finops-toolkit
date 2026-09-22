# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

BeforeAll {
    . (Join-Path $PSScriptRoot 'Initialize-PilotFabric.ps1')
}

Describe 'Initialize-PilotFabric (mocked REST only)' {
    BeforeEach {
        $script:paramsPath = Join-Path $TestDrive "$([guid]::NewGuid()).json"
        $script:sqlHost = 'abc123.datawarehouse.fabric.microsoft.com'
        Mock Invoke-RestMethod { throw "Unexpected REST request: $Method $Uri" }
        Mock Start-Sleep {}
        Mock Invoke-RestMethod {
            @{ value = @(@{ id = 'workspace-id'; displayName = 'FinOps Pilot' }) }
        } -ParameterFilter { $Method -eq 'Get' -and $Uri -eq 'https://api.fabric.microsoft.com/v1/workspaces' }
        Mock Invoke-RestMethod {
            @{ value = @(@{
                id = 'lakehouse-id'
                displayName = 'FinOpsHub'
                properties = @{ sqlEndpointProperties = @{ connectionString = $script:sqlHost } }
            }) }
        } -ParameterFilter { $Method -eq 'Get' -and $Uri -eq 'https://api.fabric.microsoft.com/v1/workspaces/workspace-id/lakehouses' }
    }

    It 'reuses existing items across repeated calls and writes validated parameters' {
        foreach ($attempt in 1..2) {
            $result = Initialize-PilotFabric -WorkspaceName 'FinOps Pilot' -LakehouseName 'FinOpsHub' -AccessToken 'test-token' -ParametersPath $script:paramsPath
            $result.sqlEndpoint | Should -Be $script:sqlHost
            $result.oneLakeEndpoint | Should -Be 'abfss://FinOps Pilot@onelake.dfs.fabric.microsoft.com/FinOpsHub.Lakehouse'
        }
        Test-Path $script:paramsPath | Should -BeTrue
        Should -Invoke Invoke-RestMethod -Times 0 -Exactly -ParameterFilter { $Method -eq 'Post' }
        Should -Invoke Invoke-RestMethod -Times 4 -Exactly -ParameterFilter { $Headers.Authorization -eq 'Bearer test-token' }
    }

    It 'does not validate an unwritten file when WhatIf reuses existing items' {
        { Initialize-PilotFabric -WorkspaceName 'FinOps Pilot' -LakehouseName 'FinOpsHub' -AccessToken 'test-token' -ParametersPath $script:paramsPath -WhatIf } | Should -Not -Throw
        Test-Path $script:paramsPath | Should -BeFalse
        Should -Invoke Invoke-RestMethod -Times 0 -Exactly -ParameterFilter { $Method -eq 'Post' }
    }

    It 'does not create a missing workspace in WhatIf mode' {
        Mock Invoke-RestMethod { @{ value = @() } } -ParameterFilter { $Uri -eq 'https://api.fabric.microsoft.com/v1/workspaces' }
        Initialize-PilotFabric -WorkspaceName 'FinOps Pilot' -LakehouseName 'FinOpsHub' -AccessToken 'test-token' -ParametersPath $script:paramsPath -WhatIf
        Test-Path $script:paramsPath | Should -BeFalse
        Should -Invoke Invoke-RestMethod -Times 1 -Exactly
    }

    It 'does not read or overwrite a stale parameters file in WhatIf mode' {
        Set-Content -Path $script:paramsPath -Value 'not valid JSON'
        { Initialize-PilotFabric -WorkspaceName 'FinOps Pilot' -LakehouseName 'FinOpsHub' -AccessToken 'test-token' -ParametersPath $script:paramsPath -WhatIf } | Should -Not -Throw
        Get-Content $script:paramsPath | Should -Be 'not valid JSON'
        Should -Invoke Invoke-RestMethod -Times 0 -Exactly -ParameterFilter { $Method -eq 'Post' }
    }

    It 'creates missing items using mocked responses and validates the generated file' {
        Mock Invoke-RestMethod { @{ value = @() } } -ParameterFilter { $Method -eq 'Get' }
        Mock Invoke-RestMethod { @{ id = 'workspace-id' } } -ParameterFilter {
            $Method -eq 'Post' -and $Uri -eq 'https://api.fabric.microsoft.com/v1/workspaces'
        }
        Mock Invoke-RestMethod {
            @{
                id = 'lakehouse-id'
                properties = @{ sqlEndpointProperties = @{ connectionString = $script:sqlHost } }
            }
        } -ParameterFilter { $Method -eq 'Post' -and $Uri -eq 'https://api.fabric.microsoft.com/v1/workspaces/workspace-id/lakehouses' }
        $result = Initialize-PilotFabric -WorkspaceName 'FinOps Pilot' -LakehouseName 'FinOpsHub' -CapacityId 'capacity-id' -AccessToken 'test-token' -ParametersPath $script:paramsPath
        $result.capacityId | Should -Be 'capacity-id'
        Should -Invoke Invoke-RestMethod -Times 1 -Exactly -ParameterFilter {
            $Method -eq 'Post' -and ($Body | ConvertFrom-Json).capacityId -eq 'capacity-id'
        }
        Should -Invoke Invoke-RestMethod -Times 2 -Exactly -ParameterFilter { $Method -eq 'Post' }
    }

    It 'waits for an asynchronously provisioned SQL endpoint before writing parameters' {
        $script:sqlHost = $null
        Mock Invoke-RestMethod {
            @{ properties = @{ sqlEndpointProperties = @{ connectionString = 'ready.datawarehouse.fabric.microsoft.com' } } }
        } -ParameterFilter { $Uri -eq 'https://api.fabric.microsoft.com/v1/workspaces/workspace-id/lakehouses/lakehouse-id' }
        $result = Initialize-PilotFabric -WorkspaceName 'FinOps Pilot' -LakehouseName 'FinOpsHub' -AccessToken 'test-token' -ParametersPath $script:paramsPath
        $result.sqlEndpoint | Should -Be 'ready.datawarehouse.fabric.microsoft.com'
        Should -Invoke Start-Sleep -Times 1 -Exactly -ParameterFilter { $Seconds -eq 10 }
    }

    It 'fails without writing parameters when SQL endpoint provisioning times out' {
        $script:sqlHost = $null
        $script:now = [datetime]'2026-01-01T00:00:00Z'
        Mock Get-Date { $script:now }
        Mock Start-Sleep { $script:now = $script:now.AddSeconds(31) }
        Mock Invoke-RestMethod { @{ properties = @{} } } -ParameterFilter {
            $Uri -eq 'https://api.fabric.microsoft.com/v1/workspaces/workspace-id/lakehouses/lakehouse-id'
        }
        { Initialize-PilotFabric -WorkspaceName 'FinOps Pilot' -LakehouseName 'FinOpsHub' -AccessToken 'test-token' -ParametersPath $script:paramsPath -ProvisioningTimeoutSeconds 30 } |
        Should -Throw -ExpectedMessage '*did not provision within 30 seconds*'
        Test-Path $script:paramsPath | Should -BeFalse
        Should -Invoke Start-Sleep -Times 1 -Exactly
    }

    It 'fails before a request for an unresolved sovereign cloud' {
        { Initialize-PilotFabric -WorkspaceName 'FinOps Pilot' -LakehouseName 'FinOpsHub' -AccessToken 'test-token' -AzureEnvironment AzureUSGovernment -ParametersPath $script:paramsPath } |
        Should -Throw -ExpectedMessage '*No OneLake DFS host*'
        Should -Invoke Invoke-RestMethod -Times 0 -Exactly
    }
}

Describe 'Fabric REST helpers (mocked REST only)' {
    It 'normalizes a SecureString without stringifying the type' {
        $token = ConvertTo-SecureString 'test-token' -AsPlainText -Force
        ConvertTo-PilotPlainToken -Token $token | Should -Be 'test-token'
    }

    It 'rejects an accidentally stringified SecureString' {
        { ConvertTo-PilotPlainToken -Token 'System.Security.SecureString' } | Should -Throw '*stringified*'
    }

    It 'follows pagination to reuse an item on a later page' {
        Mock Invoke-RestMethod { throw "Unexpected REST request: $Uri" }
        Mock Invoke-RestMethod {
            @{ value = @(); continuationUri = 'https://api.fabric.microsoft.com/v1/workspaces?continuationToken=next' }
        } -ParameterFilter { $Uri -eq 'https://api.fabric.microsoft.com/v1/workspaces' }
        Mock Invoke-RestMethod {
            @{ value = @(@{ id = 'existing-id'; displayName = 'FinOps Pilot' }) }
        } -ParameterFilter { $Uri -eq 'https://api.fabric.microsoft.com/v1/workspaces?continuationToken=next' }
        $item = Get-PilotFabricItem -Uri 'https://api.fabric.microsoft.com/v1/workspaces' -Headers @{} -DisplayName 'FinOps Pilot'
        $item.id | Should -Be 'existing-id'
        Should -Invoke Invoke-RestMethod -Times 2 -Exactly
    }
}
