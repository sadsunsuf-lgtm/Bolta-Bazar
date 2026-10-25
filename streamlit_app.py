import os
import sys
import tempfile
import json
import re
import datetime
import streamlit as st

# Insert backend directory into sys.path so we can import services cleanly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

# Load GOOGLE_API_KEY from streamlit secrets into environment if available
if "GOOGLE_API_KEY" in st.secrets:
    os.environ["GOOGLE_API_KEY"] = st.secrets["GOOGLE_API_KEY"]

from services.voice_processor import process_audio
from services.firestore_service import get_inventory, update_inventory_item

# Streamlit Page Config with Telenor 4G Theme
st.set_page_config(
    page_title="Bolta Bazaar - بولتا بازار",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Telenor 4G CSS (Blue / White / Red with Google Material Design)
st.markdown("""
<style>
    :root {
        --telenor-blue: #007AC9;
        --telenor-red: #E30613;
        --telenor-bg: #F4F7F9;
    }
    .main {
        background-color: var(--telenor-bg);
    }
    .header-card {
        background: linear-gradient(135deg, #007AC9 0%, #005086 100%);
        color: white;
        padding: 24px;
        border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0, 122, 201, 0.2);
        margin-bottom: 24px;
        text-align: center;
    }
    .urdu-banner {
        font-size: 28px;
        font-weight: bold;
        direction: rtl;
        margin-bottom: 6px;
    }
    .sub-banner {
        font-size: 16px;
        opacity: 0.9;
    }
    .stock-card {
        background: white;
        border-radius: 10px;
        padding: 16px;
        border-left: 5px solid #007AC9;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        margin-bottom: 12px;
    }
    .badge-sale {
        background-color: #E30613;
        color: white;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 12px;
        font-weight: bold;
    }
    .badge-stock {
        background-color: #007AC9;
        color: white;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 12px;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# App Header
st.markdown("""
<div class="header-card">
    <div class="urdu-banner">🛒 بولتا بازار - آواز سے دکان سنبھالیں</div>
    <div class="sub-banner">Bolta Bazaar AI - Voice-Driven Inventory for Pakistani Dukandars</div>
</div>
""", unsafe_allow_html=True)

# Sidebar with status & quick tips
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/c/cf/Telenor_Logo.svg/512px-Telenor_Logo.svg.png", width=120)
    st.subheader("💡 بولنے کے طریقے (Sample Voice Commands)")
    st.info("🔹 '5 kilo aata shamil karo' (Add 5kg Flour)")
    st.info("🔹 '2 packets cheeni bechi' (Sold 2 packets Sugar)")
    st.info("🔹 '10 chawal add karo' (Add 10 Rice)")
    st.info("🔹 '3 oil bottle sale' (Sold 3 Oil)")
    
    st.divider()
    key_status = bool(os.getenv("GOOGLE_API_KEY"))
    if key_status:
        st.success("✅ Gemini AI Connected")
    else:
        st.warning("⚠️ Add GOOGLE_API_KEY in Streamlit Secrets")

# Main Layout
col_voice, col_inventory = st.columns([1, 1], gap="large")

with col_voice:
    st.subheader("🎤 بول کر اسٹاک اپڈیٹ کریں (Voice Command)")
    
    # Audio input from user microphone or file upload
    audio_file = st.audio_input("مائیک پر کلک کریں اور اردو یا انگلش میں بولیں:")
    
    # Fallback text input for quick testing or silent environments
    text_cmd = st.text_input("یا یہاں لکھیں (Or type Roman Urdu):", placeholder="e.g. 5 kilo aata becha")
    
    process_btn = st.button("🚀 پروسیس کریں (Update Stock)", use_container_width=True, type="primary")

    if process_btn:
        if audio_file:
            with st.spinner("آواز کی شناخت ہو رہی ہے... (AI processing audio)"):
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                        tmp.write(audio_file.read())
                        temp_path = tmp.name
                    
                    raw_result = process_audio(temp_path)
                    
                    json_match = re.search(r'\{.*\}', raw_result, re.DOTALL)
                    if json_match:
                        data = json.loads(json_match.group(0))
                        item = data.get("item")
                        action = data.get("action", "add")
                        qty = data.get("qty", 1)
                        msg_en = data.get("msg_en", "Stock updated successfully.")
                        msg_ur = data.get("msg_ur", "✅ اسٹاک کامیابی سے اپڈیٹ ہو گیا۔")
                        
                        # Update database / local store
                        update_inventory_item(item, action, qty)
                        
                        st.success(f"{msg_ur}\n\n*{msg_en}*")
                        st.rerun()
                    else:
                        st.error("آواز سمجھ نہیں آئی، برائے مہربانی دوبارہ بولیں۔")
                except Exception as e:
                    st.error(f"Error processing voice: {e}")
                finally:
                    if 'temp_path' in locals() and os.path.exists(temp_path):
                        os.remove(temp_path)
        elif text_cmd:
            with st.spinner("پروسیسنگ..."):
                try:
                    # Simple rule-based or AI parser for text fallback
                    action = "sale" if any(w in text_cmd.lower() for w in ["bech", "sale", "nikal", "sold"]) else "add"
                    qty_match = re.search(r'\d+', text_cmd)
                    qty = int(qty_match.group(0)) if qty_match else 1
                    
                    item = "Item"
                    for candidate in ["flour", "aata", "atta", "rice", "chawal", "sugar", "cheeni", "oil", "chai", "tea"]:
                        if candidate in text_cmd.lower():
                            item = candidate.capitalize()
                            break
                            
                    update_inventory_item(item, action, qty)
                    st.success(f"✅ {action.upper()} {qty}x {item} updated successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
        else:
            st.warning("براہ کرم پہلے کچھ بولیں یا لکھیں۔ (Please record or enter a command)")

with col_inventory:
    st.subheader("📦 موجودہ اسٹاک (Current Shop Inventory)")
    
    items = get_inventory()
    
    if items:
        for idx, it in enumerate(items):
            name = it.get("name", "Unknown Item")
            stock = it.get("stock", 0)
            sales = it.get("sales", 0)
            
            with st.container():
                c1, c2, c3, c4 = st.columns([3, 2, 1, 1])
                c1.markdown(f"**{name}**")
                c2.markdown(f"<span class='badge-stock'>اسٹاک: {stock}</span> <span class='badge-sale'>فروخت: {sales}</span>", unsafe_allow_html=True)
                
                if c3.button("➕", key=f"add_{idx}"):
                    update_inventory_item(name, "add", 1)
                    st.rerun()
                if c4.button("➖", key=f"sale_{idx}"):
                    update_inventory_item(name, "sale", 1)
                    st.rerun()
                st.divider()
    else:
        st.info("کوئی سامان موجود نہیں ہے۔ (Inventory is empty)")

st.caption("Bolta Bazaar © 2026 - Powered by Google Gemini 1.5 & Streamlit")
