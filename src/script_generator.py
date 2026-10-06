"""
script_generator.py — Gemini API ile 16 saniyelik Shorts senaryosu üretir.

Özellikler:
- 3 API key rotasyonu (GEMINI_API_KEY, GEMINI_API_KEY_2, GEMINI_API_KEY_3)
- Model fallback (429/404 durumunda sıradaki modele geçer)
- Otomatik retry (rate limit durumunda bekleyip tekrar dener)
- Sağlam JSON parse (birçok formatta çalışır)
- Boş/eksik yanıt kontrolü
- Kısmi senaryo tamamlama

Hata vermek yerine alternatifleri dener. Hiçbir ufak hata sistemi durdurmaz.
"""

import os
import json
import re
import time
import google.generativeai as genai
from .utils import load_json, get_env, setup_logging

logger = setup_logging()

PROMPTS_PATH = "config/prompts.json"
STYLE_PATH = "config/style.json"

# ─── API KEY LİSTESİ ───────────────────────────────────────
# 3 anahtar: GEMINI_API_KEY, GEMINI_API_KEY_2, GEMINI_API_KEY_3
API_KEY_NAMES = [
    "GEMINI_API_KEY",
    "GEMINI_API_KEY_2",
    "GEMINI_API_KEY_3",
]

# ─── MODEL LİSTESİ (öncelik sırası) ────────────────────────
# Yeni kullanıcılar için gemini-3.8-flash zorunlu
PREFERRED_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.0-flash",
    "gemini-3-flash-preview",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-pro-latest",
]

# ─── RETRY AYARLARI ────────────────────────────────────────
MAX_RETRIES_PER_KEY = 3
BASE_WAIT_SECONDS = 20


# ═══════════════════════════════════════════════════════════
# API KEY YÖNETİMİ
# ═══════════════════════════════════════════════════════════

def get_api_keys() -> list:
    """Tüm mevcut API key'leri toplar (boş olanları atlar)."""
    keys = []
    for name in API_KEY_NAMES:
        key = os.getenv(name, "").strip()
        if key:
            keys.append({"name": name, "key": key})
    if not keys:
        raise RuntimeError(
            "Hiçbir Gemini API key bulunamadı. "
            "GEMINI_API_KEY en az bir tane olmalı."
        )
    logger.info(f"{len(keys)} API key bulundu: {[k['name'] for k in keys]}")
    return keys


# ═══════════════════════════════════════════════════════════
# MODEL SEÇİMİ
# ═══════════════════════════════════════════════════════════

def list_available_models(api_key: str) -> list:
    """Kullanılabilir modelleri listeler."""
    try:
        genai.configure(api_key=api_key)
        available = []
        for m in genai.list_models():
            if isinstance(m, str):
                name = m.replace("models/", "")
                methods = ["generateContent"]
            else:
                name = m.name.replace("models/", "")
                methods = getattr(m, "supported_generation_methods", []) or []
            if "generateContent" in methods:
                available.append(name)
        return available
    except Exception as e:
        logger.warning(f"Model listesi alınamadı: {str(e)[:100]}")
        return []


def pick_models(api_key: str) -> list:
    """
    Öncelik sırasına göre model listesi döner.
    En iyi model başta.
    """
    available = list_available_models(api_key)
    logger.info(f"Kullanılabilir modeller: {available[:20]}")
    
    # 1. Tercih listesindekiler (available'da olanlar)
    priority = []
    for preferred in PREFERRED_MODELS:
        if preferred in available:
            priority.append(preferred)
    
    # 2. Geri kalan flash modeller (görsel/tts hariç)
    for name in available:
        if name in priority:
            continue
        lower = name.lower()
        if "flash" in lower and "image" not in lower and "tts" not in lower and "audio" not in lower:
            priority.append(name)
    
    # 3. Diğer tüm modeller
    for name in available:
        if name not in priority:
            priority.append(name)
    
    # 4. Hiçbiri yoksa varsayılanlar
    if not priority:
        priority = PREFERRED_MODELS[:3]
    
    logger.info(f"Model öncelik sırası: {priority[:5]}")
    return priority


# ═══════════════════════════════════════════════════════════
# PROMPT OLUŞTURMA
# ═══════════════════════════════════════════════════════════

def build_prompt(topic: dict, prompts: dict, style: dict) -> str:
    """Konu ve stil bilgisinden prompt üretir."""
    template = prompts["script_generation"]["user_template"]
    
    # Çift süslü parantez
    prompt = template.replace("{{topic_title}}", topic.get("title", ""))
    prompt = prompt.replace("{{topic_seed}}", topic.get("seed", ""))
    prompt = prompt.replace("{{topic_source}}", topic.get("source", ""))
    
    # Tek süslü parantez
    prompt = prompt.replace("{topic_title}", topic.get("title", ""))
    prompt = prompt.replace("{topic_seed}", topic.get("seed", ""))
    prompt = prompt.replace("{topic_source}", topic.get("source", ""))
    
    # Stil
    prompt += f"\n\nVisual style: {style.get('prompt_suffix', '')}"
    prompt += f"\nNegative: {style.get('negative_prompt', '')}"
    
    return prompt


# ═══════════════════════════════════════════════════════════
# JSON PARSE
# ═══════════════════════════════════════════════════════════

def extract_json(text: str) -> dict:
    """Model çıktısından JSON bloğunu sağlam şekilde ayıklar."""
    if not text or not text.strip():
        raise ValueError("Model boş yanıt döndü.")
    
    # 1. ```json ... ``` bloğu
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    
    # 2. İlk { ile son } arası
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    
    # 3. Tüm metni JSON olarak dene
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
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
    
    # Kelime sayısı
    total = " ".join([
        str(script.get("hook", "")),
        str(script.get("context", "")),
        str(script.get("climax", "")),
        str(script.get("outro", "")),
    ])
    word_count = len(total.split())
    
    if word_count > 70:
        logger.warning(f"Senaryo uzun: {word_count} kelime")
    elif word_count < 25:
        logger.warning(f"Senaryo kısa: {word_count} kelime")
    
    script["_word_count"] = word_count
    return script


