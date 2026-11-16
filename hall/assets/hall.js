'use strict';
const one = (selector, root=document) => root.querySelector(selector);
const all = (selector, root=document) => Array.from(root.querySelectorAll(selector));
function create(tag, text) {
  const element = document.createElement(tag);
  element.textContent = text;
  return element;
}

function catalogue() {
  let family='all', view='catalogue';
  function update() {
    for (const node of all('[data-family]')) node.hidden=family!=='all' && family!==node.dataset.family;
    for (const group of all('.year-group')) group.hidden=!one('.card:not([hidden])',group);
    one('#catalogue').hidden=view!=='catalogue';
    one('#lineage').hidden=view!=='lineage';
    const count=all('.card:not([hidden])').length;
    one('#count').textContent=count+(count===1?' model':' models');
    for (const n of all('[data-filter]')) n.setAttribute('aria-pressed',String(family===n.dataset.filter));
    for (const n of all('[data-view]')) n.setAttribute('aria-pressed',String(view===n.dataset.view));
  }
  for (const n of all('[data-filter]')) n.addEventListener('click',()=>{family=n.dataset.filter; update(); drawPrints();});
  for (const n of all('[data-view]')) n.addEventListener('click',()=>{view=n.dataset.view; update(); drawPrints();});
}

// Engraved motifs distinguish catalogue cards. They are editorial illustrations.
function drawPrints() {
  for (const c of all('canvas[data-pattern]')) {
    const rect=c.getBoundingClientRect();
    if (!rect.width || !rect.height) continue;
    const scale=Math.min(devicePixelRatio || 1,2), w=rect.width, h=rect.height;
    c.width=Math.round(w*scale); c.height=Math.round(h*scale);
    const ctx=c.getContext('2d');
    if (!ctx) continue;
    ctx.scale(scale,scale);
    const n=Number(c.dataset.pattern);
    ctx.strokeStyle=getComputedStyle(c.parentNode).getPropertyValue('--print').trim();
    ctx.lineWidth=.7;
    ctx.globalAlpha=.22;
    for(let x=11;x<w;x+=14) for(let y=9;y<h;y+=14) ctx.strokeRect(x,y,.35,.35);
    ctx.globalAlpha=.88;
    const cx=w*.55, cy=h*.55;
    for(let row=0;row<41;row++) {
      const t=row/40;
      ctx.beginPath();
      for(let j=0;j<=145;j++) {
        const u=j/145, a=2*Math.PI*u;
        let x,y;
        if(n%4===0) {
          x=cx+(u-.5)*w*.73;
          y=cy+(t-.5)*h*.57+Math.sin(u*7.7+t*3.3)*h*.28*Math.sin(Math.PI*u);
        } else if(n%4===1) {
          x=cx+Math.cos(a)*w*(.19+.12*t)+Math.sin(a)*w*(t-.45)*.23;
          y=cy+Math.sin(a)*h*(.11+.27*t)-Math.cos(a)*h*.16;
        } else if(n%4===2) {
          x=cx+Math.cos(a)*w*(.15+.15*t)+Math.cos(2*a+t*3)*w*.05;
          y=cy+Math.sin(a)*h*(.15+.21*t)+Math.sin(2*a+t*3)*h*.10;
        } else {
          x=cx+(u-.5)*w*.72+(t-.5)*w*.08;
          y=cy+(t-.5)*h*.56+Math.cos(u*9-t*4)*h*.27*Math.sin(Math.PI*u);
        }
        if(j===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
      }
      ctx.stroke();
    }
  }
}
const states={'awaiting-preservation':'Awaiting preservation',offline:'Offline',ready:'Ready',loading:'Loading',standby:'On demand',busy:'Busy'};
const available=new Set(['ready','standby','busy','loading']);
async function json(url) {
  const response=await fetch(url,{headers:{Accept:'application/json'},cache:'no-store',signal:AbortSignal.timeout(12000)});
  if(!response.ok) throw Error('Gateway unavailable.');
  return response.json();
}
async function statusPage() {
  const note=one('#status-note');
  try {
    const response=await json('/v1/status'),rows=new Map(response.data.map(r=>[r.id,r]));
    for (const tr of all('[data-status-model]')) {
      const r=rows.get(tr.dataset.statusModel);
      if(!r) continue;
      tr.cells[1].textContent=states[r.state]||r.state;
      tr.cells[2].textContent=r.requests_this_month??'—';
      tr.cells[3].textContent=r.verified_at?String(r.verified_at).slice(0,10):'—';
    }
    note.textContent=response.catalogue_only?'Catalogue preview. Inference awaits verified packages and a connected serving gateway.':'Current gateway readings. Request counts cover the current UTC calendar month.';
  } catch {note.textContent='The gateway could not be reached. Current readings are unavailable.';}
}

async function* events(body) {
  const reader=body.getReader(),decoder=new TextDecoder();
  let buffer='';
  try {
    while(true) {
      const {done,value}=await reader.read();
      buffer+=decoder.decode(value,{stream:!done});
      let end;
      while((end=buffer.indexOf('\n'))>=0) {
        const line=buffer.slice(0,end).trimEnd();
        buffer=buffer.slice(end+1);
        if(!line.startsWith('data:')) continue;
        const data=line.slice(5).trimStart();
        if(data==='[DONE]') return;
        yield JSON.parse(data);
      }
      if(done) throw Error('Stream ended before the completion marker.');
    }
  } finally { await reader.cancel().catch(()=>{});reader.releaseLock(); }
}
async function runOne(model,prompt,box,signal) {
  const title=create('h3',model.name),out=create('pre',''),meta=create('small','Waiting for the worker…');
  box.append(title,out,meta);
  try {
    const res=await fetch('/v1/completions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:model.id,prompt,stream:true}),signal});
    if(!res.ok) {
      const detail=await res.json().catch(()=>null);
      const retry=res.headers.get('Retry-After');
      throw Error((typeof detail?.error?.message==='string'?detail.error.message:typeof detail?.detail==='string'?detail.detail:'The inference gateway is unavailable.')+(res.status===429&&retry?' Retry after '+retry+' seconds.':''));
    }
    let provenance;
    for await (const e of events(res.body)) {
      if(e.error) throw Error(e.error.message||'Worker interrupted.');
      out.textContent+=e.choices?.[0]?.text??'';
      provenance=e.sanctuary||provenance;
      meta.textContent='Receiving unmoderated model output…';
    }
    meta.textContent='Untrusted model output'+(provenance?' · '+JSON.stringify(provenance):'');
  } catch(e) {meta.textContent=signal.aborted?'Stopped by visitor.':e.message;}
}
async function readingRoom(f) {
  const input=one('textarea',f),submit=one('[type=submit]',f),stop=one('.stop',f),note=one('.form-message',f),results=one('.results',f);
  let active;
  one('.suggest',f).onclick=e=>{input.value=e.currentTarget.dataset.example;input.focus();};
  const transfer='ai-sanctuary:compare-opening';
  const link=one('.compare-link',f);
  if(link) link.onclick=()=>{try {sessionStorage.setItem(transfer,JSON.stringify({text:input.value,expires:Date.now()+60000}));}catch{}};
  if(f.dataset.model==='all') try {const stored=sessionStorage.getItem(transfer);sessionStorage.removeItem(transfer);if(stored){const p=JSON.parse(stored);if(Date.now()<p.expires)input.value=p.text;}}catch{}
  stop.onclick=()=>active?.abort();
  const getStatus=async()=>{const response=await json('/v1/status');return response.data;};
  try {
    const states=await getStatus(),m=states.find(r=>r.id===f.dataset.model);
    if(m && !available.has(m.state)) note.textContent=m.state==='awaiting-preservation'?'Inference opens after this package passes verification at all three mirrors.':'This worker is currently offline.';
    if(f.dataset.model==='all'&&!states.some(r=>available.has(r.state)))note.textContent='No models are serving yet. The catalogue remains open for reading.';
  } catch {note.textContent='The live inference gateway is currently unavailable.';}
  f.onsubmit=async e=>{
    e.preventDefault(); if(!input.value.length||active) return;
    const controller=new AbortController();active=controller;
    const prompt=input.value;submit.disabled=true;stop.hidden=false;results.replaceChildren();note.textContent='Checking availability…';
    let reason='';
    try {
      const [models,statuses]=await Promise.all([json('/catalogue.json'),getStatus()]);
      const statusById=new Map(statuses.map(r=>[r.id,r.state]));
      const targets=models.filter(m=>f.dataset.model==='all'||m.id===f.dataset.model);
      const queue=[];
      for(const model of targets) {
        const box=create('section','');box.className='result';results.append(box);
        const state=statusById.get(model.id);
        if(available.has(state)) queue.push([model,box]);
        else box.append(create('h3',model.name),create('small',state==='awaiting-preservation'?'Awaiting verification of all three archive copies.':(states[state]||'Status unknown')+'. Inference unavailable.'));
      }
      note.textContent=queue.length?'Requesting raw continuations…':'';
      async function next() {
        while(queue.length&&!controller.signal.aborted) {
          const [m,box]=queue.shift();await runOne(m,prompt,box,controller.signal);
        }
      }
      await Promise.all([next(),next()]);
      if(controller.signal.aborted) reason='Comparison or request stopped.';
    } catch {reason='The gateway could not be reached. No continuation was received.';}
    finally {active=null;submit.disabled=false;stop.hidden=true;note.textContent=reason;}
  };
}
if(one('#catalogue')) catalogue();
drawPrints();window.addEventListener('resize',drawPrints);
if(one('#status-note')) statusPage();
if(one('.prompt-form')) readingRoom(one('.prompt-form'));
for (const n of all('[data-origin]')) n.textContent=n.textContent.replaceAll('ORIGIN',location.origin);
