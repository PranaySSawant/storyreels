"""LLM script writer: plans a story into parts and writes each part as an episode JSON."""
import os, json, re, time, requests
from .art import PRESETS, BACKGROUNDS, POSES, MOODS
from .tts import VOICE_STYLES

PROVIDER = os.environ.get('LLM_PROVIDER', 'anthropic')


def llm(system, user, max_tokens=4000):
    if PROVIDER == 'groq':
        r = requests.post('https://api.groq.com/openai/v1/chat/completions', timeout=120,
                          headers={'Authorization': f"Bearer {os.environ['GROQ_API_KEY']}"},
                          json={'model': os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile'), 'max_tokens': max_tokens, 'temperature': 0.8,
                                'response_format': {'type': 'json_object'},
                                'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]})
        r.raise_for_status()
        return r.json()['choices'][0]['message']['content']
    r = requests.post('https://api.anthropic.com/v1/messages', timeout=180,
                      headers={'x-api-key': os.environ['ANTHROPIC_API_KEY'], 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
                      json={'model': os.environ.get('ANTHROPIC_MODEL', 'claude-sonnet-5-5'), 'max_tokens': max_tokens, 'system': system,
                            'messages': [{'role': 'user', 'content': user}]})
    r.raise_for_status()
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
            err = str(e)[:400]
        except requests.RequestException as e:
            err = None; time.sleep(10 * (k + 1))
            if k == tries - 1:
                raise
    raise RuntimeError(f'LLM failed validation: {err}')


SYSTEM = f"""You write short Hindi (Devanagari) animated reel scripts retelling Indian mythology (Ramayana, Mahabharata, Puranas) faithfully to the traditional telling, respectful in tone, no gore. You always answer with ONE JSON object and nothing else.

Rendering vocabulary (use ONLY these values):
- character presets: {', '.join(PRESETS)}
  (blue_god = Krishna/Vishnu style; blue_prince = Ram style; vanara = Hanuman/vanaras; sage = rishis/gurus like Drona, Vishwamitra; villain/demon = antagonists; mother = veiled older woman; queen/princess/goddess for women; boy for children)
- optional character overrides: skin, hair, beard, sash, cloth, drape as hex like "#c08050"; crown one of gold|dark|jata|feather|tiara|turban|none; glow hex (glowing eyes for divine/demonic)
- voices: {', '.join(VOICE_STYLES)}  (narrator is reserved for the narrator)
- backgrounds: {', '.join(BACKGROUNDS)}
- shot types:
  bust   -> {{"type":"bust","char":ID,"bg":BG,"mood":MOOD}}  close-up of one character; moods: {', '.join(MOODS)}
  wide   -> {{"type":"wide","bg":BG,"hero":ID,"pose":POSE,"with":ID or null,"enemies":0-6,"arrows":bool,"flash":bool,"silhouette":bool,"prop":"wheel"|"rock"}}  poses: {', '.join(POSES)} ("raise" lifts the prop overhead; silhouette=true is a dramatic sunset silhouette)
  symbol -> {{"type":"symbol","kind":"spiral"|"fire"|"rays"|"lotus"|"storm","bg":BG}}  for formations, fire, divine light, storms
Text rules: every spoken line is Hindi Devanagari, max 18 words, punchy, dramatic, simple words. Wrap 1-2 key words per line in *asterisks* (they render gold). Use "..." for dramatic pauses."""


def validate_plan(p):
    assert isinstance(p['story_title'], str) and p['story_title']
    assert 2 <= int(p['total_parts']) <= 6
    assert isinstance(p['characters'], dict) and 1 <= len(p['characters']) <= 8
    for cid, c in p['characters'].items():
        assert re.fullmatch(r'[a-z_]{2,20}', cid), f'bad id {cid}'
        assert c.get('preset') in PRESETS, f'bad preset {c.get("preset")}'
        assert c.get('voice') in VOICE_STYLES and c['voice'] != 'narrator', f'bad voice for {cid}'
        assert c.get('name')
    assert len(p['parts']) == int(p['total_parts'])
    for part in p['parts']:
        assert part['summary']


def plan_series(title, brief):
    user = f"""Plan a multi-part Instagram reel series for this story:
Title: {title}
Brief: {brief}

Split it into 2-5 parts (each part ~45-70 seconds of narration+dialogue), each ending on a cliffhanger except the last.
Return JSON:
{{"story_title": "short Hindi title (max 3 words)",
  "total_parts": N,
  "characters": {{"id": {{"name": "Hindi name", "preset": PRESET, "voice": VOICE, ...optional overrides}}}},
  "main_character": "id",
  "parts": [{{"summary": "English summary of what happens in this part"}}]
}}
ids are short lowercase latin (e.g. "hanuman", "ravan"). Include only characters that appear on screen."""
    return ask_json(SYSTEM, user, validate_plan)


def make_validate_episode(chars):
    def v(e):
        assert isinstance(e['hook'], str) and e['hook'].strip().endswith('?'), 'hook must be a question ending with ?'
        assert 6 <= len(e['scenes']) <= 12, 'need 6-12 scenes'
        for s in e['scenes']:
            assert s['speaker'] == 'narrator' or s['speaker'] in chars, f"unknown speaker {s['speaker']}"
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


def write_episode(plan, part_no, prev_summary=None):
    chars = plan['characters']
    part = plan['parts'][part_no - 1]
    last = part_no == int(plan['total_parts'])
    user = f"""Series: {plan['story_title']} — part {part_no} of {plan['total_parts']}.
All parts: {json.dumps([p['summary'] for p in plan['parts']], ensure_ascii=False)}
This part: {part['summary']}
{'Previous part ended with: ' + prev_summary if prev_summary else ''}
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
    ep = ask_json(SYSTEM, user, make_validate_episode(chars))
    ep.update(story_title=plan['story_title'], part=part_no, total_parts=int(plan['total_parts']),
              characters=chars, main_character=plan.get('main_character'))
    return ep


def new_story_idea(done_titles):
    user = f"""Suggest one well-known Indian mythology story (Ramayana, Mahabharata, Puranas, Upanishads, Jataka, folk legends of saints) that is NOT in this list: {json.dumps(done_titles, ensure_ascii=False)}.
Return JSON: {{"id": "short_latin_id", "title": "Hindi title", "brief": "one-line English summary"}}"""
    def v(d):
        assert d['id'] and d['title'] and d['brief']
    return ask_json(SYSTEM, user, v)
