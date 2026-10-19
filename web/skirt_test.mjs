/* 裙摆摆动验证：起无头 Chrome，断言
   1) 页面无 shader 编译错误、模型已加载
   2) aWeight / aDelay / aOut 属性已挂上，且权重分布合理（腰线≈0、下摆≈1、腿鞋≈0）
   3) customDepthMaterial 也被注入了（阴影里的裙子会跟着动）
   4) 走 / 停 / 转向时 uniform 按预期变化（gain 平滑、turn 有甩动再回中）
   5) 不同相位下裙摆顶点世界坐标确实不同（真的在动，不只是数字变了）
   用法：node skirt_test.mjs   （需先在 8903 端口起 http 服务） */
import { spawn } from 'child_process';
import http from 'http';
import fs from 'fs';

const CDP = 9227;
const chrome = spawn('/usr/bin/google-chrome', ['--headless=new', '--no-sandbox', '--disable-gpu-sandbox',
  '--enable-unsafe-swiftshader', '--use-gl=angle', '--use-angle=swiftshader',
  '--window-size=1400,860', `--remote-debugging-port=${CDP}`, '--user-data-dir=/tmp/cdp-skirt', 'about:blank'], { stdio: 'ignore' });

const sleep = ms => new Promise(r => setTimeout(r, ms));
const getJSON = p => new Promise((res, rej) => http.get({ host: '127.0.0.1', port: CDP, path: p },
  r => { let d = ''; r.on('data', c => d += c); r.on('end', () => res(JSON.parse(d))); }).on('error', rej));

for (let i = 0; i < 40; i++) { try { await getJSON('/json/version'); break; } catch { await sleep(250); } }
const page = (await getJSON('/json/list')).find(t => t.type === 'page');
const WS = (await import('ws')).default;
const ws = new WS(page.webSocketDebuggerUrl, { perMessageDeflate: false });
await new Promise(r => ws.on('open', r));

let id = 0; const pend = new Map();
const logs = [];
ws.on('message', m => {
  const x = JSON.parse(m);
  if (x.id && pend.has(x.id)) { pend.get(x.id)(x); pend.delete(x.id); }
  if (x.method === 'Runtime.consoleAPICalled' && /error|Error/.test(JSON.stringify(x.params.args || []))) {
    logs.push(x.params.type + ': ' + (x.params.args || []).map(a => a.value ?? a.description).join(' '));
  }
  if (x.method === 'Runtime.exceptionThrown') {
    logs.push('EXCEPTION: ' + (x.params.exceptionDetails?.exception?.description || x.params.exceptionDetails?.text));
  }
});
const send = (m, p = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method: m, params: p })); });
const evalJS = async expr => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || 'eval failed');
  return r.result?.result?.value;
};

await send('Page.enable');
await send('Runtime.enable');
await send('Page.navigate', { url: 'http://127.0.0.1:8903/index.html' });
await sleep(11000);

const fails = [];
const ok = (cond, label, extra = '') => {
  console.log((cond ? '  PASS  ' : '  FAIL  ') + label + (extra ? '   ' + extra : ''));
  if (!cond) fails.push(label);
};

console.log('\n=== 1. 页面与着色器 ===');
const errBox = await evalJS(`document.getElementById('err').style.display`);
const loadingHidden = await evalJS(`document.getElementById('loading').classList.contains('hide')`);
ok(loadingHidden, '模型已加载完成');
ok(errBox !== 'block', '无加载/编译错误弹窗', 'err.display=' + errBox);
const shaderErr = logs.filter(l => /shader|GLSL|program/i.test(l));
ok(shaderErr.length === 0, '无 shader 编译报错', shaderErr.join(' | '));

