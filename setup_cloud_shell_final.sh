#!/bin/bash
set -e

# Create directories
mkdir -p bolta-bazaar/backend/services
mkdir -p bolta-bazaar/frontend/src/components

cat <<'EOF' > bolta-bazaar/backend/requirements.txt
fastapi
uvicorn
google-genai
python-multipart
python-dotenv
google-cloud-firestore

EOF

cat <<'EOF' > bolta-bazaar/backend/main.py
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from services.voice_processor import process_audio
from services.firestore_service import get_inventory, update_inventory_item
import shutil
import os
import tempfile
import json

app = FastAPI(title="Bolta Bazaar API")

# Professional CORS setup: allow all in production for now, restrict later
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Bolta Bazaar API is Live!", "region": "asia-south1"}

@app.get("/api/inventory")
async def fetch_inventory():
    try:
        return get_inventory()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/process-voice")
async def process_voice(audio: UploadFile = File(...)):
    try:
        suffix = ""
        if audio.filename:
            _, ext = os.path.splitext(audio.filename)
            suffix = ext or ".webm"
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_audio:
            shutil.copyfileobj(audio.file, temp_audio)
            temp_path = temp_audio.name
            
        # 1. Process audio with Gemini
        result_text = process_audio(temp_path)
        os.remove(temp_path)
        
        data = json.loads(result_text)
        
        # 2. Sync with Firestore if action and item are present
        if "action" in data and "item" in data:
            qty = int(data.get("qty", 1))
            updated_item = update_inventory_item(data["item"], data["action"], qty)
            data["updated_inventory_item"] = updated_item
            
        return data
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/inventory/adjust")
async def adjust_inventory(data: dict):
    """Manual adjustment endpoint."""
    try:
        item_name = data.get("name")
        delta = data.get("delta", 0)
        action = "add" if delta > 0 else "sale"
        return update_inventory_item(item_name, action, abs(delta))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

EOF

cat <<'EOF' > bolta-bazaar/backend/Dockerfile
# Use Python 3.12 slim for smaller image size
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PORT 8080

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose the port FastAPI will run on
EXPOSE 8080

# Command to run the application using uvicorn
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]

EOF

cat <<'EOF' > bolta-bazaar/backend/services/voice_processor.py
from google import genai
from google.genai import types
import os
import time
from dotenv import load_dotenv

load_dotenv()

# Define the client at the top level
client = genai.Client(
    api_key=os.getenv('GOOGLE_API_KEY'),
    http_options={'api_version': 'v1beta'}
)

def process_audio(file_path: str) -> str:
    system_instruction = (
        "You are an expert Urdu-speaking shop assistant for 'Bolta Bazaar'. "
        "Extract structured JSON from audio input.\n"
        "Logic: 'add' for new stock, 'sale' for sold items (words like 'becha', 'khatam', 'dedo' imply sale).\n"
        "Standardize item names to English (e.g., 'chawal' -> 'rice', 'cheeni' -> 'sugar', 'aata' -> 'flour', 'tel' -> 'oil').\n"
        "Example: '10 kilo chawal mangwaye hain' -> {\"action\": \"add\", \"item\": \"rice\", \"qty\": 10, \"unit\": \"kg\"}."
    )
    
    # 1. Upload the file to Gemini
    uploaded_file = client.files.upload(
        file=file_path, 
        config={'mime_type': 'audio/webm'}
    )
    
    # 2. WAIT for the file to be processed (Crucial to prevent 400/500 errors)
    while uploaded_file.state.name == "PROCESSING":
        print("Processing audio on Gemini servers...")
        time.sleep(1)
        uploaded_file = client.files.get(name=uploaded_file.name)
        
    if uploaded_file.state.name == "FAILED":
        client.files.delete(name=uploaded_file.name)
        raise Exception(f"Audio processing failed: {uploaded_file.error}")

    # 3. Use Gemini 3.1 Flash-Lite (Fastest for 2026 Free Tier)
    model_name = "gemini-3.1-flash-lite-preview" 

    response = client.models.generate_content(
        model=model_name,
        contents=[
            types.Part.from_uri(
                file_uri=uploaded_file.uri,
                mime_type=uploaded_file.mime_type
            ),
            "Analyze this audio for Bolta Bazaar inventory and return only JSON."
        ],
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            # 'thinking_level' removed to fix validation error
            response_mime_type="application/json",
        )
    )
    
    # 4. Clean up: Delete the file from Google servers after use
    client.files.delete(name=uploaded_file.name)
    
    return response.text
