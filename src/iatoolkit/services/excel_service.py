# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import current_app, jsonify
from iatoolkit.common.util import Utility
import pandas as pd
from uuid import uuid4
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.storage_service import StorageService
from injector import inject
import os
import io
import logging
import json

EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ExcelService:
    @inject
    def __init__(self,
                 util: Utility,
                 i18n_service: I18nService,
                 storage_service: StorageService):
        self.util = util
        self.i18n_service = i18n_service
        self.storage_service = storage_service

    def read_excel(self, file_content: bytes) -> str:
        """
        Reads an Excel file and converts its content to a JSON string.
        - If the Excel file has a single sheet, it returns the JSON of that sheet.
        - If it has multiple sheets, it returns a JSON object with sheet names as keys.
        """
        try:
            # Use a BytesIO object to allow pandas to read the in-memory byte content
            file_like_object = io.BytesIO(file_content)

            # Read all sheets into a dictionary of DataFrames
            xls = pd.read_excel(file_like_object, sheet_name=None)

            if len(xls) == 1:
                # If only one sheet, return its JSON representation directly
                sheet_name = list(xls.keys())[0]
                return xls[sheet_name].to_json(orient='records', indent=4)
            else:
                # If multiple sheets, create a dictionary of JSON strings
                sheets_json = {}
                for sheet_name, df in xls.items():
                    sheets_json[sheet_name] = df.to_json(orient='records', indent=4)
                return json.dumps(sheets_json, indent=4)

        except Exception as e:
            raise IAToolkitException(IAToolkitException.ErrorType.FILE_FORMAT_ERROR,
                                     self.i18n_service.t('errors.services.cannot_read_excel')) from e

    def read_csv(self, file_content: bytes) -> str:
        """
        Reads a CSV file and converts its content to a JSON string.
        """
        try:
            # Use a BytesIO object to allow pandas to read the in-memory byte content
            file_like_object = io.BytesIO(file_content)

            # Read the CSV into a DataFrame
            df = pd.read_csv(file_like_object)

            # Return JSON representation
            return df.to_json(orient='records', indent=4)

        except Exception as e:
            raise IAToolkitException(IAToolkitException.ErrorType.FILE_FORMAT_ERROR,
                                     self.i18n_service.t('errors.services.cannot_read_csv')) from e

    def excel_generator(self, company_short_name: str, **kwargs) -> str:
        """
        Genera un Excel a partir de una lista de diccionarios.

        Parámetros esperados en kwargs:
          - filename: str (nombre lógico a mostrar, ej. "reporte_clientes.xlsx") [obligatorio]
          - data: list[dict] (filas del excel) [obligatorio]
          - sheet_name: str = "hoja 1"

        Retorna:
             {
                "filename": "reporte.xlsx",
                "attachment_token": "signed-token",
                "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "download_link": "/download/<signed-token>"
                }
        """
        try:
            # get the parameters
            fname = kwargs.get('filename')
            if not fname:
                return self.i18n_service.t('errors.services.no_output_file')

            data = kwargs.get('data')
            if not data or not isinstance(data, list):
                return self.i18n_service.t('errors.services.no_data_for_excel')

            sheet_name = kwargs.get('sheet_name', 'hoja 1')

            # 1. convert dictionary to dataframe
            df = pd.DataFrame(data)

            # 3. create a unique physical filename for storage
            storage_filename = f"{uuid4()}.xlsx"

            # 4. render the Excel file to bytes
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name=sheet_name)
            excel_bytes = output.getvalue()

            # 5. upload to storage
            storage_key = self.storage_service.upload_generated_download(
                company_short_name=company_short_name,
                file_content=excel_bytes,
                filename=storage_filename,
                mime_type=EXCEL_MIME
            )

            # 6. build a signed token used by both download endpoint and mail attachments
            attachment_token = self.storage_service.create_download_token(
                company_short_name=company_short_name,
                storage_key=storage_key,
                filename=fname
            )

            # 7. return the link + token to the LLM
            return {
                "filename": fname,
                "attachment_token": attachment_token,
                "content_type": EXCEL_MIME,
                "download_link": f"/download/{attachment_token}"
                }

        except Exception as e:
            raise IAToolkitException(IAToolkitException.ErrorType.CALL_ERROR,
                               self.i18n_service.t('errors.services.cannot_create_excel')) from e

    def validate_file_access(self, filename):
        try:
            if not filename:
                return jsonify({"error": self.i18n_service.t('errors.services.invalid_filename')})
            # Prevent path traversal attacks
            if '..' in filename or filename.startswith('/') or '\\' in filename:
                return jsonify({"error": self.i18n_service.t('errors.services.invalid_filename')})

            temp_dir = os.path.join(current_app.root_path, 'static', 'temp')
            file_path = os.path.join(temp_dir, filename)

            if not os.path.exists(file_path):
                return jsonify({"error": self.i18n_service.t('errors.services.file_not_exist')})

            if not os.path.isfile(file_path):
                return jsonify({"error": self.i18n_service.t('errors.services.path_is_not_a_file')})

            return None

        except Exception as e:
            error_msg = f"File validation error {filename}: {str(e)}"
            logging.error(error_msg)
            return jsonify({"error": self.i18n_service.t('errors.services.file_validation_error')})
