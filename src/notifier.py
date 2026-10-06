"""
notifier.py — Gmail SMTP ile bildirim gönderir.
Video başarıyla yüklenince veya hata olunca email atar.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from .utils import load_yaml, get_env, setup_logging

logger = setup_logging()

SETTINGS_PATH = "config/settings.yaml"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def send_email(subject: str, body: str, to: str = None) -> bool:
    """
    Gmail SMTP ile email gönderir.
    
    Gerekli ortam değişkenleri:
        GMAIL_USER: gönderen Gmail adresi
        GMAIL_APP_PASSWORD: 16 haneli uygulama şifresi
    """
    settings = load_yaml(SETTINGS_PATH)
    notif_cfg = settings.get("notifications", {}).get("email", {})
    
    if not notif_cfg.get("enabled", False):
        logger.info("Email bildirimi kapalı.")
        return False
    
    to = to or notif_cfg.get("to")
    if not to:
        logger.warning("Email alıcısı tanımlı değil.")
        return False
    
    try:
        gmail_user = get_env("GMAIL_USER")
        gmail_pass = get_env("GMAIL_APP_PASSWORD")
    except ValueError as e:
        logger.warning(f"Email gönderilemedi: {e}")
        return False
    
    msg = MIMEMultipart()
    msg["From"] = gmail_user
    msg["To"] = to
    msg["Subject"] = subject
    
    # HTML + düz metin
    msg.attach(MIMEText(body, "plain", "utf-8"))
    
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(gmail_user, gmail_pass)
            server.send_message(msg)
        logger.info(f"Email gönderildi: {to}")
        return True
    except Exception as e:
        logger.error(f"Email hatası: {e}")
        return False


def notify_success(script: dict, video_url: str, video_path: str = None) -> bool:
    """Başarılı yükleme bildirimi."""
    subject = f"✅ Quelnaris: {script.get('title', 'Yeni video')}"
    
    body = f"""
Quelnaris — Yeni video yayında!

Başlık: {script.get('title', '')}
URL: {video_url}

Hook: {script.get('hook', '')}
Context: {script.get('context', '')}
Climax: {script.get('climax', '')}

Kelime sayısı: {script.get('_word_count', '?')}
Zaman: {datetime.now():%Y-%m-%d %H:%M:%S}

---
Quelnaris Otomasyon Sistemi
"""
    
    return send_email(subject, body.strip())


def notify_error(step: str, error: str, context: dict = None) -> bool:
    """Hata bildirimi."""
    subject = f"❌ Quelnaris Hatası: {step}"
    
    body = f"""
Quelnaris otomasyonunda hata oluştu.

Adım: {step}
Hata: {error}

Zaman: {datetime.now():%Y-%m-%d %H:%M:%S}
"""
    
    if context:
        body += "\nBağlam:\n"
        for k, v in context.items():
            body += f"  {k}: {v}\n"
    
    body += "\n---\nQuelnaris Otomasyon Sistemi"
    
    return send_email(subject, body.strip())


def notify_daily_summary(stats: dict) -> bool:
    """Günlük özet bildirimi (opsiyonel)."""
    subject = f"📊 Quelnaris Günlük Özet — {datetime.now():%Y-%m-%d}"
    
    body = f"""
Quelnaris günlük özet:

Toplam konu: {stats.get('total', '?')}
Kullanılan: {stats.get('used', '?')}
Kalan: {stats.get('remaining', '?')}

Kategoriler:
"""
    for cat, count in stats.get("categories", {}).items():
        body += f"  {cat}: {count}\n"
    
    body += "\n---\nQuelnaris Otomasyon Sistemi"
    
    return send_email(subject, body.strip())


if __name__ == "__main__":
    # Test
    result = send_email(
        subject="Quelnaris Test",
        body="Bu bir test emailidir.",
    )
    print(f"Email gönderildi mi: {result}")