# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from sqlalchemy import  text
from huggingface_hub import InferenceClient
from injector import inject
from common.exceptions import IAToolkitException
from repositories.database_manager import DatabaseManager
from repositories.models import Document, VSDoc
import os
import logging

class VSRepo:
    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.session = db_manager.get_session()

        # Inicializar el modelo de embeddings
        self.embedder = InferenceClient(
            model="sentence-transformers/all-MiniLM-L6-v2",
            token=os.getenv('HF_TOKEN'))


    def add_document(self, vs_chunk_list: list[VSDoc]):
        try:
            for doc in vs_chunk_list:
                # calculate the embedding for the text
                doc.embedding = self.embedder.feature_extraction(doc.text)
                self.session.add(doc)
            self.session.commit()
        except Exception as e:
            logging.error(f"Error insertando documentos en PostgreSQL: {str(e)}")
            self.session.rollback()
            raise IAToolkitException(IAToolkitException.ErrorType.VECTOR_STORE_ERROR,
                               f"Error insertando documentos en PostgreSQL: {str(e)}")

    def query(self,
              company_id: int,
              query_text: str,
              n_results=5,
              metadata_filter=None
              ) -> list[Document]:
        """
        search documents similar to the query for a company

        Args:
            company_id:
            query_text: query text
            n_results: max number of results to return
            metadata_filter:  (ej: {"document_type": "certificate"})

        Returns:
            list of documents matching the query and filters
        """
        # Generate the embedding with the query text
        query_embedding = self.embedder.feature_extraction([query_text])[0]

        try:
            # build the SQL query
            sql_query_parts = ["""
                               SELECT iat_documents.id, \
                                      iat_documents.filename, \
                                      iat_documents.content, \
                                      iat_documents.content_b64, \
                                      iat_documents.meta
                               FROM iat_vsdocs, \
                                    iat_documents
                               WHERE iat_vsdocs.company_id = :company_id
                                 AND iat_vsdocs.document_id = iat_documents.id \
                               """]

            # query parameters
            params = {
                "company_id": company_id,
                "query_embedding": query_embedding,
                "n_results": n_results
            }

            # add metadata filter, if exists
            if metadata_filter and isinstance(metadata_filter, dict):
                for key, value in metadata_filter.items():
                    # Usar el operador ->> para extraer el valor del JSON como texto.
                    # La clave del JSON se interpola directamente.
                    # El valor se pasa como parámetro para evitar inyección SQL.
                    param_name = f"value_{key}_filter"
                    sql_query_parts.append(f" AND documents.meta->>'{key}' = :{param_name}")
                    params[param_name] = str(value)     # parametros como string

            # join all the query parts
            sql_query = "".join(sql_query_parts)

            # add sorting and limit of results
            sql_query += " ORDER BY embedding <-> :query_embedding LIMIT :n_results"

            logging.debug(f"Executing SQL query: {sql_query}")
            logging.debug(f"With parameters: {params}")

            # execute the query
            result = self.session.execute(text(sql_query), params)

            rows = result.fetchall()
            vs_documents = []

            for row in rows:
                # create the document object with the data
                meta_data = row[4] if len(row) > 4 and row[4] is not None else {}
                doc = Document(
                    id=row[0],
                    company_id=company_id,
                    filename=row[1],
                    content=row[2],
                    content_b64=row[3],
                    meta=meta_data
                )
                vs_documents.append(doc)

            return self.remove_duplicates_by_id(vs_documents)

        except Exception as e:
            logging.error(f"Error en la consulta de documentos: {str(e)}")
            logging.error(f"Failed SQL: {sql_query}")
            logging.error(f"Failed params: {params}")
            raise IAToolkitException(IAToolkitException.ErrorType.VECTOR_STORE_ERROR,
                               f"Error en la consulta: {str(e)}")
        finally:
            self.session.close()

    def remove_duplicates_by_id(self, objects):
        unique_by_id = {}
        result = []

        for obj in objects:
            if obj.id not in unique_by_id:
                unique_by_id[obj.id] = True
                result.append(obj)

        return result
