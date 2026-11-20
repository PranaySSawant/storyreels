"""Flat-vector character + background drawing (720x1280, drawn at 2x then downscaled)."""
import os, math, random
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

W, H = 720, 1280                         # design units (all drawing coordinates)
K = int(os.environ.get('RENDER_SCALE', '3'))  # 3 -> 2160x3840 (4K vertical), 1 -> 720x1280
OW, OH = W * K, H * K                    # output pixels
S = min(2 * K, 6)                        # supersampling for character sprites
GOLD = (217, 169, 58); GOLD_L = (242, 202, 96)
RED = (200, 30, 40); WHITE = (246, 240, 228); DARK = (22, 14, 12)


def dk(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c[:3])


def col(c):
    if isinstance(c, str):
        c = c.lstrip('#')
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    return tuple(c)


class SD:
    """ImageDraw wrapper taking design-unit coordinates on a K-scaled image."""
    def __init__(self, im):
        self.d = ImageDraw.Draw(im)

    @staticmethod
    def _p(pts):
        if pts and isinstance(pts[0], (tuple, list)):
            return [(x * K, y * K) for x, y in pts]
        return [v * K for v in pts]

    def rectangle(self, box, fill=None, outline=None, width=1):
        self.d.rectangle(self._p(box), fill=fill, outline=outline, width=max(1, int(width * K)))

    def ellipse(self, box, fill=None, outline=None, width=1):
        self.d.ellipse(self._p(box), fill=fill, outline=outline, width=max(1, int(width * K)))

    def polygon(self, pts, fill=None):
        self.d.polygon(self._p(pts), fill=fill)

    def line(self, pts, fill=None, width=1, joint=None):
        self.d.line(self._p(pts), fill=fill, width=max(1, int(width * K)), joint=joint)

    def arc(self, box, a0, a1, fill=None, width=1):
        self.d.arc(self._p(box), a0, a1, fill=fill, width=max(1, int(width * K)))

    def point(self, xy, fill=None):
        x, y = xy
        self.d.ellipse([x * K, y * K, x * K + K, y * K + K], fill=fill)


class Pen:
    def __init__(self, w, h, s=S):
        self.s = s
        self.im = Image.new('RGBA', (w * s, h * s), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.im)

    def P(self, pts):
        return [(x * self.s, y * self.s) for x, y in pts]

    def poly(self, pts, fill):
        self.d.polygon(self.P(pts), fill=fill)

    def ell(self, x0, y0, x1, y1, fill=None, outline=None, w=0):
        self.d.ellipse([x0 * self.s, y0 * self.s, x1 * self.s, y1 * self.s], fill=fill, outline=outline, width=int(w * self.s))

    def line(self, pts, fill, w):
        self.d.line(self.P(pts), fill=fill, width=int(w * self.s), joint='curve')

    def arc(self, box, a0, a1, fill, w):
        self.d.arc([v * self.s for v in box], a0, a1, fill=fill, width=int(w * self.s))

    def chord(self, box, a0, a1, fill):
        self.d.chord([v * self.s for v in box], a0, a1, fill=fill)

    def rect(self, box, fill):
        self.d.rectangle([v * self.s for v in box], fill=fill)

    def out(self, w, h):
        return self.im.resize((w, h), Image.LANCZOS)


