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

O provider fake continua disponivel e funciona sem rede. A descoberta real usa Places API (New) Text Search com `GOOGLE_MAPS_API_KEY`; nenhuma credencial e armazenada no repositorio. Playwright MCP `0.0.79` fornece evidencias estruturadas, e Oliver coordena os dois MCPs por meio de `validate_website_assessment`; o pacote Python nao acopla o dominio ao runtime OpenClaw.

## Arquitetura

- `src/business_prospector/domain`: modelos, validacao, normalizacao e scoring;
- `src/business_prospector/application`: casos de uso, configuracao e Protocols dos providers/repository;
- `src/business_prospector/infrastructure`: SQLite e providers fake;
- `src/business_prospector/infrastructure/google_places.py`: adapter REST para Places API (New);
- `src/business_prospector/mcp`: tools estruturadas do MVP;
- `skills`: Skills ativas do OpenClaw;
- `config/default.json`: thresholds, limites, cidades e pesos;
- `tests`: unitarios, integracao SQLite e pipeline fake;
- `prospector-de-sites`: implementacao original preservada como legado.

No formato Agent Plugins, o SQLite operacional fica em `${PLUGIN_DATA}/business-prospector.db`. No fallback Claude usado pelo OpenClaw 2026.7.1, fica em `~/.openclaw/data/business-prospector/business-prospector.db`. Nos dois casos, atualizar ou reinstalar o Git nao deve apagar o banco.

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

## Dashboard local

O Kanban operacional le e atualiza o mesmo SQLite do MCP. Ele e read-only exceto pela mudanca validada de status entre `new`, `qualified`, `needs_review`, `contacted`, `proposal`, `closed` e `discarded`.

Demo isolado com fixtures fake e banco temporario:

```bash
.venv/bin/python -m business_prospector.dashboard --demo
```

Banco operacional padrao:

```bash
.venv/bin/python -m business_prospector.dashboard
```

Abra `http://127.0.0.1:8765`. O servidor fica restrito ao localhost por padrao; detalhes de arquitetura, seguranca e operacao estao em [Dashboard Kanban](docs/dashboard.md).

O config default e os fixtures do demo viajam como recursos read-only do pacote, portanto `--demo` funciona no runtime instalado e independe do checkout ou do diretorio atual. Quando o MCP recebe `BUSINESS_PROSPECTOR_CONFIG`, o arquivo externo do bundle continua tendo precedencia.

## OpenClaw

O repositorio usa o formato Agent Plugins 1.0.0: `plugin.json`, `mcp.json` e Skills como filhos imediatos de `skills/`. O OpenClaw 2026.7.1 foi publicado antes do suporte a esse formato e nao examina o `plugin.json` da raiz. Para ele, `.mcp.json` oferece uma camada de compatibilidade Claude com os mesmos servidores MCP. Em uma versao que suporte Agent Plugins, a precedencia do detector escolhe `plugin.json` antes desse fallback.

1. Crie o runtime Python persistente do MCP, separado do `.venv` de desenvolvimento:

   ```bash
   cd /caminho/para/business-prospector
   python3 scripts/setup_openclaw_runtime.py
   bin/business-prospector-mcp --check
   ```

   O instalador cria `~/.openclaw/venvs/business-prospector` e instala o pacote e suas dependencias. O launcher sempre executa o `run_mcp.py` do bundle atual com esse Python. Para usar outro ambiente deliberadamente, configure `BUSINESS_PROSPECTOR_PYTHON` com o caminho absoluto do interpretador.

2. Para desenvolvimento local, revise o codigo e vincule o bundle:

   ```bash
   openclaw plugins install -l /caminho/para/business-prospector
   openclaw plugins enable business-prospector
   ```