# ═══════════════════════════════════════════════════════════
# GEMINI ÇAĞRISI — RETRY + KEY + MODEL ROTASYONU
# ═══════════════════════════════════════════════════════════

def _error_info(e: Exception) -> dict:
    """Hatadan bilgi çıkarır: rate limit mi, model yok mu, vs."""
    error_str = str(e)
    
    is_rate_limit = (
        "429" in error_str
        or "ResourceExhausted" in error_str
        or "quota" in error_str.lower()
        or ("rate" in error_str.lower() and "limit" in error_str.lower())
    )
    
    is_model_not_found = (
        "404" in error_str
        or "NotFound" in error_str
        or "not found" in error_str.lower()
        or "no longer available" in error_str.lower()
        or "not supported" in error_str.lower()
    )
    
    is_invalid_key = (
        "400" in error_str
        or "API_KEY_INVALID" in error_str
        or "API key not valid" in error_str
    )
    
    # Retry delay
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
        "is_model_not_found": is_model_not_found,
        "is_invalid_key": is_invalid_key,
        "retry_delay": retry_delay,
        "raw": error_str,
    }


def try_generate_with_model(model, prompt: str, model_name: str) -> str:
    """
    Tek bir model ile deneme yapar.
    - Rate limit olursa bekleyip tekrar dener (max 3)
    - Model yok hatası alırsa None döner (üst katman sıradaki modele geçer)
    """
    last_error = None
    
    for attempt in range(MAX_RETRIES_PER_KEY):
        try:
            logger.info(f"  → Model: {model_name} (deneme {attempt + 1}/{MAX_RETRIES_PER_KEY})")
            response = model.generate_content(prompt)
            text = response.text
            if text and text.strip():
                return text
            logger.warning("  ⚠ Boş yanıt, tekrar deneniyor...")
        except Exception as e:
            last_error = e
            info = _error_info(e)
            
            # Model yok → hemen üst katmana dön
            if info["is_model_not_found"]:
                logger.warning(f"  ⚠ Model kullanılamıyor: {model_name}")
                return None
            
            # Rate limit → bekle, tekrar dene
            if info["is_rate_limit"]:
                wait = info["retry_delay"] * (attempt + 1)
                logger.warning(f"  ⏱ Rate limit, {wait}sn bekleniyor...")
                time.sleep(wait)
                continue
            
            # Diğer hata → kısa bekle, tekrar dene
            wait = 5 * (attempt + 1)
            logger.warning(f"  ⚠ Hata: {str(e)[:100]}")
            logger.warning(f"  ⏱ {wait}sn bekleniyor...")
            time.sleep(wait)
    
    if last_error:
        logger.warning(f"  ✗ Model {model_name} başarısız: {str(last_error)[:150]}")
    return None


def generate_text_with_fallback(prompt: str) -> str:
    """
    Tüm API key + tüm modeller üzerinden dener.
    İlk başarılı yanıtı döner.
    """
    api_keys = get_api_keys()
    all_errors = []
    
    for key_info in api_keys:
        key_name = key_info["name"]
        logger.info(f"═══ API Key: {key_name} ═══")
        
        try:
            genai.configure(api_key=key_info["key"])
        except Exception as e:
            logger.warning(f"Key {key_name} yapılandırılamadı: {e}")
            all_errors.append(f"{key_name}: configure error")
            continue
        
        models = pick_models(key_info["key"])
        
        for model_name in models:
            try:
                model = genai.GenerativeModel(model_name)
            except Exception as e:
                logger.warning(f"Model {model_name} oluşturulamadı: {e}")
                continue
            
            text = try_generate_with_model(model, prompt, model_name)
            
            if text:
                logger.info(f"✅ Başarılı: {key_name} + {model_name}")
                return text
            
            all_errors.append(f"{key_name}/{model_name}")
    
    raise RuntimeError(
        f"Hiçbir API key + model kombinasyonu çalışmadı. "
        f"Denenenler: {all_errors}"
    )


# ═══════════════════════════════════════════════════════════
# ANA FONKSİYON
# ═══════════════════════════════════════════════════════════

def generate_script(topic: dict) -> dict:
    """
    Ana fonksiyon: Konu alır, senaryo döner.
    3 API key + model fallback + retry ile hatasız çalışır.
    """
    logger.info(f"Senaryo üretiliyor: {topic.get('title', '?')}")
    
    prompts = load_json(PROMPTS_PATH)
    style = load_json(STYLE_PATH)
    
    system_prompt = prompts["script_generation"]["system"]
    user_prompt = build_prompt(topic, prompts, style)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"
    
    # Fallback sistemiyle metni al
    text = generate_text_with_fallback(full_prompt)
    
    # JSON parse
    try:
        script = extract_json(text)
    except Exception as e:
        logger.error(f"JSON parse hatası: {e}")
        logger.error(f"Model çıktısı:\n{text[:1000]}")
        raise
    
    script = validate_script(script)
    script["source"] = topic.get("source", "")
    
    logger.info(f"Senaryo hazır: {script['_word_count']} kelime")
    return script


def generate_voiceover_text(script: dict) -> str:
    """Senaryodan seslendirme metnini üretir."""
    return " ".join([
        str(script.get("hook", "")),
        str(script.get("context", "")),
        str(script.get("climax", "")),
        str(script.get("outro", "Follow for more.")),
    ])


if __name__ == "__main__":
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