# ------------------------------------------------------------------ presets
PRESETS = {
    'king':        dict(gender='m', skin=(188, 126, 84), hair=(26, 20, 20), beard=(40, 28, 24), mustache=True, crown='gold', tilak='red_v', armor=True, sash=(196, 40, 40)),
    'elder_king':  dict(gender='m', skin=(196, 140, 104), hair=(236, 232, 224), beard=(238, 234, 226), mustache=True, crown='gold', tilak='red_v', armor=True, sash=(230, 230, 220)),
    'prince':      dict(gender='m', skin=(206, 146, 96), hair=(22, 18, 18), mustache=False, crown='gold', tilak='red_v', armor=True, sash=(40, 92, 176)),
    'warrior':     dict(gender='m', skin=(176, 116, 78), hair=(22, 18, 18), mustache=True, crown='gold', tilak='red_v', armor=True, sash=(150, 40, 120)),
    'sage':        dict(gender='m', skin=(196, 140, 100), hair=(236, 232, 224), beard=(238, 234, 226), mustache=True, crown='jata', tilak='tripundra', drape=(214, 110, 40)),
    'young_sage':  dict(gender='m', skin=(200, 142, 100), hair=(30, 24, 22), beard=(36, 28, 24), mustache=True, crown='jata', tilak='tripundra', drape=(214, 110, 40)),
    'villain':     dict(gender='m', skin=(122, 88, 72), hair=(14, 14, 20), goatee=True, mustache=True, crown='dark', armor='dark', sash=(26, 92, 62), angry=0.85, glow=(70, 240, 150)),
    'demon':       dict(gender='m', skin=(70, 60, 130), hair=(10, 10, 16), goatee=True, mustache=True, crown='dark', armor='dark', sash=(30, 100, 70), angry=0.9, glow=(70, 240, 150), fangs=True),
    'blue_god':    dict(gender='m', skin=(70, 110, 190), hair=(18, 16, 30), crown='feather', tilak='red_v', armor=True, sash=(240, 200, 60)),
    'blue_prince': dict(gender='m', skin=(80, 120, 190), hair=(18, 16, 30), crown='gold', tilak='red_v', armor=True, sash=(240, 200, 60)),
    'vanara':      dict(gender='m', skin=(226, 116, 40), hair=(180, 80, 30), crown='gold', tilak='red_v', armor=True, sash=(200, 40, 40), muzzle=(250, 206, 156)),
    'queen':       dict(gender='f', skin=(214, 158, 118), hair=(22, 18, 18), crown='tiara', tilak='bindi', cloth=(170, 30, 60)),
    'princess':    dict(gender='f', skin=(222, 168, 126), hair=(22, 18, 18), crown='tiara', tilak='bindi', cloth=(220, 90, 120)),
    'mother':      dict(gender='f', skin=(216, 162, 122), hair=(22, 18, 18), veil=(242, 234, 218), tilak=None),
    'goddess':     dict(gender='f', skin=(232, 180, 130), hair=(22, 18, 18), crown='gold', tilak='bindi', cloth=(210, 40, 40), glow=(255, 220, 120)),
    'boy':         dict(gender='m', skin=(210, 150, 100), hair=(22, 18, 18), crown='none', tilak='red_v', cloth=(240, 200, 80), young=True),
    'commoner':    dict(gender='m', skin=(170, 112, 76), hair=(22, 18, 18), mustache=True, crown='turban', cloth=(230, 225, 210)),
    # --- history ---
    'maratha_king':    dict(gender='m', skin=(184, 124, 84), hair=(20, 16, 16), beard=(24, 18, 16), pointed_beard=True, mustache=True, crown='pagdi', turban=(232, 120, 30), tilak='red_v', armor=True, sash=(232, 120, 30)),
    'maratha_warrior': dict(gender='m', skin=(170, 110, 74), hair=(20, 16, 16), mustache=True, crown='pagdi', turban=(190, 40, 40), tilak='red_v', armor=True, sash=(232, 120, 30)),
    'rajput_king':     dict(gender='m', skin=(196, 136, 92), hair=(20, 16, 16), beard=(26, 20, 18), mustache=True, crown='safa', turban=(214, 50, 90), tilak='red_v', armor=True, sash=(240, 190, 50)),
    'emperor':         dict(gender='m', skin=(200, 146, 104), hair=(24, 18, 16), beard=(30, 22, 18), mustache=True, crown='safa', turban=(240, 236, 220), armor=True, sash=(40, 110, 70)),
    'ancient_king':    dict(gender='m', skin=(190, 130, 88), hair=(20, 16, 16), mustache=True, crown='gold', armor=True, sash=(120, 40, 140)),
    'chanakya':        dict(gender='m', skin=(176, 120, 82), hair=(30, 26, 24), crown='shikha', tilak='tripundra', drape=(214, 110, 40), angry=0.5),
    'british_officer': dict(gender='m', skin=(236, 196, 170), hair=(120, 80, 40), mustache=True, crown='hat', cloth=(176, 28, 34), buttons=True),
    'freedom_fighter': dict(gender='m', skin=(186, 128, 90), hair=(20, 16, 16), mustache=True, crown='none', cloth=(236, 232, 220)),
    'revolutionary':   dict(gender='m', skin=(196, 140, 100), hair=(20, 16, 16), mustache=True, crown='fedora', cloth=(90, 70, 50), young=True),
    'gandhi_cap':      dict(gender='m', skin=(186, 128, 90), hair=(20, 16, 16), mustache=True, crown='topi', cloth=(236, 232, 220)),
    'warrior_queen':   dict(gender='f', skin=(214, 158, 118), hair=(22, 18, 18), crown='safa', turban=(232, 120, 30), tilak='bindi', cloth=(150, 30, 50), armor=True),
    'tribal_youth':    dict(gender='m', skin=(132, 86, 58), hair=(18, 14, 12), crown='none', cloth=(120, 78, 40), young=True, tilak=None),
    'villager_man':    dict(gender='m', skin=(160, 104, 70), hair=(22, 18, 18), mustache=True, crown='turban', turban=(240, 240, 230), cloth=(210, 200, 180)),
    'villager_woman':  dict(gender='f', skin=(196, 140, 100), hair=(22, 18, 18), veil=(200, 70, 60), tilak='bindi'),
    # --- ghost / horror ---
    'ghost_woman':     dict(gender='f', skin=(214, 226, 222), hair=(10, 10, 14), cloth=(236, 240, 236), glow=(150, 255, 210), ghost=True, angry=0.4, wild_hair=True),
    'ghost_man':       dict(gender='m', skin=(176, 196, 206), hair=(30, 34, 40), cloth=(70, 80, 96), glow=(150, 255, 210), ghost=True, angry=0.5),
    'betaal':          dict(gender='m', skin=(150, 186, 150), hair=(236, 236, 230), cloth=(60, 70, 60), glow=(255, 60, 60), ghost=True, fangs=True, angry=0.7, wild_hair=True),
    'ghost_child':     dict(gender='m', skin=(210, 222, 226), hair=(16, 16, 20), cloth=(220, 226, 230), glow=(150, 255, 210), ghost=True, young=True),
}


def char_params(c):
    p = dict(PRESETS.get(c.get('preset', 'prince'), PRESETS['prince']))
    for k, v in c.items():
        if k in ('preset', 'name', 'voice'):
            continue
        if isinstance(v, (list, str)) and k in ('skin', 'hair', 'beard', 'sash', 'cloth', 'drape', 'glow', 'veil') and v:
            v = col(v)
        p[k] = v
    p.setdefault('angry', 0.0)
    return p


