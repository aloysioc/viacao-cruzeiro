# Viação Cruzeiro — Pendências de produção

Atualizado em 03/09/2026. Itens encerrados devem permanecer registrados com a decisão e a data.

| ID | Item | Estado | Bloqueia |
|---|---|---|---|
| GAP-001 | Confirmar responsável funcional definitivo; Joilson é a referência do LAB até confirmação | Pendente de confirmação | Homologação funcional |
| GAP-002 | Definir responsável técnico pelo sistema que gera os CSVs | Pendente | Ingestão de dados |
| GAP-003 | Definir repositório definitivo dos CSVs | Em validação pelo cliente; questionário enviado. Recomendação: ADLS Gen2 do cliente | Gates C1 e D |
| GAP-004 | Definir método, periodicidade, horário de corte e SLA de entrega dos CSVs | Em validação pelo cliente; questionário enviado | Gate D e ativação da agenda |
| GAP-005 | Definir subscription, região, padrão de nomes e tags corporativas | Pendente | Gate B |
| GAP-006 | Definir executor autorizado a criar role assignments | Pendente | Gate C2 |
| GAP-007 | Confirmar domínio e remetente corporativos para envio de e-mail | Pendente | Gate C3 |
| GAP-008 | Definir retenção de CSVs, PDFs, logs e evidências | Pendente | Gates C1 e C3 |
| GAP-009 | Confirmar se Azure OpenAI é obrigatório ou se o fallback determinístico é aceitável | Pendente | Gate C3 |
| GAP-010 | Definir destinatários, alertas e rota de escalonamento | Pendente | Gates C3 e F |
| GAP-011 | Definir organização de destino do repositório e o modelo de acesso do cliente | Pendente | Antes do go-live |
| GAP-012 | Homologar primeiro CSV representativo no ambiente do cliente | Não iniciado | Gate D |

## Regra de bloqueio

Nenhum deploy produtivo será executado enquanto os itens que bloqueiam o gate correspondente não estiverem resolvidos e registrados.
