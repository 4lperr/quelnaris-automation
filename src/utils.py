"""
utils.py — Quelnaris otomasyonu için yardımcı fonksiyonlar.
"""

import os
import json
import yaml
import logging
from datetime import datetime
from pathlib import Path


def setup_logging(log_dir: str = "logs") -> logging.Logger:
    """Log sistemini kurar. Hem dosyaya hem konsola yazar."""
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    
    log_file = os.path.join(log_dir, f"quelnaris_{datetime.now():%Y%m%d}.log")
    
    logger = logging.getLogger("quelnaris")
    logger.setLevel(logging.INFO)
    
    if logger.handlers:
        return logger
    
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger


def load_yaml(path: str) -> dict:
    """YAML dosyasını okur."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_json(path: str) -> dict:
    """JSON dosyasını okur."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: dict, path: str) -> None:
    """JSON dosyasına yazar."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ensure_dir(path: str) -> None:
    """Klasör yoksa oluşturur."""
    Path(path).mkdir(parents=True, exist_ok=True)


def get_env(key: str, required: bool = True, default: str = "") -> str:
    """Ortam değişkenini okur. Yoksa hata verir veya varsayılanı döner."""
    value = os.getenv(key, default)
    if required and not value:
        raise ValueError(f"Ortam değişkeni eksik: {key}")
    return value


def format_duration(seconds: int) -> str:
    """Saniyeyi okunabilir formata çevirir."""
    minutes, secs = divmod(seconds, 60)
    if minutes:
        return f"{minutes}dk {secs}sn"
    return f"{secs}sn"


def clean_filename(text: str) -> str:
    """Dosya adı için güvenli metin üretir."""
    keep = "-_"
    return "".join(c for c in text if c.isalnum() or c in keep).rstrip()


def now_utc() -> str:
    """Şu anki UTC zamanını ISO formatında döner."""
    return datetime.utcnow().isoformat()


def truncate(text: str, max_len: int = 100) -> str:
    """Metni belirtilen uzunlukta keser."""
    return text if len(text) <= max_len else text[:max_len - 3] + "..."