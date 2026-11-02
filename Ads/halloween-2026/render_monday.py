"""Beaker Lab reel "POV: Monday after Halloween": 1080x1920, 60 fps, ~10.9 s.

Story (Nov 2): Monday morning, the day after Halloween weekend. The beakers are asleep on their feet (the skeleton's
skull is off, on the table with the candy wrappers). A beaker of coffee floats over and pours into each of them,
game style; every pour is a combo with the 10pm-post punch ("Monday combo ☕ / Combo ×1, ×2, ×3") and they wake up.
Zoom into the skeleton's purple liquid, the game's bubble transition, ad105 gameplay with combo punches, end card.
Built to hook in the first second and reach gameplay by ~4 s (IG/FB average watch time is under 5 s).

    python3 render_monday.py /path/to/ad105-tue-trick-or-treat-spooky-dark.mp4 [--stills[-only]]
"""
import math
import os
import random
import subprocess
import sys
import tempfile
from multiprocessing import Pool

from PIL import Image, ImageDraw, ImageFont

import render_last_candy as lc
import render_mirror_maze as mm
from render_dst import skull_piece
from render_last_candy import FL, FPS, GP_FPS, punch, room, stars
from render_mirror_maze import (CS, EMOJI, H, INK, W, back_out, bubble_reveal, caption, ease, fizz_frame, k, mix,
                                place, seg, tube)

OUT = os.path.join(mm.HERE, "monday.mp4")
SKEL_X, CAT_X = 230, 850
TABLE = 1330
COFFEE_HOME = (690, TABLE)                 # coffee beaker standing on the table (foot point)
RIM = FL - 316 * CS                        # top of a beaker's glass
POURS = [(1.85, 2.45, SKEL_X), (2.85, 3.45, CAT_X)]   # (start, end, target x): coffee pours, each ends in a combo
COMBOS = [2.45, 3.45, 3.75]                # combo x1, x2, x3 (x3 = both awake, happy hop)
Z0 = 4.05                                  # zoom into the skeleton's liquid
TR = Z0 + 0.45
GP_IN = lc.GP_IN
GP_END = TR + mm.GP_OUT - GP_IN
COFFEE, COFFEE_D = (150, 90, 45), (86, 46, 20)


def morning_window(img):
    """Dawn sky in the room's window (it was night in the Halloween reels)."""
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = 608, 308, 952, 752
    for y in range(k(y0), k(y1), 2):
        d.line([(k(x0), y), (k(x1), y)], fill=mix((120, 170, 235), (255, 190, 130), (y - k(y0)) / k(y1 - y0)) + (255,), width=2)
    d.ellipse([k(800), k(600), k(900), k(700)], fill=(255, 236, 170, 255))
    d.line([(k(780), k(y0)), (k(780), k(y1))], fill=(110, 70, 140, 255), width=k(12))
    d.line([(k(x0), k(530)), (k(x1), k(530))], fill=(110, 70, 140, 255), width=k(12))


def wrappers(img):
    d = ImageDraw.Draw(img)
    rnd = random.Random(6)
    for i in range(9):
        x = rnd.uniform(350, 740) if i < 5 else rnd.uniform(80, 1000)
        y = TABLE - 10 if i < 5 else rnd.uniform(1620, 1760)
        c = [(255, 92, 178), (255, 214, 60), (90, 200, 255), (255, 150, 40)][i % 4]
        a = rnd.uniform(-0.6, 0.6)
        for sgn in (-1, 1):
            ex, ey = x + sgn * 26 * math.cos(a), y + sgn * 26 * math.sin(a)
            d.polygon([(k(ex), k(ey)), (k(ex + sgn * 14), k(ey - 10)), (k(ex + sgn * 14), k(ey + 10))], fill=c)
        d.ellipse([k(x - 18), k(y - 11), k(x + 18), k(y + 11)], fill=c)


