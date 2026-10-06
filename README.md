# Quelnaris — Otonom YouTube Shorts Sistemi

> True stories. Dark minds. Unseen files.

Quelnaris, gizem + korku + psikoloji nişinde **tamamen otomatik** YouTube Shorts üreten bir sistemdir.

Her gün **saat 06:00'da (TR)** yeni bir video yayında olur. Sen hiçbir şey yapmazsın.

---

## 🎯 Ne yapar?

1. Az bilinen, gerçek bir konu seçer (134 konu havuzundan)
2. 16 saniyelik senaryo yazar (Gemini AI)
3. İngilizce kadın sesle seslendirir (Edge TTS)
4. Görsel promptları üretir (Bing Image Creator için)
5. Görsellerden Ken Burns videosu üretir (FFmpeg)
6. Altyazı ekler (Whisper)
7. YouTube'a yükler (YouTube Data API v3)
8. Sana Gmail ile bildirir

---

## 📋 Gereksinimler

### Zorunlu
- GitHub hesabı
- Google Cloud hesabı (YouTube Data API v3 için)
- Gemini API anahtarı ([ai.google.dev](https://ai.google.dev))
- Gmail hesabı (bildirim için)
- Gmail App Password

### Opsiyonel
- Telegram bot (alternatif bildirim)
- Leonardo AI hesabı (otomatik görsel için)

---

## 🚀 Kurulum

### 1. Repoyu klonla

```bash
git clone https://github.com/KULLANICIADIN/quelnaris-automation.git
cd quelnaris-automation