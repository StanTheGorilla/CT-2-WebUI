"""CT-2 RAG — on-device retrieval-augmented generation.

Indexes text files from a user-managed folder (ct2/data/rag_uploads/), embeds chunks
via llama-server's /v1/embeddings endpoint, and injects top-k relevant
chunks as context for every user message.
"""

from ct2.rag.config import RAGConfig
from ct2.rag.indexer import RAGIndexer
from ct2.rag.retriever import RAGRetriever
from ct2.rag.store import RAGStore

__all__ = ["RAGConfig", "RAGIndexer", "RAGRetriever", "RAGStore"]
