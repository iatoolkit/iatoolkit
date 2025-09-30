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
        self.company = None

        # lower warnings
        logging.getLogger().setLevel(logging.ERROR)

        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=100,
            separators=["\n\n", "\n", "."]
        )

    # load the files for all of the companies.
    def load(self, doc_type: str = None):
        # doc_type: an optional document_type for loading
        files_loaded = 0
        companies = self.profile_repo.get_companies()

        for company in companies:
            load_config = company.parameters.get('load', {})
            if not load_config:
                continue

            print(f"Cargando datos de ** {company.short_name} **")
            self.company = company

            # Si hay configuraciones de tipos de documento específicos
            doc_types_config = load_config.get('document_types', {})

            if doc_types_config and len(doc_types_config) > 0:
                # Si se especificó un tipo de documento, cargar solo ese tipo
                if doc_type and doc_type in doc_types_config:
                    files_loaded += self._load_document_type(company, doc_type, doc_types_config[doc_type])
                # Si no se especificó, cargar todos los tipos configurados
                elif not doc_type:
                    for type_name, type_config in doc_types_config.items():
                        files_loaded += self._load_document_type(company, type_name, type_config)
            else:
                # Comportamiento anterior: usar la configuración general
                connector = load_config.get('connector', {})
                if not connector:
                    raise IAToolkitException(IAToolkitException.ErrorType.MISSING_PARAMETER,
                                       f"Falta configurar conector en empresa {company.short_name}")

                files_loaded += self.load_data_source(connector)

        return {'message': f'{files_loaded} files processed'}

    # load the files for all of the companies.
    def load_company_files(self, company: Company, connector: dict):
        if not connector:
            raise IAToolkitException(IAToolkitException.ErrorType.MISSING_PARAMETER,
                        f"Falta configurar conector")

        self.company = company
        files_loaded = self.load_data_source(connector)

        return {'message': f'{files_loaded} files processed'}

    def _load_document_type(self, company: Company, doc_type_name: str, type_config: Dict) -> int:
        # load specific document_types for a company
        connector = type_config.get('connector')
        if not connector:
            logging.warning(f"Falta configurar conector para tipo {doc_type_name} en empresa {company.short_name}")
            raise IAToolkitException(IAToolkitException.ErrorType.MISSING_PARAMETER,
                               f"Falta configurar conector para tipo {doc_type_name} en empresa {company.short_name}")

        # get the metadata for this connector
        predefined_metadata = type_config.get('metadata', {})

        # config specific filters
        filters = type_config.get('filters', {"filename_contains": ".pdf"})

        return self.load_data_source(connector, predefined_metadata, filters)

    def load_data_source(self, connector_config: Dict, predefined_metadata: Dict = None, filters: Dict = None):
        """
        Carga archivos desde una fuente de datos usando un conector.

        Args:
            connector_config: Configuración del conector
            predefined_metadata: Metadatos predefinidos para todos los documentos de esta fuente
            filters: Filtros específicos para esta carga

        Returns:
            int o dict: Número de archivos procesados o diccionario de error
        """
        try:
            # Si no se proporcionaron filtros, usar el predeterminado
            if not filters:
                filters = {"filename_contains": ".pdf"}

            # Pasar metadata predefinida como parte del contexto al procesador
            # para que esté disponible en la función load_file
            extra_context = {}
            if predefined_metadata:
                extra_context['metadata'] = predefined_metadata

            # config the processor
            processor_config = FileProcessorConfig(
                context=extra_context,
                filters=filters,
                action=self.load_file,
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

    # load an individual filename
    # this method is set up on the FileProcessorConfig object
    def load_file(self, filename: str, content: bytes, context: dict = {}, company: Company = None):
        if not company:
            company = self.company

        # check if file exist in repositories
        if self.doc_repo.get(company=company,filename=filename):
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
