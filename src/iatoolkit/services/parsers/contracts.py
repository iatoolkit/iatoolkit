# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass
class ParseRequest:
    company_short_name: str
    filename: str
    content: bytes
    mime_type: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    collection_name: Optional[str] = None
    collection_id: Optional[int] = None
    document_id: Optional[int] = None
    provider_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedText:
    text: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedTable:
    text: str
    table_json: Optional[dict[str, Any]] = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedImage:
    content: bytes
    filename: str
    mime_type: str
    color_mode: str
    width: int
    height: int
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParseResult:
    contract_version: str = "1.0"
    provider: str = ""
    provider_version: Optional[str] = None
    texts: list[ParsedText] = field(default_factory=list)
    tables: list[ParsedTable] = field(default_factory=list)
    images: list[ParsedImage] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class ParsingProvider(Protocol):
    name: str
    version: str

    def supports(self, request: ParseRequest) -> bool:
        ...

    def parse(self, request: ParseRequest) -> ParseResult:
        ...
