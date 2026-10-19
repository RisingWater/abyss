// 用 Chrome DevTools Protocol 驱动真实 Chrome 验证诊断面板。
// 无头环境强制 SwiftShader 软渲染，正好能检验「软件渲染告警」这条逻辑。
// 用法: node diag_test.mjs [port]
import { spawn } from 'child_process';
import http from 'http';
import WS from 'ws';

const PORT = process.argv[2] || '8903';
const CDP = 9333;
const chrome = spawn('/usr/bin/google-chrome', [
  '--headless=new', '--no-sandbox', '--disable-gpu-sandbox',
  '--enable-unsafe-swiftshader',
  '--use-gl=angle', '--use-angle=swiftshader',
  '--window-size=1280,800', `--remote-debugging-port=${CDP}`,
  '--user-data-dir=/tmp/cdp-prof-' + Date.now(), 'about:blank'
], { stdio: 'ignore' });

const sleep = ms => new Promise(r => setTimeout(r, ms));
const getJSON = path => new Promise((res, rej) => {
  http.get({ host: '127.0.0.1', port: CDP, path }, r => {
    let d = ''; r.on('data', c => d += c); r.on('end', () => res(JSON.parse(d)));
  }).on('error', rej);
});

try {
  for (let i = 0; i < 60; i++) { try { await getJSON('/json/version'); break; } catch { await sleep(250); } }
  const tabs = await getJSON('/json/list');
  const page = tabs.find(t => t.type === 'page');
  const ws = new WS(page.webSocketDebuggerUrl, { perMessageDeflate: false });
  await new Promise(r => ws.on('open', r));

  let id = 0; const pending = new Map(); const errs = [];
  ws.on('message', m => {
    const msg = JSON.parse(m);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); return; }
    if (msg.method === 'Runtime.exceptionThrown')
      errs.push(msg.params.exceptionDetails.text + ' ' +
                (msg.params.exceptionDetails.exception?.description || ''));
    if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error')
      errs.push('console.error: ' + msg.params.args.map(a => a.value).join(' '));
  });
  const send = (method, params = {}) => new Promise(r => {
    const i = ++id; pending.set(i, r);
    ws.send(JSON.stringify({ id: i, method, params }));
  });
  const evalJS = async expr => {
    const r = await send('Runtime.evaluate',
      { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.result?.exceptionDetails)
      return '<<异常: ' + r.result.exceptionDetails.text + '>>';
    return r.result?.result?.value;
  };

  await send('Page.enable'); await send('Runtime.enable');
  await send('Page.navigate', { url: `http://127.0.0.1:${PORT}/index.html` });
  await sleep(9000);   // 等 GLB 载入 + 跑几秒帧循环

  console.log('=== 运行时错误 ===');
  console.log(errs.length ? errs.join('\n') : '(无)');

  console.log('\n=== 性能仪表（折叠态） ===');
  console.log('FPS      :', await evalJS('document.getElementById("fps").textContent'));
  console.log('三角面   :', await evalJS('document.getElementById("tris").textContent'));
  console.log('画质档位 :', await evalJS('document.getElementById("perfmode").textContent'));
  console.log('折叠时诊断内容不可见:',
    await evalJS('getComputedStyle(document.getElementById("diag")).display') === 'none' ? '是（零开销）' : '否');

  console.log('\n=== 展开诊断面板 ===');
  await evalJS('document.getElementById("diag").open = true');
  await sleep(2000);
  for (const [k, el] of [['GPU', 'dGPU'], ['渲染器', 'dBackend'], ['像素比', 'dDPR'],
                          ['画布', 'dSize'], ['阴影', 'dShadow'],
                          ['DrawCall', 'dCalls'], ['帧时间', 'dFrame']]) {
    const v = await evalJS(`document.getElementById("${el}").textContent`);
    const cls = await evalJS(`document.getElementById("${el}").className`);
    console.log(k.padEnd(10) + ':', v, cls === 'warn' ? '  ⚠️ 软渲染告警已触发' : '');
  }
  const bars = await evalJS(
    'document.querySelectorAll("#ft i").length + "/" + ' +
    '[...document.querySelectorAll("#ft i")].filter(b=>b.style.height).length');
  console.log('\n帧时间直方图(总/已赋值):', bars);
  const sample = await evalJS(
    '[...document.querySelectorAll("#ft i")].slice(0,5).map(b=>b.style.height).join(" ")');
  console.log('前5根柱子高度:', sample);

  ws.close();
} finally { chrome.kill(); }