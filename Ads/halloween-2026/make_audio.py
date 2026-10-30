"""Sound for the Halloween reels: synthesized cartoon SFX timed to each render script, the game's own sounds under
the gameplay, plus music.

    python3 make_audio.py <reel>.mp4 ad105-tue-trick-or-treat-spooky-dark.mp4 [music.mp3 [start_seconds [tempo]]]
Writes <reel>-sound.mp4 (video stream copied, AAC audio, loudness-normalised for social). The cue list is picked from
the video's name (mirror-maze, last-candy or pumpkin). Both reels use ad105's gameplay, whose audio from 6 s on is only game
sounds (pours, combo), so that audio is laid in under our gameplay at the bubble transition, in sync with the footage.
"""
import os
import subprocess
import sys
import wave

import numpy as np

TD = 0.85             # bubble transition length (render_mirror_maze.TD)
GAME_END = 10.0       # ad105's end-card music starts ~10.0 s; its gameplay audio before that is only game sounds

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


def dun(f, dur, vol=0.4):
    """Brassy 'dun' for the dun-dun-DUN reveal."""
    return tone((f, f * 0.98), dur, dur * 0.6, ((1, 1.0), (2, 0.6), (3, 0.4), (4, 0.25), (5, 0.15))) * vol


def thump():
    """Spotlight switching on."""
    return tone((90, 45), 0.25, 0.08) * 0.6 + np.concatenate([noise(0.03, 2) * 0.2, np.zeros(int(0.22 * SR))])[: int(0.25 * SR)]


def laugh(n=6):
    out = np.zeros(int((0.13 * n + 0.2) * SR))
    for i in range(n):
        mix_into(out, tone((560 - i * 30, 480 - i * 30), 0.11, 0.05, ((1, 1.0), (2, 0.5), (3, 0.2))) * 0.3, int(i * 0.13 * SR))
    return out


def mix_into(out, clip, at):
    at = max(0, at)
    end = min(len(out), at + len(clip))
    if end > at:
        out[at:end] += clip[: end - at]
    return out


def transition_and_card(put, tr, gp_in=6.0):
    """Bubble transition rush; the gameplay itself gets ad105's real game sounds (see main); end-card chime."""
    put(whoosh(1.0) * 0.8, tr - 0.05)
    for i in range(36):
        put(blip(rng.uniform(350, 1100)), tr + rng.uniform(0, 0.6))
    put(chime((1318.5, 1568.0, 2093.0), 0.09, 0.25), tr + 10.65 - gp_in)   # ad105 gameplay ends at 10.6 s


def zoom_fizz(put, z0):
    """Whoosh into the liquid + fizz."""
    put(whoosh(0.8), z0 - 0.05)
    fizz = np.diff(noise(0.5), prepend=0) * 0.04
    crack = (rng.random(len(fizz)) < 0.0025) * rng.uniform(-0.5, 0.5, len(fizz))
    put((fizz + crack) * np.sin(np.linspace(0, np.pi, len(fizz))) ** 0.5, z0 + 0.4)
    for i in range(4):
        put(blip(rng.uniform(300, 700)), z0 + 0.5 + i * 0.09)


def build_last_candy(total, z0=9.6):
    """Cues for render_last_candy.py (video time, after the 2 s "Not me!" cut)."""
    tr = z0 + 0.45
    out = np.zeros(int(total * SR) + SR)

    def put(clip, t):
        mix_into(out, clip, int(t * SR))

    for i in range(4):                       # skeleton walks in
        put(step(), 0.3 + i * 0.278)
    put(stinger(), 1.65)                     # the bowl is empty!
    put(boing(), 1.72)
    for i in range(4):                       # cat strolls in (no whistle sound: Guy, Oct 30)
        put(step(0.9), 2.7 + i * 0.3125)
    put(thump(), 4.4)                        # spotlight on the cat
    put(pop(1100), 4.65)                     # "Wasn't me!"
    put(dun(110, 0.22), 6.5)                 # dun... dun... DUN: the wrapper
    put(dun(104, 0.22), 6.8)
    put(dun(98, 0.9, 0.5), 7.1)
    put(chime((1568.0, 2093.0, 2637.0), 0.06, 0.18), 7.0)    # wrapper sparkle
    put(stinger(), 7.98)                     # CAUGHT!
    put(boing(), 8.02)
    put(pop(520) * 1.4, 8.72)                # cork!
    put(chime((1318.5, 1568.0, 2093.0), 0.05, 0.2), 8.78)
    put(laugh(), 8.85)                       # skeleton laughs
    zoom_fizz(put, z0)
    transition_and_card(put, tr, 6.45)
    return out[: int(total * SR)]


