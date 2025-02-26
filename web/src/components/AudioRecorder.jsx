import React, { useState, useEffect, useRef } from 'react';
import { Mic, Globe, Volume2, AlertCircle } from 'lucide-react';

const AudioRecorder = () => {
  const [isRecording, setIsRecording] = useState(false);
  const [error, setError] = useState('');
  const [connectionStatus, setConnectionStatus] = useState('กำลังเชื่อมต่อ...');
  const [isConnected, setIsConnected] = useState(false);
  const [transcription, setTranscription] = useState('');
  const [translation, setTranslation] = useState('');
  const [reconnectAttempts, setReconnectAttempts] = useState(0);
  const [isProcessing, setIsProcessing] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  
  // ภาษาที่รองรับ
  const [sourceLanguages, setSourceLanguages] = useState([
    { code: "th", name: "Thai" },
    { code: "en", name: "English" },
    { code: "zh", name: "Chinese" },
    { code: "ja", name: "Japanese" },
    { code: "ko", name: "Korean" }
  ]);
  const [targetLanguages, setTargetLanguages] = useState([
    { code: "th", name: "Thai" },
    { code: "en", name: "English" },
    { code: "zh", name: "Chinese" },
    { code: "ja", name: "Japanese" },
    { code: "ko", name: "Korean" }
  ]);
  
  // ภาษาที่เลือก
  const [sourceLanguage, setSourceLanguage] = useState('th');
  const [targetLanguage, setTargetLanguage] = useState('en');
  
  // แสดงว่ากำลังรอการตั้งค่าภาษาหรือไม่
  const [isSettingLanguage, setIsSettingLanguage] = useState(false);
  
  // ข้อมูลสถานะการแปลด้วย Whisper
  const [whispperInfo, setWhisperInfo] = useState({
    usingWhisperTranslation: true,
    supportsTranslation: true
  });

  const ws = useRef(null);
  const mediaRecorder = useRef(null);
  const audioContext = useRef(null);
  const analyser = useRef(null);
  const audioLevelInterval = useRef(null);

  useEffect(() => {
    initializeWebSocket();
    fetchSupportedLanguages();
    checkWhisperCapabilities();

    return () => {
      cleanupWebSocket();
      cleanupAudioAnalyser();
    };
  }, []);
  
  const cleanupAudioAnalyser = () => {
    if (audioLevelInterval.current) {
      clearInterval(audioLevelInterval.current);
      audioLevelInterval.current = null;
    }
    
    if (audioContext.current) {
      audioContext.current.close().catch(console.error);
      audioContext.current = null;
      analyser.current = null;
    }
  };
  
  // ดึงข้อมูลความสามารถของ Whisper
  const checkWhisperCapabilities = async () => {
    try {
      const response = await fetch('http://localhost:8000/whisper-capabilities');
      
      if (response.ok) {
        const data = await response.json();
        setWhisperInfo({
          usingWhisperTranslation: data.use_whisper_translation,
          supportsTranslation: data.supports_translation,
          canTranscribe: data.can_transcribe,
          canTranslate: data.can_translate
        });
        console.log('Whisper capabilities:', data);
      } else {
        console.error('Failed to fetch Whisper capabilities');
      }
    } catch (error) {
      console.error('Error checking Whisper capabilities:', error);
    }
  };
  
  // ดึงข้อมูลภาษาที่รองรับจาก backend
  const fetchSupportedLanguages = async () => {
    try {
      const response = await fetch('http://localhost:8000/supported-languages');
      
      if (response.ok) {
        const data = await response.json();
        if (data.source_languages && data.source_languages.length > 0) {
          setSourceLanguages(data.source_languages);
        }
        if (data.target_languages && data.target_languages.length > 0) {
          setTargetLanguages(data.target_languages);
        }
      } else {
        console.error('Failed to fetch supported languages');
      }
    } catch (error) {
      console.error('Error fetching supported languages:', error);
    }
  };

  const cleanupWebSocket = () => {
    if (ws.current) {
      ws.current.unmounted = true;
      ws.current = null;
    }
    if (mediaRecorder.current?.state === 'recording') {
      stopRecording();
    }
  };

  const handleReconnect = () => {
    if (reconnectAttempts < 5) {
      setTimeout(() => {
        setReconnectAttempts(prev => prev + 1);
        initializeWebSocket();
      }, 3000); // รอ 3 วินาทีก่อนลองเชื่อมต่อใหม่
    }
  };

  const initializeWebSocket = () => {
    // ตรวจสอบและจัดการกับการเชื่อมต่อที่มีอยู่
    if (ws.current) {
      ws.current.removeEventListener('open', null);
      ws.current.removeEventListener('message', null);
      ws.current.removeEventListener('error', null);
      ws.current.removeEventListener('close', null);
      ws.current = null;
    }

    // สร้าง WebSocket connection ใหม่
    try {
      console.log(`Attempting to connect to WebSocket... (attempt ${reconnectAttempts + 1})`);
      const clientId = Math.random().toString(36).substring(2, 9);
      const wsUrl = `ws://localhost:8000/ws/${clientId}`;
      console.log('Connecting to:', wsUrl);

      ws.current = new WebSocket(wsUrl);

      // จัดการ Connection Timeout
      const connectionTimeout = setTimeout(() => {
        if (ws.current?.readyState !== WebSocket.OPEN) {
          console.log('Connection timeout - closing socket');
          ws.current?.close();
          setError('การเชื่อมต่อหมดเวลา');
          setConnectionStatus('ไม่สามารถเชื่อมต่อได้ - กรุณาลองใหม่');
          handleReconnect();
        }
      }, 10000); // 10 วินาที timeout

      // Event Handlers
      ws.current.addEventListener('open', () => {
        console.log('WebSocket Connected! ReadyState:', ws.current?.readyState);
        clearTimeout(connectionTimeout);
        setIsConnected(true);
        setConnectionStatus('เชื่อมต่อแล้ว');
        setError('');
        setReconnectAttempts(0); // รีเซ็ตตัวนับเมื่อเชื่อมต่อสำเร็จ
        
        // ส่งการตั้งค่าภาษาเริ่มต้น
        updateLanguageSettings();
      });

      ws.current.addEventListener('message', handleWebSocketMessage);
      
      ws.current.addEventListener('error', (event) => {
        console.error('WebSocket error:', event);
        setError('เกิดข้อผิดพลาดในการเชื่อมต่อ');
      });
      
      ws.current.addEventListener('close', (event) => {
        console.log('WebSocket closed:', event);
        setIsConnected(false);
        setConnectionStatus('การเชื่อมต่อถูกปิด - กำลังลองใหม่');
        handleReconnect();
      });

    } catch (error) {
      console.error('WebSocket initialization error:', error);
      setError(`ไม่สามารถเริ่มการเชื่อมต่อได้: ${error?.message || 'Unknown error'}`);
      handleReconnect();
    }
  };

  const handleWebSocketMessage = (event) => {
    if (!event.data) return;
    try {
      const message = JSON.parse(event.data);
      
      // หยุดการแสดงสถานะกำลังประมวลผล
      setIsProcessing(false);
      
      // ตรวจสอบข้อความผิดพลาด
      if (message.error) {
        console.error('Server error:', message.error);
        setIsSettingLanguage(false);
        
        // จัดการข้อความผิดพลาดตามประเภท
        if (message.error === "ไม่พบข้อความในเสียง") {
          setError('ไม่พบข้อความในเสียง กรุณาลองพูดใหม่อีกครั้ง');
        } else if (message.error.includes("Translation failed")) {
          // เก็บข้อความต้นฉบับแต่แสดงข้อความแจ้งเตือนการแปลล้มเหลว
          setTranslation(prev => {
            const errorMessage = "⚠️ การแปลล้มเหลว กรุณาลองอีกครั้ง";
            return errorMessage;
          });
        } else {
          setError(message.error);
        }
        return;
      }
      
      // ตรวจสอบข้อความปกติ
      if (message.text) {
        setTranscription(prev => {
          const newText = message.text.trim();
          return prev ? `${prev} ${newText}` : newText;
        });
        
        // จัดการกับข้อความแปล
        if (message.translated_text) {
          const translatedText = message.translated_text.trim();
          
          // ตรวจสอบว่าการแปลล้มเหลวหรือไม่
          if (translatedText.includes("Translation failed") || 
              translatedText.includes("Maximum retries exceeded")) {
            setTranslation(prev => {
              const errorMessage = "⚠️ การแปลล้มเหลว กรุณาลองอีกครั้ง";
              return prev ? `${prev}\n${errorMessage}` : errorMessage;
            });
          } else {
            // การแปลสำเร็จ
            setTranslation(prev => {
              return prev ? `${prev} ${translatedText}` : translatedText;
            });
          }
        }
      } else if (message.status === "ok" && message.message === "Language settings updated") {
        // การตั้งค่าภาษาสำเร็จ
        setIsSettingLanguage(false);
        console.log('Language settings updated successfully');
      }
    } catch (error) {
      console.error('Error parsing message:', error);
      setError('ข้อผิดพลาดในการประมวลผลข้อความจากเซิร์ฟเวอร์');
      setIsSettingLanguage(false);
      setIsProcessing(false);
    }
  };

  const startRecording = async () => {
    try {
      console.log('Requesting microphone access...');
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 44100,
          sampleSize: 16,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,  // เพิ่มการควบคุม gain อัตโนมัติ
        },
      });

      // ตั้งค่า Audio Context สำหรับวิเคราะห์ระดับเสียง
      setupAudioAnalyser(stream);

      let mimeType = 'audio/webm;codecs=opus';
      if (!MediaRecorder.isTypeSupported(mimeType)) {
        console.log('WebM not supported, falling back to default format');
        mimeType = '';
      }

      mediaRecorder.current = new MediaRecorder(stream, {
        mimeType: 'audio/webm;codecs=opus',
        audioBitsPerSecond: 128000,
      });

      mediaRecorder.current.addEventListener('start', () => {
        console.log('MediaRecorder started');
      });

      let audioChunks = [];

      mediaRecorder.current.addEventListener('dataavailable', (event) => {
        console.log('Received audio chunk:', event.data.size, 'bytes');
        if (event.data.size > 0) {
          audioChunks.push(event.data);
        }
      });

      mediaRecorder.current.addEventListener('stop', async () => {
        try {
          const blob = new Blob(audioChunks, { type: 'audio/webm;codecs=opus' });
          const arrayBuffer = await blob.arrayBuffer();
          
          // Log ขนาดและ type ของข้อมูลก่อนส่ง
          console.log('Client sending:', {
            blobSize: blob.size,
            blobType: blob.type,
            arrayBufferSize: arrayBuffer.byteLength
          });

          // ตรวจสอบว่าขนาดเสียงเล็กเกินไปหรือไม่ (อาจจะไม่มีเสียงพูด)
          if (blob.size < 1000) { // ประมาณ 1KB
            setError('ไม่พบเสียงพูด กรุณาลองใหม่');
            return;
          }

          // แสดงสถานะกำลังประมวลผล
          setIsProcessing(true);

          // ตั้งค่า WebSocket binary type
          if (ws.current) {
            ws.current.binaryType = 'arraybuffer';
            
            // ส่งข้อมูล
            ws.current.send(arrayBuffer);
          }
          
          // เคลียร์ chunks สำหรับการบันทึกครั้งต่อไป
          audioChunks = [];
        } catch (error) {
          console.error('Client error:', error);
          setError(`เกิดข้อผิดพลาดในการส่งข้อมูล: ${error?.message || 'Unknown error'}`);
          setIsProcessing(false);
        }
      });

      mediaRecorder.current.start();
      setIsRecording(true);
      setError('');

      // ลดเวลาในการส่งช่วงเสียงจาก 3 วินาทีเป็น 2 วินาที เพื่อให้ตอบสนองเร็วขึ้น
      const interval = setInterval(() => {
  if (mediaRecorder.current?.state === 'recording') {
    mediaRecorder.current.stop();
    mediaRecorder.current.start();
  }
}, 5000);   // ลดลงจาก 3000 เป็น 2000

      mediaRecorder.current.interval = interval;

    } catch (err) {
      console.error('Recording error:', err);
      if (err.name === 'NotAllowedError') {
        setError('ไม่ได้รับอนุญาตให้เข้าถึงไมโครโฟน');
      } else if (err.name === 'NotFoundError') {
        setError('ไม่พบไมโครโฟนที่เชื่อมต่อ');
      } else {
        setError(`ไม่สามารถเข้าถึงไมโครโฟนได้: ${err?.message || 'Unknown error'}`);
      }
    }
  };

  // ตั้งค่า Audio Analyser เพื่อวิเคราะห์ระดับเสียง
  const setupAudioAnalyser = (stream) => {
    try {
      // เคลียร์ก่อนตั้งค่าใหม่
      cleanupAudioAnalyser();
      
      audioContext.current = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioContext.current.createMediaStreamSource(stream);
      analyser.current = audioContext.current.createAnalyser();
      analyser.current.fftSize = 256;
      source.connect(analyser.current);
      
      const bufferLength = analyser.current.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);
      
      // ตรวจสอบระดับเสียงอย่างต่อเนื่อง
      audioLevelInterval.current = setInterval(() => {
        if (analyser.current) {
          analyser.current.getByteFrequencyData(dataArray);
          
          // คำนวณค่าเฉลี่ยของระดับเสียง
          let sum = 0;
          for(let i = 0; i < bufferLength; i++) {
            sum += dataArray[i];
          }
          const average = sum / bufferLength;
          
          // อัพเดทระดับเสียงสำหรับการแสดงผล (0-100)
          setAudioLevel(Math.min(100, average * 2));
          
          // แสดงคำเตือนถ้าเสียงเบาเกินไป
          if (average < 10 && isRecording) {
            setError('เสียงเบาเกินไป กรุณาพูดดังขึ้นหรือตรวจสอบไมโครโฟน');
          } else if (isRecording) {
            setError(''); // ล้างข้อความ error เมื่อระดับเสียงปกติ
          }
        }
      }, 100);
    } catch (err) {
      console.error('Error setting up audio analyser:', err);
    }
  };

  const stopRecording = () => {
    if (mediaRecorder.current?.state === 'recording') {
      clearInterval(mediaRecorder.current.interval);
      mediaRecorder.current.stop();
      mediaRecorder.current.stream.getTracks().forEach((track) => track.stop());
    }
    setIsRecording(false);
    
    // ไม่ต้องเคลียร์ audio analyser เพื่อให้ยังแสดงระดับเสียงได้
    // แต่หยุดการแสดงข้อความเตือนเมื่อเสียงเบา
    setError('');
  };

  const clearText = () => {
    setTranscription('');
    setTranslation('');
  };
  
  // ส่งการตั้งค่าภาษาไปยัง backend
  const updateLanguageSettings = () => {
    if (!ws.current || ws.current.readyState !== WebSocket.OPEN) {
      console.log('Cannot update language settings: WebSocket not connected');
      return;
    }
    
    setIsSettingLanguage(true);
    const settings = {
      source_lang: sourceLanguage,
      target_lang: targetLanguage
    };
    
    try {
      ws.current.send(JSON.stringify(settings));
      console.log('Sent language settings:', settings);
    } catch (error) {
      console.error('Error sending language settings:', error);
      setError(`ไม่สามารถตั้งค่าภาษา: ${error?.message || 'Unknown error'}`);
      setIsSettingLanguage(false);
    }
  };
  
  // เมื่อเลือกภาษาต้นทางหรือปลายทาง
  const handleSourceLanguageChange = (e) => {
    setSourceLanguage(e.target.value);
  };
  
  const handleTargetLanguageChange = (e) => {
    setTargetLanguage(e.target.value);
  };

  // ดำเนินการเมื่อกดปุ่มอัพเดตภาษา
  const handleLanguageUpdateClick = () => {
    updateLanguageSettings();
  };

  return (
    <div className="max-w-2xl mx-auto p-6">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-2xl font-bold">บันทึกเสียงและแปลภาษา</h1>
        <div className="flex items-center">
          <div
            className={`w-2 h-2 rounded-full mr-2 ${
              isConnected ? 'bg-green-500' : 'bg-gray-300'
            }`}
          />
          <span className="text-sm text-gray-600">{connectionStatus}</span>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border-l-4 border-red-500 p-4 mb-6">
          <div className="text-red-700">{error}</div>
        </div>
      )}

      {/* Translation Method Info */}
      <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg mb-6 text-sm text-blue-800 flex items-start">
        <AlertCircle className="w-5 h-5 mr-2 flex-shrink-0 mt-0.5" />
        <div>
          <p className="font-medium">ระบบการแปลภาษา: {whispperInfo.usingWhisperTranslation ? 'Whisper Translation' : 'External Translation API'}</p>
          <p>Whisper จะ{whispperInfo.usingWhisperTranslation ? '' : 'ไม่'}ถอดเสียงและแปลภาษาในขั้นตอนเดียวกัน</p>
        </div>
      </div>

      {/* Language Selection Panel */}
      <div className="mb-6 p-4 bg-gray-50 rounded-lg border border-gray-200">
        <div className="flex items-center mb-3">
          <Globe className="w-5 h-5 mr-2 text-gray-600" />
          <h2 className="font-semibold">ตั้งค่าภาษา</h2>
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              ภาษาต้นทาง (ที่พูด)
            </label>
            <select
              value={sourceLanguage}
              onChange={handleSourceLanguageChange}
              className="block w-full py-2 px-3 border border-gray-300 bg-white rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
              disabled={isSettingLanguage || isRecording}
            >
              {sourceLanguages.map(lang => (
                <option key={lang.code} value={lang.code}>
                  {lang.name}
                </option>
              ))}
            </select>
          </div>
          
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              ภาษาปลายทาง (แปลเป็น)
            </label>
            <select
              value={targetLanguage}
              onChange={handleTargetLanguageChange}
              className="block w-full py-2 px-3 border border-gray-300 bg-white rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
              disabled={isSettingLanguage || isRecording}
            >
              {targetLanguages.map(lang => (
                <option key={lang.code} value={lang.code}>
                  {lang.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        
        <button
          onClick={handleLanguageUpdateClick}
          className={`w-full py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white ${
            isSettingLanguage 
              ? 'bg-gray-400 cursor-not-allowed' 
              : 'bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500'
          }`}
          disabled={isSettingLanguage || isRecording}
        >
          {isSettingLanguage ? 'กำลังบันทึกการตั้งค่า...' : 'บันทึกการตั้งค่าภาษา'}
        </button>
      </div>

      {/* Recording Button and Audio Level */}
      <div className="flex flex-col items-center justify-center p-8 bg-gray-50 rounded-lg">
        {/* Audio Level Meter */}
        <div className="w-full mb-4">
          <div className="flex items-center mb-1">
            <Volume2 className="w-4 h-4 mr-1 text-gray-600" />
            <span className="text-xs text-gray-600">ระดับเสียง</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2.5">
            <div 
              className={`h-2.5 rounded-full ${
                audioLevel > 50 ? 'bg-green-500' : audioLevel > 20 ? 'bg-yellow-500' : 'bg-red-500'
              }`}
              style={{ width: `${audioLevel}%` }}
            ></div>
          </div>
        </div>

        <button
          onClick={isRecording ? stopRecording : startRecording}
          className={`p-6 rounded-full transition-colors ${
            isRecording ? 'bg-red-500 hover:bg-red-600' : 'bg-blue-500 hover:bg-blue-600'
          }`}
          disabled={!isConnected || isSettingLanguage}
        >
          <Mic className="w-8 h-8 text-white" />
        </button>
        <div className="mt-4 text-gray-600">
          {isRecording ? 'กำลังบันทึก...' : 'กดเพื่อเริ่มบันทึก'}
        </div>
      </div>

      {/* Processing Indicator */}
      {isProcessing && (
        <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg text-yellow-800 text-center">
          กำลังประมวลผลเสียง กรุณารอสักครู่...
        </div>
      )}

      {/* Source language transcription */}
      <div className="mt-6">
        <div className="flex justify-between items-center mb-2">
          <h2 className="font-semibold">
            ข้อความต้นฉบับ ({sourceLanguages.find(l => l.code === sourceLanguage)?.name || sourceLanguage})
          </h2>
          <button 
            onClick={clearText}
            className="text-sm text-blue-500 hover:text-blue-700"
          >
            ล้างข้อความ
          </button>
        </div>
        <div className="p-4 bg-white rounded-lg border border-gray-200 min-h-[100px]">
          <div className={transcription ? 'text-gray-900' : 'text-gray-400'}>
            {transcription || 'ข้อความที่ถอดความจะแสดงที่นี่...'}
          </div>
        </div>
      </div>
      
      {/* Target language translation */}
      <div className="mt-6">
        <h2 className="font-semibold mb-2">
          คำแปล ({targetLanguages.find(l => l.code === targetLanguage)?.name || targetLanguage})
        </h2>
        <div className="p-4 bg-white rounded-lg border border-gray-200 min-h-[100px]">
          <div className={translation ? (translation.includes('⚠️') ? 'text-red-500' : 'text-gray-900') : 'text-gray-400'}>
            {translation || 'คำแปลจะแสดงที่นี่...'}
          </div>
        </div>
      </div>
    </div>
  );
};

export default AudioRecorder;