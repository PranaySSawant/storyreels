"""LLM script writer: plans a story into parts and writes each part as an episode JSON."""
import os, json, re, time, requests
from .art import PRESETS, BACKGROUNDS, POSES, MOODS
from .tts import VOICE_STYLES
from . import sources

PROVIDER = (os.environ.get('LLM_PROVIDER') or ('gemini' if os.environ.get('GEMINI_API_KEY') else 'groq' if os.environ.get('GROQ_API_KEY') else 'anthropic')).lower()
GEMINI_BASE = 'https://generativelanguage.googleapis.com/v1beta/openai'
_gemini_model = None


def gemini_model():
    global _gemini_model
    if _gemini_model:
        return _gemini_model
    if os.environ.get('GEMINI_MODEL'):
        _gemini_model = os.environ['GEMINI_MODEL']; return _gemini_model
    try:
        r = requests.get(f'{GEMINI_BASE}/models', timeout=30, headers={'Authorization': f"Bearer {os.environ['GEMINI_API_KEY']}"})
        ids = [m['id'].split('/')[-1] for m in r.json().get('data', [])]
        ok = [i for i in ids if i.startswith('gemini') and not re.search(r'image|tts|embed|audio|live|vision|lite|exp|preview', i)]
        def ver(i):
            m = re.search(r'gemini-(\d+(?:\.\d+)?)', i)
            return (float(m.group(1)) if m else 0, 'pro' in i)
        _gemini_model = sorted(ok, key=ver)[-1] if ok else 'gemini-2.5-flash'
    except Exception:
        _gemini_model = 'gemini-2.5-flash'
    print('gemini model:', _gemini_model)
    return _gemini_model
GROQ_PREFERRED = ['openai/gpt-oss-120b', 'moonshotai/kimi-k2-instruct', 'llama-3.3-70b-versatile', 'openai/gpt-oss-120b', 'qwen/qwen3-32b', 'llama-3.1-8b-instant']
_groq_model = None


def groq_model():
    global _groq_model
    if _groq_model:
        return _groq_model
    if os.environ.get('GROQ_MODEL'):
        _groq_model = os.environ['GROQ_MODEL']; return _groq_model
    try:
        r = requests.get('https://api.groq.com/openai/v1/models', timeout=30, headers={'Authorization': f"Bearer {os.environ['GROQ_API_KEY']}"})
        ids = [m['id'] for m in r.json().get('data', [])]
        _groq_model = next((i for m in GROQ_PREFERRED for i in sorted(ids, reverse=True) if i == m or i.startswith(m + '-')), ids[0] if ids else GROQ_PREFERRED[0])
    except Exception:
        _groq_model = GROQ_PREFERRED[0]
    print('groq model:', _groq_model)
    return _groq_model


def llm(system, user, max_tokens=4000):
    """Calls the LLM; waits and retries on rate limits (Groq free tier: ~8k tokens/min)."""
    for attempt in range(8):
        try:
            return _llm(system, user, max_tokens)
        except RuntimeError as e:
            msg = str(e)
            if ' 429' not in msg and ' 503' not in msg and ' 500' not in msg:
                raise
            m = re.search(r'try again in ([0-9.]+)(ms|s|m)', msg)
            wait = float(m.group(1)) * {'ms': 0.001, 's': 1, 'm': 60}[m.group(2)] if m else 20
            wait = min(max(wait + 2, 5), 120) * (1 + attempt * 0.5)
            print(f'LLM rate-limited, waiting {wait:.0f}s (attempt {attempt + 1})')
            time.sleep(wait)
    return _llm(system, user, max_tokens)