def coffee_beaker(img, x, y, angle, level, t):
    """Beaker of coffee, foot-centre at (x, y) when upright; angle in degrees (+ = tips its mouth to the left).
    Returns the mouth position (frame coords)."""
    w, h = 96, 230
    lw, lh = k(w + 120), k(h + 120)
    L = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    d = ImageDraw.Draw(L)
    cx, cy = lw / 2, lh / 2
    x0, y0, x1, y1 = cx - k(w / 2), cy - k(h / 2), cx + k(w / 2), cy + k(h / 2)
    d.rounded_rectangle([x0, y0, x1, y1], k(w / 2), fill=(220, 235, 255, 50))
    liq = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(liq)
    top = y1 - (y1 - y0 - k(20)) * level
    for yy in range(int(top), int(y1), 2):
        ld.line([(x0, yy), (x1, yy)], fill=mix(COFFEE, COFFEE_D, (yy - top) / max(1, y1 - top)) + (245,), width=2)
    ld.ellipse([x0, top - k(8), x1, top + k(8)], fill=(210, 160, 110, 245))       # crema
    body = Image.new("L", (lw, lh), 0)
    ImageDraw.Draw(body).rounded_rectangle([x0 + k(4), y0 + k(4), x1 - k(4), y1 - k(4)], k(w / 2 - 4), fill=255)
    clip = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    clip.paste(liq, (0, 0), body)
    L.alpha_composite(clip)
    d.rounded_rectangle([x0, y0, x1, y1], k(w / 2), outline=(235, 245, 255, 230), width=k(5))
    d.ellipse([x0 - k(8), y0 - k(6), x1 + k(8), y0 + k(14)], outline=(235, 245, 255, 255), width=k(5))
    d.rounded_rectangle([x0 + k(14), y0 + k(34), x0 + k(26), y1 - k(60)], k(6), fill=(255, 255, 255, 110))
    rot = L.rotate(angle, resample=Image.BICUBIC, center=(cx, cy))
    ccx, ccy = x, y - h / 2                                  # beaker centre in frame coords
    img.alpha_composite(rot, (int(k(ccx) - cx), int(k(ccy) - cy)))
    a = math.radians(angle)
    mx, my = ccx - (h / 2) * math.sin(a), ccy - (h / 2) * math.cos(a)
    if angle < 20:                                            # steam while it stands
        d2 = ImageDraw.Draw(img)
        for i in range(3):
            ph = (t * 0.8 + i / 3) % 1
            sx = mx - 20 + i * 20 + 10 * math.sin(ph * 8 + i)
            sy = my - 20 - 90 * ph
            r = 10 + 10 * ph
            d2.ellipse([k(sx - r), k(sy - r), k(sx + r), k(sy + r)], fill=(255, 255, 255, int(110 * (1 - ph))))
    return mx, my


def coffee_state(t):
    """Where the coffee beaker is: (x, foot y, angle, level)."""
    level = 0.8
    hover = lambda tx: (tx + (150 if tx < W / 2 else -150), RIM - 120)   # pour from the side facing the table
    if t < 1.35:
        return COFFEE_HOME[0], COFFEE_HOME[1], 0.0, level
    (s1, e1, t1), (s2, e2, t2) = POURS
    if t < s1:                                                # fly over to the skeleton
        p = ease(seg(t, 1.35, s1))
        hx, hy = hover(t1)
        return COFFEE_HOME[0] + (hx - COFFEE_HOME[0]) * p, COFFEE_HOME[1] + (hy - COFFEE_HOME[1]) * p - 120 * math.sin(math.pi * p), 0.0, level
    if t < s2 - 0.35:                                         # pour into the skeleton
        hx, hy = hover(t1)
        tilt = 112 * ease(seg(t, s1, s1 + 0.2)) * (1 - ease(seg(t, e1 - 0.1, e1 + 0.1)))
        return hx, hy, tilt, level - 0.25 * seg(t, s1 + 0.15, e1)
    if t < s2:                                                # hop over to the cat
        p = ease(seg(t, s2 - 0.35, s2))
        (ax, ay), (bx, by) = hover(t1), hover(t2)
        return ax + (bx - ax) * p, ay - 90 * math.sin(math.pi * p), 0.0, level - 0.25
    hx, hy = hover(t2)
    tilt = -112 * ease(seg(t, s2, s2 + 0.2)) * (1 - ease(seg(t, e2 - 0.1, e2 + 0.1)))
    return hx, hy, tilt, level - 0.25 - 0.25 * seg(t, s2 + 0.15, e2)


