"""
script_generator.py — Gemini API ile 16 saniyelik Shorts senaryosu üretir.
Konu bilgisi alır, JSON formatında senaryo döner.

Model adı otomatik seçilir: kullanılabilir modeller listelenir,
tercih sırasına göre en iyisi kullanılır. Model kaldırılsa bile
sistem otomatik yeni modele geçer.
"""

import json
import re
import google.generativeai as genai
from .utils import load_json, get_env, setup_logging

logger = setup_logging()

PROMPTS_PATH = "config/prompts.json"
STYLE_PATH = "config/style.json"

# Tercih edilen modeller (yeniden eskiye)
PREFERRED_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.0-flash",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-flash-latest",
    "gemini-pro-latest",
]


def pick_model() -> str:
    """
    Kullanılabilir modeller arasından en iyisini seçer.
    1. Tercih listesindekileri dener.
    2. Yoksa generateContent destekleyen ilk modeli alır.
    """
    available = []
    try:
        for m in genai.list_models():
            methods = getattr(m, "supported_generation_methods", []) or []
            if "generateContent" in methods:
                available.append(m.name.replace("models/", ""))
    except Exception as e:
        logger.warning(f"Model listesi alınamadı: {e}")
        return PREFERRED_MODELS[0]
    
    logger.info(f"Kullanılabilir modeller: {available[:15]}")
    
    # Tercih sırasına göre ara
    for preferred in PREFERRED_MODELS:
        if preferred in available:
            logger.info(f"Model seçildi (tercih): {preferred}")
            return preferred
    
    # Tercih listesinde yoksa, "flash" içeren ilk modeli al
    for name in available:
        if "flash" in name.lower():
            logger.info(f"Model seçildi (flash): {name}")
            return name
    
    # Hiçbiri yoksa ilk uygun modeli al
    if available:
        logger.warning(f"Tercih edilen model yok, {available[0]} kullanılıyor.")
        return available[0]
    
    raise RuntimeError("Kullanılabilir Gemini modeli bulunamadı. API key kontrol et.")


def configure_gemini():
    """Gemini API'yi yapılandırır ve uygun modeli döner."""
    api_key = get_env("GEMINI_API_KEY")
    genai.configure(api_key=api_key)
    
    model_name = pick_model()
    return genai.GenerativeModel(model_name)


def build_prompt(topic: dict, prompts: dict, style: dict) -> str:
    """Konu ve stil bilgisinden prompt üretir."""
    template = prompts["script_generation"]["user_template"]
    
    # Format string yerine replace kullan (JSON içindeki {} sorun çıkarmasın)
    prompt = template.replace("{{topic_title}}", topic.get("title", ""))
    prompt = prompt.replace("{{topic_seed}}", topic.get("seed", ""))
    prompt = prompt.replace("{{topic_source}}", topic.get("source", ""))
    
    # Eski stil (tek süslü parantez) için de destek
    prompt = prompt.replace("{topic_title}", topic.get("title", ""))
    prompt = prompt.replace("{topic_seed}", topic.get("seed", ""))
    prompt = prompt.replace("{topic_source}", topic.get("source", ""))
    
    # Stil bilgisini ekle
    prompt += f"\n\nVisual style: {style.get('prompt_suffix', '')}"
    prompt += f"\nNegative: {style.get('negative_prompt', '')}"
    
    return prompt


def extract_json(text: str) -> dict:
    """Model çıktısından JSON bloğunu ayıklar."""
    # ```json ... ``` bloğunu bul
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    
    # Direkt JSON'u bul (ilk { ile son } arası)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    
    raise ValueError(f"JSON bulunamadı:\n{text[:500]}")


def validate_script(script: dict) -> dict:
    """Senaryo alanlarını doğrular ve eksikleri tamamlar."""
    required = ["title", "hook", "context", "climax", "outro", "description", "tags"]
    
    for field in required:
        if field not in script:
            script[field] = "" if field != "tags" else []
    
    if not script["outro"]:
        script["outro"] = "Follow for more."
    
    # Toplam kelime kontrolü (40-50 ideal)
    total = " ".join([
        script["hook"],
        script["context"],
        script["climax"],
        script["outro"],
    ])
    word_count = len(total.split())
    
    if word_count > 60:
        logger.warning(f"Senaryo uzun: {word_count} kelime")
    elif word_count < 30:
        logger.warning(f"Senaryo kısa: {word_count} kelime")
    
    script["_word_count"] = word_count
    return script


def generate_script(topic: dict) -> dict:
    """
    Ana fonksiyon: Konu alır, senaryo döner.
    
    Dönen yapı:
    {
        "title": "...",
        "hook": "...",
        "context": "...",
        "climax": "...",
        "outro": "Follow for more.",
        "description": "...",
        "tags": ["..."],
        "_word_count": 45
    }
    """
    logger.info(f"Senaryo üretiliyor: {topic.get('title', '?')}")
    
    prompts = load_json(PROMPTS_PATH)
    style = load_json(STYLE_PATH)
    model = configure_gemini()
    
    system_prompt = prompts["script_generation"]["system"]
    user_prompt = build_prompt(topic, prompts, style)
    
    full_prompt = f"{system_prompt}\n\n{user_prompt}"
    
    try:
        response = model.generate_content(full_prompt)
        text = response.text
    except Exception as e:
        logger.error(f"Gemini hatası: {e}")
        raise
    
    script = extract_json(text)
    script = validate_script(script)
    
    # Kaynak bilgisini ekle
    script["source"] = topic.get("source", "")
    
    logger.info(f"Senaryo hazır: {script['_word_count']} kelime")
    return script


def generate_voiceover_text(script: dict) -> str:
    """Senaryodan seslendirme metnini üretir."""
    return " ".join([
        script["hook"],
        script["context"],
        script["climax"],
        script["outro"],
    ])


if __name__ == "__main__":
    # Test
    test_topic = {
        "id": "test_001",
        "title": "The Cyranoid Experiment",
        "seed": "Stanley Milgram tested whether people would accept another person's words as their own.",
        "source": "Milgram, 1984",
    }
    
    script = generate_script(test_topic)
    print(json.dumps(script, indent=2, ensure_ascii=False))
    print("\n--- Voiceover ---")
    print(generate_voiceover_text(script))