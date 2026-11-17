# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Remember corrections and reuse them on the next document.

Nothing here trains a model. A rename becomes an alias, a deleted fact
becomes a rejection, and both are written into the prompt of the next
extraction. A small gold paragraph (the bundled library example) gives a
precision and a recall when that text is seen again. The guide says this
in the same words.
"""

from __future__ import annotations

from auto_ontology.text_ontology.models import OntologyTriplet, TextOntology
from auto_ontology.text_ontology.normalize import normalize_ontology
from auto_ontology.text_ontology.provenance import entity_key
from auto_ontology.text_ontology.sample import sample_ontology
from auto_ontology.text_ontology.studio_models import (
    Alias,
    Edit,
    Example,
    Memory,
    Project,
    RejectedFact,
    ScorePoint,
)
from auto_ontology.text_ontology.store import ProjectStore, now_iso

_ALIAS_LIMIT = 200
_REJECT_LIMIT = 200
_EXAMPLE_LIMIT = 8
_SCORE_LIMIT = 40


def merged_memory(project: Project, store: ProjectStore) -> Memory:
    """Project corrections first, then the home-wide memory."""
    return _union(project.memory, store.load_memory())


def lessons_text(memory: Memory) -> str:
    """The block prepended to the next extraction. Empty when nothing was learned."""
    lines: list[str] = []
    for alias in memory.aliases[-24:]:
        lines.append(
            f"- Écrire « {alias.target} » et non « {alias.source} » ({alias.kind})."
        )
    for fact in memory.rejected[-16:]:
        lines.append(
            "- Ne pas extraire le fait "
            f"({fact.subject}) —[{fact.predicate}]→ ({fact.object})."
        )
    for example in memory.examples[-3:]:
        lines.append(f"- {example.note} Passage : {example.passage[:220]}")
    if not lines:
        return ""
    return (
        "Corrections déjà faites par la personne. Respecte-les, "
        "sans les inventer dans un texte qui ne les contient pas :\n" + "\n".join(lines)
    )


def remember_edit(store: ProjectStore, project: Project, edit: Edit) -> None:
    """Copy one correction into the project and into the home-wide memory."""
    changed = _record(project.memory, project, edit)
    if not changed:
        return
    global_memory = store.load_memory()
    _record(global_memory, project, edit)
    store.save_memory(global_memory)


def align_names(
    ontology: TextOntology, memory: Memory, known: TextOntology
) -> TextOntology:
    """Rewrite spellings the person already corrected, or that already exist."""
    prefer: dict[str, str] = {}
    for alias in memory.aliases:
        if alias.kind in {"entity", "class"} and alias.source and alias.target:
            prefer[entity_key(alias.source)] = alias.target
    for cls in known.classes:
        prefer.setdefault(entity_key(cls.name), cls.name)
    for triplet in known.triplets:
        prefer.setdefault(entity_key(triplet.subject), triplet.subject)
        prefer.setdefault(entity_key(triplet.object), triplet.object)
    if not prefer:
        return ontology

    def rewrite(name: str) -> str:
        return prefer.get(entity_key(name), name)

    rewritten = ontology.model_copy(deep=True)
    for cls in rewritten.classes:
        cls.name = rewrite(cls.name)
        if cls.parent:
            cls.parent = rewrite(cls.parent)
    for triplet in rewritten.triplets:
        triplet.subject = rewrite(triplet.subject)
        triplet.object = rewrite(triplet.object)
        triplet.subject_type = rewrite(triplet.subject_type)
        triplet.object_type = rewrite(triplet.object_type)
    for attribute in rewritten.attributes:
        attribute.entity = rewrite(attribute.entity)
    return rewritten


def drop_rejected(ontology: TextOntology, memory: Memory) -> TextOntology:
    """Remove facts the person has already refused."""
    if not memory.rejected:
        return ontology
    blocked = {
        (entity_key(fact.subject), fact.predicate, entity_key(fact.object))
        for fact in memory.rejected
    }
    kept = [
        triplet
        for triplet in ontology.triplets
        if (entity_key(triplet.subject), triplet.predicate, entity_key(triplet.object))
        not in blocked
    ]
    if len(kept) == len(ontology.triplets):
        return ontology
    return TextOntology(
        classes=list(ontology.classes),
        triplets=kept,
        attributes=list(ontology.attributes),
    )


def record_score(project: Project, text: str) -> ScorePoint:
    """One point on the quality curve, with gold precision when the text is the example."""
    point = ScorePoint(
        at=now_iso(),
        quality=quality_score(project),
        note="couverture des passages et morceaux réussis",
    )
    gold = gold_scores(project.ontology, text)
    if gold is not None:
        precision, recall, f1 = gold
        point.precision = precision
        point.recall = recall
        point.f1 = f1
        point.note = "jeu d'or : l'exemple de la bibliothèque"
    project.memory.scores.append(point)
    del project.memory.scores[:-_SCORE_LIMIT]
    return point


def quality_score(project: Project) -> float:
    """0 to 1. Provenance and successful chunks, not a model score."""
    facts = len(project.ontology.triplets) + len(project.ontology.attributes)
    linked = 0
    for item in (*project.triplets, *project.attributes):
        if item.sources:
            linked += 1
    provenance = linked / facts if facts else 0.0
    failed = sum(len(document.chunks_failed) for document in project.documents)
    total = sum(document.chunks_total for document in project.documents) or 1
    return round(0.6 * provenance + 0.4 * (1 - failed / total), 3)


def gold_scores(ontology: TextOntology, text: str) -> tuple[float, float, float] | None:
    """Precision, recall and F1 against the bundled example, or None."""
    if "camille martin" not in text.casefold():
        return None
    expected, _warnings = normalize_ontology(sample_ontology())
    expected_keys = {_fact_key(triplet) for triplet in expected.triplets}
    got_keys = {_fact_key(triplet) for triplet in ontology.triplets}
    if not expected_keys:
        return None
    hit = len(expected_keys & got_keys)
    precision = hit / len(got_keys) if got_keys else 0.0
    recall = hit / len(expected_keys)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return round(precision, 3), round(recall, 3), round(f1, 3)


def training_rows(project: Project) -> list[dict[str, object]]:
    """Validated triplets, plus rejected ones, ready to write as JSONL."""
    rows: list[dict[str, object]] = []
    for fact in project.triplets:
        quote = fact.sources[0].quote if fact.sources else ""
        rows.append(
            {
                "text": quote,
                "subject": fact.subject,
                "predicate": fact.predicate,
                "object": fact.object,
                "accepted": True,
            }
        )
    for fact in project.memory.rejected:
        rows.append(
            {
                "text": fact.passage,
                "subject": fact.subject,
                "predicate": fact.predicate,
                "object": fact.object,
                "accepted": False,
            }
        )
    return rows


def _fact_key(triplet: OntologyTriplet) -> tuple[str, str, str]:
    return (entity_key(triplet.subject), triplet.predicate, entity_key(triplet.object))


def _record(memory: Memory, project: Project, edit: Edit) -> bool:
    if edit.op in {"rename_entity", "merge_entities"} and edit.source and edit.target:
        _add_alias(memory, "entity", edit.source, edit.target)
        return True
    if edit.op == "rename_class" and edit.old and edit.new:
        _add_alias(memory, "class", edit.old, edit.new)
        return True
    if edit.op == "delete_triplet" and edit.subject and edit.predicate:
        passage = _quote(project, edit.subject, edit.predicate, edit.object)
        _add_rejected(memory, edit.subject, edit.predicate, edit.object, passage)
        if passage:
            _add_example(
                memory,
                passage,
                "Fait retiré par la personne : "
                f"({edit.subject}) {edit.predicate} ({edit.object}).",
            )
        return True
    if edit.op == "set_genre" and edit.new:
        _add_example(
            memory,
            edit.document_id,
            f"Le document {edit.document_id} est de type {edit.new}, pas une estimation.",
        )
        return True
    return False


def _add_alias(memory: Memory, kind: str, source: str, target: str) -> None:
    if source == target:
        return
    memory.aliases = [
        alias
        for alias in memory.aliases
        if not (alias.kind == kind and alias.source == source)
    ]
    memory.aliases.append(Alias(kind=kind, source=source, target=target))
    del memory.aliases[:-_ALIAS_LIMIT]


def _add_rejected(
    memory: Memory, subject: str, predicate: str, obj: str, passage: str
) -> None:
    memory.rejected.append(
        RejectedFact(
            subject=subject, predicate=predicate, object=obj, passage=passage[:400]
        )
    )
    del memory.rejected[:-_REJECT_LIMIT]


def _add_example(memory: Memory, passage: str, note: str) -> None:
    if not passage:
        return
    memory.examples.append(Example(passage=passage[:400], note=note[:240]))
    del memory.examples[:-_EXAMPLE_LIMIT]


def _quote(project: Project, subject: str, predicate: str, obj: str) -> str:
    for fact in project.triplets:
        if (
            fact.subject == subject
            and fact.predicate == predicate
            and fact.object == obj
            and fact.sources
        ):
            return fact.sources[0].quote
    return ""


def _union(left: Memory, right: Memory) -> Memory:
    merged = left.model_copy(deep=True)
    seen = {(alias.kind, alias.source) for alias in merged.aliases}
    for alias in right.aliases:
        if (alias.kind, alias.source) not in seen:
            merged.aliases.append(alias)
    seen_facts = {
        (fact.subject, fact.predicate, fact.object) for fact in merged.rejected
    }
    for fact in right.rejected:
        key = (fact.subject, fact.predicate, fact.object)
        if key not in seen_facts:
            merged.rejected.append(fact)
    if not merged.examples:
        merged.examples = list(right.examples[-_EXAMPLE_LIMIT:])
    return merged
