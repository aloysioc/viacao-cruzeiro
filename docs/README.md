# Documentação de produção

| Documento | Finalidade |
|---|---|
| [PROJECT-SCHEDULE.md](PROJECT-SCHEDULE.md) | Gates, marcos e estado de execução |
| [OPEN-ITEMS.md](OPEN-ITEMS.md) | Pendências, responsáveis e bloqueios |
| [checklist-migracao-producao.md](checklist-migracao-producao.md) | Checklist completo de migração do LAB |
| [adr/](adr/) | Decisões arquiteturais registradas |
| [runbooks/](runbooks/) | Procedimentos de implantação e operação |
| [evidence/](evidence/) | Evidências de cada gate, sem segredos |
| [architecture/](architecture/) | Diagramas executivos da solução |
| [questionario-dados-e-ingestao-producao.docx](questionario-dados-e-ingestao-producao.docx) | Questionário para definição de dados e ingestão |

## Princípio de controle

Não executar deploy produtivo sem preflight, validação, revisão do `what-if`, autorização explícita e evidência pós-implantação.
