"""
topic_selector.py — Konu havuzundan rastgele konu seçer.
Kullanılan konuları işaretler, tekrar etmesini engeller.
"""

import random
from datetime import datetime
from .utils import load_json, save_json, setup_logging

logger = setup_logging()

TOPICS_PATH = "config/topics.json"
STATE_PATH = "logs/used_topics.json"


def load_topics() -> list:
    """Konu havuzunu okur."""
    data = load_json(TOPICS_PATH)
    return data.get("topics", [])


def load_used() -> list:
    """Daha önce kullanılan konuların ID listesini okur."""
    try:
        data = load_json(STATE_PATH)
        return data.get("used", [])
    except FileNotFoundError:
        return []


def save_used(used: list) -> None:
    """Kullanılan konuları kaydeder."""
    save_json({"used": used, "updated": datetime.utcnow().isoformat()}, STATE_PATH)


def select_topic(category: str = None) -> dict:
    """
    Rastgele bir konu seçer.
    - category verilirse o kategoriden seçer.
    - Daha önce kullanılmamış konuları önceler.
    - Tüm konular kullanıldıysa sıfırlar.
    """
    topics = load_topics()
    used = load_used()
    
    if not topics:
        raise ValueError("Konu havuzu boş: config/topics.json")
    
    # Kategori filtresi
    if category:
        pool = [t for t in topics if t.get("category") == category]
    else:
        pool = topics
    
    # Kullanılmamışları filtrele
    available = [t for t in pool if t["id"] not in used]
    
    # Hepsi kullanıldıysa sıfırla
    if not available:
        logger.info("Tüm konular kullanıldı, sıfırlanıyor.")
        used = [u for u in used if u not in [t["id"] for t in pool]]
        available = pool
    
    # Rastgele seç
    topic = random.choice(available)
    
    # Kullanıldı olarak işaretle
    used.append(topic["id"])
    save_used(used)
    
    logger.info(f"Konu seçildi: {topic['id']} — {topic['title']}")
    return topic


def get_stats() -> dict:
    """Konu havuzu istatistiklerini döner."""
    topics = load_topics()
    used = load_used()
    
    categories = {}
    for t in topics:
        cat = t.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1
    
    return {
        "total": len(topics),
        "used": len(used),
        "remaining": len(topics) - len([t for t in topics if t["id"] in used]),
        "categories": categories,
    }


if __name__ == "__main__":
    stats = get_stats()
    print(f"Toplam konu: {stats['total']}")
    print(f"Kullanılan: {stats['used']}")
    print(f"Kalan: {stats['remaining']}")
    print(f"Kategoriler: {stats['categories']}")
    
    topic = select_topic()
    print(f"\nSeçilen konu: {topic['title']}")