3. Se a configuracao usa `plugins.allow`, inclua `business-prospector`.
4. Inspecione o carregamento e confirme os MCPs `business-prospector` e `playwright`:

   ```bash
   openclaw plugins inspect business-prospector --runtime
   openclaw plugins inspect business-prospector --json
   openclaw plugins doctor
   ```

   No OpenClaw 2026.7.1, o formato continuara sendo `claude`, mas `mcpServers` deve deixar de estar vazio. Para obter `bundleFormat: agent`, atualize para uma versao que contenha o suporte a Agent Plugins.
5. Inicie uma nova sessao do Oliver Queen. Use `business-prospector__prospect_fake` para o pipeline deterministico offline. No fluxo real controlado, use `prospect_places`, Playwright, `validate_website_assessment`, `find_duplicate` e somente entao `save_lead`.

No formato Agent Plugins, o OpenClaw expande `${PLUGIN_ROOT}` e `${PLUGIN_DATA}` ao iniciar o MCP. No fallback 2026.7.1, expande `${CLAUDE_PLUGIN_ROOT}`. Nenhum path absoluto do autor ou de Windows e necessario.

### Identidade de empresas

Google Place ID tem precedencia sobre identificadores derivados. Dois registros com Place IDs nao vazios e diferentes representam Places distintos e nunca sao unidos por dominio, telefone, endereco ou nome+cidade. Esses fallbacks sao usados somente quando pelo menos um registro nao possui Place ID. Dominios compartilhados de redes sociais e perfis de terceiros nao sao identificadores de empresa. A selecao de concorrentes separa correspondencia com o alvo, duplicata dentro do pool e duplicata ja persistida.

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

Redesign/criacao de website, envio de WhatsApp ou e-mail, propostas, contratos, financeiro, follow-ups, deploy, HostGator, Locaweb, Google Sheets e `leads.md`.

## Google Places

`GooglePlacesBusinessDiscoveryProvider` implementa `BusinessDiscoveryProvider` via `POST places:searchText`, usando exclusivamente Places API (New). A chave vem de `GOOGLE_MAPS_API_KEY` e e enviada somente em `X-Goog-Api-Key`.

Teste real minimo, com uma unica resposta:

```bash
python -m business_prospector.google_places_smoke --niche dentistas --city 'Catanduva, SP' --limit 1
```

Campos, custo/SKU, seguranca e troubleshooting estao em [Google Places discovery](docs/google-places.md). O guia de criacao/restricao da credencial permanece em [GOOGLE PLACES SETUP REQUIRED](docs/google-places-setup.md).

## Website assessment

O assessment real e orquestrado por Oliver: Playwright produz snapshots de acessibilidade e evidencias desktop/mobile; `business-prospector__validate_website_assessment` valida status, fatos, inferencias e elegibilidade para scoring. Falhas de browser ou acesso nunca viram flags de oportunidade. O score continua exclusivamente no Python ao salvar o lead.

Contrato, criterios, seguranca, estados de falha e o TODO do futuro pipeline para empresas sem website estao em [Website assessment with Playwright MCP](docs/website-assessment.md).

## Batch real

Oliver orquestra uma descoberta Places limitada, prefiltragem deterministica, assessments Playwright sequenciais e qualificacao/salvamento por candidato. Python controla filtros, duplicatas, thresholds e score; leads qualificados chegam ao Kanban pelo mesmo SQLite. Arquitetura, outcomes, evidencia persistida, limites e validacao controlada estao em [Batch real de prospeccao](docs/real-batch.md).

O fluxo separado de [oportunidades de primeiro site](docs/first-website.md) pesquisa ate 2–3 concorrentes comparaveis, valida facts/inferences/recommendations e usa score proprio. `opportunity_type` distingue `redesign` de `first_website`; ambos compartilham identidade, SQLite, Kanban e os mesmos status comerciais.

## Seguranca

- secrets e bancos locais sao ignorados pelo Git;
- URLs aceitas pelo dominio devem ser absolutas e `http(s)`;
- dados de websites sao explicitamente nao confiaveis nas Skills;
- o MCP nao envia mensagens nem executa deploy;
- o SQLite usa context managers, timeout, busy timeout e WAL;
- logs nao incluem credenciais nem payloads completos de websites.
