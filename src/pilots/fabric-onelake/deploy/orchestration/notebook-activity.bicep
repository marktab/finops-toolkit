// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

//==============================================================================
// FinOps OneLake pilot - hybrid orchestration (Decision 3)
//
// ADF stays as the orchestrator (it deploys via Bicep/ARM and runs in
// restricted/air-gapped tenants that Fabric pipelines cannot be ARM-provisioned
// into). This module adds the genuinely new surface area: an ADF pipeline that
// hands off to a Fabric Spark notebook via the Fabric REST API and waits for it,
// using the Data Factory managed identity. It is the sibling of the existing
// AzureDataExplorerCommand path, not a replacement for it.
//
// The handoff is intentionally a thin REST call layered over a notebook that has
// already been proven via the manual deployment path (Test-PilotDeployment).
//==============================================================================

@description('Required. Name of the existing Data Factory to add the pipeline to.')
param dataFactoryName string

@description('Required. Microsoft Fabric workspace (GUID) that hosts the pilot notebooks.')
param fabricWorkspaceId string

@description('Required. Microsoft Fabric notebook artifact id (GUID) to run.')
param fabricNotebookId string

@description('Optional. Fabric REST API base URL. Default: public cloud.')
param fabricApiBaseUrl string = 'https://api.fabric.microsoft.com/v1'

@description('Optional. Seconds to wait between job status polls. Default: 30.')
@minValue(30)
@maxValue(300)
param pollIntervalSeconds int = 30

@description('Optional. Maximum time to wait for the notebook job before failing, as a d.HH:mm:ss timespan. Default: 2 hours.')
param jobTimeout string = '0.02:00:00'

var fabricResource = 'https://api.fabric.microsoft.com'

resource dataFactory 'Microsoft.DataFactory/factories@2018-06-01' existing = {
  name: dataFactoryName
}

@description('Runs a Fabric Spark notebook via the Fabric REST API and waits for completion.')
resource pipeline_RunFabricNotebook 'Microsoft.DataFactory/factories/pipelines@2018-06-01' = {
  name: 'pilot_RunFabricNotebook'
  parent: dataFactory
  properties: {
    description: 'Hybrid handoff: ADF invokes a Fabric notebook job and polls until it completes.'
    parameters: {
      executionData: {
        type: 'Object'
        defaultValue: {}
      }
    }
    variables: {
      statusUri: { type: 'String' }
      jobStatus: { type: 'String', defaultValue: 'NotStarted' }
    }
    activities: [
      { // Start Notebook Job
        // POST .../items/{notebookId}/jobs/instances?jobType=RunNotebook
        // Returns 202 with a Location header pointing at the job instance.
        name: 'Start Notebook Job'
        type: 'WebActivity'
        policy: {
          timeout: '0.00:10:00'
          retry: 1
          retryIntervalInSeconds: 30
          secureOutput: false
          secureInput: false
        }
        userProperties: []
        typeProperties: {
          method: 'POST'
          url: '${fabricApiBaseUrl}/workspaces/${fabricWorkspaceId}/items/${fabricNotebookId}/jobs/instances?jobType=RunNotebook'
          body: {
            executionData: '@pipeline().parameters.executionData'
          }
          authentication: {
            type: 'MSI'
            resource: fabricResource
          }
        }
      }
      { // Capture Status Uri
        name: 'Capture Status Uri'
        type: 'SetVariable'
        dependsOn: [
          { activity: 'Start Notebook Job', dependencyConditions: ['Succeeded'] }
        ]
        policy: { secureOutput: false, secureInput: false }
        userProperties: []
        typeProperties: {
          variableName: 'statusUri'
          value: {
            value: '@activity(\'Start Notebook Job\').output.ADFWebActivityResponseHeaders.Location'
            type: 'Expression'
          }
        }
      }
      { // Wait For Completion
        name: 'Wait For Completion'
        type: 'Until'
        dependsOn: [
          { activity: 'Capture Status Uri', dependencyConditions: ['Succeeded'] }
        ]
        userProperties: []
        typeProperties: {
          // Stop polling once the job reaches a terminal state.
          expression: {
            value: '@or(or(equals(variables(\'jobStatus\'), \'Completed\'), equals(variables(\'jobStatus\'), \'Failed\')), equals(variables(\'jobStatus\'), \'Cancelled\'))'
            type: 'Expression'
          }
          timeout: jobTimeout
          activities: [
            { // Wait Between Polls
              name: 'Wait Between Polls'
              type: 'Wait'
              userProperties: []
              typeProperties: {
                waitTimeInSeconds: pollIntervalSeconds
              }
            }
            { // Get Job Status
              name: 'Get Job Status'
              type: 'WebActivity'
              dependsOn: [
                { activity: 'Wait Between Polls', dependencyConditions: ['Succeeded'] }
              ]
              policy: {
                timeout: '0.00:05:00'
                retry: 2
                retryIntervalInSeconds: 15
                secureOutput: false
                secureInput: false
              }
              userProperties: []
              typeProperties: {
                method: 'GET'
                url: {
                  value: '@variables(\'statusUri\')'
                  type: 'Expression'
                }
                authentication: {
                  type: 'MSI'
                  resource: fabricResource
                }
              }
            }
            { // Set Job Status
              name: 'Set Job Status'
              type: 'SetVariable'
              dependsOn: [
                { activity: 'Get Job Status', dependencyConditions: ['Succeeded'] }
              ]
              policy: { secureOutput: false, secureInput: false }
              userProperties: []
              typeProperties: {
                variableName: 'jobStatus'
                value: {
                  value: '@activity(\'Get Job Status\').output.status'
                  type: 'Expression'
                }
              }
            }
          ]
        }
      }
      { // Fail On Notebook Error
        // Fail loudly: a non-Completed terminal state must stop the pipeline
        // rather than silently continuing as if ingestion succeeded.
        name: 'Fail On Notebook Error'
        type: 'IfCondition'
        dependsOn: [
          { activity: 'Wait For Completion', dependencyConditions: ['Succeeded'] }
        ]
        userProperties: []
        typeProperties: {
          expression: {
            value: '@not(equals(variables(\'jobStatus\'), \'Completed\'))'
            type: 'Expression'
          }
          ifTrueActivities: [
            {
              name: 'Raise Notebook Failure'
              type: 'Fail'
              userProperties: []
              typeProperties: {
                message: {
                  value: '@concat(\'Fabric notebook job ended in non-success state: \', variables(\'jobStatus\'))'
                  type: 'Expression'
                }
                errorCode: 'FabricNotebookJobFailed'
              }
            }
          ]
        }
      }
    ]
    concurrency: 1
  }
}

@description('Resource ID of the pilot Fabric-notebook orchestration pipeline.')
output pipelineId string = pipeline_RunFabricNotebook.id

@description('Name of the pilot Fabric-notebook orchestration pipeline.')
output pipelineName string = pipeline_RunFabricNotebook.name
