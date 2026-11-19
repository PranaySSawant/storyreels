"""Manual-posting mode: publish each reel as a GitHub Release (permanent download links) and email the links + caption."""
import os, smtplib, ssl, html, mimetypes, requests
from email.message import EmailMessage

API = 'https://api.github.com'


def _gh():
    return {'Authorization': f"Bearer {os.environ['GITHUB_TOKEN']}", 'Accept': 'application/vnd.github+json'}


def github_release(tag, title, body, files):
    repo = os.environ['GITHUB_REPOSITORY']
    r = requests.post(f'{API}/repos/{repo}/releases', headers=_gh(), timeout=60,
                      json={'tag_name': tag, 'name': title, 'body': body, 'make_latest': 'true'})
    r.raise_for_status()
    rel = r.json()
    links = {}
    for label, path in files:
        if not path or not os.path.exists(path):
            continue
        name = os.path.basename(path)
        ctype = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        with open(path, 'rb') as f:
            u = requests.post(f'https://uploads.github.com/repos/{repo}/releases/{rel["id"]}/assets', params={'name': name},
                              headers={**_gh(), 'Content-Type': ctype}, data=f, timeout=600)
        u.raise_for_status()
        links[label] = u.json()['browser_download_url']
    return rel['html_url'], links


def send_mail(subject, text, html_body):
    host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    port = int(os.environ.get('SMTP_PORT', '465'))
    user, pwd = os.environ['SMTP_USER'], os.environ['SMTP_PASS']
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = os.environ.get('MAIL_FROM', user)
    msg['To'] = os.environ['MAIL_TO']
    msg.set_content(text)
    msg.add_alternative(html_body, subtype='html')
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=60) as s:
            s.login(user, pwd); s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=60) as s:
            s.starttls(context=ssl.create_default_context()); s.login(user, pwd); s.send_message(msg)


def deliver(ep, mp4, master, cover, caption, key, log=print):
    title = f"{ep.get('story_title', '')} — भाग {ep.get('part', 1)}/{ep.get('total_parts', 1)}"
    page, links = github_release(key, title, caption, [('reel_1080p', mp4), ('master_4k', master), ('cover', cover)])
    log(f'release: {page}')
    rows = ''.join(f'<li><a href="{u}">{l.replace("_", " ")}</a></li>' for l, u in links.items())
    html_body = f"""<div style="font-family:Arial,sans-serif;font-size:15px">
<h2 style="margin:0 0 8px">{html.escape(title)}</h2>
<p><b>Hook:</b> {html.escape(ep.get('hook', '').replace('*', ''))}</p>
<p><b>Download:</b></p><ul>{rows}</ul>
<p>Post the <b>1080p</b> file to Instagram. Keep the 4K master for YouTube Shorts and similar.</p>
<p><b>Caption (copy-paste):</b></p>
<pre style="white-space:pre-wrap;background:#f4f4f4;padding:12px;border-radius:8px">{html.escape(caption)}</pre>
<p><a href="{page}">Release page</a></p></div>"""
    text = f"{title}\n\n" + '\n'.join(f'{l}: {u}' for l, u in links.items()) + f"\n\nCaption:\n{caption}\n\n{page}"
    if os.environ.get('MAIL_TO') and os.environ.get('SMTP_PASS'):
        send_mail(f'🎬 Reel ready: {title}', text, html_body)
        log(f"emailed {os.environ['MAIL_TO']}")
    return 'email', links.get('reel_1080p', page)
