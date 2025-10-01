# Copyright (c) 2024 Fernando Libedinsky
# Producto: IAToolkit
# Todos los derechos reservados.
# En trámite de registro en el Registro de Propiedad Intelectual de Chile.

from repositories.vs_repo import VSRepo
from repositories.document_repo import DocumentRepo
from repositories.profile_repo import ProfileRepo
from repositories.llm_query_repo import LLMQueryRepo
from repositories.models import Document, VSDoc, Company
from services.document_service import DocumentService
from langchain.text_splitter import RecursiveCharacterTextSplitter
from infra.connectors.file_connector_factory import FileConnectorFactory
from services.file_processor_service import FileProcessorConfig, FileProcessor
from services.dispatcher_service import Dispatcher
from common.exceptions import IAToolkitException
import logging
import base64
from injector import inject
from typing import Dict


class LoadDocumentsService:
    """
    Orchestrates the process of loading, processing, and storing documents
    from various sources for different companies.
    """
    @inject
    def __init__(self,
                 file_connector_factory: FileConnectorFactory,
                 doc_service: DocumentService,
                 doc_repo: DocumentRepo,
                 vector_store: VSRepo,
                 profile_repo: ProfileRepo,
                 dispatcher: Dispatcher,
                 llm_query_repo: LLMQueryRepo
                 ):
        self.doc_service = doc_service
        self.doc_repo = doc_repo
        self.profile_repo = profile_repo
        self.llm_query_repo = llm_query_repo
        self.vector_store = vector_store
        self.file_connector_factory = file_connector_factory
        self.dispatcher = dispatcher

        # lower warnings
        logging.getLogger().setLevel(logging.ERROR)

        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=100,
            separators=["\n\n", "\n", "."]
        )

    def load_company_files(self,
                         company: Company,
                         connector_config: Dict,
                         predefined_metadata: Dict = None,
                         filters: Dict = None):
        """
        Loads all the company files from a connector

        Args:
            company (Company): The company to load files for.
            connector_config (Dict): The configuration for the file connector.
            predefined_metadata (Dict, optional): Metadata to be added to all documents from this source.
            filters (Dict, optional): Filters to apply to the files.

        Returns:
            int: The number of processed files.
        """
        if not connector_config:
            raise IAToolkitException(IAToolkitException.ErrorType.MISSING_PARAMETER,
                        f"Falta configurar conector")

        try:
            if not filters:
                filters = {"filename_contains": ".pdf"}

            # Pasar metadata predefinida como parte del contexto al procesador
            # para que esté disponible en la función load_file_callback
            context = {
                'company': company,
                'metadata': {}
            }

            if predefined_metadata:
                context['metadata'] = predefined_metadata

            # config the processor
            processor_config = FileProcessorConfig(
                callback=self.load_file_callback,
                context=context,
                filters=filters,
                continue_on_error=True,
                echo=True
            )

            connector = self.file_connector_factory.create(connector_config)
            processor = FileProcessor(connector, processor_config)

            # process the files
            processor.process_files()

            return processor.processed_files
        except Exception as e:
            logging.exception("Loading files error: %s", str(e))
            return {"error": str(e)}

    def load_file_callback(self, company: Company, filename: str, content: bytes, context: dict = {}):
        """
        Processes a single file: extracts text, generates metadata, and saves it
        to the relational database and the vector store.
        This method is intended to be used as the 'action' for FileProcessor.

        Args:
            company (Company): The company associated with the file.
            filename (str): The name of the file.
            content (bytes): The binary content of the file.
            context (dict, optional): A context dictionary, may contain predefined metadata.
        """

        # check if file exist in repositories
        if self.doc_repo.get(company_id=company.id,filename=filename):
            return

        try:
            # extract text from the document
            document_content = self.doc_service.file_to_txt(filename, content)
            content_base64 = base64.b64encode(content).decode('utf-8')

            # generate metada based on the filename structure
            dynamic_metadata = self.dispatcher.get_metadata_from_filename(company_name=company.short_name, filename=filename)

            # Obtener metadatos del contexto si existen
            context_metadata = context.get('metadata', {}).copy() if context else {}

            # Fusionar los metadatos. El orden de prioridad es:
            # 1. dynamic_metadata (tiene mayor prioridad)
            # 2. context_metadata (del parámetro context)
            # Los valores en dynamic_metadata tendrán precedencia sobre los de context_metadata
            final_meta = {**context_metadata, **dynamic_metadata}

            # save the file in the document repositories
            new_document = Document(
                company_id=company.id,
                filename=filename,
                content=document_content,
                content_b64=content_base64,
                meta=final_meta
            )

            # insert the document into the Database (without commit)
            session = self.doc_repo.session
            session.add(new_document)
            session.flush()     # get the ID without commit

            # split the content, and create the chunk list
            splitted_content = self.splitter.split_text(document_content)
            chunk_list = [
                VSDoc(
                    company_id=company.id,
                    document_id=new_document.id,
                    text=text
                )
                for text in splitted_content
            ]

            # save to vector store
            self.vector_store.add_document(chunk_list)

            # confirm the transaction
            session.commit()

            return new_document
        except Exception as e:
            self.doc_repo.session.rollback()

            # if something fails, throw exception
            logging.exception("Error procesando el archivo %s: %s", filename, str(e))
            raise IAToolkitException(IAToolkitException.ErrorType.LOAD_DOCUMENT_ERROR,
                               f"Error al procesar el archivo {filename}")
