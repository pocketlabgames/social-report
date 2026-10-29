"""Beaker Lab Halloween reel "Mirror Maze" (ad107 draft): 1080x1920, 30 fps, ~19.6 s.

Story (Guy, Oct 29): the purple skeleton beaker and the green cat beaker wander a Halloween mirror maze, scared,
find each other and hug; zoom into the cat's fizzy liquid; bubble transition into gameplay; usual end card.

The characters and maze are drawn here with Pillow (styled after ad105 "Trick or Treat"). Gameplay and the end card
are cut from the ad105 video, so pass its path:
    python3 render_mirror_maze.py /path/to/ad105-tue-trick-or-treat-spooky-dark.mp4 [music.mp3] [--stills]
Output: ad107-mirror-maze.mp4 next to this script (silent unless a music file is given).
"""
import math
import os
import random
import subprocess
import sys
import tempfile
from multiprocessing import Pool

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
K = 2                                     # draw at 2x, downscale for smooth edges
CS = 1.6                                  # character scale on screen
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "ad107-mirror-maze.mp4")
FONT = "/usr/share/fonts/opentype/inter/InterDisplay-Black.otf"
EMOJI = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"

ANIM_END = 14.2                           # our animation (maze, hug, fizz, bubble transition) runs 0-14.2 s
GP_IN, GP_OUT = 6.0, 10.6                 # ad105 gameplay: 6.0 s is revealed by the bubbles, then plays on
CARD_IN, CARD_OUT = 11.0, 13.0            # ad105 end card
CARD_HOLD = 0.5                           # freeze the end card a little longer

PURPLE, PURPLE_D = (140, 70, 220), (96, 40, 168)
GREEN, GREEN_D = (110, 230, 60), (60, 170, 30)
DOT = (124, 70, 200)
INK, WHITE = (18, 12, 28), (255, 255, 255)
BUBBLE_TXT = (60, 30, 100)


def k(v):
    return int(round(v * K))


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def seg(t, a, b):
    return clamp((t - a) / (b - a))


def ease(x):
    return x * x * (3 - 2 * x)


def back_out(x):
    c = 1.7
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def mix(c1, c2, x):
    return tuple(int(a + (b - a) * x) for a, b in zip(c1, c2))


_FONTS = {}


def font(size):
    key = int(k(size))
    if key not in _FONTS:
        _FONTS[key] = ImageFont.truetype(FONT, key)
    return _FONTS[key]


