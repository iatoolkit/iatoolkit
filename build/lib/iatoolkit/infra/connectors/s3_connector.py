# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import boto3
from iatoolkit.infra.connectors.file_connector import FileConnector
from typing import List


class S3Connector(FileConnector):
    def __init__(self, bucket: str, prefix: str, folder: str, auth: dict):
        self.bucket = bucket
        self.prefix = prefix
        self.folder = folder
        self.s3 = boto3.client('s3', **auth)

    def list_files(self) -> List[dict]:
        # list all the files as dictionaries, with keys:  'path', 'name' y 'metadata'.
        prefix = f'{self.prefix}/{self.folder}/'
        response = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        files = response.get('Contents', [])

        return [
            {
                "path": obj['Key'],  # s3 key
                "name": obj['Key'].split('/')[-1],  # filename
                "metadata": {"size": obj.get('Size'), "last_modified": obj.get('LastModified')}
            }
            for obj in files
        ]

    def get_file_content(self, file_path: str) -> bytes:
        response = self.s3.get_object(Bucket=self.bucket, Key=file_path)
        return response['Body'].read()

    def delete_file(self, file_path: str) -> None:
        self.s3.delete_object(Bucket=self.bucket, Key=file_path)

    def upload_file(self, file_path: str, content: bytes, content_type: str = None) -> None:
        # If the path doesn't start with the prefix, add it (optional, depends on your logic)'
        # Assuming file_path is either a full path or relative to the root of the bucket for flexibility
        full_path = file_path

        extra_args = {}
        if content_type:
            extra_args['ContentType'] = content_type

        self.s3.put_object(
            Bucket=self.bucket,
            Key=full_path,
            Body=content,
            **extra_args
        )

    def generate_presigned_url(self, file_path: str, expiration: int = 3600) -> str:
        return self.s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': self.bucket, 'Key': file_path},
            ExpiresIn=expiration
        )