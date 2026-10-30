"""Beaker Lab Halloween reel "Who ate the last candy?": 1080x1920, 30 fps, ~19.2 s.

Story (Guy, Oct 30): the candy bowl is empty. Spotlight on the green cat beaker (whistling, "Wasn't me"), but a
candy wrapper is stuck to the cat's tail. Caught, the cat corks
itself out of embarrassment while the skeleton laughs. Zoom into the cat's liquid, the game's bubble transition,
ad105 gameplay (with its own game sounds, see make_audio.py), ad105 end card.

Reuses the characters, liquid zoom and bubble transition from render_mirror_maze.py:
    python3 render_last_candy.py /path/to/ad105-tue-trick-or-treat-spooky-dark.mp4 [--stills[-only]]
"""
import math
import os
import random
import subprocess
import sys
import tempfile
from multiprocessing import Pool

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import render_mirror_maze as mm
from render_mirror_maze import (CS, H, INK, W, bubble_reveal, caption, ease, exclaim, fizz_frame, k, mix, place,
                                seg, speech, tube)

OUT = os.path.join(mm.HERE, "last-candy.mp4")
FPS = 60                                   # smoother than the 30 fps mirror maze; ad105 footage is frame-doubled
NOTE_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

FL = 1690                                  # floor line the beakers stand on
SKEL_X, CAT_X = 230, 850
CUT_AT, CUT_LEN = 4.4, 2.0                 # story 4.4-6.4 s (the skeleton's "Not me!") was cut (Guy, Oct 30)
Z0 = 11.6 - CUT_LEN                        # zoom into the cat's liquid starts (video time)
TR = Z0 + 0.45                             # bubble transition starts
TD = mm.TD
ANIM_END = TR + TD
WRAP = (CAT_X - 176, FL - 385)             # the wrapper on the cat's tail (cat is flipped: tail points at the bowl)


# ---------------------------------------------------------------- set
def room():
    """Cosy Halloween living room at night: purple walls, moonlit window, string lights, table with the candy bucket."""
    bg = Image.new("RGBA", (k(W), k(H)))
    d = ImageDraw.Draw(bg)
    for y in range(0, k(H), 2):
        d.line([(0, y), (k(W), y)], fill=mix((58, 30, 88), (30, 16, 50), y / k(H)) + (255,), width=2)
    # window with moon
    wx0, wy0, wx1, wy1 = 600, 300, 960, 760
    d.rounded_rectangle([k(wx0), k(wy0), k(wx1), k(wy1)], k(18), fill=(16, 12, 42, 255))
    rnd = random.Random(2)
    for _ in range(30):
        x, y, r = rnd.uniform(wx0 + 20, wx1 - 20), rnd.uniform(wy0 + 20, wy1 - 20), rnd.uniform(1.5, 3.5)
        d.ellipse([k(x - r), k(y - r), k(x + r), k(y + r)], fill=(255, 248, 220, 255))
    glow = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([k(700), k(360), k(900), k(560)], fill=(255, 240, 190, 120))
    bg.alpha_composite(glow.filter(ImageFilter.GaussianBlur(k(30))))
    d.ellipse([k(740), k(400), k(860), k(520)], fill=(255, 246, 210, 255))
    d.rounded_rectangle([k(wx0), k(wy0), k(wx1), k(wy1)], k(18), outline=(110, 70, 140, 255), width=k(16))
    d.line([(k((wx0 + wx1) / 2), k(wy0)), (k((wx0 + wx1) / 2), k(wy1))], fill=(110, 70, 140, 255), width=k(12))
    d.line([(k(wx0), k((wy0 + wy1) / 2)), (k(wx1), k((wy0 + wy1) / 2))], fill=(110, 70, 140, 255), width=k(12))
    # ghost painting
    d.rounded_rectangle([k(120), k(420), k(400), k(700)], k(8), fill=(200, 150, 60, 255))
    d.rectangle([k(140), k(440), k(380), k(680)], fill=(40, 30, 70, 255))
    d.chord([k(200), k(480), k(320), k(600)], 180, 360, fill=(240, 240, 255, 255))
    d.rectangle([k(200), k(540), k(320), k(640)], fill=(240, 240, 255, 255))
    for i in range(4):
        d.pieslice([k(200 + i * 30), k(625), k(230 + i * 30), k(655)], 0, 180, fill=(240, 240, 255, 255))
    d.ellipse([k(232), k(530), k(248), k(550)], fill=INK + (255,))
    d.ellipse([k(272), k(530), k(288), k(550)], fill=INK + (255,))
    # string lights sagging across the top
    pts = [(x, 150 + 70 * math.sin(math.pi * x / W)) for x in range(-20, W + 40, 20)]
    d.line([(k(x), k(y)) for x, y in pts], fill=(30, 20, 40, 255), width=k(4))
    for i, (x, y) in enumerate(pts[::3]):
        c = [(255, 150, 40), (180, 90, 255), (120, 255, 90)][i % 3]
        d.ellipse([k(x - 11), k(y + 4), k(x + 11), k(y + 30)], fill=c + (255,))
    # floor
    d.rectangle([0, k(1560), k(W), k(H)], fill=(44, 24, 40, 255))
    for i in range(10):
        y = 1580 + i * i * 4
        d.line([(0, k(y)), (k(W), k(y))], fill=(62, 36, 56, 255), width=k(3))
    d.ellipse([k(160), k(1630), k(920), k(1780)], fill=(96, 40, 90, 255))    # rug
    # table
    d.rectangle([k(370), k(1360), k(390), k(FL - 10)], fill=(90, 50, 40, 255))
    d.rectangle([k(690), k(1360), k(710), k(FL - 10)], fill=(90, 50, 40, 255))
    d.rounded_rectangle([k(330), k(1330), k(750), k(1370)], k(12), fill=(130, 76, 56, 255))
    # jack-o'-lantern candy bucket (empty)
    bx, by = 540, 1330
    d.arc([k(bx - 95), k(by - 260), k(bx + 95), k(by - 90)], 190, 350, fill=INK + (255,), width=k(8))   # handle
    d.ellipse([k(bx - 115), k(by - 170), k(bx + 115), k(by)], fill=(240, 120, 24, 255))
    d.ellipse([k(bx - 95), k(by - 175), k(bx + 95), k(by - 135)], fill=(40, 20, 10, 255))               # empty inside
    for sgn in (-1, 1):
        ex = bx + sgn * 45
        d.polygon([(k(ex - 20), k(by - 70)), (k(ex + 20), k(by - 70)), (k(ex), k(by - 100))], fill=(60, 26, 6, 255))
    d.chord([k(bx - 55), k(by - 60), k(bx + 55), k(by - 10)], 0, 180, fill=(60, 26, 6, 255))
    return bg


