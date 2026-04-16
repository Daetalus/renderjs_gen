from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import chromadb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from chroma_embedding import EmbeddingGemmaFunction
from embedding_client import EmbeddingClientError, EmbeddingGemmaClient


DEFAULT_CORPUS_DIR = PROJECT_ROOT / "corpus"
DEFAULT_PERSIST_DIR = PROJECT_ROOT / "chroma_db"
DEFAULT_COLLECTION = "renderjs_poc_v3"
DEFAULT_EMBEDDING_URL = "http://localhost"

CORPUS_FILES: tuple[str, ...] = (
    "renderjs_corpus_api_rules.md",
    "renderjs_corpus_patterns.md",
    "renderjs_corpus_examples.md",
    "renderjs_corpus_glossary.md",
)

PRIORITY_BY_DOC_TYPE: dict[str, int] = {
    "rule": 1,
    "api": 2,
    "pattern": 3,
    "example": 4,
    "glossary": 5,
}

DOC_TYPE_BY_CORPUS_TYPE: dict[str, str] = {
    "patterns": "pattern",
    "code_examples": "example",
    "glossary_templates": "glossary",
}

LIST_METADATA_KEYS: tuple[str, ...] = (
    "field_groups",
    "api_names",
    "use_cases",
    "component_kinds",
)


@dataclass(frozen=True)
class MarkdownChunk:
    corpus_type: str
    source_file: str
    section_title: str
    chunk_index: int
    text: str
    doc_type: str
    metadata: dict[str, str | int]


@dataclass(frozen=True)
class CorpusFile:
    filename: str
    corpus_type: str
    content: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser("Build RenderJS PoC vector database")
    parser.add_argument("--corpus-dir", default=str(DEFAULT_CORPUS_DIR))
    parser.add_argument("--persist-dir", default=str(DEFAULT_PERSIST_DIR))
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--embedding-url", default=DEFAULT_EMBEDDING_URL)
    return parser.parse_args()


def split_h2_sections(markdown_text: str) -> list[tuple[str, str]]:
    lines = markdown_text.splitlines()
    sections: list[tuple[str, str]] = []
    in_code_block = False
    current_title: str | None = None
    current_body: list[str] = []

    for line in lines:
        stripped = line.strip()
        fence_candidate = stripped.lstrip("\u200b\ufeff")
        if fence_candidate.startswith("```"):
            in_code_block = not in_code_block
        if not in_code_block and line.startswith("## "):
            if current_title is not None:
                sections.append((current_title, "\n".join(current_body).strip()))
            current_title = line[3:].strip()
            current_body = []
            continue
        if current_title is not None:
            current_body.append(line)

    if current_title is not None:
        sections.append((current_title, "\n".join(current_body).strip()))
    return sections


def parse_corpus_file(path: Path) -> CorpusFile:
    content = path.read_text(encoding="utf-8")
    header = parse_header_metadata(content)
    corpus_type = str(header.get("corpus_type") or "").strip()
    if not corpus_type:
        raise ValueError(f"Corpus file {path} is missing a corpus_type header.")
    return CorpusFile(
        filename=path.name,
        corpus_type=corpus_type,
        content=content,
    )


