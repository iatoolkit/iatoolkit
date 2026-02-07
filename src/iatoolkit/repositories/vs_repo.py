# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from sqlalchemy import  text
from injector import inject
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.services.embedding_service import EmbeddingService
from iatoolkit.services.storage_service import StorageService
from iatoolkit.repositories.models import Document, VSDoc, Company, VSImage
from typing import Dict
import logging


class VSRepo:
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

                # add metadata filter, if exists
                if metadata_filter and isinstance(metadata_filter, dict):
                    for key, value in metadata_filter.items():
                        # FIX: Lógica híbrida.
                        # 1. Si la key es específica de estructura (ej: page, block_type), buscamos en vsdocs.meta
                        # 2. Si no, asumimos que es del documento global (ej: category, user) o buscamos en ambos.

                        param_name = f"value_{key}_filter"

                        # Lista de keys que sabemos que viven en el chunk (generados por docling)
                        chunk_keys = ['page_start', 'page_end', 'block_type', 'section_title', 'table_index', 'image_index']

                        if key in chunk_keys:
                            # Filtro a nivel de Chunk
                            sql_query_parts.append(f" AND iat_vsdocs.meta->>'{key}' = :{param_name}")
                        else:
                            # Filtro a nivel de Documento (comportamiento original)
                            # Opcional: podrías usar OR para buscar en ambos lados si no estás seguro
                            sql_query_parts.append(f" AND iat_documents.meta->>'{key}' = :{param_name}")

                        params[param_name] = str(value)

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
            raise IAToolkitException(IAToolkitException.ErrorType.VECTOR_STORE_ERROR,
                               f"Error en la consulta: {str(e)}")
        finally:
            self.session.close()

    def query_images(self, company_short_name: str, query_text: str, n_results: int = 5, collection_id: int = None) -> list[Dict]:
        """
        Searches for images semantically similar to the query text.
        """
        try:
            # 1. Generate Query Vector (Text -> Visual Space)
            query_embedding = self.embedding_service.embed_text(company_short_name, query_text, model_type='image')

            # 2. Delegate to internal vector search
            return self._query_images_by_vector(company_short_name, query_embedding, n_results, collection_id)

        except Exception as e:
            logging.error(f"Error querying images by text: {e}")
            raise IAToolkitException(IAToolkitException.ErrorType.VECTOR_STORE_ERROR, str(e))

    def query_images_by_image(self,
                              company_short_name: str,
                              image_bytes: bytes,
                              n_results: int = 5,
                              collection_id: int = None) -> list[Dict]:
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
            return self._query_images_by_vector(company_short_name, query_embedding, n_results, collection_id)

        except Exception as e:
            logging.error(f"Error querying images by image: {e}")
            raise IAToolkitException(IAToolkitException.ErrorType.VECTOR_STORE_ERROR, str(e))

    def _query_images_by_vector(self, company_short_name: str, query_vector: list, n_results: int, collection_id: int = None) -> list[Dict]:
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
                      img_ref.id,
                      img_ref.storage_key,
                      img_ref.meta,
                      img_ref.page,
                      img_ref.image_index,
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

            sql += " ORDER BY distance ASC LIMIT :n_results"

            result = self.session.execute(text(sql), params)
            rows = result.fetchall()

            image_results = []
            for row in rows:
                score = 1 - row[7]
                image_results.append({
                    'document_id': row[0],
                    'filename': row[1],
                    'document_image_id': row[2],
                    'storage_key': row[3],
                    'meta': row[4] or {},
                    'page': row[5],
                    'image_index': row[6],
                    'score': score
                })

            return image_results
        except Exception as e:
            raise e
