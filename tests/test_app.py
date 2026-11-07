import os
import tempfile
from pathlib import Path

os.environ["CROSSLIST_PASSWORD"] = "local-test-password"
_tmp = tempfile.TemporaryDirectory()
os.environ["CROSSLIST_DB"] = str(Path(_tmp.name) / "test.sqlite3")
from fastapi.testclient import TestClient
from app.main import app

def test_stock_and_sale():
    with TestClient(app) as c:
        auth = ("admin", "local-test-password")
        assert c.get("/api/items").status_code == 401
        created = c.post("/api/items", auth=auth, json={"sku":"TEST-001","title":"Jacket","price_pence":2500,"quantity":1})
        assert created.status_code == 201
        item = created.json()
        linked = c.post(f"/api/items/{item['id']}/listings", auth=auth, json={"marketplace":"ebay","price_pence":2600,"status":"live"})
        assert linked.status_code == 201
        result = c.post(f"/api/items/{item['id']}/sold", auth=auth)
        assert result.json() == {"status":"sold","action_required":1}
        listing = c.get("/api/items", auth=auth).json()[0]["listings"][0]
        assert listing["status"] == "action_required"
        assert c.patch(f"/api/listings/{listing['id']}/status", auth=auth, json={"status":"live"}).status_code == 409
        assert c.patch(f"/api/listings/{listing['id']}/status", auth=auth, json={"status":"ended"}).json()["status"] == "ended"
        assert c.post("/api/items", auth=auth, json={"sku":"TEST-001","title":"Duplicate","price_pence":1}).status_code == 409