def crown_gold(p, c1, c2, jewel, oy=0):
    p.poly([(220, 440 + oy), (182, 345 + oy), (252, 392 + oy)], c2)
    p.poly([(500, 440 + oy), (538, 345 + oy), (468, 392 + oy)], c2)
    p.poly([(245, 388 + oy), (475, 388 + oy), (450, 330 + oy), (270, 330 + oy)], c2)
    p.poly([(270, 332 + oy), (450, 332 + oy), (420, 270 + oy), (300, 270 + oy)], c1)
    p.poly([(300, 272 + oy), (420, 272 + oy), (386, 205 + oy), (334, 205 + oy)], c2)
    p.poly([(334, 207 + oy), (386, 207 + oy), (360, 158 + oy)], c1)
    p.ell(349, 140 + oy, 371, 162 + oy, jewel)
    for y, r in ((358, 11), (300, 10), (240, 9)):
        y += oy
        p.poly([(360, y - r), (360 + r * 0.7, y), (360, y + r), (360 - r * 0.7, y)], jewel)
    p.poly([(222, 386 + oy), (498, 386 + oy), (503, 444 + oy), (217, 444 + oy)], c1)
    for k, x in enumerate(range(236, 490, 22)):
        p.ell(x - 5, 410 + oy, x + 5, 420 + oy, jewel if k % 2 else WHITE)


MOODS = {'calm': 0.0, 'angry': 1.0, 'sad': -0.6, 'smile': -0.2, 'shock': -0.8, 'sleep': 0.0, 'sly': 0.6, 'scared': -0.9}


