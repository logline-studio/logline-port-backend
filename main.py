from fastapi import FastAPI, HTTPException
import requests
from datetime import datetime, timedelta

app = FastAPI()

# --- CONFIGURATION ---
MAINTENANCE_VARIANT_ID = 746775 # REPLACE with the Variant ID of your "1 Year Maintenance" product
LEMON_API_KEY = os.environ.get("LEMON_API_KEY")
if not LEMON_API_KEY:
    raise ValueError("LEMON_API_KEY is not set in environment variables!")

def is_maintenance_product(order):
    """
    Helper function to check if an order contains the maintenance product.
    """
    # Lemon Squeezy orders have an 'included' array or relationships.
    # For simplicity in this example, we assume we check the 'first' order item variant_id.
    # In a real production app, you might need to query the /order-items endpoint for this order.
    
    # Simplified check: logic depends on how detailed the order object is.
    # Often it's easier to check product_name or variant_id if available in attributes.
    attributes = order.get('attributes', {})
    
    # If you see 'first_order_item' in attributes (Lemon API sometimes includes summaries)
    first_item = attributes.get('first_order_item', {})
    if first_item.get('variant_id') == MAINTENANCE_VARIANT_ID:
        return True
        
    return False

@app.post("/sync-maintenance")
def sync_maintenance(data: dict):
    license_key = data.get("license_key")
    
    if not license_key:
        raise HTTPException(status_code=400, detail="Missing license key")
    
    # 1. Validate License Key & Get Customer
    headers = {
        "Authorization": f"Bearer {LEMON_API_KEY}", 
        "Accept": "application/vnd.api+json"
    }
    
    # Get the license info
    r = requests.get(f"https://api.lemonsqueezy.com/v1/licenses?filter[key]={license_key}", headers=headers)
    resp_data = r.json()
    
    if not resp_data.get('data'):
        raise HTTPException(status_code=400, detail="Invalid Key")
    
    license_data = resp_data['data'][0]
    customer_id = license_data['attributes']['customer_id']
    
    # Initial expiry is 1 year after the original license creation
    created_at_str = license_data['attributes']['created_at'] # e.g. "2024-05-20T14:00:00.000000Z"
    # Fix 'Z' for python < 3.11 if needed, or just slice
    created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
    
    updates_until = created_at + timedelta(days=365)
    
    # 2. Find Maintenance Top-ups
    # Fetch all orders for this customer
    r_orders = requests.get(f"https://api.lemonsqueezy.com/v1/orders?filter[customer_id]={customer_id}", headers=headers)
    orders = r_orders.json().get('data', [])
    
    for order in orders:
        if is_maintenance_product(order):
            now = datetime.now(created_at.tzinfo) # Use timezone aware now
            
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
