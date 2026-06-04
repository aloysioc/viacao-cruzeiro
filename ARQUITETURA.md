# Documento de Arquitetura

## 1. Objetivo
Descrever a arquitetura da solução de geração automatizada de relatórios operacionais por filial, incluindo processamento de dados, geração de PDF, distribuição por e-mail, monitoramento e uso opcional de IA para humanização de comentários analíticos.

## 2. Escopo da Solução
Entradas:
- CSV de destinatários com e-mail, filial e CPF parcial
- CSVs operacionais oriundos do BI/TMS
- Arquivo de referência de filiais

Processamento:
- Consolidação por filial (chave principal: Unidade Emissora)
- Cálculo de indicadores operacionais
- Montagem de tabelas analíticas
- Geração de comentários analíticos (com fallback sem IA)
- Renderização de relatório PDF protegido por senha

Saída:
- Envio de e-mail por destinatário com PDF anexado
- Logs e métricas de execução

## 3. Visão de Alto Nível
Fluxo principal:
1. Trigger agendado inicia a Function.
2. Function lê destinatários e dados de origem no Data Lake.
3. Function consolida dados por filial e gera conteúdo analítico.
4. Function monta e protege o PDF.
5. Function envia e-mail via Azure Communication Services.
6. Function registra logs e telemetria no Application Insights.

## 4. Componentes e Responsabilidades

### 4.1 Azure Function App
- Função principal: process_csv
- Responsável por orquestrar todo o pipeline
- Runtime Python

### 4.2 Storage Account com Data Lake Gen2
- Repositório de entrada de dados
- Estruturas utilizadas:
  - raw/csv/destinatarios.csv
  - raw/csv/fonte
  - reference/Filiais.TXT

### 4.3 Azure Communication Services
- Serviço de envio de e-mail transacional
- Entrega de relatórios protegidos para destinatários cadastrados

### 4.4 Application Insights
- Observabilidade de execução
- Métricas de sucesso, falha, duração e rastreamento operacional

### 4.5 Azure OpenAI (Opcional)
- Humanização de comentários analíticos
- Se indisponível ou não configurado, solução usa fallback determinístico por regras

## 5. Fluxo Técnico Detalhado

### 5.1 Ingestão
1. Ler destinatários.
2. Ler arquivos de dados operacionais.
3. Ler referência de filiais.
4. Aplicar seleção de colunas relevantes para reduzir volume em memória.

### 5.2 Transformação e Regras
1. Filtrar por filial com base na Unidade Emissora.
2. Normalizar colunas e aliases.
3. Calcular valor de frete final e comparações entre períodos.
4. Construir tabelas:
   - Resumo operacional
   - Expedidos e recebidos
   - UF
   - Cliente pagador (com comparativo do ano anterior)
   - Clientes sem contato (+30 dias)

### 5.3 Comentários Analíticos
1. Tentar gerar comentário via IA quando variáveis AOAI estiverem presentes.
2. Se falhar, usar comentário por regras de negócio.

### 5.4 Renderização e Segurança
1. Gerar PDF com layout tabular.
2. Aplicar páginas landscape quando necessário para tabelas largas.
3. Proteger PDF com senha derivada do CPF cadastrado.

### 5.5 Distribuição
1. Construir payload de e-mail.
2. Enviar anexo em base64.
3. Aplicar retry em casos de throttling (429).

## 6. Modelo de Dados Funcional

### 6.1 Entidade Destinatário
- email
- filial
- cpf

### 6.2 Entidade Operacional
- Unidade Emissora
- Unidade Receptora
- Tipo de Baixa
- Valor do Frete
- Valor Liquidado
- Data de Emissao
- Cliente Pagador
- CNPJ Pagador
- Login/Vendedor
- Quantidade
- Peso Calc
- ValMerc
- Campos de última ocorrência para tabela de sem contato

## 7. Segurança e Governança
- Segredos em Application Settings (não em arquivo versionado)
- Privilégio mínimo para acesso ao Storage e serviços associados
- PDF protegido para reduzir exposição de conteúdo
- Rastreabilidade por logs de execução e envio

## 8. Observabilidade
Indicadores operacionais recomendados:
- Taxa de execução bem-sucedida
- Tempo médio de processamento
- Taxa de envio concluído
- Falhas por etapa (ingestão, transformação, envio)
- Uso de IA versus fallback

## 9. Continuidade Operacional

### 9.1 Comportamentos de Resiliência
- Tolerância a colunas ausentes com aliases
- Fallback sem IA
- Retry de envio em 429

### 9.2 Modos de Falha Mais Comuns
- Dados de origem inconsistentes
- Throttling de e-mail
- Erro de parsing de data/numérico
- Indisponibilidade temporária de serviço externo

## 10. Implantação e Ambientes

### 10.1 Ambientes Recomendados
- Homologação
- Produção

### 10.2 Pacote de Implantação
- Código Python da Function
- Dependências
- Configurações por ambiente
- Permissões de identidade

### 10.3 Checklist de Go-live
1. Validar variáveis obrigatórias.
2. Validar permissões de acesso.
3. Testar execução controlada com lote reduzido.
4. Confirmar geração de PDF e envio.
5. Confirmar logs e alertas.

## 11. Escalabilidade e Custos
Custos base da arquitetura:
- Function App e plano de execução
- Storage/Data Lake
- Communication Services (e-mail)
- Application Insights

Custo opcional:
- Azure OpenAI para comentários humanizados

Direcionadores de custo:
- Quantidade de destinatários
- Frequência de execução
- Volume de dados por execução
- Quantidade de chamadas de IA por filial

## 12. Evolução Arquitetural Recomendada
1. Publicação de runbook operacional dedicado.
2. Dashboards de operação e custo.
3. Pipeline de homologação com testes de regressão de layout do PDF.
4. Versionamento de templates de relatório.
5. Trilha de auditoria funcional por destinatário.
