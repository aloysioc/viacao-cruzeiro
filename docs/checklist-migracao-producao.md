# Checklist — Migração do Agente Viação Cruzeiro para Produção

Use este documento na ordem apresentada. Não avance uma etapa crítica sem o aceite indicado.

> Regra de ouro: recrie o ambiente no tenant do cliente. Não copie segredos, permissões ou recursos diretamente do LAB.

## 0. Preparação e responsáveis

- [ ] Definir patrocinador do cliente e responsável funcional pelos relatórios.
- [ ] Definir responsável técnico Azure do cliente.
- [ ] Definir responsável pela origem dos CSVs.
- [ ] Definir responsável pelo domínio e remetente de e-mail.
- [ ] Definir responsável pelo suporte após a entrada em produção.
- [ ] Criar canal de comunicação para a implantação e o hypercare.
- [ ] Registrar janela de implantação e janela de contingência.
- [ ] Confirmar o orçamento aprovado: R$ 15.000/ano ou outro valor formalmente definido.

**Aceite:** contatos, papéis, orçamento e calendário aprovados por escrito.

## 1. Descoberta com o cliente

- [ ] Consolidar com Joilson as premissas já validadas no LAB: filiais, destinatários, regras de cálculo, estrutura dos CSVs e critérios de aceite dos relatórios.
- [ ] Registrar formalmente Joilson como referência funcional da fase de descoberta, enquanto o cliente confirmar os responsáveis definitivos.
- [ ] Confirmar quantidade de filiais, destinatários e relatórios esperados por dia/mês.
- [ ] Confirmar dias e horário de envio, considerando que o timer é configurado em UTC.
- [ ] Confirmar o que ocorre em feriados, fins de semana e ausência de arquivo de origem.
- [ ] Confirmar o formato, encoding, separador e nomenclatura dos CSVs de entrada.
- [ ] Confirmar quem publica os arquivos e o SLA de disponibilização.
- [ ] Confirmar campos obrigatórios em `destinatarios.csv`, arquivos de fonte e `Filiais.TXT`.
- [ ] Definir retenção de CSVs, PDFs, logs e evidências de envio.
- [ ] Definir procedimento para inclusão, remoção e alteração de destinatários.
- [ ] Validar se o uso de Azure OpenAI é obrigatório ou se o fallback por regras é aceitável.

**Aceite:** contrato de dados e regras operacionais validados pelo cliente.

## 1.1 Decisão crítica — repositório e ingestão definitiva dos CSVs

Esta é a principal decisão pendente antes de ativar a automação em produção. O timer não deve ser habilitado enquanto o fluxo abaixo não estiver definido e testado.

- [ ] Definir o repositório definitivo dos arquivos. Recomendação: Azure Data Lake Storage Gen2 na subscription do cliente.
- [ ] Definir a conta de storage, filesystem e convenção de pastas de produção.
- [ ] Definir se os arquivos serão enviados diretamente ao Data Lake ou primeiro a uma área de entrada controlada.
- [ ] Definir o sistema de origem dos CSVs e o responsável técnico por ele.
- [ ] Escolher o método de entrega: exportação automatizada do TMS, SFTP gerenciado, API, Azure Data Factory/Logic Apps ou upload manual assistido.
- [ ] Evitar upload manual como método permanente; aceitá-lo apenas em piloto ou contingência documentada.
- [ ] Definir a periodicidade: diária, dias úteis, semanal ou sob demanda.
- [ ] Definir horário de corte: até que hora o arquivo deve estar disponível para o processamento.
- [ ] Definir SLA para atraso, ausência ou republicação de arquivo.
- [ ] Definir convenção de nomes com data/hora e identificador de origem.
- [ ] Definir como identificar arquivo completo e pronto para processamento, evitando leitura durante upload.
- [ ] Definir se haverá um arquivo por execução ou múltiplos arquivos incrementais.
- [ ] Definir retenção de arquivos brutos, histórico e política de reprocessamento.
- [ ] Definir tratamento para arquivo duplicado, corrompido, vazio ou fora do padrão.
- [ ] Definir identidade de serviço e permissões mínimas para publicar e ler os arquivos.
- [ ] Validar volume médio e máximo por arquivo para confirmar memória e duração da Function.

**Aceite:** diagrama simples do fluxo de dados, responsável por cada etapa, método de entrega, horário/SLA e primeiro arquivo de produção homologado.

### Estrutura recomendada

```text
Data Lake do cliente
└── raw
    └── csv
        ├── fonte
        │   └── AAAA/MM/DD/<arquivo-origem-data-hora>.csv
        ├── destinatarios
        │   └── destinatarios.csv
        └── rejeitados
            └── AAAA/MM/DD/<arquivo-invalido>.csv
```

