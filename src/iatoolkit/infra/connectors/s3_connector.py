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