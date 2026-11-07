# Geração local de primeiro site

O gerador cria um rascunho estático para revisão interna a partir de um lead `first_website` qualificado e de pesquisa de mercado completa e validada. Ele não consulta SQLite de produção, Google ou Playwright; não publica, envia mensagem nem cria proposta.

## Arquitetura e entradas

`FirstWebsiteSiteBrief` mantém fatos do alvo, pesquisa validada, conteúdo revisado, estratégia e informações ausentes. A versão 3 transforma observações e prioridades respaldadas por evidências em estratégia determinística, modelo de conteúdo e componentes HTML/CSS. Policies pequenas para dentistas, restaurantes e categoria genérica escolhem seções e hierarquia sem inventar fatos. Consulte o [relatório de Phase 2](phase-2-implementation.md) para contratos, exemplos, testes e compatibilidade.

São obrigatórios:

- `opportunity_type=first_website` e `status=qualified`;
- nome, categoria, cidade, reputação pública e slug seguro;
- pesquisa `complete`, com pelo menos dois benchmarks válidos;
- dados públicos opcionais de endereço, telefone, WhatsApp confirmado, Instagram e mapa.

Informação ausente permanece em `missing_information` e aparece como pendência interna. `reviewed_content` opcional exige identidade do alvo, revisor, timestamp e fontes para cada fato; pesquisa de concorrentes não comprova fatos do negócio. O gerador não inventa biografia, credenciais, tratamentos, horários, preços, depoimentos ou alegações clínicas. WhatsApp só vira CTA quando número e confirmação estão presentes.

## Atualizar pesquisa de um lead existente

`refresh_first_website_research(lead_id, research)` substitui explicitamente a pesquisa
de um lead `first_website` que ainda está `qualified`. Use o `selection_id` de uma
seleção persistida para esse mesmo alvo e envie o relatório completo com observações
reais. O Python valida seleção, alvo, benchmarks, frequências e os critérios atuais
de qualificação antes de persistir. Não reutilize números inválidos nem invente
evidências para preencher pesquisa histórica.

O retorno contém `data.lead` e `data.previous_artifact_path`. Depois do sucesso, chame
`generate_first_website_draft(lead=data.lead, research=data.lead.market_research)`.
O lead permanece `qualified` até a geração concluir; somente então passa para
`internal_website`. `revise_first_website_draft` continua reservado a drafts internos
ou previews aprovados ainda não publicados; não altera pesquisa nem requalifica leads.

A atualização transacional modifica somente pesquisa, status da pesquisa e timestamp
da pesquisa. Identidade, contatos, score, motivo de qualificação, batch e demais dados
permanecem intactos. Um token do registro inteiro rejeita alterações concorrentes.
O carregamento especial para refresh não interpreta a pesquisa antiga; as operações
normais continuam exigindo sua validação. Isso permite substituir registros legados
com frequências inválidas, seleção ausente ou JSON inválido, sem migração ou reparo
automático de evidências. SQLite permanece na versão 8.

Um draft antigo do mesmo lead é movido integralmente para
`<data_dir>/site-revisions/<slug>/<archive_id>`, fora da raiz servida, tornando sua
aprovação indisponível para publicação. O caminho é retornado para revisão; conteúdo
revisado e assets não são transferidos automaticamente para o novo draft. Forneça-os
explicitamente na geração, usando os contratos existentes. Falhas de arquivo ou de
transação restauram o draft anterior e preservam a pesquisa antiga. O lock existente
serializa refresh, geração, aprovação e publicação. Reservas de deployment, publicações,
identidade divergente e metadata insegura bloqueiam o refresh. Outros status não são
rebaixados para `qualified`. Como na revisão existente, o arquivo é recuperável para
falhas capturadas; não há journal de recuperação automática entre filesystem e SQLite
para interrupção abrupta do processo.

## Originalidade e segurança

Os benchmarks informam padrões de mercado, mas seus textos, HTML, domínios, imagens e identidade não entram no site. O HTML é produzido por templates internos com escaping; dados de pesquisa hostis permanecem dados. URLs aceitas são validadas e links externos em nova aba usam `noopener noreferrer`.

## Qualidade visual e assets

A estratégia visual 3.0 compõe serviços/cardápio, biografia, equipe/credenciais, horários, FAQ, galeria, reputação, localização e contato somente quando justificados por fatos e pesquisa. Três paletas originais, duas composições de hero e tipografia local tornam a escolha visual determinística e explicável. Na ausência de fotografia aprovada, uma ilustração decorativa local e authored mantém o draft visualmente completo; pendências ficam no README, manifesto e warnings, não em grandes placeholders visíveis.

