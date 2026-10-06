"""
subtitle_generator.py — Whisper ile altyazı üretir, ASS formatında videoya ekler.
Whisper: OpenAI'nin ücretsiz, yerel çalışan speech-to-text modeli.
GitHub Actions'ta faster-whisper ile hızlı çalışır.
"""

import os
import subprocess
from .utils import load_yaml, ensure_dir, setup_logging

logger = setup_logging()

SETTINGS_PATH = "config/settings.yaml"


def transcribe_audio(audio_path: str, model_size: str = "base") -> list:
    """
    Ses dosyasını Whisper ile metne çevirir, kelime zamanlamalarını döner.
    
    Args:
        audio_path: Ses dosyası (mp3, wav)
        model_size: tiny / base / small / medium / large
    
    Returns:
        [{"word": "...", "start": 0.5, "end": 0.9}, ...]
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        logger.error("faster-whisper kurulu değil. 'pip install faster-whisper'")
        raise
    
    logger.info(f"Whisper yükleniyor: {model_size}")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    
    logger.info(f"Transkripsiyon: {audio_path}")
    segments, info = model.transcribe(
        audio_path,
        word_timestamps=True,
        language="en",
        vad_filter=True,
    )
    
    words = []
    for segment in segments:
        if segment.words:
            for w in segment.words:
                words.append({
                    "word": w.word.strip(),
                    "start": round(w.start, 2),
                    "end": round(w.end, 2),
                })
    
    logger.info(f"{len(words)} kelime bulundu ({info.duration:.1f}sn)")
    return words


def group_words_into_lines(words: list, max_words: int = 3) -> list:
    """Kelimeleri 2-3'lü gruplara ayırır (Shorts altyazı stili)."""
    lines = []
    for i in range(0, len(words), max_words):
        chunk = words[i:i + max_words]
        if not chunk:
            continue
        lines.append({
            "text": " ".join(w["word"] for w in chunk),
            "start": chunk[0]["start"],
            "end": chunk[-1]["end"],
        })
    return lines


def format_timestamp(seconds: float) -> str:
    """Saniyeyi ASS zaman formatına çevirir: H:MM:SS.cc"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass_subtitles(lines: list, settings: dict) -> str:
    """ASS formatında altyazı dosyası içeriği üretir."""
    sub_cfg = settings.get("subtitles", {})
    font = sub_cfg.get("font", "Inter")
    font_size = sub_cfg.get("font_size", 18)
    color = sub_cfg.get("color", "&HFFFFFF&")
    outline_color = sub_cfg.get("outline_color", "&H000000&")
    outline_width = sub_cfg.get("outline_width", 2)
    
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{font_size},{color},&H000000FF,{outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,{outline_width},1,2,60,60,300,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    events = []
    for line in lines:
        start = format_timestamp(line["start"])
        end = format_timestamp(line["end"])
        text = line["text"].replace("\n", " ").strip()
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    
    return header + "\n".join(events) + "\n"


def generate_subtitles(
    audio_path: str,
    output_ass: str = "output/subtitles.ass",
    model_size: str = "base",
) -> str:
    """
    Ana fonksiyon: Ses dosyasından ASS altyazı üretir.
    
    Args:
        audio_path: Ses dosyası
        output_ass: Çıktı ASS yolu
        model_size: Whisper model boyutu
    
    Returns:
        Oluşturulan ASS dosyası
    """
    settings = load_yaml(SETTINGS_PATH)
    
    logger.info("Altyazı üretiliyor...")
    words = transcribe_audio(audio_path, model_size)
    
    if not words:
        logger.warning("Kelime bulunamadı, altyazı boş.")
        return ""
    
    lines = group_words_into_lines(words, max_words=3)
    ass_content = build_ass_subtitles(lines, settings)
    
    ensure_dir(os.path.dirname(output_ass))
    with open(output_ass, "w", encoding="utf-8") as f:
        f.write(ass_content)
    
    logger.info(f"Altyazı hazır: {output_ass} ({len(lines)} satır)")
    return output_ass


def burn_subtitles(video_path: str, ass_path: str, output_path: str) -> str:
    """
    ASS altyazıyı videoya gömer (hardcode).
    ASS kullanılır çünkü stil, font, renk kontrolü daha iyi.
    """
    if not os.path.exists(ass_path):
        logger.warning("Altyazı dosyası yok, atlanıyor.")
        return video_path
    
    # ASS yolunu FFmpeg için escape et
    ass_escaped = ass_path.replace("\\", "/").replace(":", "\\:")
    
    vf = f"ass='{ass_escaped}'"
    
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-c:a", "copy",
        output_path,
    ]
    
    logger.info("Altyazı videoya gömülüyor...")
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Altyazı gömme hatası:\n{e.stderr[-2000:]}")
        raise
    
    logger.info(f"Altyazılı video hazır: {output_path}")
    return output_path


if __name__ == "__main__":
    # Test: output/voice.mp3 varsa
    voice = "output/voice.mp3"
    if os.path.exists(voice):
        ass = generate_subtitles(voice)
        print(f"ASS: {ass}")
    else:
        print(f"Test için ses dosyası gerekli: {voice}")