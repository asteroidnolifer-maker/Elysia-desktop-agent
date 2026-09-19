"""Knowledge Registry — unified knowledge system with ingestion, chunking, indexing.

Supports: local documents, PDFs, Markdown, websites, Git repos, source code,
YouTube transcripts, structured databases, spreadsheets.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional
from pathlib import Path


@dataclass
class KnowledgeEntry:
    """A single knowledge item with full provenance."""
    id: str = field(default_factory=lambda: f"k-{uuid.uuid4().hex[:8]}")
    source: str = ""  # file path, URL, repo, etc.
    source_type: str = "document"  # document, pdf, web, github, youtube, dataset
    title: str = ""
    uri: str = ""
    content_hash: str = ""
    version: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    license: str = "unknown"
    author: str = ""
    publisher: str = ""
    language: str = "en"
    domain: str = "general"
    tags: list[str] = field(default_factory=list)
    trust_level: str = "community"  # system, official, verified, reputable, community, unknown, blocked
    provenance: dict = field(default_factory=dict)
    embedding_id: str = ""
    chunks: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeEntry":
        return cls(**data)


class DocumentLoader:
    """Load documents from various sources."""

    SUPPORTED_EXTENSIONS = {
        ".md", ".txt", ".py", ".js", ".ts", ".go", ".rs", ".java", ".cpp",
        ".json", ".yaml", ".yml", ".toml", ".html", ".css", ".sql", ".sh",
        ".pdf", ".csv", ".tsv", ".rst", ".adoc"
    }

    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root

    def load_file(self, path: str) -> tuple[str, dict]:
        """Load a single file, return (content, metadata)."""
        full_path = os.path.join(self.workspace_root, path) if not os.path.isabs(path) else path
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {full_path}")

        ext = Path(full_path).suffix.lower()
        metadata = {"path": path, "extension": ext, "size": os.path.getsize(full_path)}

        if ext == ".pdf":
            content = self._load_pdf(full_path)
        elif ext in (".md", ".txt", ".rst", ".adoc"):
            content = self._load_text(full_path)
        elif ext in (".py", ".js", ".ts", ".go", ".rs", ".java", ".cpp", ".sh"):
            content = self._load_code(full_path)
        elif ext in (".json", ".yaml", ".yml", ".toml"):
            content = self._load_structured(full_path)
        elif ext in (".csv", ".tsv"):
            content = self._load_tabular(full_path)
        else:
            content = self._load_text(full_path)

        return content, metadata

    def _load_text(self, path: str) -> str:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def _load_code(self, path: str) -> str:
        return self._load_text(path)

    def _load_pdf(self, path: str) -> str:
        """Extract text from PDF."""
        try:
            import pypdf
            with open(path, "rb") as f:
                reader = pypdf.PdfReader(f)
                return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            return f"[PDF: {path} — pypdf not installed]"

    def _load_structured(self, path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def _load_tabular(self, path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def load_directory(self, rel_path: str, max_files: int = 100) -> list[tuple[str, str, dict]]:
        """Load all supported files from a directory."""
        base = os.path.join(self.workspace_root, rel_path)
        results = []
        for root, dirs, files in os.walk(base):
            # Skip hidden and common ignore dirs
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in
                       ("node_modules", "__pycache__", ".git", "dist", "build", ".venv", "venv")]
            for f in files:
                ext = Path(f).suffix.lower()
                if ext in self.SUPPORTED_EXTENSIONS:
                    rel = os.path.relpath(os.path.join(root, f), self.workspace_root)
                    content, meta = self.load_file(rel)
                    results.append((rel, content, meta))
                    if len(results) >= max_files:
                        return results
        return results


class Chunker:
    """Semantic chunking for knowledge documents."""

    def __init__(self, max_chunk_chars: int = 2000, overlap_chars: int = 200):
        self.max_chunk_chars = max_chunk_chars
        self.overlap_chars = overlap_chars

    def chunk_text(self, text: str, source_id: str, metadata: dict = None) -> list[dict]:
        """Chunk text into overlapping segments with semantic boundaries."""
        if len(text) <= self.max_chunk_chars:
            return [{
                "id": f"{source_id}-0",
                "source_id": source_id,
                "text": text,
                "start_char": 0,
                "end_char": len(text),
                "metadata": metadata or {}
            }]

        chunks = []
        # Try to split on semantic boundaries first
        boundaries = self._find_boundaries(text)

        start = 0
        chunk_idx = 0
        while start < len(text):
            end = min(start + self.max_chunk_chars, len(text))

            # Adjust to nearest boundary
            if end < len(text):
                nearest = self._nearest_boundary(boundaries, end)
                if nearest > start:
                    end = nearest

            chunk_text = text[start:end]
            chunks.append({
                "id": f"{source_id}-{chunk_idx}",
                "source_id": source_id,
                "text": chunk_text,
                "start_char": start,
                "end_char": end,
                "metadata": metadata or {}
            })
            chunk_idx += 1
            start = max(end - self.overlap_chars, start + 1)

        return chunks

    def _find_boundaries(self, text: str) -> list[int]:
        """Find semantic boundaries (headings, paragraphs, code blocks)."""
        boundaries = [0]
        # Headings
        for m in re.finditer(r"^#{1,6}\s+", text, re.MULTILINE):
            boundaries.append(m.start())
        # Double newlines (paragraphs)
        for m in re.finditer(r"\n\s*\n", text):
            boundaries.append(m.start())
        # Code block fences
        for m in re.finditer(r"^```", text, re.MULTILINE):
            boundaries.append(m.start())
        boundaries.append(len(text))
        return sorted(set(boundaries))

    def _nearest_boundary(self, boundaries: list[int], target: int) -> int:
        """Find the boundary closest to target."""
        return min(boundaries, key=lambda b: abs(b - target))

    def chunk_code(self, text: str, source_id: str, language: str = "python") -> list[dict]:
        """Chunk code by function/class definitions."""
        # Simple approach: split by function/class definitions
        if language == "python":
            pattern = r"^(async\s+)?def\s+\w+|^class\s+\w+"
        elif language in ("javascript", "typescript"):
            pattern = r"^(export\s+)?(async\s+)?function\s+\w+|^class\s+\w+"
        else:
            pattern = r"^\w+\s+\w+\s*\("

        matches = list(re.finditer(pattern, text, re.MULTILINE))
        if not matches:
            return self.chunk_text(text, source_id)

        chunks = []
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            chunks.append({
                "id": f"{source_id}-{i}",
                "source_id": source_id,
                "text": text[start:end],
                "start_char": start,
                "end_char": end,
                "metadata": {"language": language, "type": "code_block"}
            })
        return chunks


class KnowledgeRegistry:
    """Registry for knowledge entries with SQLite persistence."""

    def __init__(self, workspace_root: str, db_name: str = "knowledge.db"):
        self.workspace_root = workspace_root
        self.db_path = os.path.join(workspace_root, ".elysia", db_name)
        self.loader = DocumentLoader(workspace_root)
        self.chunker = Chunker()
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        import sqlite3
        con = sqlite3.connect(self.db_path)
        con.execute("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id TEXT PRIMARY KEY,
                source TEXT,
                source_type TEXT,
                title TEXT,
                uri TEXT,
                content_hash TEXT,
                version TEXT,
                created_at TEXT,
                updated_at TEXT,
                license TEXT,
                author TEXT,
                publisher TEXT,
                language TEXT,
                domain TEXT,
                tags TEXT,
                trust_level TEXT,
                provenance TEXT,
                embedding_id TEXT,
                chunks TEXT,
                metadata TEXT
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_domain ON knowledge(domain)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_source ON knowledge(source)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_hash ON knowledge(content_hash)")
        con.commit()
        con.close()

    def _connect(self):
        import sqlite3
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def add(self, entry: KnowledgeEntry) -> str:
        """Add or update a knowledge entry."""
        import sqlite3
        con = self._connect()
        con.execute("""
            INSERT OR REPLACE INTO knowledge VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            entry.id, entry.source, entry.source_type, entry.title, entry.uri,
            entry.content_hash, entry.version, entry.created_at, entry.updated_at,
            entry.license, entry.author, entry.publisher, entry.language,
            entry.domain, json.dumps(entry.tags), entry.trust_level,
            json.dumps(entry.provenance), entry.embedding_id,
            json.dumps(entry.chunks), json.dumps(entry.metadata)
        ))
        con.commit()
        con.close()
        return entry.id

    def get(self, entry_id: str) -> Optional[KnowledgeEntry]:
        import sqlite3
        con = self._connect()
        row = con.execute("SELECT * FROM knowledge WHERE id=?", (entry_id,)).fetchone()
        con.close()
        if not row:
            return None
        return self._row_to_entry(row)

    def search(self, query: str = "", domain: str = None, tags: list = None,
               trust_min: str = "community", limit: int = 20) -> list[KnowledgeEntry]:
        """Search knowledge entries by metadata (not semantic — use retriever for that)."""
        import sqlite3
        con = self._connect()
        sql = "SELECT * FROM knowledge WHERE 1=1"
        params = []

        # Trust level filter (simple string comparison for ordering)
        trust_order = {"system": 0, "official": 1, "verified": 2, "reputable": 3,
                       "community": 4, "unknown": 5, "blocked": 6}
        min_trust = trust_order.get(trust_min, 4)
        trust_filter = " AND trust_level IN ({})".format(
            ",".join("?" for _ in trust_order if trust_order[_] <= min_trust))
        sql += trust_filter
        params.extend([t for t in trust_order if trust_order[t] <= min_trust])

        if domain:
            sql += " AND domain=?"
            params.append(domain)
        if tags:
            for tag in tags:
                sql += " AND tags LIKE ?"
                params.append(f"%{tag}%")
        if query:
            sql += " AND (title LIKE ? OR source LIKE ?)"
            params.extend([f"%{query}%", f"%{query}%"])

        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        rows = con.execute(sql, params).fetchall()
        con.close()
        return [self._row_to_entry(r) for r in rows]

    def list(self, limit: int = 50, domain: str = None) -> list[KnowledgeEntry]:
        import sqlite3
        con = self._connect()
        sql = "SELECT * FROM knowledge"
        params = []
        if domain:
            sql += " WHERE domain=?"
            params.append(domain)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        rows = con.execute(sql, params).fetchall()
        con.close()
        return [self._row_to_entry(r) for r in rows]

    def stats(self) -> dict:
        import sqlite3
        con = self._connect()
        total = con.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        by_domain = dict(con.execute(
            "SELECT domain, COUNT(*) FROM knowledge GROUP BY domain").fetchall())
        by_source_type = dict(con.execute(
            "SELECT source_type, COUNT(*) FROM knowledge GROUP BY source_type").fetchall())
        by_trust = dict(con.execute(
            "SELECT trust_level, COUNT(*) FROM knowledge GROUP BY trust_level").fetchall())
        con.close()
        return {
            "total": total,
            "by_domain": by_domain,
            "by_source_type": by_source_type,
            "by_trust": by_trust,
        }

    def ingest_file(self, rel_path: str, domain: str = None, tags: list = None,
                    trust_level: str = "community", license: str = "unknown") -> KnowledgeEntry:
        """Load, chunk, and index a single file."""
        content, meta = self.loader.load_file(rel_path)
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        # Check for duplicates
        existing = self._connect().execute(
            "SELECT id FROM knowledge WHERE content_hash=?", (content_hash,)
        ).fetchone()
        if existing:
            return self.get(existing[0])

        entry = KnowledgeEntry(
            source=rel_path,
            source_type=self._infer_source_type(rel_path),
            title=meta.get("path", rel_path),
            uri=f"file://{rel_path}",
            content_hash=content_hash,
            version="1.0",
            domain=domain or self._infer_domain(content),
            tags=tags or [],
            trust_level=trust_level,
            license=license,
            provenance={"ingested_at": datetime.now().isoformat(), "method": "file"},
        )

        # Chunk the content
        chunks = self.chunker.chunk_text(content, entry.id, metadata=meta)
        entry.chunks = chunks

        self.add(entry)
        return entry

    def ingest_directory(self, rel_path: str, domain: str = None, tags: list = None,
                         trust_level: str = "community") -> list[KnowledgeEntry]:
        """Ingest all supported files in a directory."""
        entries = []
        for rel, content, meta in self.loader.load_directory(rel_path):
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            existing = self._connect().execute(
                "SELECT id FROM knowledge WHERE content_hash=?", (content_hash,)
            ).fetchone()
            if existing:
                entries.append(self.get(existing[0]))
                continue

            entry = KnowledgeEntry(
                source=rel,
                source_type=self._infer_source_type(rel),
                title=meta.get("path", rel),
                uri=f"file://{rel}",
                content_hash=content_hash,
                version="1.0",
                domain=domain or self._infer_domain(content),
                tags=tags or [],
                trust_level=trust_level,
                provenance={"ingested_at": datetime.now().isoformat(), "method": "directory"},
            )
            chunks = self.chunker.chunk_text(content, entry.id, metadata=meta)
            entry.chunks = chunks
            self.add(entry)
            entries.append(entry)
        return entries

    def _infer_source_type(self, path: str) -> str:
        ext = Path(path).suffix.lower()
        if ext == ".pdf":
            return "pdf"
        elif ext in (".md", ".txt", ".rst", ".adoc"):
            return "document"
        elif ext in (".py", ".js", ".ts", ".go", ".rs", ".java", ".cpp", ".sh"):
            return "code"
        elif ext in (".json", ".yaml", ".yml", ".toml", ".csv", ".tsv"):
            return "data"
        return "document"

    def _infer_domain(self, content: str) -> str:
        """Infer domain from content."""
        text = content.lower()[:5000]
        if any(k in text for k in ("def ", "class ", "import ", "function", "const ", "var ")):
            return "coding"
        if any(k in text for k in ("revenue", "profit", "budget", "financial", "stock")):
            return "finance"
        if any(k in text for k in ("vulnerability", "security", "exploit", "threat")):
            return "security"
        if any(k in text for k in ("select ", "insert ", "update ", "delete ", "create table")):
            return "data"
        return "general"

    def _row_to_entry(self, row) -> KnowledgeEntry:
        return KnowledgeEntry(
            id=row["id"], source=row["source"], source_type=row["source_type"],
            title=row["title"], uri=row["uri"], content_hash=row["content_hash"],
            version=row["version"], created_at=row["created_at"], updated_at=row["updated_at"],
            license=row["license"], author=row["author"], publisher=row["publisher"],
            language=row["language"], domain=row["domain"],
            tags=json.loads(row["tags"] or "[]"),
            trust_level=row["trust_level"], provenance=json.loads(row["provenance"] or "{}"),
            embedding_id=row["embedding_id"], chunks=json.loads(row["chunks"] or "[]"),
            metadata=json.loads(row["metadata"] or "{}")
        )