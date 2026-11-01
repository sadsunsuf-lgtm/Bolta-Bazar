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
try:
    if "GOOGLE_API_KEY" in st.secrets:
        os.environ["GOOGLE_API_KEY"] = st.secrets["GOOGLE_API_KEY"]
except Exception:
    pass

from services.voice_processor import process_audio, process_text_command
from services.firestore_service import get_inventory, update_inventory_item, is_firestore_connected

# Streamlit Page Config with Telenor 4G Theme
st.set_page_config(
    page_title="Bolta Bazaar - بولتا بازار",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Telenor 4G CSS (Telenor Blue #007AC9, White, Red #E30613 + Google Material Design)
st.markdown("""
<style>
    :root {
        --telenor-blue: #007AC9;
        --telenor-dark-blue: #005086;
        --telenor-red: #E30613;
        --telenor-bg: #F4F7F9;
    }
    .main {
        background-color: var(--telenor-bg);
    }
    .header-card {
        background: linear-gradient(135deg, #007AC9 0%, #005086 100%);
        color: white;
        padding: 22px 20px;
        border-radius: 14px;
        box-shadow: 0 4px 14px rgba(0, 122, 201, 0.25);
        margin-bottom: 20px;
        text-align: center;
    }
    .urdu-banner {
        font-size: 30px;
        font-weight: 700;
        direction: rtl;
        margin-bottom: 4px;
        letter-spacing: 0.5px;
    }
    .sub-banner {
        font-size: 15px;
        opacity: 0.95;
        font-weight: 400;
    }
    .status-banner {
        background: white;
        border-left: 6px solid #007AC9;
        border-radius: 10px;
        padding: 16px 20px;
        margin-bottom: 18px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.06);
    }
    .badge-sale {
        background-color: #E30613;
        color: white;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 600;
        display: inline-block;
    }
    .badge-stock {
        background-color: #007AC9;
        color: white;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 600;
        display: inline-block;
        margin-right: 6px;
    }
    .stock-row {
        background: white;
        padding: 12px 16px;
        border-radius: 8px;
        border-left: 4px solid #007AC9;
        margin-bottom: 8px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.04);
    }
</style>
""", unsafe_allow_html=True)

# App Header
st.markdown("""
<div class="header-card">
    <div class="urdu-banner">🛒 بولتا بازار - آواز سے دکان سنبھالیں</div>
    <div class="sub-banner">Bolta Bazaar AI — Voice-Driven Smart Inventory for Pakistani Dukandars</div>
</div>
""", unsafe_allow_html=True)

# Display persistent notification banner if an action was executed
if "alert_info" in st.session_state and st.session_state["alert_info"]:
    alert = st.session_state["alert_info"]
    st.markdown(f"""
    <div class="status-banner">
        <div style="font-size: 20px; font-weight: bold; color: #007AC9; direction: rtl; margin-bottom: 4px;">
            {alert.get('msg_ur', '')}
        </div>
        <div style="font-size: 14px; color: #333;">
            <b>Action Summary:</b> {alert.get('msg_en', '')}
        </div>
    </div>
    """, unsafe_allow_html=True)
    # Clear alert after rendering once so next page interaction starts fresh
    st.session_state["alert_info"] = None

# Sidebar with status & quick tips
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/c/cf/Telenor_Logo.svg/512px-Telenor_Logo.svg.png", width=110)
    
    st.subheader("📡 سسٹم اسٹیٹس (System Status)")
    gemini_ready = bool(os.getenv("GOOGLE_API_KEY"))
    if gemini_ready:
        st.success("✅ Gemini AI Connected")
    else:
        st.error("❌ GOOGLE_API_KEY Missing")
        st.caption("Please add `GOOGLE_API_KEY` in Streamlit Cloud Secrets.")

    firestore_ready = is_firestore_connected()
    if firestore_ready:
        st.success("✅ Cloud Firestore Live")
    else:
        st.info("💾 Local JSON Storage Active")
        with st.expander("ℹ️ Connect Live Firestore"):
            st.markdown("""
            To connect live Google Cloud Firestore on Streamlit Cloud:
            1. Open Streamlit App Settings -> **Secrets**.
            2. Add your Firebase service account credentials under `[firebase]`:
            ```toml
            [firebase]
            type = "service_account"
            project_id = "your-gcp-project-id"
            private_key = "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
            client_email = "...@...iam.gserviceaccount.com"
            ```
            """)

    st.divider()
    st.subheader("💡 بولنے کے طریقے (Voice Examples)")
    st.info("🔹 '5 kilo aata shamil karo' (Add 5kg Flour)")
    st.info("🔹 '2 packets cheeni bechi' (Sold 2 packets Sugar)")
    st.info("🔹 '10 chawal add karo' (Add 10 Rice)")
    st.info("🔹 '3 oil bottle sale' (Sold 3 Oil)")
    st.info("🔹 'Chai patti 5 packet aayi hai' (Stock 5 Tea)")

# Main Layout
col_voice, col_inventory = st.columns([1, 1], gap="large")

with col_voice:
    st.subheader("🎤 بول کر اسٹاک اپڈیٹ کریں (Voice Command)")
    
    # Modern Streamlit microphone input
    audio_file = st.audio_input("مائیک پر کلک کریں اور اردو یا انگلش میں بولیں:")
    
    # Text input – preserve across reruns using session_state
    if "text_cmd" not in st.session_state:
        st.session_state["text_cmd"] = ""
    text_cmd = st.text_input(
        "یا یہاں لکھیں (Or type Roman Urdu / English):",
        placeholder="مثال: 5 kilo aata becha",
        key="text_cmd"
    )
    
    process_btn = st.button("🚀 پروسیس کریں (Update Stock)", use_container_width=True, type="primary")

    if process_btn:
        if audio_file:
            with st.spinner("آواز کی شناخت ہو رہی ہے... (AI processing audio)"):
                temp_path = None
                try:
                    # Seek to start before reading (critical for BytesIO from st.audio_input)
                    if hasattr(audio_file, 'seek'):
                        audio_file.seek(0)
                    audio_bytes = audio_file.read()
                    if not audio_bytes:
                        raise ValueError("آڈیو ریکارڈنگ خالی ہے۔ براہ کرم دوبارہ ریکارڈ کریں۔")

                    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                        tmp.write(audio_bytes)
                        temp_path = tmp.name

                    # Pass explicit WAV mime-type to Gemini
                    raw_result = process_audio(temp_path, mime_type="audio/wav")

                    json_match = re.search(r'\{.*\}', raw_result, re.DOTALL)
                    if json_match:
                        data = json.loads(json_match.group(0))
                        item = data.get("item", "Item").capitalize()
                        action = data.get("action", "add")
                        qty = int(data.get("qty", 1))
                        msg_en = data.get("msg_en", f"{action.capitalize()} {qty}x {item}")
                        msg_ur = data.get("msg_ur", "✅ اسٹاک کامیابی سے اپڈیٹ ہو گیا۔")

                        update_inventory_item(item, action, qty)
                        st.session_state["alert_info"] = {"msg_ur": msg_ur, "msg_en": msg_en}
                        st.rerun()
                    else:
                        st.error(f"⚠️ آواز سمجھ نہیں آئی۔ AI returned: {raw_result[:200]}")
                except Exception as e:
                    st.error(f"❌ Voice Error: {e}")
                finally:
                    if temp_path and os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except Exception:
                            pass

        elif text_cmd.strip():
            with st.spinner("پروسیسنگ... (Processing text command)"):
                _cmd = text_cmd.strip()
                gemini_ok = False
                try:
                    raw_result = process_text_command(_cmd)
                    json_match = re.search(r'\{.*\}', raw_result, re.DOTALL)
                    if json_match:
                        data = json.loads(json_match.group(0))
                        item = data.get("item", "Item").capitalize()
                        action = data.get("action", "add")
                        qty = int(data.get("qty", 1))
                        msg_en = data.get("msg_en", f"{action.capitalize()} {qty}x {item}")
                        msg_ur = data.get("msg_ur", "✅ اسٹاک کامیابی سے اپڈیٹ ہو گیا۔")
                        update_inventory_item(item, action, qty)
                        st.session_state["alert_info"] = {"msg_ur": msg_ur, "msg_en": msg_en}
                        gemini_ok = True
                        st.rerun()
                    else:
                        st.warning(f"Gemini returned unexpected format. Using rule-based fallback.")
                except Exception as e:
                    st.warning(f"Gemini unavailable ({e}). Using rule-based fallback.")

                if not gemini_ok:
                    # Rule-based fallback
                    action = "sale" if any(w in _cmd.lower() for w in ["bech", "sale", "nikal", "sold", "minus"]) else "add"
                    qty_match = re.search(r'\d+', _cmd)
                    qty = int(qty_match.group(0)) if qty_match else 1
                    item = "General Item"
                    for candidate in [("Flour", ["flour", "aata", "atta", "wheat"]),
                                      ("Sugar", ["sugar", "cheeni", "chini"]),
                                      ("Rice", ["rice", "chawal"]),
                                      ("Tea", ["chai", "patti", "tea"]),
                                      ("Cooking Oil", ["oil", "tel", "ghee"])]:
                        if any(w in _cmd.lower() for w in candidate[1]):
                            item = candidate[0]
                            break
                    update_inventory_item(item, action, qty)
                    st.session_state["alert_info"] = {
                        "msg_ur": f"✅ {item} — {qty} عدد {'شامل' if action == 'add' else 'فروخت'} ہو گئے۔",
                        "msg_en": f"{action.upper()} {qty}x {item} (rule-based)"
                    }
                    st.rerun()
        else:
            st.warning("⚠️ براہ کرم پہلے مائیک سے کچھ بولیں یا ٹیکسٹ باکس میں لکھیں۔")

with col_inventory:
    st.subheader("📦 موجودہ اسٹاک (Current Shop Inventory)")
    
    items = get_inventory()
    
    if items:
        for idx, it in enumerate(items):
            name = it.get("name", "Unknown Item")
            stock = int(it.get("stock", 0))
            sales = int(it.get("sales", 0))
            
            with st.container():
                c1, c2, c3, c4 = st.columns([3, 2, 1, 1])
                c1.markdown(f"**{name}**")
                c2.markdown(f"<span class='badge-stock'>اسٹاک: {stock}</span> <span class='badge-sale'>فروخت: {sales}</span>", unsafe_allow_html=True)
                
                if c3.button("➕", key=f"add_{idx}", help="اسٹاک میں 1 شامل کریں"):
                    update_inventory_item(name, "add", 1)
                    st.rerun()
                if c4.button("➖", key=f"sale_{idx}", help="1 فروخت درج کریں"):
                    update_inventory_item(name, "sale", 1)
                    st.rerun()
                st.divider()
    else:
        st.info("کوئی سامان موجود نہیں ہے۔ (Inventory is empty)")

st.caption("Bolta Bazaar © 2026 — Built with Google Gemini AI & Streamlit")
