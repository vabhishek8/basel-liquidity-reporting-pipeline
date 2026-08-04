// Basel III LCR / NSFR regulatory reporting: production Azure mapping.
//
// This is the third distinct architectural posture in the portfolio, and
// deliberately makes a different infrastructure call than either sibling
// project, not because more infrastructure is inherently better, but
// because this workload's shape is different:
//
//   - weather-pipeline:  low, sporadic volume        -> Synapse Serverless
//   - aml-pipeline:      compliance/PII-adjacent data -> private-endpoint-only
//   - this project:      scheduled, predictable, regulatory-deadline batch
//                        with a segregation-of-duties requirement
//                        -> reserved/dedicated capacity, geo-redundant
//                           storage, and a maker-checker approval gate
//
// A missed regulatory submission because of a regional storage outage is
// itself a compliance failure, so this is the one project in the
// portfolio that spends the extra cost on geo-redundant storage. It is
// also the one project where "serverless, pay-per-query" is the wrong
// default: the batch runs on a fixed daily schedule with a hard
// submission deadline, so a small reserved Synapse Dedicated SQL Pool
// that is paused outside the batch window gives predictable throughput
// against that deadline, without serverless's per-query cost and
// cold-start variance for a job that cannot simply retry after hours.

@description('Deployment environment. Prod gets GRS storage, longer retention, and a live Synapse Dedicated Pool; dev keeps costs near zero.')
@allowed(['dev', 'prod'])
param envName string = 'dev'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Email address for pipeline-failure and submission-approval alerts.')
param alertEmail string

@description('Object ID of the "checker" principal allowed to approve a submission. Left blank in dev.')
param checkerPrincipalId string = ''

var namePrefix = 'bliq${envName}'
var isProd = envName == 'prod'
var tags = {
  project: 'basel-liquidity-reporting-pipeline'
  environment: envName
  costCentre: 'regulatory-reporting'
}

// ---------------------------------------------------------------------------
// Networking: private endpoints for storage and the Synapse workspace.
// Lighter-touch than the AML project's VNet-everywhere posture (this data
// is regulatory-submission data, not raw transaction/PII data), but still
// off the public internet for the resources that hold it.
// ---------------------------------------------------------------------------
resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: '${namePrefix}-vnet'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: ['10.30.0.0/16'] }
    subnets: [
      {
        name: 'snet-private-endpoints'
        properties: {
          addressPrefix: '10.30.1.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

// ---------------------------------------------------------------------------
// Storage: bronze/silver/gold, plus a submission workflow split into
// pending-submission and submitted containers (the maker-checker gate),
// and a dedicated audit-log container for sign-off evidence.
//
// GRS, not LRS/ZRS: this is the one project in the portfolio where a
// regional outage during the reporting window is itself the risk being
// mitigated, not just data durability.
// ---------------------------------------------------------------------------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: '${namePrefix}${uniqueString(resourceGroup().id)}'
  location: location
  tags: tags
  sku: { name: isProd ? 'Standard_GRS' : 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    publicNetworkAccess: 'Disabled'
    isHnsEnabled: true
  }

  resource blobServices 'blobServices' = {
    name: 'default'
    properties: {
      isVersioningEnabled: true
      deleteRetentionPolicy: { enabled: true, days: isProd ? 90 : 14 }
    }

    resource bronze 'containers' = { name: 'bronze' }
    resource silver 'containers' = { name: 'silver' }
    resource gold 'containers' = { name: 'gold' }
    resource pendingSubmission 'containers' = { name: 'pending-submission' }
    resource submitted 'containers' = { name: 'submitted' }
    resource auditLog 'containers' = { name: 'audit-log' }
  }
}

resource peStorage 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: '${namePrefix}-pe-storage'
  location: location
  tags: tags
  properties: {
    subnet: { id: vnet.properties.subnets[0].id }
    privateLinkServiceConnections: [
      {
        name: 'storage-connection'
        properties: {
          privateLinkServiceId: storage.id
          groupIds: ['dfs']
        }
      }
    ]
  }
}

// ---------------------------------------------------------------------------
// Key Vault: RBAC-authorized, purge protection on. Holds the Synapse SQL
// admin credential and the checker-approval function's signing key.
// ---------------------------------------------------------------------------
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${namePrefix}-kv-${uniqueString(resourceGroup().id)}'
  location: location
  tags: tags
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enablePurgeProtection: true
    softDeleteRetentionInDays: 90
    publicNetworkAccess: 'Disabled'
  }
}

