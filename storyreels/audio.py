"""Procedural background scores per niche + SFX + voice mix.

myth    : tanpura drone, bansuri (flute) melody in a raga, soft pad, dhol on action
history : war-march score — nagada/tom drum ostinato, low brass chords, shehnai-like call, snare rolls on action
ghost   : wind, detuned tritone drone, music-box notes, glassy high tones, reverse swells, heartbeat on suspense
"""
import numpy as np, soundfile as sf

SR = 44100


def build_mix(total, voice_clips, intense_spans, booms, cuts, arrows, out_wav, seed=0, genre='myth'):
    rng = np.random.default_rng(seed)
    N = int(total * SR) + SR
    t = np.arange(N) / SR
    music = np.zeros(N); sfx = np.zeros(N); voice = np.zeros(N)
    fade = np.interp(t, [0, 2.5, total - 2, total], [0, 1, 1, 0])

    def add(buf, sig, at, g=1.0):
        i = max(0, int(at * SR)); j = min(N, i + len(sig))
        if j > i:
            buf[i:j] += g * sig[:j - i]

    def env_ad(n, att, dec):
        tt = np.arange(n) / SR
        return (1 - np.exp(-tt / max(att, 1e-4))) * np.exp(-tt / dec)

    def tone(f, dur, harm=(1,), att=0.01, dec=0.5, vib=0.0, vibf=5.0):
        n = int(dur * SR); tt = np.arange(n) / SR
        ph = 2 * np.pi * f * tt + ((vib * f / vibf) * np.sin(2 * np.pi * vibf * tt) if vib else 0)
        s = sum(a * np.sin(ph * (k + 1)) for k, a in enumerate(harm))
        return s * env_ad(n, att, dec)

    def noise(n, smooth=1):
        x = rng.standard_normal(n)
        return np.convolve(x, np.ones(smooth) / smooth, 'same') if smooth > 1 else x

    def drum(f0=150, f1=60, dec=0.32, nz=0.3):
        tt = np.arange(int(0.7 * SR)) / SR
        f = f1 + (f0 - f1) * np.exp(-tt * 25)
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / dec) + nz * rng.standard_normal(len(tt)) * np.exp(-tt * 60)

    intense = np.zeros(N)
    for a, b in intense_spans:
        intense[int(a * SR):int(b * SR)] = 1
    intense = np.convolve(intense, np.ones(SR) / SR, 'same')

    if genre == 'history':
        root = rng.choice([73.4, 77.8, 82.4])                     # D2 / Eb2 / E2
        minor = [0, 2, 3, 5, 7, 8, 10]
        prog = [(0, 3, 7), (8, 12, 15), (10, 14, 17), (0, 3, 7)]   # i - VI - VII - i, low brass
        bar = 60 / rng.uniform(84, 96) * 4
        at, k = 0.0, 0
        while at < total:
            for semi in prog[k % 4]:
                f = root * 2 * 2 ** (semi / 12)
                add(music, tone(f, bar + 0.5, harm=(1, .5, .33, .25, .2, .16), att=0.25, dec=bar * 1.5), at, 0.05)
            at += bar; k += 1
        beat = bar / 4                                               # nagada / tom march
        big, tom = drum(110, 50, 0.4), drum(220, 110, 0.18)
        sn_n = int(0.25 * SR); snare = noise(sn_n) * env_ad(sn_n, 0.001, 0.06)
        at, k = 0.5, 0
        while at < total - 1:
            it = intense[min(int(at * SR), N - 1)]
            lv = 0.18 + 0.25 * it
            if k % 4 == 0: add(music, big, at, lv * 1.4)
            if k % 4 == 2: add(music, tom, at, lv)
            if k % 8 == 7: add(music, tom, at + beat / 2, lv * 0.8)
            if it > 0.5:
                for r in range(4): add(music, snare, at + r * beat / 4, 0.12)
            at += beat; k += 1
        at = bar * 2                                                 # shehnai-like call
        while at < total - 3:
            for j, semi in enumerate(rng.choice(minor, 4)):
                f = root * 8 * 2 ** (semi / 12)
                add(music, tone(f, 0.6, harm=(1, .7, .5, .45, .3, .25), att=0.04, dec=0.5, vib=0.012, vibf=6), at + j * 0.35, 0.03)
            at += bar * int(rng.integers(2, 4))
    elif genre == 'ghost':
        Sa = rng.choice([98.0, 103.8, 110.0])
        w = noise(N, 40); w2 = noise(N, 400)                         # wind
        music += (w * 0.5 + w2 * 3) * (0.4 + 0.6 * np.sin(2 * np.pi * 0.07 * t) ** 2) * 0.05
        music += (np.sin(2 * np.pi * Sa / 2 * t) + 0.7 * np.sin(2 * np.pi * Sa / 2 * 1.008 * t) + 0.5 * np.sin(2 * np.pi * Sa * 2 ** (6 / 12) * t)) \
            * (0.5 + 0.5 * np.sin(2 * np.pi * 0.05 * t) ** 2) * (0.06 + 0.05 * intense)
        notes = [0, 3, 7, 12, 11, 7, 3, 2]                           # out-of-tune music box
        at, k = 1.5, 0
        while at < total - 1:
            f = Sa * 8 * 2 ** ((notes[k % len(notes)] + rng.uniform(-0.15, 0.15)) / 12)
            add(music, tone(f, 1.6, harm=(1, .3, .12), att=0.002, dec=0.6), at, 0.05)
            at += 0.55 if (k // 8) % 2 == 0 else 0.8; k += 1
            if k % 16 == 0: at += 2.5
        for _ in range(int(total / 5)):                              # glassy high tones
            add(music, tone(rng.uniform(1400, 2600), 3.0, harm=(1, .2), att=0.8, dec=1.2), rng.uniform(1, total - 3), 0.02)
        hb = drum(70, 40, 0.18, 0.1)                                 # heartbeat on suspense
        for a, b in intense_spans:
            at = a
            while at < b:
                add(music, hb, at, 0.5); add(music, hb, at + 0.28, 0.32); at += 60 / 66
        for c in cuts:                                               # reverse swells into each cut
            n = int(1.2 * SR)
            add(sfx, noise(n, 12) * np.linspace(0, 1, n) ** 3, c - 1.2, 0.18)
    else:  # myth
        Sa = rng.choice([130.8, 138.6, 146.8]); Pa = Sa * 1.5
        cyc = rng.uniform(2.2, 2.8)
        tan = {f: tone(f, 2.2, harm=tuple(1 / n for n in range(1, 12)), att=0.003, dec=0.9) for f in (Pa, Sa * 2, Sa)}
        for k, at in enumerate(np.arange(0, total, cyc / 4)):
            add(music, tan[[Pa, Sa * 2, Sa * 2, Sa][k % 4]], at, 0.07)
        music += (np.sin(2 * np.pi * Sa / 2 * t) + 0.5 * np.sin(2 * np.pi * Pa / 2 * t)) * (0.05 + 0.05 * intense)
        scale = [0, 2, 4, 7, 9, 12, 14, 16]                         # bansuri, raga Bhupali
        at, idx = 2.0, 2
        while at < total - 2:
            idx = int(np.clip(idx + rng.choice([-2, -1, 1, 1, 2]), 0, len(scale) - 1))
            dur = float(rng.choice([0.5, 0.75, 1.0, 1.5]))
            f = Sa * 4 * 2 ** (scale[idx] / 12)
            add(music, tone(f, dur + 0.6, harm=(1, .25, .08), att=0.08, dec=dur, vib=0.008, vibf=5.5), at, 0.05)
            n = int((dur + 0.3) * SR)
            add(music, noise(n, 3) * env_ad(n, 0.05, dur) * 0.15, at, 0.02)
            at += dur
            if rng.random() < 0.15: at += 1.5
        big, small = drum(150, 60, 0.3), drum(220, 80, 0.15)       # dhol on action
        pat = [1, 0, 0.6, 0.7, 0, 0.5, 1, 0]
        beat = 60 / rng.uniform(96, 112)
        for a, b in intense_spans:
            at, k = a, 0
            while at < b:
                v = pat[k % 8]
                if v: add(music, big if v > 0.8 else small, at, 0.35 * v)
                at += beat / 2; k += 1

    music *= fade

    def boom():
        tt = np.arange(int(2.5 * SR)) / SR
        f = 30 + 60 * np.exp(-tt * 4)
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 1.6) + 0.8 * noise(len(tt), 60) * np.exp(-tt * 2.5)
    for b in booms:
        add(sfx, boom(), b, 0.5 if genre != 'ghost' else 0.35)
    if genre != 'ghost':
        for c in cuts:
            n = int(0.4 * SR)
            add(sfx, noise(n, 8) * np.sin(np.pi * np.linspace(0, 1, n)) ** 2, c - 0.2, 0.12)
    for a in arrows:
        n = int(0.45 * SR); wv = noise(n); wv = wv - np.convolve(wv, np.ones(4) / 4, 'same')
        add(sfx, wv * np.linspace(0.2, 1, n), a, 0.10)
        add(sfx, drum(400, 200, 0.05), a + 0.45, 0.12)

    for path, st in voice_clips:
        v, _ = sf.read(path)
        add(voice, v, st)
    env = np.convolve(np.abs(voice), np.ones(4410) / 4410, 'same')
    duck = 1 - 0.5 * np.clip(env / 0.05, 0, 1)
    music = music / (np.max(np.abs(music)) + 1e-9) * 0.35
    mix = np.tanh((voice + music * duck + sfx * 0.8) * 1.1) * 0.9
    mix = mix[:int(total * SR)]
    sf.write(out_wav, np.stack([mix, mix], 1), SR)
