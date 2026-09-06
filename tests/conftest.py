import os
import sys

# The Lambda modules create their boto3 clients at import time
# (module-level `boto3.client(...)`), so a region must be set before any
# test file imports them -- otherwise even the moto-mocked calls fail with
# NoRegionError before moto gets a chance to intercept anything.
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

sys.path.insert(0, os.path.dirname(__file__))

pytest_plugins = ["aws_fixtures"]
