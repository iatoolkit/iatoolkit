# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from sqlalchemy import  text
from injector import inject
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.services.embedding_service import EmbeddingService
from iatoolkit.repositories.models import Document, VSDoc, Company
import logging


class VSRepo:
    @inject
    def __init__(self,
                 db_manager: DatabaseManager,
                 embedding_service: EmbeddingService):
        self.session = db_manager.get_session()
        self.embedding_service = embedding_service


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

    def query(self,
              company_short_name: str,
              query_text: str,
              n_results=5,
              metadata_filter=None
              ) -> list[Document]:
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
                "company_id": company.id,
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
            sql_query += " ORDER BY embedding <-> CAST(:query_embedding AS VECTOR) LIMIT :n_results"

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
                    company_id=company.id,
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
