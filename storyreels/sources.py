"""Fetch reference text for a story (Wikipedia, English + Hindi) so the script follows the real telling."""
import re, requests

UA = {'User-Agent': 'storyreels/1.0 (https://github.com/PranaySSawant/storyreels)'}


def _wiki(lang, query, max_chars, exact=False):
    api = f'https://{lang}.wikipedia.org/w/api.php'
    if exact:
        title = query
    else:
        r = requests.get(api, headers=UA, timeout=20, params={'action': 'query', 'list': 'search', 'srsearch': query,
                                                               'srlimit': 1, 'format': 'json'})
        hits = r.json().get('query', {}).get('search', [])
        if not hits:
            return None, None
        title = hits[0]['title']
    r = requests.get(api, headers=UA, timeout=20, params={'action': 'query', 'prop': 'extracts', 'explaintext': 1,
                                                           'titles': title, 'format': 'json', 'redirects': 1})
    pages = r.json().get('query', {}).get('pages', {})
    text = next(iter(pages.values()), {}).get('extract', '') or ''
    text = re.split(r'\n==+\s*(References|See also|External links|Notes|Further reading|In popular culture|संदर्भ|बाहरी कड़ियाँ)\s*==+', text)[0]
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return title, text[:max_chars]


def reference(story_id, title_hi, brief, max_chars=6000, wiki_title=None):
    """Best-effort: returns (source_label, text) or (None, '')."""
    q = story_id.replace('_', ' ') + ' ' + ' '.join(re.findall(r'[A-Za-z]+', brief)[:6])
    out, labels = [], []
    for lang, query, n in (('en', wiki_title or q, max_chars), ('hi', title_hi, max_chars // 2)):
        try:
            t, txt = _wiki(lang, query, n, exact=bool(wiki_title) and lang == 'en')
        except Exception:
            t, txt = None, None
        if txt and len(txt) > 400:
            labels.append(f'{lang}.wikipedia: {t}'); out.append(txt)
    return ('; '.join(labels) or None), '\n\n---\n\n'.join(out)


# ---------------------------------------------------------------- unlimited story discovery
CATEGORIES = {
    'myth': ['Characters in the Mahabharata', 'Characters in the Ramayana', 'Hindu mythology', 'Puranas',
             'Avatars of Vishnu', 'Hindu goddesses', 'Rishis', 'Asura', 'Rakshasas', 'Jataka tales',
             'Hindu legendary creatures', 'Hindu folklore'],
    'history': ['Maratha Empire', 'People of the Maratha Empire', 'Battles involving the Maratha Empire', 'Rajput rulers',
                'Maurya Empire', 'Chola dynasty', 'Vijayanagara Empire', 'Indian rebellion of 1857',
                'Revolutionary movement for Indian independence', 'Indian independence activists',
                'Women in the Indian independence movement', 'Battles involving the Mughal Empire', 'Sikh warriors'],
    'ghost': ['Reportedly haunted locations in India', 'Indian ghosts', 'Indian legendary creatures',
              'Indian folklore', 'Ghosts in Hindu mythology', 'Urban legends in India', 'Unexplained phenomena in India'],
}


def _members(cat, depth=1):
    api = 'https://en.wikipedia.org/w/api.php'
    out, cont = [], {}
    try:
        while True:
            r = requests.get(api, headers=UA, timeout=20, params={'action': 'query', 'list': 'categorymembers',
                             'cmtitle': f'Category:{cat}', 'cmtype': 'page|subcat', 'cmlimit': 200, 'format': 'json', **cont})
            j = r.json()
            for m in j.get('query', {}).get('categorymembers', []):
                if m['ns'] == 0:
                    out.append(m['title'])
                elif m['ns'] == 14 and depth > 0:
                    out += _members(m['title'].split(':', 1)[1], depth - 1)
            if 'continue' not in j or len(out) > 600:
                break
            cont = j['continue']
    except Exception:
        pass
    return out


def slug(title):
    return re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')[:40]


def discover(genre, done_ids, rng):
    """Pick an unused Wikipedia article for this genre that is long enough to tell as a story.
    Returns (id, en_title) or None."""
    cats = list(CATEGORIES.get(genre, []))
    rng.shuffle(cats)
    for cat in cats:
        titles = [t for t in _members(cat) if slug(t) not in done_ids and not t.startswith(('List of', 'Index of', 'Outline of'))]
        rng.shuffle(titles)
        for t in titles[:12]:
            try:
                _, txt = _wiki('en', t, 8000, exact=True)
            except Exception:
                continue
            if txt and len(txt) > 2500:
                return slug(t), t
    return None
