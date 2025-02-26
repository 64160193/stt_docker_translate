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
WHISPER_TRANSLATE_ENDPOINT = os.getenv("WHISPER_TRANSLATE_ENDPOINT", "/asr")  # ใช้ endpoint เดียวกันแต่เปลี่ยน task

# บังคับใช้เฉพาะ Whisper เท่านั้น
WHISPER_SUPPORTS_TRANSLATION = True
USE_WHISPER_TRANSLATION = True

# เก็บ active connections
active_connections: Dict[str, WebSocket] = {}
ping_tasks: Dict[str, asyncio.Task] = {}

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

async def process_audio_with_translation(audio_data, source_lang="th", target_lang="en") -> Optional[dict]:
    """ฟังก์ชันสำหรับส่งข้อมูลเสียงไปยัง Whisper API เพื่อแปลภาษา"""
    try:
        files = {
            'audio_file': ('audio.webm', audio_data, 'audio/webm')
        }
        url = urljoin(WHISPER_URL, WHISPER_TRANSLATE_ENDPOINT)
        
        logger.info(f"Sending request to Whisper for translation: {url}")
        logger.info(f"Audio data size: {len(audio_data)} bytes")
        logger.info(f"Source language: {source_lang}, Target language: {target_lang}")
        
        params = {
            "task": "translate",  
            "language": source_lang,
            "output": "json"
        }
        
        if target_lang != "en":
            params["target_language"] = target_lang
        
        response = await asyncio.to_thread(
            requests.post,
            url,
            files=files,
            params=params,
            timeout=30
        )
        
        logger.debug(f"Whisper response status: {response.status_code}")
        logger.debug(f"Whisper response content: {response.text}")
        
        if response.status_code == 200:
            translation_result = response.json()
            translated_text = translation_result.get("text", "").strip()
            
            original_text = translation_result.get("original_text", "")
            
            # ถ้าไม่มีข้อความต้นฉบับ ให้ถอดเสียงอีกครั้ง
            if not original_text:
                logger.info("No original text in translation response, transcribing separately")
                transcription_response = await process_audio(audio_data, source_lang)
                
                if transcription_response and transcription_response.status_code == 200:
                    transcription_result = transcription_response.json()
                    original_text = transcription_result.get("text", "").strip()
                    logger.info(f"Successfully transcribed original text: {original_text[:30]}...")
            
            return {
                "original_text": original_text,
                "translated_text": translated_text,
                "source_lang": source_lang,
                "target_lang": target_lang
            }
        else:
            logger.error(f"Whisper API error: {response.status_code}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in process_audio_with_translation: {str(e)}")
        return None

async def process_audio_and_translate(audio_data, source_lang="th", target_lang="en") -> Optional[dict]:
    """ฟังก์ชันรวมสำหรับถอดเสียงและแปลภาษา โดยใช้เฉพาะ Whisper"""
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
            error_msg = "ไม่สามารถเชื่อมต่อกับ Whisper service" if not transcription_response else f"Whisper error: {transcription_response.status_code}"
            logger.error(error_msg)
            return {
                "error": error_msg,
                "source_lang": source_lang,
                "target_lang": target_lang
            }
        
        # ใช้ Whisper แปลภาษา
        logger.info(f"Translating from {source_lang} to {target_lang} using Whisper")
        translation_result = await process_audio_with_translation(audio_data, source_lang, target_lang)
        
        if translation_result and translation_result.get("translated_text"):
            translated_text = translation_result.get("translated_text")
            logger.info(f"Successfully translated: {translated_text[:50]}...")
            
            return {
                "original_text": original_text,
                "translated_text": translated_text,
                "source_lang": source_lang,
                "target_lang": target_lang
            }
        else:
            # กรณี Whisper แปลไม่สำเร็จ
            logger.warning("Whisper translation failed")
            return {
                "original_text": original_text,
                "translated_text": "การแปลด้วย Whisper ล้มเหลว",
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

    return {
        "status": "healthy",
        "whisper_service": whisper_status,
        "whisper_translation_enabled": True
    }

@app.get("/")
def read_root():
    """Root endpoint"""
    return {
        "status": "running",
        "whisper_url": WHISPER_URL,
        "whisper_translation_enabled": True
    }

@app.get("/supported-languages")
def get_supported_languages():
    """Return supported languages for both source and target"""
    return {
        "source_languages": [
            {"code": "th", "name": "Thai"},
            {"code": "en", "name": "English"},
            {"code": "zh", "name": "Chinese"},
            {"code": "ja", "name": "Japanese"},
            {"code": "ko", "name": "Korean"},
            {"code": "fr", "name": "French"},
            {"code": "de", "name": "German"},
            {"code": "es", "name": "Spanish"},
            {"code": "it", "name": "Italian"},
            {"code": "ru", "name": "Russian"}
        ],
        "target_languages": [
            {"code": "th", "name": "Thai"},
            {"code": "en", "name": "English"},
            {"code": "zh", "name": "Chinese"},
            {"code": "ja", "name": "Japanese"},
            {"code": "ko", "name": "Korean"},
            {"code": "fr", "name": "French"},
            {"code": "de", "name": "German"},
            {"code": "es", "name": "Spanish"},
            {"code": "it", "name": "Italian"},
            {"code": "ru", "name": "Russian"}
        ]
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

# เพิ่มฟังก์ชันตรวจสอบ Whisper capabilities
@app.get("/whisper-capabilities")
async def whisper_capabilities():
    """ตรวจสอบความสามารถของ Whisper API"""
    try:
        # ทดสอบว่า Whisper API รองรับการถอดเสียงและแปลภาษาหรือไม่
        test_audio_path = os.getenv("TEST_AUDIO_PATH", "./test_audio.webm")
        
        if os.path.exists(test_audio_path):
            with open(test_audio_path, "rb") as f:
                test_audio = f.read()
                
            # ทดสอบถอดเสียง
            transcribe_response = await process_audio(test_audio, "en")
            can_transcribe = transcribe_response is not None and transcribe_response.status_code == 200
            
            # ทดสอบแปลภาษา
            translate_result = await process_audio_with_translation(test_audio, "en", "th")
            can_translate = translate_result is not None and "translated_text" in translate_result
            
            return {
                "whisper_url": WHISPER_URL,
                "can_transcribe": can_transcribe,
                "can_translate": can_translate,
                "supports_translation": True,
                "use_whisper_translation": True
            }
        else:
            return {
                "error": f"Test audio file not found: {test_audio_path}",
                "whisper_url": WHISPER_URL,
                "supports_translation": True,
                "use_whisper_translation": True
            }
    except Exception as e:
        logger.error(f"Error checking Whisper capabilities: {str(e)}")
        return {"error": f"เกิดข้อผิดพลาดในการตรวจสอบความสามารถของ Whisper: {str(e)}"}