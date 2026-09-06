"""
A pytest fixture that spins up mocked S3 + DynamoDB (via moto) matching the
real infra/template.yaml schema, so the Lambda handlers can be tested
against something that behaves like the real AWS resources without any
real AWS account. Rekognition itself isn't mocked here -- moto doesn't
support it -- see test_ingest_lambda.py for how that call is stubbed
instead.
"""
import boto3
import pytest
from moto import mock_aws

TABLE_NAME = "FaceAnalysisResults"
BUCKET_NAME = "face-analysis-uploads-test"


@pytest.fixture
def aws():
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET_NAME)

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName=TABLE_NAME,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "ImageId", "AttributeType": "S"},
                {"AttributeName": "RecordType", "AttributeType": "S"},
                {"AttributeName": "UploadedAt", "AttributeType": "S"},
            ],
            KeySchema=[{"AttributeName": "ImageId", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "UploadTimeIndex",
                    "KeySchema": [
                        {"AttributeName": "RecordType", "KeyType": "HASH"},
                        {"AttributeName": "UploadedAt", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )
        table.wait_until_exists()

        yield {"s3": s3, "dynamodb": dynamodb, "table": table}
