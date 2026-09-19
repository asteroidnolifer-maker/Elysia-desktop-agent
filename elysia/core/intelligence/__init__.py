"""Elysia Intelligence Fabric — knowledge, datasets, adapters, retrieval, provenance.

The Intelligence Fabric is the knowledge, expertise, adaptation, retrieval, routing,
and learning layer surrounding Elysia's AI models.

It does NOT replace the model — it makes the system around the model smarter.
"""
from .fabric import IntelligenceFabric, IntelligencePlan
from .knowledge import KnowledgeRegistry, KnowledgeEntry, DocumentLoader, Chunker
from .embeddings import EmbeddingManager, EmbeddingModel
from .retrieval import HybridRetriever, VectorIndex
from .provenance import ProvenanceTracker
from .datasets import DatasetRegistry, DatasetEntry
from .adapters import AdapterRegistry, AdapterEntry, AdapterRouter
from .router import IntelligenceRouter

__all__ = [
    "IntelligenceFabric",
    "IntelligencePlan",
    "KnowledgeRegistry",
    "KnowledgeEntry",
    "DocumentLoader",
    "Chunker",
    "EmbeddingManager",
    "VectorIndex",
    "HybridRetriever",
    "ProvenanceTracker",
    "DatasetRegistry",
    "DatasetEntry",
    "AdapterRegistry",
    "AdapterEntry",
    "AdapterRouter",
    "IntelligenceRouter",
]