import json
import os
from decimal import Decimal

import pytest

from loader import load_lambda_module

API_APP_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "api_lambda", "app.py")
api_app = load_lambda_module(API_APP_PATH, "api_app")


def _seed_item(table, image_id, uploaded_at, face_count=1):
    table.put_item(
        Item={
            "ImageId": image_id,
            "RecordType": "FACE_ANALYSIS",
            "S3Bucket": "face-analysis-uploads-test",
            "S3Key": f"uploads/{image_id}/photo.jpg",
            "UploadedAt": uploaded_at,
            "FaceCount": face_count,
            "Faces": [{"Gender": "Male", "GenderConfidence": Decimal("97.6")}] if face_count else [],
        }
    )


def test_list_recent_images_returns_newest_first(aws):
    table = aws["table"]
    _seed_item(table, "img-1", "2024-01-01T00:00:00+00:00")
    _seed_item(table, "img-2", "2024-01-02T00:00:00+00:00")
    _seed_item(table, "img-3", "2024-01-03T00:00:00+00:00")

    items = api_app.list_recent_images(table, limit=10)
    ids_in_order = [item["ImageId"] for item in items]
    assert ids_in_order == ["img-3", "img-2", "img-1"]


def test_list_recent_images_respects_limit(aws):
    table = aws["table"]
    for i in range(5):
        _seed_item(table, f"img-{i}", f"2024-01-0{i+1}T00:00:00+00:00")

    items = api_app.list_recent_images(table, limit=2)
    assert len(items) == 2


def test_get_image_returns_none_for_missing_id(aws):
    assert api_app.get_image(aws["table"], "does-not-exist") is None


def test_get_image_returns_stored_item(aws):
    _seed_item(aws["table"], "img-42", "2024-01-01T00:00:00+00:00")
    item = api_app.get_image(aws["table"], "img-42")
    assert item["ImageId"] == "img-42"


def test_handle_list_images_returns_200_with_images(aws):
    _seed_item(aws["table"], "img-1", "2024-01-01T00:00:00+00:00")
    event = {"queryStringParameters": None}
    response = api_app._handle_list_images(event, aws["table"])
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert len(body["images"]) == 1


def test_handle_list_images_rejects_non_integer_limit(aws):
    event = {"queryStringParameters": {"limit": "not-a-number"}}
    response = api_app._handle_list_images(event, aws["table"])
    assert response["statusCode"] == 400


def test_handle_get_image_404_for_missing(aws):
    event = {"pathParameters": {"imageId": "nope"}}
    response = api_app._handle_get_image(event, aws["table"])
    assert response["statusCode"] == 404


def test_handle_get_image_returns_full_item_with_decimals_converted(aws):
    _seed_item(aws["table"], "img-7", "2024-01-01T00:00:00+00:00")
    event = {"pathParameters": {"imageId": "img-7"}}
    response = api_app._handle_get_image(event, aws["table"])
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    # Decimal("97.6") must come back as a real JSON number, not a string.
    assert body["Faces"][0]["GenderConfidence"] == pytest.approx(97.6)


def test_handle_upload_url_requires_filename_and_image_id():
    event = {"body": json.dumps({"filename": "photo.jpg"})}  # missing imageId
    response = api_app._handle_upload_url(event)
    assert response["statusCode"] == 400


def test_handle_upload_url_rejects_invalid_json():
    event = {"body": "{not json"}
    response = api_app._handle_upload_url(event)
    assert response["statusCode"] == 400


def test_handle_upload_url_generates_key_with_image_id_prefix(monkeypatch):
    monkeypatch.setattr(api_app, "generate_upload_url", lambda key: f"https://example.com/{key}?signed=1")
    event = {"body": json.dumps({"filename": "photo.jpg", "imageId": "abc-123"})}
    response = api_app._handle_upload_url(event)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["key"] == "uploads/abc-123/photo.jpg"
    assert "signed=1" in body["uploadUrl"]


def test_lambda_handler_routes_get_images(aws):
    event = {"httpMethod": "GET", "path": "/images", "queryStringParameters": None}
    response = api_app.lambda_handler(event, None)
    assert response["statusCode"] == 200


def test_lambda_handler_routes_get_single_image(aws):
    _seed_item(aws["table"], "img-9", "2024-01-01T00:00:00+00:00")
    event = {"httpMethod": "GET", "path": "/images/img-9", "pathParameters": {"imageId": "img-9"}}
    response = api_app.lambda_handler(event, None)
    assert response["statusCode"] == 200


def test_lambda_handler_unknown_route_returns_404(aws):
    event = {"httpMethod": "DELETE", "path": "/images/img-9"}
    response = api_app.lambda_handler(event, None)
    assert response["statusCode"] == 404
