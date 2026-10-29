"""Sound for the Mirror Maze reel (ad107): synthesized cartoon SFX timed to render_mirror_maze.py, plus music.

    python3 make_audio.py ad107-mirror-maze.mp4 [music.mp3 [start_seconds]]
Writes ad107-mirror-maze-sound.mp4 (video stream copied, AAC audio, loudness-normalised for social).
Timings below follow the scene times in render_mirror_maze.py; gameplay pours were read off the ad105 footage.
"""
import os
import subprocess
import sys
import wave

import numpy as np

TR, TD = 11.6, 0.85   # bubble transition start + length, as in render_mirror_maze.py

SR = 44100
rng = np.random.default_rng(4)


def env(n, attack=0.005, release=None):
    t = np.arange(n) / SR
    a = np.clip(t / attack, 0, 1)
    r = np.exp(-t / release) if release else 1
    return a * r


def tone(freqs, dur, release, harmonics=((1, 1.0),)):
    """Sine sweep through freqs (start, end) with optional partials."""
    n = int(dur * SR)
    f = np.linspace(freqs[0], freqs[1], n)
    ph = 2 * np.pi * np.cumsum(f) / SR
    out = sum(a * np.sin(ph * h) for h, a in harmonics)
    return out * env(n, release=release)


def noise(dur, smooth=1):
    x = rng.standard_normal(int(dur * SR))
    if smooth > 1:
        x = np.convolve(x, np.ones(smooth) / smooth, mode="same")
    return x


def step(soft=1.0):
    click = noise(0.04, 3) * env(int(0.04 * SR), 0.001, 0.008) * 0.5
    wood = tone((900, 700), 0.06, 0.015) * 0.5
    return mix_into(wood, click, 0) * 0.35 * soft


def boing():
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    f = 180 + 420 * (1 - np.exp(-t * 9)) + 40 * np.sin(2 * np.pi * 14 * t)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.003, 0.16) * 0.55


def stinger():
    """Cartoon 'yikes!': fast slide whistle up + a little shaker hit."""
    slide = tone((500, 1900), 0.22, 0.2, ((1, 1.0), (2, 0.25))) * 0.4
    hiss = np.diff(noise(0.25), prepend=0) * env(int(0.25 * SR), 0.002, 0.05) * 0.18
    return mix_into(np.concatenate([slide, np.zeros(len(hiss))]), hiss, 0)


def whoosh(dur=0.6, up=True):
    n = int(dur * SR)
    x = noise(dur, 6)
    shape = np.sin(np.linspace(0, np.pi, n)) ** 2
    return x * shape * 0.35


def chime(notes=(1046.5, 1318.5, 1568.0, 2093.0), gap=0.07, vol=0.3):
    out = np.zeros(int((gap * len(notes) + 1.2) * SR))
    for i, f in enumerate(notes):
        b = tone((f, f), 1.0, 0.35, ((1, 1.0), (2.76, 0.25), (5.4, 0.08)))
        mix_into(out, b * vol, int(i * gap * SR))
    return out


def pop(f0=900):
    return tone((f0, f0 * 0.35), 0.07, 0.025) * 0.45


def blip(f0):
    return tone((f0, f0 * 2.4), 0.06, 0.03) * 0.22


def squish():
    return tone((320, 140), 0.3, 0.12, ((1, 1.0), (2, 0.3))) * 0.4


def glug():
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    am = 0.5 + 0.5 * np.sin(2 * np.pi * 16 * t)
    f = 170 + 60 * np.sin(2 * np.pi * 5 * t)
    g = np.sin(2 * np.pi * np.cumsum(f) / SR) * am * env(n, 0.02, 0.25) * 0.35
    for i in range(4):
        mix_into(g, blip(500 + 150 * i) * 0.6, int((0.05 + i * 0.08) * SR))
    return g


def ding(step_n):
    f = 880 * 2 ** (step_n / 12)
    return tone((f, f), 0.4, 0.14, ((1, 1.0), (2, 0.35), (3, 0.1))) * 0.28


