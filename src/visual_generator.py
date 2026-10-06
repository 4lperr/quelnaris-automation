"""
visual_generator.py — Gemini ile görsel üretir.

Model: gemini-3.1-flash-image (ana)
Fallback: gemini-2.5-flash-image

Senaryodan 4 sahne promptu üretir, her biri için görsel oluşturur,
output/img1.jpg ... img4.jpg olarak kaydeder.
"""

import os
import json
import base64
from datetime import datetime
from io import BytesIO

from .utils import load_json, load_yaml, save_json, ensure_dir, get_env, setup_logging

logger = setup_logging()

PROMPTS_PATH = "config/prompts.json"
STYLE_PATH = "config/style.json"
SETTINGS_PATH = "config/settings.yaml"

# Gemini görsel modelleri (öncelik sırası)
IMAGE_MODELS = [
    "gemini-3.1-flash-image",
    "gemini-3.1-flash-image-preview",
    "gemini-2.5-flash-image",
    "gemini-3-pro-image",
]


def _configure_genai():
    """Gemini API'yi yapılandırır."""
    import google.generativeai as genai
    api_key = get_env("GEMINI_API_KEY")
    genai.configure(api_key=api_key)
    return genai


def _pick_image_model(genai):
    """Görsel üretebilen bir model seçer."""
    try:
        available = []
        for m in genai.list_models():
            name = m if isinstance(m, str) else m.name
            name = name.replace("models/", "")
            available.append(name)
        
        for preferred in IMAGE_MODELS:
            if preferred in available:
                logger.info(f"Görsel modeli seçildi: {preferred}")
                return preferred
        
        # Fallback: image içeren ilk model
        for name in available:
            if "image" in name.lower() and "embedding" not in name.lower():
                logger.info(f"Görsel modeli seçildi (fallback): {name}")
                return name
    except Exception as e:
        logger.warning(f"Model listesi alınamadı: {e}")
    
    logger.warning(f"Varsayılan model kullanılıyor: {IMAGE_MODELS[0]}")
    return IMAGE_MODELS[0]


def build_scene_prompts(script: dict) -> list:
    """Senaryodan 4 sahne için görsel prompt üretir."""
    prompts_cfg = load_json(PROMPTS_PATH)
    style = load_json(STYLE_PATH)
    
    scenes_cfg = prompts_cfg["visual_generation"]["scenes"]
    style_suffix = style.get("prompt_suffix", "")
    negative = style.get("negative_prompt", "")
    
    # Senaryodan görsel ipuçları çıkar
    hook_visual = _visual_hint(script.get("hook", ""))
    context_visual = _visual_hint(script.get("context", ""))
    climax_visual = _visual_hint(script.get("climax", ""))
    outro_visual = "half-open door with blood red light, abstract shadow"
    
    visuals = [hook_visual, context_visual, climax_visual, outro_visual]
    
    scenes = []
    for i, scene_cfg in enumerate(scenes_cfg):
        prompt = scene_cfg["prompt_template"].format(
            hook_visual=visuals[0],
            context_visual=visuals[1],
            climax_visual=visuals[2],
        )
        
        full_prompt = f"{prompt} {style_suffix}"
        
        scenes.append({
            "scene": i + 1,
            "duration": scene_cfg["duration"],
            "prompt": full_prompt,
            "negative_prompt": negative,
            "width": 1080,
            "height": 1920,
        })
    
    return scenes


def _visual_hint(text: str) -> str:
    """Metinden görsel ipucu çıkarır."""
    keywords = {
        "man": "silhouette of a man in dark room",
        "woman": "silhouette of a woman in dark room",
        "child": "young child silhouette in shadow",
        "eye": "extreme close-up of human eye",
        "door": "half-open door with red light",
        "file": "old case file folder on desk",
        "brain": "human brain with red glow",
        "mirror": "cracked mirror in dark room",
        "police": "police lights in dark street",
        "missing": "blurred missing person poster",
        "phone": "old phone on wooden table",
        "photo": "faded photograph on table",
        "experiment": "vintage psychology lab, dim light",
        "death": "empty chair in dark room",
        "hospital": "empty hospital corridor at night",
        "light": "floating mysterious light in dark forest",
        "house": "abandoned house at night",
        "forest": "dark misty forest",
        "road": "empty country road at night",
        "car": "old car on dark road",
        "mirror": "cracked mirror in dim room",
        "clock": "old clock showing midnight",
        "book": "open ancient book on table",
        "letter": "old handwritten letter on desk",
    }
    
    text_lower = text.lower()
    for key, visual in keywords.items():
        if key in text_lower:
            return visual
    
    return "dark abstract cinematic scene, shadow and light"


