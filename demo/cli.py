"""
Small command-line demo: uploads a local image straight to S3 (using boto3
credentials on this machine, bypassing the presigned-URL API endpoint that a
browser client would use instead), then polls the API for that image's
Rekognition face analysis until the ingest Lambda has finished processing it.

Usage:
    python demo/cli.py path/to/photo.jpg \\
        --bucket face-analysis-uploads-123456789012-us-east-1 \\
        --api-url https://abc123.execute-api.us-east-1.amazonaws.com/Prod
"""
import argparse
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import boto3


def upload_image(bucket: str, image_path: str) -> tuple[str, str]:
    """Uploads the file and returns (image_id, s3_key)."""
    image_id = str(uuid.uuid4())
    filename = Path(image_path).name
    key = f"uploads/{image_id}/{filename}"

    s3 = boto3.client("s3")
    s3.upload_file(image_path, bucket, key)
    return image_id, key


def poll_for_result(api_base_url: str, image_id: str, timeout: int = 30, interval: int = 2) -> dict:
    url = f"{api_base_url.rstrip('/')}/images/{image_id}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
        time.sleep(interval)
    raise TimeoutError(f"No analysis result for image {image_id} after {timeout}s")


def print_result(result: dict) -> None:
    print(f"Faces detected: {result['FaceCount']}")
    for i, face in enumerate(result.get("Faces", []), start=1):
        age = face.get("AgeRange") or {}
        gender_conf = face.get("GenderConfidence")
        emotion_conf = face.get("TopEmotionConfidence")
        print(
            f"  Face {i}: age {age.get('Low')}-{age.get('High')}, "
            f"gender={face.get('Gender')}"
            + (f" ({gender_conf:.1f}%)" if gender_conf is not None else "")
            + f", top emotion={face.get('TopEmotion')}"
            + (f" ({emotion_conf:.1f}%)" if emotion_conf is not None else "")
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image_path")
    parser.add_argument("--bucket", required=True, help="Uploads bucket name (see the stack's UploadsBucketName output)")
    parser.add_argument("--api-url", required=True, help="API Gateway base URL (see the stack's ApiUrl output)")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    image_id, key = upload_image(args.bucket, args.image_path)
    print(f"Uploaded to s3://{args.bucket}/{key}  (image id: {image_id})")

    result = poll_for_result(args.api_url, image_id, timeout=args.timeout)
    print_result(result)


if __name__ == "__main__":
    main()
