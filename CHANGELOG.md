# CHANGELOG - Projeto Cruzeiro

## [WIP] - 1 de Junho de 2026

### 🚀 Regra de Expedidos x Recebidos (alinhada com cliente)

    - se `Tipo de Baixa = LIQUIDADO` → usa `Valor Liquidado`
    - caso contrário → usa `Valor do Frete`
    - total **expedido** por unidade calculado por `Unidade Emissora` usando `Valor do Frete Final`;
    - total **recebido** por unidade calculado por `Unidade Receptora` usando `Valor do Frete Final`.
- **Nova tabela**: inclusão de `Valores por Cliente Pagador (Frete Final)` em formato mensal (3 últimos meses), filtrada por filial + `CNPJ Pagador` e exibida por `Cliente Pagador`, com métricas `QUANT`, `PESO CALC`, `VALMERC`, `FRETE TOTAL` e `CRES` mês contra mês.

## [WIP] - 28 de Maio de 2026

### 🚀 Entregas do Dia

#### 1. Match de Filial e Leitura de Fonte estabilizados
- **Correção**: leitura do CSV de insights com `sep=";"`, `skiprows=1` e fallback robusto de encoding.
- **Ajuste**: match por filial/cidade com comparação case-insensitive.
- **Resultado**: mapeamento de DOURADOS validado com dados reais.

#### 2. Métricas corrigidas (fim dos valores "absurdos")
- **Correção**: exclusão de colunas identificadoras/códigos da agregação automática.
- **Ajuste**: parsing numérico BR para colunas com vírgula decimal e ponto de milhar.
- **Resultado**: insights numéricos coerentes para operação.

#### 3. Tabelas de negócio CIF/FOB no PDF
- **Implementação**: resumo e detalhe por `Tipo do Frete` com linhas TOTAL/CIF/FOB e códigos CV/CP/FV/FP.
- **Ajuste**: layout de tabela alinhado ao padrão esperado pelo cliente.
- **Resultado**: PDF com visão executiva e detalhamento operacional.

#### 4. Conteúdo no PDF e refinos visuais
- **Mudança**: insights removidos do corpo do e-mail e mantidos apenas no anexo PDF.
- **Correções**:
    - garantia de renderização de insights mesmo com quebra de página;
    - remoção de "Acesso protegido por CPF" do cabeçalho visual;
    - espaçamento entre blocos/títulos para evitar layout "colado";
    - formatação de métricas: `R$` apenas para dados financeiros.

#### 5. Envio com tolerância a throttle ACS (429)
- **Implementação**: retry controlado no envio (com uso de `Retry-After` quando disponível).
- **Resultado**: maior resiliência em cenários de limitação temporária.

#### 6. Publicação e trigger em produção
- **Ação**: fluxo de deploy estabilizado com `func azure functionapp publish --no-build`.
- **Correção crítica**: ajuste de sintaxe em `function_app.py` (parêntese faltante) que impedia indexação correta da função.
- **Resultado**: trigger `process_csv` restaurado e ativo após publicação.

### 🔍 Validações do Dia

- Execuções confirmadas no App Insights após disparos de teste.
- Envio de e-mail confirmado em logs (`Email enviado para ...`).
- Episódios de ausência imediata de log atribuídos a latência de ingestão/execução assíncrona, não a falha definitiva.

### ⚠️ Observações Operacionais

- Timer diário: restart do app não garante execução imediata do job.
- `202 Accepted` no Test/Run indica aceite assíncrono; confirmação final deve ser feita via App Insights (`requests` e `traces`).

## [WIP] - 27 de Maio de 2026

### 🚀 Iniciativas Implementadas

#### 1. Parser CSV com Suporte a Múltiplos Separadores
- **Correção**: Função `_read_csv_from_datalake()` agora tenta `sep=";"` primeiro
- **Motivo**: CSV de origem usa ponto-e-vírgula como separador, não vírgula
- **Status**: ✅ Publicado

#### 2. Detecção Automática de Coluna de Filial
- **Mudança**: Prioridade de busca alterada para `["Cidade do remetente", "cidade do remetente", "filial", "branch", "unidade", "loja"]`
- **Motivo**: Coluna real no CSV é "Cidade do Remetente" (R maiúsculo)
- **Detecção**: Case-insensitive com fuzzy matching
- **Status**: ✅ Publicado

#### 3. Tratamento de Múltiplos Encodings
- **Correção**: Adicionado suporte para encodings: utf-8, latin-1, iso-8859-1, cp1252, windows-1252
- **Motivo**: Arquivo CSV de insights tem bytes inválidos para UTF-8 (0xa0 em posição 2897)
- **Implementação**: Loop de tentativas com fallback gracioso
- **Status**: ✅ Publicado (18:46:07 UTC)

### 🐛 Problemas Identificados

#### Erro de Codificação Persistente
- **Manifestação**: `'utf-8' codec can't decode byte 0xa0 in position 2897: invalid start byte`
- **Data**: Observado até 18:40 UTC
- **Patch**: Múltiplos encodings publicado em 18:46
- **Novo Erro (18:50)**: `list index out of range` - possivelmente em `_resolve_insights_source_path()`
- **Status**: 🔄 Requer investigação