`SiteAsset` separa três decisões:

- `source_type`: de onde veio (`existing_business_site`, referência social, stock, generated etc.);
- `rights_status`: o que sabemos sobre direitos (`likely_business_owned`, `licensed`, `generated`, `unknown`, `do_not_use`);
- `approval_status`: em qual etapa pode ser usado (`candidate`, `approved_for_draft`, `approved_for_publish`, `rejected`).

Um arquivo público não é automaticamente reutilizável. Imagens observadas no site atual de uma oportunidade `redesign` podem ser classificadas como `likely_business_owned` e `approved_for_draft`, nunca como aprovadas para publicação. A observação precisa corresponder à identidade do negócio e ter sido descoberta a partir do website atual. Assets de concorrentes e identity mismatch são rejeitados.

Imagens de Instagram, Facebook, TikTok e outras redes são apenas referências: não são aprovadas nem baixadas automaticamente. Não há bypass de login, scraping social ou screenshot de feed. Stock permanece com direitos desconhecidos até comprovação de licença; integrações com fornecedores e geração por API não fazem parte desta versão.

`SiteAssetCandidateValidator` valida observações sem rede. `SiteAssetIngestionService` recebe um transport/fetcher controlado, revalida MIME, assinatura binária e limite de 8 MiB, recusa SVG externo, cria nome a partir da key segura, calcula SHA-256 e grava atomicamente sob `assets/`. O transport não está exposto para Oliver escrever paths arbitrários. URLs são HTTP(S), sem credenciais ou parâmetros secretos.