O processo deve publicar o arquivo em uma área temporária e movê-lo para `fonte` somente após a conclusão do upload, ou criar um marcador explícito de prontidão. Assim, a Function nunca processa arquivo parcial.

## 2. Segurança, LGPD e rede

- [ ] Classificar os dados tratados: CPF, e-mail, dados comerciais e dados operacionais.
- [ ] Validar base legal, retenção e responsáveis LGPD com o cliente.
- [ ] Definir mecanismo de proteção do PDF em produção.
- [ ] Revisar a senha baseada em três dígitos do CPF; não tratar esse método como proteção forte.
- [ ] Definir se haverá acesso público restrito ou Private Endpoints/VNet.
- [ ] Definir IPs, firewalls e DNS privados, se a política corporativa exigir.
- [ ] Definir grupos Microsoft Entra ID para administração, operação e leitura de logs.
- [ ] Aplicar princípio de menor privilégio.
- [ ] Proibir segredos no Git, código, planilhas e e-mails.

**Aceite:** arquitetura de segurança e tratamento de dados aprovados pelo responsável do cliente.

## 3. Acessos e fundação Azure

- [ ] Confirmar tenant e subscription de produção do cliente.
- [ ] Definir região primária e, se necessário, estratégia de recuperação.
- [ ] Criar Resource Group de produção seguindo o padrão de nomes do cliente.
- [ ] Criar tags obrigatórias: ambiente, sistema, centro de custo, responsável e cliente.
- [ ] Conceder acesso temporário mínimo para implantação.
- [ ] Criar grupos de acesso permanentes para operação do cliente.
- [ ] Criar budget mensal e anual no Cost Management.
- [ ] Configurar alertas de custo em 50%, 75%, 90% e 100%.
- [ ] Registrar IDs dos recursos, responsáveis e localização em inventário.

**Aceite:** subscription, Resource Group, RBAC, tags e budget disponíveis.

## 4. Provisionamento da plataforma

- [ ] Criar Storage Account Standard com Data Lake Gen2.
- [ ] Habilitar HTTPS, TLS 1.2+ e bloquear Blob público.
- [ ] Habilitar Soft Delete, versionamento e retenção compatível com a política do cliente.
- [ ] Criar filesystems `raw`, `reference` e `output`.
- [ ] Criar Azure Key Vault.
- [ ] Criar Application Insights e Log Analytics Workspace.
- [ ] Definir retenção de logs e amostragem.
- [ ] Criar Function App Flex Consumption, Linux e Python 3.11.
- [ ] Definir memória e escala inicial conforme o volume validado.
- [ ] Habilitar identidade gerenciada da Function App.
- [ ] Conceder à identidade apenas os papéis necessários no Data Lake.
- [ ] Criar Azure Communication Services e Email Service.
- [ ] Configurar e validar domínio corporativo de envio de e-mail.
- [ ] Criar Azure OpenAI e deployment do modelo aprovado, se aplicável.
- [ ] Confirmar quota, região, filtros de conteúdo e orçamento do Azure OpenAI.

**Aceite:** todos os recursos estão provisionados e cada integração responde com uma validação técnica não produtiva.

## 5. Segredos e configurações

- [ ] Armazenar chaves e connection strings no Key Vault.
- [ ] Configurar referências ao Key Vault na Function App quando suportadas.
- [ ] Registrar as configurações não secretas em infraestrutura como código ou documentação versionada.
- [ ] Configurar `AZURE_STORAGE_ACCOUNT_NAME`.
- [ ] Configurar caminhos de origem, referência e destinatários.
- [ ] Configurar endpoint, deployment e versão da API do Azure OpenAI.
- [ ] Configurar parâmetros de retentativa do ACS e intervalo entre e-mails.
- [ ] Confirmar que as credenciais do LAB não existem no ambiente do cliente.
- [ ] Confirmar que nenhum segredo aparece em logs, artefatos de build ou repositório.

**Aceite:** teste de acesso a Storage, Azure OpenAI e ACS funciona sem segredo exposto.

## 6. Código, versionamento e CI/CD

- [ ] Transferir ou espelhar o repositório para a organização do cliente.
- [ ] Proteger a branch principal e exigir revisão antes de merge.
- [ ] Fixar versões das dependências Python após teste de compatibilidade.
- [ ] Criar infraestrutura como código para os recursos de produção.
- [ ] Criar pipeline de CI: lint, análise de segurança e testes.
- [ ] Criar pipeline de CD para Homologação e Produção.
- [ ] Usar identidade federada/OIDC ou service connection segura; não usar credenciais pessoais.
- [ ] Publicar pacote de implantação versionado e rastreável.
- [ ] Registrar versão, commit e data de cada deploy.
- [ ] Definir procedimento de rollback para o pacote anterior.
- [ ] Criar ambiente de homologação separado da produção.

**Aceite:** uma alteração simples percorre CI, Homologação e Produção controlada, com rollback testado.

