const mime={html:'text/html; charset=utf-8',txt:'text/plain; charset=utf-8',css:'text/css; charset=utf-8',js:'text/javascript; charset=utf-8',json:'application/json',svg:'image/svg+xml',jpg:'image/jpeg',woff2:'font/woff2'};
function respond(body,status=200,type='application/json') {
  return new Response(body,{status,headers:{'Content-Type':type,'X-Content-Type-Options':'nosniff','Referrer-Policy':'same-origin'}});
}
const error=(status,code,message)=>respond(JSON.stringify({error:{message,type:code,code}}),status);
export default {
  async fetch(request) {
    const path=new URL(request.url).pathname;
    if(path.startsWith('/v1/')) {
      if(path==='/v1/models'&&request.method==='GET') return respond(JSON.stringify({object:'list',data:registry.map(m=>({...m,object:'model',owned_by:m.lab,created:Date.parse(m.release_date)/1000,state:'awaiting-preservation'}))}));
      if(path==='/v1/status'&&request.method==='GET') return respond(JSON.stringify({catalogue_only:true,data:registry.map(m=>({id:m.id,state:'awaiting-preservation',requests_this_month:null,verified_at:null}))}));
      if(/^\/v1\/models\/[^/]+\/package$/.test(path)&&request.method==='GET') {
        if(!registry.some(m=>m.id===path.split('/')[3])) return error(404,'unknown_model','Unknown model identifier.');
        return error(503,'awaiting_preservation','No verified package is attached to this catalogue.');
      }
      if(['/v1/completions','/v1/chat/completions'].includes(path)&&request.method==='POST') {
        return error(503,'inference_unavailable','Catalogue preview. Inference awaits a verified package and a connected CPU worker.');
      }
      return error(404,'not_found','No such API route.');
    }
    if(!['GET','HEAD'].includes(request.method))return error(405,'method_not_allowed','Use GET or HEAD.');
    const page=assets[path]||assets[path.replace(/\/?$/,'/index.html')];
    if(!page)return error(404,'not_found','Page not found.');
    const [ext,mode,content]=page;
    const data=request.method==='HEAD'?null:mode==='b64'?Uint8Array.from(atob(content),c=>c.charCodeAt(0)):content;
    return respond(data,200,mime[ext]||'text/plain; charset=utf-8');
  }
};
