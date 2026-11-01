from google import genai
from google.genai import types
import os
import time
from dotenv import load_dotenv

# Load environment variables from current directory, backend/.env, or root .env
load_dotenv()
backend_env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
if os.path.exists(backend_env_path):
    load_dotenv(backend_env_path)
root_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
if os.path.exists(root_env_path):
    load_dotenv(root_env_path)

# Confirmed working models on v1beta
DEFAULT_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')

def get_genai_client():
    api_key = os.getenv('GOOGLE_API_KEY')
    if not api_key:
        try:
            import streamlit as st
            api_key = st.secrets.get("GOOGLE_API_KEY")
        except Exception:
            pass
    if not api_key:
        raise ValueError("GOOGLE_API_KEY is not set. Please set it in Streamlit Secrets or environment variable.")
    return genai.Client(
        api_key=api_key,
        http_options={'api_version': 'v1beta'}
    )

def get_audio_mime_type(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    mime_map = {
        '.wav': 'audio/wav',
        '.webm': 'audio/webm',
        '.mp3': 'audio/mp3',
        '.ogg': 'audio/ogg',
        '.m4a': 'audio/mp4',
        '.aac': 'audio/aac',
        '.flac': 'audio/flac'
    }
    return mime_map.get(ext, 'audio/wav')

SYSTEM_INSTRUCTION = (
    "You are an expert Urdu-speaking shop assistant for 'Bolta Bazaar'. "
    "Extract structured JSON from user audio or text commands.\n"
    "1. Logic: 'add' for stock-in (خریداری / اضافہ / اسٹاک میں شامل), 'sale' for items sold (فروخت / بیچا / نکالا).\n"
    "2. Item Names: Standardize the item name in English for the 'item' field (e.g. Flour, Rice, Sugar, Tea, Cooking Oil).\n"
    "3. Dual Language Support: Provide two distinct display messages:\n"
    "   - 'msg_en': A clear English sentence (e.g., 'Added 50 Flour to stock' or 'Sold 2 Sugar').\n"
    "   - 'msg_ur': A natural Urdu sentence with emoji (e.g., '✅ 50 کلو آٹا اسٹاک میں شامل کر دیا گیا' or '🛒 2 چینی فروخت کر دی گئی').\n"
    "Example Output: "
    "{\"action\": \"add\", \"item\": \"Flour\", \"qty\": 50, \"unit\": \"kg\", \"msg_en\": \"Added 50 Flour to stock\", \"msg_ur\": \"✅ 50 کلو آٹا اسٹاک میں شامل کر دیا گیا\"}"
)

def process_audio(file_path: str, mime_type: str = None) -> str:
    resolved_mime = mime_type or get_audio_mime_type(file_path)
    client = get_genai_client()

    uploaded_file = client.files.upload(
        file=file_path,
        config={'mime_type': resolved_mime}
    )

    # Fast polling for speed
    while uploaded_file.state.name == "PROCESSING":
        time.sleep(0.5) 
        uploaded_file = client.files.get(name=uploaded_file.name)

    if uploaded_file.state.name == "FAILED":
        try:
            client.files.delete(name=uploaded_file.name)
        except Exception:
            pass
        raise Exception("Audio processing failed in Gemini Files API")

    models_to_try = [DEFAULT_MODEL, "gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-flash-lite"]
    response = None
    last_exception = None

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[
                    types.Part.from_uri(
                        file_uri=uploaded_file.uri,
                        mime_type=uploaded_file.mime_type
                    ),
                    "Process this Bolta Bazaar audio command immediately and return structured JSON."
                ],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    temperature=0.1 
                )
            )
            if response and response.text:
                break
        except Exception as e:
            last_exception = e
            continue

    try:
        client.files.delete(name=uploaded_file.name)
    except Exception:
        pass
    
    if not response or not response.text:
        raise Exception(f"All models failed. Last error: {str(last_exception)}")
        
    return response.text

def process_text_command(command_text: str) -> str:
    """Processes Roman Urdu or Urdu text command with Gemini for high accuracy."""
    client = get_genai_client()
    models_to_try = [DEFAULT_MODEL, "gemini-2.5-flash", "gemini-flash-latest"]
    last_exception = None

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=f"User command: {command_text}",
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            if response and response.text:
                return response.text
        except Exception as e:
            last_exception = e
            continue

    raise Exception(f"Text processing failed. Last error: {str(last_exception)}")