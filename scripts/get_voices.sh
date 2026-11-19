#!/usr/bin/env bash
# Downloads the 3 Hindi Piper voices (rohan, pratham = male, priyamvada = female)
set -euo pipefail
DEST="${1:-voices}"; mkdir -p "$DEST"; cd "$DEST"
for v in rohan pratham priyamvada; do
  [ -f "hi_IN-$v-medium.onnx" ] && continue
  curl -sSL -o v.tar.bz2 "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-hi_IN-$v-medium.tar.bz2"
  tar xjf v.tar.bz2 --wildcards --strip-components=1 "*/hi_IN-$v-medium.onnx" "*/hi_IN-$v-medium.onnx.json"
  rm v.tar.bz2
done
ls -lh
