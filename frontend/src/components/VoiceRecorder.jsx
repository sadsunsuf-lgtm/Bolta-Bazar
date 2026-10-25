import React, { useState, useRef, useEffect } from 'react';

const VoiceRecorder = ({ onResult, onTranscriptUpdate, lang, getText }) => {
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const recognitionRef = useRef(null);

  // Sync Voice Recognition Language with App Language
  useEffect(() => {
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

      // Re-initialize or update language whenever 'lang' prop changes
      if (!recognitionRef.current) {
        recognitionRef.current = new SR();
        recognitionRef.current.continuous = true;
        recognitionRef.current.interimResults = true;
      }

      // Set correct language: ur-PK for Urdu, en-US for English
      recognitionRef.current.lang = lang === 'ur' ? 'ur-PK' : 'en-US';

      recognitionRef.current.onresult = (event) => {
        let interim = '', final = '';
        for (let i = event.resultIndex; i < event.results.length; ++i) {
          if (event.results[i].isFinal) final += event.results[i][0].transcript;
          else interim += event.results[i][0].transcript;
        }
        // Send the most relevant text to the Live Transcription box
        if (onTranscriptUpdate) onTranscriptUpdate(final || interim);
      };

      recognitionRef.current.onerror = (event) => {
        console.error("Speech Recognition Error:", event.error);
      };
    }
  }, [lang, onTranscriptUpdate]); // Re-run when language changes

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      mediaRecorder.onstop = async () => {
        const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        await processAudio(blob);
      };

      mediaRecorder.start();

      // Start the live listener
      if (recognitionRef.current) {
        try { recognitionRef.current.start(); } catch (_) { }
      }

      setIsRecording(true);
      if (onTranscriptUpdate) onTranscriptUpdate(getText('listening'));
    } catch (err) {
      alert('Microphone access denied. Please allow microphone in your browser.');
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current.stream.getTracks().forEach(t => t.stop());
    }
    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch (_) { }
    }
    setIsRecording(false);
  };

  const playSuccessSound = () => {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      gain.gain.setValueAtTime(0.1, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.2);
      osc.connect(gain); gain.connect(ctx.destination);
      osc.start(); osc.stop(ctx.currentTime + 0.2);
    } catch (_) { }
  };

  const processAudio = async (audioBlob) => {
    setIsProcessing(true);
    if (onTranscriptUpdate) onTranscriptUpdate(getText('sendingToAI'));

    const formData = new FormData();
    formData.append('audio', audioBlob, 'recording.webm');

    try {
      const apiBaseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
      const response = await fetch(`${apiBaseUrl}/api/process-voice`, {
        method: 'POST',
        body: formData
      });

      if (!response.ok) throw new Error(`Server error: ${response.status}`);
      const data = await response.json();

      if (!data.error) {
        playSuccessSound();
        if (onResult) onResult(data);
      } else {
        if (onTranscriptUpdate) onTranscriptUpdate(`❌ ${data.error}`);
      }
    } catch (error) {
      console.error('Error processing audio:', error);
      const msg = lang === 'ur' ? '❌ رابطہ نہیں ہو سکا' : '❌ Connection failed.';
      if (onTranscriptUpdate) onTranscriptUpdate(msg);
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="flex flex-col items-center justify-center w-full">
      {/* High-End Mic Button */}
      <div className="relative">
        {isRecording && (
          <div className="absolute inset-0 bg-blue-400 rounded-full animate-ping opacity-20"></div>
        )}
        <button
          onClick={isRecording ? stopRecording : startRecording}
          disabled={isProcessing}
          className={`relative z-10 w-32 h-32 rounded-full flex items-center justify-center text-white transition-all shadow-2xl border-8
            ${isProcessing ? 'bg-gray-200 border-gray-100 cursor-not-allowed' :
              isRecording ? 'bg-red-500 border-red-100 scale-110' :
                'bg-blue-600 border-blue-50 hover:scale-105 active:scale-95'}`}
        >
          <span className="text-5xl">
            {isProcessing ? '⏳' : isRecording ? '⏹' : '🎤'}
          </span>
        </button>
      </div>

      <div className="mt-10 text-center">
        <p className={`text-sm font-black uppercase tracking-widest ${isRecording ? 'text-red-500 animate-pulse' : 'text-gray-400'}`}>
          {isRecording ? getText('recording') : isProcessing ? getText('processingVoice') : getText('tapToRecord')}
        </p>
      </div>

      {/* Progress Bar for Processing */}
      {isProcessing && (
        <div className="w-48 h-1.5 bg-gray-100 rounded-full mt-4 overflow-hidden">
          <div className="h-full bg-blue-600 animate-[progress_2s_ease-in-out_infinite] w-1/2 rounded-full"></div>
        </div>
      )}
    </div>
  );
};

export default VoiceRecorder;