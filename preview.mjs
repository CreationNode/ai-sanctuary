import http from 'node:http';
import worker from './dist/server/index.js';
const port=Number(process.env.PORT||4175);
http.createServer(async(req,res)=>{
  try{
    const request=new Request(new URL(req.url,'http://127.0.0.1:'+port),{method:req.method});
    const output=await worker.fetch(request);
    res.writeHead(output.status,Object.fromEntries(output.headers));
    res.end(Buffer.from(await output.arrayBuffer()));
  }catch{res.writeHead(500);res.end('Preview request failed.');}
}).listen(port,'127.0.0.1',()=>console.log('Local: http://127.0.0.1:'+port+'/'));
