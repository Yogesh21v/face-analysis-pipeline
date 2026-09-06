"""
S3-triggered Lambda: whenever an image lands in the uploads/ prefix of the
uploads bucket, calls Amazon Rekognition's DetectFaces on it and writes a
flattened summary of the results to DynamoDB.

Key design choice: the client uploading the image chooses the image id up
front and embeds it in the S3 key (see demo/cli.py), as
`uploads/<image-id>/<original-filename>`. That way the client can start
polling the API for that exact id immediately after the upload finishes,
instead of needing the server to tell it what id got assigned -- the same
pattern used for async request tracking in the other rebuilt projects in
this account.
"""
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3

_rekognition = boto3.client("rekognition")
_dynamodb = boto3.resource("dynamodb")

TABLE_NAME = os.environ.get("TABLE_NAME", "FaceAnalysisResults")
RECORD_TYPE = "FACE_ANALYSIS"
UPLOAD_PREFIX = "uploads/"

_IMAGE_ID_RE = re.compile(rf"^{re.escape(UPLOAD_PREFIX)}([^/]+)/")


def parse_image_id_from_key(key: str) -> str:
    """Extracts the client-chosen image id from an 'uploads/<id>/<name>'
    key. Falls back to a fresh uuid4 for a key that doesn't match that
    shape (e.g. something uploaded by hand through the S3 console rather
    than through demo/cli.py)."""
    match = _IMAGE_ID_RE.match(key)
    if match:
        return match.group(1)
    return str(uuid.uuid4())


def _extract_face_summary(face: dict) -> dict:
    """Flattens the handful of Rekognition DetectFaces fields this project
    cares about into a DynamoDB-friendly dict. Rekognition returns each
    attribute as a {"Value": ..., "Confidence": ...} pair; we keep the
    confidence only where it's genuinely useful (gender, top emotion) and
    just the boolean value for the rest, to keep stored items small."""
    emotions = face.get("Emotions", [])
    top_emotion = max(emotions, key=lambda e: e.get("Confidence", 0)) if emotions else None

    return {
        "BoundingBox": face.get("BoundingBox", {}),
        "AgeRange": face.get("AgeRange", {"Low": None, "High": None}),
        "Gender": face.get("Gender", {}).get("Value"),
        "GenderConfidence": face.get("Gender", {}).get("Confidence"),
        "Smile": face.get("Smile", {}).get("Value"),
        "Eyeglasses": face.get("Eyeglasses", {}).get("Value"),
        "Sunglasses": face.get("Sunglasses", {}).get("Value"),
        "EyesOpen": face.get("EyesOpen", {}).get("Value"),
        "MouthOpen": face.get("MouthOpen", {}).get("Value"),
        "TopEmotion": top_emotion.get("Type") if top_emotion else None,
        "TopEmotionConfidence": top_emotion.get("Confidence") if top_emotion else None,
    }


def analyze_image(bucket: str, key: str) -> dict:
    """Calls Rekognition DetectFaces on an S3 object. Split out from
    process_s3_record so tests can stub just this one AWS call (moto
    doesn't support Rekognition) without faking the rest of the pipeline."""
    return _rekognition.detect_faces(
        Image={"S3Object": {"Bucket": bucket, "Name": key}},
        Attributes=["ALL"],
    )


def build_record(bucket: str, key: str, rekognition_response: dict, image_id: str = None, uploaded_at: str = None) -> dict:
    """Pure function: a Rekognition DetectFaces response -> the DynamoDB
    item this project stores. Kept free of any AWS I/O so it's trivially
    unit-testable against hand-built fixture responses."""
    faces = [_extract_face_summary(f) for f in rekognition_response.get("FaceDetails", [])]
    return {
        "ImageId": image_id or parse_image_id_from_key(key),
        "RecordType": RECORD_TYPE,
        "S3Bucket": bucket,
        "S3Key": key,
        "UploadedAt": uploaded_at or datetime.now(timezone.utc).isoformat(),
        "FaceCount": len(faces),
        "Faces": faces,
    }


def _floats_to_decimal(value):
    """DynamoDB's boto3 resource API rejects native Python floats -- it
    requires Decimal, for exact-precision reasons -- and Rekognition's
    response is full of floats (confidences, bounding-box ratios). Converts
    recursively just before writing. Kept separate from build_record() so
    that function's output stays plain floats, which is what makes it easy
    to assert against with pytest.approx in tests."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _floats_to_decimal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_floats_to_decimal(v) for v in value]
    return value


def process_s3_record(record: dict, table) -> dict:
    bucket = record["s3"]["bucket"]["name"]
    key = record["s3"]["object"]["key"]
    # S3 event notifications URL-encode keys; spaces become '+'.
    key = key.replace("+", " ")

    response = analyze_image(bucket, key)
    item = build_record(bucket, key, response)
    table.put_item(Item=_floats_to_decimal(item))
    return item


def lambda_handler(event, context):
    table = _dynamodb.Table(TABLE_NAME)
    processed = [process_s3_record(record, table) for record in event.get("Records", [])]
    return {"processed": len(processed), "items": processed}
