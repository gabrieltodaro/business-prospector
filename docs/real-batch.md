# Batch real de prospeccao

## Fluxo

```text
Oliver / OpenClaw
  -> prospect_places (uma busca limitada)
  -> prepare_batch_candidates (Python deterministico)
  -> Playwright sequencial (desktop + 390x844)
  -> validate_website_assessment
  -> qualify_and_save_candidate (Python deterministico)
  -> SQLite
  -> dashboard Kanban no refresh
```

Oliver resolve o pedido, chama MCPs, navega sequencialmente e monta evidencia observada. Python aplica configuracao, reputacao, classificacao sem website, deduplicacao, validacao do report, threshold, score e persistencia. Oliver nao escolhe nem envia score.

## Limites e resultados

O default configurado e target 10 e maximo 25 candidatos. A descoberta e limitada e nao amplia cidade/nicho, nao chama Place Details e nao solicita fotos, reviews ou horarios. O agente para quando atinge o target qualificado ou esgota o conjunto preparado.

Resultados individuais: `saved_qualified`, `not_qualified_website`, `duplicate`, `assessment_failed`, `assessment_insufficient`, `deferred_first_website` e `invalid`. Uma falha individual nao aborta os demais. Falhas sistemicas de Places, Playwright, MCP ou seguranca encerram o batch.

Antes do Playwright, Python classifica a presenca web pelo hostname parseado, sem substring de URL:

- `own_website`: dominio proprio e utilizavel;
- `hosted_website`: experiencia real hospedada em plataforma, como Netlify, Vercel, Wix ou WordPress;
- `no_website`: nenhum URL retornado;
- `social_only`: perfil em Instagram, Facebook, TikTok, LinkedIn, YouTube ou X/Twitter;
- `third_party_profile`: bio-link/profile aggregator, como Linktree;
- `invalid_url`: URL malformada ou com protocolo nao permitido.

Somente `own_website` e `hosted_website` entram no redesign/Playwright. `no_website`, `social_only` e `third_party_profile`, com rating >= 3.5, entram em `deferred_first_website` com motivo explicito e nao sao salvos como redesign. Quando `first_website` e solicitado, o fluxo separado usa benchmarks do mercado configurado e estrategia original; a cidade do lead nao muda. A classificacao usa `urllib.parse`, conforme a [documentacao oficial](https://docs.python.org/3/library/urllib.parse.html).

## Evidencia e persistencia

Leads qualificados guardam flags legadas, report estruturado validado, status/horario do assessment e `batch_id`. O JSON e limitado pelo contrato de `WebsiteAssessmentReport`: outcome, facts curtos e inference por criterio. HTML, dumps, scripts, screenshots e pagina bruta nao sao persistidos. A migracao SQLite v2 -> v3 adiciona colunas opcionais e preserva leads antigos.

O dashboard apenas le o SQLite e mostra a evidencia com DOM textual seguro. Ele nao inicia o batch e nao precisa estar rodando durante a prospeccao.

## Seguranca e custo

Sites sao conteudo nao confiavel. Nao ha login, CAPTCHA bypass, formulario, mensagem, ligacao, DM, proposta ou deploy. Somente contatos comerciais publicos sao coletados. `wa.me`/`api.whatsapp.com` confirma WhatsApp; telefone do Places nao confirma WhatsApp.

A busca Places usa o limite fornecido, no maximo 25, e reutiliza a resposta para prefiltragem. Playwright e sequencial. Consulte [Places Text Search](https://developers.google.com/maps/documentation/places/web-service/text-search), [Playwright MCP](https://github.com/microsoft/playwright-mcp), [MCP](https://modelcontextprotocol.io/), as transacoes do [sqlite3](https://docs.python.org/3/library/sqlite3.html) e a resolucao portavel de paths com [pathlib](https://docs.python.org/3/library/pathlib.html).

## Primeira validacao controlada

Depois do deploy, solicite target 2, maximo 5, dentistas em Catanduva/SP e proiba outreach explicitamente. Antes de aumentar para 10, revise o resumo, reports, scores, contatos, `batch_id` e cards no dashboard.