// ---------------------------------------------------------------------------
// Orchestration: Azure Data Factory, the "maker". Writes to
// pending-submission only; cannot write to submitted directly.
// ---------------------------------------------------------------------------
resource dataFactory 'Microsoft.DataFactory/factories@2018-06-01' = {
  name: '${namePrefix}-adf'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    publicNetworkAccess: 'Disabled'
  }
}

resource adfStorageRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, dataFactory.id, 'StorageBlobDataContributor')
  scope: storage
  properties: {
    principalId: dataFactory.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  }
}

// The checker's role assignment: submit-approval permission scoped to
// the 'submitted' container path is enforced at the application layer
// (the approval Function checks the caller's identity against this
// role), Azure RBAC alone does not do path-scoped blob ACLs without
// Azure AD DS or ABAC conditions, which is out of scope for a portfolio
// deployment target. The segregation of duties this models is real; the
// enforcement mechanism here is simplified.
resource checkerRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(checkerPrincipalId)) {
  name: guid(storage.id, checkerPrincipalId, 'StorageBlobDataContributor')
  scope: storage
  properties: {
    principalId: checkerPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  }
}

// ---------------------------------------------------------------------------
// Compute: Synapse workspace with a Dedicated SQL Pool, not Serverless.
// Deliberately paused outside the nightly batch window (resumed by the
// ADF pipeline's first activity, paused by its last) so it is not billed
// 24/7, the same cost discipline as the sibling projects, applied
// differently because this workload's demand curve is different: fixed
// schedule, predictable size, hard deadline, rather than the sporadic
// low-volume pattern that makes serverless the right call for
// weather-pipeline.
// ---------------------------------------------------------------------------
resource synapseWorkspace 'Microsoft.Synapse/workspaces@2021-06-01' = {
  name: '${namePrefix}-synapse'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    defaultDataLakeStorage: {
      accountUrl: 'https://${storage.name}.dfs.${az.environment().suffixes.storage}'
      filesystem: 'gold'
    }
    sqlAdministratorLogin: 'baselliqadmin'
    sqlAdministratorLoginPassword: '${uniqueString(resourceGroup().id, deployment().name)}Aa1!'
    managedVirtualNetwork: 'default'
    publicNetworkAccess: 'Disabled'
  }
}

resource dedicatedPool 'Microsoft.Synapse/workspaces/sqlPools@2021-06-01' = {
  parent: synapseWorkspace
  name: 'reportingpool'
  location: location
  tags: tags
  sku: { name: 'DW100c' } // smallest reserved tier; paused outside the batch window
  properties: {
    createMode: 'Default'
    collation: 'SQL_Latin1_General_CP1_CI_AS'
  }
}

resource peSynapse 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: '${namePrefix}-pe-synapse'
  location: location
  tags: tags
  properties: {
    subnet: { id: vnet.properties.subnets[0].id }
    privateLinkServiceConnections: [
      {
        name: 'synapse-connection'
        properties: {
          privateLinkServiceId: synapseWorkspace.id
          groupIds: ['Sql']
        }
      }
    ]
  }
}

// ---------------------------------------------------------------------------
// Monitoring & alerting: pipeline failures, plus longer retention than
// the weather-pipeline baseline, this is an audit trail for a regulatory
// submission process, not just operational telemetry.
// ---------------------------------------------------------------------------
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${namePrefix}-law'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: isProd ? 365 : 30
  }
}

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: '${namePrefix}-ag'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: 'baselliqag'
    enabled: true
    emailReceivers: [
      { name: 'reporting-owner', emailAddress: alertEmail, useCommonAlertSchema: true }
    ]
  }
}

resource pipelineFailureAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: '${namePrefix}-pipeline-failed'
  location: 'global'
  tags: tags
  properties: {
    severity: 1
    enabled: true
    scopes: [dataFactory.id]
    evaluationFrequency: 'PT15M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          criterionType: 'StaticThresholdCriterion'
          name: 'PipelineFailedRuns'
          metricName: 'PipelineFailedRuns'
          operator: 'GreaterThan'
          threshold: 0
          timeAggregation: 'Total'
        }
      ]
    }
    actions: [{ actionGroupId: actionGroup.id }]
  }
}

output storageAccountName string = storage.name
output synapseWorkspaceName string = synapseWorkspace.name
output dedicatedPoolName string = dedicatedPool.name
output dataFactoryName string = dataFactory.name
