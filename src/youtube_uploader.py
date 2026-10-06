"""
youtube_uploader.py — YouTube Data API v3 ile video yükler.
OAuth token otomatik yenilenir, hata durumunda retry yapar.
"""

import os
import json
import time
import pickle
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from .utils import load_yaml, get_env, setup_logging

logger = setup_logging()

SETTINGS_PATH = "config/settings.yaml"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def get_credentials() -> Credentials:
    """
    OAuth kimlik bilgilerini alır.
    - token.json varsa kullanır
    - Yoksa client_secret.json ile yeni token üretir
    - GitHub Actions'ta YT_TOKEN ve YT_CLIENT_SECRET secrets'tan alınır
    """
    creds = None
    
    # 1. Ortamdan token oku (GitHub Actions için)
    token_env = os.getenv("YT_TOKEN")
    if token_env:
        try:
            creds = Credentials.from_authorized_user_info(
                json.loads(token_env), SCOPES
            )
        except Exception as e:
            logger.warning(f"YT_TOKEN okunamadı: {e}")
    
    # 2. Dosyadan token oku
    if not creds and os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    
    # 3. Token yenile
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            logger.info("Token yenilendi.")
        except Exception as e:
            logger.error(f"Token yenileme hatası: {e}")
            creds = None
    
    # 4. Yeni token üret (sadece lokal)
    if not creds:
        secret_env = os.getenv("YT_CLIENT_SECRET")
        if secret_env:
            with open("client_secret.json", "w", encoding="utf-8") as f:
                f.write(secret_env)
        
        if not os.path.exists("client_secret.json"):
            raise FileNotFoundError("client_secret.json bulunamadı.")
        
        flow = InstalledAppFlow.from_client_secrets_file(
            "client_secret.json", SCOPES
        )
        creds = flow.run_local_server(port=0)
        
        with open("token.json", "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        logger.info("Yeni token üretildi: token.json")
    
    return creds


def build_description(script: dict, settings: dict) -> str:
    """Video açıklamasını üretir."""
    template = settings.get("youtube", {}).get("description_template", "{description}")
    
    description = template.format(
        description=script.get("description", ""),
    )
    
    # Kaynak ekle
    source = script.get("source", "")
    if source:
        description += f"\n\nSource: {source}"
    
    return description.strip()


def upload_video(
    video_path: str,
    script: dict,
    output_log: str = "logs/upload_log.json",
) -> dict:
    """
    Videoyu YouTube'a yükler.
    
    Args:
        video_path: Video dosyası
        script: Senaryo (title, description, tags)
        output_log: Log dosyası
    
    Returns:
        {"video_id": "...", "url": "..."}
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video yok: {video_path}")
    
    settings = load_yaml(SETTINGS_PATH)
    yt_cfg = settings.get("youtube", {})
    channel_cfg = settings.get("channel", {})
    
    logger.info("YouTube'a yükleniyor...")
    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)
    
    title = script.get("title", "Quelnaris")[:100]
    description = build_description(script, settings)
    tags = script.get("tags", yt_cfg.get("tags", []))
    
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "27",  # Education
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": yt_cfg.get("privacy", "public"),
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,  # AI içerik beyanı
        },
    }
    
    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024 * 5,  # 5 MB
    )
    
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )
    
    response = None
    retries = 0
    max_retries = 5
    
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                logger.info(f"Yükleme: %{pct}")
        except HttpError as e:
            if e.resp.status in [500, 502, 503, 504] and retries < max_retries:
                retries += 1
                wait = 2 ** retries
                logger.warning(f"Sunucu hatası, {wait}sn sonra tekrar ({retries}/{max_retries})")
                time.sleep(wait)
            else:
                logger.error(f"YouTube hatası: {e}")
                raise
        except Exception as e:
            if retries < max_retries:
                retries += 1
                wait = 2 ** retries
                logger.warning(f"Hata: {e}, {wait}sn sonra tekrar")
                time.sleep(wait)
            else:
                raise
    
    video_id = response["id"]
    url = f"https://youtube.com/shorts/{video_id}"
    
    logger.info(f"Video yüklendi: {url}")
    
    # Log kaydet
    log = {
        "video_id": video_id,
        "url": url,
        "title": title,
        "uploaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    if os.path.exists(output_log):
        with open(output_log, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"uploads": []}
    
    data["uploads"].append(log)
    
    with open(output_log, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    return log


if __name__ == "__main__":
    # Test: output/final.mp4 varsa
    video = "output/final.mp4"
    if os.path.exists(video):
        test_script = {
            "title": "Test Video",
            "description": "Test açıklama.",
            "tags": ["test", "quelnaris"],
        }
        result = upload_video(video, test_script)
        print(f"Video: {result['url']}")
    else:
        print(f"Test için video gerekli: {video}")