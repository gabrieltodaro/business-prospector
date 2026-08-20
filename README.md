# business-prospector

MVP de prospeccao local da **Gapps Tecnologia** para **OpenClaw**, operado pelo agente **Oliver Queen**. O objetivo atual e encontrar empresas brasileiras com boa reputacao e website fraco, estruturar a avaliacao, evitar duplicatas, calcular um score deterministico e persistir os melhores leads em SQLite.

Este fork deriva de `ArrecheNeto/gemini-prospector`, criado por Helio Arreche. Os componentes originais foram preservados em `prospector-de-sites/` para trabalho futuro; eles nao participam do fluxo ativo do MVP.

## Escopo ativo

```text
DiscoveryProvider
  -> filtros configuraveis de reputacao
  -> deduplicacao em camadas
  -> WebsiteAssessmentProvider / Playwright
  -> flags estruturadas do website
  -> scoring Python 0-100
  -> SQLiteLeadRepository
  -> ranking
```

O provider inicial e fake e funciona sem rede. Google Places ainda nao esta implementado. Playwright MCP `0.0.79` esta fixado no bundle para assessment de websites, evitando uma dependencia flutuante em `@latest`.

## Arquitetura

- `src/business_prospector/domain`: modelos, validacao, normalizacao e scoring;
- `src/business_prospector/application`: casos de uso, configuracao e Protocols dos providers/repository;
- `src/business_prospector/infrastructure`: SQLite e providers fake;
- `src/business_prospector/mcp`: tools estruturadas do MVP;
- `skills`: Skills ativas do OpenClaw;
- `config/default.json`: thresholds, limites, cidades e pesos;
- `tests`: unitarios, integracao SQLite e pipeline fake;
- `prospector-de-sites`: implementacao original preservada como legado.

O SQLite operacional fica em `${PLUGIN_DATA}/business-prospector.db`, fora do diretorio instalado do plugin. Atualizar ou reinstalar o Git nao deve apagar o banco.

## Instalacao local

Requer Python 3.11+ e, para o browser MCP, Node.js 18+ com `npx`.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest
```

Pipeline simulado, sem rede:

```bash
.venv/bin/python -m business_prospector.demo --niche dentistas --city Catanduva
```

Por padrao o demo cria o banco em um diretorio temporario. Use `--database /caminho/seguro/prospector.db` apenas quando quiser preservar o resultado.

## OpenClaw

O repositorio usa o formato Agent Plugins 1.0.0: `plugin.json`, `mcp.json` e Skills como filhos imediatos de `skills/`.

1. Instale as dependencias no Python 3 que estara no `PATH` do processo OpenClaw:

   ```bash
   python3 -m pip install /caminho/para/business-prospector
   ```

2. Para desenvolvimento local, revise o codigo e vincule o bundle:

   ```bash
   openclaw plugins install -l /caminho/para/business-prospector
   openclaw plugins enable business-prospector
   ```

3. Se a configuracao usa `plugins.allow`, inclua `business-prospector`.
4. Inspecione o carregamento com `openclaw plugins inspect business-prospector` e confirme os MCPs `business-prospector` e `playwright`.
5. Inicie uma nova sessao do Oliver Queen e use `prospector-setup` ou solicite uma prospeccao. Enquanto o provider for `fake`, use `business-prospector__prospect_fake` para validacao offline.

O OpenClaw expande `${PLUGIN_ROOT}` e `${PLUGIN_DATA}` ao iniciar o MCP. Nenhum path absoluto do autor ou de Windows e necessario.

Documentacao oficial usada para o bundle:

- [OpenClaw plugin bundles](https://docs.openclaw.ai/plugins/bundles)
- [OpenClaw plugins CLI](https://docs.openclaw.ai/cli/plugins)
- [OpenClaw Skills](https://docs.openclaw.ai/skills)
- [Agent Plugins MCP servers](https://agent-plugins.org/plugin-authors/mcp-servers)

## Deduplicacao

A ordem e explicita e testada:

1. `external_place_id`: correspondencia exata;
2. dominio normalizado: duplicata provavel;
3. telefone/WhatsApp normalizado: duplicata provavel;
4. nome normalizado + cidade: duplicata possivel;
5. endereco normalizado: duplicata possivel.

## Scoring

O LLM registra somente observacoes estruturadas. Python calcula o resultado:

- Business Quality: ate 40, usando rating e review count;
- Website Opportunity: ate 40, usando a quantidade de problemas, com teto em quatro;
- Contactability: ate 20, priorizando WhatsApp confirmado, telefone, e-mail e Instagram.

Pesos e filtros estao centralizados em `config/default.json` e serao calibrados com leads reais.

## Fora do MVP ativo

Dashboard, redesign/criacao de website, envio de WhatsApp ou e-mail, propostas, contratos, financeiro, follow-ups, deploy, HostGator, Locaweb, Google Sheets e `leads.md`.

## Google Places

O codigo contem apenas a abstracao `BusinessDiscoveryProvider`; nenhuma chamada Google e feita. Siga [GOOGLE PLACES SETUP REQUIRED](docs/google-places-setup.md) para preparar a credencial de forma segura. Depois disso sera implementado `GooglePlacesBusinessDiscoveryProvider`, preferencialmente com Places API (New), sem alterar as regras de negocio.

## Seguranca

- secrets e bancos locais sao ignorados pelo Git;
- URLs aceitas pelo dominio devem ser absolutas e `http(s)`;
- dados de websites sao explicitamente nao confiaveis nas Skills;
- o MCP nao envia mensagens nem executa deploy;
- o SQLite usa context managers, timeout, busy timeout e WAL;
- logs nao incluem credenciais nem payloads completos de websites.
