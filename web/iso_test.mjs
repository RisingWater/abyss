// 验证 45° 等距视角锁定：
//  1) 派发真实的鼠标拖拽 / 右键拖拽 / 双指手势，模拟用户乱动视角
//  2) 派发滚轮，确认缩放仍然可用（不被误锁）
//  3) 每次操作后读window.__iso.probe()，核对仰角/方位角恒定
import { spawn } from 'child_process';
import http from 'http';

const CDP = 9224;
const chrome = spawn('/usr/bin/google-chrome', [
  '--headless=new', '--disable-gpu-sandbox', '--no-sandbox',
  '--enable-unsafe-swiftshader', '--use-gl=angle', '--use-angle=swiftshader',
  '--window-size=1280,800', `--remote-debugging-port=${CDP}`,
  '--user-data-dir=/tmp/cdp-iso', 'about:blank'
], { stdio: 'ignore' });

const sleep = ms => new Promise(r => setTimeout(r, ms));
const getJSON = path => new Promise((res, rej) => {
  http.get({ host: '127.0.0.1', port: CDP, path }, r => {
    let d = ''; r.on('data', c => d += c); r.on('end', () => res(JSON.parse(d)));
  }).on('error', rej);
});

const EXPECT_ELEV = 35.264;  // asin(1/√3)
const EXPECT_AZIM = 45;