#### Possível Causa Secundária
- Pode haver múltiplos arquivos em `csv/fonte/`
- Função assume arquivo único e tenta acessar `csv_files[0]` que pode estar vazio
- **Investigação Necessária**: Validar quantidade de CSV files na pasta

### 📋 Checklist de Próximas Ações

- [ ] Investigar erro "list index out of range"
- [ ] Validar se há múltiplos arquivos em `csv/fonte/`
- [ ] Testar encoding localmente com dados reais
- [ ] Confirmar que insights são lidos e injetados no corpo do e-mail
- [ ] Validar qualidade de texto gerado por gpt-4o-mini
- [ ] Ajustar prompt de IA conforme necessário
- [ ] Configurar logs mais detalhados em `_resolve_insights_source_path()`

### 🔍 Diagnósticos Realizados

#### CSV de Destinatários
- ✅ Localizado: `raw/csv/destinatarios.csv`
- ✅ Estrutura: email, filial, cpf
- ✅ Status: Leitura funciona

#### CSV de Insights (Fonte)
- 📍 Localizado: `raw/csv/fonte/vcs02709955vcs113608.csv`
- ✅ Separador: `;` (ponto-e-vírgula)
- ✅ Coluna Chave: "Cidade do Remetente"
- ⚠️ Encoding: Problemático (não é UTF-8 puro)
- ⚠️ Estrutura: ~100+ colunas, formato CTRC/logística

#### Azure Resources Validados
- ✅ Function App: func-VCruzeiro2 (Flex, Brazil South)
- ✅ Storage Account: dlvcruzeiro (Data Lake)
- ✅ Communication Services: Configurado com rate limiting (429 handling)
- ✅ Azure OpenAI: fou-VCruzeiro (gpt-4o-mini, capacity 75000)

### 📝 Código Alterado

#### Arquivo: `function_app.py`

**Mudança 1** - Função `_read_csv_from_datalake()`:
```python
# ANTES
def _read_csv_from_datalake(file_system, path: str, sep: str = ",") -> pd.DataFrame:
    file_client = file_system.get_file_client(path)
    download = file_client.download_file()
    return pd.read_csv(BytesIO(download.readall()), sep=sep)

# DEPOIS
def _read_csv_from_datalake(file_system, path: str, sep: str = ",") -> pd.DataFrame:
    file_client = file_system.get_file_client(path)
    download = file_client.download_file()
    content = download.readall()
    
    # Tenta múltiplos encodings (comum em arquivos de origem variada)
    encodings = ["utf-8", "latin-1", "iso-8859-1", "cp1252", "windows-1252"]
    for encoding in encodings:
        try:
            return pd.read_csv(BytesIO(content), sep=sep, encoding=encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    
    # Se nenhum encoding funcionou, tenta sem especificar (fallback)
    logging.warning("Nenhum encoding padrão funcionou para %s. Tentando fallback com erros ignorados.", path)
    return pd.read_csv(BytesIO(content), sep=sep, encoding="utf-8", errors="ignore")
```

**Mudança 2** - Chamada em `process_csv()`:
```python
# ANTES
insights_filial_col = _find_column(insights_df, ["filial", "branch", "unidade", "loja"])

# DEPOIS
insights_filial_col = _find_column(
    insights_df,
    ["Cidade do remetente", "cidade do remetente", "filial", "branch", "unidade", "loja"],
)
```

**Mudança 3** - Separador CSV de insights:
```python
# ANTES
insights_df = _read_csv_from_datalake(file_system, insights_source_path)

# DEPOIS
insights_df = _read_csv_from_datalake(file_system, insights_source_path, sep=";")
```

### 🔗 Commits/Publicações

| Data/Hora | Ação | Status | Hash/ID |
|-----------|------|--------|---------|
| 18:34:48 | Publicação (sep=";") | ✅ Sucesso | Deploy 1 |
| 18:46:07 | Publicação (múltiplos encodings) | ✅ Sucesso | Deploy 2 |

### ⚙️ Configuração Atual

**Environment Variables (Function App)**:
- `INTER_EMAIL_DELAY_SECONDS=2`
- `RECIPIENTS_CSV_PATH=csv/destinatarios.csv`
- `INSIGHTS_SOURCE_FOLDER=csv/fonte`
- `INSIGHTS_SOURCE_FILENAME=` (vazio)
- `AOAI_ENDPOINT=https://fou-vcruzeiro.cognitiveservices.azure.com/`
- `AOAI_DEPLOYMENT=gpt-4o-mini`
- `AOAI_API_KEY=` (configurado)
- `AOAI_API_VERSION=2024-10-21`

**Recurso Azure OpenAI**:
- Nome: fou-VCruzeiro
- Tipo: AIServices
- Região: Brazil South
- Deployment: gpt-4o-mini (status: Succeeded, capacity: 75000)

### 🎯 Objetivo Final

Integrar agente de IA para gerar insights por filial baseado em dados operacionais (CSV de fonte), com os insights sendo injetados no corpo do e-mail enviado automaticamente a cada 10 minutos.

**Fases Completadas**:
1. ✅ Timer trigger estável
2. ✅ Envio de e-mail com anexo PDF criptografado
3. ✅ Tratamento de throttling (429)
4. 🔄 Leitura de CSV de insights (em diagnóstico)
5. ⏳ Geração de insights por filial com IA

---

**Próxima Sessão**: Investigar erro "list index out of range" e validar leitura completa do CSV
