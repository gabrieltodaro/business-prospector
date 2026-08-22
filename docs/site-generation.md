# Geração local de primeiro site

O gerador cria um rascunho estático para revisão interna a partir de um lead `first_website` qualificado e de pesquisa de mercado completa e validada. Ele não consulta SQLite de produção, Google ou Playwright; não publica, envia mensagem nem cria proposta.

## Arquitetura e entradas

`FirstWebsiteSiteBrief` mantém fatos do alvo, resumo estruturado da pesquisa, estratégia, hipóteses e informações ausentes. `SiteGenerationService` escolhe uma policy de categoria e renderiza arquivos controlados. A policy de dentistas só adapta linguagem genérica e placeholders; novas categorias podem registrar outra policy sem alterar o renderizador.

São obrigatórios:

- `opportunity_type=first_website` e `status=qualified`;
- nome, categoria, cidade, reputação pública e slug seguro;
- pesquisa `complete`, com pelo menos dois benchmarks válidos;
- dados públicos opcionais de endereço, telefone, WhatsApp confirmado, Instagram e mapa.

Informação ausente permanece em `missing_information` e aparece como pendência. O gerador não inventa biografia, credenciais, tratamentos, horários, preços, depoimentos ou alegações clínicas. WhatsApp só vira CTA quando número e confirmação estão presentes.

## Originalidade e segurança

Os benchmarks informam padrões de mercado, mas seus textos, HTML, domínios, imagens e identidade não entram no site. O HTML é produzido por templates internos com escaping; dados de pesquisa hostis permanecem dados. URLs aceitas são validadas e links externos em nova aba usam `noopener noreferrer`.

O diretório é sempre `<sites_root>/<lead_slug>`. Slugs com travessia são recusados. A geração usa diretório temporário e troca atômica; um site existente gera conflito, a menos que `overwrite=true` seja solicitado explicitamente. O MCP controla `sites_root` como `<BUSINESS_PROSPECTOR_DATA_DIR>/sites`, sem aceitar destino enviado pelo agente.

Estrutura:

```text
sites/<lead-slug>/
  index.html
  styles.css
  assets/
  site-manifest.json
  README.md
```

O manifesto contém identidade mínima, batch de origem, mercado benchmark, versões, arquivos e pendências. Não contém pesquisa integral nem segredos.

## Demo e preview

Gere somente com a fixture offline:

```bash
python -m business_prospector.site_demo --sites-root ./sites
```

Faça preview, restrito a loopback e ao diretório do site:

```bash
python -m business_prospector.site_preview clinica-sorriso-exemplo-catanduva-sp --sites-root ./sites --port 8765
```

Abra `http://127.0.0.1:8765`. O servidor não expõe config, banco ou repositório.

O MCP oferece `generate_first_website_draft(lead, research, overwrite=false)`. A operação gera apenas artefato local e metadata estruturada; não retorna URL pública.

Para um lead persistido, a ferramenta exige `lead.id` e relê o registro no SQLite. Somente depois de gerar e validar o artefato ela muda o status comercial de `qualified` para `site_ready`. Falha ou conflito preserva o status anterior.

Artefato, oportunidade e status são conceitos independentes:

- `opportunity_type`: `first_website` ou `redesign`;
- `status`: etapa comercial, incluindo `site_ready`;
- `site_draft.exists`: prova read-only de que há um artefato válido.

O dashboard detecta artefatos existentes sem alterar leads. Um site criado antes desta versão aparece com **Ver Site**, mas o usuário precisa arrastar explicitamente o card para **Site Pronto** se desejar reconciliar o status.

## Limites deliberados e próximos passos

- TODO: conjuntos reutilizáveis de benchmarks com TTL/cache.
- TODO: aprovação humana obrigatória antes de deploy.
- TODO: workflow de deploy Locaweb após aprovação.
- TODO: proposta a partir de site aprovado.
- TODO: outreach somente com autorização explícita de Gabriel.
- TODO: aquisição opcional de assets com proveniência e direitos verificados.
- TODO: refinamento de conteúdo aprovado pelo cliente após interesse/contrato.

Referências normativas: [pathlib](https://docs.python.org/3/library/pathlib.html), [html.parser](https://docs.python.org/3/library/html.parser.html), [http.server](https://docs.python.org/3/library/http.server.html), [MDN HTML](https://developer.mozilla.org/docs/Web/HTML), [MDN CSS](https://developer.mozilla.org/docs/Web/CSS) e [WCAG](https://www.w3.org/WAI/standards-guidelines/wcag/).
