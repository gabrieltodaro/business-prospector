# Dashboard Kanban local

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
- `contacted` — Contatado;
- `proposal` — Proposta;
- `closed` — Fechado;
- `discarded` — Descartado.

`rejected` continua aceito apenas para compatibilidade com registros antigos e e exibido em Descartado. As novas movimentacoes usam `discarded`. A migracao SQLite v1 -> v2 preserva os leads e amplia o `CHECK` de status.

Cada card mostra empresa, cidade, categoria, score persistido, rating, numero de avaliacoes, motivo de qualificacao, quantidade de issues e indicadores de website/WhatsApp/telefone/e-mail. A ordenacao prioriza score e avaliacoes. Busca, cidade, categoria e score minimo filtram a visualizacao em memoria; a API tambem aceita `status`, `city`, `category` e `min_score` em `GET /api/leads`.

O painel lateral e read-only e apresenta dados do negocio, Maps/Place ID, website, motivo e flags do assessment, contatos, score/status/fonte e timestamps. Para `first_website`, tambem mostra benchmark market, benchmarks utilizados, rating/reviews, facts, features comuns, inferences, recommendations e confidence persistidos no report validado. O breakdown do score nao e persistido nem recalculado no JavaScript.

A unica escrita e:

```http
PATCH /api/leads/{id}/status
Content-Type: application/json

{"status":"contacted"}
```

O backend aceita exatamente esse campo, valida ID e status pelo dominio e atualiza pelo repositorio existente. Em falha, o frontend restaura a coluna anterior e mostra um aviso. Nao ha edicao geral, exclusao, SQL no browser, outreach, proposta/contrato financeiro ou prospeccao disparada pela UI.

## Seguranca

- dados de prospects entram no DOM apenas por `textContent`/nos de texto; nao ha `innerHTML`;
- links externos sao habilitados apenas para URLs absolutas `http`/`https` e usam `noopener noreferrer`;
- CSP, `nosniff`, `no-referrer`, protecao contra frames e Permissions Policy sao enviados em todas as respostas;
- corpos JSON exigem tipo correto, tamanho maximo de 4 KiB, objeto valido e schema restrito;
- metodos mutantes nao suportados retornam 405 e erros internos nao enviam stack traces ou detalhes locais;
- somente `index.html`, `styles.css` e `app.js` sao servidos de um diretorio dedicado do pacote;
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
- sem fluxo para empresas sem website;
- sem fatos/inferencias Playwright ou breakdown de score persistidos;
- sem batch prospecting, outreach, edicao geral ou delete;
- a interface nao inicia Places, Playwright ou MCP; ela apenas opera leads ja persistidos.
