"""RAG configuration — loaded from model_config.yaml under the `rag:` key."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DEFAULTS = {
    "enabled": False,
    "data_dir": "ct1/data/rag_uploads",
    "embedding_model": "",          # empty = use chat model
    "embedding_port": 8081,
    "chunks_per_query": 15,
    "chunk_size": 800,              # target tokens per chunk
    "chunk_overlap": 200,           # overlap tokens between chunks
    "max_file_mb": 25,
}

# File extensions we can reliably extract text from
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".txt", ".md", ".markdown", ".rst",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php",
    ".html", ".htm", ".css", ".scss", ".less",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml",
    ".csv", ".tsv", ".log",
    ".sh", ".bat", ".ps1", ".sql",
    ".pdf",
    ".svg",
})


@dataclass
class RAGConfig:
    enabled: bool = False
    data_dir: str = "ct1/data/rag_uploads"
    embedding_model: str = ""
    embedding_port: int = 8081
    chunks_per_query: int = 15
    chunk_size: int = 800
    chunk_overlap: int = 200
    max_file_mb: int = 25

    @staticmethod
    def from_dict(cfg: dict[str, Any]) -> "RAGConfig":
        rag = cfg.get("rag", {}) or {}
        return RAGConfig(
            enabled=rag.get("enabled", _DEFAULTS["enabled"]),
            data_dir=rag.get("data_dir", _DEFAULTS["data_dir"]),
            embedding_model=rag.get("embedding_model", _DEFAULTS["embedding_model"]),
            embedding_port=rag.get("embedding_port", _DEFAULTS["embedding_port"]),
            chunks_per_query=rag.get("chunks_per_query", _DEFAULTS["chunks_per_query"]),
            chunk_size=rag.get("chunk_size", _DEFAULTS["chunk_size"]),
            chunk_overlap=rag.get("chunk_overlap", _DEFAULTS["chunk_overlap"]),
            max_file_mb=rag.get("max_file_mb", _DEFAULTS["max_file_mb"]),
        )

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    def context_cost_estimate(self) -> int:
        """Estimated tokens this RAG config injects per message.

        Accounts for neighbor expansion (~2 neighbors per retrieved chunk).
        """
        # Each retrieved chunk pulls up to 2 neighbors
        return self.chunks_per_query * self.chunk_size * 3