Assets aceitos são copiados para o site; o HTML nunca hotlinka imagens. `<img>` usa `alt`, dimensões quando conhecidas, `object-fit`, `fetchpriority` no hero e `loading="lazy"` abaixo da dobra. Alt desconhecido permanece vazio em vez de descrever conteúdo não identificado. Consulte [pathlib](https://docs.python.org/3/library/pathlib.html), [urllib.request](https://docs.python.org/3/library/urllib.request.html), [urllib.parse](https://docs.python.org/3/library/urllib.parse.html), [mimetypes](https://docs.python.org/3/library/mimetypes.html), [MDN img](https://developer.mozilla.org/docs/Web/HTML/Reference/Elements/img), [MDN picture](https://developer.mozilla.org/docs/Web/HTML/Reference/Elements/picture) e [WCAG](https://www.w3.org/WAI/standards-guidelines/wcag/).

O diretório é sempre `<sites_root>/<lead_slug>`. Slugs com travessia são recusados. A geração valida primeiro um diretório temporário; um site existente gera conflito, a menos que a revisão seja explícita. A revisão arquiva o artefato anterior fora da raiz pública e restaura-o em falhas capturadas de instalação/persistência. Não há transação única entre filesystem e SQLite: interrupções abruptas podem exigir reconciliação manual. Artefatos publicados não podem ser substituídos. O MCP controla `sites_root` como `<BUSINESS_PROSPECTOR_DATA_DIR>/sites`, sem aceitar destino enviado pelo agente.

Estrutura:

```text
sites/<lead-slug>/
  index.html
  styles.css
  assets/
  site-manifest.json
  README.md
```

O manifesto privado contém identidade, batch, mercado benchmark, versões, estratégia e suas evidências, fatos revisados, modelo de conteúdo, proveniência de assets, identidade de revisão e pendências. Não contém pesquisa integral nem deve receber segredos. Apenas HTML, CSS e assets do inventário permitido são publicáveis.

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

O MCP oferece `generate_first_website_draft(lead, research, overwrite=false, reviewed_content=null, asset_keys=null)`. Assets são selecionados por chave na biblioteca local revisada `<data_dir>/reviewed-assets/<lead_slug>/asset-manifest.json`; a ferramenta não aceita paths ou concessão de direitos. O contrato e seus limites estão no [relatório de Phase 2](phase-2-implementation.md). A operação gera apenas artefato local e metadata estruturada; não retorna URL pública.

Para gerar as duas demonstrações sintéticas com pesquisa/fatos distintos, use `python -m business_prospector.personalized_demo --output /tmp/novo-diretorio-demo`. O destino deve ser novo e explícito; nenhum download ou publicação ocorre. Toda página nova inclui divulgação de demonstração independente e `noindex,nofollow,noarchive`.

`revise_first_website_draft(lead_id, reviewed_content=null, asset_keys=null)` revisa Internal Website ou Sales Preview não publicado sem requalificação. Campos omitidos reutilizam fatos/assets; `{}` limpa fatos opcionais e `[]` limpa assets selecionados. Cada revisão bem-sucedida volta a Internal Website, remove aprovação anterior e exige nova revisão comercial. O resultado registra número, identidade de bytes e caminho privado da versão anterior.

Para um lead persistido, a ferramenta exige `lead.id` e relê o registro no SQLite. A pesquisa enviada deve corresponder ao report persistido desse lead. Reports antigos completos ainda podem gerar drafts se passarem a validacao atual. Somente depois de gerar e validar o artefato ela muda o status de `qualified` para `internal_website`. Geração nunca cria `sales_preview`; falha ou conflito preserva o status anterior.

Artefato, oportunidade e status são conceitos independentes:

- `opportunity_type`: `first_website` ou `redesign`;
- `status`: etapa comercial (`internal_website` para revisão interna; `sales_preview` após aprovação humana);
- `site_draft.exists`: prova read-only de que há um artefato válido.

O dashboard detecta artefatos existentes sem alterar leads. `site_ready` legado é mostrado como **Internal Website**, sem migração de dados. Um artefato válido pode ser reconciliado manualmente para Internal Website; Sales Preview exige a operação controlada de aprovação.

## Aprovação para Sales Preview

`SalesPreviewReadiness` revalida estrutura, identidade, oportunidade, conteúdo visível, metadata responsiva, paths e direitos dos assets. `approved_for_draft` é suficiente apenas internamente. Para preview público, cada asset precisa de `approved_for_publish`; assets de site existente nunca recebem essa promoção automaticamente. Assets gerados e com direitos `generated` são elegíveis pela política, mas continuam sujeitos à revisão humana.

`approve_sales_preview` exige confirmação explícita do conteúdo, assets indicados e revisor. Ela registra no manifesto um `preview_slug` proposto e seguro, metadata de aprovação e URL nula. O slug é apenas uma intenção para um futuro endereço como `drlaura.gapps.tech`; disponibilidade, DNS e publicação não são realizados.

A aprovacao inclui `sales_preview.approved_artifact`: versao, checksum agregado e
inventario exato de paths, SHA-256 e tamanhos. Alterar HTML, CSS, imagens ou o
conjunto de arquivos bloqueia publicacao ate nova revisao. Previews antigos sem
essa identidade exigem aprovacao explicita novamente. Um Sales Preview sem reserva de deployment pode ser reaprovado; substituicao de preview ja publicado continua bloqueada.

`PreviewDeploymentProvider` mantém hosting fora da aplicação. O primeiro adapter é o [HostGator/cPanel UAPI](cpanel-deployment.md), configurado apenas por secrets do runtime. Ele não publica automaticamente ao aprovar, não implementa DNS e não usa FTP, senha cPanel, SSH ou Cloudflare.

## Limites deliberados e próximos passos

- TODO: conjuntos reutilizáveis de benchmarks com TTL/cache.
- TODO: interface de revisão de assets; a biblioteca local por lead já está integrada.
- Phase 3 implementa verificação pública DNS/HTTPS/HTTP com providers offline para testes; validação real HostGator requer autorização separada.
- TODO: proposta a partir de site aprovado.
- TODO: outreach somente com autorização explícita de Gabriel.
- TODO: aquisição opcional de assets com proveniência e direitos verificados.
- TODO: refinamento de conteúdo aprovado pelo cliente após interesse/contrato.

Referências normativas: [pathlib](https://docs.python.org/3/library/pathlib.html), [html.parser](https://docs.python.org/3/library/html.parser.html), [http.server](https://docs.python.org/3/library/http.server.html), [MDN HTML](https://developer.mozilla.org/docs/Web/HTML), [MDN CSS](https://developer.mozilla.org/docs/Web/CSS) e [WCAG](https://www.w3.org/WAI/standards-guidelines/wcag/).

Phase 3 bloqueia revisão/reaprovação de artefatos com destino reservado, inclusive após falhas ou interrupções. Resolva o deployment existente pelo [fluxo de recuperação](cpanel-deployment.md); não regenere os bytes aprovados para contornar uma falha remota.
