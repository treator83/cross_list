import hmac
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field, field_validator

DB_PATH = Path(os.getenv("CROSSLIST_DB", "/data/crosslist.sqlite3"))
PASSWORD = os.getenv("CROSSLIST_PASSWORD", "")
USERNAME = os.getenv("CROSSLIST_USERNAME", "admin")
if not PASSWORD:
    raise RuntimeError("CROSSLIST_PASSWORD is required")
app = FastAPI(title="CrossList", docs_url=None, redoc_url=None)
security = HTTPBasic(auto_error=False)
MARKETPLACES = {"ebay", "vinted", "depop", "facebook", "other"}

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def auth(credentials: HTTPBasicCredentials | None = Depends(security)):
    valid = bool(credentials) and hmac.compare_digest(credentials.username.encode(), USERNAME.encode()) and hmac.compare_digest(credentials.password.encode(), PASSWORD.encode())
    if not valid:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": 'Basic realm="CrossList"'})

@contextmanager
def database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    try:
        yield db
    finally:
        db.close()

@app.on_event("startup")
def startup():
    with database() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          sku TEXT NOT NULL UNIQUE,
          title TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          price_pence INTEGER NOT NULL CHECK(price_pence >= 0),
          quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity >= 0),
          status TEXT NOT NULL DEFAULT 'available' CHECK(status IN ('available','sold')),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS listings (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
          marketplace TEXT NOT NULL,
          external_id TEXT NOT NULL DEFAULT '',
          url TEXT NOT NULL DEFAULT '',
          price_pence INTEGER NOT NULL CHECK(price_pence >= 0),
          status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','live','ended','action_required')),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS listings_item_id ON listings(item_id);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          item_id INTEGER NOT NULL REFERENCES items(id),
          message TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        """)

class ItemInput(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    price_pence: int = Field(ge=0, le=100000000)
    quantity: int = Field(default=1, ge=0, le=100000)

    @field_validator("sku")
    @classmethod
    def validate_sku(cls, value):
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
            raise ValueError("SKU must contain only letters, digits, dots, underscores or dashes")
        return value

    @field_validator("title")
    @classmethod
    def validate_title(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Title required")
        return value

class ListingInput(BaseModel):
    marketplace: str
    external_id: str = Field(default="", max_length=200)
    url: str = Field(default="", max_length=2000)
    price_pence: int = Field(ge=0, le=100000000)
    status: str = "draft"

    @field_validator("marketplace")
    @classmethod
    def validate_marketplace(cls, value):
        if value not in MARKETPLACES:
            raise ValueError("Unsupported marketplace")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        if value not in {"draft", "live", "ended", "action_required"}:
            raise ValueError("Invalid status")
        return value

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        parsed = urlparse(value)
        if value and (parsed.scheme not in {"http", "https"} or not parsed.netloc):
            raise ValueError("URL must start with http:// or https://")
        return value

def get_item(db, item_id):
    row = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Item not found")
    return row

@app.get("/", dependencies=[Depends(auth)])
def index():
    return FileResponse(Path(__file__).resolve().parent / "index.html")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/items", dependencies=[Depends(auth)])
def get_items():
    with database() as db:
        rows = db.execute("SELECT * FROM items ORDER BY id DESC").fetchall()
        return [{**dict(row), "listings": [dict(x) for x in db.execute("SELECT * FROM listings WHERE item_id=? ORDER BY id DESC", (row["id"],))]} for row in rows]

@app.post("/api/items", status_code=201, dependencies=[Depends(auth)])
def create_item(data: ItemInput):
    with database() as db:
        try:
            cur = db.execute("INSERT INTO items (sku,title,description,price_pence,quantity,created_at,updated_at) VALUES (?,?,?,?,?,?,?)", (data.sku,data.title,data.description,data.price_pence,data.quantity,now(),now()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "SKU already exists")
        return dict(get_item(db, cur.lastrowid))

@app.put("/api/items/{item_id}", dependencies=[Depends(auth)])
def update_item(item_id: int, data: ItemInput):
    with database() as db:
        if get_item(db, item_id)["status"] == "sold":
            raise HTTPException(409, "Sold items cannot be edited")
        try:
            db.execute("UPDATE items SET sku=?,title=?,description=?,price_pence=?,quantity=?,updated_at=? WHERE id=?", (data.sku,data.title,data.description,data.price_pence,data.quantity,now(),item_id))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "SKU already exists")
        return dict(get_item(db, item_id))

@app.post("/api/items/{item_id}/listings", status_code=201, dependencies=[Depends(auth)])
def add_listing(item_id: int, data: ListingInput):
    with database() as db:
        item = get_item(db, item_id)
        if item["status"] == "sold" and data.status in {"draft", "live"}:
            raise HTTPException(409, "Cannot create an active listing for a sold item")
        cur = db.execute("INSERT INTO listings (item_id,marketplace,external_id,url,price_pence,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)", (item_id,data.marketplace,data.external_id,data.url,data.price_pence,data.status,now(),now()))
        return dict(db.execute("SELECT * FROM listings WHERE id=?", (cur.lastrowid,)).fetchone())

@app.patch("/api/listings/{listing_id}/status", dependencies=[Depends(auth)])
def set_listing_status(listing_id: int, payload: dict):
    status = payload.get("status")
    if status not in {"draft", "live", "ended", "action_required"}:
        raise HTTPException(422, "Invalid status")
    with database() as db:
        listing = db.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
        if not listing:
            raise HTTPException(404, "Listing not found")
        if get_item(db, listing["item_id"])["status"] == "sold" and status in {"draft","live"}:
            raise HTTPException(409, "Cannot reactivate sold stock")
        db.execute("UPDATE listings SET status=?,updated_at=? WHERE id=?", (status,now(),listing_id))
        return dict(db.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone())

@app.post("/api/items/{item_id}/sold", dependencies=[Depends(auth)])
def mark_sold(item_id: int):
    # Local state only. No external marketplace has been contacted.
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        item = get_item(db, item_id)
        if item["status"] == "sold":
            db.execute("COMMIT")
            return {"status":"already_sold","action_required":0}
        db.execute("UPDATE items SET status='sold',quantity=0,updated_at=? WHERE id=?", (now(),item_id))
        cur = db.execute("UPDATE listings SET status='action_required',updated_at=? WHERE item_id=? AND status='live'", (now(),item_id))
        db.execute("INSERT INTO events (item_id,message,created_at) VALUES (?,?,?)", (item_id,f"Marked sold; {cur.rowcount} live external listings require manual ending",now()))
        db.execute("COMMIT")
        return {"status":"sold","action_required":cur.rowcount}

@app.get("/api/events", dependencies=[Depends(auth)])
def get_events():
    with database() as db:
        return [dict(x) for x in db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 50")]
