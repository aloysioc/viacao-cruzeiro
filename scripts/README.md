# Scripts operacionais de implantação

Os scripts seguirão o padrão abaixo para cada gate:

1. `preflight-<gate>.ps1`: consulta somente leitura de pré-requisitos e políticas;
2. `validate-<gate>.ps1`: valida Bicep, parâmetros e convenções locais;
3. `what-if-<gate>.ps1`: mostra as alterações propostas sem aplicá-las;
4. `deploy-<gate>.ps1`: executa o deploy somente após revisão e autorização explícita.

Nenhum script deverá conter segredos. A execução de deploy não fará parte de um fluxo automático até que o ambiente de homologação, o pipeline e as aprovações estejam definidos.