console.log('\n=== 2. 权重属性 ===');
let s = await evalJS(`JSON.stringify(window.__iso.probeSkirt())`);
s = JSON.parse(s);
console.log('   ', JSON.stringify(s.weight), 'depthPatched=' + s.depthPatched);
ok(!!s.weight, 'aWeight 属性已生成');
ok(s.weight && s.weight.max > 0.9, '裙摆下摆权重接近 1', 'max=' + (s.weight && s.weight.max));
ok(s.weight && s.weight.max <= 1.001, '权重不超过 1');
ok(s.weight && s.weight.moved > 300, '参与摆动的顶点数合理', 'moved=' + (s.weight && s.weight.moved));
ok(s.depthPatched, 'customDepthMaterial 已注入（阴影同步摆动）');
// 分层：裙区 [0.075,0.30] 应有明确权重；腰以上与腿鞋必须为 0。
// 注意 SKIRT_WAIST=0.30 而非 0.52 —— 0.30~0.52 那段是垂到腰下的头发，不是裙子。
const layers = await evalJS(`(() => {
  const m = window.__iso.model; let g = null;
  m.traverse(o => { if (o.isMesh && o.geometry.attributes.aWeight && !g) g = o.geometry; });
  const p = g.attributes.position.array, w = g.attributes.aWeight.array;
  const band = { waist: [0,0], skirtTop: [0,0], skirtLow: [0,0], hem: [0,0], legs: [0,0] };
  for (let i = 0; i < w.length; i++) {
    const sy = -p[i*3+2];
    let k = sy > 0.32 ? 'waist' : sy > 0.22 ? 'skirtTop' : sy > 0.13 ? 'skirtLow'
          : sy >= 0.075 ? 'hem' : 'legs';
    band[k][0] += w[i]; band[k][1]++;
  }
  const o = {};
  for (const k in band) o[k] = band[k][1] ? +(band[k][0]/band[k][1]).toFixed(3) : -1;
  return JSON.stringify(o);
})()`);
console.log('    分层平均权重', layers);
const L = JSON.parse(layers);
ok(L.waist >= 0 && L.waist < 0.001, '腰以上完全不动', 'mean=' + L.waist);
ok(L.skirtTop > 0.02, '裙区上段有小幅权重', 'mean=' + L.skirtTop);
ok(L.skirtLow > L.skirtTop, '越往下权重越大（上小下大）', L.skirtLow + ' > ' + L.skirtTop);
ok(L.hem > 0.6, '裙摆下摆大幅参与摆动', 'mean=' + L.hem);
ok(L.legs < 0.001, '腿/鞋权重归零（不会跟着平移）', 'mean=' + L.legs);

console.log('\n=== 3. 走 / 停 的状态切换 ===');
await evalJS(`window.__iso.forceWalk(true); window.dispatchEvent(new KeyboardEvent('keydown', {code:'KeyW'}))`);
await sleep(1600);
let w1 = JSON.parse(await evalJS(`JSON.stringify(window.__iso.probeSkirt())`));
console.log('    行走中', JSON.stringify(w1.u));
ok(w1.gain > 0.5, '行走时 gain 上升', 'gain=' + w1.gain);
ok(Math.abs(w1.u.uSide) > 1e-4, '侧摆 uniform 有输出', 'uSide=' + w1.u.uSide);
ok(Math.abs(w1.u.uFlap) > 1e-4, '前后甩 uniform 有输出', 'uFlap=' + w1.u.uFlap);

await evalJS(`window.dispatchEvent(new KeyboardEvent('keyup', {code:'KeyW'}))`);
await sleep(3000);
let w2 = JSON.parse(await evalJS(`JSON.stringify(window.__iso.probeSkirt())`));
const walkSide = Math.abs(w1.u.uSide);
console.log('    停步后', JSON.stringify(w2.u));
ok(w2.gain < 0.02, '停步后 gain 归零', 'gain=' + w2.gain);
// 不能断言绝对为 0：待机保留了 0.0015 幅度的微风（有意设计，否则站定后裙子僵死）。
// 该断言的是「摆动收敛到行走时的 5% 以下」。
ok(Math.abs(w2.u.uSide) < walkSide * 0.05,
   '停步后摆动收敛到行走时的 5% 以下',
   walkSide.toFixed(4) + ' -> ' + Math.abs(w2.u.uSide).toFixed(4));

