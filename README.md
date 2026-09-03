# viacao-cruzeiro

Projeto de Azure Functions (Python) para leitura de dados no Data Lake, geracao de relatorio PDF por filial/unidade emissora e envio por e-mail via ACS.

## Visao Geral

- Trigger principal: `process_csv` (timer).
- Entrada:
	- `raw/csv/destinatarios.csv`
	- `raw/csv/fonte/*.csv` (um ou varios arquivos)
- Saida:
	- PDF por destinatario (temporario local durante execucao)
	- envio de e-mail com anexo protegido
- Observabilidade: Application Insights

## Estrutura Principal

- `function_app.py`: logica da function (leitura, consolidacao, PDF, envio)
- `requirements.txt`: dependencias Python
- `host.json`: configuracao do host Azure Functions
- `.funcignore`: controle de arquivos no publish
- `.gitignore`: artefatos locais e segredos fora do Git

## Evolucao para Producao

O repositorio esta sendo evoluido do LAB para uma base controlada de producao. A logica atual da Function permanece preservada enquanto a fundacao de governanca e infraestrutura e preparada.

- `docs/PROJECT-SCHEDULE.md`: gates, marcos e estado de execucao;
- `docs/OPEN-ITEMS.md`: pendencias e bloqueios por gate;
- `docs/adr/`: decisoes de arquitetura;
- `docs/runbooks/`: procedimentos operacionais;
- `docs/evidence/`: evidencias de implantacao, sem segredos;
- `infra/`: infraestrutura como codigo, organizada por gate;
- `scripts/`: preflight, validacao, what-if e deploy.

O primeiro template preparado e o Gate B (`infra/bootstrap/main.bicep`), que criara somente o Resource Group e tags aprovadas. Nenhum recurso Azure sera criado sem autorizacao explicita.

## Pre-requisitos

1. Python 3.11
2. Azure Functions Core Tools v4 (`func`)
3. Azure CLI (`az`) autenticado na subscription correta
4. Permissao de acesso ao Storage/Data Lake, Function App e App Insights

## Setup Local (Windows / Git Bash)

1. Criar e ativar ambiente virtual:

```bash
python -m venv .venv311
source .venv311/Scripts/activate
```

2. Instalar dependencias:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

3. Configurar variaveis locais em `local.settings.json`.

Campos principais esperados:

- `AZURE_STORAGE_ACCOUNT_NAME`
- `ACS_CONNECTION_STRING`
- `RECIPIENTS_CSV_PATH` (padrao: `csv/destinatarios.csv`)
- `INSIGHTS_SOURCE_FOLDER` (padrao: `csv/fonte`)
- `INSIGHTS_SOURCE_FILENAME` (vazio = carrega todos os CSVs da pasta)
- `INTER_EMAIL_DELAY_SECONDS` (padrao: `2`)
- `ACS_EMAIL_MAX_ATTEMPTS` (padrao: `3`)
- (Opcional) `AOAI_*` para refinamento textual

## Regras de Dados Atuais

1. A chave oficial de filial para match e `Unidade Emissora`.
2. O campo `filial` em `destinatarios.csv` deve conter o codigo alfanumerico da unidade emissora.
3. Se `INSIGHTS_SOURCE_FILENAME` estiver vazio, o processo tenta consolidar todos os CSVs em `INSIGHTS_SOURCE_FOLDER`.
4. Para reduzir memoria, a carga prioriza colunas relevantes e filtra por unidades presentes no `destinatarios.csv`.

## Execucao Local

```bash
func start
```

Observacoes:

- Timer trigger nao depende de endpoint HTTP.
- Para validacao imediata, prefira disparo manual via portal/Test Run.

## Deploy Seguro (Producao)

Padrao recomendado neste projeto:

```bash
func azure functionapp publish func-VCruzeiro2 --no-build
```

Motivo: evitar build remoto inesperado e preservar compatibilidade de dependencias no ambiente Linux.

## Validacao Pos-Deploy

1. Confirmar trigger ativo:

```bash
az functionapp function list --name func-VCruzeiro2 --resource-group RG-VCruzeiro -o table
```

2. Confirmar execucao recente:

```bash
az monitor app-insights query --app func-VCruzeiro2 --resource-group RG-VCruzeiro --analytics-query "requests | where timestamp > ago(2h) and name == 'process_csv' | project timestamp, success, duration, operation_Id | order by timestamp desc" -o table
```

3. Confirmar trilha de negocio:

```bash
az monitor app-insights query --app func-VCruzeiro2 --resource-group RG-VCruzeiro --analytics-query "traces | where timestamp > ago(2h) | where message has_any ('Processando','PDF protegido','Email enviado','Throttle ACS','ERRO:') | project timestamp, message, operation_Id | order by timestamp desc" -o table
```

## Troubleshooting Rapido

### 1) `429` no envio de e-mail

- Existe retry no codigo (`ACS_EMAIL_MAX_ATTEMPTS`).
- Se persistir, aumentar intervalo entre envios (`INTER_EMAIL_DELAY_SECONDS`) e validar limites ACS.

### 2) Function sem trigger apos deploy

- Validar sintaxe Python local antes do publish.
- Garantir deploy com `--no-build`.
- Confirmar por `az functionapp function list`.

### 3) `python exited with code 137`

- Indica encerramento do worker por memoria/processo.
- Mitigacoes atuais: filtro por unidade emissora e leitura de colunas relevantes.
- Se necessario: reduzir volume por lote, consolidar em camada Silver (Parquet) e processar incremental.

### 4) `202` vs `206` nos logs

- `202`: aceite assincrono da execucao.
- `206`: leitura parcial de blob (normal no download em blocos pelo SDK).

## Boas Praticas de Compartilhamento

1. Nao versionar segredos (`local.settings.json` deve ficar fora do Git).
2. Manter `CHANGELOG.md` atualizado em cada ciclo relevante.
3. Usar PRs para alteracoes estruturais (match de unidade, layout de PDF, regras de negocio).
4. Evitar publicar artefatos locais (`deploy.zip`, `wheelhouse`, ambientes virtuais).

## Comandos Git Basicos

```bash
git status -sb
git add .
git commit -m "mensagem"
git pull --rebase origin main
git push origin main
```

## Contato e Handoff

Para continuidade operacional durante ferias:

1. Garantir que a equipe tenha acesso ao repositorio GitHub.
2. Garantir que a equipe tenha acesso ao Azure (Function App, Storage, App Insights).
3. Compartilhar este README e o `CHANGELOG.md` como base de operacao.
