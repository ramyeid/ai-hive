from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_returns_200():
    response = client.get("/")
    assert response.status_code == 200


def test_root_returns_hello_world_json():
    response = client.get("/")
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"message": "Hello World"}