def mix_into(out, clip, at):
    at = max(0, at)
    end = min(len(out), at + len(clip))
    if end > at:
        out[at:end] += clip[: end - at]
    return out


def build(total):
    out = np.zeros(int(total * SR) + SR)

    def put(clip, t):
        mix_into(out, clip, int(t * SR))

    # S1 skeleton tiptoes (walk phase t*1.6 -> a footstep every 0.3125 s), scare at 2.6
    for i in range(9):
        put(step(), 0.2 + i * 0.3125)
    put(stinger(), 2.55)
    put(boing(), 2.62)
    for i in range(6):                       # nervous quicker steps
        put(step(0.8), 3.25 + i * 0.22)
    # S2 cat creeps, ghostly reflection slides by, scare at 6.5
    for i in range(6):
        put(step(0.9), 4.75 + i * 0.3125)
    put(whoosh(0.8), 5.9)
    put(stinger(), 6.45)
    put(boing(), 6.5)
    for i in range(6):
        put(step(0.8), 7.1 + i * 0.2)
    # S3 approach, double startle, run, hug
    for i in range(3):
        put(step(0.9), 8.25 + i * 0.28)
    put(stinger(), 9.08)
    put(boing() * 0.8, 9.12)
    for i in range(4):                       # run to each other
        put(step(1.1), 9.6 + i * 0.12)
    put(squish(), 10.08)
    put(chime(), 10.12)                      # "aww"
    put(pop(1100), 10.15)                    # speech bubble pop-in
    for n in range(5):
        put(pop(1400 + n * 120) * 0.5, 10.1 + n * 0.19)
    # S4 zoom into the liquid + fizz
    put(whoosh(0.8), 11.15)
    fizz = np.diff(noise(0.5), prepend=0) * 0.04
    crack = (rng.random(len(fizz)) < 0.0025) * rng.uniform(-0.5, 0.5, len(fizz))
    put((fizz + crack) * np.sin(np.linspace(0, np.pi, len(fizz))) ** 0.5, 11.6)
    for i in range(4):
        put(blip(rng.uniform(300, 700)), 11.7 + i * 0.09)
    # S5 bubble transition: a rush of rising bubble blips
    put(whoosh(1.0) * 0.8, TR - 0.05)
    for i in range(36):
        put(blip(rng.uniform(350, 1100)), TR + rng.uniform(0, 0.6))
    # gameplay (TR+TD onwards = ad105 6.85-10.6; pours seen at ad105 7.2, 7.6, 8.2, 8.8, 9.4, 9.85): pour + combo ding on each pour
    for n, tp in enumerate([0.35, 0.75, 1.35, 1.95, 2.55, 3.0]):
        put(glug(), TR + TD + tp)
        put(ding(n), TR + TD + tp + 0.35)
    # end card
    put(chime((1318.5, 1568.0, 2093.0), 0.09, 0.25), TR + TD + 3.8)
    return out[: int(total * SR)]


def main():
    video = sys.argv[1]
    music = sys.argv[2] if len(sys.argv) > 2 else None
    start = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0   # where in the music track the video begins
    total = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video]))
    sfx = build(total)
    sfx = sfx / max(1e-6, np.abs(sfx).max()) * 0.9
    tmp = os.path.join(os.path.dirname(os.path.abspath(video)), "sfx.wav")
    with wave.open(tmp, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((sfx * 32767).astype(np.int16).tobytes())
    out = os.path.splitext(video)[0] + "-sound.mp4"
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", video, "-i", tmp]
    if music:
        cmd += ["-i", music]
        fc = (f"[2:a]atrim={start}:{start + total},asetpts=PTS-STARTPTS,volume=0.45,afade=t=in:d=0.03,afade=t=out:st={total - 1.5}:d=1.5[m];"
              f"[1:a]aformat=channel_layouts=stereo[s];[m][s]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5[a]")
    else:
        fc = "[1:a]aformat=channel_layouts=stereo,loudnorm=I=-16:TP=-1.5[a]"
    cmd += ["-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-ar", "44100", "-shortest", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True)
    os.remove(tmp)
    print("wrote", out)


if __name__ == "__main__":
    main()
