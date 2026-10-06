"""
voice_generator.py — Seslendirme üretir.

Fallback sırası:
1. ElevenLabs (en kaliteli, API key ile, engellenmez)
2. Edge TTS (ücretsiz, kaliteli)
3. gTTS (ücretsiz, orta)
4. Google Cloud TTS (ücretsiz 1M/ay, kaliteli)

Hangisi çalışırsa onu kullanır.
"""

import asyncio
import os
import base64
import requests
from .utils import load_yaml, ensure_dir, get_env, setup_logging

logger = setup_logging()

SETTINGS_PATH = "config/settings.yaml"


# ═══════════════════════════════════════════════════════════
# 1. ELEVENLABS
# ═══════════════════════════════════════════════════════════

def try_elevenlabs(text: str, output: str, voice_id: str = "21m00Tcm4TlvDq8ikWAM") -> bool:
    """
    ElevenLabs TTS.
    voice_id: Rachel (kadın, dramatik) — varsayılan
    Diğer kadın sesler:
      - 21m00Tcm4TlvDq8ikWAM (Rachel, sakin)
      - EXAVITQu4vr4xnSDxMaL (Bella, dramatik)
      - pNInz6obpgDQGcFmaJgB (Adam, erkek)
      - ErXwobaYiN019PkySvjV (Antoni, erkek)
    """
    try:
        api_key = get_env("ELEVENLABS_API_KEY", required=False)
        if not api_key:
            logger.warning("ELEVENLABS_API_KEY yok, ElevenLabs atlanıyor.")
            return False
        
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": api_key,
        }
        
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.3,
                "use_speaker_boost": True,
            },
        }
        
        r = requests.post(url, json=payload, headers=headers, timeout=60)
        
        if r.status_code != 200:
            logger.warning(f"❌ ElevenLabs hatası: {r.status_code} — {r.text[:200]}")
            return False
        
        with open(output, "wb") as f:
            f.write(r.content)
        
        if os.path.exists(output) and os.path.getsize(output) > 1000:
            logger.info(f"✅ ElevenLabs başarılı: {output}")
            return True
    except Exception as e:
        logger.warning(f"❌ ElevenLabs başarısız: {str(e)[:100]}")
    return False


# ═══════════════════════════════════════════════════════════
# 2. EDGE TTS
# ═══════════════════════════════════════════════════════════

async def _edge_async(text: str, voice: str, rate: str, output: str) -> None:
    import edge_tts
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    await communicate.save(output)


def try_edge_tts(text: str, voice: str, rate: str, output: str) -> bool:
    try:
        asyncio.run(_edge_async(text, voice, rate, output))
        if os.path.exists(output) and os.path.getsize(output) > 1000:
            logger.info(f"✅ Edge TTS başarılı: {output}")
            return True
    except Exception as e:
        logger.warning(f"❌ Edge TTS başarısız: {str(e)[:100]}")
    return False


# ═══════════════════════════════════════════════════════════
# 3. gTTS
# ═══════════════════════════════════════════════════════════

def try_gtts(text: str, output: str, lang: str = "en") -> bool:
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(output)
        if os.path.exists(output) and os.path.getsize(output) > 1000:
            logger.info(f"✅ gTTS başarılı: {output}")
            return True
    except Exception as e:
        logger.warning(f"❌ gTTS başarısız: {str(e)[:100]}")
    return False


# ═══════════════════════════════════════════════════════════
# 4. GOOGLE CLOUD TTS (opsiyonel)
# ═══════════════════════════════════════════════════════════

