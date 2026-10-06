"""
main.py — Quelnaris otomasyonunun ana akışı.

Akış:
    1. Konu seç
    2. Senaryo üret (Gemini)
    3. Seslendirme üret (ElevenLabs/gTTS/Edge TTS)
    4. Görselleri üret (Gemini görsel)
    5. Video birleştir (Ken Burns + FFmpeg)
    6. Altyazı üret (Whisper) + göm
    7. YouTube'a yükle
    8. Gmail ile bildir

Her adım loglanır. Hata olursa Gmail ile bildirilir.
"""

import os
import sys
import time
import traceback
from datetime import datetime

# Yerel modüller
from .utils import (
    setup_logging,
    ensure_dir,
    load_json,
    load_yaml,
    get_env,
    now_utc,
    clean_filename,
)
from .topic_selector import select_topic, get_stats
from .script_generator import generate_script, generate_voiceover_text
from .voice_generator import generate_voice
from .visual_generator import generate_all_images, get_image_paths
from .video_assembler import build_video
from .subtitle_generator import generate_subtitles, burn_subtitles
from .youtube_uploader import upload_video
from .notifier import notify_success, notify_error, notify_daily_summary

logger = setup_logging()

SETTINGS_PATH = "config/settings.yaml"
OUTPUT_DIR = "output"


# ═══════════════════════════════════════════════════════════
# YARDIMCI
# ═══════════════════════════════════════════════════════════

def banner(text: str) -> None:
    """Log'a başlık basar."""
    line = "═" * 60
    logger.info(line)
    logger.info(f"  {text}")
    logger.info(line)


def step(number: int, total: int, text: str) -> None:
    """Adım başlığı."""
    logger.info(f"[{number}/{total}] {text}")


def cleanup_output(keep_images: bool = False) -> None:
    """Önceki çalıştırmadan kalan geçici dosyaları temizler."""
    if not os.path.exists(OUTPUT_DIR):
        return
    
    keep = {"visual_prompts.json", "used_topics.json"}
    if keep_images:
        keep.update({f"img{i}.jpg" for i in range(1, 5)})
    
    for f in os.listdir(OUTPUT_DIR):
        path = os.path.join(OUTPUT_DIR, f)
        if os.path.isfile(path) and f not in keep:
            try:
                os.remove(path)
            except Exception as e:
                logger.warning(f"Temizlik hatası ({f}): {e}")


def find_music() -> str:
    """assets/music/ içinden rastgele bir müzik seçer."""
    music_dir = "assets/music"
    if not os.path.exists(music_dir):
        logger.warning(f"Müzik klasörü yok: {music_dir}")
        return None
    
    tracks = [
        os.path.join(music_dir, f)
        for f in os.listdir(music_dir)
        if f.lower().endswith((".mp3", ".wav", ".m4a"))
    ]
    
    if not tracks:
        logger.warning("Müzik dosyası bulunamadı.")
        return None
    
    import random
    return random.choice(tracks)


# ═══════════════════════════════════════════════════════════
# ANA AKIŞ
# ═══════════════════════════════════════════════════════════

