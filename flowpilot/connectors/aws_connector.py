"""AWS connector — S3, Lambda, SQS."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from .base import BaseConnector

logger = logging.getLogger(__name__)


class AWSConnector(BaseConnector):
    """Interact with AWS services: S3, Lambda, SQS."""

    @property
    def name(self) -> str:
        return "aws"

    def _get_client(self, service: str):
        try:
            import boto3
            return boto3.client(
                service,
                aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
                region_name=os.environ.get("AWS_REGION", "us-east-1"),
            )
        except (ImportError, Exception):
            return None

    # --- S3 ---

    def s3_list(self, config: dict, context: dict) -> dict:
        bucket = config.get("bucket", "")
        prefix = config.get("prefix", "")
        limit = config.get("limit", 20)
        client = self._get_client("s3")
        if not client:
            return {"status": "simulated", "bucket": bucket, "objects": [
                {"key": "data/report.csv", "size": 1024, "last_modified": "2025-01-01T00:00:00Z"},
                {"key": "data/summary.json", "size": 512, "last_modified": "2025-01-01T00:00:00Z"},
            ]}
        try:
            resp = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=limit)
            objects = [
                {"key": o["Key"], "size": o["Size"], "last_modified": o["LastModified"].isoformat()}
                for o in resp.get("Contents", [])
            ]
            return {"status": "success", "bucket": bucket, "objects": objects}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def s3_upload(self, config: dict, context: dict) -> dict:
        bucket = config.get("bucket", "")
        key = config.get("key", "")
        body = config.get("body", context.get("data", ""))
        client = self._get_client("s3")
        if not client:
            return {"status": "simulated", "bucket": bucket, "key": key, "message": "Upload simulated"}
        try:
            client.put_object(Bucket=bucket, Key=key, Body=body.encode() if isinstance(body, str) else body)
            return {"status": "success", "bucket": bucket, "key": key}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def s3_download(self, config: dict, context: dict) -> dict:
        bucket = config.get("bucket", "")
        key = config.get("key", "")
        client = self._get_client("s3")
        if not client:
            return {"status": "simulated", "bucket": bucket, "key": key, "content": "<simulated file content>"}
        try:
            resp = client.get_object(Bucket=bucket, Key=key)
            content = resp["Body"].read().decode("utf-8", errors="replace")
            return {"status": "success", "bucket": bucket, "key": key, "content": content[:10000]}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # --- Lambda ---

    def lambda_invoke(self, config: dict, context: dict) -> dict:
        function_name = config.get("function_name", "")
        payload = config.get("payload", context.get("payload", {}))
        client = self._get_client("lambda")
        if not client:
            return {"status": "simulated", "function": function_name, "response": {"result": "simulated"}}
        try:
            resp = client.invoke(
                FunctionName=function_name,
                InvocationType=config.get("invocation_type", "RequestResponse"),
                Payload=json.dumps(payload),
            )
            result = json.loads(resp["Payload"].read().decode())
            return {"status": "success", "function": function_name, "status_code": resp["StatusCode"], "response": result}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # --- SQS ---

    def sqs_send(self, config: dict, context: dict) -> dict:
        queue_url = config.get("queue_url", "")
        message = config.get("message", context.get("message", ""))
        if isinstance(message, dict):
            message = json.dumps(message)
        client = self._get_client("sqs")
        if not client:
            return {"status": "simulated", "queue_url": queue_url, "message_id": "sim_msg_123"}
        try:
            resp = client.send_message(QueueUrl=queue_url, MessageBody=message)
            return {"status": "success", "message_id": resp["MessageId"]}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def sqs_receive(self, config: dict, context: dict) -> dict:
        queue_url = config.get("queue_url", "")
        max_messages = config.get("max_messages", 1)
        client = self._get_client("sqs")
        if not client:
            return {"status": "simulated", "messages": [{"id": "sim_1", "body": "Simulated message"}]}
        try:
            resp = client.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=max_messages, WaitTimeSeconds=5)
            messages = [
                {"id": m["MessageId"], "body": m["Body"], "receipt_handle": m["ReceiptHandle"]}
                for m in resp.get("Messages", [])
            ]
            return {"status": "success", "messages": messages}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def validate_config(self, action: str, config: dict) -> list[str]:
        errors = []
        if action in ("s3_list", "s3_upload", "s3_download") and not config.get("bucket"):
            errors.append("'bucket' required")
        if action in ("s3_upload", "s3_download") and not config.get("key"):
            errors.append("'key' required")
        if action == "lambda_invoke" and not config.get("function_name"):
            errors.append("'function_name' required")
        if action in ("sqs_send", "sqs_receive") and not config.get("queue_url"):
            errors.append("'queue_url' required")
        return errors
