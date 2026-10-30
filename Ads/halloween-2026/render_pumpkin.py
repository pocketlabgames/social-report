"""Beaker Lab Halloween reel "Pumpkin carving" (Halloween day post): 1080x1920, 60 fps, ~16.5 s.

Story (Guy, Oct 30): pumpkin carving night. The purple skeleton beaker and the green cat beaker each carve a
jack-o'-lantern, spin them around to show off the glowing faces (a classic toothy grin and a cute smiley one), cheer
"Happy Halloween!", the candles flicker out, and we zoom into the skeleton's purple liquid in the dark; the game's
bubble transition, ad105 gameplay with combo punches, ad105 end card. (~14.5 s after the close-up cut)

Reuses the room and gameplay helpers from render_last_candy.py:
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
from render_last_candy import FL, FPS, GP_FPS, punch, room, stars
from render_mirror_maze import (CS, H, W, bubble_reveal, caption, ease, fizz_frame, k, mix, place, seg,
                                speech, tube)

OUT = os.path.join(mm.HERE, "pumpkin.mp4")
SKEL_X, CAT_X = 200, 880
PUMP = {"skeleton": 425, "cat": 655}       # each beaker's pumpkin on the table (x); table top at y 1330
TABLE = 1330
CUT_AT, CUT_LEN = 4.8, 2.0                 # story 4.8-6.8 s (camera glides to each pumpkin) was cut (Guy, Oct 30)
Z0 = 9.4 - CUT_LEN                         # zoom into the skeleton's liquid (video time)
TR = Z0 + 0.45                             # bubble transition
GP_IN = lc.GP_IN                           # first pour you see is a combo
GP_END = TR + mm.GP_OUT - GP_IN

ORANGE, RIB, CUT = (240, 120, 24), (206, 92, 14), (60, 26, 6)
GLOW = (255, 206, 90)

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
    if face == "classic":                        # triangle eyes and nose, toothy zigzag grin
        for sgn in (-1, 1):
            d.polygon([P(sgn * 14, -6), P(sgn * 50, -6), P(sgn * 32, -36)], fill=c)
        d.polygon([P(-10, 14), P(10, 14), P(0, 0)], fill=c)
        grin = [P(-52, 22), P(-36, 30), P(-26, 24), P(-14, 34), P(0, 26), P(14, 34), P(26, 24), P(36, 30), P(52, 22),
                P(40, 46), P(20, 56), P(0, 52), P(-20, 56), P(-40, 46)]
        d.polygon(grin, fill=c)
    else:                                        # cute: round eyes, little nose, big smile with one tooth
        for sgn in (-1, 1):
            d.ellipse([*P(sgn * 30 - 15, -34), *P(sgn * 30 + 15, -4)], fill=c)
        d.ellipse([*P(-7, 4), *P(7, 14)], fill=c)
        d.chord([*P(-46, 2), *P(46, 58)], 0, 180, fill=c)
        d.rectangle([*P(8, 30), *P(20, 42)], fill=ORANGE)


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
    """t is story time (before the cut)."""
    global ROOM
    if ROOM is None:
        ROOM = room(bucket=False)
    img = ROOM.copy()
    blink = int(t * 10) % 37 == 0
    carving = 0.4 <= t < 2.4
    mood = "happy" if t >= 2.4 else "calm"
    cheer = 6.9 <= t < 8.5
    # two happy hops for "Happy Halloween!", then a gentle sway
    jump = -70 * abs(math.sin(math.pi * seg(t, 6.9, 7.7) * 2)) if 6.9 <= t < 7.7 else 0
    bob = -6 * math.sin(t * 6) if cheer and t >= 7.7 else 0
    # lean in to carve (eased in/out), with a small working wiggle
    lean = 7 * ease(seg(t, 0.3, 0.6)) * (1 - ease(seg(t, 2.3, 2.6))) + (1.5 * math.sin(t * 18) if carving else 0)
    sk, sfx, sfy = tube("skeleton", t, mood, look=1, blink=blink and mood == "calm")
    ct, cfx, cfy = tube("cat", t, mood, look=-1, blink=blink and mood == "calm")
    sq = 1 + 0.06 * math.sin(math.pi * seg(t, 6.9, 7.7) * 4) if 6.9 <= t < 7.7 else 1.0

    # candles: on at the reveal, flicker, out at 9.0
    glow = 0.0
    if t >= 4.5:
        glow = 0.85 + 0.15 * math.sin(t * 23) * math.sin(t * 7)
    if t >= 8.4:
        glow *= max(0.0, 1 - seg(t, 8.4, 9.0)) * (0.5 + 0.5 * abs(math.sin(t * 40)))
    spin = ease(seg(t, 4.0, 4.6))
    shake = 4 * math.sin(t * 50) if carving else 0
    pumpkin(img, PUMP["skeleton"], "classic", spin, glow, shake)
    pumpkin(img, PUMP["cat"], "cute", spin, glow, -shake)
    chunks(img, t)
    place(img, sk, sfx, sfy, SKEL_X, FL + jump + bob, tilt=-lean, squash=sq)
    place(img, ct, cfx, cfy, CAT_X, FL + jump + bob, tilt=lean, squash=sq)
    stars(img, PUMP["skeleton"], TABLE - 200, seg(t, 2.4, 3.0), n=6, spread=120)
    stars(img, PUMP["cat"], TABLE - 200, seg(t, 2.45, 3.05), n=6, spread=120)
    speech(img, "Ready?", CAT_X - 60, FL - 860, 3.0, t) if 3.0 <= t < 4.0 else None
    stars(img, SKEL_X, FL - 760, seg(t, 6.95, 7.6), n=7, spread=150)
    stars(img, CAT_X, FL - 760, seg(t, 6.95, 7.6), n=7, spread=150)

    # lights out
    dark = seg(t, 8.6, 9.2)
    if dark > 0:
        img.alpha_composite(Image.new("RGBA", img.size, (6, 2, 14, int(170 * ease(dark)))))
    caption(img, "Pumpkin carving night...", 250, 0.2, 3.0, t)
    caption(img, "Happy Halloween!", 280, 6.9, 8.6, t, size=110)
    return img


ROOM = None


def frame(i, gp_frames):
    t = i / FPS
    if t >= TR + mm.TD:                           # gameplay, with the combo punches
        g = min(int((t - TR) * GP_FPS), len(gp_frames) - 1)
        return punch(Image.open(gp_frames[g]).convert("RGB"), t, TR, GP_IN)
    if t < Z0:
        img = story_frame(t if t < CUT_AT else t + CUT_LEN)
    else:
        base = fizz_frame(t, story_frame(Z0 + CUT_LEN), z0=Z0, tr=TR, focus=(SKEL_X + 6, FL - 175 * CS), liquid="purple")
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
        for s in (1.0, 2.7, 3.5, 4.3, 4.7, 4.85, 5.2, 6.0, 6.8, 7.3, 7.7, 8.2):
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