console.log('\n=== 4. 转向甩动 ===');
/* 不能直接改 rig.rotation.y —— tick() 每帧 rig.rotation.y = facing 会覆写它，
   那样 facing 根本没变，dF 恒为 0，测不到任何东西。必须走 turnBy() 真正推动 facing。
   也不能只推一次：一帧的 dF 被 dt 归一化后要靠多帧逼近才能看到明显峰值，
   所以模拟「持续转动 0.5 秒 → 松手」的真实操作。 */
await evalJS(`window.__iso.turnBy(0.35)`);
let turnPeak = 0;
for (let i = 0; i < 14; i++) {
  await evalJS(`window.__iso.turnBy(0.06)`);
  await sleep(35);
  const v = Math.abs(JSON.parse(await evalJS(`JSON.stringify(window.__iso.probeSkirt())`)).u.uTurn);
  if (v > turnPeak) turnPeak = v;
}
const t1 = JSON.parse(await evalJS(`JSON.stringify(window.__iso.probeSkirt())`));
await sleep(3000);   // 停转后应缓慢回中（衰减系数 3.5，比起步的 14 慢）
const t2 = JSON.parse(await evalJS(`JSON.stringify(window.__iso.probeSkirt())`));
console.log(`    转向峰值 uTurn=${turnPeak.toFixed(4)}  停转3s后 uTurn=${t2.u.uTurn}`);
ok(turnPeak > 5e-4, '转向时产生明显横向甩动', 'peak=' + turnPeak.toFixed(4));
ok(Math.abs(t2.u.uTurn) < turnPeak * 0.5, '停转后甩动回中', t2.u.uTurn);

console.log('\n=== 5. 裙摆真的在动（渲染像素差，不是读原始属性）===');
/* 关键：顶点着色器的位移发生在 GPU 上，JS 读 BufferAttribute 永远拿到原始数据，
   用属性算「顶点位移」是自欺欺人。唯一可靠的办法是渲染两帧比对像素。 */
// 截图区域必须精确落在裙摆上（探针实测），否则截到的是背景/头发的微动
const box = JSON.parse(await evalJS(`JSON.stringify(window.__iso.skirtScreenBox(30))`));
console.log('    裙摆屏幕包围盒', JSON.stringify(box));
ok(!!box && box.width > 60 && box.height > 60, '裙摆在屏幕上有可测范围', JSON.stringify(box));
async function grabClip() {
  // CDP 的 clip 宽高必须是整数，传浮点会直接返回 error 而不带 data
  const clip = {
    x: Math.round(box.x), y: Math.round(box.y),
    width: Math.round(box.width), height: Math.round(box.height), scale: 1
  };
  const s = await send('Page.captureScreenshot', { format: 'png', clip });
  if (!s.result?.data) throw new Error('截图失败: ' + JSON.stringify(s).slice(0, 300));
  return Buffer.from(s.result.data, 'base64');
}
// 解 PNG 太重，改用更直接的办法：让页面自己算差异。
// 在页面里建一个离屏 canvas 载入两次截图的 dataURL，逐像素比较裙摆区域。
async function pixelDiff(bufA, bufB) {
  const b64 = b => b.toString('base64');
  return await evalJS(`(async () => {
    const load = b64 => new Promise((res, rej) => {
      const im = new Image(); im.onload = () => res(im); im.onerror = rej;
      im.src = 'data:image/png;base64,' + b64;
    });
    const [ia, ib] = await Promise.all([load(${JSON.stringify(b64(bufA))}), load(${JSON.stringify(b64(bufB))})]);
    const cv = document.createElement('canvas'); cv.width = ia.width; cv.height = ia.height;
    const cx = cv.getContext('2d', { willReadFrequently: true });
    cx.drawImage(ia, 0, 0); const da = cx.getImageData(0, 0, cv.width, cv.height).data;
    cx.clearRect(0, 0, cv.width, cv.height);
    cx.drawImage(ib, 0, 0); const db = cx.getImageData(0, 0, cv.width, cv.height).data;
    let diff = 0, maxd = 0;
    for (let i = 0; i < da.length; i += 4) {
      const d = Math.abs(da[i]-db[i]) + Math.abs(da[i+1]-db[i+1]) + Math.abs(da[i+2]-db[i+2]);
      if (d > 6) diff++;
      if (d > maxd) maxd = d;
    }
    return JSON.stringify({ diff, total: da.length/4, maxd });
  })()`);
}
await evalJS(`window.__iso.forceWalk(true)`);
await evalJS(`window.__iso.skirt.uPhase.value = 0.0`);
await sleep(300);
const p0 = await grabClip();
await evalJS(`window.__iso.skirt.uPhase.value = 3.14159`);
await sleep(300);
const p1 = await grabClip();
const dres = JSON.parse(await pixelDiff(p0, p1));
console.log(`    差异像素 ${dres.diff}/${dres.total} (${(dres.diff/dres.total*100).toFixed(2)}%)  最大通道差 ${dres.maxd}`);
ok(dres.diff > 300, '改变相位后裙摆区域有明显像素变化（裙摆在动）', 'diff=' + dres.diff);
ok(dres.maxd > 40, '存在显著色差（非噪点级抖动）', 'maxd=' + dres.maxd);