def try_google_tts(text: str, output: str, voice_name: str = "en-US-Neural2-F") -> bool:
    try:
        api_key = get_env("GOOGLE_TTS_API_KEY", required=False)
        if not api_key:
            logger.warning("GOOGLE_TTS_API_KEY yok, Google TTS atlanıyor.")
            return False
        
        url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}"
        
        payload = {
            "input": {"text": text},
            "voice": {"languageCode": "en-US", "name": voice_name},
            "audioConfig": {
                "audioEncoding": "MP3",
                "speakingRate": 0.95,
                "pitch": 0.0,
            },
        }
        
        r = requests.post(url, json=payload, timeout=30)
        
        if r.status_code != 200:
            logger.warning(f"❌ Google TTS hatası: {r.status_code}")
            return False
        
        audio_content = r.json().get("audioContent")
        if not audio_content:
            return False
        
        with open(output, "wb") as f:
            f.write(base64.b64decode(audio_content))
        
        if os.path.exists(output) and os.path.getsize(output) > 1000:
            logger.info(f"✅ Google TTS başarılı: {output}")
            return True
    except Exception as e:
        logger.warning(f"❌ Google TTS başarısız: {str(e)[:100]}")
    return False


# ═══════════════════════════════════════════════════════════
# ANA FONKSİYON
# ═══════════════════════════════════════════════════════════

def generate_voice(
    text: str,
    output_path: str = "output/voice.mp3",
    voice: str = None,
    rate: str = None,
) -> str:
    """
    Metni sese çevirir. 4 katmanlı fallback:
    1. ElevenLabs (en kaliteli)
    2. Edge TTS
    3. gTTS
    4. Google Cloud TTS
    """
    settings = load_yaml(SETTINGS_PATH)
    voice_cfg = settings.get("voice", {})
    
    voice = voice or voice_cfg.get("voice", "en-US-AriaNeural")
    rate = rate or voice_cfg.get("rate", "+0%")
    
    ensure_dir(os.path.dirname(output_path))
    
    logger.info(f"Seslendirme üretiliyor: {len(text)} karakter")
    
    # 1. ElevenLabs
    if try_elevenlabs(text, output_path):
        size_kb = os.path.getsize(output_path) / 1024
        logger.info(f"Ses hazır (ElevenLabs): {output_path} ({size_kb:.1f} KB)")
        return output_path
    
    # 2. Edge TTS
    logger.warning("ElevenLabs başarısız, Edge TTS deneniyor...")
    if try_edge_tts(text, voice, rate, output_path):
        size_kb = os.path.getsize(output_path) / 1024
        logger.info(f"Ses hazır (Edge TTS): {output_path} ({size_kb:.1f} KB)")
        return output_path
    
    # 3. gTTS
    logger.warning("Edge TTS başarısız, gTTS deneniyor...")
    if try_gtts(text, output_path, lang="en"):
        size_kb = os.path.getsize(output_path) / 1024
        logger.info(f"Ses hazır (gTTS): {output_path} ({size_kb:.1f} KB)")
        return output_path
    
    # 4. Google Cloud TTS
    logger.warning("gTTS başarısız, Google Cloud TTS deneniyor...")
    if try_google_tts(text, output_path):
        size_kb = os.path.getsize(output_path) / 1024
        logger.info(f"Ses hazır (Google TTS): {output_path} ({size_kb:.1f} KB)")
        return output_path
    
    raise RuntimeError("Hiçbir TTS motoru çalışmadı.")


def list_voices(language: str = "en-US") -> list:
    """Kullanılabilir Edge TTS seslerini listeler."""
    async def _list():
        import edge_tts
        return await edge_tts.list_voices()
    
    try:
        voices = asyncio.run(_list())
        return [v for v in voices if v["Locale"].startswith(language)]
    except Exception as e:
        logger.warning(f"Ses listesi alınamadı: {e}")
        return []


if __name__ == "__main__":
    test_text = (
        "A man was spoken through by a child. No one noticed. "
        "Stanley Milgram tested whether people would accept another person's words as their own. "
        "So whose thoughts are really yours? Follow for more."
    )
    
    path = generate_voice(test_text, output_path="output/test_voice.mp3")
    print(f"Ses üretildi: {path}")