def build_mirror_maze(total, tr=11.6):
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
    zoom_fizz(put, 11.2)
    transition_and_card(put, tr)
    return out[: int(total * SR)]


def scrape():
    """Knife scraping pumpkin."""
    n = int(0.12 * SR)
    x = np.diff(noise(0.12, 4), prepend=0) * np.sin(np.linspace(0, np.pi, n)) * 0.25
    return x


def build_pumpkin(total, z0=9.4):
    """Cues for render_pumpkin.py."""
    tr = z0 + 0.45
    out = np.zeros(int(total * SR) + SR)

    def put(clip, t):
        mix_into(out, clip, int(t * SR))

    for i in range(13):                      # carving
        put(scrape(), 0.42 + i * 0.15)
        if i % 2:
            put(pop(rng.uniform(700, 1000)) * 0.5, 0.5 + i * 0.15)
    put(chime((1046.5, 1318.5, 1568.0), 0.06, 0.22), 2.42)   # done!
    put(pop(1100), 3.0)                      # "Ready?"
    put(whoosh(0.6), 4.0)                    # spin them around
    put(thump(), 4.5)                        # candles on
    put(chime(), 4.55)                       # ta-da
    put(stinger(), 6.78)                     # wait... what?!
    put(boing(), 6.82)
    put(laugh(), 7.2)                        # both laugh
    put(laugh(5) * 0.8, 7.32)
    flick = np.diff(noise(0.6), prepend=0) * 0.05 * (rng.random(int(0.6 * SR)) < 0.02)
    put(flick, 8.4)                          # candles flicker...
    put(whoosh(0.5) * 0.7, 8.9)              # ...and go out
    zoom_fizz(put, z0)
    transition_and_card(put, tr, 6.45)
    return out[: int(total * SR)]


# cues, bubble transition start, where in ad105 the gameplay (and its game sounds) starts
REELS = {"mirror-maze": (build_mirror_maze, 11.6, 6.0), "last-candy": (build_last_candy, 10.05, 6.45),
         "pumpkin": (build_pumpkin, 9.85, 6.45)}


def main():
    video, game = sys.argv[1], sys.argv[2]
    music = sys.argv[3] if len(sys.argv) > 3 else None
    start = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0   # where in the music track the video begins;
    # negative = the music starts that many seconds into the video (e.g. to land a track's ending on the end card)
    tempo = float(sys.argv[5]) if len(sys.argv) > 5 else 1.0   # <1 slows the music (pitch kept) to move its ending later
    build, tr, gp_in = next(v for name, v in REELS.items() if name in os.path.basename(video))
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
    # the game's own sounds: ad105 audio from gp_in lands at the bubble transition, like its picture
    delay = int(tr * 1000)
    gfc = (f"[2:a]atrim={gp_in}:{GAME_END},asetpts=PTS-STARTPTS,aformat=channel_layouts=stereo,volume=10,"
           f"afade=t=out:st={GAME_END - gp_in - 0.3}:d=0.3,adelay={delay}|{delay},apad[g];"
           f"[1:a]aformat=channel_layouts=stereo[s];")
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", video, "-i", tmp, "-i", game]
    if music:
        cmd += ["-i", music]
        delay = int(-start * 1000) if start < 0 else 0
        fc = gfc + (f"[3:a]atrim={max(start, 0)}:{max(start, 0) + total * tempo},asetpts=PTS-STARTPTS,atempo={tempo},"
                    f"adelay={delay}|{delay},volume=0.45,afade=t=in:d=0.03,"
                    f"afade=t=out:st={total - 1.5}:d=1.5[m];[m][s][g]amix=inputs=3:normalize=0:duration=first,loudnorm=I=-14:TP=-1.5[a]")
    else:
        fc = gfc + "[s][g]amix=inputs=2:normalize=0:duration=first,loudnorm=I=-16:TP=-1.5[a]"
    cmd += ["-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-ar", "44100", "-shortest", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True)
    os.remove(tmp)
    print("wrote", out)


if __name__ == "__main__":
    main()
