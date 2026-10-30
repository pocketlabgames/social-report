"""Beaker Lab Halloween reel "Pumpkin carving" (Halloween day post): 1080x1920, 60 fps, ~16.5 s.

Story (Guy, Oct 30): pumpkin carving night. The purple skeleton beaker and the green cat beaker each carve a
pumpkin, then turn them around at the same moment: the skeleton carved a cat face, the cat carved a skull. They
laugh ("great minds carve alike"), the candles flicker out, and we zoom into the skeleton's purple liquid in the
dark; the game's bubble transition, ad105 gameplay with combo punches, ad105 end card.

Reuses the room, camera and gameplay helpers from render_last_candy.py:
    python3 render_pumpkin.py /path/to/ad105-tue-trick-or-treat-spooky-dark.mp4 [--stills[-only]]
"""
import math
import os
import random
import subprocess
import sys
import tempfile
from multiprocessing import Pool

from PIL import Image, ImageDraw, ImageFilter

import render_last_candy as lc
import render_mirror_maze as mm
from render_last_candy import FL, FPS, GP_FPS, WIDE, cam_at, camera, punch, room, stars
from render_mirror_maze import (CS, H, W, bubble_reveal, caption, ease, exclaim, fizz_frame, k, mix, place, seg,
                                speech, tube)

OUT = os.path.join(mm.HERE, "pumpkin.mp4")
SKEL_X, CAT_X = 200, 880
PUMP = {"skeleton": 425, "cat": 655}       # each beaker's pumpkin on the table (x); table top at y 1330
TABLE = 1330
Z0 = 9.4                                   # zoom into the skeleton's liquid
TR = Z0 + 0.45                             # bubble transition
GP_IN = lc.GP_IN                           # first pour you see is a combo
GP_END = TR + mm.GP_OUT - GP_IN

ORANGE, RIB, CUT = (240, 120, 24), (206, 92, 14), (60, 26, 6)
GLOW = (255, 206, 90)

# camera: hold wide, glide to each carved pumpkin after the reveal, back out for the laugh
CAM = [(4.7, *WIDE), (5.25, PUMP["skeleton"], TABLE - 100, 2.3), (5.6, PUMP["skeleton"], TABLE - 100, 2.3),
       (6.1, PUMP["cat"], TABLE - 100, 2.3), (6.6, PUMP["cat"], TABLE - 100, 2.3), (7.1, *WIDE)]


