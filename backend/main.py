from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import shutil, os, tempfile, json, re
from services.voice_processor import process_audio
from services.firestore_service import get_inventory, update_inventory_item

app = FastAPI()

# Permissive CORS for browser stability
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def health():
    return {"status": "Online"}

@app.get("/api/health")
async def api_health():
    """Diagnostic endpoint - checks all external service connections."""
    result = {"status": "checking", "gemini": "unknown", "firestore": "unknown"}

    # Test Gemini API
    try:
        from google import genai
        client = genai.Client(
            api_key=os.getenv('GOOGLE_API_KEY'),
            http_options={'api_version': 'v1beta'}
        )
        resp = client.models.generate_content(
            model="gemini-flash-latest",
            contents="Reply with just: ok"
        )
        result["gemini"] = "OK" if resp.text else "empty response"
    except Exception as e:
        result["gemini"] = f"ERROR: {str(e)}"

    # Test Firestore
    try:
        from services.firestore_service import get_inventory
        items = get_inventory()
        result["firestore"] = f"OK - {len(items)} items found"
    except Exception as e:
        result["firestore"] = f"ERROR: {str(e)}"

    result["status"] = "ok" if "ERROR" not in result["gemini"] and "ERROR" not in result["firestore"] else "degraded"
    return result

# Handles both /api/inventory and /api/inventory/ to prevent 404 errors
@app.get("/api/inventory")
@app.get("/api/inventory/")
async def fetch_inventory():
    try:
        items = get_inventory()
        return items if items is not None else []
    except Exception as e:
        print(f"Inventory Fetch Error: {e}")
        return []

@app.post("/api/inventory/adjust")
async def adjust_inventory(data: dict):
    name = data.get("name")
    try:
        delta = int(data.get("delta", 0))
    except (ValueError, TypeError):
        delta = 0
    action = "add" if delta > 0 else "sale"
    return update_inventory_item(name, action, abs(delta))

@app.post("/api/process-voice")
async def process_voice(audio: UploadFile = File(...)):
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
            shutil.copyfileobj(audio.file, tmp)
            temp_path = tmp.name
        
        result = process_audio(temp_path)
        
        # Extracts only the JSON part from AI response to prevent 500 crashes
        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        
        if json_match:
            try:
                data = json.loads(json_match.group(0))
            except json.JSONDecodeError:
                return {"msg_en": "AI formatting error", "updated_inventory_item": None}
        else:
            return {"msg_en": "Could not parse voice command", "updated_inventory_item": None}
        
        if "item" in data:
            updated = update_inventory_item(
                data["item"], 
                data.get("action", "add"), 
                data.get("qty", 1)
            )
            data["updated_inventory_item"] = updated if "error" not in updated else None
            
        return data
    except Exception as e:
        print(f"Voice Processing Error: {str(e)}")
        # Returns 200 with error info so frontend doesn't show "Connection Failed"
        return {"error": str(e), "msg_en": "Voice processing failed. Use manual update."}
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)