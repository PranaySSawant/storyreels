"""Illustrated scene images for each line of the story.

Uses Pollinations (free FLUX image generation, no key). Each scene image is a 9:16 painting built from:
  genre style + fixed character looks (so characters stay recognisable) + the scene's visual description.
Returns None on failure so the renderer can fall back to the vector cartoon.
"""
import os, time, hashlib, urllib.parse, requests
from PIL import Image

STYLE = {
    'myth': 'Indian mythological epic, detailed 2D digital painting, Amar Chitra Katha meets cinematic concept art, '
            'rich warm colors, dramatic lighting, ornate traditional costumes and jewellery',
    'history': 'Indian historical epic, detailed 2D digital painting, cinematic concept art, period-accurate costumes, '
               'armour and architecture, dramatic golden-hour lighting, rich colors',
    'ghost': 'Indian horror folk tale, dark atmospheric 2D digital painting, cinematic, moonlight, fog, deep shadows, '
             'eerie teal and amber tones, suspenseful mood',
}
SAFE = 'respectful dignified devotional depiction, everyone fully clothed in modest traditional attire, family-friendly, no nudity, no gore'
TAIL = 'vertical 9:16 composition, single coherent scene, highly detailed, no text, no letters, no watermark, no frame'

ENDPOINT = os.environ.get('IMAGE_ENDPOINT', 'https://image.pollinations.ai/prompt/')
MODEL = os.environ.get('IMAGE_MODEL', 'flux')
_disabled = False
_last = [0.0]
GAP = float(os.environ.get('IMAGE_GAP', '47'))     # free tier: 1 image / 45 s per IP


def build_prompt(genre, visual, looks):
    """looks: list of 'Name: appearance' strings for characters in this scene."""
    who = ('Characters: ' + '; '.join(looks) + '. ') if looks else ''
    return f"{STYLE.get(genre, STYLE['myth'])}. {SAFE}. {who}Scene: {visual}. {TAIL}"


def generate(prompt, out_path, seed, w=1080, h=1920, tries=4):
    global _disabled
    if _disabled or os.environ.get('IMAGES', 'on') == 'off':
        return None
    if os.path.exists(out_path):
        return out_path
    url = ENDPOINT + urllib.parse.quote(prompt[:1800], safe='')
    params = {'width': w, 'height': h, 'seed': seed, 'model': MODEL, 'nologo': 'true', 'enhance': 'false', 'safe': 'true'}
    for k in range(tries):
        wait = GAP - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            _last[0] = time.time()
            r = requests.get(url, params=params, timeout=150)
            if r.status_code == 200 and r.headers.get('content-type', '').startswith('image') and len(r.content) > 20000:
                tmp = out_path + '.tmp'
                open(tmp, 'wb').write(r.content)
                im = Image.open(tmp).convert('RGB')
                if im.width < 400:
                    raise ValueError('image too small')
                im.save(out_path, quality=95)
                os.remove(tmp)
                return out_path
            print(f'image: HTTP {r.status_code} {r.text[:120] if not r.headers.get("content-type", "").startswith("image") else ""}')
        except Exception as e:
            print('image error:', str(e)[:150])
        time.sleep(5)
    return None


FEMALE = {'queen', 'princess', 'mother', 'goddess', 'warrior_queen', 'villager_woman', 'ghost_woman'}


def seed_for(*parts):
    return int(hashlib.md5('|'.join(map(str, parts)).encode()).hexdigest()[:8], 16) % 1_000_000


def scene_images(ep, workdir, log=print):
    """Generate one image per scene (+ hook). Returns {line_index: path}. Line 0 = hook."""
    global _disabled
    genre = ep.get('genre', 'myth')
    chars = ep.get('characters', {})
    def look(c, cid):
        g = {'m': 'a man', 'f': 'a woman'}.get(c.get('gender') or ('f' if c.get('preset') in FEMALE else 'm'), '')
        return f"{c.get('name_en') or cid} ({g}; {c.get('look', '')})"
    looks_all = {cid: look(c, cid) for cid, c in chars.items() if c.get('look')}
    out, fails = {}, 0
    jobs = [(0, ep.get('hook_visual') or (ep['scenes'][0].get('visual') if ep['scenes'] else ''), ep.get('main_character'))]
    for i, s in enumerate(ep['scenes'], start=1):
        jobs.append((i, s.get('visual', ''), s.get('speaker')))
    base_seed = seed_for(ep.get('story_id'), ep.get('part'))
    for i, visual, sp in jobs:
        if not visual:
            continue
        in_scene = [cid for cid in chars if cid in (visual or '') or cid == sp or (chars[cid].get('name_en') and chars[cid]['name_en'].lower() in visual.lower())]
        prompt = build_prompt(genre, visual, [looks_all[c] for c in in_scene if c in looks_all])
        p = generate(prompt, os.path.join(workdir, f'img{i:02d}.jpg'), base_seed + i)
        if p:
            out[i] = p
        else:
            fails += 1
            if fails >= 3 and not out:
                log('image generation unavailable; using cartoon fallback')
                _disabled = True
                break
    log(f'images: {len(out)}/{len(jobs)} generated')
    if out:   # keep one consistent painted style: lines without an image reuse the nearest painted scene
        have = sorted(out)
        for i, _, _ in jobs:
            if i not in out:
                out[i] = out[min(have, key=lambda k: (abs(k - i), k > i))]
    return out