def generate_image_with_gemini(model_name: str, prompt: str, output_path: str) -> bool:
    """
    Gemini ile tek görsel üretir.
    Başarılıysa True döner.
    """
    try:
        import google.generativeai as genai
        _configure_genai()
        
        model = genai.GenerativeModel(model_name)
        
        # Gemini görsel üretim promptu
        full_prompt = (
            f"Generate a vertical 9:16 cinematic image: {prompt}\n\n"
            f"Style: dark, mysterious, film grain, high contrast, "
            f"blood red accents, deep blacks. "
            f"NO text, NO letters, NO words, NO watermark."
        )
        
        response = model.generate_content(full_prompt)
        
        # Response içinden görsel verisini al
        image_saved = False
        
        # Yöntem 1: response.candidates[0].content.parts içinden
        try:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    data = part.inline_data.data
                    if isinstance(data, str):
                        data = base64.b64decode(data)
                    with open(output_path, "wb") as f:
                        f.write(data)
                    image_saved = True
                    break
        except Exception as e:
            logger.debug(f"Yöntem 1 başarısız: {e}")
        
        # Yöntem 2: response.parts içinden
        if not image_saved:
            try:
                for part in response.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        data = part.inline_data.data
                        if isinstance(data, str):
                            data = base64.b64decode(data)
                        with open(output_path, "wb") as f:
                            f.write(data)
                        image_saved = True
                        break
            except Exception as e:
                logger.debug(f"Yöntem 2 başarısız: {e}")
        
        if image_saved and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            logger.info(f"✅ Görsel üretildi: {output_path}")
            return True
        else:
            logger.warning(f"❌ Görsel üretilemedi: {prompt[:80]}")
            return False
    
    except Exception as e:
        logger.warning(f"❌ Gemini görsel hatası: {str(e)[:200]}")
        return False


def generate_all_images(script: dict) -> list:
    """
    Senaryodan 4 görsel üretir.
    Döner: [img1_path, img2_path, img3_path, img4_path]
    """
    logger.info("Görseller üretiliyor (Gemini)...")
    
    genai = _configure_genai()
    model_name = _pick_image_model(genai)
    
    scenes = build_scene_prompts(script)
    ensure_dir("output")
    
    # Promptları JSON'a kaydet (log için)
    save_json({
        "title": script.get("title", ""),
        "created": datetime.utcnow().isoformat(),
        "model": model_name,
        "scenes": scenes,
    }, "output/visual_prompts.json")
    
    image_paths = []
    
    for scene in scenes:
        img_path = f"output/img{scene['scene']}.jpg"
        
        # Zaten varsa atla
        if os.path.exists(img_path) and os.path.getsize(img_path) > 1000:
            logger.info(f"Görsel zaten var: {img_path}")
            image_paths.append(img_path)
            continue
        
        # Üret
        success = generate_image_with_gemini(model_name, scene["prompt"], img_path)
        
        if not success:
            # Fallback model dene
            for fallback in IMAGE_MODELS:
                if fallback == model_name:
                    continue
                logger.info(f"Fallback deneniyor: {fallback}")
                if generate_image_with_gemini(fallback, scene["prompt"], img_path):
                    success = True
                    break
        
        if success:
            image_paths.append(img_path)
        else:
            logger.error(f"Görsel {scene['scene']} üretilemedi.")
            image_paths.append(None)
    
    success_count = sum(1 for p in image_paths if p and os.path.exists(p))
    logger.info(f"{success_count}/4 görsel hazır.")
    
    return image_paths


def get_image_paths(count: int = 4) -> list:
    """Beklenen görsel yollarını döner."""
    return [f"output/img{i+1}.jpg" for i in range(count)]


def check_images_exist(count: int = 4) -> bool:
    """Görsellerin var olup olmadığını kontrol eder."""
    paths = get_image_paths(count)
    missing = [p for p in paths if not os.path.exists(p)]
    
    if missing:
        logger.warning(f"Eksik görseller: {missing}")
        return False
    
    logger.info(f"{count} görsel hazır.")
    return True


if __name__ == "__main__":
    test_script = {
        "title": "The Spook Light",
        "hook": "A floating light has haunted this Missouri road since 1886.",
        "context": "Studied by Missouri State University researchers.",
        "climax": "No one has ever explained it.",
        "outro": "Follow for more.",
    }
    
    paths = generate_all_images(test_script)
    print(f"\nSonuç: {paths}")