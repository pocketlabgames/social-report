"""Beaker Lab Halloween reel: "Trick or Treat in the Lab" (15 s, 1080x1920, 30 fps).

Draws every frame with Pillow (no game assets needed) and encodes with ffmpeg:
    python3 render_reel.py            # -> beaker-trick-or-treat.mp4 (silent; add a trending sound in the app)
    python3 render_reel.py --stills   # also saves a few keyframes as PNG for the storyboard
Scene timings and on-screen text match SCRIPT.md.
"""
import math
import os
import random
import subprocess
import sys
from multiprocessing import Pool

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS, DUR = 1080, 1920, 30, 15.0
K = 2                                   # draw at 2x, downscale = smooth edges
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "beaker-trick-or-treat.mp4")
FONT = "/usr/share/fonts/opentype/inter/InterDisplay-Black.otf"
FONT2 = "/usr/share/fonts/opentype/inter/InterDisplay-Bold.otf"

NIGHT_TOP, NIGHT_BOT = (24, 14, 52), (62, 28, 92)
ORANGE, PURPLE, GHOST = (255, 138, 28), (164, 84, 255), (122, 255, 170)
PINK, CAULDRON_GREEN, MUD = (255, 92, 178), (110, 230, 60), (150, 110, 60)
WHITE, INK = (255, 255, 255), (20, 12, 30)


def k(v):
    return int(round(v * K))


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def seg(t, a, b):
    """0..1 progress of t through [a, b]."""
    return clamp((t - a) / (b - a))


def ease(x):
    return x * x * (3 - 2 * x)


def back_out(x):
    c = 1.9
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def mix(c1, c2, x):
    return tuple(int(a + (b - a) * x) for a, b in zip(c1, c2))


def font(size, f=FONT):
    return ImageFont.truetype(f, k(size))


# ---------------------------------------------------------------- background
def make_background():
    bg = Image.new("RGB", (k(W), k(H)))
    d = ImageDraw.Draw(bg)
    for y in range(k(H)):
        d.line([(0, y), (k(W), y)], fill=mix(NIGHT_TOP, NIGHT_BOT, y / k(H)))
    rnd = random.Random(3)
    # window with moon + stars
    wx0, wy0, wx1, wy1 = 140, 260, 940, 900
    d.rounded_rectangle([k(wx0), k(wy0), k(wx1), k(wy1)], k(40), fill=(14, 10, 40))
    for _ in range(60):
        x, y = rnd.uniform(wx0 + 20, wx1 - 20), rnd.uniform(wy0 + 20, wy1 - 20)
        r = rnd.uniform(1.5, 4)
        d.ellipse([k(x - r), k(y - r), k(x + r), k(y + r)], fill=(255, 250, 220))
    glow = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([k(560), k(330), k(860), k(630)], fill=(255, 240, 180, 110))
    glow = glow.filter(ImageFilter.GaussianBlur(k(40)))
    bg.paste(glow, (0, 0), glow)
    d.ellipse([k(610), k(380), k(810), k(580)], fill=(255, 246, 205))
    d.ellipse([k(660), k(420), k(700), k(460)], fill=(236, 226, 185))
    d.ellipse([k(730), k(490), k(760), k(520)], fill=(236, 226, 185))
    # bat silhouettes
    for bx, by, s in [(330, 450, 1.0), (440, 380, 0.7), (250, 560, 0.6)]:
        pts = [(-60, 0), (-30, -20), (-10, -5), (0, -15), (10, -5), (30, -20), (60, 0), (30, -5), (15, 10), (0, 5), (-15, 10), (-30, -5)]
        d.polygon([(k(bx + px * s), k(by + py * s)) for px, py in pts], fill=(10, 6, 24))
    # window frame
    d.rounded_rectangle([k(wx0), k(wy0), k(wx1), k(wy1)], k(40), outline=(92, 60, 130), width=k(18))
    d.line([(k((wx0 + wx1) / 2), k(wy0)), (k((wx0 + wx1) / 2), k(wy1))], fill=(92, 60, 130), width=k(14))
    d.line([(k(wx0), k((wy0 + wy1) / 2)), (k(wx1), k((wy0 + wy1) / 2))], fill=(92, 60, 130), width=k(14))
    # shelf with little bottles
    d.rectangle([k(60), k(1030), k(1020), k(1050)], fill=(70, 40, 96))
    for i, c in enumerate([(255, 92, 178), (90, 200, 255), (255, 214, 60), (120, 240, 140), (255, 120, 80), (180, 120, 255)]):
        x = 110 + i * 155
        hgt = 70 + (i % 3) * 25
        d.rounded_rectangle([k(x), k(1030 - hgt), k(x + 60), k(1030)], k(14), fill=(60, 44, 90))
        d.rounded_rectangle([k(x + 6), k(1030 - hgt * 0.55), k(x + 54), k(1024)], k(10), fill=c)
        d.rectangle([k(x + 20), k(1030 - hgt - 18), k(x + 40), k(1030 - hgt)], fill=(60, 44, 90))
    # cobweb top-left
    for a in range(0, 91, 18):
        r = math.radians(a)
        d.line([(0, 0), (k(260 * math.cos(r)), k(260 * math.sin(r)))], fill=(200, 190, 230), width=k(2))
    for rr in (70, 140, 210):
        pts = [(k(rr * math.cos(math.radians(a))), k(rr * math.sin(math.radians(a)))) for a in range(0, 91, 18)]
        d.line(pts, fill=(200, 190, 230), width=k(2))
    # floor (lab bench)
    d.rectangle([0, k(1560), k(W), k(H)], fill=(44, 22, 64))
    d.rectangle([0, k(1560), k(W), k(1576)], fill=(96, 58, 128))
    return bg