def combo_badge(img, t):
    """Game-style combo badge: grey panel 'Monday combo ☕' over a red 'Combo ×N' pill; pops on each combo."""
    n = sum(1 for c in COMBOS if t >= c)
    if n == 0:
        return
    p = back_out(seg(t, COMBOS[n - 1], COMBOS[n - 1] + 0.25))
    s = 0.95 * (0.9 + 0.1 * p)
    d = ImageDraw.Draw(img)
    cx, cy = W / 2, 430
    pw, ph = 600 * s, 190 * s
    d.rounded_rectangle([k(cx - pw / 2), k(cy - ph / 2), k(cx + pw / 2), k(cy + ph / 2)], k(30 * s), fill=(206, 206, 212))
    f1 = ImageFont.truetype(mm.FONT, k(52 * s))
    tw = d.textlength("Monday combo", font=f1) / mm.K
    d.text((k(cx - 30 * s), k(cy - 45 * s)), "Monday combo", font=f1, fill=INK, anchor="mm")
    em = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    ImageDraw.Draw(em).text((0, 0), "☕", font=ImageFont.truetype(EMOJI, 109), embedded_color=True)
    em = em.crop(em.getbbox()).resize((k(52 * s), k(52 * s)), Image.LANCZOS)
    img.alpha_composite(em, (k(cx - 30 * s + tw / 2 + 12 * s), k(cy - 45 * s - 26 * s)))
    d = ImageDraw.Draw(img)
    qw, qh = 390 * s, 92 * s
    d.rounded_rectangle([k(cx - qw / 2), k(cy + 40 * s - qh / 2), k(cx + qw / 2), k(cy + 40 * s + qh / 2)], k(16 * s), fill=(220, 20, 60))
    f2 = ImageFont.truetype(mm.FONT, k(70 * s))
    d.text((k(cx), k(cy + 40 * s)), f"Combo ×{n}", font=f2, fill=(255, 255, 255), anchor="mm")


def zzz(img, x, y, t):
    d = ImageDraw.Draw(img)
    for i in range(3):
        ph = (t * 0.7 + i / 3) % 1
        f = ImageFont.truetype(mm.FONT, k(30 + 26 * ph))
        a = int(255 * min(1, 3 * (1 - ph)))
        d.text((k(x + 60 * ph), k(y - 160 * ph)), "z", font=f, fill=(230, 230, 255, a), anchor="mm", stroke_width=k(3), stroke_fill=INK + (a,))


def story_punch(img, t):
    """The 10pm-post punch on each story combo (same look as the gameplay punches)."""
    for c in COMBOS:
        dt = t - c
        if 0 <= dt < 0.45:
            return punch_at(img, dt)
    return img


def punch_at(img, dt):
    z = 1 + 0.12 * seg(dt, 0, 0.05) * (1 - ease(seg(dt, 0.05, 0.42)))
    w, h = img.size
    cw, ch = w / z, h / z
    img = img.resize((w, h), Image.BICUBIC, box=((w - cw) / 2, (h - ch) / 2, (w + cw) / 2, (h + ch) / 2))
    fade = 1 - ease(seg(dt, 0.1, 0.45))
    rays = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(rays)
    cx, cy, R = w / 2, h * 0.55, 2600 * mm.K
    for n in range(28):
        th = n * 2 * math.pi / 28 + 0.05
        wd = 0.035 if n % 2 else 0.02
        d.polygon([(cx + k(120) * math.cos(th), cy + k(120) * math.sin(th)), (cx + R * math.cos(th - wd), cy + R * math.sin(th - wd)),
                   (cx + R * math.cos(th + wd), cy + R * math.sin(th + wd))], fill=(255, 255, 255, int(34 * fade)))
    img.alpha_composite(rays)
    return img


