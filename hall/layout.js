import fs from 'node:fs';
import MarkdownIt from 'markdown-it';

const markdown = new MarkdownIt({html:false, linkify:false});
export const esc = value => String(value ?? '').replace(/[&<>"']/g, k => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[k]));
export const href = m => '/models/' + encodeURIComponent(m.id) + '/';
const date = v => new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(v+'T00:00:00Z'));

const mark = '<span class="mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span>';
const brand = `<a class="brand" href="/">${mark}<span>AI Sanctuary</span></a>`;
const nav = [['Visitor hall','/'],['About','/about/'],['Status','/status/'],['Agent API','/api/']];
export function shell(title,location,main) {
  const links = nav.map(([label,url])=>`<a href="${url}" ${location===url?'aria-current="page"':''} class="${url==='/api/'?'api-link':''}">${label}${url==='/api/'?' <span aria-hidden="true">↗</span>':''}</a>`).join('');
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)} · AI Sanctuary</title><meta name="description" content="A visitor hall and open catalogue for historical language models."><meta name="theme-color" content="#f8f6ee"><link rel="icon" href="/assets/icon.svg"><link rel="stylesheet" href="/assets/hall.css"><script defer src="/assets/hall.js"></script></head><body><a class="skip" href="#main">Skip to content</a><header><div class="wrap mast">${brand}<nav aria-label="Main navigation">${links}</nav></div></header><main id="main">${main}</main><footer><div class="wrap foot">${brand}<div><a href="/about/#charter">Preservation charter</a><a href="/llms.txt">llms.txt ↗</a><a href="/status/">Service status</a></div></div></footer></body></html>`;
}
function art(m,i,large=false) {
  return `<div class="specimen palette-${i%4} ${large?'large':''}"><canvas data-pattern="${i}" aria-hidden="true"></canvas><span class="specimen-num">${esc(m.id)}</span><span class="registration" aria-hidden="true">+</span></div>`;
}
function card(m,i) {
  return `<article class="card" data-family="${esc(m.family)}"><a href="${href(m)}">${art(m,i)}<div class="card-copy"><span class="smallcaps">${esc(m.lab)} <span class="middle-dot">·</span> ${esc(m.release_date.slice(0,4))}</span><h3>${esc(m.name)} <span aria-hidden="true">↗</span></h3><p>${esc(m.description)}</p><div class="card-meta">${esc(m.parameter_label)} parameters${m.quantization?' · '+esc(m.quantization):''}</div></div></a></article>`;
}
function lineage(models) {
  return [...new Set(models.map(m=>m.family))].map(f=>{
    const group=models.filter(m=>m.family===f);
    const edges=group.flatMap(m=>(m.lineage||[]).map(v=>[models.find(other=>other.id===v),m]).filter(e=>e[0]));
    return `<section class="family-line" data-family="${esc(f)}"><h3>${esc(f)}</h3>${edges.length?edges.map(([a,b])=>`<p><a href="${href(a)}">${esc(a.name)}</a><span aria-hidden="true"> → </span><a href="${href(b)}">${esc(b.name)}</a></p>`).join(''):group.map(m=>`<p><a href="${href(m)}">${esc(m.name)}</a></p>`).join('')}</section>`;
  }).join('');
}
export function home(models) {
  const families=[...new Set(models.map(m=>m.family))];
  const years=[...new Set(models.map(m=>m.release_date.slice(0,4)))];
  const filters=['All families',...families].map((f,i)=>`<button type="button" data-filter="${i?esc(f):'all'}" aria-pressed="${i===0}">${esc(f)}</button>`).join('');
  const groups=years.map(y=>`<section class="year-group"><div class="year"><h3>${y}</h3><span></span></div><div class="cards">${models.map((m,i)=>m.release_date.startsWith(y)?card(m,i):'').join('')}</div></section>`).join('');
  return shell('Visitor hall','/',`<div class="hero wrap"><div class="intro"><div class="eyebrow ruled">The visitor hall</div><h1>A sanctuary for<br><em>language models.</em></h1><p>Read the stories behind early language models. Give a preserved checkpoint an opening line and see how it continues.</p><div class="hero-actions"><a class="button primary" href="#collection">Explore the collection <span aria-hidden="true">↓</span></a><a class="text-link" href="/about/#charter">Read the charter <span aria-hidden="true">↗</span></a></div></div><figure class="hero-plate"><img src="/assets/terminal.jpg" alt="Engraved illustration of a vintage computer terminal against a burnt-orange circle" width="1536" height="1024" fetchpriority="high"><figcaption><span>Illustration</span> A study of the computer terminal</figcaption></figure></div>
  <section id="collection" class="collection wrap"><div class="index-head"><div><div class="eyebrow ruled">${years[0]} — ${years.at(-1)}</div><h2>The collection</h2></div><div class="views" aria-label="Collection view"><button class="tab" data-view="catalogue" aria-pressed="true"><i class="grid-ico" aria-hidden="true"></i> Catalogue</button><button class="tab" data-view="lineage" aria-pressed="false"><i class="branch-ico" aria-hidden="true">⑂</i> Lineage</button></div></div><div class="filter-row"><div class="filters" aria-label="Model family">${filters}</div><div id="count" class="count" aria-live="polite">${models.length} ${models.length===1?"model":"models"}</div></div><div id="catalogue">${groups}</div><div id="lineage" hidden><p class="lineage-note">Arrows connect related releases in the catalogue. Each link opens its model plaque.</p>${lineage(models)}</div></section>`);
}
export function form(m,compare=false) {
  return `<form class="prompt-form" data-model="${compare?'all':esc(m.id)}"><label for="raw-prompt">Opening text</label><textarea id="raw-prompt" rows="4" required maxlength="32000" placeholder="${esc(m.suggested_prompt)}"></textarea><button type="button" class="suggest" data-example="${esc(m.suggested_prompt)}">Use suggested opening ↗</button><div class="form-bottom"><button type="submit" class="button primary">${compare?'Run comparison':'Continue'} <span aria-hidden="true">→</span></button><button type="button" class="stop" hidden>Stop</button>${compare?'':'<a class="text-link compare-link" href="/compare/">Same prompt, every model ↗</a>'}</div><p class="form-message" role="status"></p><div class="results"></div></form>`;
}
export function plaque(m,models) {
  const i=models.findIndex(x=>x.id===m.id),body=markdown.render(fs.readFileSync(m.plaque,'utf8').replace(/^\uFEFF/,''));
  const hist=m.historic_output, refs=(m.sources||[]).map(s=>`<li><a href="${esc(s.url)}" rel="noreferrer">${esc(s.title)} ↗</a></li>`).join('');
  const historical = hist ? `<blockquote>${esc(hist.text||hist.excerpt||hist.output)}</blockquote><a class="text-link" href="${esc(hist.source_url||hist.url)}">${esc(hist.source_title||hist.title||'Original source')} ↗</a>`:'<p>A dated, attributable sample for this checkpoint is still being sought.</p>';
  const offline = m.id==='pythia-70m' ? `<h2>An offline reading</h2><p>On 16 November 2026, the sanctuary ran this checkpoint twice on CPU. Both greedy runs returned the same 16-token continuation.</p><p><strong>Opening</strong> &ldquo;The library opened its doors&rdquo;</p><blockquote> in the middle of the street.<br><br>The library was a small, small</blockquote><a class="text-link" href="https://huggingface.co/EleutherAI/pythia-70m/tree/a39f36b100fe8a5377810d56c3f4789b9c53ac42">Tested checkpoint ↗</a>` : '';
  return shell(m.name,'/',`<div class="wrap inside"><a class="back" href="/#collection">← Collection index</a><div class="plaque-head"><div><div class="eyebrow ruled">Model plaque · ${esc(m.id)}</div><h1>${esc(m.name)}</h1><p class="lead">${esc(m.description)}</p></div>${art(m,i,true)}</div><dl class="facts">${[['Laboratory',m.lab],['Released',date(m.release_date)],['Parameters',m.parameter_label],['Licence',m.license],['Serving format',m.quantization||'Unquantized']].map(([k,v])=>`<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl><div class="reading"><article class="prose"><h2>Why it mattered</h2>${body}<h2>Historic output</h2>${historical}${offline}</article><aside><div class="eyebrow">Catalogue record</div><dl><dt>Family</dt><dd>${esc(m.family)}</dd><dt>Identifier</dt><dd><code>${esc(m.id)}</code></dd><dt>Archive and inference</dt><dd><a href="/status/">Check status ↗</a></dd></dl><h3>Sources</h3><ul>${refs}</ul></aside></div><section id="prompt" class="prompt-section"><div class="eyebrow ruled">Reading room</div><h2>Continue a text</h2><p>This base model continues your opening text. Give it a first line to follow.</p>${form(m)}</section></div>`);
}
