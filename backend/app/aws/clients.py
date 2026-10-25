"""Factories for AWS SDK clients (single place for retry + timeout policy)."""

import boto3
from botocore.config import Config

from app.config import Settings

_BOTO_CONFIG = Config(
    retries={"max_attempts": 5, "mode": "adaptive"},
    connect_timeout=5,
    read_timeout=60,
    max_pool_connections=50,
)


def bedrock_runtime(settings: Settings, region: str | None = None):
    """Create a Bedrock Runtime client for generation or guardrails."""
    return boto3.client("bedrock-runtime", region_name=region or settings.aws_region, config=_BOTO_CONFIG)


def dynamodb_table(settings: Settings):
    return boto3.resource("dynamodb", region_name=settings.aws_region, config=_BOTO_CONFIG).Table(
        settings.sessions_table
    )


def s3_client(settings: Settings):
    return boto3.client("s3", region_name=settings.aws_region, config=_BOTO_CONFIG)
