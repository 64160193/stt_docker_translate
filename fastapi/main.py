from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import requests
import logging
import os
import asyncio
from urllib.parse import urljoin
from typing import Dict, Optional, Union
from starlette.websockets import WebSocketState
import json
import html

# ตั้งค่า logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastAPI()

# ตั้งค่า CORS (เพิ่มเพื่อให้ frontend เข้าถึงได้)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ในการใช้งานจริงควรระบุ domain ที่อนุญาต
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ตั้งค่า Whisper และ Translation
WHISPER_URL = os.getenv("WHISPER_SERVICE_URL", "http://localhost:9000")
WHISPER_ASR_ENDPOINT = os.getenv("WHISPER_ASR_ENDPOINT", "/asr")

# ตั้งค่า Translation Service
# ใช้ LibreTranslate ซึ่งเป็น open-source และฟรี หรือสามารถเลือก Google Translate, DeepL ได้
TRANSLATION_SERVICE = os.getenv("TRANSLATION_SERVICE", "libre")  # libre, google, deepl
LIBRETRANSLATE_URL = os.getenv("LIBRETRANSLATE_URL", "https://libretranslate.com/translate")
LIBRETRANSLATE_API_KEY = os.getenv("LIBRETRANSLATE_API_KEY", "")  # ถ้าต้องการใช้ LibreTranslate API

GOOGLE_TRANSLATE_API_KEY = os.getenv("GOOGLE_TRANSLATE_API_KEY", "")  # สำหรับ Google Translate
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY", "")  # สำหรับ DeepL

# เก็บ active connections
active_connections: Dict[str, WebSocket] = {}

async def process_audio(audio_data, source_lang="th") -> Optional[requests.Response]:
    """ฟังก์ชันสำหรับส่งข้อมูลเสียงไปยัง Whisper API (เฉพาะถอดเสียง)"""
    try:
        files = {
            'audio_file': ('audio.webm', audio_data, 'audio/webm')
        }
        url = urljoin(WHISPER_URL, WHISPER_ASR_ENDPOINT)
        
        # ตรวจสอบการเชื่อมต่อกับ Whisper
        try:
            health_url = urljoin(WHISPER_URL, "/openapi.json")
            health_response = await asyncio.to_thread(
                requests.get,
                health_url,
                timeout=5
            )
            logger.info(f"Whisper health check status: {health_response.status_code}")
            if health_response.status_code != 200:
                logger.error("Whisper service is not healthy")
                return None
        except Exception as e:
            logger.error(f"Cannot connect to Whisper service: {str(e)}")
            return None

        logger.info(f"Sending request to Whisper ASR: {url} with language: {source_lang}")
        logger.info(f"Audio data size: {len(audio_data)} bytes")
        
        # ใช้ asyncio.to_thread เพื่อไม่ให้ block event loop
        response = await asyncio.to_thread(
            requests.post,
            url,
            files=files,
            params={
                "task": "transcribe",
                "language": source_lang,
                "output": "json"
            },
            timeout=30
        )
        
        logger.debug(f"Whisper response status: {response.status_code}")
        logger.debug(f"Whisper response content: {response.text}")
        return response
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in process_audio: {str(e)}")
        return None