ROOM = None


def camera(img, cx, cy, z):
    """Frame (cx, cy) at zoom z and scale back to full frame (1x coords). Float crop box, so slow moves don't jitter."""
    if z <= 1.001:
        return img
    cw, ch = W / z, H / z
    x0 = min(max(cx - cw / 2, 0), W - cw)
    y0 = min(max(cy - ch / 2, 0), H - ch)
    return img.resize(img.size, Image.BICUBIC, box=(k(x0), k(y0), k(x0 + cw), k(y0 + ch)))


# camera keyframes in story time: (t, centre x, centre y, zoom); eased glides between them, no hard cuts
WIDE = (W / 2, H / 2, 1.0)
CAM = [(6.4, *WIDE), (7.1, CAT_X, FL - 420, 1.45), (8.4, CAT_X, FL - 420, 1.45), (9.1, *WRAP, 3.2),
       (9.85, *WRAP, 3.2), (10.35, *WIDE)]


def cam_at(t):
    if t <= CAM[0][0] or t >= CAM[-1][0]:
        return WIDE
    for (t0, x0, y0, z0), (t1, x1, y1, z1) in zip(CAM, CAM[1:]):
        if t0 <= t < t1:
            p = ease(seg(t, t0, t1))
            return x0 + (x1 - x0) * p, y0 + (y1 - y0) * p, z0 * (z1 / z0) ** p    # zoom eases in log space


