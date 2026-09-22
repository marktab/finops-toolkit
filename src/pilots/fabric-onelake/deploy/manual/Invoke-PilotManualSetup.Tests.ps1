# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

BeforeAll {
    . (Join-Path $PSScriptRoot 'Invoke-PilotManualSetup.ps1')
}

Describe 'Manual setup offline boundary' {
    BeforeEach {
        Mock Write-Host {}
        Mock Write-Warning {}
        Mock Invoke-RestMethod { throw 'Unexpected network request' }
    }

    It 'reports parameter validation, not end-to-end readiness' {
        $sample = Join-Path $PSScriptRoot 'deploy-parameters.sample.json'
        $result = Invoke-PilotManualSetup -ParametersPath $sample
        $result.environment | Should -Be 'pilot'
        Should -Invoke Write-Host -Times 1 -Exactly -ParameterFilter {
            $Object -eq 'Parameter preflight passed. Live notebook, SQL, and report validation is still required.'
        }
        Should -Invoke Invoke-RestMethod -Times 0 -Exactly
    }

    It 'does not claim success before the operator supplies a parameters file' {
        $missing = Join-Path $TestDrive 'missing.json'
        Invoke-PilotManualSetup -ParametersPath $missing | Should -BeNullOrEmpty
        Should -Invoke Write-Warning -Times 2 -Exactly
        Should -Invoke Write-Host -Times 0 -Exactly -ParameterFilter { $Object -like '*preflight passed*' }
        Should -Invoke Invoke-RestMethod -Times 0 -Exactly
    }
}
