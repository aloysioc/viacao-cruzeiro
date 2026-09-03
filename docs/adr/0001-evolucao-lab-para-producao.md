# ADR-001 — Evolução do LAB para uma base controlada de produção

- **Estado:** Aceita
- **Data:** 03/09/2026

## Contexto

O projeto Viação Cruzeiro foi construído como LAB experimental. O cliente aprovou a evolução para produção, exigindo controle de mudanças, infraestrutura reproduzível, evidências de implantação e operação sustentável.

## Decisão

O repositório atual será evoluído, preservando o histórico e o código do LAB. A partir desta decisão, a implantação produtiva seguirá gates, infraestrutura como código, validações, `what-if`, registros de evidência, ADRs e runbooks.

O LAB continuará sendo apenas referência até que a solução seja homologada e colocada em produção no tenant do cliente. Segredos, permissões e recursos não serão copiados diretamente do LAB.

## Consequências

- O código existente será preservado e testado antes de qualquer refatoração funcional.
- Recursos Azure do cliente serão criados por infraestrutura versionada e parâmetros específicos do ambiente.
- Permissões RBAC serão implantadas e revisadas separadamente dos recursos-base.
- Deploys manuais diretos deixarão de ser o método padrão após a adoção do pipeline.
- A trigger permanecerá desabilitada até o Gate E e o aceite formal.
