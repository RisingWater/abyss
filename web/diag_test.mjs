// 验证诊断区：可见性（rect/display）、可点击性（hit-test 命中 summary）、字段是否有真实值
import { spawn } from 'child_process';
import http from 'http';

const CDP = 9223;
const chrome = spawn('/usr/bin/google-chrome', [
  '--headless=new', '--disable-gpu-sandbox', '--no-sandbox',
  '--enable-unsafe-swiftshader', '--use-gl=angle', '--use-angle=swiftshader',
  '--window-size=1280,800', `--remote-debugging-port=${CDP}`,
  '--user-data-dir=/tmp/cdp-diag2', 'about:blank'
], { stdio: 'ignore' });

const sleep = ms => new Promise(r => setTimeout(r, ms));
const getJSON = path => new Promise((res, rej) => {
  http.get({ host: '127.0.0.1', port: CDP, path }, r => {
    let d = ''; r.on('data', c => d += c); r.on('end', () => res(JSON.parse(d)));
  }).on('error', rej);
});

try {
  for (let i = 0; i < 40; i++) { try { await getJSON('/json/version'); break; } catch { await sleep(250); } }
  const tabs = await getJSON('/json/list');
  const page = tabs.find(t => t.type === 'page');
  const WS = (await import('ws')).default;
  const ws = new WS(page.webSocketDebuggerUrl, { perMessageDeflate: false });
  await new Promise(r => ws.on('open', r));

  let id = 0; const pending = new Map();
  const errs = [];
  ws.on('message', m => {
    const msg = JSON.parse(m);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
    if (msg.method === 'Runtime.exceptionThrown') errs.push(msg.params.exceptionDetails.text);
  });
  const send = (method, params = {}) => new Promise(r => {
    const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params }));
  });
  const evalJS = async expr => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.result?.exceptionDetails) return '__ERR__ ' + r.result.exceptionDetails.text;
    return r.result?.result?.value;
  };

  await send('Page.enable'); await send('Runtime.enable');
  await send('Page.navigate', { url: 'http://127.0.0.1:8903/index.html' });
  await sleep(9000);

  console.log('=== 运行时错误 ===');
  console.log(errs.length ? errs.join('\n') : '(无)');

  console.log('\n=== 1. 收起态：诊断标题是否真的在屏幕上 ===');
  console.log('summary 文本:', await evalJS('document.querySelector("#diag > summary").textContent'));
  console.log('#perf 类名  :', await evalJS('document.getElementById("perf").className'));
  const rect = await evalJS(`(() => {
    const r = document.querySelector('#diag > summary').getBoundingClientRect();
    return JSON.stringify({w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top), right: Math.round(r.right)});
  })()`);
  console.log('summary 屏幕矩形:', rect, '(w/h > 0 才说明真的可见)');

  console.log('\n=== 2. 可点击性：对 summary 中心点做 hit-test ===');
  const hit = await evalJS(`(() => {
    const s = document.querySelector('#diag > summary');
    const r = s.getBoundingClientRect();
    const el = document.elementFromPoint(r.left + r.width/2, r.top + r.height/2);
    return el ? (el.tagName + (el.closest('#diag') ? ' (命中诊断区内)' : ' (在诊断区外!)')) : 'null';
  })()`);
  console.log('命中元素:', hit);

  console.log('\n=== 3. 真实点击展开（不用 JS 直接设 open）===');
  await evalJS(`(() => {
    const s = document.querySelector('#diag > summary');
    s.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
  })()`);
  await sleep(1200);
  console.log('#diag.open:', await evalJS('document.getElementById("diag").open'));

  console.log('\n=== 4. 各字段实际取值 ===');
  for (const [k, id] of [['GPU','dGPU'],['渲染器','dBackend'],['像素比','dDPR'],['画布','dSize'],
                          ['阴影','dShadow'],['DrawCall','dCalls'],['帧时间','dFrame']]) {
    const v = await evalJS(`document.getElementById("${id}").textContent`);
    const cls = await evalJS(`document.getElementById("${id}").className`);
    console.log(('  ' + k).padEnd(12) + ':', String(v).padEnd(42), cls === 'warn' ? '⚠️ 警告' : '');
  }
  console.log('直方图柱子  :', await evalJS('[...document.querySelectorAll("#ft i")].filter(b=>b.style.height).length'), '/ 60');
  console.log('FPS         :', await evalJS('document.getElementById("fps").textContent'));

  // 收起后应停止更新（零开销）
  await evalJS('document.getElementById("diag").open = false');
  const before = await evalJS('document.getElementById("dCalls").textContent');
  await sleep(1200);
  const after = await evalJS('document.getElementById("dCalls").textContent');
  console.log('\n收起后 DrawCall 是否冻结:', before === after ? `是 (${before} 未变，零开销)` : `否 (${before}→${after})`);

  ws.close();
} finally { chrome.kill(); }