def run_pipeline() -> dict:
    """
    Tam üretim akışını çalıştırır.
    
    Returns:
        {
            "status": "success" | "error",
            "video_url": "...",
            "video_path": "...",
            "script": {...},
            "error": "..."
        }
    """
    start_time = time.time()
    result = {
        "status": "error",
        "video_url": None,
        "video_path": None,
        "script": None,
        "error": None,
    }
    
    banner(f"QUELNARIS OTOMASYON — {now_utc()}")
    logger.info(f"Python: {sys.version.split()[0]}")
    logger.info(f"Çalışma dizini: {os.getcwd()}")
    
    settings = load_yaml(SETTINGS_PATH)
    ensure_dir(OUTPUT_DIR)
    ensure_dir("logs")
    
    # Temizlik (görselleri koru, belki önceki çalıştırmadan kalmıştır)
    cleanup_output(keep_images=False)
    
    total_steps = 8
    
    try:
        # ─── 1. Konu seç ─────────────────────────────
        step(1, total_steps, "Konu seçiliyor...")
        topic = select_topic()
        logger.info(f"  Konu: {topic['title']}")
        logger.info(f"  Kategori: {topic.get('category', '?')}")
        logger.info(f"  Kaynak: {topic.get('source', '?')}")
        
        # ─── 2. Senaryo üret ─────────────────────────
        step(2, total_steps, "Senaryo üretiliyor (Gemini)...")
        script = generate_script(topic)
        script["_topic_id"] = topic["id"]
        script["_source"] = topic.get("source", "")
        logger.info(f"  Başlık: {script['title']}")
        logger.info(f"  Kelime: {script.get('_word_count', '?')}")
        
        voiceover_text = generate_voiceover_text(script)
        logger.info(f"  Seslendirme metni: {voiceover_text[:80]}...")
        result["script"] = script
        
        # ─── 3. Seslendirme ──────────────────────────
        step(3, total_steps, "Seslendirme üretiliyor...")
        voice_path = os.path.join(OUTPUT_DIR, "voice.mp3")
        generate_voice(voiceover_text, output_path=voice_path)
        logger.info(f"  Ses: {voice_path}")
        
        # ─── 4. Görselleri üret (Gemini) ─────────────
        step(4, total_steps, "Görseller üretiliyor (Gemini)...")
        image_paths = generate_all_images(script)
        
        # Eksik görsel kontrolü
        missing = [p for p in image_paths if not p or not os.path.exists(p)]
        if missing:
            logger.error(f"Eksik görseller: {missing}")
            notify_error(
                "Görsel Üretimi",
                f"Bazı görseller üretilemedi: {missing}",
                context={
                    "topic": topic["title"],
                    "missing": str(missing),
                },
            )
            result["status"] = "error"
            result["error"] = f"Görsel üretilemedi: {missing}"
            return result
        
        logger.info(f"  {len(image_paths)} görsel hazır.")
        
        # ─── 5. Video birleştir ──────────────────────
        step(5, total_steps, "Video birleştiriliyor (Ken Burns + FFmpeg)...")
        music_path = find_music()
        if music_path:
            logger.info(f"  Müzik: {music_path}")
        else:
            logger.warning("  Müzik yok, sadece seslendirme.")
        
        raw_video = os.path.join(OUTPUT_DIR, "raw_video.mp4")
        build_video(
            image_paths=image_paths,
            voice_path=voice_path,
            music_path=music_path,
            output_path=raw_video,
            script=script,
        )
        logger.info(f"  Ham video: {raw_video}")
        
        # ─── 6. Altyazı ──────────────────────────────
        step(6, total_steps, "Altyazı üretiliyor (Whisper)...")
        final_video = os.path.join(OUTPUT_DIR, "final.mp4")
        
        try:
            ass_path = generate_subtitles(voice_path, model_size="base")
            if ass_path and os.path.exists(ass_path):
                burn_subtitles(raw_video, ass_path, final_video)
                logger.info(f"  Altyazılı video: {final_video}")
            else:
                logger.warning("  Altyazı üretilemedi, ham video kullanılacak.")
                if os.path.exists(raw_video) and not os.path.exists(final_video):
                    os.rename(raw_video, final_video)
        except Exception as e:
            logger.warning(f"  Altyazı hatası: {e}. Ham video kullanılacak.")
            if os.path.exists(raw_video) and not os.path.exists(final_video):
                os.rename(raw_video, final_video)
        
        if not os.path.exists(final_video):
            raise RuntimeError("Final video oluşmadı.")
        
        result["video_path"] = final_video
        
        # ─── 7. YouTube'a yükle ──────────────────────
        step(7, total_steps, "YouTube'a yükleniyor...")
        
        # Başlık temizle
        script["title"] = clean_filename(script.get("title", "Quelnaris"))[:100]
        
        try:
            upload_result = upload_video(final_video, script)
            result["video_url"] = upload_result["url"]
            logger.info(f"  Video: {upload_result['url']}")
        except Exception as e:
            logger.warning(f"  YouTube yükleme hatası: {e}")
            logger.warning("  Video artifact olarak kaydedildi.")
            result["video_url"] = None
            # YouTube hatası kritik değil, devam et
        
        # ─── 8. Başarılı ────────────────────────────
        step(8, total_steps, "Tamamlandı.")
        elapsed = time.time() - start_time
        logger.info(f"✅ TAMAMLANDI — {elapsed:.0f} saniye")
        
        # Başarı maili
        try:
            notify_success(script, result.get("video_url") or "Artifact olarak kaydedildi", final_video)
        except Exception as e:
            logger.warning(f"Başarı maili gönderilemedi: {e}")
        
        # Günlük özet
        try:
            stats = get_stats()
            notify_daily_summary(stats)
        except Exception as e:
            logger.warning(f"Özet maili gönderilemedi: {e}")
        
        result["status"] = "success"
        return result
    
    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = f"{type(e).__name__}: {e}"
        tb = traceback.format_exc()
        
        logger.error(f"❌ HATA — {elapsed:.0f} saniye")
        logger.error(error_msg)
        logger.error(tb)
        
        result["status"] = "error"
        result["error"] = error_msg
        
        # Hata maili
        try:
            notify_error(
                step="Ana Akış",
                error=error_msg,
                context={
                    "traceback": tb[-1500:],
                    "elapsed_seconds": f"{elapsed:.0f}",
                    "script_title": result.get("script", {}).get("title", "?") if result.get("script") else "?",
                },
            )
        except Exception as notify_err:
            logger.error(f"Bildirim gönderilemedi: {notify_err}")
        
        return result


# ═══════════════════════════════════════════════════════════
# GİRİŞ NOKTASI
# ═══════════════════════════════════════════════════════════

def main() -> int:
    """
    Ana giriş noktası.
    
    Returns:
        0 = başarı, 1 = hata
    """
    try:
        result = run_pipeline()
        
        if result["status"] == "success":
            if result.get("video_url"):
                logger.info(f"Video yayında: {result['video_url']}")
            else:
                logger.info(f"Video hazır (artifact): {result.get('video_path')}")
            return 0
        else:
            logger.error(f"Hata: {result['error']}")
            return 1
    
    except KeyboardInterrupt:
        logger.warning("Kullanıcı tarafından durduruldu.")
        return 130
    
    except Exception as e:
        logger.critical(f"Beklenmeyen hata: {e}")
        logger.critical(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())