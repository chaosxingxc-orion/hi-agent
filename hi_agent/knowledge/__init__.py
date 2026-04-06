"""Knowledge module exports."""

from hi_agent.knowledge.entry import KnowledgeEntry
from hi_agent.knowledge.ingest import IngestPolicy, ingest_run_summary, should_ingest
from hi_agent.knowledge.query import query_knowledge
from hi_agent.knowledge.store import InMemoryKnowledgeStore, KnowledgeRecord

__all__ = [
    "InMemoryKnowledgeStore",
    "IngestPolicy",
    "KnowledgeEntry",
    "KnowledgeRecord",
    "ingest_run_summary",
    "query_knowledge",
    "should_ingest",
]

