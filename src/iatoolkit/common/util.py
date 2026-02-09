# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import logging
from typing import List, Union
from iatoolkit.common.exceptions import IAToolkitException
from flask import request
from injector import inject
import os
from jinja2 import Environment, FileSystemLoader
from datetime import datetime, date
from decimal import Decimal
import yaml
from cryptography.fernet import Fernet
import base64
from PIL import Image
import io
import time
from functools import wraps


def measure_time(func):
    """
    Decorator to measure execution time of a function or method.
    Logs the execution time with the function name.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start_time
            func_name = func.__name__
            logging.info(f"[TIMING] {func_name} executed in {elapsed:.2f} seconds")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            func_name = func.__name__
            logging.error(f"[TIMING] {func_name} failed after {elapsed:.2f} seconds: {str(e)}")
            raise
    return wrapper


class Utility:
    @inject
    def __init__(self):
        self.encryption_key = os.getenv('FERNET_KEY')

    def render_prompt_from_template(self,
                                    template_pathname: str,
                                    client_data: dict = {},
                                    **kwargs) -> str:

        try:
            # Normalizar la ruta para que funcione en cualquier SO
            template_pathname = os.path.abspath(template_pathname)
            template_dir = os.path.dirname(template_pathname)
            template_file = os.path.basename(template_pathname)

            env = Environment(loader=FileSystemLoader(template_dir))
            template = env.get_template(template_file)

            # add all the keys in client_data to kwargs
            kwargs.update(client_data)

            # render my dynamic prompt
            prompt = template.render(**kwargs)
            return prompt
        except Exception as e:
            logging.exception(e)
            raise IAToolkitException(IAToolkitException.ErrorType.TEMPLATE_ERROR,
                               f'No se pudo renderizar el template: {template_pathname}, error: {str(e)}') from e

    def render_prompt_from_string(self,
                                  template_string: str,
                                  searchpath: str | list[str] = None,
                                  client_data: dict = {},
                                  **kwargs) -> str:
        """
        Renderiza un prompt a partir de un string de plantilla Jinja2.

        :param template_string: El string que contiene la plantilla Jinja2.
        :param searchpath: Una ruta o lista de rutas a directorios para buscar plantillas incluidas (con {% include %}).
        :param query: El query principal a pasar a la plantilla.
        :param client_data: Un diccionario con datos adicionales para la plantilla.
        :param kwargs: Argumentos adicionales para la plantilla.
        :return: El prompt renderizado como un string.
        """
        try:
            # Si se proporciona un searchpath, se usa un FileSystemLoader para permitir includes.
            if searchpath:
                loader = FileSystemLoader(searchpath)
            else:
                loader = None  # Sin loader, no se pueden incluir plantillas desde archivos.

            env = Environment(loader=loader)
            template = env.from_string(template_string)

            kwargs.update(client_data)

            prompt = template.render(**kwargs)
            return prompt
        except Exception as e:
            logging.exception(e)
            raise IAToolkitException(IAToolkitException.ErrorType.TEMPLATE_ERROR,
                               f'No se pudo renderizar el template desde el string, error: {str(e)}') from e


    def get_company_template(self, company_short_name: str, template_name: str) -> str:
        # 1. get the path to the company specific template
        template_path = os.path.join(os.getcwd(), f'companies/{company_short_name}/templates/{template_name}')
        if not os.path.exists(template_path):
            return None

        # 2. read the file
        try:
            with open(template_path, 'r') as f:
                template_string = f.read()

            return template_string
        except Exception as e:
            logging.exception(e)
            return None

    def get_template_by_language(self, template_name: str, default_lenguage: str = 'en') -> str:
        # english is default
        lang = request.args.get("lang", default_lenguage)
        return f'{template_name}_{lang}.html'

    def serialize(self, obj):
        if isinstance(obj, datetime) or isinstance(obj, date):
            return obj.isoformat()
        elif isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, bytes):
            return obj.decode('utf-8')
        else:
            raise TypeError(f"Type {type(obj)} not serializable")

    def normalize_base64_payload(self, content: Union[str, bytes]) -> bytes:
        """
        Normalizes a Base64 payload coming from:
        - plain base64 string
        - data:*/*;base64,<payload>
        - bytes (already encoded)

        Returns raw decoded bytes.
        """
        if content is None:
            return b""

        # If already bytes, assume raw file bytes
        if isinstance(content, bytes):
            return content

        if not isinstance(content, str):
            raise TypeError(f"Invalid base64 content type: {type(content)}")

        # Remove data URL header if present
        if "," in content and content.strip().lower().startswith("data:"):
            content = content.split(",", 1)[1]

        # Base64 is ASCII-safe, no need for utf-8 encode but we normalize
        return __import__("base64").b64decode(content)

    def encrypt_key(self, key: str) -> str:
        if not self.encryption_key:
            raise IAToolkitException(IAToolkitException.ErrorType.CRYPT_ERROR,
                               'No se pudo obtener variable de ambiente para encriptar')

        if not key:
            raise IAToolkitException(IAToolkitException.ErrorType.CRYPT_ERROR,
                               'falta la clave a encriptar')
        try:
            cipher_suite = Fernet(self.encryption_key.encode('utf-8'))

            encrypted_key = cipher_suite.encrypt(key.encode('utf-8'))
            encrypted_key_str = base64.urlsafe_b64encode(encrypted_key).decode('utf-8')

            return encrypted_key_str
        except Exception as e:
            raise IAToolkitException(IAToolkitException.ErrorType.CRYPT_ERROR,
                               f'No se pudo encriptar la clave: {str(e)}') from e

    def decrypt_key(self, encrypted_key: str) -> str:
        if not self.encryption_key:
            raise IAToolkitException(IAToolkitException.ErrorType.CRYPT_ERROR,
                               'No se pudo obtener variable de ambiente para desencriptar')
        if not encrypted_key:
            raise IAToolkitException(IAToolkitException.ErrorType.CRYPT_ERROR,
                               'falta la clave a encriptar')

        try:
            # transform to bytes first
            encrypted_data_from_storage_bytes = base64.urlsafe_b64decode(encrypted_key.encode('utf-8'))

            cipher_suite = Fernet(self.encryption_key.encode('utf-8'))
            decrypted_key_bytes = cipher_suite.decrypt(encrypted_data_from_storage_bytes)
            return decrypted_key_bytes.decode('utf-8')
        except Exception as e:
            raise IAToolkitException(IAToolkitException.ErrorType.CRYPT_ERROR,
                               f'No se pudo desencriptar la clave: {str(e)}') from e

    def load_schema_from_yaml(self, file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            schema = yaml.safe_load(f)
        return schema

    def load_yaml_from_string(self, yaml_content: str) -> dict:
        """
        Parses a YAML string into a dictionary securely.
        """
        try:
            if not yaml_content:
                return {}

            # Normalizar tabulaciones que rompen YAML
            yaml_content = yaml_content.replace('\t', '  ')

            loaded = yaml.safe_load(yaml_content)
            return loaded
        except yaml.YAMLError as e:
            logging.error(f"Error parsing YAML string: {e}")
            return {}

    def dump_yaml_to_string(self, config: dict) -> str:
        """
        Dumps a dictionary into a YAML formatted string.
        It uses default flow style False to ensure block format (readable YAML).
        """
        try:
            # default_flow_style=False ensures lists and dicts are expanded (not inline like JSON)
            # allow_unicode=True ensures characters like accents are preserved
            return yaml.safe_dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except yaml.YAMLError as e:
            logging.error(f"Error dumping YAML to string: {e}")
            raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR,
                                     f"Failed to generate YAML: {e}")


    def load_markdown_context(self, filepath: str) -> str:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()

    @classmethod
    def _get_verifier(self, rut: int):
        value = 11 - sum([int(a) * int(b) for a, b in zip(str(rut).zfill(8), '32765432')]) % 11
        return {10: 'K', 11: '0'}.get(value, str(value))

    def validate_rut(self, rut_str):
        if not rut_str or not isinstance(rut_str, str):
            return False

        rut_str = rut_str.strip().replace('.', '').upper()
        parts = rut_str.split('-')
        if not len(parts) == 2:
            return False

        try:
            rut = int(parts[0])
        except ValueError:
            return False

        if rut < 1000000:
            return False

        if not len(parts[1]) == 1:
            return False

        digit = parts[1].upper()
        return digit == self._get_verifier(rut)

    def get_files_by_extension(self, directory: str, extension: str, return_extension: bool = False) -> List[str]:
        try:
            # Normalizar la extensión (agregar punto si no lo tiene)
            if not extension.startswith('.'):
                extension = '.' + extension

            # Verificar que el directorio existe
            if not os.path.exists(directory):
                raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR,
                                   f'El directorio no existe: {directory}')

            if not os.path.isdir(directory):
                raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR,
                                   f'La ruta no es un directorio: {directory}')

            # Buscar archivos con la extensión especificada
            files = []
            for filename in os.listdir(directory):
                file_path = os.path.join(directory, filename)
                if os.path.isfile(file_path) and filename.endswith(extension):
                    if return_extension:
                        files.append(filename)
                    else:
                        name_without_extension = os.path.splitext(filename)[0]
                        files.append(name_without_extension)

            return sorted(files)  # Retornar lista ordenada alfabéticamente

        except IAToolkitException:
            raise
        except Exception as e:
            logging.exception(e)
            raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR,
                               f'Error al buscar archivos en el directorio {directory}: {str(e)}') from e
