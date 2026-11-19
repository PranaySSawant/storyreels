"""Host the video at a public URL (GitHub raw by default, or S3) and publish a Reel via the Instagram Graph API."""
import os, time, json, requests

HOST = os.environ.get('IG_API_HOST', 'graph.instagram.com')   # graph.facebook.com if you use Facebook Login / Page token
VER = os.environ.get('IG_API_VERSION', 'v25.0')
IG_ID = os.environ.get('IG_USER_ID', '')
TOKEN_FILE = os.environ.get('IG_TOKEN_FILE', os.path.join(os.environ.get('DATA_DIR', 'data'), 'ig_token.json'))


class PublishError(Exception):
    pass


def _fernet():
    key = os.environ.get('STATE_KEY')
    if not key:
        return None
    import base64, hashlib
    from cryptography.fernet import Fernet
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def token():
    """refreshed token is kept in DATA_DIR (encrypted with STATE_KEY if set, so it can live in a public repo branch)"""
    f = _fernet()
    if f and os.path.exists(TOKEN_FILE + '.enc'):
        return json.loads(f.decrypt(open(TOKEN_FILE + '.enc', 'rb').read()))['access_token']
    if not f and os.path.exists(TOKEN_FILE):
        return json.load(open(TOKEN_FILE))['access_token']
    return os.environ['IG_ACCESS_TOKEN']


def _save_token(d):
    os.makedirs(os.path.dirname(TOKEN_FILE) or '.', exist_ok=True)
    f = _fernet()
    if f:
        open(TOKEN_FILE + '.enc', 'wb').write(f.encrypt(json.dumps(d).encode()))
    else:
        json.dump(d, open(TOKEN_FILE, 'w')); os.chmod(TOKEN_FILE, 0o600)


def api(method, path, **params):
    params['access_token'] = token()
    url = f'https://{HOST}/{VER}/{path}'
    r = requests.request(method, url, params=params if method == 'GET' else None, data=params if method != 'GET' else None, timeout=60)
    try:
        j = r.json()
    except ValueError:
        raise PublishError(f'{r.status_code} {r.text[:300]}')
    if r.status_code >= 400 or 'error' in j:
        raise PublishError(json.dumps(j.get('error', j))[:500])
    return j


def refresh_token():
    """Instagram-Login long-lived tokens last 60 days; refresh weekly. (Facebook Page tokens don't need this.)"""
    if HOST != 'graph.instagram.com':
        return None
    r = requests.get('https://graph.instagram.com/refresh_access_token',
                     params={'grant_type': 'ig_refresh_token', 'access_token': token()}, timeout=30)
    j = r.json()
    if 'access_token' not in j:
        raise PublishError(f'token refresh failed: {j}')
    _save_token({'access_token': j['access_token'], 'refreshed_at': int(time.time()), 'expires_in': j.get('expires_in')})
    return j.get('expires_in')


def quota_left():
    j = api('GET', f'{IG_ID}/content_publishing_limit', fields='quota_usage,config')
    d = j['data'][0]
    return d.get('config', {}).get('quota_total', 50) - d.get('quota_usage', 0)


def s3_url(path, key):
    import boto3
    bucket = os.environ['S3_BUCKET']
    s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'ap-south-1'))
    ctype = 'video/mp4' if path.endswith('.mp4') else 'image/jpeg'
    s3.upload_file(path, bucket, key, ExtraArgs={'ContentType': ctype})
    return s3.generate_presigned_url('get_object', Params={'Bucket': bucket, 'Key': key}, ExpiresIn=3 * 3600)


def github_urls(files):
    """Host files on an orphan 'media' branch of this (public) repo; Instagram fetches them from raw.githubusercontent.com.
    Only the latest reel is kept (force-push)."""
    import subprocess, tempfile, shutil
    repo, tok = os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_TOKEN']
    d = tempfile.mkdtemp()
    for f in files:
        shutil.copy(f, d)
    run = lambda *a: subprocess.run(['git', '-C', d, *a], check=True, capture_output=True)
    run('init', '-q'); run('checkout', '-q', '-b', 'media')
    run('-c', 'user.name=storyreels-bot', '-c', 'user.email=bot@users.noreply.github.com', 'add', '.')
    run('-c', 'user.name=storyreels-bot', '-c', 'user.email=bot@users.noreply.github.com', 'commit', '-q', '-m', 'latest reel')
    run('push', '-q', '-f', f'https://x-access-token:{tok}@github.com/{repo}.git', 'media')
    shutil.rmtree(d, ignore_errors=True)
    time.sleep(5)
    return [f'https://raw.githubusercontent.com/{repo}/media/{os.path.basename(f)}' for f in files]


def host(mp4, cover, key_prefix):
    if os.environ.get('S3_BUCKET'):
        prefix = os.environ.get('S3_PREFIX', 'storyreels').strip('/')
        return s3_url(mp4, f'{prefix}/{key_prefix}.mp4'), (s3_url(cover, f'{prefix}/{key_prefix}.jpg') if cover else None)
    urls = github_urls([mp4] + ([cover] if cover else []))
    return urls[0], (urls[1] if cover else None)


def publish_reel(mp4, cover, caption, key_prefix, log=print):
    left = quota_left()
    if left <= 0:
        raise PublishError('publishing quota for the last 24h is used up')
    vurl, curl = host(mp4, cover, key_prefix)
    params = dict(media_type='REELS', video_url=vurl, caption=caption[:2200], share_to_feed='true')
    if curl:
        params['cover_url'] = curl
    cid = api('POST', f'{IG_ID}/media', **params)['id']
    log(f'container {cid} created; waiting for Instagram to process...')
    for _ in range(90):
        time.sleep(10)
        st = api('GET', cid, fields='status_code,status')
        if st.get('status_code') == 'FINISHED':
            break
        if st.get('status_code') in ('ERROR', 'EXPIRED'):
            raise PublishError(f'container {cid}: {st}')
    else:
        raise PublishError(f'container {cid} not ready after 15 min')
    mid = api('POST', f'{IG_ID}/media_publish', creation_id=cid)['id']
    try:
        link = api('GET', mid, fields='permalink').get('permalink')
    except PublishError:
        link = None
    return mid, link


def publish_via_webhook(mp4, cover, caption, key_prefix, meta=None, log=print):
    """Zapier / Make mode: host the reel publicly and hand the URL + caption to a webhook.
    The Zap/scenario then posts it with its Instagram for Business 'reel' action."""
    vurl, curl = host(mp4, cover, key_prefix)
    payload = {'video_url': vurl, 'cover_url': curl, 'caption': caption[:2200], **(meta or {})}
    r = requests.post(os.environ['WEBHOOK_URL'], json=payload, timeout=60)
    if r.status_code >= 300:
        raise PublishError(f'webhook {r.status_code}: {r.text[:300]}')
    log(f'sent to webhook: {vurl}')
    return 'webhook', vurl
