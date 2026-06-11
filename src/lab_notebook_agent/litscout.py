from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .search import SearchResult, flatten_text


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.\-/]+", "-", value.strip().lower()).strip("-")
    return normalized or "experiment"


def build_litscout_query(entry: dict[str, Any], knowledge_results: list[SearchResult] | None = None) -> str:
    pieces = [
        str(entry.get("process_type", "")),
        str(entry.get("objective", "")),
        flatten_text(entry.get("observations", "")),
        flatten_text(entry.get("results", "")),
    ]
    for result in knowledge_results or []:
        record = result.record
        pieces.extend(record.get("search_terms", []))
        pieces.append(record.get("process_type", ""))
    tokens = []
    seen = set()
    for token in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]+", " ".join(pieces).lower()):
        if token not in seen and len(token) > 2:
            seen.add(token)
            tokens.append(token)
    priority = [
        "emulsion",
        "polymerization",
        "surfactant",
        "initiator",
        "particle",
        "size",
        "coagulum",
        "latex",
        "core",
        "shell",
        "monomer",
        "feed",
    ]
    ordered = [token for token in priority if token in seen]
    ordered.extend(token for token in tokens if token not in ordered)
    return " ".join(ordered[:18])


def build_litscout_commands(
    entry: dict[str, Any],
    knowledge_results: list[SearchResult] | None = None,
    artifacts_dir: str | Path = "artifacts",
) -> list[str]:
    experiment_id = slugify(str(entry.get("experiment_id", "experiment")))
    session_name = f"labnotebook/{experiment_id}"
    query = build_litscout_query(entry, knowledge_results)
    output = Path(artifacts_dir) / f"litscout-{experiment_id}.json"
    return [
        (
            f'litscout search multi "{query}" '
            "--sources openalex,crossref,semantic_scholar "
            "--depth light --limit 25 --save "
            f"--session-name {session_name}"
        ),
        (
            f"litscout sessions export {session_name} "
            f"--format json --json-array --output {output}"
        ),
    ]