# ---------------------------------------------------------------- characters
def tube(costume, t, mood="calm", walk=0.0, look=0.0, blink=False):
    """One beaker character on its own RGBA layer. Returns (layer, foot_x, foot_y) in layer pixels.

    costume: "skeleton" (purple) or "cat" (green). mood: calm | scared | happy.
    walk: walk-cycle phase in cycles (0 = standing). look: -1..1 pupil direction.
    """
    lw, lh = k(420), k(560)
    L = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    d = ImageDraw.Draw(L)
    cx, foot = lw // 2, k(520)
    tw, th = k(112), k(270)                 # tube width / height
    x0, x1 = cx - tw // 2, cx + tw // 2
    yb = foot - k(46)                        # bottom of the tube
    y0 = yb - th
    liquid, dark = (PURPLE, PURPLE_D) if costume == "skeleton" else (GREEN, GREEN_D)
    # legs (walk cycle)
    for i, sgn in enumerate((-1, 1)):
        ph = walk * 2 * math.pi + i * math.pi
        lift = max(0, math.sin(ph)) * k(14) if walk else 0
        sw = math.cos(ph) * k(12) if walk else 0
        lx = cx + sgn * k(22) + sw
        legc = (70, 30, 110) if costume == "skeleton" else (50, 140, 40)
        d.rounded_rectangle([lx - k(9), yb - k(10), lx + k(9), foot - lift], k(9), fill=legc + (255,))
        d.ellipse([lx - k(14), foot - lift - k(10), lx + k(18), foot - lift + k(4)], fill=legc + (255,))
    # cat tail (behind the glass)
    if costume == "cat":
        sway = math.sin(t * 3) * 0.3 + (0.6 if mood == "scared" else 0)
        pts = []
        for n in range(24):
            u = n / 23
            px = x1 - k(6) + k(70) * u + k(18) * math.sin(u * 3 + t * 2)
            py = yb - k(40) - k(160) * u * (1 + sway * 0.4) + k(30) * math.sin(u * 4)
            pts.append((px, py))
        d.line(pts, fill=INK + (255,), width=k(14 if mood == "scared" else 11), joint="curve")
        d.ellipse([pts[-1][0] - k(8), pts[-1][1] - k(8), pts[-1][0] + k(8), pts[-1][1] + k(8)], fill=INK + (255,))
    # glass body + liquid
    body = Image.new("L", (lw, lh), 0)
    ImageDraw.Draw(body).rounded_rectangle([x0, y0, x1, yb], tw // 2, fill=255)
    liq = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(liq)
    top = y0 + k(26)
    for yy in range(int(top), int(yb) + 1, 2):   # vertical gradient, lighter at the top
        ld.line([(x0, yy), (x1, yy)], fill=mix(liquid, dark, (yy - top) / (yb - top)) + (240,), width=2)
    ld.ellipse([x0, top - k(10), x1, top + k(10)], fill=mix(liquid, WHITE, 0.35) + (240,))
    if costume == "skeleton":
        for n in range(5):                    # glowing green bubbles
            bx = cx + k(26 * math.sin(n * 2.3))
            by = yb - k(30) - ((t * 40 + n * 47) % 200) * K
            r = k(7 + (n % 3) * 4)
            ld.ellipse([bx - r, by - r, bx + r, by + r], fill=(150, 255, 110, 220))
        sx = cx                               # ribs + spine
        ld.line([(sx, y0 + k(60)), (sx, yb - k(36))], fill=WHITE + (255,), width=k(9))
        for n in range(5):
            ry = y0 + k(78 + n * 30)
            ww = k(40 - n * 3)
            ld.arc([sx - ww, ry - k(14), sx + ww, ry + k(18)], 200, 340, fill=WHITE + (255,), width=k(8))
        ld.arc([sx - k(30), yb - k(56), sx + k(30), yb - k(14)], 180, 360, fill=WHITE + (255,), width=k(8))
    else:
        rnd = random.Random(7)
        for n in range(9):                    # purple dots
            bx = cx + rnd.uniform(-34, 34) * K
            by = y0 + k(110) + rnd.uniform(0, 120) * K + k(4) * math.sin(t * 3 + n)
            r = k(rnd.uniform(6, 12))
            ld.ellipse([bx - r, by - r, bx + r, by + r], fill=DOT + (255,))
            ld.ellipse([bx - r * 0.4, by - r * 0.5, bx, by - r * 0.1], fill=(190, 150, 255, 200))
    clipped = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    clipped.paste(liq, (0, 0), body)
    glass = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glass)
    gd.rounded_rectangle([x0, y0, x1, yb], tw // 2, fill=(220, 235, 255, 50))
    L.alpha_composite(glass)
    L.alpha_composite(clipped)
    d.rounded_rectangle([x0, y0, x1, yb], tw // 2, outline=(235, 245, 255, 230), width=k(5))
    d.rounded_rectangle([x0 + k(14), y0 + k(34), x0 + k(26), yb - k(70)], k(6), fill=(255, 255, 255, 110))  # shine
    d.ellipse([x0 - k(8), y0 - k(6), x1 + k(8), y0 + k(16)], outline=(235, 245, 255, 255), width=k(5))     # rim
    # faces
    pupil = k(6) if mood == "scared" else k(11)
    if costume == "skeleton":
        hx, hy, hr = cx, y0 - k(38), k(56)
        d.ellipse([hx - hr, hy - hr, hx + hr, hy + hr * 0.95], fill=(240, 238, 228, 255))
        d.rounded_rectangle([hx - k(30), hy + k(30), hx + k(30), hy + k(68)], k(10), fill=(240, 238, 228, 255))
        for n in range(4):
            tx = hx - k(18) + n * k(12)
            d.line([(tx, hy + k(46)), (tx, hy + k(64))], fill=(120, 110, 100, 255), width=k(3))
        d.ellipse([hx - k(10), hy + k(4), hx + k(10), hy + k(28)], fill=(120, 110, 100, 255))  # nose hole
        for sgn in (-1, 1):
            ex, ey = hx + sgn * k(24), hy - k(8)
            er = k(22) if mood == "scared" else k(19)
            if blink:
                d.line([(ex - er, ey), (ex + er, ey)], fill=INK + (255,), width=k(6))
            elif mood == "happy":
                d.arc([ex - er, ey - k(6), ex + er, ey + er + k(6)], 200, 340, fill=INK + (255,), width=k(8))
            else:
                d.ellipse([ex - er, ey - er, ex + er, ey + er], fill=INK + (255,))
                px = ex + k(look * 6)
                d.ellipse([px - pupil, ey - pupil, px + pupil, ey + pupil], fill=(130, 255, 90, 255))
        d.ellipse([hx - hr - k(10), y0 - k(12), hx + hr + k(10), y0 + k(10)], outline=(235, 245, 255, 180), width=k(4))
    else:
        # cat-ear headband on the rim
        d.rounded_rectangle([x0 - k(4), y0 - k(10), x1 + k(4), y0 + k(14)], k(8), fill=INK + (255,))
        for sgn in (-1, 1):
            ex = cx + sgn * k(32)
            perk = k(6) if mood == "scared" else 0
            d.polygon([(ex - k(26), y0 - k(4)), (ex + k(26), y0 - k(4)), (ex + sgn * k(6), y0 - k(64) - perk)], fill=INK + (255,))
            d.polygon([(ex - k(14), y0 - k(10)), (ex + k(14), y0 - k(10)), (ex + sgn * k(5), y0 - k(46) - perk)], fill=(255, 170, 200, 255))
        fy = y0 + k(66)
        for sgn in (-1, 1):
            ex = cx + sgn * k(22)
            if blink:
                d.line([(ex - k(10), fy), (ex + k(10), fy)], fill=INK + (255,), width=k(5))
            elif mood == "happy":
                d.arc([ex - k(11), fy - k(8), ex + k(11), fy + k(12)], 200, 340, fill=INK + (255,), width=k(5))
            else:
                er = k(14) if mood == "scared" else k(11)
                d.ellipse([ex - er, fy - er * 1.15, ex + er, fy + er * 1.15], fill=INK + (255,) if mood != "scared" else WHITE + (255,))
                if mood == "scared":
                    d.ellipse([ex - er, fy - er * 1.15, ex + er, fy + er * 1.15], outline=INK + (255,), width=k(3))
                    d.ellipse([ex - k(4) + k(look * 4), fy - k(4), ex + k(4) + k(look * 4), fy + k(4)], fill=INK + (255,))
                else:
                    d.ellipse([ex - k(4) + k(look * 3), fy - k(8), ex + k(2) + k(look * 3), fy - k(2)], fill=WHITE + (255,))
        d.polygon([(cx - k(6), fy + k(14)), (cx + k(6), fy + k(14)), (cx, fy + k(21))], fill=(255, 130, 170, 255))
        if mood == "scared":
            d.line([(cx - k(12), fy + k(32)), (cx - k(6), fy + k(28)), (cx, fy + k(32)), (cx + k(6), fy + k(28)), (cx + k(12), fy + k(32))],
                   fill=INK + (255,), width=k(3))
        else:
            d.arc([cx - k(12), fy + k(18), cx, fy + k(30)], 0, 180, fill=INK + (255,), width=k(3))
            d.arc([cx, fy + k(18), cx + k(12), fy + k(30)], 0, 180, fill=INK + (255,), width=k(3))
        for sgn in (-1, 1):
            for n in (-1, 0, 1):
                d.line([(cx + sgn * k(16), fy + k(22) + n * k(5)), (cx + sgn * k(66), fy + k(18) + n * k(10))], fill=INK + (255,), width=k(2))
    return L, cx, foot


def place(img, layer, fx, fy, x, y, scale=CS, flip=False, tilt=0.0, alpha=1.0, squash=1.0):
    """Paste a character layer so its foot point lands on frame point (x, y) (1x coordinates)."""
    if flip:
        layer = layer.transpose(Image.FLIP_LEFT_RIGHT)
        fx = layer.width - fx
    if tilt:
        layer = layer.rotate(tilt, resample=Image.BICUBIC, center=(fx, fy))
    if scale != 1.0 or squash != 1.0:
        sx, sy = scale / math.sqrt(squash), scale * squash
        layer = layer.resize((max(1, int(layer.width * sx)), max(1, int(layer.height * sy))), Image.BICUBIC)
        fx, fy = fx * sx, fy * sy
    if alpha < 1.0:
        a = layer.getchannel("A").point(lambda v: int(v * alpha))
        layer.putalpha(a)
    img.alpha_composite(layer, (int(k(x) - fx), int(k(y) - fy)))


# ---------------------------------------------------------------- the maze
FLOOR = 1650
MIRROR_W, MIRROR_GAP, MIRROR_TOP = 300, 46, 430


def maze_background(tint):
    """Wide strip of arched mirrors (world 3000 px), Halloween-dressed. Returns (bg, mirror masks list)."""
    WW = 3000
    bg = Image.new("RGBA", (k(WW), k(H)))
    d = ImageDraw.Draw(bg)
    for y in range(0, k(H), 2):
        d.line([(0, y), (k(WW), y)], fill=mix((16, 8, 30), (34, 14, 52), y / k(H)) + (255,), width=2)
    masks = []
    rnd = random.Random(11)
    x = 60
    while x < WW - MIRROR_W:
        x0, x1, yt, yb = x, x + MIRROR_W, MIRROR_TOP, FLOOR - 30
        glass = [k(x0 + 18), k(yt + 18), k(x1 - 18), k(yb - 12)]
        m = Image.new("L", bg.size, 0)
        md = ImageDraw.Draw(m)
        md.rounded_rectangle(glass, k(MIRROR_W / 2 - 18), fill=255)
        md.rectangle([glass[0], k(yt + 200), glass[2], glass[3]], fill=255)
        masks.append((x0, x1, m.crop((k(x0), 0, k(x1), k(H)))))
        # frame
        d.rounded_rectangle([k(x0), k(yt), k(x1), k(yb)], k(MIRROR_W / 2), fill=(70, 40, 96, 255))
        d.rectangle([k(x0), k(yt + 200), k(x1), k(yb)], fill=(70, 40, 96, 255))
        # glass: dark, tinted, with sheen
        gl = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(gl)
        gd.rectangle([glass[0], glass[1], glass[2], glass[3]], fill=mix((40, 46, 80), tint, 0.25) + (255,))
        sheen = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(sheen)
        for s in range(2):
            sx = x0 + 70 + s * 120
            sd.polygon([(k(sx), k(yt + 40)), (k(sx + 26 - s * 10), k(yt + 40)), (k(sx - 140), k(yb)), (k(sx - 166 + s * 10), k(yb))], fill=(255, 255, 255, 34 - s * 12))
        gl.alpha_composite(sheen)
        bg.paste(gl, (0, 0), m)
        # string lights along the arch
        for a in range(0, 181, 15):
            r = math.radians(a)
            lx = (x0 + x1) / 2 + (MIRROR_W / 2 - 4) * math.cos(r)
            ly = yt + MIRROR_W / 2 - (MIRROR_W / 2 - 4) * math.sin(r)
            c = [(255, 150, 40), (180, 90, 255), (120, 255, 90)][(a // 15) % 3]
            d.ellipse([k(lx - 9), k(ly - 9), k(lx + 9), k(ly + 9)], fill=c + (255,))
        # cobweb in a corner, pumpkin at the foot of some mirrors
        if rnd.random() < 0.6:
            cxw, cyw = (x0 + 20, yt + 170) if rnd.random() < 0.5 else (x1 - 20, yt + 170)
            sgn = 1 if cxw < (x0 + x1) / 2 else -1
            for a in range(0, 91, 22):
                r = math.radians(a)
                d.line([(k(cxw), k(cyw)), (k(cxw + sgn * 90 * math.cos(r)), k(cyw + 90 * math.sin(r)))], fill=(220, 210, 240, 150), width=k(2))
        if rnd.random() < 0.5:
            px = x1 - 30
            d.ellipse([k(px - 40), k(FLOOR - 66), k(px + 40), k(FLOOR - 4)], fill=(240, 120, 20, 255))
            d.rectangle([k(px - 5), k(FLOOR - 80), k(px + 5), k(FLOOR - 62)], fill=(70, 130, 40, 255))
            d.polygon([(k(px - 20), k(FLOOR - 46)), (k(px - 8), k(FLOOR - 46)), (k(px - 14), k(FLOOR - 56))], fill=(255, 230, 120, 255))
            d.polygon([(k(px + 8), k(FLOOR - 46)), (k(px + 20), k(FLOOR - 46)), (k(px + 14), k(FLOOR - 56))], fill=(255, 230, 120, 255))
            d.chord([k(px - 20), k(FLOOR - 44), k(px + 20), k(FLOOR - 20)], 0, 180, fill=(255, 230, 120, 255))
        x += MIRROR_W + MIRROR_GAP
    # floor with a soft sheen
    d.rectangle([0, k(FLOOR), k(WW), k(H)], fill=(26, 12, 40, 255))
    for i in range(12):
        d.line([(0, k(FLOOR + 30 + i * i * 3)), (k(WW), k(FLOOR + 30 + i * i * 3))], fill=(60, 30, 86, 255), width=k(2))
    # hanging bats
    for bx in range(250, WW, 560):
        by = 220 + (bx % 3) * 40
        pts = [(-50, 0), (-25, -16), (-8, -4), (0, -12), (8, -4), (25, -16), (50, 0), (25, -4), (12, 8), (0, 4), (-12, 8), (-25, -4)]
        d.polygon([(k(bx + px), k(by + py)) for px, py in pts], fill=(8, 4, 16, 255))
    return bg, masks


def reflect(img, cam, masks, layer, fx, fy, wx, stretch=None, alpha=0.55, flip=True):
    """Mirror-maze reflections: a copy of the character in each nearby mirror (clipped to the glass), fading with distance."""
    for x0, x1, m in masks:
        mc = (x0 + x1) / 2
        dist = abs(wx - mc)
        if dist > 560:
            continue
        sx = mc - cam + (wx - mc) * 0.35
        a = alpha * (1 - dist / 700)
        tmp = Image.new("RGBA", img.size, (0, 0, 0, 0))
        if stretch:
            sq, wob = stretch
            ly = layer.resize((int(layer.width / math.sqrt(sq)), int(layer.height * sq)), Image.BICUBIC)
            ly = ly.transform(ly.size, Image.AFFINE, (1, wob, -wob * ly.height / 2, 0, 1, 0), resample=Image.BICUBIC)
            place(tmp, ly, fx / math.sqrt(sq), fy * sq, sx, FLOOR - 50, 0.85 * CS, flip, alpha=min(1, a * 1.4))
        else:
            place(tmp, layer, fx, fy, sx, FLOOR - 50, 0.78 * CS, flip, alpha=a)
        full = Image.new("L", img.size, 0)
        full.paste(m, (k(x0 - cam), 0))
        tmp.putalpha(ImageChops.multiply(tmp.getchannel("A"), full))
        img.alpha_composite(tmp)


def speech(img, text, x, y, t_in, t, size=58, emoji=None):
    """ad105-style bubble: white, purple outline, dark purple text."""
    if t < t_in:
        return
    p = back_out(seg(t, t_in, t_in + 0.3))
    d = ImageDraw.Draw(img)
    f = font(size)
    tw = d.textlength(text, font=f) / K + (size * 1.1 if emoji else 0)
    bw, bh = (tw + 70) * p, size * 1.7 * p
    d.polygon([(k(x - 20), k(y + bh / 2 - 4)), (k(x + 20), k(y + bh / 2 - 4)), (k(x - 10), k(y + bh / 2 + 34 * p))], fill=(110, 60, 170))
    d.rounded_rectangle([k(x - bw / 2 - 5), k(y - bh / 2 - 5), k(x + bw / 2 + 5), k(y + bh / 2 + 5)], k(36), fill=(110, 60, 170))
    d.rounded_rectangle([k(x - bw / 2), k(y - bh / 2), k(x + bw / 2), k(y + bh / 2)], k(32), fill=WHITE)
    d.polygon([(k(x - 14), k(y + bh / 2 - 6)), (k(x + 14), k(y + bh / 2 - 6)), (k(x - 8), k(y + bh / 2 + 26 * p))], fill=WHITE)
    if p > 0.6:
        txt = Image.new("RGBA", img.size, (0, 0, 0, 0))
        td = ImageDraw.Draw(txt)
        tx = x - (size * 0.55 if emoji else 0)
        td.text((k(tx), k(y)), text, font=f, fill=BUBBLE_TXT, anchor="mm")
        img.alpha_composite(txt)
        if emoji:
            em = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
            ImageDraw.Draw(em).text((0, 0), emoji, font=ImageFont.truetype(EMOJI, 109), embedded_color=True)
            em = em.crop(em.getbbox()).resize((k(size * 0.95), k(size * 0.95)), Image.LANCZOS)
            ex = tx + d.textlength(text, font=f) / K / 2 + size * 0.15
            img.alpha_composite(em, (k(ex), k(y - size * 0.5)))


def caption(img, text, y, t_in, t_out, t, size=76):
    """Top caption: white bold with dark outline, pops in and fades out."""
    if not (t_in <= t < t_out):
        return
    p = back_out(seg(t, t_in, t_in + 0.3))
    fade = 1 - seg(t, t_out - 0.25, t_out)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = font(size * (0.7 + 0.3 * p))
    for i, line in enumerate(text.split("\n")):
        d.text((k(W / 2), k(y + i * size * 1.15)), line, font=f, fill=WHITE, anchor="mm", stroke_width=k(8), stroke_fill=INK)
    if fade < 1:
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * fade)))
    img.alpha_composite(layer)


def exclaim(img, x, y, t_in, t, dur=0.7):
    if not (t_in <= t < t_in + dur):
        return
    p = back_out(seg(t, t_in, t_in + 0.2))
    d = ImageDraw.Draw(img)
    d.text((k(x), k(y)), "!", font=font(110 * p + 1), fill=(255, 214, 60), anchor="mm", stroke_width=k(7), stroke_fill=INK)


def heart(d, x, y, s, c=(255, 90, 140)):
    r = s * 0.5
    d.ellipse([k(x - s), k(y - r), k(x), k(y + r)], fill=c)
    d.ellipse([k(x), k(y - r), k(x + s), k(y + r)], fill=c)
    d.polygon([(k(x - s * 0.97), k(y + r * 0.3)), (k(x + s * 0.97), k(y + r * 0.3)), (k(x), k(y + s * 1.25))], fill=c)


# ---------------------------------------------------------------- scenes
BG_A = BG_B = None


def maze_frame(t):
    """0-11.2 s: S1 skeleton alone, S2 cat alone, S3 they meet and hug."""
    blink = int(t * 10) % 37 == 0
    if t < 4.6:                                  # S1: skeleton tiptoes left -> right
        bg, masks = BG_A
        wx = 300 + 190 * t + (-120 * ease(seg(t, 2.6, 2.9)) if t > 2.6 else 0)   # jumps back at the scare
        cam = clamp(wx - 420, 0, 2000)
        scared = 2.55 <= t
        mood = "scared" if scared else "calm"
        walk = t * 1.6 if not (2.6 <= t < 3.2) else 0
        jump = -90 * math.sin(math.pi * seg(t, 2.6, 2.95)) if t < 3.0 else 0
        shake = 4 * math.sin(t * 70) if scared else 0
        img = bg.crop((k(cam), 0, k(cam + W), k(H)))
        lay, fx, fy = tube("skeleton", t, mood, walk, look=1 if not scared else -1, blink=blink and not scared)
        funhouse = (sq := 1 + 0.35 * math.sin(t * 6)), 0.25 * math.sin(t * 4)
        # the mirror right of the start is a funhouse one: wobbly stretched reflection gives the scare
        for x0, x1, m in masks:
            fun = x0 > 700 and x0 < 1100
            reflect(img, cam, [(x0, x1, m)], lay, fx, fy, wx, stretch=funhouse if fun else None, alpha=0.7)
        place(img, lay, fx, fy, wx - cam + shake, FLOOR + 6 + jump)
        exclaim(img, wx - cam + 90, FLOOR - 740, 2.6, t)
        caption(img, "Lost in the haunted\nmirror maze...", 230, 0.2, 4.5, t)
        return img
    if t < 8.2:                                  # S2: cat creeps right -> left in another corridor
        tt = t - 4.6
        bg, masks = BG_B
        wx = 2500 - 190 * tt + (110 * ease(seg(tt, 1.9, 2.2)) if tt > 1.9 else 0)
        cam = clamp(wx - 660, 0, 2000)
        scared = tt >= 1.85
        img = bg.crop((k(cam), 0, k(cam + W), k(H)))
        lay, fx, fy = tube("cat", t, "scared" if scared else "calm", 0 if 1.9 <= tt < 2.5 else tt * 1.6,
                           look=-1 if not scared else 1, blink=blink and not scared)
        for x0, x1, m in masks:
            reflect(img, cam, [(x0, x1, m)], lay, fx, fy, wx, alpha=0.6, flip=False)
        # the scare: a skeleton reflection slides across a mirror (it's the purple friend, nearby)
        if 1.5 < tt < 2.6:
            sk, sfx, sfy = tube("skeleton", t, "scared", tt * 1.6)
            gx = wx - 380 + 260 * seg(tt, 1.5, 2.6)
            reflect(img, cam, masks, sk, sfx, sfy, gx, alpha=0.5, flip=True)
        jump = -90 * math.sin(math.pi * seg(tt, 1.9, 2.25)) if tt < 2.3 else 0
        shake = 4 * math.sin(t * 70) if scared else 0
        place(img, lay, fx, fy, wx - cam + shake, FLOOR + 6 + jump)
        exclaim(img, wx - cam - 90, FLOOR - 740, 6.5, t)
        caption(img, "...all alone", 230, 4.75, 8.1, t)
        return img
    # S3: meet in the middle and hug (8.2-11.2), camera centred
    tt = t - 8.2
    bg, masks = BG_A
    cam = 1100
    img = bg.crop((k(cam), 0, k(cam + W), k(H)))
    meet = 540
    gap = 80 * CS
    # approach (scared, trembling), notice + startle at 0.9, recognise at 1.4, run, hug from 1.9
    pa = ease(seg(tt, 0, 0.9)) * 0.55 + ease(seg(tt, 1.4, 1.9)) * 0.45
    left_x = 150 + (meet - gap - 150) * pa
    right_x = 930 - (930 - meet - gap) * pa
    mood = "scared" if tt < 1.4 else "happy"
    hugging = tt >= 1.9
    shake = 4 * math.sin(t * 70) if 0.9 <= tt < 1.4 else 0
    jump = -70 * math.sin(math.pi * seg(tt, 0.9, 1.2)) if tt < 1.25 else 0
    walk = tt * 1.8 if (tt < 0.9 or 1.4 <= tt < 1.9) else 0
    tilt = 9 * ease(seg(tt, 1.9, 2.1)) if hugging else 0
    sq = 1 - 0.05 * math.sin(math.pi * seg(tt, 1.9, 2.15))
    a, afx, afy = tube("skeleton", t, mood, walk, look=1, blink=blink and hugging)
    b, bfx, bfy = tube("cat", t, mood, walk, look=-1, blink=blink and hugging)
    for wx, lay, fx, fy, fl in ((cam + left_x, a, afx, afy, True), (cam + right_x, b, bfx, bfy, True)):
        reflect(img, cam, masks, lay, fx, fy, wx, alpha=0.5, flip=fl)
    place(img, a, afx, afy, left_x + shake, FLOOR + 6 + jump, tilt=-tilt, squash=sq)
    place(img, b, bfx, bfy, right_x - shake, FLOOR + 6 + jump, tilt=tilt, squash=sq)
    exclaim(img, left_x + 10, FLOOR - 740, 9.1, t, 0.45)
    exclaim(img, right_x - 10, FLOOR - 740, 9.1, t, 0.45)
    if hugging:
        d = ImageDraw.Draw(img)
        for n in range(5):
            ph = (tt - 1.9) * 0.9 + n * 0.21
            if ph < 1.2:
                hx = meet + 160 * math.sin(n * 2.4 + ph * 3)
                heart(d, hx, FLOOR - 720 - ph * 380, 26 + 8 * (n % 2))
        speech(img, "Found you!", meet, FLOOR - 920, 10.15, t, emoji="\U0001f383")
    return img


def fizz_frame(t, zoom_src):
    """11.2-13.0 s: push in on the cat's liquid until the frame is only fizzy green liquid."""
    p = ease(seg(t, 11.2, 11.9))
    z = 1 + 7 * p * p
    fx, fy = 540 + 80 * CS + 6, FLOOR - 175 * CS   # the cat's liquid, in frame coords
    cw, ch = W / z, H / z
    x0 = clamp(fx - cw / 2, 0, W - cw)
    y0 = clamp(fy - ch / 2, 0, H - ch)
    zoomed = zoom_src.crop((k(x0), k(y0), k(x0 + cw), k(y0 + ch))).resize((k(W), k(H)), Image.BICUBIC)
    macro = Image.new("RGBA", (k(W), k(H)))
    d = ImageDraw.Draw(macro)
    for y in range(0, k(H), 4):
        d.line([(0, y), (k(W), y)], fill=mix((150, 250, 90), (40, 150, 24), y / k(H)) + (255,), width=4)
    rnd = random.Random(5)
    for n in range(70):                            # fizz: bubbles rising at different speeds/sizes
        r = rnd.uniform(6, 40)
        sp = rnd.uniform(250, 700) * (1.2 - r / 50)
        x = rnd.uniform(0, W) + 14 * math.sin(t * 3 + n)
        y = (rnd.uniform(0, H) - (t - 11.2) * sp) % (H + 100) - 50
        d.ellipse([k(x - r), k(y - r), k(x + r), k(y + r)], fill=(190, 255, 150, 120))
        d.ellipse([k(x - r * 0.55), k(y - r * 0.6), k(x - r * 0.05), k(y - r * 0.1)], fill=(235, 255, 225, 110))
    for n in range(7):                             # big purple dots drifting by
        x = 140 + n * 140 + 30 * math.sin(t + n)
        y = (300 + n * 260 - (t - 11.2) * 90) % H
        r = 70 + 20 * (n % 3)
        d.ellipse([k(x - r), k(y - r), k(x + r), k(y + r)], fill=DOT + (235,))
        d.ellipse([k(x - r * 0.5), k(y - r * 0.6), k(x - r * 0.05), k(y - r * 0.2)], fill=(190, 150, 255, 200))
    macro = macro.filter(ImageFilter.GaussianBlur(k(1.2)))
    m = seg(t, 11.65, 11.95)
    return Image.blend(zoomed.convert("RGBA"), macro, m) if m < 1 else macro


BUBBLE_COLORS = [(232, 150, 52), (96, 196, 72), (150, 92, 196), (176, 64, 84), (226, 226, 236)]


def game_bubble(d, x, y, r, c, a):
    """One glassy bubble like the game's level transition: tinted disc, darker rim, big glint, light lower crescent."""
    rim = mix(c, (20, 10, 30), 0.35)
    d.ellipse([k(x - r), k(y - r), k(x + r), k(y + r)], fill=c + (int(120 * a),), outline=rim + (int(170 * a),), width=k(max(2, r * 0.07)))
    g = r * 0.3
    gx, gy = x - r * 0.32, y - r * 0.32
    d.ellipse([k(gx - g), k(gy - g), k(gx + g), k(gy + g)], fill=(255, 255, 255, int(235 * a)))
    d.arc([k(x - r * 0.72), k(y - r * 0.72), k(x + r * 0.72), k(y + r * 0.72)], 30, 150, fill=(255, 255, 255, int(110 * a)), width=k(max(2, r * 0.1)))


def bubble_reveal(t, base, gameplay):
    """13.0-14.2 s: the game's bubble transition (no level number). Bubbles flood up from the bottom over the
    liquid, the gameplay fades in underneath, then the bubbles clear out the top."""
    gp = gameplay.convert("RGBA").resize((k(W), k(H)), Image.LANCZOS)
    out = Image.blend(base, gp, ease(seg(t, 13.35, 13.8)))
    layer = Image.new("RGBA", out.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rnd = random.Random(21)
    for n in range(260):
        start = 13.0 + rnd.uniform(0, 0.55)
        r = rnd.choice([rnd.uniform(14, 34), rnd.uniform(30, 60), rnd.uniform(55, 110)])
        speed = rnd.uniform(2600, 3600) * (0.8 + r / 300)
        x = rnd.uniform(-40, W + 40)
        y = H + r - (t - start) * speed
        if t < start or y < -r:
            continue
        x += 18 * math.sin((t - start) * 6 + n)
        game_bubble(d, x, y, r, rnd.choice(BUBBLE_COLORS), 1.0)
    out.alpha_composite(layer)
    return out


def frame(i, gp_frames):
    global BG_A, BG_B
    if BG_A is None:
        BG_A = maze_background((150, 80, 255))
        BG_B = maze_background((90, 255, 120))
    t = i / FPS
    if t < 11.2:
        img = maze_frame(t)
    elif t < 13.0:
        img = fizz_frame(t, maze_frame(11.2))
    else:
        base = fizz_frame(t, maze_frame(11.2))
        g = min(int((t - 13.0) * FPS), len(gp_frames) - 1)
        img = bubble_reveal(t, base, Image.open(gp_frames[g]))
    return img.convert("RGB").resize((W, H), Image.LANCZOS)


_GP = []


def _init(gp):
    _GP.extend(gp)


def _render(i):
    return frame(i, _GP).tobytes()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src = args[0]
    music = args[1] if len(args) > 1 else None
    tmp = tempfile.mkdtemp()
    # gameplay frames under the bubbles (13-14.2 s of our timeline = ad105 6.0-7.2 s)
    subprocess.run(["ffmpeg", "-v", "error", "-ss", str(GP_IN), "-i", src, "-t", "1.2", "-vf", f"fps={FPS}",
                    os.path.join(tmp, "gp%03d.png")], check=True)
    gp = sorted(os.path.join(tmp, f) for f in os.listdir(tmp) if f.startswith("gp"))
    if "--stills" in sys.argv:
        _init(gp)
        for s in (1.0, 2.8, 5.5, 6.7, 9.2, 10.6, 11.5, 12.4, 13.4):
            frame(int(s * FPS), _GP).save(os.path.join(os.getcwd(), f"still-{s:04.1f}s.png"))
        if "--stills-only" in sys.argv:
            return
    anim = os.path.join(tmp, "anim.mp4")
    n = int(ANIM_END * FPS)
    ff = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                           "-i", "-", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", anim], stdin=subprocess.PIPE)
    with Pool(initializer=_init, initargs=(gp,)) as pool:
        for b in pool.imap(_render, range(n), chunksize=3):
            ff.stdin.write(b)
    ff.stdin.close()
    ff.wait()
    # stitch: our animation + rest of ad105 gameplay + ad105 end card (held a little)
    gp_rest = GP_IN + 1.2
    fc = (f"[0:v]setpts=PTS-STARTPTS[a];"
          f"[1:v]trim={gp_rest}:{GP_OUT},setpts=PTS-STARTPTS[g];"
          f"[1:v]trim={CARD_IN}:{CARD_OUT},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={CARD_HOLD}[c];"
          f"[a][g][c]concat=n=3:v=1:a=0[v]")
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", anim, "-i", src]
    total = ANIM_END + (GP_OUT - gp_rest) + (CARD_OUT - CARD_IN) + CARD_HOLD
    if music:
        cmd += ["-i", music]
        fc += f";[2:a]atrim=0:{total},afade=t=out:st={total - 1.2}:d=1.2[m]"
    cmd += ["-filter_complex", fc, "-map", "[v]"]
    if music:
        cmd += ["-map", "[m]", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-crf", "19", "-preset", "slow", "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart", OUT]
    subprocess.run(cmd, check=True)
    print(f"wrote {OUT} ({total:.1f} s)")


if __name__ == "__main__":
    main()