# ---------------------------------------------------------------- characters
def beaker(img, cx, base, liquid, level, costume="", look=0.0, blink=False, squash=1.0,
           tilt=0.0, mood="happy", cork=0.0, wobble=0.0, t=0.0, scale=1.0):
    """Draw one beaker character standing on y=base. level 0..1.15 (>1 overflows)."""
    bw, bh = 190 * scale / math.sqrt(squash), 250 * scale * squash
    pad = 160 * scale
    lw, lh = int(k(bw + pad * 2)), int(k(bh + pad * 2))
    layer = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0, y0 = k(pad), k(pad)
    x1, y1 = x0 + k(bw), y0 + k(bh)
    rad = k(34 * scale)
    # glass body
    d.rounded_rectangle([x0, y0, x1, y1], rad, fill=(210, 230, 255, 70))
    # liquid (wave top), clipped to body
    liq = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(liq)
    top = y1 - (y1 - y0 - k(20)) * clamp(level, 0, 1.0) - k(4)
    amp = k(8 + 10 * wobble)
    pts = [(x, top + amp * math.sin(x / k(28) + t * 7)) for x in range(x0 - 4, x1 + 6, 6)]
    ld.polygon(pts + [(x1 + 6, y1 + 4), (x0 - 4, y1 + 4)], fill=liquid + (235,))
    ld.ellipse([x0 + k(26), top + k(30), x0 + k(46), top + k(50)], fill=(255, 255, 255, 70))   # bubble
    mask = Image.new("L", (lw, lh), 0)
    ImageDraw.Draw(mask).rounded_rectangle([x0 + k(6), y0 + k(6), x1 - k(6), y1 - k(6)], rad - k(6), fill=255)
    if level <= 1.0:
        clipped = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
        clipped.paste(liq, (0, 0), mask)
        layer.alpha_composite(clipped)
    else:
        layer.alpha_composite(liq)
        # overflow drips down the sides
        o = clamp((level - 1.0) / 0.15)
        for sx in (x0 - k(4), x1 - k(14)):
            d.rounded_rectangle([sx, y0 - k(10), sx + k(18), y0 + k(bh * 0.7 * o)], k(9), fill=liquid + (235,))
    # glass outline + lip + shine + measuring ticks
    d.rounded_rectangle([x0, y0, x1, y1], rad, outline=(235, 245, 255, 255), width=k(7))
    d.rounded_rectangle([x0 - k(16), y0 - k(10), x1 + k(16), y0 + k(10)], k(10), fill=(235, 245, 255, 255))
    d.rounded_rectangle([x1 - k(34), y0 + k(30), x1 - k(22), y0 + k(bh * 0.55)], k(6), fill=(255, 255, 255, 120))
    for i in range(3):
        ty = y0 + k(bh * (0.35 + i * 0.17))
        d.line([(x0 + k(10), ty), (x0 + k(34), ty)], fill=(235, 245, 255, 200), width=k(4))
    # face
    fx, fy = (x0 + x1) / 2, y0 + k(bh * 0.42)
    er = k(24 * scale)
    gap = k(44 * scale)
    if costume == "ghost":   # sheet over the top half
        sheet = [(x0 - k(26), y0 - k(14))]
        cxm, sw = (x0 + x1) / 2, (x1 - x0) / 2 + k(26)
        sheet = [(cxm + sw * math.cos(math.radians(a)), y0 + k(10) - k(120 * scale) * math.sin(math.radians(a))) for a in range(0, 181, 10)]
        hem = y0 + k(bh * 0.62)
        n = 5
        for i in range(n + 1):
            x = (x0 - k(26)) + (x1 - x0 + k(52)) * i / n
            sheet.append((x, hem + (k(22) if i % 2 else 0) + k(6) * math.sin(t * 6 + i)))
        d.polygon(sheet, fill=(248, 248, 255, 250))
        for sgn in (-1, 1):
            ex = fx + sgn * gap
            d.ellipse([ex - k(16), fy - k(26) - (k(2) if blink else 0), ex + k(16), fy + k(20)], fill=INK if not blink else (248, 248, 255, 0))
            if blink:
                d.line([(ex - k(16), fy), (ex + k(16), fy)], fill=INK, width=k(6))
        d.ellipse([fx - k(14), fy + k(36), fx + k(14), fy + k(66)], fill=INK)
    elif costume == "pumpkin":   # jack-o-lantern face on the glass + stem hat
        d.rounded_rectangle([fx - k(10), y0 - k(54), fx + k(10), y0 - k(10)], k(6), fill=(70, 150, 50, 255))
        d.ellipse([fx + k(4), y0 - k(58), fx + k(54), y0 - k(30)], fill=(90, 190, 70, 255))
        for sgn in (-1, 1):
            ex = fx + sgn * gap + k(look * 10)
            if blink:
                d.line([(ex - er, fy), (ex + er, fy)], fill=INK, width=k(7))
            elif mood == "shock":
                d.ellipse([ex - er - k(6), fy - er - k(6), ex + er + k(6), fy + er + k(6)], fill=WHITE)
                d.ellipse([ex - k(9), fy - k(9), ex + k(9), fy + k(9)], fill=INK)
            elif mood == "sneaky":
                d.polygon([(ex - er, fy - k(4)), (ex + er, fy - k(4)), (ex + k(look * 12), fy + er)], fill=INK)
                d.line([(ex - er, fy - k(14)), (ex + er, fy - k(4))] if sgn < 0 else [(ex - er, fy - k(4)), (ex + er, fy - k(14))], fill=INK, width=k(6))
            else:
                d.polygon([(ex - er, fy + er * 0.7), (ex + er, fy + er * 0.7), (ex, fy - er)], fill=INK)
        my = fy + k(56)
        if mood == "shock":
            d.ellipse([fx - k(20), my - k(10), fx + k(20), my + k(34)], fill=INK)
        else:
            zig = [(fx - k(54), my), (fx - k(36), my + k(18)), (fx - k(18), my + k(6)), (fx, my + k(24)),
                   (fx + k(18), my + k(6)), (fx + k(36), my + k(18)), (fx + k(54), my)]
            d.polygon(zig + [(fx + k(40), my + k(34)), (fx - k(40), my + k(34))], fill=INK)
    else:   # plain eyes (witch, grown-up flask etc.)
        for sgn in (-1, 1):
            ex = fx + sgn * gap
            if blink:
                d.line([(ex - er, fy), (ex + er, fy)], fill=INK, width=k(7))
            else:
                d.ellipse([ex - er, fy - er, ex + er, fy + er], fill=WHITE)
                px = ex + k(look * 10)
                d.ellipse([px - k(11), fy - k(9), px + k(11), fy + k(13)], fill=INK)
        my = fy + k(50)
        if mood == "laugh":
            d.chord([fx - k(36), my - k(24), fx + k(36), my + k(36)], 0, 180, fill=INK)
        else:
            d.arc([fx - k(30), my - k(22), fx + k(30), my + k(18)], 20, 160, fill=INK, width=k(7))
        for sgn in (-1, 1):   # blush
            d.ellipse([fx + sgn * k(78) - k(16), my - k(16), fx + sgn * k(78) + k(16), my], fill=(255, 120, 160, 120))
    if costume == "witch":
        hb = y0 - k(4)
        d.ellipse([x0 - k(44), hb - k(26), x1 + k(44), hb + k(16)], fill=(36, 20, 54, 255))
        tip = ((x0 + x1) / 2 + k(70), hb - k(190))
        d.polygon([(x0 + k(18), hb - k(10)), (x1 - k(18), hb - k(10)), (tip[0] - k(20), tip[1] + k(40)), tip], fill=(36, 20, 54, 255))
        d.rectangle([x0 + k(26), hb - k(46), x1 - k(26), hb - k(16)], fill=(255, 138, 28, 255))
    if cork > 0:   # cork drops in from above
        cy = y0 - k(18) - k(400) * (1 - cork)
        d.rounded_rectangle([x0 + k(14), cy - k(50), x1 - k(14), cy + k(16)], k(14), fill=(196, 140, 84, 255))
        for i in range(4):
            dx = x0 + k(40) + i * (x1 - x0 - k(80)) / 3
            d.ellipse([dx - k(5), cy - k(26), dx + k(5), cy - k(16)], fill=(150, 100, 56, 255))
    if tilt:
        layer = layer.rotate(tilt, resample=Image.BICUBIC, center=(lw / 2, y1))
    img.alpha_composite(layer, (int(k(cx) - lw / 2), int(k(base) - y1)))


