# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""The contract of a Memoria source (BL-016, Fase 3).

Everything enters Memoria as a capture; what kind of source a capture comes
from is its `meta.mode` (and, for a document, its `meta.kind`). Before, each
kind was a string in `meta` plus an `if` in the compiler, with its rules spread
over three services. A source now declares, in one place:

- `mode`: the capture's `meta.mode` it answers for (None: a person's capture);
- `handler`: the compiler step that reads it;
- `agent`: the system agent that reads it (None: no model), and `kind_agents`
  for variants of the same source (a meeting transcript is a document read by
  the meeting reader);
- `on_new_version`: what a new version of the same source does to what the
  previous one taught ("replace": its lines are marked obsolete before the new
  version is read; "add": both stay, as two people saying things);
- `on_removal`: what its removal does ("mark_obsolete": its lines are marked,
  never erased; "none");
- `visibility`: who may read what it teaches: "company" (people, corrections in the
  page's audience) or "folder" (a document: its folder's audience when restricted).
  The capture carries the audience (`audience_key`) and the compiler writes it only
  into pages of that audience (BL-010, Fase 3).

A new source registers here (`MemorySourceRegistry.register`) instead of adding
another branch to the compiler.
"""

from __future__ import annotations

from dataclasses import dataclass, field

VERSION_REPLACE = "replace"
VERSION_ADD = "add"
REMOVAL_MARK_OBSOLETE = "mark_obsolete"
REMOVAL_NONE = "none"
VISIBILITY_COMPANY = "company"
# What it teaches is for its folder's audience when the folder is restricted (BL-010, Fase 3).
VISIBILITY_FOLDER = "folder"


@dataclass(frozen=True)
class MemorySource:
    key: str
    mode: str | None
    handler: str
    agent: str | None
    kind_agents: dict = field(default_factory=dict)
    on_new_version: str = VERSION_ADD
    on_removal: str = REMOVAL_NONE
    visibility: str = VISIBILITY_COMPANY
    description: str = ""

    def agent_for(self, meta: dict | None) -> str | None:
        kind = str((meta or {}).get("kind") or "").strip()
        return self.kind_agents.get(kind, self.agent)


class MemorySourceRegistry:
    """Which source each capture is, by its `meta.mode`."""

    _sources: dict[str | None, MemorySource] = {}

    @classmethod
    def register(cls, source: MemorySource) -> None:
        cls._sources[source.mode] = source

    @classmethod
    def for_capture(cls, meta: dict | None) -> MemorySource:
        mode = (meta or {}).get("mode")
        return cls._sources.get(mode) or cls._sources[None]

    @classmethod
    def get(cls, key: str) -> MemorySource | None:
        return next((source for source in cls._sources.values() if source.key == key), None)

    @classmethod
    def all(cls) -> list[MemorySource]:
        return list(cls._sources.values())


def register_core_sources(*, compiler_agent: str, correction_agent: str, document_agent: str,
                          meeting_agent: str, correction_mode: str, document_mode: str,
                          document_removed_mode: str, meeting_kind: str) -> None:
    """The sources core knows; MemoryCompilerService registers them with its constants."""
    MemorySourceRegistry.register(MemorySource(
        key="people", mode=None, handler="_compile_person_capture", agent=compiler_agent,
        description="What a person explained: the chat, MCP, the console, an answered question, the capture API.",
    ))
    MemorySourceRegistry.register(MemorySource(
        key="correction", mode=correction_mode, handler="_apply_correction", agent=correction_agent,
        description="'¿Qué hay que corregir?' on one page.",
    ))
    MemorySourceRegistry.register(MemorySource(
        key="document", mode=document_mode, handler="_ingest_document", agent=document_agent,
        kind_agents={meeting_kind: meeting_agent},
        on_new_version=VERSION_REPLACE, on_removal=REMOVAL_MARK_OBSOLETE, visibility=VISIBILITY_FOLDER,
        description="A document of a Memoria folder (Drive or uploaded), or a meeting transcript.",
    ))
    MemorySourceRegistry.register(MemorySource(
        key="document_removed", mode=document_removed_mode, handler="_mark_document_obsolete", agent=None,
        description="A document that left Memoria, or the previous version of one: its lines marked obsolete.",
    ))
