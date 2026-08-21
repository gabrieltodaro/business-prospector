---
name: prospector-setup
description: Configure o MVP de prospeccao local da Gapps no OpenClaw; use no primeiro uso ou ao ajustar regiao, filtros, limites ou providers.
---

# Setup do Business Prospector

Configure somente a prospeccao operada por Oliver Queen. Leia `{baseDir}/../../config/default.json`, mostre os valores atuais e altere apenas mediante pedido do usuario.

## Configuracao ativa

- regiao e cidades;
- nota e quantidade minima de avaliacoes;
- meta e limite de negocios inspecionados;
- quantidade minima de problemas do website;
- pesos de scoring, que devem totalizar 100;
- provider de discovery e provider de browser.

O banco fica no `PLUGIN_DATA` fornecido pelo OpenClaw. Nunca grave dados operacionais dentro do plugin. A chave do Google deve vir do secret `GOOGLE_MAPS_API_KEY`; nunca coloque credenciais nesta Skill, no Git ou em logs. Use `google_places_status` para verificar apenas se esta configurada.

O provider fake continua disponivel para testes offline. `prospect_places` faz descoberta real via Places API (New), mas nao executa assessment nem persiste leads. O browser esperado para assessment manual e Playwright disponibilizado pelo OpenClaw.

Nao configure dashboard, hospedagem, Gmail, Drive, propostas, contratos, financeiro ou envio de mensagens.
