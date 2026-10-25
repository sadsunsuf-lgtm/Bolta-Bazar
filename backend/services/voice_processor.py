from google import genai
from google.genai import types
import os
import time
from dotenv import load_dotenv

load_dotenv()

# Use the 'latest' alias for maximum speed
# Primary model - gemini-3.1-flash-lite-preview confirmed available on v1beta
DEFAULT_MODEL = os.getenv('GEMINI_MODEL', 'gemini-3.1-flash-lite-preview')

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

def process_audio(file_path: str) -> str:
    # UPDATED INSTRUCTION: Added msg_en and msg_ur to keep both versions separate
    system_instruction = (
        "You are an expert Urdu-speaking shop assistant for 'Bolta Bazaar'. "
        "Extract structured JSON from audio input.\n"
        "1. Logic: 'add' for stock-in, 'sale' for items sold.\n"
        "2. Item Names: Convert to English for the 'item' field.\n"
        "3. Dual Language Support: Provide two distinct display messages:\n"
        "   - 'msg_en': A clear English sentence (e.g., 'Added 50 Flour to stock').\n"
        "   - 'msg_ur': A natural Urdu sentence (e.g., '✅ 50 کلو آٹا اسٹاک میں شامل کر دیا گیا').\n"
        "Example Output: "
        "{\"action\": \"add\", \"item\": \"flour\", \"qty\": 50, \"unit\": \"kg\", \"msg_en\": \"Added 50 Flour to stock\", \"msg_ur\": \"✅ 50 کلو آٹا اسٹاک میں شامل کر دیا گیا\"}"
    )

    client = get_genai_client()

    uploaded_file = client.files.upload(
        file=file_path,
        config={'mime_type': 'audio/webm'}
    )

    # Fast polling for speed
    while uploaded_file.state.name == "PROCESSING":
        time.sleep(0.5) 
        uploaded_file = client.files.get(name=uploaded_file.name)

    if uploaded_file.state.name == "FAILED":
        client.files.delete(name=uploaded_file.name)
        raise Exception(f"Audio processing failed")

    # NOTE: gemini-1.5-flash is NOT available on v1beta - use v1beta-compatible models only
    models_to_try = [DEFAULT_MODEL, "gemini-2.5-flash", "gemini-flash-latest"]
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
                    "Process this Bolta Bazaar command immediately."
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=0.1 
                )
            )
            if response: break
        except Exception as e:
            last_exception = e
            continue

    client.files.delete(name=uploaded_file.name)
    
    if not response:
        raise Exception(f"All models failed. Last error: {str(last_exception)}")
        
    return response.text