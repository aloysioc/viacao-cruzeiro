# Infraestrutura como código

Esta pasta contém somente a infraestrutura da aplicação Viação Cruzeiro no ambiente do cliente. Não contém segredos, arquivos CSV, dados pessoais ou artefatos gerados.

## Ordem de implantação

1. `bootstrap`: Resource Group, tags e baseline de governança.
2. `core`: Data Lake, Key Vault, Log Analytics, Application Insights e identidade gerenciada.
3. `rbac`: permissões mínimas, implantadas separadamente.
4. `communications`: Azure Communication Services, e-mail e domínio/remetente aprovados.
5. `ai`: Azure OpenAI, somente se aprovado como requisito produtivo.
6. `function`: plano Flex Consumption, Function App, configurações não secretas e diagnósticos.

Cada etapa deverá possuir preflight, validação, `what-if`, deploy explícito e evidência pós-implantação.

## Parâmetros

Use os arquivos `*.parameters.example.json` como modelo. Crie um arquivo local para o ambiente real, que não será versionado, e obtenha segredos exclusivamente pelo Key Vault.