def flask(img, cx, base, tilt, level, look=0.0, blink=False, t=0.0):
    """Big round-bottom 'neighbour' flask that hands out treats."""
    lw, lh = k(700), k(900)
    layer = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    bx, by, r = lw / 2, k(560), k(230)
    nx0, nx1, ny0 = bx - k(60), bx + k(60), k(150)
    liq = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(liq)
    top = by + r - 2 * r * level
    pts = [(x, top + k(10) * math.sin(x / k(30) + t * 6)) for x in range(0, lw, 8)]
    ld.polygon(pts + [(lw, lh), (0, lh)], fill=PINK + (235,))
    mask = Image.new("L", (lw, lh), 0)
    ImageDraw.Draw(mask).ellipse([bx - r + k(8), by - r + k(8), bx + r - k(8), by + r - k(8)], fill=255)
    d.ellipse([bx - r, by - r, bx + r, by + r], fill=(210, 230, 255, 70))
    d.rectangle([nx0, ny0, nx1, by - r + k(30)], fill=(210, 230, 255, 70))
    clipped = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    clipped.paste(liq, (0, 0), mask)
    layer.alpha_composite(clipped)
    d.ellipse([bx - r, by - r, bx + r, by + r], outline=(235, 245, 255, 255), width=k(8))
    d.rectangle([nx0, ny0, nx1, by - r + k(40)], fill=None, outline=(235, 245, 255, 255), width=k(8))
    d.rectangle([nx0 + k(8), by - r - k(4), nx1 - k(8), by - r + k(30)], fill=(210, 230, 255, 70))
    d.rounded_rectangle([nx0 - k(20), ny0 - k(16), nx1 + k(20), ny0 + k(8)], k(10), fill=(235, 245, 255, 255))
    d.ellipse([bx + k(110), by - k(150), bx + k(150), by - k(60)], fill=(255, 255, 255, 130))
    fy = by - k(30)
    for sgn in (-1, 1):
        ex = bx + sgn * k(70)
        if blink:
            d.line([(ex - k(30), fy), (ex + k(30), fy)], fill=INK, width=k(8))
        else:
            d.ellipse([ex - k(30), fy - k(30), ex + k(30), fy + k(30)], fill=WHITE)
            d.ellipse([ex - k(13) + k(look * 12), fy - k(10), ex + k(13) + k(look * 12), fy + k(16)], fill=INK)
        d.ellipse([ex - k(42), fy - k(42), ex + k(42), fy + k(42)], outline=(255, 214, 90, 255), width=k(7))   # glasses
    d.line([(bx - k(28), fy), (bx + k(28), fy)], fill=(255, 214, 90, 255), width=k(7))
    d.arc([bx - k(50), fy + k(40), bx + k(50), fy + k(100)], 15, 165, fill=INK, width=k(8))
    layer = layer.rotate(tilt, resample=Image.BICUBIC, center=(bx, by + r))
    img.alpha_composite(layer, (int(k(cx) - bx), int(k(base) - by - r)))
    # spout position (neck top) after rotation, in frame coords
    a = math.radians(-tilt)
    ox, oy = 0, -(r + (by - ny0))
    sx = cx + (ox * math.cos(a) - oy * math.sin(a)) / K
    sy = base + (ox * math.sin(a) + oy * math.cos(a)) / K
    return sx, sy


