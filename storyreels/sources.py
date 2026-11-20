"""Fetch reference text for a story (Wikipedia, English + Hindi) so the script follows the real telling."""
import re, requests

UA = {'User-Agent': 'storyreels/1.0 (https://github.com/PranaySSawant/storyreels)'}


def _wiki(lang, query, max_chars, exact=False, must=None):
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
        if must and not (set(re.findall(r'[a-z]+', title.lower())) & must):
            return None, None          # top hit is about something else
    r = requests.get(api, headers=UA, timeout=20, params={'action': 'query', 'prop': 'extracts', 'explaintext': 1,
                                                           'titles': title, 'format': 'json', 'redirects': 1})
    pages = r.json().get('query', {}).get('pages', {})
    text = next(iter(pages.values()), {}).get('extract', '') or ''
    text = re.split(r'\n==+\s*(References|See also|External links|Notes|Further reading|In popular culture|संदर्भ|बाहरी कड़ियाँ)\s*==+', text)[0]
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return title, text[:max_chars]


def reference(story_id, title_hi, brief, max_chars=6000, wiki_title=None):
    """Best-effort: returns (source_label, text) or (None, '')."""
    q = story_id.replace('_', ' ')
    words = set(w for w in re.findall(r'[a-z]+', (q + ' ' + brief).lower()) if len(w) > 3)
    out, labels = [], []
    for lang, query, n in (('en', wiki_title or q, max_chars), ('hi', title_hi, max_chars // 2)):
        try:
            t, txt = _wiki(lang, query, n, exact=bool(wiki_title) and lang == 'en',
                           must=None if (wiki_title or lang != 'en') else words)
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
              'Ghosts in Hindu mythology', 'Urban legends in India', 'Unexplained phenomena in India',
              'Demons in Hinduism', 'Vetala', 'Bengali folklore', 'Hindu folklore'],
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


KEYWORDS = {
    'myth': r'\b(Mahabharata|Ramayana|Purana|Vishnu|Shiva|Krishna|Rama|Devi|asura|rakshasa|curse|boon|sage|king|battle|slay|legend)\b',
    'history': r'\b(battle|fought|army|siege|killed|executed|escaped|captured|revolt|rebellion|war|fort|arrest)\b',
    'ghost': r'\b(haunted|ghost|spirit|paranormal|curse|legend|apparition|witch|demon|supernatural|vampire|possess)\b',
}
SKIP = ('List of', 'Index of', 'Outline of', 'Timeline of', 'Bibliography', 'Glossary')


def discover(genre, done_ids, rng, judge=None, tries=10):
    """Pick an unused Wikipedia article for this genre that reads like a story.
    judge(title, text) -> dict|None lets the LLM confirm it is a dramatic, tellable story.
    Returns (id, en_title, judged) or None."""
    cats = list(CATEGORIES.get(genre, []))
    rng.shuffle(cats)
    checked = 0
    for cat in cats:
        titles = [t for t in _members(cat) if slug(t) not in done_ids and not t.startswith(SKIP)]
        rng.shuffle(titles)
        for t in titles[:8]:
            try:
                _, txt = _wiki('en', t, 8000, exact=True)
            except Exception:
                continue
            if not txt or len(txt) < 2500 or len(re.findall(KEYWORDS[genre], txt, re.I)) < 6:
                continue
            checked += 1
            verdict = judge(t, txt) if judge else {}
            if verdict is not None:
                return slug(t), t, verdict
            if checked >= tries:
                return None
    return None


def search_title(query):
    """Best matching English Wikipedia article title for a specific episode, or None."""
    try:
        r = requests.get('https://en.wikipedia.org/w/api.php', headers=UA, timeout=20,
                         params={'action': 'query', 'list': 'search', 'srsearch': query, 'srlimit': 1, 'format': 'json'})
        hits = r.json().get('query', {}).get('search', [])
        return hits[0]['title'] if hits else None
    except Exception:
        return None
