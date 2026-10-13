# -*- coding: utf-8 -*-
"""
產生旁白音檔、時間軸與講稿
  python3 build/build.py

輸出：
  audio/narration.mp3   全片旁白（Allan：台灣男聲 zh-TW-YunJheNeural；阿拉蕾：zh-TW-HsiaoYuNeural）
  timeline.js           播放器使用的時間軸 + 口型資料
  講稿.md               完整講稿
"""
import asyncio, hashlib, json, os, ssl, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "build"))
from lesson import SCENES, ZONES  # noqa: E402

CACHE = os.path.join(ROOT, "build", ".tts_cache")
SR = 24000
VOICES = {
    "A": {"voice": "zh-TW-YunJheNeural", "rate": "+4%", "pitch": "+0Hz"},
    "R": {"voice": "zh-TW-HsiaoYuNeural", "rate": "+12%", "pitch": "+30Hz"},
}
LEAD, TAIL, GAP_SAME, GAP_SWITCH = 1.0, 1.1, 0.35, 0.55
ENV_FPS = 25  # 口型取樣率


def mood_of(who, text):
    """依台詞挑選字幕頭像的表情（對應 assets/face/）。"""
    has = lambda *ks: any(k in text for k in ks)
    if who == "A":
        if has("噗噗"): return "point"
        if has("哈哈", "答對了", "講得太好了", "很好的比喻"): return "laugh"
        if has("好問題", "居然", "更慘的是", "撐不到"): return "surprised"
        if has("改善重點", "核心中的核心", "最愛的查核點", "一定做"): return "point"
        if has("掰掰", "下一堂課見", "很好！", "沒錯", "對！"): return "wink"
        if has("為什麼", "怎麼", "我會問", "追問"): return "think"
        return "smile"
    if has("嗚嗚"): return "cry"
    if has("好可怕", "然後呢", "哇！離職"): return "surprised"
    if has("欸？", "咦？"): return "confused"
    if has("？"): return "think"
    if has("懂了", "學到了", "記住了", "救一家公司", "畫重點"): return "wink"
    if has("第一章", "第二章", "第三章", "有測驗", "認真聽", "抱緊緊"): return "cheer"
    if has("阿拉蕾知道", "這題簡單", "哈囉", "掰掰"): return "talk"
    return "laugh"


def patch_ssl():
    """代理環境需信任指定 CA。"""
    import edge_tts.communicate as ec
    ca = os.environ.get("SSL_CERT_FILE") or "/root/.ccr/ca-bundle.crt"
    if os.path.exists(ca):
        ec._SSL_CTX = ssl.create_default_context(cafile=ca)


async def tts_one(who, text, path):
    import edge_tts
    v = VOICES[who]
    for attempt in range(4):
        try:
            await edge_tts.Communicate(text, v["voice"], rate=v["rate"], pitch=v["pitch"]).save(path)
            if os.path.getsize(path) > 0:
                return
        except Exception as e:  # 網路偶發錯誤重試
            print("  retry", attempt, e)
            await asyncio.sleep(2 ** attempt)
    raise RuntimeError("TTS failed: " + text)


def cache_path(who, text):
    v = VOICES[who]
    h = hashlib.sha1(json.dumps([v, text], ensure_ascii=False).encode()).hexdigest()[:16]
    return os.path.join(CACHE, f"{who}_{h}.mp3")


async def synth_all(jobs):
    sem = asyncio.Semaphore(6)

    async def run(who, text):
        p = cache_path(who, text)
        if os.path.exists(p) and os.path.getsize(p) > 0:
            return
        async with sem:
            print("TTS", who, text[:24])
            await tts_one(who, text, p)

    await asyncio.gather(*(run(w, t) for w, t in jobs))


def decode(path):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
        check=True, capture_output=True).stdout
    import array
    a = array.array("h")
    a.frombytes(raw)
    # 修剪頭尾靜音，讓節奏更緊湊
    th = 300
    s = 0
    while s < len(a) and abs(a[s]) < th:
        s += 1
    e = len(a)
    while e > s and abs(a[e - 1]) < th:
        e -= 1
    s = max(0, s - int(0.04 * SR))
    e = min(len(a), e + int(0.08 * SR))
    return a[s:e]


def main():
    os.makedirs(CACHE, exist_ok=True)
    os.makedirs(os.path.join(ROOT, "audio"), exist_ok=True)
    patch_ssl()

    norm = []
    for sc in SCENES:
        ls = []
        for ln in sc["lines"]:
            who, text = ln[0], ln[1]
            show = ln[2] if len(ln) > 2 else None
            ls.append({"who": who, "text": text, "show": show, "mood": mood_of(who, text)})
        norm.append(ls)

    asyncio.run(synth_all([(l["who"], l["text"]) for ls in norm for l in ls]))

    import array
    pcm = array.array("h")
    t = 0.0

    def add_silence(sec):
        nonlocal t
        n = int(round(sec * SR))
        pcm.extend([0] * n)
        t += n / SR

    out_scenes = []
    for sc, ls in zip(SCENES, norm):
        start = t
        add_silence(LEAD)
        prev = None
        lines_out = []
        for l in ls:
            if prev is not None:
                add_silence(GAP_SAME if prev == l["who"] else GAP_SWITCH)
            seg = decode(cache_path(l["who"], l["text"]))
            ls_start = t
            pcm.extend(seg)
            t += len(seg) / SR
            lines_out.append({**l, "start": round(ls_start, 3), "end": round(t, 3)})
            prev = l["who"]
        add_silence(TAIL)
        s = {k: v for k, v in sc.items() if k != "lines"}
        s.update({"start": round(start, 3), "end": round(t, 3), "lines": lines_out})
        out_scenes.append(s)

    # 口型包絡（0~9）
    step = SR // ENV_FPS
    env = []
    for i in range(0, len(pcm), step):
        chunk = pcm[i:i + step]
        if not chunk:
            break
        rms = (sum(x * x for x in chunk[::4]) / max(1, len(chunk[::4]))) ** 0.5
        env.append(min(9, int(rms / 900)))
    env_str = "".join(str(x) for x in env)

    wav = os.path.join(CACHE, "narration.raw")
    with open(wav, "wb") as f:
        f.write(pcm.tobytes())
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", wav,
                    "-codec:a", "libmp3lame", "-b:a", "64k", "-ar", "24000",
                    os.path.join(ROOT, "audio", "narration.mp3")], check=True)

    data = {"duration": round(t, 3), "envFps": ENV_FPS, "env": env_str, "zones": ZONES, "scenes": out_scenes}
    with open(os.path.join(ROOT, "timeline.js"), "w", encoding="utf-8") as f:
        f.write("// 由 build/build.py 自動產生，請勿手動修改\nwindow.LESSON = ")
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")

    # 講稿
    md = ["# ISO 27001:2022 資產管理｜動畫課程講稿", "",
          "> 講師：Q 版 Allan Lo（台灣男聲）｜助教：阿拉蕾", "",
          f"總長度約 {int(t // 60)} 分 {int(t % 60)} 秒", ""]
    for s in out_scenes:
        mm, ss = divmod(int(s["start"]), 60)
        md.append(f"## [{mm:02d}:{ss:02d}] {s['chapter']}｜{s['title']}")
        md.append("")
        for l in s["lines"]:
            name = "Allan" if l["who"] == "A" else "阿拉蕾"
            md.append(f"- **{name}**：{l['text']}")
        md.append("")
    with open(os.path.join(ROOT, "講稿.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"done: {len(out_scenes)} scenes, {sum(len(s['lines']) for s in out_scenes)} lines, {t:.1f}s")


if __name__ == "__main__":
    main()