def bust(c, mouth=0, blink=False, mood=None):
    """c: params from char_params. returns RGBA 720x1280"""
    p = Pen(W, H)
    skin = c['skin']; sd = dk(skin, 0.82)
    hair = c['hair']
    ang = MOODS.get(mood, None) if mood else None
    if ang is None:
        ang = c.get('angry', 0)
    if mood == 'sleep':
        blink = True
    fem = c.get('gender') == 'f'
    veil = c.get('veil')
    # back hair / veil
    if veil:
        p.poly([(200, 470), (520, 470), (560, 1280), (160, 1280)], dk(veil, 0.9))
    elif c.get('wild_hair'):
        p.poly([(220, 400), (500, 400), (600, 700), (640, 1100), (520, 1000), (474, 600), (246, 600), (200, 1000), (80, 1100), (120, 700)], hair)
    elif fem:
        p.poly([(222, 430), (498, 430), (540, 760), (560, 1040), (480, 1060), (474, 600), (246, 600), (240, 1060), (160, 1040), (180, 760)], hair)
    else:
        p.poly([(222, 430), (498, 430), (522, 700), (514, 805), (470, 795), (474, 600), (246, 600), (250, 795), (206, 805), (198, 700)], hair)
    # torso
    body = veil or c.get('cloth') or skin
    p.poly([(0, 1280), (0, 1010), (70, 905), (210, 850), (510, 850), (650, 905), (720, 1010), (720, 1280)], body)
    if body == skin:
        p.arc((170, 900, 360, 1060), 20, 160, sd, 4)
        p.arc((360, 900, 550, 1060), 20, 160, sd, 4)
    if fem and not veil:
        p.poly([(210, 850), (510, 850), (470, 900), (360, 940), (250, 900)], skin)
        p.line([(250, 900), (360, 940), (470, 900)], GOLD, 6)
        p.poly([(420, 860), (600, 880), (720, 1000), (720, 1280), (560, 1280)], dk(body, 0.8))
    if c.get('buttons'):
        for y in range(920, 1280, 70):
            p.ell(350, y, 370, y + 20, GOLD)
        p.poly([(250, 850), (470, 850), (430, 900), (290, 900)], dk(body, 0.7))
    if c.get('drape'):
        dr = c['drape']
        p.poly([(330, 850), (560, 856), (720, 990), (720, 1280), (300, 1280), (420, 1000)], dr)
        p.line([(330, 850), (420, 1000), (300, 1280)], dk(dr, 0.75), 6)
    if c.get('sash') and not fem:
        p.poly([(140, 885), (230, 858), (610, 1280), (480, 1280)], c['sash'])
        p.line([(230, 858), (610, 1280)], GOLD, 5)
    if c.get('armor'):
        ac = GOLD if c['armor'] is True else (120, 92, 40)
        for x0 in (60, 500):
            p.ell(x0, 872, x0 + 160, 962, ac)
            p.ell(x0 + 70, 905, x0 + 90, 925, RED if c['armor'] is True else (60, 220, 140))
    # neck
    nw = 0 if not fem else 12
    p.poly([(315 + nw, 660), (405 - nw, 660), (418 - nw, 868), (302 + nw, 868)], sd)
    p.arc((262, 700, 458, 905), 25, 155, GOLD, 7)
    p.ell(350, 888, 370, 908, RED)
    # ears
    if not veil:
        er = 22 if c.get('muzzle') else 0
        p.ell(208 - er, 505 - er, 242, 585, sd); p.ell(478, 505 - er, 512 + er, 585, sd)
        for x in (225, 495):
            p.ell(x - 14, 578, x + 14, 606, None, GOLD, 5); p.ell(x - 5, 596, x + 5, 606, RED)
    # face
    if fem or c.get('young'):
        face = [(240, 430), (480, 430), (484, 590), (436, 680), (384, 712), (336, 712), (284, 680), (236, 590)]
        half = [(360, 430), (480, 430), (484, 590), (436, 680), (384, 712), (360, 712)]
    else:
        face = [(235, 430), (485, 430), (490, 590), (440, 690), (390, 722), (330, 722), (280, 690), (230, 590)]
        half = [(360, 430), (485, 430), (490, 590), (440, 690), (390, 722), (360, 722)]
    p.poly(face, skin)
    p.poly(half, dk(skin, 0.94))
    if c.get('muzzle'):
        p.ell(268, 590, 452, 735, c['muzzle'])
        p.ell(250, 470, 470, 580, dk(c['muzzle'], 1.0))
    # hairline
    if veil:
        p.poly([(238, 432), (482, 432), (476, 470), (420, 452), (360, 446), (300, 452), (244, 470)], hair)
    elif fem:
        p.poly([(236, 428), (484, 428), (482, 486), (420, 452), (360, 444), (300, 452), (238, 486)], hair)
    elif c.get('crown') == 'jata':
        p.poly([(232, 425), (488, 425), (490, 478), (470, 456), (250, 456), (230, 478)], hair)
    elif not c.get('muzzle'):
        p.poly([(232, 425), (488, 425), (488, 472), (468, 452), (252, 452), (232, 472)], hair)
    # beard
    if c.get('beard'):
        p.poly([(232, 600), (280, 690), (330, 722), (390, 722), (440, 690), (488, 600), (496, 662), (472, 762), (402, 826), (360, 836), (318, 826), (248, 762), (224, 662)], c['beard'])
    if c.get('pointed_beard'):
        p.poly([(300, 700), (420, 700), (380, 830), (360, 860), (340, 830)], c.get('beard') or hair)
    if c.get('goatee'):
        p.poly([(343, 712), (377, 712), (368, 800), (360, 812), (352, 800)], hair)
    # eyes
    for cx, outer in ((305, -1), (415, 1)):
        if blink:
            p.line([(cx - 32, 548), (cx, 557), (cx + 32, 548)], DARK, 5)
            p.line([(cx - 30, 556), (cx - 24, 566)] if outer < 0 else [(cx + 30, 556), (cx + 24, 566)], DARK, 3)
        else:
            p.ell(cx - 32, 533, cx + 32, 561, (250, 246, 238))
            if c.get('glow') and c.get('gender') != 'f':
                g = c['glow']
                p.ell(cx - 15, 532, cx + 15, 562, g)
                p.ell(cx - 6, 540, cx + 6, 554, (230, 255, 240))
            else:
                p.ell(cx - 13, 534, cx + 13, 560, (44, 24, 16))
                p.ell(cx - 6, 540, cx + 1, 547, (255, 255, 255))
            p.line([(cx - 34 if outer < 0 else cx + 34, 546), (cx - 18, 533), (cx + 18, 533), (cx + 34 if outer > 0 else cx - 34, 546)], DARK, 5)
            p.line([(cx + outer * 30, 541), (cx + outer * 46, 532)], DARK, 4)
            if fem:
                p.line([(cx + outer * 34, 538), (cx + outer * 50, 526)], DARK, 3)
        if mood == 'sad' and not blink:
            p.ell(cx + outer * 6 - 4, 566, cx + outer * 6 + 4, 590, (180, 220, 255))
    # brows
    br = dk(hair, 1.0) if sum(hair) < 400 else dk(hair, 0.9)
    bw = 10 if not fem else 6
    p.line([(266, 515 - 6 * ang), (300, 503), (343, 509 + 16 * ang)], br, bw)
    p.line([(454, 515 - 6 * ang), (420, 503), (377, 509 + 16 * ang)], br, bw)
    # nose
    if c.get('muzzle'):
        p.ell(340, 600, 380, 622, dk(skin, 0.5))
    else:
        p.poly([(360, 562), (374, 624), (386, 633), (360, 642), (338, 634), (352, 620)], dk(skin, 0.86))
    # mouth
    lip = dk(skin, 0.55) if not fem else (170, 50, 60)
    my = 682 if not fem else 672
    if mouth == 0:
        if mood == 'smile':
            p.line([(332, my - 6), (360, my + 6), (388, my - 6)], lip, 6)
        elif mood in ('sad', 'angry'):
            p.line([(334, my + 4), (360, my - 2), (386, my + 4)], lip, 6)
        else:
            p.line([(334, my), (360, my + 4), (386, my)], lip, 6)
    elif mouth == 1:
        p.ell(334, my - 11, 386, my + 14, (62, 16, 16)); p.ell(342, my - 11, 378, my - 3, WHITE)
    else:
        p.ell(328, my - 19, 392, my + 24, (62, 16, 16)); p.ell(338, my - 19, 382, my - 8, WHITE); p.ell(346, my + 10, 374, my + 22, (150, 50, 50))
    if c.get('fangs'):
        p.poly([(338, my), (346, my), (342, my + 18)], WHITE); p.poly([(374, my), (382, my), (378, my + 18)], WHITE)
    if c.get('mustache'):
        mc = c.get('beard') or hair
        p.poly([(360, 654), (396, 650), (428, 664), (436, 684), (408, 668), (360, 668), (312, 668), (284, 684), (292, 664), (324, 650)], mc)
    # tilak
    t = c.get('tilak')
    if t == 'red_v':
        p.poly([(354, 452), (366, 452), (364, 508), (356, 508)], RED)
    elif t == 'tripundra':
        for y in (468, 481, 494):
            p.line([(302, y), (418, y)], WHITE, 6)
        p.ell(353, 474, 367, 488, RED)
    elif t == 'bindi':
        p.ell(352, 500, 368, 516, RED)
    # crown / headwear
    cr = c.get('crown')
    if cr == 'gold':
        crown_gold(p, GOLD, GOLD_L, RED)
    elif cr == 'dark':
        crown_gold(p, (96, 74, 34), (132, 102, 44), (60, 220, 140))
    elif cr == 'jata':
        p.ell(296, 318, 424, 440, hair)
        p.arc((296, 318, 424, 440), 200, 340, dk(hair, 0.85), 5)
        p.rect((300, 404, 420, 422), GOLD)
        for x in range(312, 412, 20):
            p.ell(x - 5, 408, x + 5, 418, (120, 50, 30))
    elif cr == 'feather':
        p.poly([(222, 400), (498, 400), (503, 446), (217, 446)], GOLD)
        for k, x in enumerate(range(236, 490, 22)):
            p.ell(x - 5, 416, x + 5, 426, RED if k % 2 else WHITE)
        p.line([(420, 400), (470, 250)], (40, 120, 60), 6)
        p.ell(440, 220, 500, 320, (30, 130, 80)); p.ell(452, 240, 488, 290, (40, 80, 180)); p.ell(462, 255, 478, 275, (20, 20, 60))
    elif cr == 'tiara':
        p.line([(240, 440), (360, 410), (480, 440)], GOLD, 8)
        p.poly([(340, 418), (360, 378), (380, 418)], GOLD); p.ell(352, 396, 368, 412, RED)
        p.line([(360, 444), (360, 476)], GOLD, 4); p.ell(352, 476, 368, 492, RED)
    elif cr in ('pagdi', 'safa'):
        tc = c.get('turban', (230, 120, 40))
        p.ell(212, 318, 508, 462, tc)
        for k, y in enumerate((350, 378, 406, 432)):
            p.arc((222, y - 30, 498, y + 40), 200, 340, dk(tc, 0.78 if k % 2 else 1.15), 7)
        if cr == 'pagdi':
            p.poly([(470, 360), (540, 330), (520, 420)], tc)
            p.ell(345, 352, 375, 382, GOLD); p.ell(353, 360, 367, 374, RED)
            p.line([(360, 352), (372, 300), (392, 270)], WHITE, 6)
        else:
            p.poly([(480, 410), (560, 520), (520, 640), (500, 460)], tc)
            p.ell(345, 340, 375, 370, GOLD); p.line([(360, 340), (354, 290)], (250, 250, 250), 7)
    elif cr == 'topi':
        p.poly([(246, 448), (474, 448), (456, 388), (264, 388)], (246, 246, 240))
        p.line([(264, 392), (456, 392)], (220, 220, 214), 4)
    elif cr == 'hat':
        p.poly([(196, 446), (524, 446), (480, 380), (420, 340), (360, 326), (300, 340), (240, 380)], (24, 22, 26))
        p.line([(220, 440), (500, 440)], GOLD, 6)
    elif cr == 'fedora':
        p.ell(196, 420, 524, 462, (70, 56, 44))
        p.poly([(262, 444), (458, 444), (446, 350), (360, 330), (274, 350)], (84, 68, 52))
        p.rect((264, 418, 456, 436), (30, 24, 20))
    elif cr == 'shikha':
        p.ell(236, 410, 484, 470, (190, 136, 96))
        p.line([(360, 420), (372, 370), (400, 340)], hair, 9)
    elif cr == 'turban':
        p.ell(220, 340, 500, 470, c.get('turban', (230, 120, 40)))
        p.arc((220, 340, 500, 470), 190, 350, dk(c.get('turban', (230, 120, 40)), 0.8), 6)
    if veil:
        p.chord((206, 318, 514, 572), 180, 360, veil)
        p.arc((206, 318, 514, 572), 180, 360, GOLD, 7)
        p.line([(360, 446), (360, 478)], GOLD, 4); p.ell(351, 476, 369, 494, RED)
    return p.out(OW, OH)


