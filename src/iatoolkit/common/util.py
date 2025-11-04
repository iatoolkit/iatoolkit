# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import logging
from typing import List
from iatoolkit.common.exceptions import IAToolkitException
from injector import inject
import os
from jinja2 import Environment, FileSystemLoader
from datetime import datetime, date
from decimal import Decimal
import yaml
from cryptography.fernet import Fernet
import base64


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


    def serialize(self, obj):
        if isinstance(obj, datetime) or isinstance(obj, date):
            return obj.isoformat()
        elif isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, bytes):
            return obj.decode('utf-8')
        else:
            raise TypeError(f"Type {type(obj)} not serializable")

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

    def generate_context_for_schema(self, entity_name: str, schema_file: str = None, schema: dict = {}) -> str:
        if not schema_file and not schema:
            raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR,
                               f'No se pudo obtener schema de la entidad: {entity_name}')

        try:
            if schema_file:
                schema = self.load_schema_from_yaml(schema_file)
            table_schema = self.generate_schema_table(schema)
            return table_schema
        except Exception as e:
            logging.exception(e)
            raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR,
                               f'No se pudo leer el schema de la entidad: {entity_name}') from e

    def generate_schema_table(self, schema: dict) -> str:
        """
        Genera una descripción detallada y formateada en Markdown de un esquema.
        Esta función está diseñada para manejar el formato específico de nuestros
        archivos YAML, donde el esquema se define bajo una única clave raíz.
        """
        if not schema or not isinstance(schema, dict):
            return ""

        # Asumimos que el YAML tiene una única clave raíz que nombra a la entidad.
        if len(schema) == 1:
            root_name = list(schema.keys())[0]
            root_details = schema[root_name]

            if isinstance(root_details, dict):
                # Las claves de metadatos describen el objeto en sí, no sus propiedades hijas.
                METADATA_KEYS = ['description', 'type', 'format', 'items', 'properties']

                # Las propiedades son las claves restantes en el diccionario.
                properties = {
                    k: v for k, v in root_details.items() if k not in METADATA_KEYS
                }

                # La descripción del objeto raíz.
                root_description = root_details.get('description', '')

                # Formatea las propiedades extraídas usando la función auxiliar recursiva.
                formatted_properties = self._format_json_schema(properties, 0)

                # Construcción del resultado final, incluyendo el nombre del objeto raíz.
                output_parts = [f"\n\n### Objeto: `{root_name}`"]
                if root_description:
                    # Limpia la descripción para que se muestre bien
                    cleaned_description = '\n'.join(line.strip() for line in root_description.strip().split('\n'))
                    output_parts.append(f"{cleaned_description}")

                if formatted_properties:
                    output_parts.append(f"**Campos del objeto `{root_name}`:**\n{formatted_properties}")

                return "\n".join(output_parts)

        # Si el esquema (como tender_schema.yaml) no tiene un objeto raíz,
        # se formatea directamente como una lista de propiedades.
        return self._format_json_schema(schema, 0)

    def _format_json_schema(self, properties: dict, indent_level: int) -> str:
        """
        Formatea de manera recursiva las propiedades de un esquema JSON/YAML.
        """
        output = []
        indent_str = '  ' * indent_level

        for name, details in properties.items():
            if not isinstance(details, dict):
                continue

            description = details.get('description', '')
            data_type = details.get('type', 'any')
            output.append(f"{indent_str}- **`{name.lower()}`** ({data_type}): {description}")

            child_indent_str = '  ' * (indent_level + 1)

            # Manejo de 'oneOf' para mostrar valores constantes
            if 'oneOf' in details:
                for item in details['oneOf']:
                    if 'const' in item:
                        const_desc = item.get('description', '')
                        output.append(f"{child_indent_str}- `{item['const']}`: {const_desc}")

            # Manejo de 'items' para arrays
            if 'items' in details:
                items_details = details.get('items', {})
                if isinstance(items_details, dict):
                    item_description = items_details.get('description')
                    if item_description:
                        # Limpiamos y añadimos la descripción del item
                        cleaned_description = '\n'.join(
                            f"{line.strip()}" for line in item_description.strip().split('\n')
                        )
                        output.append(
                            f"{child_indent_str}*Descripción de los elementos del array:*\n{child_indent_str}{cleaned_description}")

                    if 'properties' in items_details:
                        nested_properties = self._format_json_schema(items_details['properties'], indent_level + 1)
                        output.append(nested_properties)

            # Manejo de 'properties' para objetos anidados estándar
            if 'properties' in details:
                nested_properties = self._format_json_schema(details['properties'], indent_level + 1)
                output.append(nested_properties)

            elif 'additionalProperties' in details and 'properties' in details.get('additionalProperties', {}):
                # Imprime un marcador de posición para la clave dinámica.
                output.append(
                    f"{child_indent_str}- **[*]** (object): Las claves de este objeto son dinámicas (ej. un ID).")
                # Procesa las propiedades del objeto anidado.
                nested_properties = self._format_json_schema(details['additionalProperties']['properties'],
                                                             indent_level + 2)
                output.append(nested_properties)

        return '\n'.join(output)

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

    def is_openai_model(self, model: str) -> bool:
        openai_models = [
            'gpt-5', 'gpt'
        ]
        return any(openai_model in model.lower() for openai_model in openai_models)

    def is_gemini_model(self, model: str) -> bool:
        gemini_models = [
            'gemini', 'gemini-2.5-pro'
        ]
        return any(gemini_model in model.lower() for gemini_model in gemini_models)