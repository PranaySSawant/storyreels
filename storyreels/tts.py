"""Hindi TTS.

Primary: Microsoft neural voices via edge-tts (hi-IN Madhur / Swara) — natural, human-like.
Fallback: offline Piper voices (used automatically if edge-tts fails or TTS_ENGINE=piper).
Each character style = voice + pitch/rate shaping + light room tone so it sounds recorded, not synthetic.
"""
import os, subprocess, wave, asyncio, re
from functools import lru_cache

VOICES_DIR = os.environ.get('PIPER_VOICES_DIR', os.path.join(os.path.dirname(__file__), '..', 'voices'))
ENGINE = os.environ.get('TTS_ENGINE', 'edge')

# style: (edge voice, edge rate, edge pitch, piper model, piper semitones, piper speed, extra ffmpeg filter)
VOICE_STYLES = {
    'narrator':    ('hi-IN-MadhurNeural', '-6%', '-4Hz', 'rohan', 0.0, 0.92, ''),
    'man':         ('hi-IN-MadhurNeural', '+0%', '-8Hz', 'pratham', -1.0, 0.97, ''),
    'young_man':   ('hi-IN-MadhurNeural', '+6%', '+10Hz', 'pratham', 2.0, 1.05, ''),
    'old_man':     ('hi-IN-MadhurNeural', '-12%', '-22Hz', 'rohan', -3.0, 0.90, ',aecho=0.8:0.5:40:0.10'),
    'villain':     ('hi-IN-MadhurNeural', '-8%', '-30Hz', 'rohan', -5.0, 0.92, ',aecho=0.8:0.6:60:0.25'),
    'divine':      ('hi-IN-MadhurNeural', '-12%', '-14Hz', 'rohan', -2.0, 0.88, ',aecho=0.8:0.7:90:0.22'),
    'woman':       ('hi-IN-SwaraNeural', '+0%', '+0Hz', 'priyamvada', 0.0, 0.97, ''),
    'young_woman': ('hi-IN-SwaraNeural', '+5%', '+12Hz', 'priyamvada', 1.5, 1.02, ''),
    'old_woman':   ('hi-IN-SwaraNeural', '-10%', '-14Hz', 'priyamvada', -2.0, 0.92, ''),
    'child':       ('hi-IN-SwaraNeural', '+8%', '+45Hz', 'pratham', 4.0, 1.08, ''),
}
# light "recorded voice" finish: warmth, gentle compression, tiny room
FINISH = 'highpass=f=70,equalizer=f=180:t=q:w=1:g=2,equalizer=f=6500:t=q:w=2:g=-2,acompressor=threshold=-18dB:ratio=3:attack=10:release=150,' \
         'aecho=0.85:0.25:18|31:0.08|0.05,loudnorm=I=-16:TP=-1.5'


def _speakable(text):
    return any(ch.isalpha() for ch in text)


def _prep(text):
    t = re.sub(r'\s*\.\.\.\s*', '... ', text)
    return re.sub(r'\s+', ' ', t).strip()


def _edge(text, voice, rate, pitch, out_mp3):
    import edge_tts

    async def go():
        await edge_tts.Communicate(_prep(text), voice, rate=rate, pitch=pitch).save(out_mp3)
    asyncio.run(go())
    if not os.path.exists(out_mp3) or os.path.getsize(out_mp3) < 1000:
        raise RuntimeError('edge-tts returned no audio')


@lru_cache(None)
def _voice(model):
    from piper import PiperVoice
    return PiperVoice.load(os.path.join(VOICES_DIR, f'hi_IN-{model}-medium.onnx'))


def _piper(text, model, semi, speed, raw_wav):
    from piper import SynthesisConfig
    v = _voice(model)
    with wave.open(raw_wav, 'wb') as w:
        v.synthesize_wav(text, w, syn_config=SynthesisConfig(length_scale=1 / speed, noise_scale=0.75, noise_w_scale=0.9))
    sr = v.config.sample_rate
    f = 2 ** (semi / 12)
    return f'asetrate={int(sr * f)},aresample=44100,atempo={1 / f:.4f},'


_edge_ok = None


def synth(text, style, out_wav):
    """write 44.1k mono wav, return duration seconds"""
    global _edge_ok
    ev, rate, pitch, model, semi, speed, extra = VOICE_STYLES.get(style, VOICE_STYLES['man'])
    if not _speakable(text):
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono', '-t', '0.6', out_wav], check=True)
        return 0.6
    src, pre = None, ''
    if ENGINE == 'edge' and _edge_ok is not False:
        try:
            src = out_wav + '.mp3'
            _edge(text, ev, rate, pitch, src)
            if _edge_ok is None:
                print('tts: using Microsoft neural voices (edge-tts)')
            _edge_ok = True
        except Exception as e:
            print('tts: edge-tts failed, using piper:', str(e)[:200])
            if _edge_ok is None:
                _edge_ok = False          # first call failed -> don't keep retrying for this reel
            src = None
    if src is None:
        src = out_wav + '.raw.wav'
        pre = _piper(text, model, semi, speed, src)
    af = f"{pre}aresample=44100,silenceremove=start_periods=1:start_threshold=-50dB{extra},{FINISH}"
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', src, '-af', af, '-ar', '44100', '-ac', '1', out_wav], check=True)
    os.remove(src)
    with wave.open(out_wav) as w:
        return w.getnframes() / w.getframerate()
