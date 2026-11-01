import datetime
import os
import json

# Initialize Firestore safely
db = None
_firestore_initialized = False

def init_firestore():
    global db, _firestore_initialized
    if _firestore_initialized:
        return db
    _firestore_initialized = True

    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            cred_dict = None
            cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")

            # Check Streamlit secrets
            try:
                import streamlit as st
                if hasattr(st, "secrets"):
                    if "firebase" in st.secrets:
                        cred_dict = dict(st.secrets["firebase"])
                    elif "FIREBASE_CREDENTIALS_JSON" in st.secrets:
                        cred_json = st.secrets["FIREBASE_CREDENTIALS_JSON"]
            except Exception:
                pass

            if cred_dict:
                if "private_key" in cred_dict and isinstance(cred_dict["private_key"], str):
                    cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
                firebase_admin.initialize_app(credentials.Certificate(cred_dict))
                db = firestore.client()
                print("Firebase initialized via Streamlit [firebase] secrets")
            elif cred_path and os.path.exists(cred_path):
                firebase_admin.initialize_app(credentials.Certificate(cred_path))
                db = firestore.client()
                print(f"Firebase initialized with service account file: {cred_path}")
            elif cred_json:
                import json as pyjson
                if isinstance(cred_json, str):
                    cred_dict = pyjson.loads(cred_json)
                else:
                    cred_dict = dict(cred_json)
                if "private_key" in cred_dict and isinstance(cred_dict["private_key"], str):
                    cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
                firebase_admin.initialize_app(credentials.Certificate(cred_dict))
                db = firestore.client()
                print("Firebase initialized with FIREBASE_CREDENTIALS_JSON")
            else:
                try:
                    firebase_admin.initialize_app()
                    db = firestore.client()
                    print("Firebase initialized with Application Default Credentials (ADC)")
                except Exception as adc_err:
                    print(f"[Firestore] ADC not available: {adc_err}")
                    db = None
        else:
            db = firestore.client()
    except Exception as e:
        print(f"[Firestore] Firestore not configured or auth missing: {e}. Using local JSON inventory store.")
        db = None
    return db

# Auto-initialize on import
init_firestore()

def is_firestore_connected() -> bool:
    global db
    if db is None:
        init_firestore()
    return db is not None

# Local fallback store file
LOCAL_INVENTORY_FILE = os.path.join(os.path.dirname(__file__), "local_inventory.json")

