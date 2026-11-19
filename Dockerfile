FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-noto-core curl bzip2 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY scripts/get_voices.sh scripts/
RUN bash scripts/get_voices.sh /app/voices
COPY . .
ENV PIPER_VOICES_DIR=/app/voices DATA_DIR=/data
VOLUME /data
# one cycle per container run (schedule with EventBridge -> ECS task, or host cron: docker run --env-file .env -v ...:/data img)
ENTRYPOINT ["python", "-m", "storyreels.main"]
CMD ["run"]
