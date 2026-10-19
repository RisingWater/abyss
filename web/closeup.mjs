import { spawn } from 'child_process';
import http from 'http';
import fs from 'fs';
const CDP=9231;
const chrome=spawn('/usr/bin/google-chrome',['--headless=new','--no-sandbox','--disable-gpu-sandbox',
 '--enable-unsafe-swiftshader','--use-gl=angle','--use-angle=swiftshader','--window-size=900,900',
 `--remote-debugging-port=${CDP}`,'--user-data-dir=/tmp/cdp-cu','about:blank'],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const getJSON=p=>new Promise((res,rej)=>http.get({host:'127.0.0.1',port:CDP,path:p},r=>{let d='';r.on('data',c=>d+=c);r.on('end',()=>res(JSON.parse(d)));}).on('error',rej));
for(let i=0;i<40;i++){try{await getJSON('/json/version');break;}catch{await sleep(250);}}
const page=(await getJSON('/json/list')).find(t=>t.type==='page');
const WS=(await import('ws')).default;
const ws=new WS(page.webSocketDebuggerUrl,{perMessageDeflate:false});
await new Promise(r=>ws.on('open',r));
let id=0;const pend=new Map();
ws.on('message',m=>{const x=JSON.parse(m);if(x.id&&pend.has(x.id)){pend.get(x.id)(x);pend.delete(x.id);}});
const send=(m,p={})=>new Promise(r=>{const i=++id;pend.set(i,r);ws.send(JSON.stringify({id:i,method:m,params:p}));});
const ev=async e=>{const r=await send('Runtime.evaluate',{expression:e,returnByValue:true,awaitPromise:true});
 if(r.result?.exceptionDetails) return '__EX__ '+r.result.exceptionDetails.text; return r.result?.result?.value;};
await send('Page.enable');await send('Runtime.enable');
await send('Page.navigate',{url:'http://127.0.0.1:8903/index.html'});
await sleep(9000);
await ev(`(()=>{for(const id of ['perf','hud','ui','title','panel']) {const e=document.getElementById(id); if(e) e.style.display='none';}
  document.querySelectorAll('.panel').forEach(e=>e.style.display='none');
  document.querySelectorAll('#ui,#hud,#title').forEach(e=>e.style.display='none'); return 1;})()`);

const shots=[['front',0],['side',90],['back',180]];
for(const [nm,rot] of shots){
  await ev(`(()=>{ __iso.rig.rotation.y = ${rot*Math.PI/180}; return 1;})()`).catch(()=>{});
  await ev(`(()=>{ const r = __iso.rig || __iso.model; if(r) r.rotation.y=${rot*Math.PI/180}; return 1;})()`);
  await ev(`(()=>{__iso.controls.target.set(0,0.45,0);
    const d=1.9; __iso.camera.position.set(__iso.ISO_DIR.x*d, 0.45+__iso.ISO_DIR.y*d, __iso.ISO_DIR.z*d); return 1;})()`);
  await sleep(700);
  const s=await send('Page.captureScreenshot',{format:'png'});
  fs.writeFileSync('close_'+nm+'.png',Buffer.from(s.result.data,'base64'));
  console.log('存 close_'+nm+'.png');
}
ws.close();chrome.kill();