def cauldron(img, cx, base, t, level=1.0):
    d = ImageDraw.Draw(img)
    rw, rh = 260, 210
    d.ellipse([k(cx - rw), k(base - rh * 2), k(cx + rw), k(base)], fill=(28, 24, 34))
    d.rectangle([k(cx - rw - 10), k(base - rh * 2 - 10), k(cx + rw + 10), k(base - rh * 1.6)], fill=(28, 24, 34))
    d.ellipse([k(cx - rw - 30), k(base - rh * 2 - 50), k(cx + rw + 30), k(base - rh * 2 + 30)], fill=(48, 42, 58))
    d.ellipse([k(cx - rw + 4), k(base - rh * 2 - 30), k(cx + rw - 4), k(base - rh * 2 + 14)], fill=CAULDRON_GREEN)
    rnd = random.Random(int(t * 4))
    for i in range(7):   # bubbles
        ph = (t * 1.6 + i * 0.37) % 1
        bx = cx - rw + 60 + (i * 71) % (rw * 2 - 120)
        by = base - rh * 2 - 8 - ph * 90
        br = 10 + 12 * math.sin(ph * math.pi)
        d.ellipse([k(bx - br), k(by - br), k(bx + br), k(by + br)], fill=(170, 255, 120))
    for sx in (-1, 1):
        d.ellipse([k(cx + sx * 200 - 30), k(base - 30), k(cx + sx * 200 + 30), k(base + 10)], fill=(28, 24, 34))
    # sign
    d.rounded_rectangle([k(cx - 150), k(base - 270), k(cx + 150), k(base - 150)], k(16), fill=(255, 214, 90))
    f = font(54)
    d.text((k(cx), k(base - 210)), "TAKE 1", font=f, fill=INK, anchor="mm")
    # candy pile peeking over the rim
    for i, c in enumerate([PINK, ORANGE, PURPLE, (90, 200, 255), (255, 214, 60)]):
        x = cx - 180 + i * 90
        candy(d, x, base - rh * 2 - 26, c, 0.8, i * 20)


