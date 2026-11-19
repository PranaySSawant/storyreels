"""Offline Hindi TTS (Piper neural voices) with per-character pitch/speed styling."""
import os, subprocess, wave, tempfile
from functools import lru_cache

VOICES_DIR = os.environ.get('PIPER_VOICES_DIR', os.path.join(os.path.dirname(__file__), '..', 'voices'))

# style: (model, semitones, speed, extra ffmpeg filter)
VOICE_STYLES = {
    'narrator':    ('rohan', 0.0, 0.92, ''),
    'man':         ('pratham', -1.0, 0.97, ''),
    'young_man':   ('pratham', 2.0, 1.05, ''),
    'old_man':     ('rohan', -3.0, 0.90, ',aecho=0.8:0.5:40:0.12'),
    'villain':     ('rohan', -5.0, 0.92, ',aecho=0.8:0.6:60:0.3'),
    'divine':      ('rohan', -2.0, 0.88, ',aecho=0.8:0.7:90:0.25'),
    'woman':       ('priyamvada', 0.0, 0.97, ''),
    'young_woman': ('priyamvada', 1.5, 1.02, ''),
    'old_woman':   ('priyamvada', -2.0, 0.92, ''),
    'child':       ('pratham', 4.0, 1.08, ''),
}


@lru_cache(None)
def _voice(model):
    from piper import PiperVoice
    return PiperVoice.load(os.path.join(VOICES_DIR, f'hi_IN-{model}-medium.onnx'))


def synth(text, style, out_wav):
    """write 44.1k mono wav, return duration seconds"""
    from piper import SynthesisConfig
    model, semi, speed, extra = VOICE_STYLES.get(style, VOICE_STYLES['man'])
    if not any(ch.isalpha() for ch in text):     # nothing speakable -> short silence instead of crashing
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono', '-t', '0.6', out_wav], check=True)
        return 0.6
    v = _voice(model)
    raw = out_wav + '.raw.wav'
    with wave.open(raw, 'wb') as w:
        v.synthesize_wav(text, w, syn_config=SynthesisConfig(length_scale=1 / speed))
    sr = v.config.sample_rate
    f = 2 ** (semi / 12)
    af = f'asetrate={int(sr * f)},aresample=44100,atempo={1 / f:.4f}{extra},highpass=f=70,' \
         'acompressor=threshold=-18dB:ratio=3,loudnorm=I=-16:TP=-1.5'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', raw, '-af', af, '-ar', '44100', '-ac', '1', out_wav], check=True)
    os.remove(raw)
    with wave.open(out_wav) as w:
        return w.getnframes() / w.getframerate()
