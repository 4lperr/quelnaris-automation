"""
script_generator.py — Gemini API ile 16 saniyelik Shorts senaryosu üretir.
Konu bilgisi alır, JSON formatında senaryo döner.

Özellikler:
- Model adı otomatik seçilir (kullanılabilir modeller listelenir)
- 429 rate limit durumunda otomatik bekleyip tekrar dener
- Model kaldırılsa bile sistem otomatik yeni modele geçer
- JSON çıktısı sağlam şekilde parse edilir
"""

import json
import re
import time
import google.generativeai as genai
from .utils import load_json, get_env, setup_logging

logger = setup_logging()

PROMPTS_PATH = "config/prompts.json"
STYLE_PATH = "config/style.json"

# Tercih edilen modeller (rate limit'e göre sıralı)
# gemini-2.5-flash: en stabil, yüksek limit
# gemini-2.5-flash-lite: hızlı
# gemini-flash-latest: güncel
PREFERRED_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-3.0-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-pro-latest",
]

# Rate limit ayarları
MAX_RETRIES = 5
BASE_WAIT_SECONDS = 30


def _extract_error_info(e: Exception) -> dict:
    """Hatadan 429/rate limit bilgisi çıkarır."""
    error_str = str(e)
    is_rate_limit = (
        "429" in error_str
        or "ResourceExhausted" in error_str
        or "quota" in error_str.lower()
        or "rate" in error_str.lower() and "limit" in error_str.lower()
    )
    
    # Retry delay'i çıkarmaya çalış
    retry_delay = BASE_WAIT_SECONDS
    match = re.search(r"retry in (\d+)", error_str)
    if match:
        retry_delay = int(match.group(1)) + 5
    else:
        match = re.search(r"retry_delay\s*{\s*seconds:\s*(\d+)", error_str)
        if match:
            retry_delay = int(match.group(1)) + 5
    
    return {
        "is_rate_limit": is_rate_limit,
        "retry_delay": retry_delay,
    }


def pick_model() -> str:
    """
    Kullanılabilir modeller arasından en iyisini seçer.
    1. Tercih listesindekileri dener.
    2. Yoksa generateContent destekleyen ilk modeli alır.
    """
    available = []
    try:
        for m in genai.list_models():
            # Hem obje hem string dönüşüne uyum sağla
            if isinstance(m, str):
                name = m.replace("models/", "")
                methods = ["generateContent"]
            else:
                name = m.name.replace("models/", "")
                methods = getattr(m, "supported_generation_methods", []) or []
            
            if "generateContent" in methods:
                available.append(name)
    except Exception as e:
        logger.warning(f"Model listesi alınamadı: {e}")
        return PREFERRED_MODELS[0]
    
    logger.info(f"Kullanılabilir modeller: {available[:20]}")
    
    # Tercih sırasına göre ara
    for preferred in PREFERRED_MODELS:
        if preferred in available:
            logger.info(f"Model seçildi (tercih): {preferred}")
            return preferred
    
    # Tercih listesinde yoksa, "flash" içeren ilk modeli al
    for name in available:
        if "flash" in name.lower() and "image" not in name.lower() and "tts" not in name.lower():
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
    return genai.GenerativeModel(model_name), model_name


def build_prompt(topic: dict, prompts: dict, style: dict) -> str:
    """Konu ve stil bilgisinden prompt üretir."""
    template = prompts["script_generation"]["user_template"]
    
    # Format string yerine replace kullan (JSON içindeki {} sorun çıkarmasın)
    # Çift süslü parantez desteği
    prompt = template.replace("{{topic_title}}", topic.get("title", ""))
    prompt = prompt.replace("{{topic_seed}}", topic.get("seed", ""))
    prompt = prompt.replace("{{topic_source}}", topic.get("source", ""))
    
    # Tek süslü parantez desteği
    prompt = prompt.replace("{topic_title}", topic.get("title", ""))
    prompt = prompt.replace("{topic_seed}", topic.get("seed", ""))
    prompt = prompt.replace("{topic_source}", topic.get("source", ""))
    
    # Stil bilgisini ekle
    prompt += f"\n\nVisual style: {style.get('prompt_suffix', '')}"
    prompt += f"\nNegative: {style.get('negative_prompt', '')}"
    
    return prompt


def extract_json(text: str) -> dict:
    """Model çıktısından JSON bloğunu ayıklar."""
    if not text or not text.strip():
        raise ValueError("Model boş yanıt döndü.")
    
    # ```json ... ``` bloğunu bul
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Direkt JSON'u bul (ilk { ile son } arası)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse hatası: {e}")
    
    raise ValueError(f"JSON bulunamadı:\n{text[:500]}")


def validate_script(script: dict) -> dict:
    """Senaryo alanlarını doğrular ve eksikleri tamamlar."""
    required = ["title", "hook", "context", "climax", "outro", "description", "tags"]
    
    for field in required:
        if field not in script:
            script[field] = "" if field != "tags" else []
    
    if not script["outro"]:
        script["outro"] = "Follow for more."
    
    if not script["title"]:
        script["title"] = "Quelnaris"
    
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


def _call_gemini_with_retry(model, prompt: str) -> str:
    """
    Gemini'yi çağırır. 429 rate limit olursa bekleyip tekrar dener.
    """
    last_error = None
    
    for attempt in range(MAX_RETRIES):
        try:
            logger.info(f"Gemini çağrısı (deneme {attempt + 1}/{MAX_RETRIES})")
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            last_error = e
            info = _extract_error_info(e)
            
            if info["is_rate_limit"]:
                wait = info["retry_delay"] * (attempt + 1)
                logger.warning(
                    f"Rate limit (429). {wait}sn bekleyip tekrar denenecek "
                    f"({attempt + 1}/{MAX_RETRIES})"
                )
                time.sleep(wait)
            else:
                # Rate limit değil, direkt hata ver
                logger.error(f"Gemini hatası (rate limit değil): {e}")
                raise
    
    logger.error(f"Gemini max retry aşıldı: {last_error}")
    raise last_error


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
        "_word_count": 45,
        "source": "..."
    }
    """
    logger.info(f"Senaryo üretiliyor: {topic.get('title', '?')}")
    
    prompts = load_json(PROMPTS_PATH)
    style = load_json(STYLE_PATH)
    model, model_name = configure_gemini()
    
    system_prompt = prompts["script_generation"]["system"]
    user_prompt = build_prompt(topic, prompts, style)
    
    full_prompt = f"{system_prompt}\n\n{user_prompt}"
    
    # Retry mekanizması ile çağır
    text = _call_gemini_with_retry(model, full_prompt)
    
    # JSON parse
    try:
        script = extract_json(text)
    except Exception as e:
        logger.error(f"JSON parse hatası: {e}")
        logger.error(f"Model çıktısı:\n{text[:1000]}")
        raise
    
    script = validate_script(script)
    
    # Kaynak bilgisini ekle
    script["source"] = topic.get("source", "")
    script["_model"] = model_name
    
    logger.info(f"Senaryo hazır: {script['_word_count']} kelime (model: {model_name})")
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