def pumpkin(img, x, face, spin, glow, shake=0.0):
    """Pumpkin on the table. spin 0..1 turns it around (back -> carved face); glow 0..1 is the candle inside."""
    d = ImageDraw.Draw(img)
    wv = max(0.04, abs(math.cos(math.pi * spin)))
    front = spin >= 0.5
    x += shake
    w, h = 104, 170
    if front and glow > 0:                     # warm halo
        halo = Image.new("L", (k(W) // 8, k(H) // 8), 0)
        ImageDraw.Draw(halo).ellipse([k(x - 140) / 8, k(TABLE - h - 30) / 8, k(x + 140) / 8, k(TABLE + 10) / 8], fill=int(110 * glow))
        halo = halo.filter(ImageFilter.GaussianBlur(3)).resize(img.size, Image.BILINEAR)
        lay = Image.new("RGBA", img.size, GLOW + (0,))
        lay.putalpha(halo)
        img.alpha_composite(lay)
        d = ImageDraw.Draw(img)
    d.rounded_rectangle([k(x - 8), k(TABLE - h - 28), k(x + 8), k(TABLE - h + 6)], k(5), fill=(96, 120, 40))
    for i, f in enumerate((-0.55, 0.55, -0.27, 0.27, 0)):        # ribs, outer to inner
        cx, rw = x + f * w * wv, w * 0.6 * wv
        d.ellipse([k(cx - rw), k(TABLE - h), k(cx + rw), k(TABLE)], fill=RIB if i < 2 else ORANGE,
                  outline=RIB, width=k(3))
    if not front:
        return
    c = mix(CUT, GLOW, glow)
    def P(px, py):                               # face coords (relative to pumpkin centre) -> canvas
        return k(x + px * 1.15 * wv), k(TABLE - h / 2 + py * 1.15)
    if face == "cat":
        for sgn in (-1, 1):
            d.polygon([P(sgn * 18, -22), P(sgn * 50, -30), P(sgn * 44, -6), P(sgn * 22, -6)], fill=c)       # eyes
            for n in (-1, 0, 1):                                                                            # whiskers
                d.line([P(sgn * 24, 20 + n * 9), P(sgn * 70, 14 + n * 14)], fill=c, width=k(4))
            d.polygon([P(sgn * 30, -h / 2.3 + 8), P(sgn * 50, -h / 2.3 + 22), P(sgn * 18, -h / 2.3 + 22)], fill=c)  # ears
        d.polygon([P(-9, 6), P(9, 6), P(0, 16)], fill=c)                                                    # nose
        d.polygon([P(-22, 24), P(-11, 34), P(0, 26), P(11, 34), P(22, 24), P(11, 40), P(0, 33), P(-11, 40)], fill=c)
    else:   # skull
        for sgn in (-1, 1):
            ex, ey = sgn * 30, -14
            d.ellipse([*P(ex - 20, ey - 20), *P(ex + 20, ey + 20)], fill=c)
        d.polygon([P(-9, 18), P(9, 18), P(0, 4)], fill=c)
        d.rounded_rectangle([*P(-40, 30), *P(40, 54)], k(6), fill=c)
        for n in range(-3, 4):
            d.line([P(n * 11, 28), P(n * 11, 56)], fill=ORANGE, width=k(4))


def chunks(img, t):
    """Pumpkin bits flying while they carve."""
    d = ImageDraw.Draw(img)
    rnd = random.Random(8)
    for i in range(26):
        t0 = 0.45 + i * 0.075
        who = "skeleton" if i % 2 else "cat"
        vx, vy = rnd.uniform(-260, 260), rnd.uniform(-720, -520)
        age = t - t0
        if not (0 <= age < 0.6) or t0 > 2.4:
            continue
        x = PUMP[who] + vx * age
        y = TABLE - 150 + vy * age + 1900 * age * age
        r = rnd.uniform(7, 13)
        d.rounded_rectangle([k(x - r), k(y - r * 0.7), k(x + r), k(y + r * 0.7)], k(3), fill=(250, 150, 50))


def story_frame(t):
    global ROOM
    if ROOM is None:
        ROOM = room(bucket=False)
    img = ROOM.copy()
    blink = int(t * 10) % 37 == 0
    carving = 0.4 <= t < 2.4
    mood = "happy" if (2.4 <= t < 6.8 or t >= 7.2) else "calm"
    if 6.8 <= t < 7.2:
        mood = "scared"                                       # wait... what?!
    laugh = 7.2 <= t < 8.6
    jump = -60 * math.sin(math.pi * seg(t, 6.8, 7.05)) if 6.8 <= t < 7.05 else 0
    bob = -12 * abs(math.sin(t * 20)) if laugh else 0
    lean = 8 * math.sin(t * 16) if carving else 0
    sk, sfx, sfy = tube("skeleton", t, mood, look=1, blink=blink and mood == "calm")
    ct, cfx, cfy = tube("cat", t, mood, look=-1, blink=blink and mood == "calm")
    sq = 1 + 0.05 * math.sin(t * 40) if laugh else 1.0

    # candles: on at the reveal, flicker, out at 9.0
    glow = 0.0
    if t >= 4.5:
        glow = 0.85 + 0.15 * math.sin(t * 23) * math.sin(t * 7)
    if t >= 8.4:
        glow *= max(0.0, 1 - seg(t, 8.4, 9.0)) * (0.5 + 0.5 * abs(math.sin(t * 40)))
    spin = ease(seg(t, 4.0, 4.6))
    shake = 4 * math.sin(t * 50) if carving else 0
    pumpkin(img, PUMP["skeleton"], "cat", spin, glow, shake)
    pumpkin(img, PUMP["cat"], "skull", spin, glow, -shake)
    chunks(img, t)
    place(img, sk, sfx, sfy, SKEL_X, FL + jump + bob, tilt=-abs(lean), squash=sq)
    place(img, ct, cfx, cfy, CAT_X, FL + jump + bob, tilt=abs(lean), squash=sq)
    stars(img, PUMP["skeleton"], TABLE - 200, seg(t, 2.4, 3.0), n=6, spread=120)
    stars(img, PUMP["cat"], TABLE - 200, seg(t, 2.45, 3.05), n=6, spread=120)
    speech(img, "Ready?", CAT_X - 60, FL - 860, 3.0, t) if 3.0 <= t < 4.0 else None
    exclaim(img, SKEL_X + 40, FL - 780, 6.8, t, 0.5)
    exclaim(img, CAT_X - 40, FL - 780, 6.8, t, 0.5)

    # lights out
    dark = seg(t, 8.6, 9.2)
    if dark > 0:
        img.alpha_composite(Image.new("RGBA", img.size, (6, 2, 14, int(170 * ease(dark)))))
    img = camera(img, *cam_at(t, CAM))
    caption(img, "Pumpkin carving night...", 250, 0.2, 3.0, t)
    caption(img, "...great minds carve alike", 250, 7.15, 8.6, t, size=70)
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
        base = fizz_frame(t, story_frame(Z0), z0=Z0, tr=TR, focus=(SKEL_X + 6, FL - 175 * CS), liquid="purple")
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
        for s in (1.0, 2.7, 3.5, 4.3, 5.4, 6.4, 6.9, 7.8, 8.8, 9.3, 9.7, 10.2):
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