def candy(d, x, y, c, s=1.0, rot=0):
    r = 26 * s
    a = math.radians(rot)
    for sgn in (-1, 1):
        ex, ey = x + sgn * math.cos(a) * r * 1.6, y + sgn * math.sin(a) * r * 1.6
        tri = [(ex, ey), (ex + sgn * math.cos(a + 0.6) * r, ey + sgn * math.sin(a + 0.6) * r),
               (ex + sgn * math.cos(a - 0.6) * r, ey + sgn * math.sin(a - 0.6) * r)]
        d.polygon([(k(px), k(py)) for px, py in tri], fill=c)
    d.ellipse([k(x - r), k(y - r), k(x + r), k(y + r)], fill=c)
    d.arc([k(x - r * 0.6), k(y - r * 0.6), k(x + r * 0.6), k(y + r * 0.6)], 200, 320, fill=WHITE, width=k(4))


def star(d, x, y, r, c):
    pts = []
    for i in range(8):
        rr = r if i % 2 == 0 else r * 0.32
        a = math.radians(i * 45 - 90)
        pts.append((k(x + rr * math.cos(a)), k(y + rr * math.sin(a))))
    d.polygon(pts, fill=c)


def caption(img, text, y, t_in, t, size=86, color=WHITE, stroke=INK, sub=None, box=None):
    """Bold caption that pops in at t_in (scale overshoot)."""
    if t < t_in:
        return
    p = back_out(seg(t, t_in, t_in + 0.35))
    f = font(size * (0.6 + 0.4 * p))
    d = ImageDraw.Draw(img)
    lines = text.split("\n")
    lh = size * 1.12
    if box:
        bw = max(d.textlength(l, font=font(size)) for l in lines) / K + 70
        bh = lh * len(lines) + 40
        d.rounded_rectangle([k(W / 2 - bw / 2 * p), k(y - bh / 2 * p), k(W / 2 + bw / 2 * p), k(y + bh / 2 * p)], k(34), fill=box)
    for i, l in enumerate(lines):
        yy = y + (i - (len(lines) - 1) / 2) * lh * (0.6 + 0.4 * p)
        d.text((k(W / 2), k(yy)), l, font=f, fill=color, anchor="mm", stroke_width=k(9) if stroke else 0, stroke_fill=stroke)