def load_litscout_export(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("LitScout export must be a JSON array.")
    return [row for row in data if isinstance(row, dict)]


def litscout_works_to_evidence_rows(
    works: list[dict[str, Any]],
    experiment_id: str,
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ranked = sorted(works, key=lambda work: work_relevance_sort_key(work, query), reverse=True)
    for index, work in enumerate(ranked[:limit], start=1):
        evidence_id = f"LIT-{slugify(experiment_id).upper().replace('/', '-')}-{index:03d}"
        title = str(work.get("title") or "").strip()
        concepts = concept_names(work)
        search_text = work_search_text(work)
        tags = relevance_tags(search_text)
        rows.append(
            {
                "evidence_id": evidence_id,
                "source": str(work.get("service") or work.get("source") or "litscout"),
                "title": title,
                "authors": ", ".join(author_names(work)[:6]),
                "year": work.get("year") or publication_year(work),
                "doi_or_url": work.get("url") or doi_url(work.get("doi")) or work.get("primary_id") or "",
                "query": query,
                "finding": build_evidence_finding(work, concepts),
                "relevance_tags": ",".join(tags),
                "confidence": evidence_confidence(work, query),
                "notes": "Imported from LitScout export; review source text before treating as definitive.",
            }
        )
    return rows


def evidence_rows_to_values(rows: list[dict[str, Any]]) -> list[list[Any]]:
    headers = [
        "evidence_id",
        "source",
        "title",
        "authors",
        "year",
        "doi_or_url",
        "query",
        "finding",
        "relevance_tags",
        "confidence",
        "notes",
    ]
    return [[row.get(header, "") for header in headers] for row in rows]


def work_relevance_sort_key(work: dict[str, Any], query: str = "") -> tuple[float, int, int]:
    text = work_search_text(work).lower()
    title = str(work.get("title") or "").lower()
    query_terms = query_relevance_terms(query)
    work_terms = set(re.findall(r"[a-zA-Z][a-zA-Z0-9\-]+", text))
    overlap = len(query_terms & work_terms)

    score = float(overlap)
    if "emulsion polymerization" in text:
        score += 8.0
        if "emulsion polymerization" in title:
            score += 4.0
    elif {"emulsion", "polymerization"} <= work_terms:
        score += 4.0
    elif "polymerization" in query_terms and "polymerization" not in work_terms:
        score -= 4.0

    if "particle size" in text and {"particle", "size"} <= query_terms:
        score += 4.0
        if "particle size" in title:
            score += 2.0
    for term in ("latex", "coagulum", "coagulation", "nucleation", "surfactant", "initiator", "monomer", "feed"):
        if term in query_terms and term in work_terms:
            score += 2.0

    if "polymerization" in query_terms and "polymerization" not in work_terms:
        score -= generic_off_process_penalty(text)

    citations = int(work.get("cited_by_count") or 0)
    year = int(work.get("year") or 0)
    return score, citations, year


def work_search_text(work: dict[str, Any]) -> str:
    return " ".join(
        [
            str(work.get("title") or ""),
            str(work.get("source") or ""),
            str(work.get("journal_or_collection") or ""),
            flatten_text(work.get("abstract", "")),
            flatten_text(work.get("summary", "")),
            " ".join(concept_names(work)),
        ]
    )


def query_relevance_terms(query: str) -> set[str]:
    stopwords = {
        "completed",
        "experiment",
        "record",
        "recorded",
        "run",
        "sample",
        "stage",
        "timestamp",
        "temperature",
    }
    return {
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]+", query.lower())
        if len(token) > 2 and token not in stopwords and not token.startswith("ep-")
    }


def generic_off_process_penalty(text: str) -> float:
    penalty_terms = (
        "biomedical",
        "biocompatibility",
        "nanoparticle",
        "photocatalysis",
        "pickering emulsion",
        "pulmonary surfactant",
    )
    return float(sum(1 for term in penalty_terms if term in text))


def author_names(work: dict[str, Any]) -> list[str]:
    names = work.get("author_names")
    if isinstance(names, list):
        return [str(name) for name in names if name]
    authors = work.get("authors")
    if isinstance(authors, list):
        return [str(author.get("name")) for author in authors if isinstance(author, dict) and author.get("name")]
    return []


def concept_names(work: dict[str, Any]) -> list[str]:
    concepts = work.get("concepts") or []
    names = []
    if isinstance(concepts, list):
        for concept in concepts:
            if isinstance(concept, dict) and concept.get("display_name"):
                names.append(str(concept["display_name"]))
            elif isinstance(concept, str):
                names.append(concept)
    keywords = work.get("keywords") or []
    if isinstance(keywords, list):
        for keyword in keywords:
            if isinstance(keyword, dict):
                text = keyword.get("text") or keyword.get("display_name") or keyword.get("name")
                if text:
                    names.append(str(text))
            elif keyword:
                names.append(str(keyword))
    return names


def build_evidence_finding(work: dict[str, Any], concepts: list[str]) -> str:
    title = str(work.get("title") or "Untitled work")
    year = work.get("year") or publication_year(work) or "unknown year"
    cited_by = work.get("cited_by_count")
    concept_text = ", ".join(concepts[:5])
    citation_text = f"; cited by {cited_by}" if cited_by not in (None, "") else ""
    if concept_text:
        return f"{title} ({year}) is a LitScout hit with concepts: {concept_text}{citation_text}."
    return f"{title} ({year}) is a LitScout hit for the experiment query{citation_text}."


def relevance_tags(text: str) -> list[str]:
    lowered = text.lower()
    tag_terms = {
        "surfactant": ("surfactant", "anionic", "nonionic"),
        "particle_size": ("particle size", "particles", "latex"),
        "initiator": ("initiator", "persulfate", "radical"),
        "monomer": ("monomer", "acrylate", "methacrylate"),
        "stability": ("stability", "coagulative", "coagulum", "coagulation", "colloidal"),
        "feed": ("semibatch", "semi-batch", "feed"),
    }
    return [tag for tag, terms in tag_terms.items() if any(term in lowered for term in terms)]


def evidence_confidence(work: dict[str, Any], query: str) -> str:
    text = work_search_text(work).lower()
    query_terms = query_relevance_terms(query)
    matches = sum(1 for token in query_terms if token in text)
    if "emulsion polymerization" in text and matches >= 4:
        return "high"
    if matches >= 3:
        return "medium"
    return "low"


def doi_url(doi: Any) -> str:
    if not doi:
        return ""
    doi_text = str(doi).removeprefix("https://doi.org/").strip()
    return f"https://doi.org/{doi_text}"


def publication_year(work: dict[str, Any]) -> str:
    publication_date = str(work.get("publication_date") or "")
    if len(publication_date) >= 4 and publication_date[:4].isdigit():
        return publication_date[:4]
    return ""
