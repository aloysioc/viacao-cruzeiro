targetScope = 'subscription'

@description('Nome do Resource Group da aplicação Viação Cruzeiro.')
param resourceGroupName string

@description('Região Azure aprovada para os recursos da aplicação.')
param location string

@description('Tags obrigatórias definidas pelo cliente para a aplicação.')
param tags object = {}

resource applicationResourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

output resourceGroupId string = applicationResourceGroup.id
output resourceGroupNameOutput string = applicationResourceGroup.name
output locationOutput string = applicationResourceGroup.location
