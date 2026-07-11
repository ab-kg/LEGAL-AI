"""
Legal AI GraphRAG — Core Package
=================================
Public API surface for the Legal AI Knowledge Graph pipeline.

Usage:
    from src.core import LegalGraphRAG, build_infrastructure
"""

try:
    from .rag_pipeline import LegalGraphRAG
except ImportError:
    LegalGraphRAG = None

try:
    from .ingestion.kg_builder import build_infrastructure
except ImportError:
    build_infrastructure = None

try:
    from .ingestion.data_loader import get_cuad_contracts
except ImportError:
    get_cuad_contracts = None

__all__ = [
    "LegalGraphRAG",
    "build_infrastructure",
    "get_cuad_contracts",
]