try {
  for (let i = 0; i < 40; i++) { try { await getJSON('/json/version'); break; } catch { await sleep(250); } }
  const tabs = await getJSON('/json/list');
  const page = tabs.find(t => t.type === 'page');
  const WS = (await import('ws')).default;
  const ws = new WS(page.webSocketDebuggerUrl, { perMessageDeflate: false });
  await new Promise(r => ws.on('open', r));

  let id = 0; const pending = new Map(); const errs = [];
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
    if (r.result?.exceptionDetails) return { err: r.result.exceptionDetails.text };
    return r.result?.result?.value;
  };
  const mouse = (type, x, y, button = 'left', extra = {}) => send('Input.dispatchMouseEvent', {
    type, x, y, button, buttons: extra.buttons ?? (type === 'mouseMoved' ? 1 : (button === 'right' ? 2 : 1)),
    clickCount: extra.clickCount ?? (type === 'mousePressed' || type === 'mouseReleased' ? 1 : 0),
    ...extra
  });
  const touch = (type, points) => send('Input.dispatchTouchEvent', { type, touchPoints: points });

  await send('Page.enable'); await send('Runtime.enable');
  await send('Page.navigate', { url: 'http://127.0.0.1:8903/index.html' });
  await sleep(8000);

  const hook = await evalJS('typeof window.__iso');
  if (hook !== 'object') { console.log('!! 页面无 __iso 钩子，加载失败'); console.log(errs); ws.close(); chrome.kill(); process.exit(1); }

  const fmt = p => `仰角 ${p.elev.toFixed(2)}°  方位角 ${p.azim.toFixed(2)}°  距离 ${p.dist.toFixed(2)}`;
  const judge = (p, tag) => {
    const okE = Math.abs(p.elev - EXPECT_ELEV) < 0.01;
    const okA = Math.abs(p.azim - EXPECT_AZIM) < 0.01;
    console.log(`  ${okE && okA ? '锁定✓' : '漂移✗'}  ${tag}: ${fmt(p)}`);
    return okE && okA;
  };

  let allOk = true;
  const probe = async () => {
    const s = await evalJS('JSON.stringify(__iso.probe())');
    return typeof s === 'string' ? JSON.parse(s) : { err: String(s) };
  };

  console.log('=== 0. 初始状态 ===');
  allOk &= judge(await probe(), '载入后');

  console.log('\n=== 1. 左键横向大幅拖拽（原本会把视角转歪）===');
  await mouse('mousePressed', 640, 400);
  for (let i = 1; i <= 10; i++) await mouse('mouseMoved', 640 + i * 60, 400, 'left', { buttons: 1 });
  await mouse('mouseReleased', 1240, 400);
  await sleep(400);
  allOk &= judge(await probe(), '拖拽后');

  console.log('\n=== 2. 左键纵向拖拽（原本会俯视/仰视）===');
  await mouse('mousePressed', 640, 400);
  for (let i = 1; i <= 10; i++) await mouse('mouseMoved', 640, 400 - i * 50, 'left', { buttons: 1 });
  await mouse('mouseReleased', 640, 100);
  await sleep(400);
  allOk &= judge(await probe(), '纵拖后');

  console.log('\n=== 3. 右键拖拽平移 ===');
  await mouse('mousePressed', 640, 400, 'right', { buttons: 2 });
  for (let i = 1; i <= 8; i++) await mouse('mouseMoved', 640 + i * 40, 400 + i * 20, 'right', { buttons: 2 });
  await mouse('mouseReleased', 960, 560, 'right');
  await sleep(400);
  allOk &= judge(await probe(), '右拖后');

  console.log('\n=== 4. 双指捏合手势 ===');
  await touch('touchStart', [{ x: 500, y: 400, id: 1 }, { x: 780, y: 400, id: 2 }]);
  for (let i = 1; i <= 6; i++) {
    await touch('touchMove', [{ x: 500 + i * 20, y: 400, id: 1 }, { x: 780 - i * 20, y: 400, id: 2 }]);
  }
  await touch('touchEnd', []);
  await sleep(400);
  allOk &= judge(await probe(), '捏合后');

  console.log('\n=== 5. 滚轮缩放：方向必须不变，距离必须变 ===');
  const before = await probe();
  await send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: 640, y: 400, deltaX: 0, deltaY: -600 });
  await sleep(700);
  const zoomed = await probe();
  await send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: 640, y: 400, deltaX: 0, deltaY: 1200 });
  await sleep(700);
  const out = await probe();
  console.log(`  放大: 距离 ${before.dist.toFixed(2)} → ${zoomed.dist.toFixed(2)}  ${zoomed.dist < before.dist ? '✓ 变近' : '✗ 没变'}`);
  console.log(`  缩小: 距离 ${zoomed.dist.toFixed(2)} → ${out.dist.toFixed(2)}  ${out.dist > zoomed.dist ? '✓ 变远' : '✗ 没变'}`);
  console.log(`  方向: 放大后 ${fmt(zoomed)}`);
  console.log(`  方向: 缩小后 ${fmt(out)}`);
  const zoomOk = zoomed.dist < before.dist && out.dist > zoomed.dist
    && Math.abs(zoomed.elev - EXPECT_ELEV) < 0.01 && Math.abs(out.elev - EXPECT_ELEV) < 0.01
    && Math.abs(zoomed.azim - EXPECT_AZIM) < 0.01 && Math.abs(out.azim - EXPECT_AZIM) < 0.01;
  console.log('  ' + (zoomOk ? '缩放正常且方向恒定 ✓' : '缩放异常 ✗'));
  allOk = allOk && zoomOk;

  console.log('\n=== 6. 跟随开启时移动角色，相机应平移但方向不变 ===');
  await evalJS('document.getElementById("tFollow").checked = true');
  await evalJS(`(() => {
    for (const t of ['w','a','s','d']) dispatchEvent(new KeyboardEvent('keydown', {key: t}));
    return 1;
  })()`);
  await sleep(1500);
  await evalJS(`(() => {
    for (const t of ['w','a','s','d']) dispatchEvent(new KeyboardEvent('keyup', {key: t}));
    return 1;
  })()`);
  await sleep(600);
  allOk &= judge(await probe(), '角色移动后');

  console.log('\n=== 7. R 重置 ===');
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'r', code: 'KeyR', windowsVirtualKeyCode: 82 });
  await sleep(800);
  allOk &= judge(await probe(), '重置后');

  console.log('\n=== 8. FOV ===');
  console.log('  ' + (await evalJS('__iso.camera.fov')) + '° （等距建议 30°，越小越接近正交投影）');

  console.log('\n=== 运行时错误 ===');
  console.log(errs.length ? errs.join('\n') : '(无)');

  console.log('\n=================================');
  console.log(allOk ? '全部通过：视角始终锁定 45° 等距' : '存在漂移，需修复');

  ws.close();
} finally { chrome.kill(); }