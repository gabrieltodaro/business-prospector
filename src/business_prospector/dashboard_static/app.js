'use strict';

const STATUS = [
  ['new','Novo','#7a8ca8'],['qualified','Qualificado','#d66f4d'],['needs_review','Revisar','#a87525'],
  ['contacted','Contatado','#688c94'],['proposal','Proposta','#8b6fa2'],['closed','Fechado','#547b5d'],['discarded','Descartado','#99948a']
];
const labels = Object.fromEntries(STATUS.map(([key,label]) => [key,label]));
const colors = Object.fromEntries(STATUS.map(([key,,color]) => [key,color]));
let leads = [];
let draggedId = null;

const el = id => document.getElementById(id);
const node = (tag, className, text) => { const item=document.createElement(tag); if(className)item.className=className; if(text!==undefined)item.textContent=String(text); return item; };
const safeUrl = value => { try { const url=new URL(value); return ['http:','https:'].includes(url.protocol)?url.href:null; } catch { return null; } };
const hasContact = lead => Boolean(lead.whatsapp || lead.phone || lead.email || lead.instagram);

async function request(url, options={}) {
  const response = await fetch(url, {cache:'no-store', ...options});
  const body = await response.json().catch(() => ({error:'Resposta inválida do servidor'}));
  if (!response.ok) throw new Error(body.error || 'Operação não concluída');
  return body;
}

async function load() {
  try {
    const body = await request('/api/leads');
    leads = body.leads;
    populateFilters(); render();
    el('freshness').textContent = `Atualizado às ${new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'})}`;
  } catch (error) { showToast(error.message, true); }
}

