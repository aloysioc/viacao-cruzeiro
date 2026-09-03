# Gate C2 — RBAC

As permissões serão definidas e implantadas separadamente dos recursos-base. O objetivo é aplicar o menor privilégio e permitir revisão explícita do executor autorizado.

Exemplos esperados:

- Function: leitura controlada em `raw` e `reference`, escrita somente onde necessário em `output`;
- publicador dos CSVs: escrita somente na área autorizada de entrada;
- operadores: leitura de logs e ações operacionais conforme o papel;
- administradores: acesso temporário e auditável durante a implantação.