def story_frame(t, punched=True):
    global ROOM
    if ROOM is None:
        ROOM = room(bucket=True)
        morning_window(ROOM)
        wrappers(ROOM)
        skull_piece(ROOM, 430, TABLE - 60, 0.62)
    img = ROOM.copy()
    s_awake, c_awake = t >= POURS[0][1] - 0.1, t >= POURS[1][1] - 0.1
    hop = -70 * math.sin(math.pi * seg(t, COMBOS[2], COMBOS[2] + 0.3)) if COMBOS[2] <= t < COMBOS[2] + 0.3 else 0
    slump = lambda awake: 1.0 if awake else 0.93 + 0.02 * math.sin(t * 2.5)
    perk_s = 1 + 0.1 * math.sin(math.pi * seg(t, POURS[0][1] - 0.1, POURS[0][1] + 0.2))
    perk_c = 1 + 0.1 * math.sin(math.pi * seg(t, POURS[1][1] - 0.1, POURS[1][1] + 0.2))
    sk, sfx, sfy = tube("skeleton", t, "happy" if s_awake else "calm", blink=not s_awake, bare=True)
    ct, cfx, cfy = tube("cat", t, "happy" if c_awake else "calm", blink=not c_awake)
    place(img, sk, sfx, sfy, SKEL_X, FL + hop, squash=slump(s_awake) * perk_s, tilt=0 if s_awake else -5)
    place(img, ct, cfx, cfy, CAT_X, FL + hop, squash=slump(c_awake) * perk_c, tilt=0 if c_awake else 5)
    if not s_awake:
        zzz(img, SKEL_X + 50, RIM - 60, t)
    if not c_awake:
        zzz(img, CAT_X + 50, RIM - 140, t + 0.4)

    x, y, ang, lev = coffee_state(t)
    mx, my = coffee_beaker(img, x, y, ang, lev, t)
    for s, e, tx in POURS:                                    # coffee stream into the target's rim
        if s + 0.15 <= t < e:
            d = ImageDraw.Draw(img)
            pts = [(mx + (tx - mx) * u + 6 * math.sin(t * 30 + u * 9), my + (RIM - my) * u) for u in [i / 12 for i in range(13)]]
            d.line([(k(px), k(py)) for px, py in pts], fill=COFFEE + (255,), width=k(16))
    stars(img, SKEL_X, RIM - 80, seg(t, POURS[0][1], POURS[0][1] + 0.5), n=6, spread=130)
    stars(img, CAT_X, RIM - 120, seg(t, POURS[1][1], POURS[1][1] + 0.5), n=6, spread=130)

    if punched:
        img = story_punch(img, t)
    combo_badge(img, t)
    caption(img, "POV: Monday after\nHalloween...", 230, 0.0, 2.4, t, size=90)
    caption(img, "...okay, NOW we're awake", 250, 3.75, 4.05, t, size=74)
    return img


ROOM = None


def frame(i, gp_frames):
    t = i / FPS
    if t >= TR + mm.TD:                           # gameplay, with the combo punches
        g = min(int((t - TR) * GP_FPS), len(gp_frames) - 1)
        return punch(Image.open(gp_frames[g]).convert("RGB"), t, TR, GP_IN)
    if t < Z0:
        img = story_frame(t)
    else:
        base = fizz_frame(t, story_frame(Z0, punched=False), z0=Z0, tr=TR, focus=(SKEL_X + 6, FL - 175 * CS), liquid="purple")
        if t < TR:
            img = base
        else:
            g = min(int((t - TR) * GP_FPS), len(gp_frames) - 1)
            img = bubble_reveal(t, base, Image.open(gp_frames[g]), tr=TR)
    return img.convert("RGB").resize((W, H), Image.LANCZOS)


_GP = []


def _init(gp):
    _GP.extend(gp)


def _render(i):
    return frame(i, _GP).tobytes()


def main():
    src = [a for a in sys.argv[1:] if not a.startswith("--")][0]
    tmp = tempfile.mkdtemp()
    subprocess.run(["ffmpeg", "-v", "error", "-ss", str(GP_IN), "-i", src, "-t", str(mm.GP_OUT - GP_IN),
                    "-vf", f"fps={GP_FPS}", "-q:v", "2", os.path.join(tmp, "gp%03d.jpg")], check=True)
    gp = sorted(os.path.join(tmp, f) for f in os.listdir(tmp) if f.startswith("gp"))
    if any(a.startswith("--stills") for a in sys.argv):
        _init(gp)
        for s in (0.5, 1.6, 2.1, 2.5, 3.0, 3.2, 3.5, 3.8, 4.3, 5.0):
            frame(int(s * FPS), _GP).save(os.path.join(os.getcwd(), f"still-{s:05.2f}s.png"))
        if "--stills-only" in sys.argv:
            return
    anim = os.path.join(tmp, "anim.mp4")
    ff = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                           "-i", "-", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", anim], stdin=subprocess.PIPE)
    with Pool(initializer=_init, initargs=(gp,)) as pool:
        for b in pool.imap(_render, range(int(GP_END * FPS)), chunksize=3):
            ff.stdin.write(b)
    ff.stdin.close()
    ff.wait()
    fc = (f"[0:v]setpts=PTS-STARTPTS[a];"
          f"[1:v]trim={mm.CARD_IN}:{mm.CARD_OUT},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={mm.CARD_HOLD}[c];"
          f"[a][c]concat=n=2:v=1:a=0[v]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", anim, "-i", src, "-filter_complex", fc, "-map", "[v]",
                    "-c:v", "libx264", "-crf", "19", "-preset", "slow", "-pix_fmt", "yuv420p", "-r", str(FPS),
                    "-movflags", "+faststart", OUT], check=True)
    total = GP_END + (mm.CARD_OUT - mm.CARD_IN) + mm.CARD_HOLD
    print(f"wrote {OUT} ({total:.1f} s)")


if __name__ == "__main__":
    main()