function populateFilters() {
  fillSelect(el('city-filter'), [...new Set(leads.map(l=>l.city).filter(Boolean))].sort());
  fillSelect(el('category-filter'), [...new Set(leads.map(l=>l.category).filter(Boolean))].sort());
}
function fillSelect(select, values) {
  const current=select.value; while(select.options.length>1)select.remove(1);
  values.forEach(value => select.append(node('option','',value))); select.value=current;
}
function filtered() {
  const term=el('search').value.trim().toLocaleLowerCase('pt-BR');
  const city=el('city-filter').value, category=el('category-filter').value;
  const minimum=Math.max(0,Math.min(100,Number(el('score-filter').value)||0));
  return leads.filter(lead => (!term || `${lead.name} ${lead.city} ${lead.category}`.toLocaleLowerCase('pt-BR').includes(term)) && (!city||lead.city===city) && (!category||lead.category===category) && lead.score>=minimum);
}
function render() {
  const visible=filtered(); const board=el('board'); board.replaceChildren();
  const total=leads.length, contacted=leads.filter(hasContact).length;
  el('lead-count').textContent=total; el('contact-count').textContent=contacted;
  el('avg-score').textContent=total?Math.round(leads.reduce((sum,l)=>sum+l.score,0)/total):0;
  STATUS.forEach(([status,label,color]) => board.append(makeColumn(status,label,color,visible)));
}
function makeColumn(status,label,color,visible) {
  const column=node('section','column'); column.dataset.status=status;
  const head=node('div','column-head'); head.append(node('h2','',label),node('span','',visible.filter(l=>visualStatus(l.status)===status).length));
  const list=node('div','card-list');
  const items=visible.filter(l=>visualStatus(l.status)===status).sort((a,b)=>b.score-a.score||b.review_count-a.review_count);
  if(!items.length)list.append(node('p','empty','Nenhum lead nesta etapa'));
  items.forEach((lead,index)=>{const card=makeCard(lead);card.style.animationDelay=`${Math.min(index,8)*25}ms`;list.append(card)});
  column.append(head,list);
  column.addEventListener('dragover',event=>{event.preventDefault();column.classList.add('drop-target')});
  column.addEventListener('dragleave',()=>column.classList.remove('drop-target'));
  column.addEventListener('drop',event=>{event.preventDefault();column.classList.remove('drop-target');moveLead(draggedId,status)});
  column.style.setProperty('--status-color',color); return column;
}
function visualStatus(status){return status==='rejected'?'discarded':status}
function makeCard(lead) {
  const card=node('article','lead-card'); card.draggable=true; card.dataset.id=lead.id; card.style.setProperty('--status-color',colors[visualStatus(lead.status)]||colors.qualified);
  const top=node('div','card-top'); top.append(node('div','card-name',lead.name),node('span','score',lead.score));
  card.append(top,node('p','card-meta',`${lead.category} · ${lead.city}`));
  const quality=node('div','quality'); quality.append(node('span','rating',`★ ${Number(lead.rating).toFixed(1)}`),node('span','',`${lead.review_count} avaliações`)); card.append(quality);
  card.append(node('p','reason',lead.assessment?.reason||'Sem justificativa registrada'));
  const indicators=node('div','indicators');
  addIndicator(indicators,'WhatsApp',lead.whatsapp_confirmed); addIndicator(indicators,'Telefone',Boolean(lead.phone)); addIndicator(indicators,'E-mail',Boolean(lead.email));
  addIndicator(indicators,lead.website_url?'Website':'Sem site',Boolean(lead.website_url),!lead.website_url); if(!hasContact(lead))addIndicator(indicators,'Sem contato',false,true);
  indicators.append(node('span','indicator on',`${lead.website_issue_count||0} issues`)); card.append(indicators);
  card.addEventListener('click',()=>openDetail(lead)); card.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();openDetail(lead)}});card.tabIndex=0;
  card.addEventListener('dragstart',()=>{draggedId=lead.id;card.classList.add('dragging')});card.addEventListener('dragend',()=>{draggedId=null;card.classList.remove('dragging');document.querySelectorAll('.drop-target').forEach(x=>x.classList.remove('drop-target'))});
  return card;
}
function addIndicator(parent,text,on,alert=false){parent.append(node('span',`indicator ${on?'on':''} ${alert?'alert':''}`.trim(),text))}
async function moveLead(id,status) {
  const lead=leads.find(item=>item.id===id); if(!lead||visualStatus(lead.status)===status)return;
  const previous=lead.status; lead.status=status; render();
  try { const body=await request(`/api/leads/${id}/status`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})}); Object.assign(lead,body.lead); render(); showToast(`Movido para ${labels[status]}`); }
  catch(error){lead.status=previous;render();showToast(error.message,true)}
}
function openDetail(lead) {
  el('detail-title').textContent=lead.name; const content=el('detail-content'); content.replaceChildren();
  content.append(detailSection('Negócio', [['Categoria',lead.category],['Cidade',lead.city],['Endereço',lead.address],['Google Maps',externalLink(lead.maps_url,'Abrir no Maps')],['Place ID',lead.external_place_id],['Avaliação',`${lead.rating} · ${lead.review_count} avaliações`]]));
  const flags=['layout','mobile','cta','content','social_proof','platform'].filter(key=>lead.assessment?.[key]).join(', ')||'Nenhum flag registrado';
  content.append(detailSection('Website', [['Website',externalLink(lead.website_url,'Abrir website')],['Assessment','Flags legados persistidos'],['Problemas',lead.website_issue_count],['Flags',flags],['Qualificação',lead.assessment?.reason]]));
  content.append(detailSection('Contatos', [['Telefone',lead.phone],['WhatsApp',lead.whatsapp],['Confirmado',lead.whatsapp_confirmed?'Sim':'Não'],['Fonte WhatsApp',lead.whatsapp_source],['E-mail',lead.email],['Instagram',externalLink(lead.instagram,'Abrir Instagram')]]));
  content.append(detailSection('Prospecção', [['Score',lead.score],['Status',labels[visualStatus(lead.status)]||lead.status],['Fonte',lead.source],['Descoberto em',lead.discovered_at],['Última verificação',lead.last_checked_at]]));
  el('scrim').hidden=false; el('inspector').classList.add('open');el('inspector').setAttribute('aria-hidden','false');el('close-detail').focus();
}
function detailSection(title,rows){const section=node('section','detail-section');section.append(node('h3','',title));const dl=node('dl','');rows.forEach(([label,value])=>{const row=node('div','detail-row');row.append(node('dt','',label));const dd=node('dd','');if(value instanceof Node)dd.append(value);else dd.textContent=value===null||value===undefined||value===''?'—':String(value);row.append(dd);dl.append(row)});section.append(dl);return section}
function externalLink(value,label){const url=safeUrl(value);if(!url)return node('span','',value?'URL não permitida':'—');const link=node('a','',label);link.href=url;link.target='_blank';link.rel='noopener noreferrer';return link}
function closeDetail(){el('inspector').classList.remove('open');el('inspector').setAttribute('aria-hidden','true');el('scrim').hidden=true}
function showToast(message,error=false){const toast=el('toast');toast.textContent=message;toast.className=`toast ${error?'error':''}`;toast.hidden=false;clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>toast.hidden=true,2600)}

['search','city-filter','category-filter','score-filter'].forEach(id=>el(id).addEventListener('input',render));
el('refresh').addEventListener('click',load);el('close-detail').addEventListener('click',closeDetail);el('scrim').addEventListener('click',closeDetail);document.addEventListener('keydown',event=>{if(event.key==='Escape')closeDetail()});
load();
