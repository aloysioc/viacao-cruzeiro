# Gate B — Bootstrap

Este gate cria exclusivamente o Resource Group da aplicação e aplica as tags aprovadas pelo cliente.

Antes do deploy, confirmar:

- subscription e região do cliente;
- nome do Resource Group conforme padrão corporativo;
- tags obrigatórias;
- budget e responsáveis;
- executor autorizado.

O template não cria Storage, Function, identidades, permissões ou segredos.
