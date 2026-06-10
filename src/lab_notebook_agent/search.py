from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Iterable


TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_\-]+")


@dataclass(frozen=True)
class SearchResult:
    record: dict[str, Any]
    score: float


def default_knowledge_path() -> Path:
    return Path(str(files("lab_notebook_agent").joinpath("resources/process_knowledge.json")))


def load_knowledge(path: str | Path | None = None) -> list[dict[str, Any]]:
    source = Path(path).expanduser() if path else default_knowledge_path()
    with source.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    records = data.get("records", data)
    if not isinstance(records, list):
        raise ValueError("Process knowledge must be a list or an object with a records list.")
    return records


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(f"{key} {flatten_text(item)}" for key, item in value.items())
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        return " ".join(flatten_text(item) for item in value)
    return str(value)


class LocalSemanticIndex:
    """Small deterministic TF-IDF index for process-knowledge bootstrapping."""

    def __init__(self, records: list[dict[str, Any]]):
        self.records = records
        self.documents = [flatten_text(record) for record in records]
        self.doc_tokens = [tokenize(document) for document in self.documents]
        self.idf = self._build_idf(self.doc_tokens)
        self.doc_vectors = [self._vectorize(tokens) for tokens in self.doc_tokens]

    @classmethod
    def from_default(cls) -> "LocalSemanticIndex":
        return cls(load_knowledge())

    def search(self, query: str, k: int = 5) -> list[SearchResult]:
        query_vector = self._vectorize(tokenize(query))
        scored = []
        for record, vector in zip(self.records, self.doc_vectors):
            score = cosine_similarity(query_vector, vector)
            if score > 0:
                scored.append(SearchResult(record=record, score=score))
        scored.sort(key=lambda result: result.score, reverse=True)
        return scored[:k]

    @staticmethod
    def _build_idf(doc_tokens: list[list[str]]) -> dict[str, float]:
        document_count = len(doc_tokens)
        document_frequency: dict[str, int] = {}
        for tokens in doc_tokens:
            for token in set(tokens):
                document_frequency[token] = document_frequency.get(token, 0) + 1
        return {
            token: math.log((document_count + 1) / (frequency + 1)) + 1
            for token, frequency in document_frequency.items()
        }

    def _vectorize(self, tokens: list[str]) -> dict[str, float]:
        if not tokens:
            return {}
        counts: dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        total = len(tokens)
        return {
            token: (count / total) * self.idf.get(token, 1.0)
            for token, count in counts.items()
        }


def cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(value * right.get(token, 0.0) for token, value in left.items())
    if numerator == 0:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)