def parse_header_metadata(markdown_text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## "):
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata


def parse_chunk_metadata(body: str) -> dict[str, list[str]]:
    metadata: dict[str, list[str]] = {key: [] for key in LIST_METADATA_KEYS}
    lines = body.splitlines()
    index = 0

    while index < len(lines):
        stripped = lines[index].strip()
        if stripped in {f"{key}:" for key in LIST_METADATA_KEYS}:
            key = stripped[:-1]
            index += 1
            values: list[str] = []
            while index < len(lines):
                item = lines[index].strip()
                if not item:
                    index += 1
                    continue
                if item.startswith("- "):
                    values.append(item[2:].strip())
                    index += 1
                    continue
                break
            metadata[key] = values
            continue
        index += 1

    return metadata


def infer_doc_type(corpus_type: str, title: str) -> str:
    if corpus_type == "rules_api":
        return "api" if title.lower().startswith("api:") else "rule"
    try:
        return DOC_TYPE_BY_CORPUS_TYPE[corpus_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported corpus_type for doc_type inference: {corpus_type}") from exc


def list_to_csv(values: Iterable[str]) -> str:
    return ",".join(dedupe_preserve_order([value.strip() for value in values if value.strip()]))


def dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


def format_chunk_id(corpus_type: str, sequence_number: int) -> str:
    return f"{corpus_type}_{sequence_number:03d}"


def build_chunk(
    source_file: str,
    corpus_type: str,
    chunk_index: int,
    sequence_number: int,
    title: str,
    body: str,
) -> MarkdownChunk:
    text = f"## {title}\n\n{body}".strip()
    parsed_metadata = parse_chunk_metadata(body)
    doc_type = infer_doc_type(corpus_type, title)
    priority = PRIORITY_BY_DOC_TYPE[doc_type]
    doc_id = format_chunk_id(corpus_type, sequence_number)
    metadata: dict[str, str | int] = {
        "doc_id": doc_id,
        "corpus_type": corpus_type,
        "source_file": source_file,
        "section_title": title,
        "chunk_index": chunk_index,
        "doc_type": doc_type,
        "priority": priority,
        "field_groups": list_to_csv(parsed_metadata["field_groups"]),
        "api_names": list_to_csv(parsed_metadata["api_names"]),
        "use_cases": list_to_csv(parsed_metadata["use_cases"]),
        "component_kinds": list_to_csv(parsed_metadata["component_kinds"]),
    }
    return MarkdownChunk(
        corpus_type=corpus_type,
        source_file=source_file,
        section_title=title,
        chunk_index=chunk_index,
        text=text,
        doc_type=doc_type,
        metadata=metadata,
    )


def iter_markdown_chunks(corpus_dir: Path) -> list[MarkdownChunk]:
    chunks: list[MarkdownChunk] = []
    counters: dict[str, int] = {}
    for filename in CORPUS_FILES:
        path = corpus_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Corpus file not found: {path}")
        corpus_file = parse_corpus_file(path)
        corpus_type = corpus_file.corpus_type
        sections = split_h2_sections(corpus_file.content)
        for chunk_index, (title, body) in enumerate(sections):
            if not title.strip():
                continue
            counters[corpus_type] = counters.get(corpus_type, 0) + 1
            chunks.append(
                build_chunk(
                    filename,
                    corpus_type,
                    chunk_index,
                    counters[corpus_type],
                    title,
                    body,
                )
            )
    return chunks


def check_embedding_service(embedding_url: str) -> None:
    client = EmbeddingGemmaClient(base_url=embedding_url)
    try:
        vector = client.embed_document("RenderJS vector DB healthcheck", title="healthcheck")
    except Exception as exc:
        raise RuntimeError(
            "EmbeddingGemma service is unavailable. "
            f"Checked endpoint: {embedding_url}. "
            f"Error: {exc}"
        ) from exc
    if not vector:
        raise RuntimeError(
            "EmbeddingGemma service returned an empty embedding. "
            f"Checked endpoint: {embedding_url}."
        )


def build_vector_db(
    *,
    corpus_dir: Path = DEFAULT_CORPUS_DIR,
    persist_dir: Path = DEFAULT_PERSIST_DIR,
    collection_name: str = DEFAULT_COLLECTION,
    embedding_url: str = DEFAULT_EMBEDDING_URL,
) -> dict[str, int | str]:
    check_embedding_service(embedding_url)
    chunks = iter_markdown_chunks(corpus_dir)
    persist_dir.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(persist_dir))
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass

    collection = client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=EmbeddingGemmaFunction(
            EmbeddingGemmaClient(base_url=embedding_url),
        ),
    )

    if chunks:
        collection.add(
            ids=[str(chunk.metadata["doc_id"]) for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            metadatas=[chunk.metadata for chunk in chunks],
        )

    result = {
        "collection": collection_name,
        "persist_dir": str(persist_dir),
        "chunk_count": len(chunks),
    }
    print(result, flush=True)
    return result


def main() -> None:
    args = parse_args()
    try:
        build_vector_db(
            corpus_dir=Path(args.corpus_dir).resolve(),
            persist_dir=Path(args.persist_dir).resolve(),
            collection_name=args.collection,
            embedding_url=str(args.embedding_url),
        )
    except Exception as exc:
        print(f"[build_vectordb] {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
