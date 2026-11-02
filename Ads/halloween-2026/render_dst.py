"""Beaker Lab reel "One more hour of Halloween" (daylight saving, Nov 2026): 1080x1920, 60 fps, ~15 s.

Story (Guy, Nov 2): Nov 1, 1:59 AM. Halloween is over: costumes off (the skull and the cat ears lie on the table),
both beakers sad. The pumpkin clock on the wall strikes 2:00... and falls back to 1:00. One more hour of Halloween!
They pop their costumes back on and party (confetti, hops). Zoom into the cat's green liquid, the game's bubble
transition, ad105 gameplay with combo punches, ad105 end card.

Reuses the room and gameplay helpers from render_last_candy.py:
    python3 render_dst.py /path/to/ad105-tue-trick-or-treat-spooky-dark.mp4 [--stills[-only]]
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
from render_last_candy import FL, FPS, GP_FPS, NOTE_FONT, WIDE, cam_at, camera, punch, room, stars
from render_mirror_maze import (CS, H, INK, W, back_out, bubble_reveal, caption, ease, exclaim, fizz_frame, k, place,
                                seg, tube)

OUT = os.path.join(mm.HERE, "dst.mp4")
SKEL_X, CAT_X = 200, 880
TABLE = 1330
CLOCK = (500, 560, 86)                     # pumpkin wall clock: centre x, y, radius
SKULL_AT, EARS_AT = (420, TABLE - 60), (660, TABLE - 34)   # costume pieces lying on the table
HEAD = FL - 566                            # skull centre when worn (tube geometry x CS)
EARS_ON = FL - 520                         # ear band when worn
Z0 = 7.9                                   # zoom into the cat's liquid
TR = Z0 + 0.45                             # bubble transition
GP_IN = lc.GP_IN                           # first pour you see is a combo
GP_END = TR + mm.GP_OUT - GP_IN
SKULL_T, EARS_T = (4.7, 5.05), (5.0, 5.35)  # costume pieces fly back on

CAM = [(2.55, *WIDE), (3.1, CLOCK[0], CLOCK[1] + 40, 2.8), (3.85, CLOCK[0], CLOCK[1] + 40, 2.8), (4.35, *WIDE)]


def clock_time(t):
    """Minutes past midnight shown on the clock: 1:59 -> 2:00, falls back to 1:00, then ticks on."""
    if t < 2.95:
        return 119
    if t < 3.2:
        return 120
    if t < 3.75:
        return 120 - 60 * ease(seg(t, 3.2, 3.75))     # hands spin back an hour
    return 60 + (t - 3.75) * 0.6


def wall_clock(img, t):
    d = ImageDraw.Draw(img)
    cx, cy, r = CLOCK
    wob = 3 * math.sin(t * 60) * (1 - seg(t, 3.0, 3.35)) if 3.0 <= t < 3.35 else 0    # DONG
    cx += wob
    d.rounded_rectangle([k(cx - 8), k(cy - r - 26), k(cx + 8), k(cy - r + 6)], k(5), fill=(96, 120, 40))
    for f in (-0.45, 0.45, 0):
        d.ellipse([k(cx + f * r - r * 0.75), k(cy - r), k(cx + f * r + r * 0.75), k(cy + r)], fill=(240, 120, 24),
                  outline=(206, 92, 14), width=k(3))
    d.ellipse([k(cx - r * 0.72), k(cy - r * 0.72), k(cx + r * 0.72), k(cy + r * 0.72)], fill=(255, 236, 196))
    f = ImageFont.truetype(NOTE_FONT, k(22))
    for n, lab in ((0, "12"), (3, "3"), (6, "6"), (9, "9")):
        a = math.radians(n * 30 - 90)
        d.text((k(cx + r * 0.56 * math.cos(a)), k(cy + r * 0.56 * math.sin(a))), lab, font=f, fill=INK, anchor="mm")
    m = clock_time(t)
    for frac, length, width in ((m / 720, 0.36, 7), ((m % 60) / 60, 0.56, 5)):
        a = 2 * math.pi * frac - math.pi / 2
        d.line([(k(cx), k(cy)), (k(cx + r * length * math.cos(a)), k(cy + r * length * math.sin(a)))], fill=INK, width=k(width))
    d.ellipse([k(cx - 6), k(cy - 6), k(cx + 6), k(cy + 6)], fill=INK)
    if 3.2 <= t < 3.75:                         # rewind arrows spinning around the face
        for i in range(3):
            a = -t * 14 + i * 2.1
            ax, ay = cx + r * 0.9 * math.cos(a), cy + r * 0.9 * math.sin(a)
            d.polygon([(k(ax), k(ay - 9)), (k(ax), k(ay + 9)), (k(ax - 14 * math.sin(a)), k(ay + 14 * math.cos(a)))], fill=(255, 214, 60))
    if 3.3 <= t < 4.4:                          # "FALL BACK" sign
        p = back_out(seg(t, 3.3, 3.55))
        f2 = ImageFont.truetype(mm.FONT, k(30 * p + 1))
        d.rounded_rectangle([k(cx - 84 * p), k(cy + r + 14), k(cx + 84 * p), k(cy + r + 14 + 46 * p)], k(12), fill=(140, 70, 220))
        d.text((k(cx), k(cy + r + 14 + 23 * p)), "FALL BACK", font=f2, fill=(255, 255, 255), anchor="mm")


def skull_piece(img, x, y, s=1.0):
    d = ImageDraw.Draw(img)
    r = 90 * s
    d.ellipse([k(x - r), k(y - r), k(x + r), k(y + r * 0.95)], fill=(240, 238, 228))
    d.rounded_rectangle([k(x - r * 0.54), k(y + r * 0.54), k(x + r * 0.54), k(y + r * 1.2)], k(14 * s), fill=(240, 238, 228))
    for sgn in (-1, 1):
        d.ellipse([k(x + sgn * r * 0.43 - r * 0.33), k(y - r * 0.47), k(x + sgn * r * 0.43 + r * 0.33), k(y + r * 0.19)], fill=INK)
    d.ellipse([k(x - r * 0.17), k(y + r * 0.07), k(x + r * 0.17), k(y + r * 0.5)], fill=(120, 110, 100))


def ears_piece(img, x, y, s=1.0):
    d = ImageDraw.Draw(img)
    w = 95 * s
    d.rounded_rectangle([k(x - w), k(y - 20 * s), k(x + w), k(y + 18 * s)], k(12 * s), fill=INK)
    for sgn in (-1, 1):
        ex = x + sgn * 51 * s
        d.polygon([(k(ex - 42 * s), k(y - 8 * s)), (k(ex + 42 * s), k(y - 8 * s)), (k(ex + sgn * 10 * s), k(y - 100 * s))], fill=INK)
        d.polygon([(k(ex - 22 * s), k(y - 16 * s)), (k(ex + 22 * s), k(y - 16 * s)), (k(ex + sgn * 8 * s), k(y - 72 * s))], fill=(255, 170, 200))


def fly(a, b, p, lift=260):
    """Arc from a to b."""
    return a[0] + (b[0] - a[0]) * p, a[1] + (b[1] - a[1]) * p - lift * math.sin(math.pi * p)


def confetti(img, t):
    if t < 5.4:
        return
    d = ImageDraw.Draw(img)
    rnd = random.Random(4)
    for n in range(90):
        x0, sp, start = rnd.uniform(0, W), rnd.uniform(380, 620), 5.4 + rnd.uniform(0, 1.2)
        if t < start:
            continue
        age = t - start
        x = x0 + 40 * math.sin(age * 3 + n)
        y = -40 + age * sp
        if y > FL + 60:
            continue
        a = age * 6 + n
        w, h = 14 * abs(math.cos(a)) + 3, 9
        c = [(255, 150, 40), (180, 90, 255), (120, 255, 90), (255, 214, 60), (255, 92, 178)][n % 5]
        d.rectangle([k(x - w), k(y - h), k(x + w), k(y + h)], fill=c)


def story_frame(t):
    global ROOM
    if ROOM is None:
        ROOM = room(bucket=False)
    img = ROOM.copy()
    if t >= 5.4:                                # party lights: the room pulses orange / purple
        c = (255, 140, 40) if int(t * 4) % 2 else (170, 80, 255)
        img.alpha_composite(Image.new("RGBA", img.size, c + (int(26 + 12 * math.sin(t * 25)),)))
    wall_clock(img, t)
    blink = int(t * 10) % 37 == 0

    sad = t < 4.1
    mood = "sad" if sad else ("scared" if t < 4.45 else "happy")
    skull_on, ears_on = t >= SKULL_T[1], t >= EARS_T[1]
    look_up = 1 if 2.6 <= t < 4.4 else 0
    party = t >= 5.4
    hop_s = -60 * abs(math.sin(math.pi * (t - 5.4) * 2.4)) if party else 0
    hop_c = -60 * abs(math.sin(math.pi * (t - 5.4) * 2.4 + math.pi / 2)) if party else 0
    sigh = 1 - 0.03 * math.sin(t * 2.2) if sad else 1.0
    jump = -70 * math.sin(math.pi * seg(t, 4.1, 4.4)) if 4.1 <= t < 4.4 else 0
    pop_s = 1 + 0.12 * math.sin(math.pi * seg(t, SKULL_T[1], SKULL_T[1] + 0.25))
    pop_c = 1 + 0.12 * math.sin(math.pi * seg(t, EARS_T[1], EARS_T[1] + 0.25))

    sk, sfx, sfy = tube("skeleton", t, mood, look=look_up, blink=blink and mood != "happy", bare=not skull_on)
    ct, cfx, cfy = tube("cat", t, mood, look=-look_up, blink=blink and mood != "happy", bare=not ears_on)
    place(img, sk, sfx, sfy, SKEL_X, FL + jump + hop_s, squash=sigh * pop_s)
    place(img, ct, cfx, cfy, CAT_X, FL + jump + hop_c, squash=sigh * pop_c)

    # costume pieces: on the table, then flying back on
    if not skull_on:
        p = ease(seg(t, *SKULL_T))
        skull_piece(img, *fly(SKULL_AT, (SKEL_X, HEAD), p), 0.62 + 0.38 * p)
    if not ears_on:
        p = ease(seg(t, *EARS_T))
        ears_piece(img, *fly(EARS_AT, (CAT_X, EARS_ON), p), 0.62 + 0.38 * p)
    stars(img, SKEL_X, HEAD, seg(t, SKULL_T[1], SKULL_T[1] + 0.5), n=7, spread=150)
    stars(img, CAT_X, EARS_ON, seg(t, EARS_T[1], EARS_T[1] + 0.5), n=7, spread=150)
    exclaim(img, SKEL_X + 40, FL - 780, 4.1, t, 0.45)
    exclaim(img, CAT_X - 40, FL - 780, 4.1, t, 0.45)
    confetti(img, t)

    img = camera(img, *cam_at(t, CAM))
    caption(img, "Nov 1, 1:59 AM...\nHalloween is over", 250, 0.2, 2.6, t)
    caption(img, "Clocks fall back 1 hour...", 250, 3.25, 4.4, t, size=70)
    caption(img, "...ONE MORE HOUR\nOF HALLOWEEN!", 260, 4.45, 7.9, t, size=96)
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
        base = fizz_frame(t, story_frame(Z0), z0=Z0, tr=TR, focus=(CAT_X + 6, FL - 175 * CS), liquid="green")
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
        for s in (1.0, 2.9, 3.1, 3.5, 3.9, 4.3, 4.9, 5.2, 5.6, 6.5, 7.6, 8.2):
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
