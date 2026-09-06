"""
API Gateway-backed Lambda exposing the stored face-analysis results:

  GET  /images            -> most recent analyzed images (newest first)
  GET  /images/{imageId}  -> full analysis for one image
  POST /upload-url        -> a presigned S3 PUT URL for a new upload

The presigned-URL endpoint exists so a browser/mobile client could upload
directly to S3 without routing image bytes through API Gateway/Lambda (API
Gateway has a 10MB payload limit); demo/cli.py in this repo instead uploads
straight to S3 with boto3 credentials, which is simpler for a local demo but
isn't how a real client-facing app would do it.
"""
import json
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

_dynamodb = boto3.resource("dynamodb")
_s3 = boto3.client("s3")

TABLE_NAME = os.environ.get("TABLE_NAME", "FaceAnalysisResults")
UPLOAD_BUCKET = os.environ.get("UPLOAD_BUCKET", "")
GSI_NAME = "UploadTimeIndex"
RECORD_TYPE = "FACE_ANALYSIS"


def _json_default(value):
    """DynamoDB items come back with Decimal for every number (bounding-box
    ratios, confidences); Decimal isn't JSON-serializable by default, so
    this converts it to a plain int (when it's a whole number) or float for
    the API response, rather than falling back to str(value) and turning
    every number into a quoted string."""
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    return str(value)


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=_json_default),
    }


def list_recent_images(table, limit: int = 20):
    """Newest-first listing via the UploadTimeIndex GSI (partitioned on the
    constant RecordType so all records land in one logical partition -- fine
    at this project's scale, and documented as a known scaling limitation in
    the README rather than hidden). Falls back to an unsorted scan if the
    GSI isn't available, so the API still works against a minimal/older
    table definition."""
    try:
        result = table.query(
            IndexName=GSI_NAME,
            KeyConditionExpression=Key("RecordType").eq(RECORD_TYPE),
            ScanIndexForward=False,
            Limit=limit,
        )
        return result.get("Items", [])
    except Exception:
        result = table.scan(Limit=limit)
        return result.get("Items", [])


def get_image(table, image_id: str):
    result = table.get_item(Key={"ImageId": image_id})
    return result.get("Item")


def generate_upload_url(key: str) -> str:
    return _s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": UPLOAD_BUCKET, "Key": key},
        ExpiresIn=300,
    )


def _handle_list_images(event, table):
    params = event.get("queryStringParameters") or {}
    try:
        limit = int(params.get("limit", 20))
    except (TypeError, ValueError):
        return _response(400, {"error": "limit must be an integer"})
    return _response(200, {"images": list_recent_images(table, limit=limit)})


def _handle_get_image(event, table):
    image_id = (event.get("pathParameters") or {}).get("imageId")
    if not image_id:
        return _response(400, {"error": "imageId is required"})
    item = get_image(table, image_id)
    if item is None:
        return _response(404, {"error": "not found"})
    return _response(200, item)


def _handle_upload_url(event):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "body must be valid JSON"})
    filename = body.get("filename")
    image_id = body.get("imageId")
    if not filename or not image_id:
        return _response(400, {"error": "filename and imageId are required"})
    key = f"uploads/{image_id}/{filename}"
    return _response(200, {"uploadUrl": generate_upload_url(key), "key": key})


def lambda_handler(event, context):
    table = _dynamodb.Table(TABLE_NAME)
    method = event.get("httpMethod")
    path = event.get("path", "")

    if method == "GET" and path == "/images":
        return _handle_list_images(event, table)
    if method == "GET" and path.startswith("/images/"):
        return _handle_get_image(event, table)
    if method == "POST" and path == "/upload-url":
        return _handle_upload_url(event)

    return _response(404, {"error": "not found"})