POSES = ('stand', 'bow', 'raise', 'mace', 'sword', 'pray')


def figure(c, pose='stand', sil=False, mirror=False, enemy=False, prop='wheel'):
    """full-body sprite in 400x700 box (feet at y=670)."""
    p = Pen(400, 700)
    oy = 100
    blk = (12, 6, 6) if not enemy else (30, 8, 8)

    def cc(x):
        return blk if sil else x
    skin = cc(c['skin']); sd = cc(dk(c['skin'], 0.82))
    fem = c.get('gender') == 'f'
    hair = cc(c['hair'])
    p.rect((162, 95 + oy, 238, (260 if fem else 195) + oy), hair)
    if c.get('veil') and not sil:
        p.poly([(158, 92 + oy), (242, 92 + oy), (262, 300 + oy), (138, 300 + oy)], c['veil'])
    p.rect((168, 430 + oy, 192, 560 + oy), sd); p.rect((208, 430 + oy, 232, 560 + oy), sd)
    p.ell(158, 548 + oy, 196, 570 + oy, sd); p.ell(204, 548 + oy, 242, 570 + oy, sd)
    lower = cc(c.get('cloth') or (200, 50, 50))
    if fem:
        p.poly([(160, 290 + oy), (240, 290 + oy), (280, 560 + oy), (120, 560 + oy)], lower)
    else:
        p.poly([(156, 300 + oy), (244, 300 + oy), (262, 450 + oy), (138, 450 + oy)], lower)
    p.rect((150, 296 + oy, 250, 312 + oy), cc(GOLD))
    top = cc(c.get('drape') or c.get('cloth') if (c.get('drape') or fem or c.get('crown') in ('hat', 'topi', 'fedora', 'none', 'turban') or c.get('ghost')) and (c.get('drape') or c.get('cloth')) else c['skin'])
    p.poly([(148, 192 + oy), (252, 192 + oy), (242, 302 + oy), (158, 302 + oy)], top)
    if c.get('sash') and not fem:
        p.poly([(150, 196 + oy), (172, 190 + oy), (250, 300 + oy), (228, 302 + oy)], cc(c['sash']))
    aw = 20
    wood = cc((120, 72, 30))
    if pose == 'bow':
        p.line([(160, 205 + oy), (128, 222 + oy), (96, 232 + oy)], skin, aw)
        p.line([(240, 205 + oy), (268, 238 + oy), (204, 236 + oy)], skin, aw)
        p.arc((88, 105 + oy, 188, 365 + oy), 95, 265, wood, 10)
        p.line([(130, 112 + oy), (204, 236 + oy), (130, 358 + oy)], cc((230, 220, 200)), 2)
        p.line([(204, 236 + oy), (60, 236 + oy)], cc((90, 60, 30)), 4)
        p.poly([(60, 228 + oy), (40, 236 + oy), (60, 244 + oy)], cc((200, 200, 210)))
    elif pose == 'raise':
        p.line([(158, 200 + oy), (132, 130 + oy), (150, 40 + oy)], skin, aw)
        p.line([(242, 200 + oy), (268, 130 + oy), (250, 40 + oy)], skin, aw)
        if prop == 'rock':
            p.ell(100, -70 + oy, 300, 110 + oy, cc((110, 100, 90)))
        else:
            p.ell(110, -60 + oy, 290, 120 + oy, None, wood, 16)
            for k in range(8):
                a = k * math.pi / 4
                p.line([(200, 30 + oy), (200 + 84 * math.cos(a), 30 + oy + 84 * math.sin(a))], wood, 7)
            p.ell(186, 16 + oy, 214, 44 + oy, cc(GOLD))
    elif pose == 'mace':
        p.line([(156, 200 + oy), (138, 300 + oy), (140, 380 + oy)], skin, aw)
        p.line([(244, 200 + oy), (290, 160 + oy), (300, 100 + oy)], skin, aw)
        p.line([(300, 120 + oy), (300, -10 + oy)], cc(GOLD), 12)
        p.ell(266, -80 + oy, 334, -10 + oy, cc(GOLD)); p.ell(290, -56 + oy, 310, -36 + oy, cc(RED))
    elif pose == 'sword':
        p.line([(156, 200 + oy), (138, 300 + oy), (140, 380 + oy)], skin, aw)
        p.line([(244, 200 + oy), (280, 250 + oy), (300, 230 + oy)], skin, aw)
        p.line([(300, 230 + oy), (360, 60 + oy)], cc((210, 210, 220)), 9)
        p.line([(286, 240 + oy), (316, 216 + oy)], cc(GOLD), 8)
    elif pose == 'pray':
        p.line([(158, 205 + oy), (170, 270 + oy), (198, 230 + oy)], skin, aw)
        p.line([(242, 205 + oy), (230, 270 + oy), (202, 230 + oy)], skin, aw)
    else:
        p.line([(156, 200 + oy), (138, 300 + oy), (140, 380 + oy)], skin, aw)
        p.line([(244, 200 + oy), (262, 300 + oy), (260, 380 + oy)], skin, aw)
        if c.get('armor') and not fem:
            p.line([(262, 380 + oy), (300, 160 + oy)], cc((170, 170, 180)), 8)
    if c.get('armor'):
        p.ell(138, 186 + oy, 178, 216 + oy, cc(GOLD)); p.ell(222, 186 + oy, 262, 216 + oy, cc(GOLD))
    p.rect((190, 168 + oy, 210, 196 + oy), sd)
    p.poly([(166, 100 + oy), (234, 100 + oy), (236, 150 + oy), (214, 178 + oy), (186, 178 + oy), (164, 150 + oy)], skin)
    if c.get('muzzle') and not sil:
        p.ell(176, 135 + oy, 224, 180 + oy, c['muzzle'])
    if c.get('beard'):
        p.poly([(166, 140 + oy), (234, 140 + oy), (226, 196 + oy), (200, 206 + oy), (174, 196 + oy)], cc(c['beard']))
    if not sil:
        for cx in (186, 214):
            p.ell(cx - 6, 128 + oy, cx + 6, 136 + oy, WHITE); p.ell(cx - 3, 129 + oy, cx + 3, 135 + oy, DARK)
        p.line([(176, 122 + oy), (194, 124 + oy)], DARK, 3); p.line([(224, 122 + oy), (206, 124 + oy)], DARK, 3)
        p.line([(192, 160 + oy), (208, 160 + oy)], (120, 50, 40), 3)
    cr = c.get('crown')
    if cr in ('gold', 'dark', 'feather'):
        g = cc(GOLD) if cr != 'dark' else cc((110, 86, 40))
        p.poly([(160, 104 + oy), (240, 104 + oy), (226, 60 + oy), (200, 22 + oy), (174, 60 + oy)], g)
        p.rect((158, 96 + oy, 242, 108 + oy), cc(GOLD_L) if cr != 'dark' else g)
        if not sil:
            p.ell(196, 54 + oy, 204, 62 + oy, RED)
    elif cr == 'jata':
        p.ell(176, 50 + oy, 224, 104 + oy, hair)
    elif cr == 'tiara':
        p.line([(164, 104 + oy), (200, 96 + oy), (236, 104 + oy)], cc(GOLD), 5)
    elif cr in ('turban', 'pagdi', 'safa'):
        p.ell(156, 64 + oy, 244, 116 + oy, cc(c.get('turban', (230, 120, 40))))
    elif cr == 'topi':
        p.poly([(168, 104 + oy), (232, 104 + oy), (226, 82 + oy), (174, 82 + oy)], cc((246, 246, 240)))
    elif cr in ('hat', 'fedora'):
        p.ell(150, 92 + oy, 250, 110 + oy, cc((30, 26, 24)))
        p.poly([(170, 102 + oy), (230, 102 + oy), (222, 64 + oy), (178, 64 + oy)], cc((30, 26, 24)))
    im = p.out(400 * K, 700 * K)
    return ImageOps.mirror(im) if mirror else im


