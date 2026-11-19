"""Procedural background score (tanpura drone, pad, dhol), SFX and voice mix."""
import numpy as np, soundfile as sf

SR = 44100


def build_mix(total, voice_clips, intense_spans, booms, cuts, arrows, out_wav, seed=0, genre='myth'):
    horror = genre == 'ghost'
    rng = np.random.default_rng(seed)
    N = int(total * SR) + SR
    t = np.arange(N) / SR
    music = np.zeros(N); sfx = np.zeros(N); voice = np.zeros(N)

    def add(buf, sig, at, g=1.0):
        i = max(0, int(at * SR)); j = min(N, i + len(sig))
        if j > i:
            buf[i:j] += g * sig[:j - i]

    def pluck(f, dur=2.2):
        tt = np.arange(int(dur * SR)) / SR
        s = sum((1 / n) * np.sin(2 * np.pi * f * n * tt + n) * (1 + 0.3 * np.sin(2 * np.pi * 0.7 * tt * n)) for n in range(1, 14))
        return s * np.exp(-tt * 1.6) * (1 - np.exp(-tt * 200))

    Sa = rng.choice([130.8, 138.6, 146.8, 123.5]) if not horror else rng.choice([98.0, 103.8, 110.0]); Pa = Sa * 0.75
    cyc = rng.uniform(2.2, 2.8) if not horror else rng.uniform(4.5, 6.0)
    notes = [Pa * 2, Sa * 2, Sa * 2, Sa] if not horror else [Sa * 2, Sa * 2 ** (6 / 12) * 2, Sa * 2 ** (1 / 12) * 2, Sa]
    plucks = {n: pluck(n) for n in set(notes)}
    at, k = 0.0, 0
    while at < total:
        add(music, plucks[notes[k % 4]], at, 0.12); at += cyc / 4; k += 1

    intense = np.zeros(N)
    for a, b in intense_spans:
        intense[int(a * SR):int(b * SR)] = 1
    intense = np.convolve(intense, np.ones(SR) / SR, 'same')
    if horror:   # detuned tritone drone + slow swell
        pad = (np.sin(2 * np.pi * Sa / 2 * t) + 0.7 * np.sin(2 * np.pi * Sa / 2 * 1.007 * t) + 0.5 * np.sin(2 * np.pi * Sa * 2 ** (6 / 12) * t)
               + 0.25 * np.sin(2 * np.pi * Sa * 4.02 * t)) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.06 * t) ** 2)
    else:
        pad = (np.sin(2 * np.pi * Sa / 2 * t) + 0.6 * np.sin(2 * np.pi * Pa * t) + 0.4 * np.sin(2 * np.pi * Sa * 1.2 * t + 1)) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.1 * t))
    fade = np.interp(t, [0, 3, total - 2, total], [0, 1, 1, 0])
    music += pad * (0.09 + 0.07 * intense) * fade

    def dhol(f0=150, dec=0.32):
        tt = np.arange(int(0.6 * SR)) / SR
        f = 60 + (f0 - 60) * np.exp(-tt * 25)
        s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / dec)
        return s + 0.3 * rng.standard_normal(len(tt)) * np.exp(-tt * 60)
    beat = 60 / rng.uniform(96, 112)
    pat = [1, 0, 0.6, 0.7, 0, 0.5, 1, 0]
    big, small = dhol(150, 0.3), dhol(220, 0.15)
    for a, b in intense_spans:
        at, k = a, 0
        if horror:   # heartbeat instead of dhol
            hb = dhol(70, 0.18)
            while at < b:
                add(music, hb, at, 0.45); add(music, hb, at + 0.28, 0.3); at += 60 / 66
            continue
        while at < b:
            v = pat[k % 8]
            if v:
                add(music, big if v > 0.8 else small, at, 0.35 * v)
            at += beat / 2; k += 1

    def boom():
        tt = np.arange(int(2.5 * SR)) / SR
        f = 30 + 60 * np.exp(-tt * 4)
        s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 1.6)
        n = np.convolve(rng.standard_normal(len(tt)), np.ones(60) / 60, 'same')
        return s + 0.8 * n * np.exp(-tt * 2.5)
    for b in booms:
        add(sfx, boom(), b, 0.55)

    def whoosh(d=0.4):
        n = np.convolve(rng.standard_normal(int(d * SR)), np.ones(8) / 8, 'same')
        return n * np.sin(np.pi * np.linspace(0, 1, len(n))) ** 2
    for c in cuts:
        add(sfx, whoosh(), c - 0.2, 0.12)
    for a in arrows:
        w = rng.standard_normal(int(0.45 * SR)); w = w - np.convolve(w, np.ones(4) / 4, 'same')
        add(sfx, w * np.linspace(0.2, 1, len(w)), a, 0.10)
        add(sfx, dhol(400, 0.05), a + 0.45, 0.12)

    for path, st in voice_clips:
        v, _ = sf.read(path)
        add(voice, v, st)
    env = np.convolve(np.abs(voice), np.ones(4410) / 4410, 'same')
    duck = 1 - 0.55 * np.clip(env / 0.05, 0, 1)
    mix = np.tanh((voice + music * duck * 0.8 + sfx * 0.8) * 1.1) * 0.9
    mix = mix[:int(total * SR)]
    sf.write(out_wav, np.stack([mix, mix], 1), SR)
