# Dashboard Kanban local

## Website lifecycle

O Kanban possui **Internal Website** (`internal_website`) e **Sales Preview** (`sales_preview`) entre Revisar e Contatado. Ambas servem a Primeiro Site e Redesign.

Geração bem-sucedida promove um lead qualificado somente a **Internal Website**. Isso significa que existe um site válido para revisão interna, ainda sujeito a warnings, revisão visual e assets liberados apenas para draft. Falhas e conflitos preservam o status anterior.

**Sales Preview** significa que uma pessoa revisou o conteúdo visível e aprovou explicitamente os assets para publicação. A ação **Approve Sales Preview** executa a regra no backend; drag-and-drop para essa coluna é rejeitado e o card volta à origem. A aprovação não publica o site e não significa `contacted`.

O dashboard consulta `SiteDraftService` para cada slug. O status sozinho não prova que existe site: o botão **Ver Site** aparece somente quando estrutura e `site-manifest.json` são válidos. A API expõe metadata segura, nunca o path absoluto.

Sites válidos são servidos em:

```text
http://127.0.0.1:8765/sites/<lead-slug>/
```

Somente `index.html`, `styles.css` e arquivos regulares sob `assets/` são servidos. Slugs inválidos, traversal normal ou codificado, symlinks externos, manifestos, SQLite, config e arquivos de ambiente retornam 404. Não há listagem de diretórios. Consulte [pathlib](https://docs.python.org/3/library/pathlib.html), [http.server](https://docs.python.org/3/library/http.server.html) e [urllib.parse](https://docs.python.org/3/library/urllib.parse.html).

Sites gerados antes da atualização não provocam atualização automática do banco. O legado `site_ready` permanece legível e aparece como **Internal Website**, sem reescrita silenciosa. Para reconciliar outro lead, confirme **Ver Site**; só então mova aquele card para **Internal Website**. Não aprove Sales Preview sem a revisão comercial.

## Arquitetura e estado

```text
Browser
  -> HTTP API local
  -> DashboardApplication / LeadStatusService
  -> SQLiteLeadRepository
  -> SQLite
```

O dashboard reutiliza `Lead`, a validacao de status e `SQLiteLeadRepository`. Nao existe ORM, repositorio ou regra de score paralela. O SQLite operacional e a unica fonte persistente; o browser mantem apenas estado transitorio para renderizacao e drag-and-drop. Recarregar a pagina sempre consulta a API novamente.

O banco padrao e `~/.openclaw/data/business-prospector/business-prospector.db`, o mesmo fallback persistente usado pelo bundle Claude/OpenClaw 2026.7.1. Um caminho explicito pode ser passado com `--database`.

O config default e os fixtures fake do demo sao recursos read-only instalados dentro do pacote e resolvidos com `importlib.resources`. No MCP, `BUSINESS_PROSPECTOR_CONFIG` continua tendo precedencia e aponta para o config do bundle quando fornecido pelo OpenClaw. Nenhum recurso empacotado e usado para dados gravaveis.

## Executar

Ambiente de desenvolvimento, com dados fake e banco temporario:

```bash
.venv/bin/python -m business_prospector.dashboard --demo
```

Banco operacional padrao:

```bash
.venv/bin/python -m business_prospector.dashboard
```

Porta alternativa:

```bash
.venv/bin/python -m business_prospector.dashboard --port 8877
```

Abra `http://127.0.0.1:8765`. O bind padrao em `127.0.0.1`, e nao `0.0.0.0`, e uma premissa de seguranca deste MVP. Nao ha autenticacao nem suporte a exposicao remota.

## Board e operacao

As colunas persistidas sao:

- `new` — Novo;
- `qualified` — Qualificado;
- `needs_review` — Revisar;
- `internal_website` — Internal Website;
- `sales_preview` — Sales Preview;
- `contacted` — Contatado;
- `proposal` — Proposta;
- `closed` — Fechado;
- `discarded` — Descartado.

`site_ready` e `rejected` continuam aceitos apenas para compatibilidade; visualmente aparecem em Internal Website e Descartado, respectivamente. Novas gravações usam os status atuais. A migração SQLite v5 -> v6 amplia o `CHECK` sem alterar nenhuma linha existente.

Cada card mostra empresa, cidade, categoria, score persistido, rating, numero de avaliacoes, motivo de qualificacao, quantidade de issues e indicadores de website/WhatsApp/telefone/e-mail. A ordenacao prioriza score e avaliacoes. Busca, cidade, categoria e score minimo filtram a visualizacao em memoria; a API tambem aceita `status`, `city`, `category` e `min_score` em `GET /api/leads`.

O painel lateral e read-only e apresenta dados do negocio, Maps/Place ID, website, motivo e flags do assessment, contatos, score/status/fonte e timestamps. Para `first_website`, tambem mostra benchmark market, benchmarks utilizados, rating/reviews, facts, features comuns, inferences, recommendations e confidence persistidos no report validado. O breakdown do score nao e persistido nem recalculado no JavaScript.

Uma escrita comum é:

```http
PATCH /api/leads/{id}/status
Content-Type: application/json

{"status":"contacted"}
```

O backend aceita exatamente esse campo, valida ID e status pelo domínio e atualiza pelo repositório existente. `internal_website` exige artefato válido; `sales_preview` nunca é aceito por essa rota. A rota separada de aprovação exige confirmação de conteúdo, lista explícita de assets e identidade do revisor, revalida o artefato e grava no manifesto `preview_slug`, `preview_status=approved_not_published`, `preview_url=null`, horário e revisor. Em falha, o frontend preserva o estado e mostra razões determinísticas. Não há deploy, outreach ou edição geral.

## Seguranca

- dados de prospects entram no DOM apenas por `textContent`/nos de texto; nao ha `innerHTML`;
- links externos sao habilitados apenas para URLs absolutas `http`/`https` e usam `noopener noreferrer`;
- CSP, `nosniff`, `no-referrer`, protecao contra frames e Permissions Policy sao enviados em todas as respostas;
- corpos JSON exigem tipo correto, tamanho maximo de 4 KiB, objeto valido e schema restrito;
- metodos mutantes nao suportados retornam 405 e erros internos nao enviam stack traces ou detalhes locais;
- os assets do dashboard continuam em allowlist; sites validados expõem somente `index.html`, `styles.css` e arquivos sob `assets/`;
- banco, config, Git, service-env, logs e demais paths nunca entram no file server; traversal retorna 404;
- nao ha shell execution nem SQL construido a partir de entrada HTTP;
- SQLite continua usando context managers, WAL, busy timeout e validacoes do dominio.

O dashboard nao le nem exibe secrets. Conteudo de sites e prospects deve continuar sendo tratado como nao confiavel.

## Mac Mini

Apos atualizar o checkout, reprovisione o runtime para instalar o pacote e seus assets:

```bash
cd /caminho/para/business-prospector
git pull --ff-only origin openclaw-port
python3 scripts/setup_openclaw_runtime.py
bin/business-prospector-mcp --check
~/.openclaw/venvs/business-prospector/bin/python -m business_prospector.dashboard
```

Entao abra `http://127.0.0.1:8765` no proprio Mac Mini (ou use um tunel deliberado e protegido; hospedagem remota esta fora do MVP).

## Limites atuais

- sem autenticacao ou hosting publico;
- aprovação de Sales Preview é simples e explícita; não há workflow editorial complexo;
- sem fatos/inferencias Playwright ou breakdown de score persistidos;
- sem batch prospecting, outreach, edicao geral ou delete;
- a interface nao inicia Places, Playwright ou MCP; ela apenas opera leads ja persistidos.