# ------------------------------------------------------------------ backgrounds
def vgrad(stops):
    a = np.zeros((OH, OW, 3), np.float32)
    ys = np.arange(OH)
    for ch in range(3):
        a[:, :, ch] = np.interp(ys, [s[0] * K for s in stops], [s[1][ch] for s in stops])[:, None]
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))


def glow(im, x, y, r, color, alpha=170, blur=None):
    lay = Image.new('RGBA', im.size, (0, 0, 0, 0))
    SD(lay).ellipse([x - r, y - r, x + r, y + r], fill=tuple(color) + (alpha,))
    im.alpha_composite(lay.filter(ImageFilter.GaussianBlur((blur or r * 0.6) * K)))


def stars(im, n, ymax, seed=1):
    r = random.Random(seed); d = SD(im)
    for _ in range(n):
        x, y = r.randint(0, W), r.randint(0, ymax); s = r.choice([1, 1, 2])
        d.ellipse([x, y, x + s, y + s], fill=(255, 245, 220))


def bg_palace(kind):
    pal = {
        'palace_red': ((12, 4, 6), (64, 16, 14), (92, 26, 22), (118, 38, 28), (34, 10, 10)),
        'palace_blue': ((6, 10, 26), (26, 36, 70), (36, 46, 84), (54, 66, 108), (12, 16, 32)),
        'temple': ((30, 14, 4), (110, 64, 20), (150, 96, 36), (190, 130, 50), (60, 30, 10)),
        'patal': ((6, 4, 14), (30, 14, 50), (40, 20, 66), (60, 30, 90), (10, 6, 20)),
    }[kind]
    top, bot, pil, arch, fl = pal
    im = vgrad([(0, top), (900, bot), (1280, bot)]).convert('RGBA')
    stars(im, 60, 200)
    d = SD(im)
    for x in range(-60, 780, 200):
        d.rectangle([x, 170, x + 54, 1280], fill=pil)
        d.rectangle([x - 8, 160, x + 62, 190], fill=arch)
        d.arc([x + 54, 230, x + 200, 520], 180, 360, fill=arch, width=10)
    d.rectangle([0, 1080, W, H], fill=fl)
    fc = (255, 150, 40) if kind != 'patal' else (90, 255, 160)
    for tx in (96, 624):
        d.rectangle([tx - 6, 760, tx + 6, 860], fill=(60, 40, 20))
        glow(im, tx, 740, 120, fc, 150)
        d = SD(im)
        d.ellipse([tx - 18, 700, tx + 18, 760], fill=dk(fc, 1.0) if kind == 'patal' else (255, 190, 70))
        d.ellipse([tx - 8, 722, tx + 8, 758], fill=(255, 240, 180))
    return im


