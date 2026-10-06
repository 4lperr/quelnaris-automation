"""
video_assembler.py — Görsellerden Ken Burns videoları üretir, ses ve müzikle birleştirir.
FFmpeg kullanır. 8+8 saniyelik iki parça halinde üretir.
"""

import os
import subprocess
from .utils import load_yaml, ensure_dir, setup_logging

logger = setup_logging()

SETTINGS_PATH = "config/settings.yaml"


def run_ffmpeg(cmd: list, step: str) -> None:
    """FFmpeg komutunu çalıştırır, hata olursa loglar."""
    logger.info(f"FFmpeg: {step}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg hatası ({step}):\n{e.stderr[-2000:]}")
        raise


def get_video_settings() -> dict:
    """Ayarları okur."""
    settings = load_yaml(SETTINGS_PATH)
    return {
        "video": settings.get("video", {}),
        "ken_burns": settings.get("ken_burns", {}),
        "music": settings.get("music", {}),
        "paths": settings.get("paths", {}),
    }


def make_ken_burns_clip(
    image_path: str,
    output_path: str,
    duration: int,
    width: int,
    height: int,
    fps: int,
    zoom_speed: float,
    max_zoom: float,
    direction: str = "in",
) -> str:
    """
    Tek görselden Ken Burns efekti ile video klip üretir.
    
    Args:
        image_path: Görsel dosyası
        output_path: Çıktı video
        duration: Saniye
        direction: "in" (yakınlaş) veya "out" (uzaklaş)
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Görsel yok: {image_path}")
    
    frames = duration * fps
    
    if direction == "in":
        zoom_expr = f"min(zoom+{zoom_speed},{max_zoom})"
    else:
        zoom_expr = f"if(lte(zoom,1.0),{max_zoom},max(1.001,zoom-{zoom_speed}))"
    
    vf = (
        f"scale={width*2}:{height*2},"
        f"zoompan=z='{zoom_expr}':d={frames}:s={width}x{height}:fps={fps},"
        f"format=yuv420p"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", image_path,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        output_path,
    ]
    
    run_ffmpeg(cmd, f"Ken Burns: {os.path.basename(image_path)}")
    return output_path


def concat_clips(clip_paths: list, output_path: str) -> str:
    """Birden fazla videoyu birleştirir (ara reklamsız, tek akış)."""
    list_file = "output/_concat_list.txt"
    ensure_dir("output")
    
    with open(list_file, "w", encoding="utf-8") as f:
        for clip in clip_paths:
            abs_path = os.path.abspath(clip).replace("\\", "/")
            f.write(f"file '{abs_path}'\n")
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        output_path,
    ]
    
    run_ffmpeg(cmd, "Klip birleştirme")
    return output_path


def add_audio(
    video_path: str,
    voice_path: str,
    music_path: str,
    output_path: str,
    music_volume: float = 0.2,
) -> str:
    """Videoya seslendirme + arka plan müziği ekler."""
    if not os.path.exists(voice_path):
        raise FileNotFoundError(f"Ses yok: {voice_path}")
    
    if music_path and os.path.exists(music_path):
        # Ses + müzik
        filter_complex = (
            f"[1:a]volume=1.0[voice];"
            f"[2:a]volume={music_volume}[music];"
            f"[voice][music]amix=inputs=2:duration=first:dropout_transition=2[a]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", voice_path,
            "-i", music_path,
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_path,
        ]
        run_ffmpeg(cmd, "Ses + müzik ekleme")
    else:
        # Sadece ses
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", voice_path,
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_path,
        ]
        run_ffmpeg(cmd, "Ses ekleme")
    
    return output_path


def add_color_grade_and_grain(input_path: str, output_path: str) -> str:
    """Renk düzeltme + film grain ekler."""
    vf = (
        "eq=contrast=1.1:brightness=-0.05:saturation=0.9,"
        "noise=alls=8:allf=t,"
        "format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-c:a", "copy",
        output_path,
    ]
    run_ffmpeg(cmd, "Renk + grain")
    return output_path


def build_video(
    image_paths: list,
    voice_path: str,
    music_path: str = None,
    output_path: str = "output/final.mp4",
    script: dict = None,
) -> str:
    """
    Ana fonksiyon: Görsellerden + sesten + müzikten tam video üretir.
    
    Args:
        image_paths: 4 görsel yolu
        voice_path: Seslendirme dosyası
        music_path: Arka plan müziği (opsiyonel)
        output_path: Çıktı video
        script: Senaryo (opsiyonel, log için)
    
    Returns:
        Oluşturulan video yolu
    """
    cfg = get_video_settings()
    video_cfg = cfg["video"]
    kb_cfg = cfg["ken_burns"]
    music_cfg = cfg["music"]
    
    width = video_cfg.get("width", 1080)
    height = video_cfg.get("height", 1920)
    fps = video_cfg.get("fps", 30)
    duration = video_cfg.get("duration_seconds", 16)
    zoom_speed = kb_cfg.get("zoom_speed", 0.0015)
    max_zoom = kb_cfg.get("max_zoom", 1.5)
    music_volume = music_cfg.get("volume", 0.2)
    
    if len(image_paths) < 4:
        raise ValueError(f"En az 4 görsel gerekli, {len(image_paths)} verildi.")
    
    ensure_dir("output")
    
    # 1. Her görselden Ken Burns klip
    logger.info("Adım 1/5: Ken Burns klipleri üretiliyor...")
    clip_duration = duration // 4  # 16/4 = 4 saniye
    directions = ["in", "out", "in", "out"]
    
    clips = []
    for i, img in enumerate(image_paths[:4]):
        clip_path = f"output/_clip{i+1}.mp4"
        make_ken_burns_clip(
            image_path=img,
            output_path=clip_path,
            duration=clip_duration,
            width=width,
            height=height,
            fps=fps,
            zoom_speed=zoom_speed,
            max_zoom=max_zoom,
            direction=directions[i],
        )
        clips.append(clip_path)
    
    # 2. Klipleri birleştir
    logger.info("Adım 2/5: Klipler birleştiriliyor...")
    merged = "output/_merged.mp4"
    concat_clips(clips, merged)
    
    # 3. Ses + müzik ekle
    logger.info("Adım 3/5: Ses ekleniyor...")
    with_audio = "output/_with_audio.mp4"
    add_audio(merged, voice_path, music_path, with_audio, music_volume)
    
    # 4. Renk + grain
    logger.info("Adım 4/5: Renk düzeltme + grain...")
    add_color_grade_and_grain(with_audio, output_path)
    
    # 5. Temizlik
    logger.info("Adım 5/5: Geçici dosyalar temizleniyor...")
    for f in clips + [merged, with_audio]:
        if os.path.exists(f):
            os.remove(f)
    
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    logger.info(f"Video hazır: {output_path} ({size_mb:.1f} MB)")
    
    return output_path


if __name__ == "__main__":
    # Test: 4 görsel + ses + müzik varsa
    images = [f"output/img{i}.jpg" for i in range(1, 5)]
    voice = "output/voice.mp3"
    music = None  # opsiyonel
    
    if all(os.path.exists(p) for p in images) and os.path.exists(voice):
        path = build_video(images, voice, music)
        print(f"Video: {path}")
    else:
        print("Test için 4 görsel ve ses dosyası gerekli.")
        print("Beklenen:")
        for p in images:
            print(f"  {p} — {'✅' if os.path.exists(p) else '❌'}")
        print(f"  {voice} — {'✅' if os.path.exists(voice) else '❌'}")