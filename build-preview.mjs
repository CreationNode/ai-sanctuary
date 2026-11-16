import fs from 'node:fs';
import path from 'node:path';

// The archive includes a static reading copy. Sites additionally needs an HTTP
// entry point for catalogue discovery and honest pre-admission API responses.
const assets={};
const root=path.resolve('dist');
function collect(dir) {
  for(const entry of fs.readdirSync(dir,{withFileTypes:true})) {
    if(['server','.openai'].includes(entry.name)) continue;
    const location=path.join(dir,entry.name);
    if(entry.isDirectory()) {collect(location);continue;}
    const ext=path.extname(entry.name).slice(1);
    if(!['html','txt','css','js','json','svg','jpg','woff2'].includes(ext))continue;
    const binary=['jpg','woff2'].includes(ext);
    assets['/'+path.relative(root,location).split(path.sep).join('/')]=[ext,binary?'b64':'text',fs.readFileSync(location,binary?'base64':'utf8')];
  }
}
fs.mkdirSync(path.join(root,'.well-known'),{recursive:true});
fs.copyFileSync('service/openapi.json',path.join(root,'.well-known/openapi.json'));
collect(root);
const registry=JSON.parse(fs.readFileSync(path.join(root,'catalogue.json'),'utf8'));
const worker='const assets='+JSON.stringify(assets)+';\nconst registry='+JSON.stringify(registry)+';\n'+fs.readFileSync('catalogue-worker.js','utf8');
fs.mkdirSync(path.join(root,'server'),{recursive:true});
fs.writeFileSync(path.join(root,'server/index.js'),worker);
fs.mkdirSync(path.join(root,'.openai'),{recursive:true});
fs.copyFileSync('.openai/hosting.json',path.join(root,'.openai/hosting.json'));
console.log('Built catalogue HTTP preview with '+registry.length+' models and '+Object.keys(assets).length+' assets.');