async def translate_text(text: str, source_lang: str, target_lang: str) -> Optional[str]:
    """ฟังก์ชันสำหรับแปลข้อความโดยใช้บริการแปลภาษาต่างๆ"""
    try:
        if not text or text.strip() == "":
            logger.warning("Empty text for translation")
            return ""
            
        logger.info(f"Translating text from {source_lang} to {target_lang}")
        logger.info(f"Text to translate: {text[:50]}...")
        
        # ถ้าภาษาต้นทางและปลายทางเหมือนกัน ไม่ต้องแปล
        if source_lang == target_lang:
            return text
            
        # LibreTranslate (Free and Open Source)
        if TRANSLATION_SERVICE == "libre":
            payload = {
                "q": text,
                "source": source_lang,
                "target": target_lang,
                "format": "text"
            }
            
            if LIBRETRANSLATE_API_KEY:
                payload["api_key"] = LIBRETRANSLATE_API_KEY
                
            response = await asyncio.to_thread(
                requests.post,
                LIBRETRANSLATE_URL,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get("translatedText", "")
            else:
                logger.error(f"LibreTranslate API error: {response.status_code}, {response.text}")
                return None
        
        # Google Translate
        elif TRANSLATION_SERVICE == "google":
            if not GOOGLE_TRANSLATE_API_KEY:
                logger.error("Google Translate API key is not set")
                return None
                
            url = f"https://translation.googleapis.com/language/translate/v2?key={GOOGLE_TRANSLATE_API_KEY}"
            payload = {
                "q": text,
                "source": source_lang,
                "target": target_lang,
                "format": "text"
            }
            
            response = await asyncio.to_thread(
                requests.post,
                url,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                translations = result.get("data", {}).get("translations", [])
                if translations:
                    return html.unescape(translations[0].get("translatedText", ""))
                else:
                    return None
            else:
                logger.error(f"Google Translate API error: {response.status_code}, {response.text}")
                return None
        
        # DeepL
        elif TRANSLATION_SERVICE == "deepl":
            if not DEEPL_API_KEY:
                logger.error("DeepL API key is not set")
                return None
                
            url = "https://api-free.deepl.com/v2/translate"  # ใช้ API ฟรีของ DeepL
            headers = {
                "Authorization": f"DeepL-Auth-Key {DEEPL_API_KEY}"
            }
            payload = {
                "text": [text],
                "source_lang": source_lang.upper(),
                "target_lang": target_lang.upper()
            }
            
            response = await asyncio.to_thread(
                requests.post,
                url,
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                translations = result.get("translations", [])
                if translations:
                    return translations[0].get("text", "")
                else:
                    return None
            else:
                logger.error(f"DeepL API error: {response.status_code}, {response.text}")
                return None
                
        # ใช้บริการแปลภาษาอื่นๆ เพิ่มเติมได้
        else:
            logger.error(f"Unsupported translation service: {TRANSLATION_SERVICE}")
            return None
            
    except Exception as e:
        logger.error(f"Error in translate_text: {str(e)}")
        return None

async def process_audio_and_translate(audio_data, source_lang="th", target_lang="en") -> Optional[dict]:
    """ฟังก์ชันรวมสำหรับถอดเสียงและแปลภาษา"""
    try:
        # ถอดเสียงเป็นข้อความในภาษาต้นทาง
        logger.info(f"Transcribing audio in source language: {source_lang}")
        transcription_response = await process_audio(audio_data, source_lang)
        
        original_text = ""
        if transcription_response and transcription_response.status_code == 200:
            result = transcription_response.json()
            original_text = result.get("text", "").strip()
            logger.info(f"Successfully transcribed: {original_text[:50]}...")
            
            if not original_text:
                logger.warning("No text found in audio")
                return {
                    "error": "ไม่พบข้อความในเสียง",
                    "source_lang": source_lang,
                    "target_lang": target_lang
                }
        else:
            error_msg = "ไม่สามารถเชื่อมต่อกับระบบเเปลภาษาได้กรุณารอสักครู่" if not transcription_response else f"Whisper error: {transcription_response.status_code}"
            logger.error(error_msg)
            return {
                "error": error_msg,
                "source_lang": source_lang,
                "target_lang": target_lang
            }
        
        # กรณีภาษาต้นทางและปลายทางเหมือนกัน ไม่ต้องแปล
        if source_lang == target_lang:
            return {
                "original_text": original_text,
                "translated_text": original_text,
                "source_lang": source_lang,
                "target_lang": target_lang
            }
            
        # แปลข้อความโดยใช้ Translation Service
        translated_text = await translate_text(original_text, source_lang, target_lang)
        
        if translated_text:
            logger.info(f"Successfully translated: {translated_text[:50]}...")
            
            return {
                "original_text": original_text,
                "translated_text": translated_text,
                "source_lang": source_lang,
                "target_lang": target_lang
            }
        else:
            logger.warning("Translation failed")
            return {
                "original_text": original_text,
                "translated_text": "การแปลล้มเหลว",
                "source_lang": source_lang,
                "target_lang": target_lang
            }
            
    except Exception as e:
        logger.error(f"Error in process_audio_and_translate: {str(e)}")
        return {
            "error": f"เกิดข้อผิดพลาด: {str(e)}",
            "source_lang": source_lang,
            "target_lang": target_lang
        }

async def send_error_message(websocket: WebSocket, message: str, details: str = None):
    """ฟังก์ชันสำหรับส่งข้อความ error"""
    try:
        if websocket.client_state == WebSocketState.CONNECTED:
            error_message = {"error": message}
            if details:
                error_message["details"] = details
            await websocket.send_json(error_message)
    except Exception as e:
        logger.error(f"Error sending error message: {str(e)}")

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """WebSocket endpoint หลัก"""
    try:
        # รับ connection ใหม่
        await websocket.accept()
        active_connections[client_id] = websocket
        logger.info(f"New client connected: {client_id}")

        # ตั้งค่าเริ่มต้นสำหรับภาษา
        source_lang = "th"
        target_lang = "en"

        while True:
            try:
                # รับข้อมูลจาก client
                data = await websocket.receive()
                
                # ตรวจสอบว่าเป็นข้อความหรือข้อมูล binary
                if data["type"] == "websocket.receive":
                    if "bytes" in data:
                        # เป็นข้อมูลเสียง
                        audio_data = data["bytes"]
                        
                        if not audio_data:
                            logger.warning("Received empty audio data")
                            continue

                        logger.info(f"Received audio data: {len(audio_data)} bytes")
                        
                        # ใช้ฟังก์ชันรวมสำหรับถอดเสียงและแปลภาษา
                        result = await process_audio_and_translate(audio_data, source_lang, target_lang)
                        
                        if result:
                            if "error" in result:
                                # ส่งข้อความแจ้งข้อผิดพลาด
                                await websocket.send_json({
                                    "error": result["error"],
                                    "source_lang": result["source_lang"],
                                    "target_lang": result["target_lang"]
                                })
                            else:
                                # ส่งข้อความต้นฉบับและข้อความที่แปลแล้ว
                                await websocket.send_json({
                                    "text": result["original_text"],
                                    "translated_text": result["translated_text"],
                                    "source_lang": result["source_lang"],
                                    "target_lang": result["target_lang"]
                                })
                        else:
                            # กรณีไม่มีผลลัพธ์
                            await websocket.send_json({
                                "error": "ไม่สามารถประมวลผลเสียงได้",
                                "source_lang": source_lang,
                                "target_lang": target_lang
                            })
                    
                    elif "text" in data:
                        # เป็นข้อความ JSON - ตรวจสอบว่าเป็นการตั้งค่าภาษาหรือไม่
                        try:
                            message = json.loads(data["text"])
                            if "source_lang" in message:
                                source_lang = message["source_lang"]
                                logger.info(f"Client {client_id} set source language to: {source_lang}")
                            if "target_lang" in message:
                                target_lang = message["target_lang"]
                                logger.info(f"Client {client_id} set target language to: {target_lang}")
                                
                            # ส่งการยืนยันกลับไป
                            await websocket.send_json({
                                "status": "ok",
                                "message": "Language settings updated",
                                "source_lang": source_lang,
                                "target_lang": target_lang
                            })
                        except json.JSONDecodeError:
                            logger.error("Received invalid JSON message")
                            await websocket.send_json({"error": "Invalid JSON message"})

            except WebSocketDisconnect:
                logger.info(f"Client disconnected normally: {client_id}")
                break
            except Exception as e:
                logger.error(f"Error processing message: {str(e)}")
                try:
                    await websocket.send_json({"error": f"เกิดข้อผิดพลาด: {str(e)}"})
                except:
                    break

    except Exception as e:
        logger.error(f"WebSocket connection error: {str(e)}")
        if client_id in active_connections:
            del active_connections[client_id]
        
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # ทดสอบการเชื่อมต่อกับ Whisper service
        url = urljoin(WHISPER_URL, "/health")
        response = requests.get(url, timeout=5)
        whisper_status = "up" if response.status_code == 200 else "down"
    except:
        whisper_status = "down"

    # ทดสอบการเชื่อมต่อกับ Translation service
    translation_status = "up"
    try:
        if TRANSLATION_SERVICE == "libre":
            test_response = requests.get(LIBRETRANSLATE_URL.replace("/translate", "/languages"), timeout=5)
            translation_status = "up" if test_response.status_code == 200 else "down"
    except:
        translation_status = "down"

    return {
        "status": "healthy",
        "whisper_service": whisper_status,
        "translation_service": TRANSLATION_SERVICE,
        "translation_status": translation_status
    }

@app.get("/")
def read_root():
    """Root endpoint"""
    return {
        "status": "running",
        "whisper_url": WHISPER_URL,
        "translation_service": TRANSLATION_SERVICE
    }

@app.get("/supported-languages")
def get_supported_languages():
    """Return supported languages for both source and target"""
    # สามารถเพิ่มภาษาที่รองรับได้ตามต้องการ
    languages = [
        {"code": "th", "name": "Thai"},
        {"code": "en", "name": "English"},
        {"code": "zh", "name": "Chinese"},
        {"code": "ja", "name": "Japanese"},
        {"code": "ko", "name": "Korean"},
        {"code": "fr", "name": "French"},
        {"code": "de", "name": "German"},
        {"code": "es", "name": "Spanish"},
        {"code": "it", "name": "Italian"},
        {"code": "ru", "name": "Russian"},
        {"code": "vi", "name": "Vietnamese"},
        {"code": "id", "name": "Indonesian"},
        {"code": "ms", "name": "Malay"},
        {"code": "ar", "name": "Arabic"},
        {"code": "pt", "name": "Portuguese"},
        {"code": "nl", "name": "Dutch"},
        {"code": "pl", "name": "Polish"},
        {"code": "tr", "name": "Turkish"},
        {"code": "cs", "name": "Czech"},
        {"code": "sv", "name": "Swedish"}
    ]
    
    return {
        "source_languages": languages,
        "target_languages": languages
    }

@app.post("/transcribe")
async def transcribe_audio(
    audio_file: UploadFile,
    source_lang: str = "th",
    target_lang: str = "en"
):
    try:
        # อ่านข้อมูลจากไฟล์
        audio_data = await audio_file.read()
        
        # ใช้ฟังก์ชันรวมสำหรับถอดเสียงและแปลภาษา
        result = await process_audio_and_translate(audio_data, source_lang, target_lang)
        
        if result:
            if "error" in result:
                return {"error": result["error"]}
            else:
                return {
                    "text": result["original_text"],
                    "translated_text": result["translated_text"],
                    "source_lang": result["source_lang"],
                    "target_lang": result["target_lang"]
                }
        else:
            return {"error": "ไม่สามารถประมวลผลเสียงได้"}
            
    except Exception as e:
        logger.error(f"Error in transcribe_audio: {str(e)}")
        return {"error": f"เกิดข้อผิดพลาด: {str(e)}"}

@app.get("/translation-services")
def get_translation_services():
    """ข้อมูลเกี่ยวกับบริการแปลภาษาที่รองรับ"""
    return {
        "current_service": TRANSLATION_SERVICE,
        "supported_services": ["libre", "google", "deepl"],
        "notes": {
            "libre": "บริการแปลภาษาโอเพนซอร์ส ฟรี แต่อาจมีข้อจำกัดในการใช้งาน",
            "google": "Google Translate API ต้องการ API key และมีค่าใช้จ่าย",
            "deepl": "DeepL API มีทั้งแบบฟรีและแบบเสียเงิน ให้ผลลัพธ์ที่แม่นยำสูง"
        }
    }

@app.post("/text-translate")
async def text_translate(
    text: str,
    source_lang: str = "th",
    target_lang: str = "en"
):
    """API สำหรับแปลข้อความโดยตรง"""
    try:
        translated_text = await translate_text(text, source_lang, target_lang)
        
        if translated_text:
            return {
                "original_text": text,
                "translated_text": translated_text,
                "source_lang": source_lang,
                "target_lang": target_lang
            }
        else:
            return {"error": "ไม่สามารถแปลข้อความได้"}
            
    except Exception as e:
        logger.error(f"Error in text_translate: {str(e)}")
        return {"error": f"เกิดข้อผิดพลาด: {str(e)}"}
    
@app.get("/whisper-capabilities")
async def get_whisper_capabilities():
    """ตรวจสอบความสามารถของ Whisper service ที่มีอยู่จริง"""
    try:
        # ตรวจสอบการเชื่อมต่อกับ Whisper
        health_url = urljoin(WHISPER_URL, "/openapi.json")
        health_response = await asyncio.to_thread(
            requests.get,
            health_url,
            timeout=5
        )
        
        whisper_available = health_response.status_code == 200
        
        return {
            "use_whisper_translation": True,
            "supports_translation": True,
            "can_transcribe": whisper_available,
            "can_translate": whisper_available,
            "whisper_status": "ready" if whisper_available else "unavailable",
            "error": None if whisper_available else "Cannot connect to Whisper service"
        }
    except Exception as e:
        logger.error(f"Error checking Whisper capabilities: {str(e)}")
        return {
            "use_whisper_translation": True,
            "supports_translation": True,
            "can_transcribe": False,
            "can_translate": False,
            "whisper_status": "error",
            "error": str(e)
        }