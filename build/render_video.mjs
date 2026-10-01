// 將動畫簡報輸出為 MP4（逐格渲染 + 旁白混音）
//   node build/render_video.mjs                 → output/ISO27001_資產管理_AllanLo.mp4
//   node build/render_video.mjs --stills 12,80  → 只輸出指定秒數的截圖到 output/stills/
import { createRequire } from "module";
import { spawn, execFileSync } from "child_process";
import fs from "fs";
import path from "path";
import os from "os";
import { fileURLToPath } from "url";

const require = createRequire(import.meta.url);
let pw;
try { pw = require("playwright"); } catch { pw = require(path.join(process.env.NODE_PATH || "/opt/node22/lib/node_modules", "playwright")); }

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUT = path.join(ROOT, "output");
const FPS = +(process.env.FPS || 20);
const WORKERS = +(process.env.WORKERS || Math.max(1, Math.min(4, os.cpus().length)));
const url = "file://" + path.join(ROOT, "index.html") + "#render";
fs.mkdirSync(OUT, { recursive: true });

const fontCache = new Map();
async function openPage(browser) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1 });
  // 字型經由 curl（信任系統 CA／代理 CA）取得後回填，避免瀏覽器憑證問題
  await page.route(/fonts\.(googleapis|gstatic)\.com/, async route => {
    const u = route.request().url();
    if (!fontCache.has(u)) fontCache.set(u, execFileSync("curl", ["-sS", "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36", u], { maxBuffer: 64 << 20 }));
    const body = fontCache.get(u);
    await route.fulfill({ status: 200, body, headers: { "content-type": u.includes("googleapis") ? "text/css" : "font/woff2", "access-control-allow-origin": "*" } });
  });
  await page.goto(url, { waitUntil: "load" });
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(["700 30px 'LXGW WenKai TC'", "500 20px 'Noto Sans TC'", "700 20px 'Noto Sans TC'", "800 20px 'Baloo 2'"].map(f => document.fonts.load(f, "資產管理稽核ABC123")));
  });
  await page.waitForTimeout(500);
  return page;
}

function run(cmd, args, opts = {}) {
  return new Promise((res, rej) => {
    const p = spawn(cmd, args, { stdio: ["ignore", "inherit", "inherit"], ...opts });
    p.on("exit", c => (c === 0 ? res() : rej(new Error(cmd + " exit " + c))));
  });
}

const browser = await pw.chromium.launch();
const stillsArg = process.argv.indexOf("--stills");

if (stillsArg > 0) {
  const dir = path.join(OUT, "stills");
  fs.mkdirSync(dir, { recursive: true });
  const page = await openPage(browser);
  for (const s of process.argv[stillsArg + 1].split(",").map(Number)) {
    await page.evaluate(t => window.__render(t), s);
    await page.screenshot({ path: path.join(dir, `t${String(s).padStart(4, "0")}.png`) });
  }
  await browser.close();
  process.exit(0);
}

const duration = await (await openPage(browser)).evaluate(() => window.__duration);
const total = Math.ceil(duration * FPS);
const per = Math.ceil(total / WORKERS);
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "render-"));
console.log(`duration ${duration}s, ${total} frames, ${WORKERS} workers`);

await Promise.all([...Array(WORKERS).keys()].map(async w => {
  const page = await openPage(browser);
  const from = w * per, to = Math.min(total, from + per);
  const seg = path.join(tmp, `seg${w}.mp4`);
  const ff = spawn("ffmpeg", ["-v", "error", "-y", "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "mjpeg", "-i", "-",
    "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p", "-r", String(FPS), seg],
    { stdio: ["pipe", "inherit", "inherit"] });
  const done = new Promise(r => ff.on("exit", r));
  for (let f = from; f < to; f++) {
    await page.evaluate(t => window.__render(t), f / FPS);
    const buf = await page.screenshot({ type: "jpeg", quality: 90 });
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once("drain", r));
    if (f % 600 === 0) console.log(`worker ${w}: ${f - from}/${to - from}`);
  }
  ff.stdin.end();
  await done;
}));
await browser.close();

const list = path.join(tmp, "list.txt");
fs.writeFileSync(list, [...Array(WORKERS).keys()].map(w => `file '${path.join(tmp, `seg${w}.mp4`)}'`).join("\n"));
const outFile = path.join(OUT, "ISO27001_資產管理_AllanLo.mp4");
await run("ffmpeg", ["-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", list, "-i", path.join(ROOT, "audio", "narration.mp3"),
  "-c:v", "copy", "-c:a", "aac", "-b:a", "96k", "-shortest", "-movflags", "+faststart", outFile]);
fs.rmSync(tmp, { recursive: true, force: true });
console.log("written", outFile);
