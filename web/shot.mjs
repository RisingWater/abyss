import { spawn } from 'child_process';
import http from 'http';
import fs from 'fs';
const CDP = 9226;
const chrome = spawn('/usr/bin/google-chrome', ['--headless=new','--no-sandbox','--disable-gpu-sandbox',
  '--enable-unsafe-swiftshader','--use-gl=angle','--use-angle=swiftshader',
  '--window-size=1400,860',`--remote-debugging-port=${CDP}`,'--user-data-dir=/tmp/cdp-shot','about:blank'], { stdio:'ignore' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const getJSON = p => new Promise((res,rej)=>http.get({host:'127.0.0.1',port:CDP,path:p},r=>{let d='';r.on('data',c=>d+=c);r.on('end',()=>res(JSON.parse(d)));}).on('error',rej));
for (let i=0;i<40;i++){ try{ await getJSON('/json/version'); break;}catch{await sleep(250);} }
const page=(await getJSON('/json/list')).find(t=>t.type==='page');
const WS=(await import('ws')).default;
const ws=new WS(page.webSocketDebuggerUrl,{perMessageDeflate:false});
await new Promise(r=>ws.on('open',r));
let id=0; const pend=new Map();
ws.on('message',m=>{const x=JSON.parse(m); if(x.id&&pend.has(x.id)){pend.get(x.id)(x);pend.delete(x.id);}});
const send=(m,p={})=>new Promise(r=>{const i=++id;pend.set(i,r);ws.send(JSON.stringify({id:i,method:m,params:p}));});
await send('Page.enable');
await send('Page.navigate',{url:'http://127.0.0.1:8903/index.html'});
await sleep(9000);
const s = await send('Page.captureScreenshot',{format:'png'});
fs.writeFileSync('iso_view.png', Buffer.from(s.result.data,'base64'));
console.log('截图已存iso_view.png');
ws.close(); chrome.kill();