def _llm(system, user, max_tokens=4000):
    if PROVIDER == 'gemini':
        r = requests.post(f'{GEMINI_BASE}/chat/completions', timeout=180,
                          headers={'Authorization': f"Bearer {os.environ['GEMINI_API_KEY']}"},
                          json={'model': gemini_model(), 'max_tokens': max(max_tokens, 8000), 'temperature': 0.85,
                                'response_format': {'type': 'json_object'},
                                'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]})
        if r.status_code >= 400:
            raise RuntimeError(f'Gemini API {r.status_code}: {r.text[:500]}')
        return r.json()['choices'][0]['message']['content']
    if PROVIDER == 'groq':
        r = requests.post('https://api.groq.com/openai/v1/chat/completions', timeout=120,
                          headers={'Authorization': f"Bearer {os.environ['GROQ_API_KEY']}"},
                          json={'model': groq_model(), 'max_tokens': max_tokens, 'temperature': 0.8,
                                'response_format': {'type': 'json_object'},
                                'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]})
        if r.status_code >= 400:
            raise RuntimeError(f'Groq API {r.status_code}: {r.text[:500]}')
        return r.json()['choices'][0]['message']['content']
    r = requests.post('https://api.anthropic.com/v1/messages', timeout=180,
                      headers={'x-api-key': os.environ['ANTHROPIC_API_KEY'], 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
                      json={'model': os.environ.get('ANTHROPIC_MODEL', 'claude-sonnet-5-5'), 'max_tokens': max_tokens, 'system': system,
                            'messages': [{'role': 'user', 'content': user}]})
    if r.status_code >= 400:
        raise RuntimeError(f'Anthropic API {r.status_code}: {r.text[:500]}')
    return ''.join(b.get('text', '') for b in r.json()['content'])


def parse_json(txt):
    txt = txt.strip()
    m = re.search(r'\{.*\}', txt, re.S)
    if not m:
        raise ValueError('no JSON object in reply')
    return json.loads(m.group(0))


def ask_json(system, user, validate, tries=3):
    err = None
    for k in range(tries):
        u = user if not err else user + f'\n\nYour previous answer was invalid: {err}\nReturn corrected JSON only.'
        try:
            data = parse_json(llm(system, u))
            validate(data)
            return data
        except (ValueError, KeyError, TypeError, AssertionError) as e:
            err = (str(e) or type(e).__name__)[:400]
            print('LLM answer rejected:', err)
        except requests.RequestException as e:
            err = None; time.sleep(10 * (k + 1))
            if k == tries - 1:
                raise
    raise RuntimeError(f'LLM failed validation: {err}')


SYSTEM = f"""You write short Hindi (Devanagari) animated reel scripts: Indian mythology, Indian history, and Indian ghost/folk-horror legends. You always answer with ONE JSON object and nothing else.

Rendering vocabulary (use ONLY these values):
- character presets: {', '.join(PRESETS)}
  (blue_god = Krishna/Vishnu style; blue_prince = Ram style; vanara = Hanuman/vanaras; sage = rishis/gurus like Drona, Vishwamitra; villain/demon = antagonists; mother = veiled older woman; queen/princess/goddess for women; boy for children;
   HISTORY: maratha_king = Shivaji-style saffron pagdi + beard; maratha_warrior; rajput_king = safa + beard; emperor = Mughal/sultan style white safa; ancient_king = Maurya/ancient era; chanakya = shaven head with shikha;
   british_officer = red coat + hat; freedom_fighter = white kurta; gandhi_cap = kurta + white cap; revolutionary = young man with fedora (Bhagat Singh style); warrior_queen = Rani Lakshmibai style; villager_man / villager_woman; tribal_youth = forest/tribal boy or young hunter (e.g. Eklavya);
   GHOST: ghost_woman = pale chudail/white-saree spirit; ghost_man = pale male spirit; betaal = Betaal / brahmarakshas / pishach; ghost_child)
- optional character overrides: skin, hair, beard, sash, cloth, drape as hex like "#c08050"; crown one of gold|dark|jata|feather|tiara|turban|none; glow hex (glowing eyes for divine/demonic)
- voices: {', '.join(VOICE_STYLES)}  (narrator is reserved for the narrator)
- backgrounds: {', '.join(BACKGROUNDS)}
- shot types:
  bust   -> {{"type":"bust","char":ID,"bg":BG,"mood":MOOD}}  close-up of one character; moods: {', '.join(MOODS)}
  wide   -> {{"type":"wide","bg":BG,"hero":ID,"pose":POSE,"with":ID or null,"enemies":0-6,"arrows":bool,"flash":bool,"silhouette":bool,"prop":"wheel"|"rock"}}  poses: {', '.join(POSES)} ("raise" lifts the prop overhead; silhouette=true is a dramatic sunset silhouette)
  symbol -> {{"type":"symbol","kind":KIND,"bg":BG}}  full-screen mood shot. KIND by genre:
            myth: spiral (ONLY for the Chakravyuh/army formation), rays (divine light), lotus, fire, storm
            history: fort (forts, kingdoms, battles), fire, storm, rays
            ghost: tree (haunted tree / jungle), moon (night, full moon), eyes (something watching), storm, fire
Shot rules: use bust shots for most scenes (about 70%), always for dialogue (bust of the speaker).
Use wide shots only for real action (fights, arrows, chases, lifting something) — at most 2 per part. At most 2 symbol shots per part.
Genre rules:
- myth: faithful to the traditional telling, respectful.
- history: stick to recorded facts with real years and places; anything legendary must be framed as "कहा जाता है..." / "किंवदंती है..."; neutral tone, never communal or hateful toward any religion or community; no glorified gore.
- ghost: spooky, suspenseful, Instagram-safe (no gore, no self-harm); present it as a legend/folk belief ("लोग कहते हैं...", "कहा जाता है..."), never as proven fact; use backgrounds night, haunted, fort_ruins, village_night, forest; moods scared/shock; end parts on a chilling cliffhanger.
Storytelling craft (this is what makes people watch to the end and follow):
- Open in the middle of the drama, never with background. The hook is a curiosity-gap question the viewer cannot answer yet; the part must answer it or raise the stakes.
- Every part has a mini arc: setup (1-2 lines) -> rising tension -> a turn or reveal -> cliffhanger. Each scene must move the story forward; cut anything that only explains.
- Show emotion through dialogue: characters speak in their own voice (anger, fear, pride, love). Aim for ~half the scenes as dialogue.
- Use concrete sensory details (torch light, the sound of conch shells, cold wind, blood-red sky) instead of abstract summary.
- Plant one surprising, lesser-known fact or detail per part ("बहुत कम लोग जानते हैं...").
- Short sentences, spoken rhythm, rhetorical questions, dramatic pauses ("..."). Simple everyday Hindi, not Sanskritised.
- Part 2+ starts with a one-line recap scene: "पिछले भाग में..." (max 14 words), then straight into action.
- Cliffhanger: stop at the moment of highest tension and leave an open question; the final part ends with a payoff and a one-line meaning/moral.
- Stay faithful to the reference text when one is given; never invent major events, names or numbers.
- A line spoken by a character ("मैं...", "तुम...") MUST have that character's id as speaker, never "narrator".
- NEVER invent named characters (no made-up names like Rahul/Salim). Only people named in the reference/brief; unnamed roles are allowed only as roles ("एक बूढ़ा पुजारी", "गाँव की औरत").
- Every line must make sense on its own and follow from the previous one; no filler, no vague mood lines without content. Re-read for logic before answering.
Text rules: every spoken line is Hindi Devanagari, max 18 words, punchy, dramatic, simple words. Wrap 1-2 key words per line in *asterisks* (they render gold). Use "..." for dramatic pauses."""


def validate_plan(p):
    assert isinstance(p.get('story_title'), str) and p['story_title'], 'story_title missing'
    assert 2 <= int(p.get('total_parts', 0)) <= 6, 'total_parts must be 2-6'
    assert isinstance(p.get('characters'), dict) and 1 <= len(p['characters']) <= 8, 'characters must be an object with 1-8 entries'
    for cid, c in p['characters'].items():
        assert re.fullmatch(r'[a-z_]{2,20}', cid), f'bad id {cid}'
        assert c.get('preset') in PRESETS, f'bad preset {c.get("preset")}'
        assert c.get('voice') in VOICE_STYLES and c['voice'] != 'narrator', f'bad voice for {cid}'
        assert c.get('name'), f'name missing for {cid}'
    assert isinstance(p.get('parts'), list) and len(p['parts']) == int(p['total_parts']), 'parts list length must equal total_parts'
    for part in p['parts']:
        assert part.get('summary'), 'every part needs a summary'


def plan_series(title, brief, genre='myth', story_id='', wiki_title=None):
    src, ref = sources.reference(story_id or title, title, brief, wiki_title=wiki_title) if wiki_title else (None, '')
    print('reference:', src or 'none')
    user = f"""Plan a multi-part Instagram reel series for this story:
Title: {title}
Genre: {genre}
Brief: {brief}
{('Reference text (' + src + ') — follow it for facts, names, order of events:' + chr(10) + ref) if ref else ''}

Split it into 2-5 parts (each part ~45-70 seconds of narration+dialogue), each ending on a cliffhanger except the last.
Return JSON:
{{"story_title": "short Hindi title (max 3 words)",
  "total_parts": N,
  "characters": {{"id": {{"name": "Hindi name", "name_en": "English name", "gender": "m" or "f", "preset": PRESET, "voice": VOICE, ...optional overrides}}}},
  "main_character": "id",
  "parts": [{{"summary": "English summary of what happens in this part",
             "beats": ["4-6 concrete story beats in order, English"],
             "reveal": "the surprising fact/turn in this part",
             "open_loop": "the unanswered question this part ends on (empty for the last part)"}}]
}}
Plan like a showrunner: each part needs its own peak moment; spread the best moments across parts; the last part pays off every open loop.
ids are short lowercase latin (e.g. "hanuman", "ravan"). Include only characters that appear on screen."""
    plan = ask_json(SYSTEM, user, validate_plan, tries=4)
    plan['reference'] = ref[:5000]
    plan['reference_source'] = src
    return plan


FIRST_PERSON = r'^(मैं|मेरा|मेरी|मेरे|मुझे|मुझको|हम |हमें|हमारा|तुम|आप )'


def repair_shots(e, chars):
    first = next(iter(chars))
    for s in e.get('scenes', []):
        sh = s.get('shot') or {}
        sp = s.get('speaker')
        if sh.get('type') not in ('bust', 'wide', 'symbol') or (sh.get('type') == 'bust' and sh.get('char') not in chars) \
                or (sh.get('type') == 'wide' and sh.get('hero') not in chars):
            s['shot'] = {'type': 'bust', 'char': sp if sp in chars else first, 'bg': sh.get('bg', 'palace_red'), 'mood': sh.get('mood', 'calm')}
        if s['shot'].get('bg') not in BACKGROUNDS:
            s['shot']['bg'] = 'night'
        if s.get('speaker') != 'narrator' and s.get('speaker') not in chars:
            s['speaker'] = 'narrator'


def make_validate_episode(chars):
    def v(e):
        repair_shots(e, chars)
        assert isinstance(e['hook'], str) and e['hook'].strip().endswith('?'), 'hook must be a question ending with ?'
        assert 6 <= len(e['scenes']) <= 12, 'need 6-12 scenes'
        for n, s in enumerate(e['scenes'], 1):
            assert s['speaker'] == 'narrator' or s['speaker'] in chars, f"unknown speaker {s['speaker']}"
            t = s.get('text', '').replace('*', '').strip()
            assert not (s['speaker'] == 'narrator' and re.match(FIRST_PERSON, t)), \
                f'scene {n} "{t[:30]}" is spoken by a character (first/second person): set "speaker" to that character id, not narrator'
            assert isinstance(s['text'], str) and 0 < len(s['text'].split()) <= 26, 'scene text length'
            sh = s['shot']
            assert sh['type'] in ('bust', 'wide', 'symbol'), f"bad shot type {sh['type']}"
            if sh['type'] == 'bust':
                assert sh.get('char') in chars, f"bust char {sh.get('char')} not in characters"
            if sh['type'] == 'wide':
                assert sh.get('hero') in chars, f"wide hero {sh.get('hero')} not in characters"
            assert sh.get('bg', 'battlefield') in BACKGROUNDS, f"bad bg {sh.get('bg')}"
        assert e['cliffhanger']['text'] and e['cliffhanger']['card']
        assert e['caption'] and isinstance(e.get('hashtags', []), list)
    return v


def write_episode(plan, part_no, prev_summary=None, genre='myth'):
    chars = plan['characters']
    part = plan['parts'][part_no - 1]
    last = part_no == int(plan['total_parts'])
    user = f"""Genre: {genre} (follow the genre rules).
Series: {plan['story_title']} — part {part_no} of {plan['total_parts']}.
All parts: {json.dumps([p['summary'] for p in plan['parts']], ensure_ascii=False)}
This part: {part['summary']}
Beats to cover in order: {json.dumps(part.get('beats', []), ensure_ascii=False)}
Reveal/surprise: {part.get('reveal', '')}
End on this open question: {part.get('open_loop', '') if not last else '(final part: pay off everything)'}
{'Previous part ended with: ' + prev_summary + chr(10) + 'Start with a one-line recap scene beginning "पिछले भाग में..."' if prev_summary else ''}
{('Reference facts (stay faithful):' + chr(10) + plan['reference'][:2500]) if plan.get('reference') else ''}
Characters (use these ids only): {json.dumps(chars, ensure_ascii=False)}

Write this part. Return JSON:
{{"hook": "opening narrator QUESTION in Hindi that makes viewers curious, e.g. 'क्या आप जानते हैं...?' / 'क्या होता अगर...?' / 'किसने...?' — must end with ?",
  "hook_bg": BG,
  "scenes": [{{"speaker": "narrator" or character id, "text": "...", "shot": SHOT}}],   // 7-10 scenes, mix narrator and dialogue, vary shots; the speaking character should usually be in a bust shot of themselves; use 1-3 wide/symbol shots for action
  "cliffhanger": {{"text": "narrator line that {'closes the story with its moral/meaning' if last else 'teases what happens next without resolving it'}", "card": "{'2-4 word Hindi closing title' if last else '2-4 word Hindi title teasing next part'}"}},
  "caption": "Instagram caption in Hindi (1-2 lines) that repeats the hook question and says भाग {part_no}/{plan['total_parts']}",
  "hashtags": ["#..." 8-12 relevant tags, Hindi+English mix],
  "summary_for_next": "one English sentence: how this part ended"
}}"""
    validate = make_validate_episode(chars)
    ep = ask_json(SYSTEM, user, validate)
    ep = polish(ep, validate, genre, plan.get('reference', ''))
    ep.update(genre=genre, story_title=plan['story_title'], part=part_no, total_parts=int(plan['total_parts']),
              characters=chars, main_character=plan.get('main_character'))
    return ep


def polish(draft, validate, genre, reference=''):
    """Second pass: a story editor tightens the draft for drama, rhythm and accuracy. Falls back to the draft."""
    user = f"""You are the story editor. Improve this {genre} reel script JSON without changing its structure:
- make the hook a sharper curiosity question; make lines shorter, more emotional and visual; turn dry narration into dialogue where natural
- keep every scene's speaker ids, keep shot objects valid, keep 6-12 scenes, keep *gold* marks on 1-2 key words per line
- remove invented named characters; fix any line that doesn't make sense; dialogue lines must have the character as speaker (not narrator)
- fix any fact that contradicts the reference; keep the cliffhanger at peak tension
{('Reference:' + chr(10) + reference[:2000]) if reference else ''}
Draft:
{json.dumps(draft, ensure_ascii=False)}
Return the full improved JSON only."""
    try:
        better = ask_json(SYSTEM, user, validate, tries=2)
        better.setdefault('summary_for_next', draft.get('summary_for_next'))
        return better
    except Exception as e:
        print('polish skipped:', str(e)[:200])
        return draft


def judge_story(title, text, genre, done_names=()):
    """Is this Wikipedia article a dramatic story worth a reel series? Returns {'title','brief'} or None."""
    user = f"""Genre: {genre}. Wikipedia article "{title}":
{text[:1800]}

Is this a dramatic STORY (events, conflict, a person or place with a tellable legend) that would make a gripping 2-5 part Hindi reel series for an Indian audience in this genre?
It MUST be Indian (set in India / Indian tradition). It must NOT be the same story as one already made: {json.dumps(list(done_names)[-150:], ensure_ascii=False)}. Foreign legends, concepts, lists, texts/books, generic topics, modern politics, or stories outside the genre -> no.
If the article is broad (a deity, a person's whole life, a whole place), pick ONE specific famous dramatic episode from it.
Return JSON: {{"ok": true|false, "title": "short Hindi title (2-4 words)", "episode_en": "English name of that specific episode/legend for searching Wikipedia", "brief": "one-line English summary of the story arc"}}"""
    try:
        d = ask_json(SYSTEM, user, lambda d: d['ok'] in (True, False), tries=2)
    except Exception:
        return None
    return d if d.get('ok') else None


GENRE_HINT = {'myth': 'Indian mythology story (Ramayana, Mahabharata, Puranas, Upanishads, Jataka, legends of saints)',
              'history': 'true Indian historical story (ancient to freedom struggle) with real people, years and places',
              'ghost': 'famous Indian ghost legend, haunted place or folk-horror tale'}


def new_story_idea(done_titles, genre='myth'):
    user = f"""Suggest one well-known {GENRE_HINT.get(genre, GENRE_HINT['myth'])} that is NOT in this list: {json.dumps(done_titles, ensure_ascii=False)}.
Return JSON: {{"id": "short_latin_id", "title": "Hindi title", "brief": "one-line English summary"}}"""
    def v(d):
        assert d['id'] and d['title'] and d['brief']
    return ask_json(SYSTEM, user, v)
