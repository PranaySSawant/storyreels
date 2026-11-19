# storyreels — auto Hindi mythology reels → Instagram every 30 min

Every run:
1. Takes the next story from `storyreels/catalog.py`. When the list runs out, the LLM suggests a new one.
2. The LLM plans the story as **2–5 parts** with fixed characters, then writes the next part:
   **an opening question hook**, then 7–10 scenes of narration and dialogue, then a cliffhanger.
3. Renders a **4K (2160×3840)** 9:16 animated reel with flat-vector characters, lip-sync and blinking, word-by-word Hindi captions,
   offline Hindi voices (Piper), tanpura/dhol music and SFX.
4. Makes a 1080×1920 upload copy from the 4K master (the Instagram API rejects videos wider than 1920 px), hosts it at a public URL (this repo's `media` branch, or S3), then publishes as a Reel through the Instagram Graph API.
5. Saves progress in `data/state.json`. A failed post is retried on the next run without re-rendering.

The 4K master (`*_4k.mp4`) is kept in the run's artifacts for YouTube Shorts and similar. Set the variable `RENDER_SCALE=1` for fast 720p renders.

## Instagram setup (one time)
1. Switch your IG account to **Professional** (Creator or Business).
2. Go to developers.facebook.com → **Create app** → use case *"Manage messaging & content on Instagram"*.
3. Open **Instagram API setup with Instagram login** → **Add account** (your IG) → **Generate token**.
   You need the scopes `instagram_business_basic` and `instagram_business_content_publish`.
   You can keep the app in Development mode because only your own account posts.
4. Get your IG user id:
   `curl "https://graph.instagram.com/v25.0/me?fields=user_id,username&access_token=TOKEN"`
5. Put `IG_USER_ID` and `IG_ACCESS_TOKEN` in `.env`. The token is refreshed automatically every 6 days into `data/ig_token.json`.

> If you use a Facebook Page–linked token instead, set `IG_API_HOST=graph.facebook.com`.

## Run on GitHub Actions (recommended: no server, no AWS)
The workflow `.github/workflows/post-reel.yml` runs every 30 min:
- Renders on the GitHub runner: a 4K master, plus a 1080p copy to post.
- Hosts the 1080p reel on this repo's `media` branch. The Instagram API with Instagram Login fetches videos from a **public URL**,
  and `raw.githubusercontent.com` serves that URL. Only the latest reel is kept.
- Saves progress in the `state` branch. The refreshed IG token is stored there **encrypted** with `STATE_KEY`.

**Use a public repo.** Standard runners are free there, and the raw media URL only works for public repos.

### Default mode: make the reel, publish it as a GitHub Release, post manually
The only secret you need is `ANTHROPIC_API_KEY`. Each run creates a **Release** with the 1080p reel, the 4K master, the cover and the caption.
To get an email for every reel: open the repo → **Watch → Custom → Releases** → Apply. GitHub then emails your account address.

Optional: send your own email instead, with the caption in the body. Add these secrets:
| Secret | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic key (or `GROQ_API_KEY` + variable `LLM_PROVIDER=groq`) |
| `MAIL_TO` | where to send the links (comma-separate several addresses) |
| `SMTP_USER` | Gmail address that sends the mail |
| `SMTP_PASS` | Gmail **App password** (Google Account → Security → 2-Step Verification → App passwords) |

Each run creates a GitHub **Release** with the 1080p reel, the 4K master and the cover image as assets, so the links never expire.
It then emails you the links plus the caption and hashtags, ready to paste.

### 1. Repo secrets (auto-posting mode) (Settings → Secrets and variables → Actions → *Secrets*)
| Secret | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic key (or `GROQ_API_KEY` + variable `LLM_PROVIDER=groq`) |
| `IG_USER_ID` | Instagram user id |
| `IG_ACCESS_TOKEN` | long-lived IG token |
| `STATE_KEY` | any long random string (`openssl rand -hex 32`), used to encrypt the refreshed token |

Optional *Variables*: `RENDER_SCALE` (3 = 4K, the default; 1 = 720p), `LLM_PROVIDER`, `ANTHROPIC_MODEL`, `IG_API_HOST`.

### Posting through Make (or Zapier) instead of the Meta token
If you set the secret `WEBHOOK_URL`, the pipeline doesn't call Instagram itself. It hosts the reel and POSTs this JSON to your webhook:
```json
{"video_url": "https://raw.githubusercontent.com/<you>/storyreels/media/<file>.mp4",
 "cover_url": "https://raw.githubusercontent.com/<you>/storyreels/media/<file>_cover.jpg",
 "caption": "…hook question… #hashtags", "story": "chakravyuh", "part": 1, "total_parts": 3}
```
**Make.com scenario:**
1. Create a new scenario. Module 1: **Webhooks → Custom webhook** → Add → copy the URL into the GitHub secret `WEBHOOK_URL`.
2. Run the workflow once (dry_run off), or POST the sample JSON above with curl, so Make learns the fields.
3. Module 2: **Instagram for Business → Create a Reel Post**. Connect your IG account by logging in.
   Map Video URL → `video_url`, Caption → `caption`, Share to feed → Yes.
4. Turn the scenario **ON** with "Immediately as data arrives".

**Zapier:** Trigger *Webhooks by Zapier → Catch Hook* → Action *Instagram for Business → Publish Video/Reel* with the same mapping.

With `WEBHOOK_URL` set you don't need the `IG_USER_ID`, `IG_ACCESS_TOKEN` or `STATE_KEY` secrets.
Check your Make/Zapier plan limits: every reel uses a few operations or tasks, and 48 reels a day adds up quickly.

### 2. First run
Actions → **post-reel** → *Run workflow* (dry_run ✔). Download the 1080p and 4K reels from the run's artifacts and check them.
Then run again with dry_run unticked to post. After that the schedule takes over.

### Notes
- If Instagram ever refuses the GitHub-hosted URL (container status `ERROR`), switch hosting to S3:
  set `S3_BUCKET` and add AWS credentials to the workflow (see the EC2 section for the IAM policy).
- Scheduled runs can start a few minutes late when GitHub is busy.
- The `state` branch is force-pushed on every run. That push is repo activity, which should keep GitHub from auto-disabling the schedule after 60 idle days.

---

## Alternative: run on your own EC2
## EC2 setup
- Create a **private** S3 bucket (for example in ap-south-1). Add a lifecycle rule that deletes `storyreels/` objects after 3 days.
- Attach an EC2 instance role with `s3:PutObject` and `s3:GetObject` on `arn:aws:s3:::BUCKET/storyreels/*`.
- EC2: Ubuntu 24.04 on t3.medium or bigger (c6i.large renders faster), 20 GB disk.

## Install & run (EC2)
```bash
git clone <this repo> && cd storyreels
sudo bash scripts/install_ec2.sh          # installs to /opt/storyreels and sets up cron */30
sudo nano /opt/storyreels/.env            # fill keys
/opt/storyreels/scripts/run.sh --dry-run  # writes + renders, does not post → check data/out/*.mp4
/opt/storyreels/scripts/run.sh            # first real post (cron takes over after this)
```

Useful commands (run from /opt/storyreels with .env loaded):
```bash
./venv/bin/python -m storyreels.main status          # current story/part, last posts
./venv/bin/python -m storyreels.main skip-story      # drop current story, start the next one
./venv/bin/python -m storyreels.main render --episode examples/sample_episode.json --out test.mp4
tail -f data/pipeline.log
```
Change the schedule with `crontab -e`.

## Customise
- **Stories:** edit `catalog.py`, as `(id, Hindi title, English brief)`.
- **Look:** character presets, backgrounds and shot types live in `art.py`. The LLM is told the allowed values in `writer.py`.
- **Voices:** `VOICE_STYLES` in `tts.py`, which sets the model, pitch and speed per character type.
- **Better voices:** replace `tts.synth()` with ElevenLabs, Azure or Google Hindi TTS. It only has to write a 44.1 kHz mono wav and return its duration.

## Notes
- The Instagram API allows about 50 published posts per rolling 24 h. 48 per day at a 30-min interval fits, but only just.
  The pipeline checks `content_publishing_limit` before every post.
- Posting 48 reels a day can make Instagram treat the account as spammy and cut reach. If reach drops, try `0 */2 * * *` (every 2 h).
- Treat the generated stories as drafts. The LLM can get details wrong, so spot-check `data/out/` now and then.