EOF

cat <<'EOF' > bolta-bazaar/backend/services/firestore_service.py
from google.cloud import firestore
import datetime
import os

# Initialize Firestore client
# When running in Cloud Run, it uses the default service account credentials
db = firestore.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT", "bolta-bazaar"))

def get_inventory():
    """Fetch all items from the inventory collection."""
    inventory_ref = db.collection("inventory")
    docs = inventory_ref.stream()
    
    inventory = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        inventory.append(data)
    
    # If empty, return initial mock data for first-time use
    if not inventory:
        return []
        
    return inventory

def update_inventory_item(item_name, action, qty):
    """
    Update or create an inventory item based on action ('add' or 'sale').
    Standardizes name search to be case-insensitive.
    """
    inventory_ref = db.collection("inventory")
    
    # Try to find existing item (case-insensitive search is tricky in Firestore, 
    # we'll fetch and match or use standardized names)
    search_name = item_name.strip().lower()
    
    # Fetch all items to do a fuzzy match (similar to frontend logic)
    docs = inventory_ref.stream()
    target_doc = None
    
    for doc in docs:
        data = doc.to_dict()
        existing_name = data.get("name", "").lower()
        if existing_name == search_name or search_name in existing_name or existing_name in search_name:
            target_doc = doc
            break
            
    now = datetime.datetime.now().isoformat()
    
    if target_doc:
        doc_ref = inventory_ref.document(target_doc.id)
        current_data = target_doc.to_dict()
        current_stock = current_data.get("stock", 0)
        
        if action == "add":
            new_stock = current_stock + qty
        else: # sale or update
            new_stock = max(0, current_stock - qty)
            
        doc_ref.update({
            "stock": new_stock,
            "lastUpdated": now
        })
        return {"id": target_doc.id, "name": current_data["name"], "stock": new_stock, "lastUpdated": now}
    else:
        # Create new item
        new_item = {
            "name": item_name.capitalize(),
            "stock": qty if action == "add" else 0,
            "lastUpdated": now
        }
        # Use name as ID or auto-gen
        doc_ref = inventory_ref.add(new_item)
        new_item["id"] = doc_ref[1].id
        return new_item

EOF

cat <<'EOF' > bolta-bazaar/frontend/package.json
{
  "name": "frontend",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "lint": "eslint .",
    "preview": "vite preview"
  },
  "dependencies": {
    "@tailwindcss/vite": "^4.2.2",
    "react": "^19.2.4",
    "react-dom": "^19.2.4"
  },
  "devDependencies": {
    "@eslint/js": "^9.39.4",
    "@types/react": "^19.2.14",
    "@types/react-dom": "^19.2.3",
    "@vitejs/plugin-react": "^6.0.1",
    "eslint": "^9.39.4",
    "eslint-plugin-react-hooks": "^7.0.1",
    "eslint-plugin-react-refresh": "^0.5.2",
    "globals": "^17.4.0",
    "tailwindcss": "^4.2.2",
    "vite": "^8.0.4"
  }
}

EOF

cat <<'EOF' > bolta-bazaar/frontend/vite.config.js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
})
EOF

cat <<'EOF' > bolta-bazaar/frontend/index.html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>frontend</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>

EOF

cat <<'EOF' > bolta-bazaar/frontend/Dockerfile
# Stage 1: Build the React application
FROM node:20-alpine AS build

WORKDIR /app

# Copy package files and install dependencies
COPY package*.json ./
RUN npm install

# Copy source code and build
COPY . .
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# Stage 2: Serve the application with Nginx
FROM nginx:stable-alpine

# Copy build output to Nginx html directory
COPY --from=build /app/dist /usr/share/nginx/html

# Copy custom nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port 8080 (Cloud Run default)
EXPOSE 8080

