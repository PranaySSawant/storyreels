"""One pipeline cycle: pick story -> plan parts -> write next part -> render -> post. Run every 30 min from cron."""
import os, sys, json, time, fcntl, shutil, argparse, traceback, logging
from . import catalog, writer, render, publish, notify

DATA = os.environ.get('DATA_DIR', 'data')
STATE = os.path.join(DATA, 'state.json')
OUT = os.path.join(DATA, 'out')
WORK = os.path.join(DATA, 'work')
os.makedirs(OUT, exist_ok=True); os.makedirs(WORK, exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                    handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(DATA, 'pipeline.log'))])
log = logging.getLogger('storyreels').info


# Optional remote state (needed on GitHub Actions: runners are wiped after every run)
STATE_S3 = os.environ.get('STATE_S3_URI', '').rstrip('/')   # e.g. s3://my-bucket/storyreels-state
SYNC_FILES = ('state.json', 'ig_token.json', 'ig_token.json.enc')


def _s3():
    import boto3
    b, _, k = STATE_S3[5:].partition('/')
    return boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'ap-south-1')), b, k


def sync_down():
    if not STATE_S3:
        return
    from botocore.exceptions import ClientError
    s3, b, k = _s3()
    for f in SYNC_FILES:
        try:
            s3.download_file(b, f'{k}/{f}', os.path.join(DATA, f))
        except ClientError:
            pass


def sync_up():
    if not STATE_S3:
        return
    s3, b, k = _s3()
    for f in SYNC_FILES:
        p = os.path.join(DATA, f)
        if os.path.exists(p):
            s3.upload_file(p, b, f'{k}/{f}', ExtraArgs={'ServerSideEncryption': 'AES256'})


def load():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {'done': [], 'current': None, 'posts': [], 'token_refreshed': 0}


def save(st):
    tmp = STATE + '.tmp'
    json.dump(st, open(tmp, 'w'), ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)
    sync_up()


def catalog_ids():
    return {sid for gg in catalog.GENRES.values() for sid, _, _ in gg}


def next_story(st):
    """Alternates a newly discovered Wikipedia story and a curated catalog story; LLM suggestion as last resort.
    Returns (id, title, brief, genre, wiki_title)."""
    import random
    from . import sources
    done = set(st['done'])
    order = catalog.ORDER
    last = st.get('last_genre')
    start = (order.index(last) + 1) % len(order) if last in order else 0
    g = order[start]
    # alternate sources: curated catalog story, then a newly discovered one, then catalog...
    if st.get('next_source', 'wiki') == 'catalog':
        for sid, title, brief in catalog.GENRES[g]:
            if sid not in done:
                st['next_source'] = 'wiki'
                return sid, title, brief, g, None
    names = [t for gg in catalog.GENRES.values() for sid, t, _ in gg] + [d for d in st['done'] if d not in catalog_ids()]   # done + planned
    found = sources.discover(g, done, random.Random(), judge=lambda t, txt: writer.judge_story(t, txt, g, names))
    if found:
        sid, wt, v = found
        st['next_source'] = 'catalog'
        ep_en = (v.get('episode_en') or '').strip()
        if ep_en and ep_en.lower() != wt.lower():
            hit = sources.search_title(ep_en)
            if hit:
                wt = hit
        return sid, v.get('title') or wt, v.get('brief') or f'The story of "{wt}"', g, wt
    st['next_source'] = 'wiki'
    for sid, title, brief in catalog.GENRES[g]:
        if sid not in done:
            return sid, title, brief, g, None
    idea = writer.new_story_idea(list(st['done']), g)
    return idea['id'], idea['title'], idea['brief'], g, None


def caption_for(ep):
    tags = ' '.join(t if t.startswith('#') else '#' + t for t in ep.get('hashtags', [])[:25])
    return f"{ep['caption']}\n\n{tags}"


