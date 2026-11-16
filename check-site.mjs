import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import worker from './dist/server/index.js';

const models=JSON.parse(fs.readFileSync('dist/catalogue.json','utf8'));
assert(models.length>=10 && models.length<=15,'Founding collection should have 10–15 entries.');
assert.equal(new Set(models.map(m=>m.id)).size,models.length);
const origin='https://sanctuary.test';
const fetchPage=(url,options={})=>worker.fetch(new Request(new URL(url,origin),options));
const pages=['/','/about/','/api/','/compare/','/status/',...models.map(m=>'/models/'+m.id+'/')];
let links=0;
for (const url of pages) {
  const html=await (await fetchPage(url)).text();
  assert.match(html,/<h1>/);
  assert(!html.includes('undefined'),'Missing template value at '+url);
  for(const [,attr] of html.matchAll(/(?:href|src)="([^"]+)"/g)) {
    const dest=new URL(attr,new URL(url,origin));
    if(dest.origin!==origin)continue;
    const response=await fetchPage(dest);
    assert(response.ok,'Broken internal link '+url+' → '+attr+' ('+response.status+')');
    links++;
  }
}
for(const m of models) {
  assert.equal(path.basename(m.plaque),m.id+'.md');
  assert.match(m.source_revision,/^[a-f0-9]{40}$/);
  assert(m.lineage.every(id=>models.some(x=>x.id===id)));
  assert.equal((await fetchPage('/v1/models/'+m.id+'/package')).status,503);
}
const list=await (await fetchPage('/v1/models')).json();
assert.equal(list.data.length,models.length);
const statuses=await(await fetchPage('/v1/status')).json();
assert(statuses.data.every(s=>s.state==='awaiting-preservation'&&s.verified_at===null));
const spec=await(await fetchPage('/.well-known/openapi.json')).json();
for (const endpoint of ['/v1/completions','/v1/chat/completions','/v1/models','/v1/models/{model_id}/package']) {
  assert(Object.keys(spec.paths).some(key=>key.replace(/\{[^}]+\}/g,'{}')===endpoint.replace(/\{[^}]+\}/g,'{}')),endpoint+' missing from OpenAPI');
}
assert.equal((await fetchPage('/v1/completions',{method:'POST'})).status,503);
assert.equal((await fetchPage('/v1/models/unknown/package')).status,404);
console.log(pages.length+' pages, '+models.length+' registry entries and '+links+' local links checked. Preview API and archive gates passed.');
