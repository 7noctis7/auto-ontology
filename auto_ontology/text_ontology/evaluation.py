# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Measure an extraction against a reference ontology written by hand.

Without a measure, a new model, prompt or chunk size can only be judged by
eye. :func:`evaluate` compares two ontologies and reports, per kind of fact,
how many expected facts were found (recall), how many found facts were
expected (precision), and F1.

Both sides are normalized first, so case, accents, plural classes and
predicate spelling (``estDirigéPar``) do not count as errors. Two levels are
reported for relations, because a model rarely words a predicate exactly as
the reference does:

* ``triplets``: same subject, predicate and object;
* ``links``: the same two entities are related, whatever the predicate or
  the direction. A good ``links`` score with a poor ``triplets`` score means
  the facts are found but named differently.

The bundled corpus (``evaluation_corpus/``) pairs each ``<name>.txt`` with
``<name>.gold.json``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from auto_ontology.text_ontology.models import TextOntology
from auto_ontology.text_ontology.normalize import (
    HIERARCHY_PREDICATE,
    ascii_fold,
    class_parents,
    entity_key,
    normalize_ontology,
)

CORPUS_DIR = Path(__file__).parent / "evaluation_corpus"
_SHOWN = 10


@dataclass
class Score:
    """Matches between an expected set and a found set of facts."""

    expected: int = 0
    found: int = 0
    matched: int = 0
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        return (
            self.matched / self.found
            if self.found
            else (1.0 if not self.expected else 0.0)
        )

    @property
    def recall(self) -> float:
        return self.matched / self.expected if self.expected else 1.0

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0

    def add(self, other: Score) -> None:
        """Pool *other* into this score (micro-average over documents)."""
        self.expected += other.expected
        self.found += other.found
        self.matched += other.matched
        self.missing.extend(other.missing)
        self.extra.extend(other.extra)


KINDS = ("classes", "hierarchy", "entities", "triplets", "links", "attributes")


@dataclass
class Evaluation:
    """One :class:`Score` per kind of fact."""

    scores: dict[str, Score] = field(
        default_factory=lambda: {k: Score() for k in KINDS}
    )

    def add(self, other: Evaluation) -> None:
        for kind in KINDS:
            self.scores[kind].add(other.scores[kind])

    def as_dict(self) -> dict[str, dict[str, object]]:
        return {
            kind: {
                "precision": round(score.precision, 3),
                "recall": round(score.recall, 3),
                "f1": round(score.f1, 3),
                "expected": score.expected,
                "found": score.found,
                "matched": score.matched,
                "missing": score.missing[:_SHOWN],
                "extra": score.extra[:_SHOWN],
            }
            for kind, score in self.scores.items()
        }

    def report(self, title: str = "") -> str:
        """A table a person reads in a terminal."""
        lines = [title] if title else []
        lines.append(
            f"{'':<12}{'précision':>10}{'rappel':>9}{'F1':>7}   attendus/trouvés"
        )
        for kind, score in self.scores.items():
            # Precision means nothing when nothing was found, recall when
            # nothing was expected: show a dash, not a misleading 0 %.
            precision = f"{score.precision:.0%}" if score.found else "—"
            recall = f"{score.recall:.0%}" if score.expected else "—"
            f1 = f"{score.f1:.0%}" if score.found or score.expected else "—"
            lines.append(
                f"{kind:<12}{precision:>10}{recall:>9}{f1:>7}   "
                f"{score.matched}/{score.expected} attendus, {score.found} trouvés"
            )
        for kind in ("triplets", "attributes"):
            score = self.scores[kind]
            if score.missing:
                lines.append(
                    f"  {kind} manquants : " + " ; ".join(score.missing[:_SHOWN])
                )
            if score.extra:
                lines.append(f"  {kind} en trop : " + " ; ".join(score.extra[:_SHOWN]))
        return "\n".join(lines)


def _value(text: str) -> str:
    return " ".join(ascii_fold(text).casefold().split())


def _facts(ontology: TextOntology) -> dict[str, dict[tuple[str, ...], str]]:
    """Each kind of fact as {comparison key: readable form}."""
    classes = {(c.name.casefold(),): c.name for c in ontology.classes}
    hierarchy = {
        (child.casefold(), parent.casefold()): f"{child} est_un {parent}"
        for child, parents in class_parents(ontology).items()
        for parent in parents
    }
    relations = [t for t in ontology.triplets if t.predicate != HIERARCHY_PREDICATE]
    entities: dict[tuple[str, ...], str] = {}
    triplets: dict[tuple[str, ...], str] = {}
    links: dict[tuple[str, ...], str] = {}
    for t in relations:
        subject, obj = entity_key(t.subject), entity_key(t.object)
        entities[(subject,)] = t.subject
        entities[(obj,)] = t.object
        triplets[(subject, t.predicate, obj)] = f"{t.subject} {t.predicate} {t.object}"
        links[tuple(sorted((subject, obj)))] = f"{t.subject} — {t.object}"
    attributes = {}
    for a in ontology.attributes:
        entities[(entity_key(a.entity),)] = a.entity
        attributes[(entity_key(a.entity), _value(a.value))] = (
            f"{a.entity}.{a.key} = {a.value}"
        )
    return {
        "classes": classes,
        "hierarchy": hierarchy,
        "entities": entities,
        "triplets": triplets,
        "links": links,
        "attributes": attributes,
    }


def evaluate(predicted: TextOntology, gold: TextOntology) -> Evaluation:
    """How well *predicted* matches *gold*, per kind of fact.

    Attributes match on entity and value: ``annee_fondation`` and
    ``date_de_creation`` holding 1993 for the same entity are the same fact.
    """
    found = _facts(normalize_ontology(predicted)[0])
    expected = _facts(normalize_ontology(gold)[0])
    evaluation = Evaluation()
    for kind in KINDS:
        want, got = expected[kind], found[kind]
        evaluation.scores[kind] = Score(
            expected=len(want),
            found=len(got),
            matched=len(want.keys() & got.keys()),
            missing=sorted(want[key] for key in want.keys() - got.keys()),
            extra=sorted(got[key] for key in got.keys() - want.keys()),
        )
    return evaluation


@dataclass
class CorpusDocument:
    name: str
    text: str
    gold: TextOntology


def load_corpus(directory: Path = CORPUS_DIR) -> list[CorpusDocument]:
    """Every ``<name>.txt`` that has a ``<name>.gold.json`` beside it."""
    documents = []
    for text_path in sorted(Path(directory).glob("*.txt")):
        gold_path = text_path.with_name(text_path.stem + ".gold.json")
        if gold_path.is_file():
            documents.append(
                CorpusDocument(
                    name=text_path.stem,
                    text=text_path.read_text(encoding="utf-8"),
                    gold=TextOntology.model_validate_json(gold_path.read_text("utf-8")),
                )
            )
    return documents


def evaluate_corpus(
    documents: Iterable[CorpusDocument],
    extract: Callable[[str], TextOntology],
) -> tuple[Evaluation, dict[str, Evaluation]]:
    """Run *extract* on each document: the pooled score, and one per document."""
    total = Evaluation()
    per_document: dict[str, Evaluation] = {}
    for document in documents:
        result = evaluate(extract(document.text), document.gold)
        per_document[document.name] = result
        total.add(result)
    return total, per_document
