# tests/test_main.py

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "OctoPrint FastAPI Server Running"}

def test_move_printer_no_axis():
    response = client.post("/printer/move", json={})
    assert response.status_code == 400
    assert response.json() == {"detail": "No movement axis specified"}

def test_move_printer_x_axis():
    response = client.post("/printer/move", json={"x": 10.0})
    assert response.status_code == 200
    assert "Sent command: G0 X10.0" in response.json()["message"]

def test_move_printer_xyz_axis():
    response = client.post("/printer/move", json={"x": 10.0, "y": 5.0, "z": 3.0})
    assert response.status_code == 200
    assert "Sent command: G0 X10.0 Y5.0 Z3.0" in response.json()["message"]
