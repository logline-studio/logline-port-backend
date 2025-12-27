from fastapi import FastAPI, HTTPException
import requests
import os  # <--- THIS WAS MISSING!
from datetime import datetime, timedelta

app = FastAPI()

# --- CONFIGURATION ---
MAINTENANCE_VARIANT_ID = 746775 
LEMON_API_KEY = os.environ.get("LEMON_API_KEY")

if not LEMON_API_KEY:
    # This prevents the app from starting if the key is missing
    print("CRITICAL ERROR: LEMON_API_KEY not found in environment variables.")

def is_maintenance_product(order):
    """
    Helper function to check if an order contains the maintenance product.
    """
    attributes = order.get('attributes', {})
    
    # Check first_order_item shorthand
    first_item = attributes.get('first_order_item', {})
    if first_item.get('variant_id') == MAINTENANCE_VARIANT_ID:
        return True
        
    return False

@app.post("/sync-maintenance")
def sync_maintenance(data: dict):
    license_key = data.get("license_key")
    
    if not license_key:
        raise HTTPException(status_code=400, detail="Missing license key")
    
    if not LEMON_API_KEY:
        raise HTTPException(status_code=500, detail="Server misconfiguration: No API Key")

    # 1. Validate License Key & Get Customer
    headers = {
        "Authorization": f"Bearer {LEMON_API_KEY}", 
        "Accept": "application/vnd.api+json"
    }
    
    # Get the license info
    r = requests.get(f"https://api.lemonsqueezy.com/v1/licenses?filter[key]={license_key}", headers=headers)
    
    if r.status_code != 200:
         raise HTTPException(status_code=400, detail="Could not verify license with Lemon Squeezy")

    resp_data = r.json()
    
    if not resp_data.get('data'):
        raise HTTPException(status_code=400, detail="Invalid Key")
    
    license_data = resp_data['data'][0]
    customer_id = license_data['attributes']['customer_id']
    
    # Initial expiry is 1 year after the original license creation
    created_at_str = license_data['attributes']['created_at'] 
    # Handle ISO format with Z
    created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
    
    # STARTING POINT: Purchase Date + 1 Year
    updates_until = created_at + timedelta(days=365)
    
    # 2. Find Maintenance Top-ups
    r_orders = requests.get(f"https://api.lemonsqueezy.com/v1/orders?filter[customer_id]={customer_id}", headers=headers)
    orders = r_orders.json().get('data', [])
    
    for order in orders:
        if is_maintenance_product(order):
            now = datetime.now(created_at.tzinfo) 
            
            # Logic: Stack the years
            if updates_until < now:
                # If expired, restart from today
                updates_until = now + timedelta(days=365)
            else:
                # If active, add 1 year to current expiry
                updates_until = updates_until + timedelta(days=365)
                
    return {
        "status": "active",
        "updates_until": updates_until.strftime("%Y-%m-%d")
    }
