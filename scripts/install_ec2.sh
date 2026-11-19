#!/usr/bin/env bash
# Ubuntu 24.04 EC2 (t3.medium or bigger). Run from the repo folder: sudo bash scripts/install_ec2.sh
set -euo pipefail
APP=/opt/storyreels
apt-get update -y
apt-get install -y python3-venv ffmpeg fonts-noto-core curl bzip2
mkdir -p $APP && cp -r . $APP && cd $APP
python3 -m venv venv && ./venv/bin/pip install -q -r requirements.txt
bash scripts/get_voices.sh $APP/voices
mkdir -p $APP/data
[ -f .env ] || cp .env.example .env
chmod 600 .env; chmod +x scripts/*.sh
# every 30 minutes
( crontab -l 2>/dev/null | grep -v storyreels ; echo "*/30 * * * * $APP/scripts/run.sh >> $APP/data/cron.log 2>&1" ) | crontab -
echo "Installed. Edit $APP/.env, then test:  $APP/scripts/run.sh --dry-run"
