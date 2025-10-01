# Copyright (c) 2024 Fernando Libedinsky
# Producto: IAToolkit
# Todos los derechos reservados.
# En trámite de registro en el Registro de Propiedad Intelectual de Chile.

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
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR,
                               f"Error insertando documentos en PostgreSQL: {str(e)}")

    def query(self, company_id: int, query_text: str, n_results=3, metadata_filter=None) -> list[Document]:
        """
        Busca documentos similares a la consulta para una empresa específica.

        Args:
            company_id: ID de la empresa
            query_text: Texto de la consulta
            n_results: Número máximo de resultados a devolver
            metadata_filter: Diccionario con filtros de metadatos (ej: {"document_type": "certificate"})

        Returns:
            Lista de documentos que coinciden con la consulta y los filtros
        """
        # Generate the embedding with the query text
        query_embedding = self.embedder.feature_extraction([query_text])[0]

        try:
            # Construir la consulta SQL base
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

            # Parámetros para la consulta
            params = {
                "company_id": company_id,
                "query_embedding": query_embedding,
                "n_results": n_results
            }

            # Añadir filtros de metadatos si se especifican
            if metadata_filter and isinstance(metadata_filter, dict):
                for key, value in metadata_filter.items():
                    # Usar el operador ->> para extraer el valor del JSON como texto.
                    # La clave del JSON se interpola directamente.
                    # El valor se pasa como parámetro para evitar inyección SQL.
                    param_name = f"value_{key}_filter"
                    sql_query_parts.append(f" AND documents.meta->>'{key}' = :{param_name}")
                    params[param_name] = str(value)     # parametros como string

            # Unir todas las partes de la consulta
            sql_query = "".join(sql_query_parts)

            # Añadir ordenamiento y límite
            sql_query += " ORDER BY embedding <-> :query_embedding LIMIT :n_results"

            logging.debug(f"Executing SQL query: {sql_query}")
            logging.debug(f"With parameters: {params}")

            # Ejecutar la consulta
            result = self.session.execute(text(sql_query), params)

            rows = result.fetchall()
            vs_documents = []

            for row in rows:
                # Crear objeto Document con todos los datos
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
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR,
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
