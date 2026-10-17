# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""What "used the Memoria" means, in one place (Fase 2 of the Memoria architecture review).

Before, five modules each kept their own list of Memoria tools, so the hourly
question review, Impacto and the prompts counted different things.
"""

# Looking for knowledge: a page search or a document search.
SEARCH_TOOLS = frozenset({"iat_memory_search", "iat_document_search"})
# Reading what a search found.
READ_TOOLS = frozenset({"iat_memory_get_page", "iat_document_read", "iat_document_list"})
# Every tool whose use is a use of the company's knowledge (usage events, Impacto).
KNOWLEDGE_TOOLS = SEARCH_TOOLS | READ_TOOLS

PAGE_SEARCH_TOOL = "iat_memory_search"
PAGE_READ_TOOL = "iat_memory_get_page"
DOCUMENT_SEARCH_TOOL = "iat_document_search"
DOCUMENT_READ_TOOL = "iat_document_read"

CHANNEL_CHAT = "chat"
CHANNEL_MCP = "mcp"