def bg_dusk(dark=False):
    f = 0.62 if dark else 1.0
    im = vgrad([(0, dk((40, 10, 34), f)), (520, dk((176, 62, 40), f)), (820, dk((246, 150, 62), f)), (860, dk((70, 26, 16), f)), (1280, dk((40, 14, 10), f))]).convert('RGBA')
    glow(im, 360, 790, 230, dk((255, 170, 80), f), 150)
    d = SD(im)
    d.ellipse([230, 660, 490, 920], fill=dk((252, 206, 120), f))
    d.rectangle([0, 840, W, H], fill=dk((52, 18, 12), f))
    d.polygon([(0, 860), (120, 780), (260, 830), (420, 770), (560, 820), (720, 760), (720, 880), (0, 880)], fill=dk((38, 12, 10), f))
    r = random.Random(3)
    for k in range(70):
        x = r.randint(-10, 730); h = r.randint(50, 110); y = 880 - r.randint(0, 20)
        d.line([(x, y), (x + r.randint(-6, 6), y - h)], fill=dk((24, 8, 6), f), width=3)
        if k % 6 == 0:
            d.polygon([(x, y - h), (x + 30, y - h + 10), (x, y - h + 20)], fill=dk((150, 30, 26), f))
        d.ellipse([x - 9, y - 18, x + 9, y + 2], fill=dk((22, 8, 6), f))
    d.rectangle([0, 880, W, H], fill=dk((48, 18, 12), f))
    return im


def clouds(im, n, ylo, yhi, color, alpha, seed=9):
    lay = Image.new('RGBA', (OW, OH), (0, 0, 0, 0)); d = SD(lay)
    r = random.Random(seed)
    for _ in range(n):
        x = r.randint(-200, 700); y = r.randint(ylo, yhi)
        d.ellipse([x, y, x + r.randint(250, 450), y + r.randint(50, 90)], fill=tuple(color) + (alpha,))
    im.alpha_composite(lay.filter(ImageFilter.GaussianBlur(25 * K)))


def bg_night():
    im = vgrad([(0, (4, 8, 22)), (700, (18, 28, 58)), (1280, (12, 18, 40))]).convert('RGBA')
    stars(im, 140, 900, 5)
    glow(im, 560, 250, 90, (230, 235, 255), 120)
    SD(im).ellipse([522, 212, 598, 288], fill=(244, 244, 236))
    clouds(im, 14, 650, 1150, (120, 140, 180), 70)
    return im


def bg_forest():
    im = vgrad([(0, (6, 18, 14)), (700, (20, 52, 36)), (1280, (8, 22, 14))]).convert('RGBA')
    glow(im, 360, 400, 200, (120, 200, 140), 60)
    d = SD(im); r = random.Random(4)
    for layer, (c, n) in enumerate((((14, 40, 26), 9), ((8, 26, 16), 7))):
        for _ in range(n):
            x = r.randint(-40, 760); w = r.randint(30, 60) + layer * 20
            d.rectangle([x, 300, x + w, 1280], fill=c)
            for k in range(4):
                cx = x + w / 2 + r.randint(-80, 80); cy = r.randint(150, 600)
                d.ellipse([cx - 110, cy - 70, cx + 110, cy + 70], fill=c)
    d.rectangle([0, 1080, W, H], fill=(10, 24, 14))
    return im