def spotlight(img, x, on):
    """Darken the room except a pool of light (and its cone) on the beaker at x."""
    if on <= 0:
        return
    s = 4
    m = Image.new("L", (k(W) // s, k(H) // s), int(200 * on))
    md = ImageDraw.Draw(m)
    md.polygon([(k(x - 70) / s, 0), (k(x + 70) / s, 0), (k(x + 260) / s, k(FL) / s), (k(x - 260) / s, k(FL) / s)], fill=int(120 * on))
    md.ellipse([k(x - 250) / s, k(FL - 760) / s, k(x + 250) / s, k(FL + 60) / s], fill=0)
    m = m.filter(ImageFilter.GaussianBlur(10)).resize(img.size, Image.BILINEAR)
    dark = Image.new("RGBA", img.size, (8, 4, 16, 255))
    dark.putalpha(m)
    img.alpha_composite(dark)


def notes(img, x, y, t, t0, t1):
    """Whistled music notes drifting up from the cat."""
    if not (t0 <= t < t1):
        return
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(NOTE_FONT, k(64))
    for n in range(4):
        ph = ((t - t0) * 0.9 + n * 0.25) % 1
        nx = x + 40 + 120 * ph + 20 * math.sin(ph * 9 + n)
        ny = y - 260 * ph
        a = int(255 * min(1, 4 * (1 - ph)))
        d.text((k(nx), k(ny)), "♪" if n % 2 else "♫", font=f, fill=(255, 236, 140, a), anchor="mm", stroke_width=k(3), stroke_fill=INK + (a,))


def cork(img, x, p):
    """The cat corks itself: a cork drops onto its rim (p 0..1)."""
    if p <= 0:
        return
    d = ImageDraw.Draw(img)
    ry = FL - 316 * CS
    cy = ry - 500 * (1 - p)
    d.rounded_rectangle([k(x - 84), k(cy - 70), k(x + 84), k(cy + 14)], k(16), fill=(196, 140, 84))
    for i in range(5):
        dx = x - 56 + i * 28
        d.ellipse([k(dx - 5), k(cy - 40), k(dx + 5), k(cy - 30)], fill=(150, 100, 56))
    d.rounded_rectangle([k(x - 84), k(cy - 70), k(x + 84), k(cy - 52)], k(9), fill=(220, 170, 110))


def stars(img, x, y, p, n=8, spread=200):
    if not (0 < p < 1):
        return
    d = ImageDraw.Draw(img)
    for i in range(n):
        a = i * 2 * math.pi / n
        sx, sy = x + math.cos(a) * spread * p, y + math.sin(a) * spread * 0.7 * p
        r = 26 * (1 - p * 0.6)
        pts = []
        for j in range(8):
            rr = r if j % 2 == 0 else r * 0.35
            b = math.radians(j * 45 - 90)
            pts.append((k(sx + rr * math.cos(b)), k(sy + rr * math.sin(b))))
        d.polygon(pts, fill=(255, 236, 120))


# ---------------------------------------------------------------- the story
def story_frame(t):
    """t is story time (before the cut)."""
    global ROOM
    if ROOM is None:
        ROOM = room()
    img = ROOM.copy()
    blink = int(t * 10) % 37 == 0

    # skeleton: walks in, finds the bowl empty (startle 1.7), shakes head in its spotlight, laughs at the end
    sx = -150 + (SKEL_X + 150) * ease(seg(t, 0.2, 1.4))
    s_walk = t * 1.8 if 0.2 < t < 1.4 else 0
    s_mood, s_look, s_tilt, s_jump, s_sq = "calm", 1, 0.0, 0.0, 1.0
    if 1.7 <= t < 2.6:
        s_mood = "scared"
        s_jump = -80 * math.sin(math.pi * seg(t, 1.7, 2.0)) if t < 2.0 else 0
    if 10.0 <= t < 10.8:
        s_mood = "scared"
    if t >= 10.8:                                              # laughing
        s_mood = "happy"
        s_sq = 1 + 0.06 * math.sin(t * 40)
        s_jump = -12 * abs(math.sin(t * 20))
    sk, sfx, sfy = tube("skeleton", t, s_mood, s_walk, look=s_look, blink=blink and s_mood == "calm")

    # cat: strolls in whistling (wrapper on its tail), whistles in its spotlight, caught, corks itself
    cx = 1250 - (1250 - CAT_X) * ease(seg(t, 2.6, 3.8))
    c_walk = (t - 2.6) * 1.6 if 2.6 < t < 3.8 else 0
    c_mood, c_blush, c_jump = "whistle", False, 0.0
    if t < 2.6:
        cx = 1400                                              # off stage
    if 10.0 <= t < 10.5:
        c_mood, c_blush = "scared", True
        c_jump = -60 * math.sin(math.pi * seg(t, 10.0, 10.25)) if t < 10.25 else 0
    elif t >= 10.5:
        c_mood, c_blush = "happy", True                        # sheepish grin under the cork
    ct, cfx, cfy = tube("cat", t, c_mood, c_walk, look=1, blink=False, wrapper=True, blush=c_blush)

    place(img, sk, sfx, sfy, sx, FL + s_jump, tilt=s_tilt, squash=s_sq)
    place(img, ct, cfx, cfy, cx, FL + c_jump, flip=True)
    cork(img, cx, ease(seg(t, 10.5, 10.75)))
    stars(img, cx, FL - 560, seg(t, 10.75, 11.35))
    notes(img, cx, FL - 360, t, 2.8, 4.4)
    notes(img, cx, FL - 360, t, 6.5, 8.4)
    exclaim(img, sx + 40, FL - 780, 1.7, t)
    exclaim(img, sx + 40, FL - 780, 10.0, t, 0.6)

    # spotlights
    spotlight(img, CAT_X, ease(seg(t, 6.4, 6.9)) * (1 - ease(seg(t, 8.8, 9.4))))
    speech(img, "Wasn't me!", CAT_X - 90, FL - 860, 6.65, t, emoji="\U0001f607") if 6.65 <= t < 8.5 else None

    # wrapper sparkle while the camera finds it
    if 8.8 <= t < 10.0:
        d = ImageDraw.Draw(img)
        for i in range(4):
            a = t * 3 + i * math.pi / 2
            r = 18 + 6 * math.sin(t * 12 + i)
            x, y = WRAP[0] + 70 * math.cos(a), WRAP[1] + 50 * math.sin(a)
            d.polygon([(k(x), k(y - r)), (k(x + r * 0.3), k(y)), (k(x), k(y + r)), (k(x - r * 0.3), k(y))], fill=(255, 250, 200))
            d.polygon([(k(x - r), k(y)), (k(x), k(y + r * 0.3)), (k(x + r), k(y)), (k(x), k(y - r * 0.3))], fill=(255, 250, 200))

    # camera
    img = camera(img, *cam_at(t))

    # captions (drawn after the camera so they stay put)
    caption(img, "Someone ate the\nlast candy...", 250, 0.2, 4.3, t)
    caption(img, "...then what's THAT?", 250, 8.7, 10.0, t)
    caption(img, "CAUGHT!", 300, 10.0, 11.0, t, size=150)
    caption(img, "Busted.", 280, 11.0, 11.6, t, size=90)
    return img


def frame(i, gp_frames):
    t = i / FPS
    if t < Z0:
        img = story_frame(t if t < CUT_AT else t + CUT_LEN)
    else:
        base = fizz_frame(t, story_frame(Z0 + CUT_LEN), z0=Z0, tr=TR, focus=(CAT_X - 6, FL - 175 * CS))
        if t < TR:
            img = base
        else:
            g = min(int((t - TR) * FPS), len(gp_frames) - 1)
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
    subprocess.run(["ffmpeg", "-v", "error", "-ss", str(mm.GP_IN), "-i", src, "-t", str(TD), "-vf", f"fps={FPS}",
                    os.path.join(tmp, "gp%03d.png")], check=True)
    gp = sorted(os.path.join(tmp, f) for f in os.listdir(tmp) if f.startswith("gp"))
    if any(a.startswith("--stills") for a in sys.argv):
        _init(gp)
        for s in (1.0, 1.85, 3.4, 4.6, 5.2, 7.3, 8.2, 9.2, 9.9, 10.4):
            frame(int(s * FPS), _GP).save(os.path.join(os.getcwd(), f"still-{s:04.1f}s.png"))
        if "--stills-only" in sys.argv:
            return
    anim = os.path.join(tmp, "anim.mp4")
    ff = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                           "-i", "-", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", anim], stdin=subprocess.PIPE)
    with Pool(initializer=_init, initargs=(gp,)) as pool:
        for b in pool.imap(_render, range(int(ANIM_END * FPS)), chunksize=3):
            ff.stdin.write(b)
    ff.stdin.close()
    ff.wait()
    gp_rest = mm.GP_IN + TD
    fc = (f"[0:v]setpts=PTS-STARTPTS[a];"
          f"[1:v]trim={gp_rest}:{mm.GP_OUT},setpts=PTS-STARTPTS[g];"
          f"[1:v]trim={mm.CARD_IN}:{mm.CARD_OUT},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={mm.CARD_HOLD}[c];"
          f"[a][g][c]concat=n=3:v=1:a=0[v]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", anim, "-i", src, "-filter_complex", fc, "-map", "[v]",
                    "-c:v", "libx264", "-crf", "19", "-preset", "slow", "-pix_fmt", "yuv420p", "-r", str(FPS),
                    "-movflags", "+faststart", OUT], check=True)
    total = ANIM_END + (mm.GP_OUT - gp_rest) + (mm.CARD_OUT - mm.CARD_IN) + mm.CARD_HOLD
    print(f"wrote {OUT} ({total:.1f} s)")


if __name__ == "__main__":
    main()
