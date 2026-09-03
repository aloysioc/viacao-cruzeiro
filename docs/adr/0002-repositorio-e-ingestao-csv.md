# ADR-002 — Repositório e ingestão definitiva dos CSVs

- **Estado:** Em validação pelo cliente
- **Data:** 03/09/2026

## Contexto

No LAB, os arquivos de teste foram disponibilizados de forma assistida. Em produção, o local definitivo, o método de entrega, a periodicidade e o SLA dos CSVs ainda dependem de definição do cliente.

## Proposta

Utilizar Azure Data Lake Storage Gen2 na subscription do cliente como repositório definitivo. A estrutura inicial recomendada é:

```text
raw/csv/fonte/AAAA/MM/DD/<arquivo-origem-data-hora>.csv
raw/csv/destinatarios/destinatarios.csv
raw/csv/rejeitados/AAAA/MM/DD/<arquivo-invalido>.csv
reference/Filiais.TXT
output/
```

O produtor deverá publicar o arquivo em área temporária e movê-lo para a pasta final após a conclusão do upload, ou criar marcador explícito de prontidão. Upload manual só será aceito como piloto ou contingência documentada.

## Decisão pendente

Esta proposta somente será aceita após o cliente definir a origem, a identidade publicadora, o método de entrega, a periodicidade, o horário de corte, o SLA e as regras de reprocessamento.

O questionário de definição de dados e ingestão foi enviado ao cliente. O envio inicia a validação, mas não substitui o aceite formal desta decisão.
