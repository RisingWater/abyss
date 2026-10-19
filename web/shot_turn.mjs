import { spawn } from 'child_process';
import http from 'http';
import fs from 'fs';
const CDP=9230;
const chrome=spawn('/usr/bin/google-chrome',['--headless=new','--no-sandbox','--disable-gpu-sandbox',
 '--enable-unsafe-swiftshader','--use-gl=angle','--use-angle=swiftshader','--window-size=900,760',
 `--remote-debugging-port=${CDP}`,'--user-data-dir=/tmp/cdp-turn','about:blank'],{stdio:'ignore'});
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
const ev=async e=>{const r=await send('Runtime.evaluate',{expression:e,returnByValue:true,awaitPromise:true});return r.result?.result?.value;};
await send('Page.enable');await send('Runtime.enable');
await send('Page.navigate',{url:'http://127.0.0.1:8903/index.html'});
await sleep(9000);
// 隐藏UI，只留角色
await ev(`(()=>{for(const id of ['perf','hud','ui','title']) {const e=document.getElementById(id); if(e) e.style.display='none';} return 1;})()`);
const names=['front','side','back','q34'];
for(let k=0;k<4;k++){
  await ev(`(()=>{const b=document.getElementById('tFlip'); if(${k}===2){b.checked=true;b.dispatchEvent(new Event('change'));} return 1;})()`);
  // 关闭相机跟随并拉近
  await ev(`(()=>{__iso.controls.target.set(0,0.9,0); __iso.camera.position.copy(__iso.ISO_DIR).multiplyScalar(3.2).setY(__iso.ISO_DIR.y*3.2+0.9); return 1;})()`);
  await sleep(900);
  const s=await send('Page.captureScreenshot',{format:'png'});
  fs.writeFileSync('turn_'+names[k]+'.png',Buffer.from(s.result.data,'base64'));
  console.log('存turn_'+names[k]+'.png');
}
ws.close();chrome.kill();