## 7. Dados e homologação funcional

- [ ] Carregar arquivos de teste representativos no Data Lake de homologação.
- [ ] Validar encoding, separador e múltiplos arquivos de fonte.
- [ ] Validar o mapeamento de filiais.
- [ ] Validar regra de frete final: liquidado ou valor do frete.
- [ ] Validar tabelas por cliente pagador, meses e totais.
- [ ] Validar PDFs longos e tabelas em modo landscape.
- [ ] Validar proteção do PDF e procedimento de abertura pelo destinatário.
- [ ] Validar comentários de IA e fallback determinístico.
- [ ] Validar comportamento sem arquivo, arquivo inválido e destinatário inválido.
- [ ] Validar tratamento de throttle `429` no envio.
- [ ] Enviar apenas para caixa de teste até o aceite formal.
- [ ] Comparar indicadores com uma amostra calculada manualmente pelo cliente.

**Aceite:** responsável funcional assina a validação dos números, PDF, texto e e-mail.

## 8. Observabilidade e operação

- [ ] Criar dashboard de execução, duração, falhas e e-mails enviados.
- [ ] Criar alerta para falha da Function.
- [ ] Criar alerta para ausência de execução no horário esperado.
- [ ] Criar alerta para falha de e-mail e throttling recorrente.
- [ ] Criar alerta para erro de acesso ao Storage e Azure OpenAI.
- [ ] Criar alerta de custo e consumo de tokens.
- [ ] Definir destinatários dos alertas e rota de escalonamento.
- [ ] Criar runbook para: dados ausentes, falha de e-mail, falha de IA, reprocessamento e rollback.
- [ ] Definir como habilitar/desabilitar a `process_csv` por App Setting.
- [ ] Confirmar que a trigger permanece desabilitada até a autorização de go-live.

**Aceite:** alarmes testados e runbook executado por alguém da equipe do cliente.

## 9. Piloto

- [ ] Selecionar poucas filiais e destinatários para o piloto.
- [ ] Carregar dados reais autorizados e atualizados.
- [ ] Executar manualmente em horário controlado.
- [ ] Verificar logs, totais, PDF, senha e recebimento de e-mail.
- [ ] Confirmar que não houve envio duplicado.
- [ ] Corrigir desvios e repetir o teste, se necessário.
- [ ] Aprovar expansão para todas as filiais.

**Aceite:** aceite funcional e técnico do piloto.

## 10. Go-live

- [ ] Confirmar dados de produção atualizados antes da janela.
- [ ] Confirmar lista final de destinatários.
- [ ] Confirmar domínio e remetente de e-mail.
- [ ] Confirmar budget, alertas e dashboard.
- [ ] Publicar a versão aprovada.
- [ ] Validar o commit/pacote publicado.
- [ ] Manter a trigger desabilitada durante a checagem final.
- [ ] Fazer uma execução controlada com destinatário autorizado.
- [ ] Habilitar `process_csv` somente após o aceite da execução controlada.
- [ ] Monitorar a primeira execução automática completa.
- [ ] Registrar evidências de execução, e-mail e validação.

**Aceite:** operação completa executada sem falha crítica e com validação do cliente.

## 11. Hypercare e encerramento do LAB

- [ ] Acompanhar diariamente as primeiras duas semanas de produção.
- [ ] Revisar erros, duração, custos, tokens e taxa de entrega de e-mail.
- [ ] Ajustar limites, alertas e retenção com base na operação real.
- [ ] Transferir operação e runbooks para a equipe do cliente.
- [ ] Registrar pendências e plano de evolução.
- [ ] Confirmar que o ambiente produtivo é autônomo em relação ao LAB.
- [ ] Exportar documentação e evidências necessárias do LAB.
- [ ] Definir período de retenção do LAB.
- [ ] Desabilitar ou remover recursos do LAB somente após autorização formal.

**Aceite:** cliente opera o ambiente, recebe alertas e aprova o encerramento do hypercare.

## Informações que você deve levar para a primeira reunião

- Objetivo do agente e exemplos dos relatórios gerados.
- Arquitetura executiva horizontal do projeto.
- Lista de recursos Azure necessários.
- Estimativa de custo e limite anual aprovado.
- Este checklist.
- Perguntas sobre dados, e-mail, segurança, LGPD, horário e responsáveis.

## Critérios de não avanço

Não siga para produção se ocorrer qualquer uma destas situações:

- Não há responsável funcional para validar os números.
- Não há domínio/remetente de e-mail aprovado.
- Dados reais ainda não foram validados.
- Segredos estão no código ou em arquivo compartilhado.
- Não há alerta de falha e de ausência de execução.
- Não há rollback testado.
- A proteção dos PDFs não foi aprovada sob a ótica de LGPD.
- Não há aceite formal do piloto.