console.log('\n=== 6. 关掉开关后位移 uniform 必须全零 ===');
/* 两个坑：
   1) 不能用「两次截图逐字节相同」判定：页面待机呼吸（bob.position.y = sin(phase)*0.011）
      每帧都在动，任何两帧截图本来就不可能逐字节相同 —— 那是测试方法错了，不是功能坏了。
   2) 不能把 uPhase 也算进去：uPhase 是相位不是位移量，着色器里 d 只由其余五个
      uniform 决定，uPhase 非零不代表裙子在动。 */
await evalJS(`document.getElementById('tSkirt').click()`);
await sleep(1500);   // gain 是按 dt*5.5 指数衰减的，600ms 时还剩 0.003，尾巴会让 uSide 残留 1e-4 量级
const off = JSON.parse(await evalJS(`JSON.stringify(window.__iso.probeSkirt())`));
const DISP = ['uSide', 'uFlap', 'uFlare', 'uLift', 'uTurn'];
const maxU = Math.max(...DISP.map(k => Math.abs(off.u[k])));
console.log('    关闭后位移 uniform',
  DISP.map(k => k + '=' + off.u[k]).join(' '), ' gain=' + off.gain);
ok(off.on === false, 'SKIRT.on 已置 false');
ok(maxU < 1e-5, '关闭后全部位移 uniform 归零（顶点原样返回）', 'max|u|=' + maxU);
ok(off.gain < 0.02, '关闭后 gain 归零', 'gain=' + off.gain);

console.log('\n=== 截图 ===');
await evalJS(`document.getElementById('tSkirt').click(); window.__iso.forceWalk(true); window.__iso.skirt.uPhase.value = 1.2;`);
await sleep(400);
const shot = await send('Page.captureScreenshot', { format: 'png' });
fs.writeFileSync('skirt_view.png', Buffer.from(shot.result.data, 'base64'));
console.log('    已存 skirt_view.png');

if (logs.length) { console.log('\n控制台错误:'); logs.slice(0, 10).forEach(l => console.log('   ', l.slice(0, 220))); }
console.log('\n' + (fails.length ? '✗ 失败 ' + fails.length + ' 项: ' + fails.join(' / ') : '✓ 全部通过'));
ws.close(); chrome.kill();
process.exit(fails.length ? 1 : 0);