from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
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

LICENSE_API_VALIDATE_URL = "https://api.lemonsqueezy.com/v1/licenses/validate"  # :contentReference[oaicite:6]{index=6}
ORDERS_URL = "https://api.lemonsqueezy.com/v1/orders"  # :contentReference[oaicite:7]{index=7}


class SyncReq(BaseModel):
    license_key: str
    email: EmailStr


def parse_iso(dt_str: str) -> datetime:
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))


def is_maintenance_product(order: dict) -> bool:
    attrs = order.get("attributes", {}) or {}
    first_item = attrs.get("first_order_item", {}) or {}
    return first_item.get("variant_id") == MAINTENANCE_VARIANT_ID


def list_orders_by_email(email: str) -> list[dict]:
    # Lemon uses page-based pagination with links.next :contentReference[oaicite:8]{index=8}
    url = ORDERS_URL
    params = {"filter[user_email]": email, "page[size]": 100}
    orders = []

    while True:
        r = requests.get(url, headers=REST_HEADERS, params=params, timeout=20)
        if r.status_code != 200:
            raise HTTPException(status_code=400, detail="Could not fetch orders from Lemon")

        payload = r.json()
        orders.extend(payload.get("data", []) or [])

        next_url = (payload.get("links", {}) or {}).get("next")
        if not next_url:
            break

        url = next_url
        params = None  # next_url already contains params

    return orders


@app.post("/sync-maintenance")
def sync_maintenance(req: SyncReq):
    if not LEMON_API_KEY:
        raise HTTPException(status_code=500, detail="Server misconfiguration: No API Key")

    # 1) Validate the perpetual license key (License API)
    # This endpoint validates the key string. :contentReference[oaicite:9]{index=9}
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

    # 2) Base entitlement: you already set "activation date + 365" in the app.
    # Backend should mirror that: start from *now* and extend. (No created_at available reliably.)
    now = datetime.now(timezone.utc)
    updates_until = now + timedelta(days=365)

    # 3) Find maintenance purchases by email
    orders = list_orders_by_email(req.email)

    # Optional: count only paid orders (adapt field names if needed)
    # We'll still require maintenance variant match; you can add status checks later.
    maint_orders = []
    for o in orders:
        if is_maintenance_product(o):
            attrs = o.get("attributes", {}) or {}
            created_at = attrs.get("created_at")
            if created_at:
                maint_orders.append(parse_iso(created_at))

    maint_orders.sort()

    # 4) Stack: +1 year per maintenance order
    for _dt in maint_orders:
        if updates_until < now:
            updates_until = now + timedelta(days=365)
        else:
            updates_until = updates_until + timedelta(days=365)

    return {"status": "active", "updates_until": updates_until.strftime("%Y-%m-%d")}
