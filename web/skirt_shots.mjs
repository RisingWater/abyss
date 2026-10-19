/* 生成裙摆摆动对比图：固定相位逐个截图，拼成一张对比条。
   用来肉眼确认「不同相位的裙摆形态确实不同」，比断言更有说服力。
   用法：node skirt_shots.mjs  （需先在 8903 端口起 http 服务） */
import { spawn } from 'child_process';
import http from 'http';
import fs from 'fs';

const CDP = 9228;
const chrome = spawn('/usr/bin/google-chrome', ['--headless=new', '--no-sandbox', '--disable-gpu-sandbox',
  '--enable-unsafe-swiftshader', '--use-gl=angle', '--use-angle=swiftshader',
  '--window-size=1400,860', `--remote-debugging-port=${CDP}`, '--user-data-dir=/tmp/cdp-shots', 'about:blank'], { stdio: 'ignore' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const getJSON = p => new Promise((res, rej) => http.get({ host: '127.0.0.1', port: CDP, path: p },
  r => { let d = ''; r.on('data', c => d += c); r.on('end', () => res(JSON.parse(d))); }).on('error', rej));
for (let i = 0; i < 40; i++) { try { await getJSON('/json/version'); break; } catch { await sleep(250); } }
const page = (await getJSON('/json/list')).find(t => t.type === 'page');
const WS = (await import('ws')).default;
const ws = new WS(page.webSocketDebuggerUrl, { perMessageDeflate: false });
await new Promise(r => ws.on('open', r));
let id = 0; const pend = new Map();
ws.on('message', m => { const x = JSON.parse(m); if (x.id && pend.has(x.id)) { pend.get(x.id)(x); pend.delete(x.id); } });
const send = (m, p = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method: m, params: p })); });
const evalJS = async e => {
  // awaitPromise 必须开：页面里用了 async IIFE + Image.onload，不开的话拿到的是 Promise 对象
  const r = await send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description);
  return r.result?.result?.value;
};

await send('Page.enable');
await send('Page.navigate', { url: 'http://127.0.0.1:8903/index.html' });
await sleep(11000);

// 摆动姿态 + 镜头对准下半身。头发垂到腰下会挡住裙面，所以 target 压到裙摆高度、
// 距离拉近，让 A 字裙的轮廓占据画面主体，摆动的左右位移才看得出来。
await evalJS(`(() => {
  const iso = window.__iso;
  document.querySelectorAll('.panel, #stick, #toast').forEach(e => e.style.display = 'none');
  iso.forceWalk(true);
  document.getElementById('tFollow').checked = false;
  iso.controls.target.set(0, 0.52, 0);
  iso.camera.position.copy(iso.controls.target).addScaledVector(iso.ISO_DIR, 2.4);
  return 1;
})()`);
await sleep(1200);

const shots = [];
for (let k = 0; k < 6; k++) {
  const ph = (k / 6) * Math.PI * 2;
  await evalJS(`window.__iso.skirt.uPhase.value = ${ph}`);
  await sleep(300);
  const s = await send('Page.captureScreenshot', { format: 'png', clip: { x: 380, y: 60, width: 640, height: 740, scale: 1 } });
  shots.push({ ph, data: Buffer.from(s.result.data, 'base64') });
  fs.writeFileSync(`skirt_phase_${k}.png`, shots[k].data);
  console.log('  相位 %s -> skirt_phase_%d.png', ph.toFixed(2), k);
}

// 在页面里横向拼接，标注相位
const b64 = shots.map(s => s.data.toString('base64'));
const labels = shots.map(s => s.ph.toFixed(2));
const strip = await evalJS(`(async () => {
  const imgs = await Promise.all(${JSON.stringify(b64)}.map(b => new Promise((res, rej) => {
    const im = new Image(); im.onload = () => res(im); im.onerror = rej;
    im.src = 'data:image/png;base64,' + b;
  })));
  const w = 400, h = Math.round(imgs[0].height * w / imgs[0].width);
  const cv = document.createElement('canvas');
  cv.width = w * imgs.length; cv.height = h;
  const cx = cv.getContext('2d');
  imgs.forEach((im, i) => {
    cx.drawImage(im, i * w, 0, w, h);
    cx.fillStyle = 'rgba(0,0,0,.65)'; cx.fillRect(i * w, 0, 78, 22);
    cx.fillStyle = '#7fe3ff'; cx.font = '13px monospace';
    cx.fillText('ph ' + ${JSON.stringify(labels)}[i], i * w + 8, 15);
    cx.strokeStyle = '#2a4a6a'; cx.strokeRect(i * w + .5, .5, w, h);
  });
  return cv.toDataURL('image/png');
})()`);
// 无头下 toDataURL 可能返回 "data:,"（画布被判定为污染/零尺寸），先校验再落盘
if (typeof strip !== 'string' || !strip.startsWith('data:image/png;base64,')) {
  console.log('  拼接失败，单独相位图已保存:', JSON.stringify(String(strip)).slice(0, 120));
} else {
  fs.writeFileSync('skirt_swing_strip.png', Buffer.from(strip.split(',')[1], 'base64'));
  console.log('  对比条 -> skirt_swing_strip.png');
}

ws.close(); chrome.kill();