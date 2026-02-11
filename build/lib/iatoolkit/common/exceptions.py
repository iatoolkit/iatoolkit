# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from enum import Enum


class IAToolkitException(Exception):

    class ErrorType(Enum):
        SYSTEM_ERROR = 0
        DATABASE_ERROR = 1
        LLM_ERROR = 2
        CLOUD_STORAGE_ERROR = 3
        DOCUMENT_NOT_FOUND = 4
        INVALID_PARAMETER = 5
        MISSING_PARAMETER = 6
        PARAM_NOT_FILLED = 7
        PERMISSION = 8
        EXIST = 9
        API_KEY = 10
        CALL_ERROR = 11
        PROMPT_ERROR = 12
        FILE_FORMAT_ERROR = 13
        FILE_IO_ERROR = 14
        TEMPLATE_ERROR = 15
        EXTERNAL_SOURCE_ERROR = 16
        MAIL_ERROR = 17
        CONFIG_ERROR = 18
        INVALID_NAME = 19
        REQUEST_ERROR = 20
        TASK_EXECUTION_ERROR = 21
        TASK_NOT_FOUND = 22
        INVALID_STATE = 23
        CRYPT_ERROR = 24
        LOAD_DOCUMENT_ERROR = 25
        INVALID_USER = 26
        VECTOR_STORE_ERROR = 27
        EMBEDDING_ERROR = 28
        MODEL = 29



    def __init__(self, error_type: ErrorType = ErrorType.SYSTEM_ERROR, message=None):
        self.error_type = error_type
        self.message = message
        super().__init__(self.message)
