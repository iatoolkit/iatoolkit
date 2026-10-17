"""Exercise real PDF parsing and pgvector with deterministic, offline embeddings."""

from unittest.mock import patch

import fitz

from distribution.app import create_app
from iatoolkit.core import current_iatoolkit
from iatoolkit.repositories.models import DocumentStatus
from iatoolkit.services.company_context_service import CompanyContextService
from iatoolkit.services.embedding_service import EmbeddingService
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.services.profile_service import ProfileService

app = create_app()
with app.test_request_context('/sample_company/'):
    injector = current_iatoolkit().get_injector()
    context = injector.get(CompanyContextService)
    schema = context.get_enriched_database_schema('sample_company', 'sample_db')
    assert 'orders' in schema and 'employees' in schema
    assert any(column['name'] == 'order_id' for column in schema['orders']['columns'])
    print('PASS: SQL context reflects the restored database column names')

    company = injector.get(ProfileService).get_company_by_short_name('sample_company')
    knowledge = injector.get(KnowledgeBaseService)
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 550, 750), (
        'Docker smoke contract. Employee Julia Bianchi works in the sales team. '
        'This synthetic contract is used to verify document extraction and retrieval. '
        'The employee has twenty days of annual leave. '
    ) * 6)
    content = pdf.tobytes()
    pdf.close()
    document = None
    document_id = None
    # Only the embedding boundary is mocked. Storage, PDF parsing, chunking,
    # SQL transactions and vector retrieval use the actual container services.
    with patch.object(EmbeddingService, 'embed_text', return_value=[1.0] + [0.0] * 1535):
        try:
            document = knowledge.ingest_document_sync(
                company=company, filename='docker-smoke-contract.pdf',
                content=content, collection='employee_contract',
                metadata={'source': 'docker_smoke'},
            )
            document_id = document.id
            assert document.status == DocumentStatus.ACTIVE
            duplicate = knowledge.ingest_document_sync(
                company=company, filename='docker-smoke-contract.pdf',
                content=content, collection='employee_contract',
            )
            assert duplicate.id == document.id
            results = knowledge.search(
                'sample_company', 'Julia Bianchi annual leave',
                collection='employee_contract', include_urls=True,
                metadata_filter={'source': 'docker_smoke'},
                search_mode='vector',
            )
            assert results and any('Julia Bianchi' in str(result) for result in results)
            assert knowledge.search('unregistered_company', 'Julia Bianchi') == []
            print('PASS: PDF ingestion, duplicate detection, pgvector search and tenant isolation (offline embeddings)')
        finally:
            if document_id is not None:
                knowledge.delete_document(document_id)
