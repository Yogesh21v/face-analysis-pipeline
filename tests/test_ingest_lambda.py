import os

import pytest

from loader import load_lambda_module

INGEST_APP_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "ingest_lambda", "app.py")
ingest_app = load_lambda_module(INGEST_APP_PATH, "ingest_app")

# A realistic Rekognition DetectFaces response shape (trimmed to the fields
# this project actually reads), used to test build_record() without ever
# calling AWS -- moto doesn't support Rekognition, so this fixture stands in
# for it the same way the goalpost-chatbot tests stub the Lex runtime.
SAMPLE_REKOGNITION_RESPONSE = {
    "FaceDetails": [
        {
            "BoundingBox": {"Width": 0.32, "Height": 0.44, "Left": 0.33, "Top": 0.25},
            "AgeRange": {"Low": 25, "High": 35},
            "Smile": {"Value": True, "Confidence": 98.5},
            "Eyeglasses": {"Value": False, "Confidence": 99.1},
            "Sunglasses": {"Value": False, "Confidence": 99.9},
            "Gender": {"Value": "Female", "Confidence": 99.7},
            "EyesOpen": {"Value": True, "Confidence": 98.0},
            "MouthOpen": {"Value": True, "Confidence": 87.3},
            "Emotions": [
                {"Type": "HAPPY", "Confidence": 95.2},
                {"Type": "CALM", "Confidence": 3.1},
                {"Type": "SURPRISED", "Confidence": 1.0},
            ],
            "Confidence": 99.99,
        }
    ]
}

NO_FACES_RESPONSE = {"FaceDetails": []}


def test_parse_image_id_from_key_extracts_client_chosen_id():
    key = "uploads/6b1f2b2e-27b2-4b8a-9a4c-111111111111/beach.jpg"
    assert ingest_app.parse_image_id_from_key(key) == "6b1f2b2e-27b2-4b8a-9a4c-111111111111"


def test_parse_image_id_from_key_falls_back_for_unrecognized_shape():
    # No <id>/<filename> structure under uploads/ -- e.g. uploaded by hand
    # through the console straight into the uploads/ prefix.
    image_id = ingest_app.parse_image_id_from_key("uploads/random_photo.jpg")
    # Should still produce *some* usable id (a uuid4), not crash or return None.
    assert isinstance(image_id, str) and len(image_id) > 0


def test_build_record_flattens_face_details_correctly():
    record = ingest_app.build_record("my-bucket", "uploads/id-1/photo.jpg", SAMPLE_REKOGNITION_RESPONSE, image_id="id-1")
    assert record["ImageId"] == "id-1"
    assert record["S3Bucket"] == "my-bucket"
    assert record["S3Key"] == "uploads/id-1/photo.jpg"
    assert record["FaceCount"] == 1

    face = record["Faces"][0]
    assert face["AgeRange"] == {"Low": 25, "High": 35}
    assert face["Gender"] == "Female"
    assert face["GenderConfidence"] == pytest.approx(99.7)
    assert face["Smile"] is True
    assert face["TopEmotion"] == "HAPPY"  # highest-confidence of the three emotions
    assert face["TopEmotionConfidence"] == pytest.approx(95.2)


def test_build_record_handles_zero_faces():
    record = ingest_app.build_record("my-bucket", "uploads/id-2/empty.jpg", NO_FACES_RESPONSE, image_id="id-2")
    assert record["FaceCount"] == 0
    assert record["Faces"] == []


def test_build_record_uses_default_image_id_when_not_given():
    record = ingest_app.build_record("my-bucket", "uploads/id-3/photo.jpg", NO_FACES_RESPONSE)
    assert record["ImageId"] == "id-3"


def test_process_s3_record_calls_rekognition_and_writes_to_dynamodb(aws, monkeypatch):
    monkeypatch.setattr(ingest_app, "analyze_image", lambda bucket, key: SAMPLE_REKOGNITION_RESPONSE)

    record = {
        "s3": {
            "bucket": {"name": "face-analysis-uploads-test"},
            "object": {"key": "uploads/id-99/party.jpg"},
        }
    }
    item = ingest_app.process_s3_record(record, aws["table"])

    assert item["ImageId"] == "id-99"
    assert item["FaceCount"] == 1

    stored = aws["table"].get_item(Key={"ImageId": "id-99"}).get("Item")
    assert stored is not None
    assert stored["S3Key"] == "uploads/id-99/party.jpg"


def test_process_s3_record_decodes_plus_as_space_in_key(aws, monkeypatch):
    monkeypatch.setattr(ingest_app, "analyze_image", lambda bucket, key: NO_FACES_RESPONSE)

    record = {
        "s3": {
            "bucket": {"name": "face-analysis-uploads-test"},
            "object": {"key": "uploads/id-100/my+photo.jpg"},
        }
    }
    item = ingest_app.process_s3_record(record, aws["table"])
    assert item["S3Key"] == "uploads/id-100/my photo.jpg"


def test_lambda_handler_processes_all_records_in_batch(aws, monkeypatch):
    monkeypatch.setattr(ingest_app, "analyze_image", lambda bucket, key: SAMPLE_REKOGNITION_RESPONSE)

    event = {
        "Records": [
            {"s3": {"bucket": {"name": "face-analysis-uploads-test"}, "object": {"key": "uploads/a/1.jpg"}}},
            {"s3": {"bucket": {"name": "face-analysis-uploads-test"}, "object": {"key": "uploads/b/2.jpg"}}},
        ]
    }
    result = ingest_app.lambda_handler(event, None)
    assert result["processed"] == 2

    assert aws["table"].get_item(Key={"ImageId": "a"}).get("Item") is not None
    assert aws["table"].get_item(Key={"ImageId": "b"}).get("Item") is not None
