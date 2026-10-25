import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import os

# Initialize only if not already initialized
# On Cloud Run: Uses Application Default Credentials (ADC) automatically.
# Locally: Set GOOGLE_APPLICATION_CREDENTIALS env var to the path of your service account JSON.
# IMPORTANT: Make sure the Cloud Run service account has 'Cloud Datastore User' role.
if not firebase_admin._apps:
    try:
        cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if cred_path and os.path.exists(cred_path):
            firebase_admin.initialize_app(credentials.Certificate(cred_path))
            print(f"Firebase initialized with service account: {cred_path}")
        else:
            # Falls back to ADC (works on Cloud Run, GCE, etc.)
            firebase_admin.initialize_app()
            print("Firebase initialized with Application Default Credentials (ADC)")
    except Exception as e:
        print(f"CRITICAL: Firebase initialization failed: {e}")
        raise

def get_inventory():
    db = firestore.client()
    try:
        # Fetch all documents from 'inventory' collection
        docs = db.collection("inventory").stream()
        items = []
        for doc in docs:
            d = doc.to_dict()
            d["id"] = doc.id
            # Safety: Fallback to 'quantity' if 'stock' is missing, default to 0
            d["stock"] = int(d.get("stock", d.get("quantity", 0)))
            # Ensure name exists to prevent frontend map errors
            if "name" in d:
                items.append(d)
        return items
    except Exception as e:
        print(f"Firestore Get Error: {e}")
        return []

def update_inventory_item(item_name, action, qty):
    db = firestore.client()
    now = datetime.datetime.now().isoformat()
    search_name = str(item_name).strip().lower()
    
    try:
        docs = db.collection("inventory").stream()
        target_doc = None
        
        # Search for the item by name (case-insensitive)
        for doc in docs:
            data = doc.to_dict()
            if str(data.get("name", "")).lower() == search_name:
                target_doc = doc
                break
                
        if target_doc:
            doc_ref = db.collection("inventory").document(target_doc.id)
            current = target_doc.to_dict()
            
            # Math logic: Ensure we work with integers
            old_val = int(current.get("stock", current.get("quantity", 0)))
            old_sales = int(current.get("sales", 0))
            change_qty = int(qty)
            
            if action == "add":
                new_val = old_val + change_qty
                new_sales = old_sales
            else:
                new_val = max(0, old_val - change_qty)
                # Increment sales only if it's a sale action
                new_sales = old_sales + change_qty
            
            # Update the document with 'stock', 'sales', and 'lastUpdated'
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
            change_qty = int(qty)
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
        print(f"Firestore Update Error: {e}")
        return {"error": str(e)}