# Command to run Nginx
CMD ["nginx", "-g", "daemon off;"]

EOF

cat <<'EOF' > bolta-bazaar/frontend/nginx.conf
server {
    listen 8080;
    server_name localhost;

    location / {
        root /usr/share/nginx/html;
        index index.html index.htm;
        try_files $uri $uri/ /index.html;
    }

    # Optional: Health check endpoint
    location /healthz {
        access_log off;
        return 200 "OK";
    }

    # Error pages
    error_page 500 502 503 504 /50x.html;
    location = /50x.html {
        root /usr/share/nginx/html;
    }
}

EOF

cat <<'EOF' > bolta-bazaar/frontend/src/App.jsx
import React, { useState, useEffect } from 'react';
import VoiceRecorder from './components/VoiceRecorder';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

function App() {
  const [lang, setLang] = useState('en');
  const [liveTranscript, setLiveTranscript] = useState('');
  const [inventory, setInventory] = useState([]);
  const [transactionLog, setTransactionLog] = useState([]);
  const [isLoading, setIsLoading] = useState(true);

  const formatDate = (dateString) => {
      const date = dateString ? new Date(dateString) : new Date();
      return date.toLocaleDateString('en-US', { day: 'numeric', month: 'short' }) + ', ' + 
             date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  };

  // Fetch Inventory from Firestore via Backend
  useEffect(() => {
    const fetchInventory = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/inventory`);
        const data = await response.json();
        if (Array.isArray(data)) {
            // Sort by lastUpdated descending
            const sorted = data.sort((a, b) => new Date(b.lastUpdated) - new Date(a.lastUpdated));
            setInventory(sorted);
        }
      } catch (error) {
        console.error('Error fetching inventory:', error);
      } finally {
        setIsLoading(false);
      }
    };

    fetchInventory();
  }, []);

  // Translations
  const t = {
    title: { en: 'Bolta Bazaar', ur: 'بولتا بازار' },
    status: { en: 'Gemini 3.1 Pro: Connected', ur: 'جیمنی ٣.١ پرو: منسلک ہے' },
    statsTitle1: { en: "Recent Activity", ur: "حالیہ سرگرمی" },
    statsTitle2: { en: "Top Selling Item", ur: "سب سے زیادہ بکنے والی چیز" },
    statsTitle3: { en: "Inventory Alerts", ur: "اسٹاک الرٹس" },
    topItem: { en: "Aata", ur: "آٹا" },
    voiceEntry: { en: "Voice Command Entry", ur: "آواز کے ذریعے داخل کریں" },
    liveTranscription: { en: "Live AI Transcription", ur: "لائیو ٹرانسکرپشن" },
    inventoryTable: { en: "Real-time Stock Ledger", ur: "اسٹاک کی صورتحال" },
    colItem: { en: "Item Name", ur: "آئٹم کا نام" },
    colStock: { en: "Current Stock", ur: "موجودہ اسٹاک" },
    colLastUpdated: { en: "Last Updated", ur: "آخری اپ ڈیٹ" },
    colAction: { en: "Quick Actions", ur: "ایکشن" },
    footer: { en: "Built for Karachi Shopkeepers with Gemini 3.1 AI", ur: "کراچی کے دکانداروں کے لیے جیمنی 3.1 AI کے ساتھ بنایا گیا" },
    itemsLow: { en: "low stock", ur: "کم اسٹاک" },
    waitingVoice: { en: "Waiting for voice input...", ur: "آواز کے ان پٹ کا انتظار ہے..." },
    units: { en: "Units", ur: "یونٹس" },
    noActivity: { en: "No recent transactions", ur: "کوئی حالیہ سرگرمی نہیں" },
    listening: { en: "Listening...", ur: "سن رہا ہے..." },
    allGood: { en: "All Good", ur: "سب ٹھیک ہے" },
    outOfStock: { en: "Out of Stock", ur: "اسٹاک ختم" },
    recording: { en: "Recording... Tap to stop", ur: "ریکارڈنگ جاری ہے... روکنے کے لیے دبائیں" },
    tapToRecord: { en: "Tap to record inventory", ur: "اسٹاک ریکارڈ کرنے کے لیے دبائیں" },
    processingVoice: { en: "Processing Voice...", ur: "آواز پر کارروائی ہو رہی ہے..." },
    sendingToAI: { en: "Sending to Gemini AI...", ur: "جیمنی AI کو بھیجا جا رہا ہے..." },
    processingComplete: { en: "Processing complete.", ur: "پروسیسنگ مکمل ہو گئی۔" },
    errorProcessing: { en: "Error processing audio.", ur: "آڈیو پروسیسنگ میں خرابی۔" },
    emptyInventory: { en: "No items added yet. Press mic to start!", ur: "ابھی تک کوئی مال نہیں ڈالا گیا۔ مائیک دبا کر شروع کریں!" }
  };

  const getText = (key) => t[key][lang] || t[key]['en'];
  
  const getTranslatedName = (name) => {
    const dict = {
        'Aata': { en: 'Flour', ur: 'آٹا' },
        'Rice': { en: 'Rice', ur: 'چاول' },
        'Sugar': { en: 'Sugar', ur: 'چینی' },
        'Oil': { en: 'Oil', ur: 'تیل' }
    };
    return dict[name] ? dict[name][lang] : name;
  };

  const handleVoiceResult = (data) => {
    if (data.updated_inventory_item) {
        const item = data.updated_inventory_item;
        
        // Log transaction
        const action = data.action === 'add' ? 'Added' : 'Sold';
        const logMsg = `${action} ${data.qty} ${item.name}`;
        setTransactionLog(prev => [logMsg, ...prev]);
        
        // Update local state
        setInventory(prev => {
            const index = prev.findIndex(i => i.id === item.id);
            if (index >= 0) {
                const newInv = [...prev];
                newInv[index] = item;
                return newInv;
            } else {
                return [item, ...prev];
            }
        });
    }
  };

  const handleManualAdjustment = async (item, delta) => {
      try {
          const response = await fetch(`${API_BASE_URL}/api/inventory/adjust`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ name: item.name, delta })
          });
          const updatedItem = await response.json();
          
          if (updatedItem.id) {
              const actionStr = delta > 0 ? `Manually Added ${Math.abs(delta)}` : `Manually Removed ${Math.abs(delta)}`;
              setTransactionLog(logs => [`${actionStr} ${item.name}`, ...logs]);
              
              setInventory(prev => prev.map(i => i.id === updatedItem.id ? updatedItem : i));
          }
      } catch (error) {
          console.error('Error adjusting inventory:', error);
      }
  };

  const handleTranscriptUpdate = (text) => {
      setLiveTranscript(text);
  };

  const lowStockItems = inventory.filter(i => i.stock < 5);
  const lowStockNames = lowStockItems.map(i => getTranslatedName(i.name)).join(', ');

  return (
    <div className={`min-h-screen flex flex-col bg-gradient-to-br from-[#f0f4f8] to-[#e1eaf2] ${lang === 'ur' ? 'font-urdu' : ''}`}>
      {/* Header */}
      <header className="glass shadow-sm px-6 py-4 flex justify-between items-center sticky top-0 z-50">
        <div className="flex items-center gap-3">
            <div className="bg-telenor-blue text-white p-2 rounded-lg shadow-inner">
                <span className="text-2xl">🛒</span>
            </div>
            <div>
                <h1 className="text-2xl font-bold text-gray-900 tracking-tight">{getText('title')}</h1>
                <p className="text-xs text-telenor-blue font-semibold uppercase tracking-wider">AI Powered</p>
            </div>
        </div>
        <div className="flex items-center gap-4 md:gap-6">
            <div className="hidden md:flex items-center gap-2 px-4 py-2 bg-white/80 border border-green-200 text-green-700 rounded-full text-sm font-medium shadow-sm">
                <div className="w-2.5 h-2.5 rounded-full bg-green-500 animate-pulse shadow-[0_0_8px_rgba(34,197,94,0.6)]"></div>
                {getText('status')}
            </div>
            {/* Language Toggle */}
            <button 
                onClick={() => setLang(lang === 'en' ? 'ur' : 'en')}
                className="px-5 py-2 bg-white hover:bg-gray-50 text-telenor-blue border border-gray-200 rounded-lg font-semibold transition-all shadow-sm active:scale-95"
            >
                {lang === 'en' ? 'اردو' : 'English'}
            </button>
        </div>
      </header>

      <main className="flex-grow p-4 md:p-8 max-w-[1400px] mx-auto w-full flex flex-col gap-8">
        
        {/* Stats Overview */}
        <section className={`grid grid-cols-1 md:grid-cols-3 gap-6 ${lang === 'ur' ? 'text-right' : ''}`}>
            {/* Transaction Log Stat */}
            <div className="bg-white p-6 rounded-2xl shadow-sm border border-gray-100/80 flex flex-col hover:shadow-md transition-all relative overflow-hidden group">
                <div className="absolute top-0 right-0 w-24 h-24 bg-telenor-blue/5 rounded-full -mr-10 -mt-10 transition-transform group-hover:scale-110"></div>
                <h3 className="text-sm font-semibold text-gray-500 mb-2 uppercase tracking-wide">{getText('statsTitle1')}</h3>
                {transactionLog.length > 0 ? (
                    <div className="flex flex-col gap-1">
                        <span className="text-lg font-bold text-gray-900 line-clamp-1">{transactionLog[0]}</span>
                        <span className="text-sm text-gray-400 font-medium">
                           {transactionLog.length} total actions this session
                        </span>
                    </div>
                ) : (
                    <span className="text-lg font-medium text-gray-400 italic mt-1">{getText('noActivity')}</span>
                )}
            </div>

            {/* Top Item Stat */}
            <div className="bg-white p-6 rounded-2xl shadow-sm border border-gray-100/80 flex flex-col hover:shadow-md transition-all relative overflow-hidden group">
                <div className="absolute top-0 right-0 w-24 h-24 bg-green-500/5 rounded-full -mr-10 -mt-10 transition-transform group-hover:scale-110"></div>
                <h3 className="text-sm font-semibold text-gray-500 mb-2 uppercase tracking-wide">{getText('statsTitle2')}</h3>
                <span className="text-3xl font-extrabold text-telenor-blue">{getText('topItem')}</span>
            </div>

            {/* Alerts Stat */}
            <div className={`bg-white p-6 rounded-2xl shadow-sm border-l-4 flex flex-col transition-all relative overflow-hidden ${lowStockItems.length > 0 ? 'border-l-telenor-red' : 'border-l-green-500'}`}>
                <h3 className={`text-sm font-semibold mb-2 uppercase tracking-wide ${lowStockItems.length > 0 ? 'text-telenor-red' : 'text-green-600'}`}>
                    {getText('statsTitle3')}
                </h3>
                <div className={`flex flex-col ${lang === 'ur' ? 'items-end' : 'items-start'}`}>
                    {lowStockItems.length > 0 ? (
                        <>
                            <div className="flex items-baseline gap-2">
                                <span className="text-3xl font-extrabold text-telenor-red">{lowStockItems.length}</span>
                                <span className="text-sm text-telenor-red font-medium">{getText('itemsLow')}</span>
                            </div>
                            <span className="text-sm text-gray-600 mt-1 line-clamp-1 font-medium bg-red-50 px-2 py-1 rounded w-full">
                                {lowStockNames}
                            </span>
                        </>
                    ) : (
                        <span className="text-2xl font-bold text-green-600 mt-1">{getText('allGood')}</span>
                    )}
                </div>
            </div>
        </section>

        {/* Command Center */}
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-6 h-auto lg:h-[420px]">
            {/* Voice Entry Card */}
            <div className="bg-white rounded-2xl shadow-lg border border-gray-100 flex flex-col overflow-hidden">
                <div className="p-5 bg-gradient-to-r from-telenor-blue to-blue-600 border-b border-blue-700">
                    <h2 className={`text-lg font-bold text-white tracking-wide ${lang === 'ur' ? 'text-right' : ''}`}>
                        {getText('voiceEntry')}
                    </h2>
                </div>
                <div className="flex-grow flex items-center justify-center p-6 bg-gray-50/50 relative">
                    <div className="absolute inset-0 bg-[radial-gradient(#e5e7eb_1px,transparent_1px)] [background-size:20px_20px] opacity-30"></div>
                    <div className="relative z-10 w-full">
                        <VoiceRecorder onResult={handleVoiceResult} onTranscriptUpdate={handleTranscriptUpdate} lang={lang} getText={getText} />
                    </div>
                </div>
            </div>

            {/* Live Transcription Card */}
            <div className="bg-gray-900 rounded-2xl shadow-lg flex flex-col overflow-hidden border border-gray-800 relative">
                <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-telenor-red via-orange-500 to-telenor-blue"></div>
                <div className="p-5 border-b border-gray-800 bg-black/40 flex justify-between items-center backdrop-blur-md">
                    <h2 className="text-lg font-bold text-gray-100 tracking-wide">{getText('liveTranscription')}</h2>
                    <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-400 font-mono uppercase tracking-widest">Listening</span>
                        <div className="w-2.5 h-2.5 rounded-full bg-telenor-red animate-pulse shadow-[0_0_10px_rgba(228,0,43,0.9)]"></div>
                    </div>
                </div>
                <div className="p-8 flex-grow flex flex-col justify-end bg-gradient-to-b from-gray-900 to-black relative">
                    {/* Decorative quotes */}
                    <span className="absolute top-8 left-8 text-6xl text-gray-800 font-serif opacity-50">"</span>
                    <p className={`text-3xl font-light leading-relaxed w-full tracking-wide relative z-10 ${lang === 'ur' ? 'text-right' : 'text-left'} ${liveTranscript && liveTranscript !== getText('listening') ? 'text-white drop-shadow-md' : 'text-gray-600 italic'}`}>
                        {liveTranscript || getText('waitingVoice')}
                    </p>
                </div>
            </div>
        </section>

        {/* Inventory Table */}
        <section className="bg-white rounded-2xl shadow-lg border border-gray-100 overflow-hidden">
            <div className="p-6 border-b border-gray-100 flex justify-between items-center bg-white">
                <h2 className="text-xl font-bold text-gray-900 tracking-tight">{getText('inventoryTable')}</h2>
            </div>
            <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse" dir={lang === 'ur' ? 'rtl' : 'ltr'}>
                    <thead>
                        <tr className="bg-gray-50/80 border-b border-gray-200 text-xs text-gray-500 uppercase tracking-widest">
                            <th className="px-6 py-4 font-bold">{getText('colItem')}</th>
                            <th className="px-6 py-4 font-bold">{getText('colStock')}</th>
                            <th className="px-6 py-4 font-bold">{getText('colLastUpdated')}</th>
                            <th className="px-6 py-4 font-bold text-center">{getText('colAction')}</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                        {isLoading ? (
                             <tr><td colSpan="4" className="px-6 py-12 text-center text-gray-400">Loading inventory...</td></tr>
                        ) : inventory.length > 0 ? inventory.map((item) => (
                            <tr key={item.id} className="hover:bg-blue-50/40 transition-colors group">
                                <td className="px-6 py-5 whitespace-nowrap">
                                    <div className="flex items-center gap-3">
                                        <div className={`w-2 h-2 rounded-full ${item.stock === 0 ? 'bg-telenor-red' : item.stock < 5 ? 'bg-orange-500' : 'bg-green-500'}`}></div>
                                        <span className="font-semibold text-gray-900 text-base">{getTranslatedName(item.name)}</span>
                                    </div>
                                </td>
                                <td className="px-6 py-5 whitespace-nowrap">
                                    <span className={`inline-flex items-center px-3.5 py-1.5 rounded-lg text-sm font-bold shadow-sm ${
                                        item.stock === 0 ? 'bg-red-50 text-telenor-red border border-red-100 animate-pulse' : 
                                        item.stock <= 5 ? 'bg-orange-50 text-orange-700 border border-orange-100 animate-bounce' : 
                                        'bg-blue-50 text-telenor-blue border border-blue-100'
                                    }`}>
                                        {item.stock} {getText('units')}
                                    </span>
                                    {item.stock === 0 && <span className="ml-2 text-xs font-bold text-telenor-red tracking-wide uppercase bg-red-100 px-2 py-0.5 rounded">{getText('outOfStock')}</span>}
                                </td>
                                <td className="px-6 py-5 whitespace-nowrap text-sm font-medium text-gray-500">
                                    {formatDate(item.lastUpdated)}
                                </td>
                                <td className="px-6 py-5 whitespace-nowrap">
                                    <div className="flex items-center justify-center gap-2 opacity-80 group-hover:opacity-100 transition-opacity">
                                        <button 
                                            onClick={() => handleManualAdjustment(item, -1)}
                                            className="w-8 h-8 rounded-full bg-gray-100 hover:bg-telenor-red hover:text-white text-gray-600 flex items-center justify-center transition-all shadow-sm font-bold active:scale-95"
                                            title="Decrease Stock"
                                        >
                                            -
                                        </button>
                                        <button 
                                            onClick={() => handleManualAdjustment(item, 1)}
                                            className="w-8 h-8 rounded-full bg-gray-100 hover:bg-telenor-blue hover:text-white text-gray-600 flex items-center justify-center transition-all shadow-sm font-bold active:scale-95"
                                            title="Increase Stock"
                                        >
                                            +
                                        </button>
                                    </div>
                                </td>
                            </tr>
                        )) : (
                            <tr>
                                <td colSpan="4" className="px-6 py-12 text-center">
                                    <div className="flex flex-col items-center gap-4">
                                        <span className="text-5xl opacity-20">📦</span>
                                        <p className="text-xl font-medium text-gray-400 max-w-xs mx-auto">
                                            {getText('emptyInventory')}
                                        </p>
                                    </div>
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        </section>

      </main>

      {/* Footer */}
      <footer className="bg-white/80 backdrop-blur-sm border-t border-gray-200 mt-auto py-6">
        <div className="max-w-7xl mx-auto px-4 md:px-8 text-center">
            <p className="text-gray-500 text-sm font-medium tracking-wide flex items-center justify-center gap-2">
                {getText('footer')} 
                <span className="w-1.5 h-1.5 rounded-full bg-telenor-red inline-block"></span>
            </p>
        </div>
      </footer>
    </div>
  )
}

export default App;

EOF

cat <<'EOF' > bolta-bazaar/frontend/src/components/VoiceRecorder.jsx
import React, { useState, useRef, useEffect } from 'react';

const VoiceRecorder = ({ onResult, onTranscriptUpdate, lang, getText }) => {
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const recognitionRef = useRef(null);

  useEffect(() => {
    // Set up SpeechRecognition if available to provide real-time transcription
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!recognitionRef.current) {
        recognitionRef.current = new SpeechRecognition();
        recognitionRef.current.continuous = true;
        recognitionRef.current.interimResults = true;
        recognitionRef.current.lang = 'ur-PK'; // Set to Urdu (Pakistan)
        
        recognitionRef.current.onresult = (event) => {
          let interimTranscript = '';
          let finalTranscript = '';
          for (let i = event.resultIndex; i < event.results.length; ++i) {
            if (event.results[i].isFinal) {
              finalTranscript += event.results[i][0].transcript;
            } else {
              interimTranscript += event.results[i][0].transcript;
            }
          }
          if (onTranscriptUpdate) {
              onTranscriptUpdate(finalTranscript || interimTranscript);
          }
        };
      }
    }
  }, [onTranscriptUpdate]);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          audioChunksRef.current.push(e.data);
        }
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        await processAudio(audioBlob);
      };

      mediaRecorder.start();
      
      // Start real-time speech recognition
      if (recognitionRef.current) {
          try {
              recognitionRef.current.start();
          } catch(e) {}
      }
      
      setIsRecording(true);
      if (onTranscriptUpdate) onTranscriptUpdate(getText('listening'));
    } catch (err) {
      console.error('Error accessing microphone:', err);
      alert('Could not access microphone.');
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current.stream.getTracks().forEach(track => track.stop());
    }
    
    // Stop real-time speech recognition
    if (recognitionRef.current) {
        recognitionRef.current.stop();
    }
    
    setIsRecording(false);
  };

  const playSuccessSound = () => {
    const context = new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = context.createOscillator();
    const gainNode = context.createGain();

    oscillator.type = 'sine';
    oscillator.frequency.setValueAtTime(880, context.currentTime); // A5 note
    gainNode.gain.setValueAtTime(0.1, context.currentTime);
    gainNode.gain.exponentialRampToValueAtTime(0.01, context.currentTime + 0.2);

    oscillator.connect(gainNode);
    gainNode.connect(context.destination);

    oscillator.start();
    oscillator.stop(context.currentTime + 0.2);
  };

  const processAudio = async (audioBlob) => {
    setIsProcessing(true);
    if (onTranscriptUpdate) onTranscriptUpdate(getText('sendingToAI'));
    const formData = new FormData();
    formData.append('audio', audioBlob, 'recording.webm');

    try {
      const apiBaseUrl = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
      const response = await fetch(`${apiBaseUrl}/api/process-voice`, {
        method: 'POST',
        body: formData,
      });
      const data = await response.json();
      
      if (!data.error) {
        playSuccessSound();
      }

      if (onResult) {
        onResult(data);
      }
      if (onTranscriptUpdate) onTranscriptUpdate(JSON.stringify(data));
    } catch (error) {
      console.error('Error processing audio:', error);
      alert('Error processing audio. Make sure the backend is running.');
      if (onTranscriptUpdate) onTranscriptUpdate(getText('errorProcessing'));
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="flex flex-col items-center justify-center h-full w-full py-4">
      <button
        onClick={isRecording ? stopRecording : startRecording}
        disabled={isProcessing}
        className={`w-36 h-36 rounded-full flex items-center justify-center text-white transition-all shadow-xl border-4 border-transparent
          ${isProcessing ? 'bg-gray-400 cursor-not-allowed' : 
            isRecording ? 'bg-telenor-blue animate-pulse shadow-[0_0_20px_rgba(0,102,204,0.6)] scale-105 border-blue-300' : 'bg-telenor-blue hover:scale-105 hover:shadow-blue-500/30'}`}
      >
        <span className="text-6xl">
          {isRecording ? '⏹' : '🎤'}
        </span>
      </button>

      <div className="mt-8 text-gray-600 font-semibold h-6 text-center text-lg tracking-wide">
        {isRecording && <p className="animate-pulse text-telenor-blue">{getText('recording')}</p>}
        {!isRecording && !isProcessing && <p>{getText('tapToRecord')}</p>}
      </div>

      {isProcessing && (
        <div className="w-full max-w-sm mt-8">
          <p className="text-center text-sm font-bold text-telenor-red mb-3 tracking-widest uppercase animate-pulse">{getText('processingVoice')}</p>
          <div className="h-2.5 w-full bg-red-100 rounded-full overflow-hidden relative shadow-inner">
            <div className="h-full bg-telenor-red w-full absolute animate-progress rounded-full"></div>
          </div>
        </div>
      )}
    </div>
  );
};

export default VoiceRecorder;

EOF


echo "Files created successfully."

# Enable APIs
gcloud services enable artifactregistry.googleapis.com cloudbuild.googleapis.com run.googleapis.com

# Deploy Backend
cd bolta-bazaar/backend
gcloud builds submit --tag gcr.io/bolta-bazaar/backend .
gcloud run deploy bolta-bazaar-backend --image gcr.io/bolta-bazaar/backend --region asia-south1 --set-secrets="GOOGLE_API_KEY=GOOGLE_API_KEY:latest" --allow-unauthenticated

# Get Backend URL
BACKEND_URL=$(gcloud run services describe bolta-bazaar-backend --region asia-south1 --format 'value(status.url)')

# Build and Deploy Frontend
cd ../frontend
gcloud builds submit --tag gcr.io/bolta-bazaar/frontend --build-arg VITE_API_URL=$BACKEND_URL .
gcloud run deploy bolta-bazaar-frontend --image gcr.io/bolta-bazaar/frontend --region asia-south1 --allow-unauthenticated

echo "Deployment complete!"
