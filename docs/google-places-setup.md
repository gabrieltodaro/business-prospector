# GOOGLE PLACES SETUP REQUIRED

O provider real e `GooglePlacesBusinessDiscoveryProvider`, usando Places API (New) e o secret `GOOGLE_MAPS_API_KEY`. Ele e ativado explicitamente por `prospect_places`; `prospect_fake` nunca muda de comportamento com base no ambiente.

## Criar e proteger a credencial

1. Acesse o [Google Cloud Console](https://console.cloud.google.com/) com a conta que administrara a integracao da Gapps.
2. Crie um projeto dedicado, por exemplo `gapps-business-prospector`, ou selecione um projeto dedicado existente. Evite compartilhar a mesma chave com apps client-side.
3. Associe uma conta de faturamento. A Places API exige billing ativo e opera no modelo pay-as-you-go.
4. Abra **APIs & Services > Library**, procure **Places API (New)** e habilite essa API. Nao habilite a Places API legada para este projeto novo.
5. Abra **APIs & Services > Credentials > Create credentials > API key**. Para o futuro provider REST server-side, use uma API key, nao OAuth client ID nem service-account JSON.
6. Renomeie a chave para algo identificavel, como `business-prospector-server`.
7. Em **Application restrictions**, escolha **IP addresses** se a maquina dedicada tiver IP publico de saida estavel e informe somente esse IP/CIDR. Se o IP ainda nao for estavel, nao invente um: mantenha temporariamente sem restricao de aplicacao durante a validacao controlada e aplique a restricao assim que o IP for conhecido.
8. Em **API restrictions**, selecione **Restrict key** e permita somente **Places API (New)**. Salve e aguarde a propagacao.
9. Guarde a chave no mecanismo de secrets/configuracao do OpenClaw com o nome exato `GOOGLE_MAPS_API_KEY`. Nao grave a chave em `config/default.json`, `mcp.json`, `SKILL.md`, `.env` versionado ou comandos/logs compartilhados.
10. Se for validar localmente fora do OpenClaw, use uma variavel de ambiente apenas na sessao: `GOOGLE_MAPS_API_KEY`. O `.gitignore` ja exclui `.env` e `.env.*`.
11. Em **Google Maps Platform > Quotas**, defina inicialmente um limite conservador por minuto/dia e crie alertas de budget. Text Search (New) e os campos solicitados determinam o SKU cobrado.
12. Quando o provider for implementado, ele devera usar HTTPS, timeout, backoff limitado e `X-Goog-FieldMask` somente com os campos necessarios. O teste inicial deve fazer uma unica busca controlada e nunca imprimir headers ou a chave.
13. Valide no Cloud Console que a requisicao aparece somente em Places API (New), que a restricao da API esta ativa e que nao existe uso inesperado.
14. Se a chave vazar, restrinja/rotacione-a no console e remova-a do ambiente. Nunca tente apenas apagar o valor do ultimo commit: trate a chave como comprometida.

## Custos, quotas e armazenamento

- Places API (New) exige billing e usa SKUs pay-as-you-go. Consulte a [tabela atual de precos](https://developers.google.com/maps/billing-and-pricing/pricing) antes de ativar producao.
- Text Search (New) usa field masks; solicitar campos mais caros eleva a requisicao ao SKU mais alto envolvido. Veja [usage and billing](https://developers.google.com/maps/documentation/places/web-service/usage-and-billing).
- Configure quotas e alertas baixos durante calibracao. O MVP inspeciona no maximo 25 candidatos por execucao por padrao.
- As politicas do Places limitam cache/armazenamento de conteudo. `place_id` e explicitamente permitido para armazenamento indefinido, mas os demais campos precisam ser revisados contra as [politicas de Places](https://developers.google.com/maps/documentation/places/web-service/policies) antes do adapter real persistir respostas.
- Aplique as [praticas oficiais de seguranca de API keys](https://developers.google.com/maps/api-security-best-practices), incluindo restricoes de aplicacao e de API.

## Validacao esperada na proxima rodada

Depois que o secret estiver configurado, informe apenas que `GOOGLE_MAPS_API_KEY` esta disponivel; nao cole a chave no chat. Use `google_places_status` para confirmar a configuracao e siga o teste controlado em [Google Places discovery](google-places.md).