def cycle(st, dry=False):
    cur = st['current']
    if not cur or cur['next_part'] > cur['plan']['total_parts']:
        if cur:
            st['done'].append(cur['id'])
            st['last_genre'] = cur.get('genre') or st.get('last_genre') or 'myth'
        sid, title, brief, genre, wiki_title = next_story(st)
        log(f'new story [{genre}]: {sid} {title}' + (f' (wikipedia: {wiki_title})' if wiki_title else ''))
        plan = writer.plan_series(title, brief, genre, sid, wiki_title)
        st['last_genre'] = genre
        cur = st['current'] = {'id': sid, 'title': title, 'genre': genre, 'plan': plan, 'next_part': 1, 'prev_summary': None, 'pending': None}
        save(st)
    n = cur['next_part']
    pend = cur.get('pending')
    if not pend:
        log(f"writing {cur['id']} part {n}/{cur['plan']['total_parts']}")
        ep = writer.write_episode(cur['plan'], n, cur.get('prev_summary'), cur.get('genre', 'myth'))
        ep['story_id'] = cur['id']
        pend = cur['pending'] = {'episode': ep, 'mp4': None}
        save(st)
    ep = pend['episode']
    key = f"{cur['id']}_p{n}_{int(time.time())}"
    if not pend.get('mp4') or not os.path.exists(pend['mp4']):
        wd = os.path.join(WORK, key)
        mp4, cover, dur = render.render_episode(ep, wd, os.path.join(OUT, key + '.mp4'), log=log)
        shutil.rmtree(wd, ignore_errors=True)
        pend.update(mp4=mp4, cover=cover, duration=dur)
        save(st)
        log(f'rendered {mp4} ({dur:.0f}s)')
    if dry:
        log('dry run: not posting'); return pend['mp4']
    key = os.path.basename(pend['mp4'])[:-4]
    if os.environ.get('WEBHOOK_URL'):
        mid, link = publish.publish_via_webhook(pend['mp4'], pend.get('cover'), caption_for(ep), key,
                                                meta={'story': cur['id'], 'part': n, 'total_parts': ep.get('total_parts')}, log=log)
    elif os.environ.get('IG_USER_ID'):
        mid, link = publish.publish_reel(pend['mp4'], pend.get('cover'), caption_for(ep), key, log=log)
    else:  # default: GitHub Release (download links) + optional email
        master = pend['mp4'][:-4] + '_4k.mp4'
        mid, link = notify.deliver(ep, pend['mp4'], master if os.path.exists(master) else None, pend.get('cover'),
                                   caption_for(ep), key, log=log)
    log(f'posted {mid} {link}')
    st['posts'].append({'t': int(time.time()), 'story': cur['id'], 'part': n, 'media_id': mid, 'link': link})
    cur['prev_summary'] = ep.get('summary_for_next')
    cur['next_part'] = n + 1
    cur['pending'] = None
    save(st)
    # keep disk small: keep last 20 videos
    vids = sorted(f for f in os.listdir(OUT) if f.endswith('.mp4'))
    for f in vids[:-20]:
        for ext in ('.mp4', '_cover.jpg'):
            try: os.remove(os.path.join(OUT, f[:-4] + ext))
            except FileNotFoundError: pass
    return link


def main():
    ap = argparse.ArgumentParser(prog='storyreels')
    ap.add_argument('cmd', choices=['run', 'render', 'status', 'refresh-token', 'skip-story'])
    ap.add_argument('--dry-run', action='store_true', help='write + render but do not post')
    ap.add_argument('--episode', help='render: episode JSON file')
    ap.add_argument('--out', default=os.path.join(OUT, 'test.mp4'))
    a = ap.parse_args()
    if a.cmd == 'render':
        ep = json.load(open(a.episode))
        print(render.render_episode(ep, os.path.join(WORK, 'manual'), a.out, log=log)); return
    lockf = open(os.path.join(DATA, '.lock'), 'w')
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log('previous run still active; skipping'); return
    sync_down()
    st = load()
    if a.cmd == 'status':
        c = st['current']
        print(json.dumps({'current': c and {'id': c['id'], 'next_part': c['next_part'], 'total': c['plan']['total_parts'], 'pending': bool(c.get('pending'))},
                          'done': st['done'], 'last_posts': st['posts'][-5:]}, ensure_ascii=False, indent=1)); return
    if a.cmd == 'skip-story':
        if st['current']:
            st['done'].append(st['current']['id']); st['current'] = None; save(st)
        return
    if a.cmd == 'refresh-token' or not a.dry_run and os.environ.get('IG_USER_ID') and not os.environ.get('WEBHOOK_URL') and time.time() - st.get('token_refreshed', 0) > 6 * 86400:
        try:
            if publish.refresh_token() is not None:
                st['token_refreshed'] = int(time.time()); save(st); log('access token refreshed')
        except Exception as e:
            log(f'token refresh failed: {e}')
        if a.cmd == 'refresh-token':
            return
    try:
        cycle(st, dry=a.dry_run)
    except Exception:
        logging.error(traceback.format_exc())
        sys.exit(1)


if __name__ == '__main__':
    main()
