"""Render an episode JSON into a 9:16 MP4 with voices, captions, music."""
import os, math, random, subprocess, json, multiprocessing as mp
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from . import art, tts, audio
from .art import W, H, K, OW, OH, GOLD, GOLD_L, WHITE

FPS = 30
FONT = os.environ.get('FONT_SANS', '/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf')
SERIF = os.environ.get('FONT_SERIF', '/usr/share/fonts/truetype/noto/NotoSerifDevanagari-Bold.ttf')
NARRATOR = {'name': 'सूत्रधार', 'voice': 'narrator'}

_fonts = {}


def font(path, size):
    k = (path, size)
    if k not in _fonts:
        _fonts[k] = ImageFont.truetype(path, size * K, layout_engine=ImageFont.Layout.RAQM)
    return _fonts[k]


def parse_words(txt):
    out, gold = [], False
    for w in txt.split():
        g = False
        for ch in w:
            if ch == '*':
                gold = not gold; g = g or gold
            elif gold:
                g = True
        if w.replace('*', ''):
            out.append((w.replace('*', ''), g))
    return out


def layout(d, words, f, maxw):
    maxw = maxw * K
    space = d.textlength(' ', font=f)
    lines, cur, cw = [], [], 0
    for wi, (w, g) in enumerate(words):
        ww = d.textlength(w, font=f)
        if cur and cw + space + ww > maxw:
            lines.append((cur, cw)); cur, cw = [], 0
        cur.append((wi, w, g, ww)); cw += (space if len(cur) > 1 else 0) + ww
    if cur:
        lines.append((cur, cw))
    return lines, space


def draw_words(d, lines, space, f, y0, lh, nwords, stroke=3):
    for li, (ws, lwid) in enumerate(lines):
        x = (OW - lwid) / 2; y = (y0 + li * lh) * K
        for wi, w, g, ww in ws:
            if wi < nwords:
                d.text((x + 2 * K, y + 3 * K), w, font=f, fill=(0, 0, 0, 160))
                d.text((x, y), w, font=f, fill=(GOLD_L if g else WHITE) + (255,), stroke_width=stroke * K, stroke_fill=(0, 0, 0, 255))
            x += ww + space


def crop(lay):
    bb = lay.getbbox()
    if not bb:
        return (Image.new('RGBA', (1, 1), (0, 0, 0, 0)), (0, 0))
    return (lay.crop(bb), bb[:2])


def comp(im, layer):
    img, off = layer
    im.alpha_composite(img, off)