def bg_river():
    im = vgrad([(0, (8, 12, 30)), (640, (40, 60, 100)), (700, (20, 40, 70)), (1280, (10, 20, 40))]).convert('RGBA')
    stars(im, 100, 600, 8)
    glow(im, 200, 220, 80, (230, 235, 255), 110)
    SD(im).ellipse([168, 188, 232, 252], fill=(244, 244, 236))
    d = SD(im); r = random.Random(2)
    d.polygon([(0, 700), (160, 620), (330, 680), (520, 610), (720, 690), (720, 720), (0, 720)], fill=(14, 24, 40))
    for _ in range(60):
        y = r.randint(730, 1250); x = r.randint(0, 700); w = r.randint(30, 120)
        d.line([(x, y), (x + w, y)], fill=(90, 120, 170), width=2)
    return im


def bg_sky():
    im = vgrad([(0, (60, 90, 170)), (700, (250, 190, 140)), (1280, (250, 230, 200))]).convert('RGBA')
    glow(im, 360, 500, 260, (255, 240, 200), 160)
    clouds(im, 18, 500, 1250, (255, 250, 245), 160, 3)
    return im


def bg_fort_ruins():
    im = vgrad([(0, (8, 6, 20)), (700, (40, 30, 60)), (1280, (14, 10, 22))]).convert('RGBA')
    stars(im, 120, 700, 11)
    glow(im, 520, 220, 90, (230, 230, 255), 110)
    d = SD(im); d.ellipse([482, 182, 558, 258], fill=(240, 240, 232))
    wall = (16, 12, 22)
    d.polygon([(0, 640), (90, 640), (90, 600), (130, 600), (130, 640), (220, 640), (220, 590), (260, 560), (300, 600), (300, 680), (0, 700)], fill=wall)
    d.polygon([(380, 700), (380, 560), (420, 560), (420, 530), (460, 530), (460, 560), (520, 560), (520, 520), (560, 480), (600, 540), (600, 560), (720, 560), (720, 720)], fill=wall)
    for x in (430, 560, 640):
        d.arc([x, 590, x + 60, 690], 180, 360, fill=(60, 50, 80), width=6)
    d.rectangle([0, 690, W, H], fill=(12, 10, 18))
    clouds(im, 16, 640, 1200, (150, 170, 190), 70, 21)
    return im


def bg_village_night():
    im = vgrad([(0, (6, 10, 18)), (700, (24, 36, 50)), (1280, (10, 14, 18))]).convert('RGBA')
    stars(im, 100, 650, 13)
    glow(im, 160, 200, 70, (230, 235, 255), 100)
    d = SD(im); d.ellipse([130, 170, 190, 230], fill=(240, 240, 232))
    r = random.Random(5)
    for x in (-40, 160, 420, 600):
        h = r.randint(140, 190)
        d.rectangle([x, 760, x + 160, 900], fill=(20, 18, 16))
        d.polygon([(x - 20, 770), (x + 80, 760 - h * 0.6), (x + 180, 770)], fill=(28, 22, 16))
    for x in (300, 520):
        d.ellipse([x - 4, 820, x + 4, 840], fill=(255, 200, 100))
    glow(im, 300, 830, 50, (255, 170, 60), 120); glow(im, 520, 830, 50, (255, 170, 60), 120)
    d = SD(im)
    d.line([(660, 900), (650, 500)], fill=(10, 10, 10), width=18)
    d.ellipse([520, 380, 760, 560], fill=(10, 14, 12))
    d.rectangle([0, 900, W, H], fill=(14, 16, 14))
    clouds(im, 14, 820, 1250, (160, 180, 200), 60, 17)
    return im


def bg_haunted():
    im = vgrad([(0, (6, 10, 8)), (640, (20, 34, 28)), (1280, (6, 8, 8))]).convert('RGBA')
    d = SD(im)
    d.rectangle([250, 220, 470, 560], fill=(30, 50, 60))
    glow(im, 360, 300, 70, (200, 220, 255), 90)
    d = SD(im)
    d.line([(360, 220), (360, 560)], fill=(10, 12, 10), width=10); d.line([(250, 390), (470, 390)], fill=(10, 12, 10), width=10)
    d.line([(270, 240), (330, 330), (300, 380)], fill=(10, 12, 10), width=3)
    for x in (60, 620):
        d.rectangle([x, 120, x + 40, 1280], fill=(14, 20, 18))
    d.line([(120, 600), (180, 700), (150, 820)], fill=(8, 10, 8), width=4)
    d.line([(560, 500), (600, 620)], fill=(8, 10, 8), width=4)
    d.rectangle([0, 1060, W, H], fill=(8, 12, 10))
    glow(im, 360, 1100, 300, (80, 200, 140), 60)
    clouds(im, 18, 900, 1260, (120, 200, 160), 70, 23)
    return im


BG_FUNCS = {
    'palace_red': lambda: bg_palace('palace_red'), 'palace_blue': lambda: bg_palace('palace_blue'),
    'temple': lambda: bg_palace('temple'), 'patal': lambda: bg_palace('patal'),
    'battlefield': bg_dusk, 'battlefield_dark': lambda: bg_dusk(True),
    'night': bg_night, 'forest': bg_forest, 'river': bg_river, 'sky': bg_sky,
    'fort_ruins': bg_fort_ruins, 'village_night': bg_village_night, 'haunted': bg_haunted,
}
BACKGROUNDS = tuple(BG_FUNCS)


def vignette():
    y, x = np.mgrid[0:OH, 0:OW]
    r = np.sqrt(((x - OW / 2) / (OW * 0.75)) ** 2 + ((y - OH / 2) / (OH * 0.7)) ** 2)
    a = (np.clip(r - 0.45, 0, 1) * 330).clip(0, 200).astype(np.uint8)
    v = Image.new('RGBA', (OW, OH), (0, 0, 0, 255)); v.putalpha(Image.fromarray(a))
    return v