def speech(img, text, x, y, t_in, t, size=64, tail=(0, 1)):
    if t < t_in:
        return
    p = back_out(seg(t, t_in, t_in + 0.3))
    d = ImageDraw.Draw(img)
    f = font(size * (0.5 + 0.5 * p))
    tw = d.textlength(text, font=f) / K
    bw, bh = tw + 60, size * 1.5 * (0.5 + 0.5 * p)
    tx, ty = x + tail[0] * 60, y + bh / 2 + 50
    d.polygon([(k(x - 24), k(y + bh / 2 - 6)), (k(x + 24), k(y + bh / 2 - 6)), (k(tx), k(ty))], fill=WHITE)
    d.rounded_rectangle([k(x - bw / 2), k(y - bh / 2), k(x + bw / 2), k(y + bh / 2)], k(30), fill=WHITE)
    d.text((k(x), k(y)), text, font=f, fill=INK, anchor="mm")


# ---------------------------------------------------------------- the reel
BASE = 1620   # floor line the characters stand on
GHOST_X, WITCH_X, PUMP_X = 230, 540, 850


def hop(t, period=0.42, height=46):
    ph = (t / period) % 1
    return -height * math.sin(ph * math.pi), 1 + 0.12 * math.cos(ph * 2 * math.pi)


