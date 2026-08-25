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

## Qualidade visual e assets

A estratégia visual 2.0 usa hero orientado por imagem, prova pública, ritmo editorial, seções sem caixas repetitivas, CTA final e grids responsivos. Na ausência de fotografia aprovada, uma ilustração decorativa local e authored mantém o draft visualmente completo; pendências ficam no README, manifesto e warnings, não em grandes placeholders visíveis.

`SiteAsset` separa três decisões:

- `source_type`: de onde veio (`existing_business_site`, referência social, stock, generated etc.);
- `rights_status`: o que sabemos sobre direitos (`likely_business_owned`, `licensed`, `generated`, `unknown`, `do_not_use`);
- `approval_status`: em qual etapa pode ser usado (`candidate`, `approved_for_draft`, `approved_for_publish`, `rejected`).

Um arquivo público não é automaticamente reutilizável. Imagens observadas no site atual de uma oportunidade `redesign` podem ser classificadas como `likely_business_owned` e `approved_for_draft`, nunca como aprovadas para publicação. A observação precisa corresponder à identidade do negócio e ter sido descoberta a partir do website atual. Assets de concorrentes e identity mismatch são rejeitados.

Imagens de Instagram, Facebook, TikTok e outras redes são apenas referências: não são aprovadas nem baixadas automaticamente. Não há bypass de login, scraping social ou screenshot de feed. Stock permanece com direitos desconhecidos até comprovação de licença; integrações com fornecedores e geração por API não fazem parte desta versão.

`SiteAssetCandidateValidator` valida observações sem rede. `SiteAssetIngestionService` recebe um transport/fetcher controlado, revalida MIME, assinatura binária e limite de 8 MiB, recusa SVG externo, cria nome a partir da key segura, calcula SHA-256 e grava atomicamente sob `assets/`. O transport não está exposto para Oliver escrever paths arbitrários. URLs são HTTP(S), sem credenciais ou parâmetros secretos.

Assets aceitos são copiados para o site; o HTML nunca hotlinka imagens. `<img>` usa `alt`, dimensões quando conhecidas, `object-fit`, `fetchpriority` no hero e `loading="lazy"` abaixo da dobra. Alt desconhecido permanece vazio em vez de descrever conteúdo não identificado. Consulte [pathlib](https://docs.python.org/3/library/pathlib.html), [urllib.request](https://docs.python.org/3/library/urllib.request.html), [urllib.parse](https://docs.python.org/3/library/urllib.parse.html), [mimetypes](https://docs.python.org/3/library/mimetypes.html), [MDN img](https://developer.mozilla.org/docs/Web/HTML/Reference/Elements/img), [MDN picture](https://developer.mozilla.org/docs/Web/HTML/Reference/Elements/picture) e [WCAG](https://www.w3.org/WAI/standards-guidelines/wcag/).

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

Para um lead persistido, a ferramenta exige `lead.id` e relê o registro no SQLite. Somente depois de gerar e validar o artefato ela muda o status de `qualified` para `internal_website`. Geração nunca cria `sales_preview`; falha ou conflito preserva o status anterior.

Artefato, oportunidade e status são conceitos independentes:

- `opportunity_type`: `first_website` ou `redesign`;
- `status`: etapa comercial (`internal_website` para revisão interna; `sales_preview` após aprovação humana);
- `site_draft.exists`: prova read-only de que há um artefato válido.

O dashboard detecta artefatos existentes sem alterar leads. `site_ready` legado é mostrado como **Internal Website**, sem migração de dados. Um artefato válido pode ser reconciliado manualmente para Internal Website; Sales Preview exige a operação controlada de aprovação.

## Aprovação para Sales Preview

`SalesPreviewReadiness` revalida estrutura, identidade, oportunidade, conteúdo visível, metadata responsiva, paths e direitos dos assets. `approved_for_draft` é suficiente apenas internamente. Para preview público, cada asset precisa de `approved_for_publish`; assets de site existente nunca recebem essa promoção automaticamente. Assets gerados e com direitos `generated` são elegíveis pela política, mas continuam sujeitos à revisão humana.

`approve_sales_preview` exige confirmação explícita do conteúdo, assets indicados e revisor. Ela registra no manifesto um `preview_slug` proposto e seguro, metadata de aprovação e URL nula. O slug é apenas uma intenção para um futuro endereço como `drlaura.gapps.tech`; disponibilidade, DNS e publicação não são realizados.

`PreviewDeploymentProvider` mantém hosting fora da aplicação. O primeiro adapter é o [HostGator/cPanel UAPI](cpanel-deployment.md), configurado apenas por secrets do runtime. Ele não publica automaticamente ao aprovar, não implementa DNS e não usa FTP, senha cPanel, SSH ou Cloudflare.

## Limites deliberados e próximos passos

- TODO: conjuntos reutilizáveis de benchmarks com TTL/cache.
- TODO: biblioteca reutilizável de assets por lead / asset review sheet.
- TODO: workflow de deploy Locaweb após aprovação.
- TODO: proposta a partir de site aprovado.
- TODO: outreach somente com autorização explícita de Gabriel.
- TODO: aquisição opcional de assets com proveniência e direitos verificados.
- TODO: refinamento de conteúdo aprovado pelo cliente após interesse/contrato.

Referências normativas: [pathlib](https://docs.python.org/3/library/pathlib.html), [html.parser](https://docs.python.org/3/library/html.parser.html), [http.server](https://docs.python.org/3/library/http.server.html), [MDN HTML](https://developer.mozilla.org/docs/Web/HTML), [MDN CSS](https://developer.mozilla.org/docs/Web/CSS) e [WCAG](https://www.w3.org/WAI/standards-guidelines/wcag/).
