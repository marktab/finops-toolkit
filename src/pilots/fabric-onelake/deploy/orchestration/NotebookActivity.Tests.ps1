# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

BeforeAll {
    # BICEP_CLI_PATH supports an isolated local compiler without changing PATH.
    $compiler = if ($env:BICEP_CLI_PATH) { $env:BICEP_CLI_PATH } else { 'bicep' }
    $json = & $compiler build (Join-Path $PSScriptRoot 'notebook-activity.bicep') --stdout
    if ($LASTEXITCODE -ne 0) { throw "Bicep compilation failed: $LASTEXITCODE" }
    $template = ($json -join "`n") | ConvertFrom-Json -Depth 100
    $pipeline = $template.resources | Where-Object type -EQ 'Microsoft.DataFactory/factories/pipelines'
    $activities = $pipeline.properties.activities
    $start = $activities | Where-Object name -EQ 'Start Notebook Job'
    $capture = $activities | Where-Object name -EQ 'Capture Status Uri'
    $wait = $activities | Where-Object name -EQ 'Wait For Completion'
    $poll = $wait.typeProperties.activities | Where-Object name -EQ 'Get Job Status'
    $setStatus = $wait.typeProperties.activities | Where-Object name -EQ 'Set Job Status'
    $failure = $activities | Where-Object name -EQ 'Fail On Notebook Error'
}

Describe 'Compiled notebook orchestration contract (offline, not an ADF execution)' {
    It 'adds only a standalone pipeline to an existing factory with no trigger or copy stage' {
        @($template.resources).Count | Should -Be 1
        $pipeline.properties.concurrency | Should -Be 1
        $pipeline.name | Should -Match 'pilot_RunFabricNotebook'
        @($activities).Count | Should -Be 4
    }

    It 'preserves the initial 202 Location for explicit polling without replaying the POST' {
        $start.typeProperties.method | Should -Be 'POST'
        $start.typeProperties.turnOffAsync | Should -BeTrue
        $start.policy.retry | Should -Be 0
        $capture.dependsOn.activity | Should -Be 'Start Notebook Job'
        $capture.typeProperties.value.value | Should -Be "@activity('Start Notebook Job').output.ADFWebActivityResponseHeaders.Location"
        $start.typeProperties.body.executionData | Should -Be '@pipeline().parameters.executionData'
    }

    It 'uses managed identity for submission and polling' {
        foreach ($activity in @($start, $poll)) {
            $activity.typeProperties.authentication.type | Should -Be 'MSI'
            $activity.typeProperties.authentication.resource | Should -Be "[variables('fabricResource')]"
        }
        $template.variables.fabricResource | Should -Be 'https://api.fabric.microsoft.com'
    }

    It 'polls the captured URI at a bounded interval and timeout' {
        $wait.typeProperties.timeout | Should -Be "[parameters('jobTimeout')]"
        $poll.typeProperties.method | Should -Be 'GET'
        $poll.typeProperties.url.value | Should -Be "@variables('statusUri')"
        $poll.policy.retryIntervalInSeconds | Should -BeGreaterOrEqual 30
        $poll.dependsOn.activity | Should -Be 'Wait Between Polls'
        $setStatus.dependsOn.activity | Should -Be 'Get Job Status'
        $setStatus.typeProperties.value.value | Should -Be "@activity('Get Job Status').output.status"
        $template.parameters.pollIntervalSeconds.minValue | Should -Be 30
        $template.parameters.pollIntervalSeconds.maxValue | Should -Be 300
    }

    It 'stops polling for terminal state <Status>' -ForEach @(
        @{ Status = 'Completed' }
        @{ Status = 'Failed' }
        @{ Status = 'Cancelled' }
        @{ Status = 'Deduped' }
    ) {
        $wait.typeProperties.expression.value | Should -Match ([regex]::Escape("equals(variables('jobStatus'), '$Status')"))
    }

    It 'continues polling for nonterminal state <Status>' -ForEach @(
        @{ Status = 'NotStarted' }
        @{ Status = 'InProgress' }
    ) {
        $wait.typeProperties.expression.value | Should -Not -Match ([regex]::Escape("'$Status'"))
    }

    It 'accepts only Completed, without interpreting notebook exit values as validation evidence' {
        $failure.dependsOn.activity | Should -Be 'Wait For Completion'
        $failure.dependsOn.dependencyConditions | Should -Be @('Succeeded')
        $failure.typeProperties.expression.value | Should -Be "@not(equals(variables('jobStatus'), 'Completed'))"
        $failure.typeProperties.ifTrueActivities[0].type | Should -Be 'Fail'
        $failure.typeProperties.ifTrueActivities[0].typeProperties.errorCode | Should -Be 'FabricNotebookJobFailed'
    }
}
