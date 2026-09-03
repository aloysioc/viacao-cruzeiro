# Viação Cruzeiro — Cronograma de produção

Atualizado em 03/09/2026.

## Estado executivo

| Indicador | Estado |
|---|---|
| Fase atual | Preparação do repositório e da documentação de produção |
| Ambiente do cliente | Aguardando autorização para criação da landing zone |
| LAB | Mantido como referência; triggers desabilitadas |
| Bloqueio principal | Definição do repositório, método e periodicidade de entrega dos CSVs |
| Próximo marco | Aprovação das premissas e criação do Resource Group do cliente |

## Gates de implantação

| Gate | Objetivo | Estado | Dependência para avanço |
|---|---|---|---|
| A — Baseline | Confirmar escopo, responsáveis, dados, custos e critérios de aceite | Em preparação | Respostas do cliente e validação funcional |
| B — Bootstrap | Criar Resource Group, tags, budget e baseline de governança | Aguardando autorização | Subscription, região, nomenclatura e executor autorizados |
| C1 — Fundações | Criar Data Lake, Key Vault, logs, Application Insights e identidades | Não iniciado | Gate B aprovado |
| C2 — RBAC | Aplicar permissões mínimas para serviços e operadores | Não iniciado | Gate C1 aprovado e executor com autorização RBAC |
| C3 — Serviços | Criar Function, ACS/e-mail e Azure OpenAI quando aprovado | Não iniciado | Gates C1/C2 aprovados |
| D — Aplicação | Publicar código, configurações e testes em homologação | Não iniciado | Contrato de dados e primeiro CSV homologado |
| E — Go-live | Executar processamento controlado e habilitar agenda após aceite | Não iniciado | Aceite funcional, técnico e operacional |
| F — Hypercare | Acompanhar operação, custos, alertas e transição | Não iniciado | Gate E concluído |

## Forma de trabalho

Cada gate deverá ter, antes de qualquer implantação:

1. requisitos e pendências registrados;
2. validação local de infraestrutura e código;
3. execução de `what-if` revisada;
4. autorização explícita para o deploy;
5. evidência pós-implantação sem segredos;
6. atualização do cronograma, ADRs e runbooks quando houver mudança relevante.

## Marcos imediatos

| Ordem | Entrega | Responsável inicial | Situação |
|---:|---|---|---|
| 1 | Organizar repositório para produção | Projeto | Em andamento |
| 2 | Formalizar contrato de dados e ingestão dos CSVs | Cliente + referência funcional | Aguardando questionário |
| 3 | Confirmar subscription, região, naming e responsáveis Azure | Cliente | Aguardando autorização |
| 4 | Preparar IaC e scripts de preflight/what-if | Projeto | Pendente |
| 5 | Criar landing zone da aplicação | Executor autorizado | Bloqueado até autorização |
