from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
import os
from datetime import datetime, timedelta, timezone

app = FastAPI()

MAINTENANCE_VARIANT_ID = 1175280
LEMON_API_KEY = os.environ.get("LEMON_API_KEY")

if not LEMON_API_KEY:
    print("CRITICAL ERROR: LEMON_API_KEY not found in environment variables.")

REST_HEADERS = {
    "Authorization": f"Bearer {LEMON_API_KEY}",
    "Accept": "application/vnd.api+json",
    "Content-Type": "application/vnd.api+json",
}

LICENSE_API_VALIDATE_URL = "https://api.lemonsqueezy.com/v1/licenses/validate"
ORDERS_URL = "https://api.lemonsqueezy.com/v1/orders"

class SyncReq(BaseModel):
    license_key: str

def parse_iso(dt_str: str) -> datetime:
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))

def is_maintenance_product(order: dict) -> bool:
    attrs = order.get("attributes", {}) or {}
    first_item = attrs.get("first_order_item", {}) or {}
    return first_item.get("variant_id") == MAINTENANCE_VARIANT_ID

def list_orders_by_email(email: str) -> list[dict]:
    url = ORDERS_URL
    params = {"filter[user_email]": email, "page[size]": 100}
    orders = []

    while True:
        r = requests.get(url, headers=REST_HEADERS, params=params, timeout=20)
        if r.status_code != 200:
            print(f"Error fetching orders: {r.text}") 
            break

        payload = r.json()
        orders.extend(payload.get("data", []) or [])

        next_url = (payload.get("links", {}) or {}).get("next")
        if not next_url:
            break
        url = next_url
        params = None 

    return orders

@app.post("/sync-maintenance")
def sync_maintenance(req: SyncReq):
    if not LEMON_API_KEY:
        raise HTTPException(status_code=500, detail="Server misconfiguration: No API Key")

    # 1) Validate the license key
    v = requests.post(
        LICENSE_API_VALIDATE_URL,
        data={"license_key": req.license_key},
        headers={"Accept": "application/json"},
        timeout=20,
    )

    if v.status_code != 200:
        raise HTTPException(status_code=400, detail="Could not validate license key")

    vj = v.json()
    if not vj.get("valid"):
        raise HTTPException(status_code=400, detail="Invalid license key")

    # 2) Extract SECURE data
    meta = vj.get("meta", {})
    license_key_info = vj.get("license_key", {})
    
    secure_email = meta.get("customer_email")
    if not secure_email:
        secure_email = license_key_info.get("user_email")

    created_at_str = license_key_info.get("created_at")
    if not created_at_str:
        created_at = datetime.now(timezone.utc)
    else:
        created_at = parse_iso(created_at_str)

    # 3) Establish Baseline: Original Date + 1 Year
    updates_until = created_at + timedelta(days=365)
    
    # 4) Find PAID maintenance purchases
    if secure_email:
        orders = list_orders_by_email(secure_email)
        
        maint_orders = []
        for o in orders:
            # Check 1: Is it the maintenance product?
            if is_maintenance_product(o):
                attrs = o.get("attributes", {}) or {}
                
                # Check 2: Is the order PAID? (Refunded/Failed orders are ignored) <--- NEW FIX
                if attrs.get("status") == "paid": 
                    order_created = attrs.get("created_at")
                    if order_created:
                        maint_orders.append(parse_iso(order_created))

        maint_orders.sort()

        # 5) Stack Years
        now = datetime.now(timezone.utc)
        for _ in maint_orders:
            if updates_until < now:
                updates_until = now + timedelta(days=365)
            else:
                updates_until = updates_until + timedelta(days=365)

    return {
        "status": "active", 
        "updates_until": updates_until.strftime("%Y-%m-%d")
    }