def frame(i, bg):
    t = i / FPS
    img = bg.convert("RGBA")
    d = ImageDraw.Draw(img)
    blink = (int(t * 10) % 31) == 0

    # ---- S1 (0-2.6 s): the costumed gang hops in
    # ---- S2 (2.6-5.6 s): trick or treat at the big flask, it pours candy into each beaker
    # ---- S3 (5.6-9.6 s): pumpkin sneaks to the TAKE 1 cauldron and takes way more
    # ---- S4 (9.6-12.4 s): caught! overflows, mixes into mud, cork pops on
    # ---- S5 (12.4-15 s): end card
    if t < 12.4:
        levels = [0.18, 0.18, 0.18]
        pour = [seg(t, 3.4, 4.0), seg(t, 4.0, 4.6), seg(t, 4.6, 5.2)]
        levels = [l + 0.32 * ease(p) for l, p in zip(levels, pour)]

        # world scroll: S1/S2 at the flask (left side), S3+ pans to the cauldron
        pan = ease(seg(t, 5.6, 6.4)) * 1.0
        # flask on the right in S2
        if t < 6.4:
            fx = 1250 - 420 * ease(seg(t, 1.6, 2.6)) - 900 * pan
            tilt = 0.0
            target = None
            for j, p in enumerate(pour):
                if 0 < p < 1:
                    target = j
            if t > 3.2 and t < 5.4:
                tilt = 32 * ease(seg(t, 3.2, 3.5)) * (1 - ease(seg(t, 5.2, 5.4)))
            sx, sy = flask(img, fx, BASE, tilt, 0.75 - 0.3 * seg(t, 3.4, 5.2), look=-1, blink=blink, t=t)
            if target is not None:   # candy-pink drip stream into the active beaker
                tx = [GHOST_X, WITCH_X, PUMP_X][target] * 0.55 + 120
                for n in range(10):
                    ph = (t * 3 + n / 10) % 1
                    x = sx + (tx - sx) * ph
                    y = sy + (BASE - 300 - sy) * ph - 160 * math.sin(ph * math.pi)
                    d.ellipse([k(x - 12), k(y - 12), k(x + 12), k(y + 12)], fill=PINK)
        if t >= 5.6:
            cx = 1500 - 650 * ease(seg(t, 5.6, 6.6))
            cauldron(img, cx, BASE + 10, t)

        # positions: march in during S1, line up left-of-centre under the flask in S2
        enter = ease(seg(t, 0.2, 2.2))
        line = [GHOST_X * 0.55 + 120, WITCH_X * 0.55 + 120, PUMP_X * 0.55 + 120]
        xs = [-300 + (line[j] + 300) * enter for j in range(3)]
        if t >= 5.6:   # friends slide off left with the pan; pumpkin stays and sneaks right
            xs[0] -= 700 * pan
            xs[1] -= 700 * pan
            xs[2] = line[2] - 50 * pan + 300 * ease(seg(t, 6.4, 8.4))
        hopping = t < 2.4 or (5.6 < t < 6.4)
        sneaking = 6.4 <= t < 8.6
        caught = t >= 9.6
        costumes = [("ghost", GHOST), ("witch", PURPLE), ("pumpkin", ORANGE)]
        for j, (cos, col) in enumerate(costumes):
            if j < 2 and t > 6.6:
                continue
            dy, sq = hop(t + j * 0.13) if hopping else (0, 1 + 0.03 * math.sin(t * 5 + j))
            look, mood, lv, cork, wob, tl = (1 if t < 2.6 else -0.2 if t > 2.6 else 0), "happy", levels[j], 0.0, 0.0, 0.0
            if j == 2:
                if sneaking:
                    tip = (t * 2.6) % 1
                    dy, sq = -18 * abs(math.sin(tip * math.pi)), 1.0
                    look = math.sin(t * 6)
                    mood = "sneaky"
                    tl = 6 * math.sin(t * 5.2)
                if t >= 8.4:   # slurping from the cauldron
                    lv = levels[2] + 0.75 * ease(seg(t, 8.4, 9.8))
                    mood = "sneaky"
                    wob = 0.5
                if caught:
                    mood = "shock"
                    look = 0
                    wob = 1.0
                    dy = -30 * abs(math.sin(t * 18)) * (1 - seg(t, 11.0, 11.4))
                lc = col
                if t >= 10.2:
                    lc = mix(ORANGE, MUD, ease(seg(t, 10.2, 10.9)))
                cork = ease(seg(t, 11.0, 11.35))
                if cork > 0:
                    mood = "happy" if t > 11.6 else "shock"
                beaker(img, xs[j], BASE + dy, lc, lv, cos, look=look, blink=blink and not caught, squash=sq,
                       tilt=tl, mood=mood, cork=cork, wobble=wob, t=t)
            else:
                beaker(img, xs[j], BASE + dy, col, lv, cos, look=look, blink=blink, squash=sq, t=t)
        # S2 dialogue
        speech(img, "TRICK OR TREAT!", 420, 1020, 2.6, t, size=70) if t < 3.4 else None
        # sparkles while filling
        for j, p in enumerate(pour):
            if 0.6 < p <= 1 and t < 5.6:
                for n in range(3):
                    a = n * 2.1 + t * 4
                    star(d, line[j] + 120 * math.cos(a), BASE - 330 + 60 * math.sin(a), 18, (255, 236, 120))
        # S4: spotlight
        if caught:
            dark = Image.new("RGBA", img.size, (0, 0, 0, 0))
            dd = ImageDraw.Draw(dark)
            on = seg(t, 9.6, 9.7)
            dd.rectangle([0, 0, k(W), k(H)], fill=(0, 0, 0, int(175 * on)))
            sx = xs[2]
            dd.ellipse([k(sx - 300), k(BASE - 560), k(sx + 300), k(BASE + 40)], fill=(0, 0, 0, 0))
            dark = dark.filter(ImageFilter.GaussianBlur(k(18)))
            img.alpha_composite(dark)
            d = ImageDraw.Draw(img)
            if t >= 11.0:   # cork pop stars
                p = seg(t, 11.0, 11.6)
                for n in range(8):
                    a = n * math.pi / 4
                    star(d, sx + math.cos(a) * 220 * p, BASE - 430 + math.sin(a) * 140 * p, 26 * (1 - p * 0.6), (255, 236, 120))
            if 11.6 < t < 12.4:   # friends pop back in, laughing
                p = back_out(seg(t, 11.6, 11.95))
                for j, (cos, col) in enumerate(costumes[:2]):
                    beaker(img, -120 + 240 * p + j * 0 + (j * 0), BASE + 60 + j * 0, col, levels[j], cos, mood="laugh",
                           squash=1 + 0.08 * math.sin(t * 30), t=t, scale=0.75) if j == 0 else None
                    beaker(img, W + 120 - 240 * p, BASE + 60, col, levels[j], cos, mood="laugh",
                           squash=1 + 0.08 * math.sin(t * 30), t=t, scale=0.75, look=-1) if j == 1 else None
        # captions
        if t < 2.6:
            caption(img, "What beakers do\non Halloween night", 330, 0.15, t, size=92)
        elif t < 5.6:
            caption(img, "Step 1: trick or treat", 240, 2.6, t, size=80, box=(255, 138, 28))
        elif t < 9.6:
            caption(img, "Step 2: ...take just ONE", 240, 5.9, t, size=80, box=(164, 84, 255))
        elif t < 11.0:
            caption(img, "CAUGHT!", 300, 9.6, t, size=150, color=(255, 214, 60))
        else:
            caption(img, "Mixed a little too much.\nCorked for the night.", 300, 11.0, t, size=74)
        if 8.6 < t < 9.6:
            speech(img, "*slurp*", xs[2] + 40, BASE - 500, 8.6, t, size=60)
    else:
        # ---- S5 end card
        p = seg(t, 12.4, 12.8)
        dd = ImageDraw.Draw(img)
        overlay = Image.new("RGBA", img.size, (24, 12, 46, int(215 * ease(p))))
        img.alpha_composite(overlay)
        for j, (cos, col, x) in enumerate([("ghost", GHOST, 230), ("witch", PURPLE, 540), ("pumpkin", MUD, 850)]):
            bp = back_out(seg(t, 12.5 + j * 0.12, 12.9 + j * 0.12))
            beaker(img, x, BASE + 400 * (1 - bp), col, 0.5 if j < 2 else 1.0, cos, look=0, blink=blink,
                   squash=1 + 0.03 * math.sin(t * 6 + j), cork=1.0 if j == 2 else 0, mood="happy", t=t, scale=0.9)
        caption(img, "BEAKER LAB", 560, 12.6, t, size=150, color=(255, 214, 60))
        caption(img, "Pour it. Mix it. Cork it.", 720, 12.85, t, size=72)
        caption(img, "Search \"Beaker Lab\"\non the App Store", 960, 13.2, t, size=70, box=(255, 138, 28))
        d = ImageDraw.Draw(img)
        for n in range(6):
            a = n * 1.05 + t * 1.5
            star(d, 540 + 430 * math.cos(a), 640 + 160 * math.sin(a * 1.3), 16, (255, 236, 120))
    return img.convert("RGB").resize((W, H), Image.LANCZOS)


_BG = None


def _render(i):
    global _BG
    if _BG is None:
        _BG = make_background()
    return frame(i, _BG).tobytes()


def main():
    n = int(DUR * FPS)
    if "--stills" in sys.argv:
        bg = make_background()
        for s in (1.2, 3.0, 4.4, 7.4, 9.2, 10.4, 11.8, 14.2):
            frame(int(s * FPS), bg).save(os.path.join(HERE, f"still-{s:04.1f}s.png"))
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "19",
                           "-pix_fmt", "yuv420p", "-movflags", "+faststart", OUT], stdin=subprocess.PIPE)
    with Pool() as pool:
        for b in pool.imap(_render, range(n), chunksize=4):
            ff.stdin.write(b)
    ff.stdin.close()
    ff.wait()
    print("wrote", OUT)


if __name__ == "__main__":
    main()