class Episode:
    def __init__(self, ep, workdir):
        self.ep = ep; self.wd = workdir
        os.makedirs(workdir, exist_ok=True)
        self.chars = {k: dict(v) for k, v in ep.get('characters', {}).items()}
        self.params = {k: art.char_params(v) for k, v in self.chars.items()}
        main = ep.get('main_character') or (next(iter(self.chars)) if self.chars else None)
        # line list: hook, scenes, cliffhanger
        L = [dict(speaker='narrator', text=ep['hook'], shot=dict(type='hook', bg=ep.get('hook_bg', 'battlefield'), char=main))]
        for s in ep['scenes']:
            L.append(dict(speaker=s.get('speaker', 'narrator'), text=s['text'], shot=self.fix_shot(s.get('shot', {}), s)))
        cl = ep.get('cliffhanger', {})
        L.append(dict(speaker='narrator', text=cl.get('text', 'अगले भाग में...'), shot=dict(type='end', card=cl.get('card', ''))))
        self.lines = L

    def fix_shot(self, sh, scene):
        sh = dict(sh)
        t = sh.get('type', 'bust')
        if t not in ('bust', 'wide', 'symbol'):
            t = 'bust'
        sh['type'] = t
        if sh.get('bg') not in art.BACKGROUNDS:
            sh['bg'] = 'battlefield' if t != 'bust' else 'palace_red'
        if t == 'bust':
            if sh.get('char') not in self.chars:
                sp = scene.get('speaker')
                sh['char'] = sp if sp in self.chars else next(iter(self.chars))
        if t == 'wide':
            if sh.get('hero') not in self.chars:
                sh['hero'] = next(iter(self.chars))
            if sh.get('with') not in self.chars or sh.get('with') == sh['hero']:
                sh['with'] = None
            if sh.get('pose') not in art.POSES:
                sh['pose'] = 'stand'
            sh['enemies'] = max(0, min(6, int(sh.get('enemies', 0) or 0)))
        if t == 'symbol' and sh.get('kind') not in ('spiral', 'fire', 'rays', 'lotus', 'storm'):
            sh['kind'] = 'rays'
        return sh

    # ---------------------------------------------------------------- audio
    def voices(self):
        self.durs = []
        for i, l in enumerate(self.lines):
            sp = l['speaker']
            style = NARRATOR['voice'] if sp == 'narrator' else self.chars.get(sp, {}).get('voice', 'man')
            clean = l['text'].replace('*', '')
            self.durs.append(tts.synth(clean, style, f'{self.wd}/l{i:02d}.wav'))
        lead = 0.5
        self.starts = []
        t = lead
        for i, d in enumerate(self.durs):
            self.starts.append(t)
            gap = 0.9 if i == 0 else (0.8 if i == len(self.durs) - 2 else 0.45)
            t += d + gap
        self.total = self.starts[-1] + self.durs[-1] + 2.0
        self.spans = []
        for i in range(len(self.lines)):
            s0 = 0.0 if i == 0 else self.starts[i]
            s1 = self.starts[i + 1] if i + 1 < len(self.lines) else self.total
            self.spans.append((s0, s1))
        # arrows / flashes
        rng = random.Random(self.ep.get('part', 1))
        self.arrows, self.flashes = [], []
        for i, l in enumerate(self.lines):
            sh = l['shot']; s0, s1 = self.spans[i]
            if sh['type'] == 'wide' and sh.get('arrows'):
                n = int((s1 - s0) * 2)
                for k in range(n):
                    at = s0 + 0.2 + (s1 - s0 - 0.8) * k / max(n, 1) + rng.uniform(0, 0.25)
                    side = rng.choice([-1, 1])
                    self.arrows.append((at, -60 if side < 0 else 780, rng.uniform(250, 700), 360 + rng.uniform(-140, 140), rng.uniform(820, 1080)))
            if sh['type'] == 'wide' and sh.get('flash'):
                self.flashes.append(s0 + (s1 - s0) * 0.55)
        self.env = {}
        import soundfile as sf
        for i in range(len(self.lines)):
            a, sr = sf.read(f'{self.wd}/l{i:02d}.wav')
            hop = sr // FPS; n = len(a) // hop + 1
            r = np.array([np.sqrt(np.mean(a[k * hop:(k + 1) * hop] ** 2) + 1e-9) if k * hop < len(a) else 0 for k in range(n)])
            r = r / (r.max() + 1e-9)
            m = np.where(r < 0.12, 0, np.where(r < 0.45, 1, 2))
            for k in range(1, len(m)):
                if m[k] == m[k - 1] == 2 and k % 3 == 0:
                    m[k] = 1
            self.env[i] = m

    def mix(self, out_wav):
        intense, booms = [], [0.05]
        for i, l in enumerate(self.lines):
            sh = l['shot']; s0, s1 = self.spans[i]
            if (sh['type'] == 'wide' and (sh.get('enemies') or sh.get('arrows'))) or sh.get('mood') == 'angry' or sh.get('kind') in ('fire', 'storm'):
                intense.append((s0, s1))
            if sh.get('mood') == 'angry' or sh['type'] == 'end' or sh.get('kind') == 'storm':
                booms.append(s0)
        booms += self.flashes
        merged = []
        for a, b in sorted(intense):
            if merged and a - merged[-1][1] < 1.0:
                merged[-1] = (merged[-1][0], b)
            else:
                merged.append((a, b))
        audio.build_mix(self.total, [(f'{self.wd}/l{i:02d}.wav', s) for i, s in enumerate(self.starts)], merged, booms,
                        [s[0] for s in self.spans[1:]], [a[0] for a in self.arrows], out_wav, seed=self.ep.get('part', 1))

    # ---------------------------------------------------------------- visuals
    def assets(self):
        self.bg = {}
        self.vig = art.vignette()
        self._bust, self._fig, self._cap = {}, {}, {}

    def BG(self, k):
        if k not in self.bg:
            self.bg[k] = art.BG_FUNCS[k]()
        return self.bg[k]

    def bust(self, cid, m, b, mood):
        k = (cid, m, b, mood)
        if k not in self._bust:
            self._bust[k] = art.bust(self.params[cid], m, b, mood)
        return self._bust[k]

    def fig(self, cid, pose, h, sil=False, mirror=False, enemy=False, prop='wheel'):
        k = (cid, pose, h, sil, mirror, enemy, prop)
        if k not in self._fig:
            p = self.params[cid] if cid else art.char_params({'preset': 'warrior'})
            im = art.figure(p, pose, sil, mirror, enemy, prop)
            self._fig[k] = im.resize((int(400 * h / 700 * K), h * K), Image.LANCZOS)
        return self._fig[k]

    def label(self, sp):
        return NARRATOR['name'] if sp == 'narrator' else self.chars.get(sp, {}).get('name', sp)

    def caption(self, i, n, y0):
        k = (i, n, y0)
        if k in self._cap:
            return self._cap[k]
        l = self.lines[i]
        lay = Image.new('RGBA', (OW, OH), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
        f = font(FONT, 36); fl = font(FONT, 22)
        lines, sp = layout(d, parse_words(l['text']), f, 600)
        lab = f'— {self.label(l["speaker"])} —'
        d.text(((OW - d.textlength(lab, font=fl)) / 2, (y0 - 40) * K), lab, font=fl, fill=GOLD_L + (255,), stroke_width=3 * K, stroke_fill=(0, 0, 0, 255))
        draw_words(d, lines, sp, f, y0, 54, n)
        self._cap[k] = crop(lay)
        return self._cap[k]

    def hook_text(self, n):
        k = ('hook', n)
        if k in self._cap:
            return self._cap[k]
        lay = Image.new('RGBA', (OW, OH), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
        ft = font(SERIF, 64)
        title = self.ep.get('story_title', '')
        d.text(((OW - d.textlength(title, font=ft)) / 2, 50 * K), title, font=ft, fill=GOLD_L + (255,), stroke_width=4 * K, stroke_fill=(30, 6, 4, 255))
        badge = f"भाग {self.ep.get('part', 1)}"
        fb = font(FONT, 28); bw = d.textlength(badge, font=fb)
        d.rounded_rectangle([(OW - bw) / 2 - 22 * K, 160 * K, (OW + bw) / 2 + 22 * K, 210 * K], 25 * K, fill=(170, 30, 30, 235), outline=GOLD + (255,), width=3 * K)
        d.text(((OW - bw) / 2, 163 * K), badge, font=fb, fill=(255, 255, 255, 255))
        f = font(FONT, 50)
        lines, sp = layout(d, parse_words(self.lines[0]['text']), f, 640)
        draw_words(d, lines, sp, f, 250, 70, n, stroke=4)
        self._cap[k] = crop(lay)
        return self._cap[k]

    def end_card(self, card):
        k = ('end', card)
        if k in self._cap:
            return self._cap[k]
        lay = Image.new('RGBA', (OW, OH), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
        last = self.ep.get('part', 1) >= self.ep.get('total_parts', 1)
        top = 'समाप्त' if last else f"भाग {self.ep.get('part', 1) + 1} में..."
        f1 = font(FONT, 44)
        d.text(((OW - d.textlength(top, font=f1)) / 2, 400 * K), top, font=f1, fill=WHITE + (255,), stroke_width=3 * K, stroke_fill=(0, 0, 0, 255))
        f = font(SERIF, 84)
        lines, sp = layout(d, [(w, True) for w, _ in parse_words(card)], f, 640)
        draw_words(d, lines, sp, f, 500, 120, 999, stroke=4)
        foot = 'अगला भाग देखने के लिए फ़ॉलो करें' if not last else 'ऐसी और कहानियों के लिए फ़ॉलो करें'
        f3 = font(FONT, 30)
        d.text(((OW - d.textlength(foot, font=f3)) / 2, 1100 * K), foot, font=f3, fill=GOLD_L + (255,), stroke_width=3 * K, stroke_fill=(0, 0, 0, 255))
        self._cap[k] = lay
        return lay

    def word_times(self, i):
        words = parse_words(self.lines[i]['text'])
        lens = [len(w) + 2 for w, _ in words]
        tot = sum(lens) or 1; acc = 0; out = []
        for l in lens:
            out.append(self.starts[i] - 0.05 + self.durs[i] * 0.92 * acc / tot); acc += l
        return out

    def line_at(self, t):
        for i, (a, b) in enumerate(self.spans):
            if a <= t < b:
                return i
        return len(self.spans) - 1

    def mouth(self, cid, t):
        for i, l in enumerate(self.lines):
            if l['speaker'] == cid and self.starts[i] <= t < self.starts[i] + self.durs[i]:
                e = self.env[i]
                return int(e[min(int((t - self.starts[i]) * FPS), len(e) - 1)])
        return 0

    @staticmethod
    def embers(im, t, seed, n=40, color=(255, 170, 70)):
        r = random.Random(seed); d = art.SD(im)
        for _ in range(n):
            x0 = r.uniform(0, W); sp = r.uniform(40, 120); ph = r.uniform(0, 30); s = r.uniform(1.5, 3.5)
            y = H - ((t * sp + ph * 40) % (H + 100)); x = x0 + 20 * math.sin(t * 1.5 + ph)
            d.ellipse([x - s, y - s, x + s, y + s], fill=color + (int(140 + 100 * math.sin(ph)),))

    def draw_arrows(self, im, t, s0, s1):
        d = art.SD(im)
        for at, sx, sy, ex, ey in self.arrows:
            if not (s0 <= at < s1):
                continue
            u = (t - at) / 0.45; ang = math.atan2(ey - sy, ex - sx)
            if 0 <= u <= 1:
                x = sx + (ex - sx) * u; y = sy + (ey - sy) * u
                d.line([(x - 70 * math.cos(ang), y - 70 * math.sin(ang)), (x, y)], fill=(30, 18, 10), width=4)
                d.polygon([(x + 12 * math.cos(ang), y + 12 * math.sin(ang)), (x + 8 * math.cos(ang + 2.4), y + 8 * math.sin(ang + 2.4)), (x + 8 * math.cos(ang - 2.4), y + 8 * math.sin(ang - 2.4))], fill=(200, 200, 210))
            elif u > 1:
                d.line([(ex - 46 * math.cos(ang), ey - 46 * math.sin(ang)), (ex, ey)], fill=(30, 18, 10), width=4)

    @staticmethod
    def paste_feet(base, spr, cx, feet_y):
        base.alpha_composite(spr, (int(cx * K - spr.width / 2), int(feet_y * K - 670 * spr.height / 700)))

    def symbol(self, kind, ts, bgk):
        im = self.BG(bgk).copy()
        d = art.SD(im)
        if kind == 'spiral':
            im = Image.new('RGBA', (OW, OH)); im.paste(art.vgrad([(0, (20, 6, 6)), (640, (90, 30, 18)), (1280, (24, 8, 6))]))
            art.glow(im, 360, 620, 120, (255, 190, 80), 130); d = art.SD(im)
            for k in range(7):
                rad = 70 + k * 44; n = int(2 * math.pi * rad / 26)
                rot = (ts * (10 if k % 2 else -8) + k * 52) * math.pi / 180
                for j in range(n):
                    if j / n < 0.09:
                        continue
                    a = rot + 2 * math.pi * j / n
                    x = 360 + rad * math.cos(a); y = 620 + rad * math.sin(a)
                    d.ellipse([x - 7, y - 7, x + 7, y + 7], fill=(28, 10, 8)); d.ellipse([x - 3, y - 4, x + 2, y + 1], fill=(220, 160, 70))
        elif kind == 'rays' or kind == 'lotus':
            lay = Image.new('RGBA', (OW, OH), (0, 0, 0, 0)); dl = art.SD(lay)
            for k in range(16):
                a = ts * 0.15 + k * 2 * math.pi / 16
                dl.polygon([(360, 640), (360 + 900 * math.cos(a - 0.08), 640 + 900 * math.sin(a - 0.08)), (360 + 900 * math.cos(a + 0.08), 640 + 900 * math.sin(a + 0.08))], fill=(255, 220, 120, 45))
            im.alpha_composite(lay); art.glow(im, 360, 640, 220, (255, 220, 140), 170)
            d = art.SD(im)
            if kind == 'lotus':
                for k in range(8):
                    a = k * math.pi / 8 + math.pi
                    cx, cy = 360 + 110 * math.cos(a), 700 + 50 * math.sin(a)
                    d.polygon([(360, 720), (cx - 40, cy), (cx, cy - 120), (cx + 40, cy)], fill=(240, 120, 150))
                d.ellipse([320, 640, 400, 700], fill=GOLD)
        elif kind == 'fire':
            r = random.Random(int(ts * 12))
            lay = Image.new('RGBA', (OW, OH), (0, 0, 0, 0)); dl = art.SD(lay)
            for k in range(26):
                x = 40 + k * 26 + r.uniform(-8, 8); h = 250 + 220 * abs(math.sin(ts * 3 + k)) + r.uniform(0, 60)
                for c, s in (((255, 80, 20, 200), 1.0), ((255, 170, 40, 220), 0.7), ((255, 240, 160, 230), 0.4)):
                    dl.polygon([(x - 34 * s, 1280), (x + 34 * s, 1280), (x + r.uniform(-12, 12), 1280 - h * s)], fill=c)
            im.alpha_composite(lay.filter(ImageFilter.GaussianBlur(3 * K)))
            art.glow(im, 360, 1100, 300, (255, 120, 30), 120)
            self.embers(im, ts, 11, 60)
        elif kind == 'storm':
            im = Image.new('RGBA', (OW, OH)); im.paste(art.vgrad([(0, (8, 8, 16)), (1280, (30, 30, 50))]))
            art.clouds(im, 22, 0, 700, (70, 70, 90), 160, int(ts))
            if (ts % 2.3) < 0.15:
                d = art.SD(im); x = 200 + (int(ts * 7) % 5) * 70; y = 200; pts = [(x, y)]
                rr = random.Random(int(ts))
                while y < 900:
                    x += rr.uniform(-50, 50); y += rr.uniform(50, 110); pts.append((x, y))
                d.line(pts, fill=(230, 230, 255), width=6)
                im.alpha_composite(Image.new('RGBA', (OW, OH), (200, 200, 255, 70)))
        return im

    def frame(self, t):
        i = self.line_at(t)
        s0, s1 = self.spans[i]; ts = t - s0; dur = s1 - s0
        sh = self.lines[i]['shot']; typ = sh['type']
        bob = 4 * math.sin(2 * math.pi * t / 3.2)
        shake = (0, 0)
        rnd = random.Random(int(t * 1000))
        cap_y = 960
        if typ == 'hook':
            im = self.BG(sh.get('bg', 'battlefield')).copy()
            if sh.get('char') in self.chars:
                b = self.bust(sh['char'], 0, False, None)
                im.alpha_composite(b, (0, int((300 + bob) * K)))
            im.alpha_composite(Image.new('RGBA', (OW, OH), (0, 0, 0, 90)))
            self.embers(im, t, 1)
        elif typ == 'bust':
            im = self.BG(sh['bg']).copy()
            cid = sh['char']; mood = sh.get('mood')
            if self.params[cid].get('glow') and mood != 'sleep':
                art.glow(im, 360, 560, 260, self.params[cid]['glow'], 45)
            blink = (t * 1000 + sum(map(ord, cid)) * 37) % 3400 < 130
            im.alpha_composite(self.bust(cid, self.mouth(cid, t), blink, mood), (0, int((bob + 30) * K)))
            if mood == 'angry':
                self.embers(im, t, 4, 30)
                if ts < 0.35:
                    shake = (rnd.randint(-8, 8), rnd.randint(-8, 8))
            if sh['bg'] in ('night', 'river', 'sky'):
                self.embers(im, t, 6, 25, (200, 210, 255))
        elif typ == 'wide':
            cap_y = 190
            if sh.get('silhouette'):
                im = Image.new('RGBA', (OW, OH)); im.paste(art.vgrad([(0, (30, 4, 10)), (700, (200, 70, 30)), (1000, (60, 14, 10)), (1280, (10, 2, 2))]))
                lay = Image.new('RGBA', (OW, OH), (0, 0, 0, 0)); dl = art.SD(lay)
                for k in range(16):
                    a = ts * 0.15 + k * 2 * math.pi / 16
                    dl.polygon([(360, 640), (360 + 900 * math.cos(a - 0.08), 640 + 900 * math.sin(a - 0.08)), (360 + 900 * math.cos(a + 0.08), 640 + 900 * math.sin(a + 0.08))], fill=(255, 200, 100, 40))
                im.alpha_composite(lay); art.glow(im, 360, 640, 300, (255, 190, 90), 170)
                d = art.SD(im); d.ellipse([110, 390, 610, 890], fill=(255, 214, 130)); d.rectangle([0, 1120, W, H], fill=(8, 2, 2))
                self.paste_feet(im, self.fig(sh['hero'], sh['pose'], 760, sil=True, prop=sh.get('prop', 'wheel')), 360, 1150)
                self.embers(im, t, 8, 50)
                cap_y = 960
            else:
                im = self.BG(sh['bg']).copy()
                pos = [(150, 1000, 434), (580, 1000, 434), (250, 960, 350), (480, 960, 350), (60, 1280, 665), (670, 1280, 665)]
                for k in range(sh['enemies']):
                    x, fy, h = pos[k]
                    self.paste_feet(im, self.fig(None, 'stand' if k % 3 else 'bow', h, sil=True, mirror=x > 360, enemy=True), x, fy)
                hero_h = 640 if sh['pose'] == 'raise' else 560
                if sh.get('with'):
                    self.paste_feet(im, self.fig(sh['with'], 'stand', 520, mirror=True), 500, 1170 + bob)
                    self.paste_feet(im, self.fig(sh['hero'], sh['pose'], hero_h, prop=sh.get('prop', 'wheel')), 240, 1180 + bob)
                else:
                    self.paste_feet(im, self.fig(sh['hero'], sh['pose'], hero_h, prop=sh.get('prop', 'wheel')), 360, 1180 + bob)
                if sh.get('arrows'):
                    self.draw_arrows(im, t, s0, s1)
                for ft in self.flashes:
                    if 0 <= t - ft < 0.5:
                        im.alpha_composite(Image.new('RGBA', (OW, OH), (255, 236, 200, int(220 * (1 - (t - ft) / 0.5)))))
                        shake = (rnd.randint(-10, 10), rnd.randint(-10, 10))
                if sh['bg'].startswith('battle'):
                    self.embers(im, t, 3, 30)
        elif typ == 'symbol':
            cap_y = 1090 if sh['kind'] != 'fire' else 190
            im = self.symbol(sh['kind'], ts, sh['bg'])
        else:  # end
            im = Image.new('RGBA', (OW, OH)); im.paste(art.vgrad([(0, (6, 2, 2)), (700, (60, 12, 8)), (1280, (6, 2, 2))]))
            art.glow(im, 360, 640, 260, (200, 60, 30), 90)
            a = min(1, max(0, ts / 0.8))
            ec = self.end_card(sh.get('card', '')).copy()
            ec.putalpha(ec.getchannel('A').point(lambda v: int(v * a)))
            im.alpha_composite(ec); self.embers(im, t, 9, 40)
        z = 1.0 + 0.07 * min(1, ts / max(dur, 0.1))
        cw, ch = W / z, H / z
        cx, cy = W / 2 + shake[0], H / 2 - 400 * (z - 1) + shake[1]
        im = im.transform((OW, OH), Image.EXTENT, ((cx - cw / 2) * K, (cy - ch / 2) * K, (cx + cw / 2) * K, (cy + ch / 2) * K), Image.BILINEAR)
        im.alpha_composite(self.vig)
        if typ in ('bust', 'wide', 'symbol') and t >= self.starts[i] - 0.1:
            n = sum(1 for x in self.word_times(i) if x <= t)
            if n:
                comp(im, self.caption(i, n, cap_y))
        if typ == 'hook':
            n = sum(1 for x in self.word_times(0) if x <= t)
            comp(im, self.hook_text(n))
        if t < 0.3 or t > self.total - 0.6:
            a = max(0, min(1, min(t / 0.3, (self.total - t) / 0.6)))
            im = Image.blend(Image.new('RGBA', (OW, OH), (0, 0, 0, 255)), im, a)
        return im.convert('RGB')


_EP = None


def _worker(args):
    a, b, out = args
    tmp = out + '.tmp.mp4'
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{OW}x{OH}', '-r', str(FPS), '-i', '-',
                          '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', tmp], stdin=subprocess.PIPE)
    for k in range(a, b):
        p.stdin.write(_EP.frame(k / FPS).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError('ffmpeg failed')
    os.replace(tmp, out)
    return out


def render_episode(ep, workdir, out_mp4, log=print):
    global _EP
    e = Episode(ep, workdir)
    log('tts...'); e.voices()
    log(f'duration {e.total:.1f}s; mixing audio...'); e.mix(f'{workdir}/mix.wav')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', f'{workdir}/mix.wav', '-af', 'loudnorm=I=-14:TP=-1', '-ar', '44100', f'{workdir}/mix_n.wav'], check=True)
    e.assets()
    _EP = e
    nf = int(e.total * FPS)
    nw = max(1, min(os.cpu_count() or 1, int(os.environ.get('RENDER_WORKERS', '3'))))  # ~2.5 GB RAM per worker at 4K
    cuts = [round(nf * k / nw) for k in range(nw + 1)]
    jobs = [(cuts[k], cuts[k + 1], f'{workdir}/part{k}.mp4') for k in range(nw)]
    log(f'rendering {nf} frames on {nw} workers...')
    if nw == 1:
        parts = [_worker(jobs[0])]
    else:
        with mp.get_context('fork').Pool(nw) as pool:
            parts = pool.map(_worker, jobs)
    with open(f'{workdir}/list.txt', 'w') as f:
        for pth in parts:
            f.write(f"file '{os.path.abspath(pth)}'\n")
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', f'{workdir}/list.txt', '-c', 'copy', f'{workdir}/v.mp4'], check=True)
    base = out_mp4.rsplit('.', 1)[0]
    master = f'{base}_4k.mp4' if K >= 3 else out_mp4
    tmp = master + '.tmp.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', f'{workdir}/v.mp4', '-i', f'{workdir}/mix_n.wav', '-map', '0:v', '-map', '1:a',
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-shortest', '-movflags', '+faststart', tmp], check=True)
    os.replace(tmp, master)
    if master != out_mp4:
        # Instagram API max width is 1920px -> post a 1080x1920 version downscaled from the 4K master
        log('making 1080x1920 upload copy from 4K master...')
        tmp = out_mp4 + '.tmp.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', master, '-vf', 'scale=1080:1920:flags=lanczos',
                        '-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-maxrate', '20M', '-bufsize', '40M',
                        '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-movflags', '+faststart', tmp], check=True)
        os.replace(tmp, out_mp4)
    # cover frame from the hook (title + question fully shown)
    cover = base + '_cover.jpg'
    e.frame(min(e.starts[0] + e.durs[0] + 0.3, e.spans[0][1] - 0.1)).resize((1080, 1920), Image.LANCZOS).save(cover, quality=92)
    return out_mp4, cover, e.total