def _load_local_inventory():
    if os.path.exists(LOCAL_INVENTORY_FILE):
        try:
            with open(LOCAL_INVENTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # Default sample Pakistani grocery store items
    default_items = [
        {"id": "item_1", "name": "Atta (Flour)", "stock": 50, "sales": 0, "lastUpdated": datetime.datetime.now().isoformat()},
        {"id": "item_2", "name": "Chawal (Rice)", "stock": 40, "sales": 0, "lastUpdated": datetime.datetime.now().isoformat()},
        {"id": "item_3", "name": "Cheeni (Sugar)", "stock": 25, "sales": 0, "lastUpdated": datetime.datetime.now().isoformat()},
        {"id": "item_4", "name": "Chai Patti (Tea)", "stock": 30, "sales": 0, "lastUpdated": datetime.datetime.now().isoformat()},
        {"id": "item_5", "name": "Cooking Oil", "stock": 20, "sales": 0, "lastUpdated": datetime.datetime.now().isoformat()}
    ]
    _save_local_inventory(default_items)
    return default_items

def _save_local_inventory(items):
    try:
        with open(LOCAL_INVENTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2)
    except Exception as e:
        print(f"Error saving local inventory: {e}")

def get_inventory():
    global db
    if db is None:
        init_firestore()
    if db is not None:
        try:
            docs = db.collection("inventory").stream()
            items = []
            for doc in docs:
                d = doc.to_dict()
                d["id"] = doc.id
                d["stock"] = int(d.get("stock", d.get("quantity", 0)))
                if "name" in d:
                    items.append(d)
            if items:
                return items
        except Exception as e:
            print(f"Firestore Get Error: {e}. Falling back to local store.")
    
    return _load_local_inventory()

def normalize_text(text: str) -> str:
    import re
    return re.sub(r'[^\w\s]', ' ', str(text).lower()).strip()

def item_matches(inv_name: str, search_name: str) -> bool:
    norm_inv = normalize_text(inv_name)
    norm_q = normalize_text(search_name)
    if not norm_q:
        return False
    if norm_inv == norm_q or norm_q in norm_inv or norm_inv in norm_q:
        return True
    if set(norm_inv.split()) & set(norm_q.split()):
        return True
    synonyms = {
        'flour': ['atta', 'aata', 'wheat', 'maida'],
        'sugar': ['cheeni', 'chini', 'shakar'],
        'rice': ['chawal'],
        'tea': ['chai', 'patti'],
        'oil': ['tel', 'cooking oil', 'ghee']
    }
    for primary, syn_list in synonyms.items():
        all_s = set([primary] + syn_list)
        if any(s in norm_q for s in all_s) and any(s in norm_inv for s in all_s):
            return True
    return False

def update_inventory_item(item_name, action, qty):
    global db
    if db is None:
        init_firestore()
    now = datetime.datetime.now().isoformat()
    search_name = str(item_name).strip()
    change_qty = int(qty)

    if db is not None:
        try:
            docs = db.collection("inventory").stream()
            target_doc = None
            for doc in docs:
                data = doc.to_dict()
                if item_matches(data.get("name", ""), search_name):
                    target_doc = doc
                    break
                    
            if target_doc:
                doc_ref = db.collection("inventory").document(target_doc.id)
                current = target_doc.to_dict()
                old_val = int(current.get("stock", current.get("quantity", 0)))
                old_sales = int(current.get("sales", 0))
                
                if action == "add":
                    new_val = old_val + change_qty
                    new_sales = old_sales
                else:
                    new_val = max(0, old_val - change_qty)
                    new_sales = old_sales + change_qty
                
                update_data = {
                    "stock": new_val,
                    "sales": new_sales,
                    "lastUpdated": now
                }
                doc_ref.update(update_data)
                return {
                    "id": target_doc.id, 
                    "name": current.get("name"), 
                    "stock": new_val,
                    "sales": new_sales,
                    "lastUpdated": now
                }
            else:
                new_val = change_qty if action == "add" else 0
                new_sales = change_qty if action != "add" else 0
                new_doc = {
                    "name": item_name,
                    "stock": new_val,
                    "sales": new_sales,
                    "lastUpdated": now
                }
                doc_ref = db.collection("inventory").document()
                doc_ref.set(new_doc)
                return {
                    "id": doc_ref.id,
                    "name": item_name,
                    "stock": new_val,
                    "lastUpdated": now
                }
        except Exception as e:
            print(f"Firestore Update Error: {e}. Falling back to local store.")

    # Local fallback
    items = _load_local_inventory()
    target = None
    for item in items:
        if item_matches(item.get("name", ""), search_name):
            target = item
            break
            
    if target:
        old_val = int(target.get("stock", 0))
        old_sales = int(target.get("sales", 0))
        if action == "add":
            target["stock"] = old_val + change_qty
        else:
            target["stock"] = max(0, old_val - change_qty)
            target["sales"] = old_sales + change_qty
        target["lastUpdated"] = now
        _save_local_inventory(items)
        return target
    else:
        new_val = change_qty if action == "add" else 0
        new_sales = change_qty if action != "add" else 0
        new_item = {
            "id": f"item_{len(items)+1}_{int(datetime.datetime.now().timestamp())}",
            "name": item_name,
            "stock": new_val,
            "sales": new_sales,
            "lastUpdated": now
        }
        items.append(new_item)
        _save_local_inventory(items)
        return new_item