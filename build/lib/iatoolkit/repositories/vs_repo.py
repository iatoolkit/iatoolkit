# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import logging
import re
from typing import Dict

from sqlalchemy import text
from injector import inject

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import Company, VSDoc, VSImage
from iatoolkit.services.embedding_service import EmbeddingService
from iatoolkit.services.storage_service import StorageService


class VSRepo:
    _FILTER_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_:-]+(?:\.[A-Za-z0-9_:-]+)*$")
    _TEXT_CHUNK_HINT_KEYS = {
        "source_type",
        "source_label",
        "block_index",
        "chunk_index",
        "page",
        "page_start",
        "page_end",
        "section_title",
        "table_index",
        "image_index",
        "caption_text",
        "caption_source",
        "title_prefixed",
    }
    _IMAGE_META_HINT_KEYS = {
        "source_type",
        "page",
        "image_index",
        "caption_text",
        "caption_source",
        "width",
        "height",
        "format",
        "mime_type",
        "color_mode",
    }

    @inject
    def __init__(self,
                 db_manager: DatabaseManager,
                 embedding_service: EmbeddingService,
                 storage_service: StorageService,):
        self.session = db_manager.get_session()
        self.embedding_service = embedding_service
        self.storage_service = storage_service

    def add_document(self, company_short_name, vs_chunk_list: list[VSDoc]):
        try:
            for doc in vs_chunk_list:
                # calculate the embedding for the text
                doc.embedding = self.embedding_service.embed_text(company_short_name, doc.text)
                self.session.add(doc)
            self.session.commit()
        except Exception as e:
            logging.error(f"Error while inserting embedding chunk list: {str(e)}")
            self.session.rollback()
            raise IAToolkitException(IAToolkitException.ErrorType.VECTOR_STORE_ERROR,
                               f"Error while inserting embedding chunk list: {str(e)}")

    def add_image(self, vs_image: VSImage):
        """Adds a VSImage record to the database."""
        try:
            self.session.add(vs_image)
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            raise e

    def query(self,
              company_short_name: str,
              query_text: str,
              n_results=5,
              metadata_filter=None,
              collection_id: int = None
              ) -> list[Dict]:
        """
        search documents similar to the query for a company

        Args:
            company_short_name: The company's unique short name.
            query_text: query text
            n_results: max number of results to return
            metadata_filter:  (e.g., {"document_type": "certificate"})

        Returns:
            list of documents matching the query and filters
        """
        # Generate the embedding with the query text for the specific company
        try:
            query_embedding = self.embedding_service.embed_text(company_short_name, query_text)
        except Exception as e:
            logging.error(f"error while creating text embedding: {str(e)}")
            raise IAToolkitException(IAToolkitException.ErrorType.EMBEDDING_ERROR,
                               f"embedding error: {str(e)}")

        sql_query, params = None, None
        try:
            # Get company ID from its short name for the SQL query
            company = self.session.query(Company).filter(Company.short_name == company_short_name).one_or_none()
            if not company:
                raise IAToolkitException(IAToolkitException.ErrorType.VECTOR_STORE_ERROR,
                                   f"Company with short name '{company_short_name}' not found.")

            # build the SQL query
            sql_query_parts = ["""
                               SELECT iat_vsdocs.id, \
                                      iat_documents.filename, \
                                      iat_vsdocs.text, \
                                      iat_documents.storage_key, \
                                      iat_documents.meta,
                                      iat_documents.id, \
                                      iat_vsdocs.meta
                               FROM iat_vsdocs, \
                                    iat_documents
                               WHERE iat_vsdocs.company_id = :company_id
                                 AND iat_vsdocs.document_id = iat_documents.id \
                               """]

            # query parameters
            params = {
                "company_id": company.id,
                "query_embedding": query_embedding,
                "n_results": n_results
            }

            # Filter by Collection ID
            if collection_id:
                sql_query_parts.append(" AND iat_documents.collection_type_id = :collection_id")
                params['collection_id'] = collection_id

            metadata_sql, metadata_params = self._build_metadata_filter_sql(
                metadata_filter=metadata_filter,
                mode="text",
                target_columns={
                    "doc": "iat_documents.meta",
                    "chunk": "iat_vsdocs.meta",
                },
            )
            sql_query_parts.extend(metadata_sql)
            params.update(metadata_params)

            # join all the query parts
            sql_query = "".join(sql_query_parts)

            # add sorting and limit of results
            sql_query += " ORDER BY embedding <-> CAST(:query_embedding AS VECTOR) LIMIT :n_results"

            logging.debug(f"Executing SQL query: {sql_query}")
            logging.debug(f"With parameters: {params}")

            # execute the query
            result = self.session.execute(text(sql_query), params)

            rows = result.fetchall()
            vs_documents = []

            for row in rows:
                # create the document object with the data
                doc_meta = row[4] if len(row) > 4 and row[4] is not None else {}
                chunk_meta = row[6] if len(row) > 6 and row[6] is not None else {}

                # get the url of the document
                storage_key = row[3] if len(row) > 3 and row[3] is not None else None
                url = None
                if storage_key:
                    url = self.storage_service.generate_presigned_url(company_short_name, storage_key)

                vs_documents.append(
                    {
                        'id': row[0],
                        'document_id': row[5],
                        'filename': row[1],
                        'text': row[2],
                        'meta': doc_meta,
                        'chunk_meta': chunk_meta,
                        'url': url
                    }
                )

            return vs_documents

        except Exception as e:
            logging.error(f"Error en la consulta de documentos: {str(e)}")
            logging.error(f"Failed SQL: {sql_query}")
            logging.error(f"Failed params: {params}")
            try:
                self.session.rollback()
            except Exception as rollback_error:
                logging.warning(f"VSRepo.query rollback failed: {rollback_error}")
            raise IAToolkitException(IAToolkitException.ErrorType.VECTOR_STORE_ERROR,
                               f"Error en la consulta: {str(e)}")
        finally:
            self.session.close()

    def query_images(self,
                     company_short_name: str,
                     query_text: str,
                     n_results: int = 5,
                     collection_id: int = None,
                     metadata_filter: dict | None = None) -> list[Dict]:
        """
        Searches for images semantically similar to the query text.
        """
        try:
            # 1. Generate Query Vector (Text -> Visual Space)
            query_embedding = self.embedding_service.embed_text(company_short_name, query_text, model_type='image')

            # 2. Delegate to internal vector search
            return self._query_images_by_vector(
                company_short_name=company_short_name,
                query_vector=query_embedding,
                n_results=n_results,
                collection_id=collection_id,
                metadata_filter=metadata_filter,
            )

        except Exception as e:
            logging.error(f"Error querying images by text: {e}")
            raise IAToolkitException(IAToolkitException.ErrorType.VECTOR_STORE_ERROR, str(e))

    def query_images_by_image(self,
                              company_short_name: str,
                              image_bytes: bytes,
                              n_results: int = 5,
                              collection_id: int = None,
                              metadata_filter: dict | None = None) -> list[Dict]:
        """
        Searches for images visually similar to the query image.
        """
        try:
            # 1. Generate Query Vector (Image -> Visual Space)
            query_embedding = self.embedding_service.embed_image(
                company_short_name=company_short_name,
                presigned_url=None,
                image_bytes=image_bytes)

            # 2. Delegate to internal vector search
            return self._query_images_by_vector(
                company_short_name=company_short_name,
                query_vector=query_embedding,
                n_results=n_results,
                collection_id=collection_id,
                metadata_filter=metadata_filter,
            )

        except Exception as e:
            logging.error(f"Error querying images by image: {e}")
            raise IAToolkitException(IAToolkitException.ErrorType.VECTOR_STORE_ERROR, str(e))

    def _query_images_by_vector(self,
                                company_short_name: str,
                                query_vector: list,
                                n_results: int,
                                collection_id: int = None,
                                metadata_filter: dict | None = None) -> list[Dict]:
        """
        Internal method to execute the SQL vector search.
        """
        try:
            company = self.session.query(Company).filter(Company.short_name == company_short_name).one_or_none()
            if not company:
                return []

            sql = """
                  SELECT
                      doc.id,
                      doc.filename,
                      doc.storage_key,
                      img_ref.id,
                      img_ref.storage_key,
                      img_ref.meta,
                      img_ref.page,
                      img_ref.image_index,
                      doc.meta,
                      (img.embedding <=> CAST(:query_embedding AS VECTOR)) as distance
                  FROM iat_vsimages img
                           JOIN iat_document_images img_ref ON img.document_image_id = img_ref.id
                           JOIN iat_documents doc ON img_ref.document_id = doc.id
                  WHERE img.company_id = :company_id
                  """

            params = {
                "company_id": company.id,
                "query_embedding": query_vector,
                "n_results": n_results
            }

            if collection_id:
                sql += " AND doc.collection_type_id = :collection_id"
                params["collection_id"] = collection_id

            metadata_sql, metadata_params = self._build_metadata_filter_sql(
                metadata_filter=metadata_filter,
                mode="image",
                target_columns={
                    "doc": "doc.meta",
                    "image": "img_ref.meta",
                },
            )
            sql += "".join(metadata_sql)
            params.update(metadata_params)

            sql += " ORDER BY distance ASC LIMIT :n_results"

            result = self.session.execute(text(sql), params)
            rows = result.fetchall()

            image_results = []
            for row in rows:
                score = 1 - row[9]
                image_results.append({
                    'document_id': row[0],
                    'filename': row[1],
                    'document_storage_key': row[2],
                    'document_image_id': row[3],
                    'storage_key': row[4],
                    'meta': row[5] or {},
                    'page': row[6],
                    'image_index': row[7],
                    'document_meta': row[8] or {},
                    'score': score
                })

            return image_results
        except Exception as e:
            try:
                self.session.rollback()
            except Exception as rollback_error:
                logging.warning(f"VSRepo._query_images_by_vector rollback failed: {rollback_error}")
            raise e

    def _build_metadata_filter_sql(self,
                                   metadata_filter,
                                   mode: str,
                                   target_columns: dict[str, str]) -> tuple[list[str], dict]:
        metadata_filter = self._normalize_metadata_filter_input(metadata_filter)
        if metadata_filter is None:
            return [], {}

        sql_parts = []
        params = {}

        for index, (raw_key, raw_value) in enumerate(metadata_filter.items()):
            target, path = self._resolve_metadata_target_and_path(raw_key, mode)
            column = target_columns.get(target)
            if not column:
                raise ValueError(f"Unsupported metadata filter target '{target}' for mode '{mode}'")

            expr = self._build_json_extract_expression(
                column_expression=column,
                path=path,
                params=params,
                key_param_prefix=f"mf_{mode}_{index}",
            )

            if raw_value is None:
                sql_parts.append(f" AND {expr} IS NULL")
                continue

            value_param = f"mf_{mode}_{index}_value"
            params[value_param] = self._normalize_filter_value(raw_value, raw_key)
            sql_parts.append(f" AND {expr} = :{value_param}")

        return sql_parts, params

    @staticmethod
    def _normalize_metadata_filter_input(metadata_filter):
        if metadata_filter is None:
            return None

        if isinstance(metadata_filter, dict):
            return metadata_filter

        if isinstance(metadata_filter, list):
            normalized = {}
            for index, item in enumerate(metadata_filter):
                if not isinstance(item, dict):
                    raise ValueError(f"metadata_filter[{index}] must be an object with key/value")
                if "key" not in item:
                    raise ValueError(f"metadata_filter[{index}] is missing 'key'")
                key = item.get("key")
                value = item.get("value")
                normalized[key] = value
            return normalized

        raise ValueError("metadata_filter must be a dictionary or a list of {key, value}")

    def _resolve_metadata_target_and_path(self, raw_key: str, mode: str) -> tuple[str, list[str]]:
        if not isinstance(raw_key, str):
            raise ValueError("metadata_filter keys must be strings")

        key = raw_key.strip()
        if not key:
            raise ValueError("metadata_filter keys cannot be empty")

        if not self._FILTER_KEY_PATTERN.match(key):
            raise ValueError(f"Invalid metadata_filter key '{raw_key}'")

        lowered = key.lower()
        key_prefix, _, remainder = key.partition(".")
        prefix = key_prefix.lower()

        if prefix in {"doc", "document"} and remainder:
            return "doc", self._split_filter_key_path(remainder)

        if prefix in {"chunk", "vsdoc"} and remainder:
            if mode != "text":
                raise ValueError(f"metadata_filter key '{raw_key}' is not valid for image search")
            return "chunk", self._split_filter_key_path(remainder)

        if prefix in {"image", "img"} and remainder:
            if mode != "image":
                raise ValueError(f"metadata_filter key '{raw_key}' is not valid for text search")
            return "image", self._split_filter_key_path(remainder)

        if mode == "text" and lowered in self._TEXT_CHUNK_HINT_KEYS:
            return "chunk", self._split_filter_key_path(key)

        if mode == "image" and lowered in self._IMAGE_META_HINT_KEYS:
            return "image", self._split_filter_key_path(key)

        return "doc", self._split_filter_key_path(key)

    @staticmethod
    def _split_filter_key_path(key: str) -> list[str]:
        segments = [segment.strip() for segment in key.split(".")]
        if not segments or any(not segment for segment in segments):
            raise ValueError(f"Invalid metadata filter key path '{key}'")
        return segments

    @staticmethod
    def _build_json_extract_expression(column_expression: str,
                                       path: list[str],
                                       params: dict,
                                       key_param_prefix: str) -> str:
        placeholders = []
        for index, key_part in enumerate(path):
            key_param = f"{key_param_prefix}_key_{index}"
            params[key_param] = key_part
            placeholders.append(f":{key_param}")

        # `meta` can be stored as JSON or JSONB depending on deployment/migration history.
        # Cast to jsonb to keep a single extraction function working across both schemas.
        return f"jsonb_extract_path_text(CAST({column_expression} AS jsonb), {', '.join(placeholders)})"

    @staticmethod
    def _normalize_filter_value(value, key: str) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"

        if isinstance(value, (str, int, float)):
            return str(value)

        raise ValueError(
            f"metadata_filter value for key '{key}' must be scalar (str/int/float/bool/null)"
        )
