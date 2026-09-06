# Face Detection & Analysis Pipeline

A serverless pipeline that analyzes faces in uploaded photos using Amazon
Rekognition: age range, gender, top emotion, smile/glasses/eyes-open, and
more, stored per-image in DynamoDB and queryable through a small REST API.

## Architecture

```
Image upload (uploads/<image-id>/<filename>)
                │
                ▼
        S3 (uploads bucket)
                │  ObjectCreated event
                ▼
        IngestFunction (Lambda)
        - calls Rekognition DetectFaces
        - flattens the response
        - writes one item per image to DynamoDB
                │
                ▼
   DynamoDB (FaceAnalysisResults table)
                │
                ▼
        ApiFunction (Lambda, behind API Gateway)
        GET  /images            -> recent analyzed images
        GET  /images/{imageId}  -> full analysis for one image
        POST /upload-url        -> presigned S3 PUT URL for a new upload
```

The image id is chosen by the *client* uploading the photo (see
`demo/cli.py`) and embedded in the S3 key as `uploads/<image-id>/<filename>`,
so the client can start polling `/images/{imageId}` immediately after
upload finishes instead of waiting to be told what id the server assigned.

## What's in this repo

| Path | What it is |
|---|---|
| `backend/ingest_lambda/app.py` | S3-triggered function: calls Rekognition `DetectFaces`, flattens the result, writes it to DynamoDB. |
| `backend/api_lambda/app.py` | API Gateway-backed function: list/get analyzed images, and issue presigned upload URLs. |
| `infra/template.yaml` | AWS SAM template provisioning the S3 bucket, DynamoDB table (with a GSI for newest-first listing), and both Lambda functions with their event bindings and IAM policies. Validated with `cfn-lint`. |
| `demo/cli.py` | Command-line demo: uploads a local image to S3, then polls the API until the analysis is ready and prints it. |
| `tests/` | Pytest suite (22 tests) covering both Lambda functions against mocked S3/DynamoDB (via `moto`) and a hand-built Rekognition response fixture (`moto` doesn't support mocking Rekognition itself). |

## Running the tests

```bash
pip install -r requirements.txt
cd tests && pip install -r requirements.txt
pytest -v
```

All 22 tests pass with no real AWS account needed — S3 and DynamoDB are
mocked with `moto`, and the one genuinely un-mockable call (Rekognition
`DetectFaces`) is stubbed with a realistic fixture response in
`test_ingest_lambda.py`.

## Deploying for real

```bash
sam build --template-file infra/template.yaml
sam deploy --guided
```

This provisions real AWS resources and will incur (small) charges —
Rekognition's `DetectFaces` API, Lambda invocations, and DynamoDB
on-demand capacity all bill per use. After deploying, note the
`UploadsBucketName` and `ApiUrl` stack outputs and try the demo:

```bash
python demo/cli.py path/to/photo.jpg \
    --bucket <UploadsBucketName output> \
    --api-url <ApiUrl output>
```

## Notes / limitations (intentionally honest)

- Rebuilt from memory rather than from original documentation — see "About
  this rebuild" above.
- The `UploadTimeIndex` GSI partitions on a constant `RecordType` value so
  every item lands in one logical partition. That's a known DynamoDB
  scaling limitation (fine for a small personal-project-scale table, not
  how you'd design it for a table with millions of images) rather than an
  oversight — noted here rather than hidden.
- No frontend is included — the API and CLI demo are the interface. Adding
  a small upload page would be a natural next step (the `/upload-url`
  endpoint already exists for exactly that).
- Never actually deployed/run against real AWS as part of writing this repo
  (no AWS account billing was exercised) — correctness is established by
  the test suite (mocked AWS + a realistic Rekognition fixture) and by
  `cfn-lint` validating the CloudFormation, not by a live deployment.
