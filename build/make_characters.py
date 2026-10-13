# -*- coding: utf-8 -*-
"""
由角色設定圖裁切出動畫用素材
  python3 build/make_characters.py

輸入：build/src/allan_sheet.jpg、build/src/arale_sheet.jpg（講師／助教角色設定圖）
輸出：assets/allan.png、assets/arale.png（去背全身像）
      assets/face/allan_*.jpg、assets/face/arale_*.jpg（表情包，用於字幕頭像）
"""
import os
from collections import deque
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "build", "src")
OUT = os.path.join(ROOT, "assets")


def remove_bg(im, thr=226):
    """從邊緣做 flood fill，把連通的近白色背景變透明（線稿外框會擋住填色）。"""
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()

    def bg(p):
        r, g, b, _ = p
        return min(r, g, b) >= thr and max(r, g, b) - min(r, g, b) < 28

    seen = bytearray(w * h)
    q = deque()
    for x in range(w):
        q.append((x, 0)); q.append((x, h - 1))
    for y in range(h):
        q.append((0, y)); q.append((w - 1, y))
    while q:
        x, y = q.popleft()
        i = y * w + x
        if seen[i] or not bg(px[x, y]):
            continue
        seen[i] = 1
        if x > 0: q.append((x - 1, y))
        if x < w - 1: q.append((x + 1, y))
        if y > 0: q.append((x, y - 1))
        if y < h - 1: q.append((x, y + 1))
    mask = Image.new("L", (w, h), 255)
    mp = mask.load()
    for y in range(h):
        row = y * w
        for x in range(w):
            if seen[row + x]:
                mp[x, y] = 0
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    im.putalpha(mask)
    return im


def fit_h(im, h):
    return im.resize((round(im.width * h / im.height), h), Image.LANCZOS)


def main():
    os.makedirs(os.path.join(OUT, "face"), exist_ok=True)
    A = Image.open(os.path.join(SRC, "allan_sheet.jpg")).convert("RGB")
    R = Image.open(os.path.join(SRC, "arale_sheet.jpg")).convert("RGB")

    # ---- Allan 全身（正面單張），左右翻轉讓手勢指向左側教材，名牌再貼回正向 ----
    a = A.crop((50, 80, 780, 1475))
    wipe = Image.new("RGB", (a.width - 714, a.height - 600), (255, 255, 255))
    a.paste(wipe, (714, 600))  # 清除右側鄰近圖塊的殘影
    badge_box = (290, 600, 358, 694)
    badge = a.crop(badge_box)
    a = a.transpose(Image.FLIP_LEFT_RIGHT)
    a.paste(badge, (a.width - badge_box[2], badge_box[1]))
    a = remove_bg(a)
    fit_h(a, 760).save(os.path.join(OUT, "allan.png"), optimize=True)

    # ---- 阿拉蕾 全身（揮手、黃色帽T 版本） ----
    r = R.crop((60, 790, 420, 1480))
    r = remove_bg(r)
    fit_h(r, 560).save(os.path.join(OUT, "arale.png"), optimize=True)

    # ---- 表情包（字幕頭像） ----
    def face(img, box, name):
        f = img.crop(box).resize((200, 200), Image.LANCZOS)
        f.save(os.path.join(OUT, "face", name + ".jpg"), quality=86)

    ax = [(770, 1020), (1078, 1328), (1385, 1635), (1690, 1940)]
    for name, (col, row) in {
        "allan_smile": (0, 0), "allan_laugh": (1, 0), "allan_think": (2, 0), "allan_confused": (3, 0),
        "allan_surprised": (0, 1), "allan_point": (1, 1), "allan_wink": (2, 1), "allan_talk": (3, 1),
    }.items():
        x0, x1 = ax[col]
        y0 = 800 if row == 0 else 1140
        if name == "allan_point":
            x0, x1 = x0 + 10, x1 + 10
        face(A, (x0, y0, x1, y0 + (x1 - x0)), name)

    rx = [(466, 766), (853, 1153), (1240, 1540), (1623, 1923)]
    for name, (col, row) in {
        "arale_laugh": (0, 0), "arale_think": (1, 0), "arale_surprised": (2, 0), "arale_confused": (3, 0),
        "arale_talk": (0, 1), "arale_cry": (1, 1), "arale_wink": (2, 1), "arale_cheer": (3, 1),
    }.items():
        x0, x1 = rx[col]
        y0 = 812 if row == 0 else 1146
        face(R, (x0, y0, x1, y0 + (x1 - x0)), name)
    print("ok")


if __name__ == "__main__":
    main()
