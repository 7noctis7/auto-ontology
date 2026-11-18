# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deterministic enforcement of the modeling rules on an LLM extraction.

The system prompt asks the model for these rules; this module makes them hold
whatever the model returns, so a caller never sees an ontology that breaks them:

* Rule 1, anti-duplicates. Classes that differ only by case, accents or a
  plural ending (``Personnes`` and ``Personne``) collapse into one, and an
  individual spelled two ways (``NVIDIA`` and ``Nvidia``) becomes one node.
  A plural class is folded only into a singular form that is actually
  present: nothing here invents a new name.
* Rule 2, naming. Classes are PascalCase; predicates and attribute keys are
  ASCII snake_case.
* Rule 4, hierarchy. An ``est_un`` triplet between two classes fills that
  class's ``parent``; every class named as a parent or as a triplet type is
  declared; cycles are broken.
* Rule 5, zero extrapolation. Repairs only use what the extraction itself
  states. When an individual is typed with two classes of the same lineage,
  the most specific is kept, because the hierarchy implies the other.
"""

from __future__ import annotations

import itertools
import re
import unicodedata
from collections.abc import Iterable, Sequence

from auto_ontology.text_ontology.models import (
    OntologyAttribute,
    OntologyClass,
    OntologyTriplet,
    TextOntology,
)

# The predicate for a subclass link. The prompt names it `est_un`; models also
# write the English and RDFS spellings, or the feminine form.
HIERARCHY_PREDICATE = "est_un"
_HIERARCHY_PREDICATES = frozenset(
    {
        "est_un",
        "est_une",
        "est_un_type_de",
        "est_une_sorte_de",
        "sous_classe_de",
        "is_a",
        "subclass_of",
        "sub_class_of",
    }
)

# NFKD splits accented letters but not ligatures, which French uses (oeuvre).
_LIGATURES = str.maketrans({"œ": "oe", "Œ": "Oe", "æ": "ae", "Æ": "Ae", "ß": "ss"})

# Separators: anything that is neither a letter nor a digit.
_SEPARATORS = re.compile(r"[\W_]+")

# Words inside one ASCII token, in order of preference: a plural acronym
# (``APIs``), an acronym not followed by a lowercase letter (``GPU`` in
# ``ServeurGPU``), a capitalised or lowercase word, a number.
_WORDS = re.compile(r"[A-Z]{2,}s(?![a-z])|[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")

# Past this many singular/plural combinations a class name is left alone: the
# name has too many words for the plural check to be cheap, and real class
# names are far shorter.
_MAX_SINGULAR_COMBINATIONS = 256


def ascii_fold(text: str) -> str:
    """*text* without accents or ligatures. Letters with no ASCII form stay."""
    decomposed = unicodedata.normalize("NFKD", text.translate(_LIGATURES))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _tokens(text: str) -> list[str]:
    """*text* split on separators, accents removed."""
    return [t for t in _SEPARATORS.split(ascii_fold(text)) if t]


def _words(text: str) -> list[str]:
    """*text* split on separators and camelCase boundaries.

    A token with letters that have no ASCII form is kept whole rather than
    dropped, so a non-Latin name still yields a name.
    """
    words: list[str] = []
    for token in _tokens(text):
        words.extend(_WORDS.findall(token) if token.isascii() else [token])
    return words


def split_words(text: str) -> list[str]:
    """*text* split on separators and camelCase boundaries (``ServeurGPU`` -> 2)."""
    return _words(text)


def entity_key(name: str) -> str:
    """How normalization tells two spellings of one individual apart, or not."""
    return _entity_key(name)


def to_pascal_case(name: str) -> str:
    """``"document technique"`` → ``DocumentTechnique``; ``"ProjetIA"`` stays.

    The inner case of each word is kept, so acronyms survive (``Serveur GPU``
    → ``ServeurGPU``). An all-caps name of several words is read as words, not
    acronyms (``DOCUMENT_TECHNIQUE`` → ``DocumentTechnique``).
    """
    tokens = _tokens(name)
    shouting = len(tokens) > 1 and all(t == t.upper() for t in tokens)
    if shouting:
        tokens = [t.lower() for t in tokens]
    return "".join(t[:1].upper() + t[1:] for t in tokens)


def to_snake_case(name: str) -> str:
    """``"est dirigé par"`` / ``estDirigePar`` → ``est_dirige_par``."""
    return "_".join(w.lower() for w in _words(name))


def normalize_predicate(name: str) -> str:
    """A predicate in snake_case, with every subclass spelling read as ``est_un``."""
    predicate = to_snake_case(name)
    return HIERARCHY_PREDICATE if predicate in _HIERARCHY_PREDICATES else predicate


def _entity_key(name: str) -> str:
    """Identity of an individual: case, accents and spacing do not count."""
    return " ".join(ascii_fold(name).casefold().split())


def _clean_text(text: str) -> str:
    return " ".join(text.split())


def _singular_options(word: str) -> list[str]:
    """The singular forms *word* could be the plural of. Empty for most words."""
    lower = word.lower()
    options: list[str] = []
    if len(word) > 3 and lower.endswith("aux"):
        options.append(word[:-3] + "al")  # Journaux → Journal
    if len(word) > 3 and lower.endswith("ies"):
        options.append(word[:-3] + "y")  # Companies → Company
    if len(word) > 3 and lower.endswith("es"):
        options.append(word[:-2])  # Classes → Class
    if len(word) > 2 and lower[-1] in "sx" and not lower.endswith("ss"):
        options.append(word[:-1])  # Personnes → Personne, Bureaux → Bureau
    return options


def _plural_aliases(names: Sequence[str]) -> dict[str, str]:
    """Map each plural class name to the singular one present in *names*.

    ``DocumentsTechniques`` maps to ``DocumentTechnique`` only when that name
    is also in *names*. The shortest match wins; chains resolve to their end.
    """
    by_key = {name.casefold(): name for name in names}
    aliases: dict[str, str] = {}
    for name in names:
        options = [[w, *_singular_options(w)] for w in _words(name)]
        combinations = 1
        for opts in options:
            combinations *= len(opts)
        if combinations <= 1 or combinations > _MAX_SINGULAR_COMBINATIONS:
            continue
        best: str | None = None
        for combo in itertools.product(*options):
            target = by_key.get("".join(combo).casefold())
            if target is None or target.casefold() == name.casefold():
                continue
            if best is None or len(target) < len(best):
                best = target
        if best is not None:
            aliases[name] = best

    resolved: dict[str, str] = {}
    for name in aliases:
        target, seen = name, set()
        while target in aliases and target not in seen:
            seen.add(target)
            target = aliases[target]
        resolved[name] = target
    return resolved


# Type names a model writes for a literal (a year, a city name) instead of a
# class. They are not classes: such a triplet states an attribute.
_LITERAL_TYPES = frozenset({"null", "none", "nil", "na", "literal", "litteral"})


def _is_literal_type(name: str | None) -> bool:
    return name is not None and to_pascal_case(name).casefold() in _LITERAL_TYPES


class _ClassNames:
    """Canonical spelling of every class name the extraction mentions."""

    def __init__(self, mentions: Iterable[str]) -> None:
        # First spelling wins among names equal but for case: the caller passes
        # known classes first, then the declared ones, so reuse is preferred.
        spelling: dict[str, str] = {}
        for mention in mentions:
            pascal = to_pascal_case(mention)
            if pascal and not _is_literal_type(pascal):
                spelling.setdefault(pascal.casefold(), pascal)
        self._spelling = spelling
        self._aliases = _plural_aliases(list(spelling.values()))

    def canonical(self, name: str | None) -> str | None:
        """The class *name* resolves to, or ``None`` for a blank name."""
        if name is None:
            return None
        pascal = to_pascal_case(name)
        if not pascal or _is_literal_type(pascal):
            return None
        spelled = self._spelling.get(pascal.casefold(), pascal)
        return self._aliases.get(spelled, spelled)


def _break_cycles(parents: dict[str, str | None], warnings: list[str]) -> None:
    """Drop the parent link that closes each cycle in the hierarchy."""
    for start in list(parents):
        path: list[str] = []
        on_path: set[str] = set()
        node: str | None = start
        while node is not None and node not in on_path:
            on_path.add(node)
            path.append(node)
            node = parents.get(node)
        if node is not None:
            child = path[-1]
            warnings.append(
                f"Hierarchy cycle {child} -> {node}: removed the parent of {child}."
            )
            parents[child] = None


def _ancestors(name: str, links: dict[str, list[str]]) -> set[str]:
    """Every class above *name*, through all of its parents."""
    found: set[str] = set()
    pending = list(links.get(name, ()))
    while pending:
        node = pending.pop()
        if node not in found:
            found.add(node)
            pending.extend(links.get(node, ()))
    return found


def _most_specific(types: set[str], links: dict[str, list[str]]) -> str | None:
    """The one type in *types* that specializes all the others, if any."""
    for candidate in types:
        if types - {candidate} <= _ancestors(candidate, links):
            return candidate
    return None


def class_parents(ontology: TextOntology) -> dict[str, list[str]]:
    """Every parent of each class: its ``parent``, then its other ``est_un`` links.

    Reads a normalized ontology, where class-level ``est_un`` triplets name
    their classes exactly.
    """
    found = {c.name: [c.parent] if c.parent else [] for c in ontology.classes}
    for t in ontology.triplets:
        if (
            t.predicate == HIERARCHY_PREDICATE
            and t.subject in found
            and t.object in found
            and t.object not in found[t.subject]
        ):
            found[t.subject].append(t.object)
    return found


def multi_parent_summary(ontology: TextOntology) -> str | None:
    """One warning naming the classes with several parents, or ``None``.

    Several parents can be right (multiple inheritance) but are often a small
    model's mistake, so they are listed for a person to check.
    """
    several = {n: ps for n, ps in class_parents(ontology).items() if len(ps) > 1}
    if not several:
        return None
    listed = "; ".join(f"{n} ({', '.join(ps)})" for n, ps in several.items())
    return f"Classes with several parents, check which are right: {listed}."


def normalize_ontology(
    raw: TextOntology,
    known_classes: Sequence[str] = (),
) -> tuple[TextOntology, list[str]]:
    """Return *raw* with the modeling rules enforced, and what was repaired.

    *known_classes* are names that already exist (an earlier extraction, a
    glossary): a plural or differently-cased class in *raw* resolves to them.
    They are not emitted unless the extraction uses them.
    """
    warnings: list[str] = []
    names = _ClassNames(
        [
            *known_classes,
            *(c.name for c in raw.classes),
            *(c.parent for c in raw.classes if c.parent),
            *(n for t in raw.triplets for n in (t.subject_type, t.object_type)),
        ]
    )

    # --- Classes: one per canonical name, first non-empty value of each field.
    classes: dict[str, OntologyClass] = {}
    # A second parent is never dropped: it becomes an `est_un` link of its own
    # (multiple inheritance), and the warning says which one to check.
    extra_parents: list[tuple[str, str]] = []
    for declared in raw.classes:
        name = names.canonical(declared.name)
        if name is None:
            warnings.append("Dropped a class with an empty name.")
            continue
        parent = names.canonical(declared.parent)
        if parent == name:
            warnings.append(f"Class {name} was its own parent: parent removed.")
            parent = None
        description = _clean_text(declared.description)
        if to_pascal_case(declared.name) != name:
            warnings.append(f"Class {declared.name!r} merged into {name}.")
        existing = classes.get(name)
        if existing is None:
            classes[name] = OntologyClass(
                name=name, parent=parent, description=description
            )
            continue
        if existing.parent is None:
            existing.parent = parent
        elif parent is not None and parent != existing.parent:
            warnings.append(
                f"Class {name} has two parents ({existing.parent}, {parent}): "
                f"both kept, {parent} as an extra est_un link. Check which is right."
            )
            extra_parents.append((name, parent))
        if not existing.description:
            existing.description = description

    def declare(name: str, reason: str) -> None:
        if name not in classes:
            classes[name] = OntologyClass(name=name, parent=None, description="")
            warnings.append(f"Class {name} {reason} but was not declared: added.")

    for cls in list(classes.values()):
        if cls.parent is not None:
            declare(cls.parent, f"is the parent of {cls.name}")
    for child, parent in extra_parents:
        declare(parent, f"is a parent of {child}")

    # --- Triplets: canonical names, predicate and types; drop incomplete ones.
    entity_spelling: dict[str, str] = {}

    def entity(name: str) -> str:
        cleaned = _clean_text(name)
        return entity_spelling.setdefault(_entity_key(cleaned), cleaned)

    triplets: list[OntologyTriplet] = []
    literal_facts: list[OntologyTriplet] = []
    for t in raw.triplets:
        subject, obj = entity(t.subject), entity(t.object)
        predicate = normalize_predicate(t.predicate)
        if _is_literal_type(t.object_type) and not _is_literal_type(t.subject_type):
            literal_facts.append(t)  # kept below as an attribute
            continue
        subject_type = names.canonical(t.subject_type)
        object_type = names.canonical(t.object_type)
        if not (subject and obj and predicate and subject_type and object_type):
            warnings.append(
                f"Dropped an incomplete triplet ({t.subject!r}, {t.predicate!r}, "
                f"{t.object!r})."
            )
            continue
        declare(subject_type, f"types {subject}")
        declare(object_type, f"types {obj}")
        triplets.append(
            OntologyTriplet(
                subject=subject,
                subject_type=subject_type,
                predicate=predicate,
                object=obj,
                object_type=object_type,
            )
        )

    # --- Hierarchy: `est_un` between two classes is a subclass link (rule 4).
    class_links: list[OntologyTriplet] = []
    for t in triplets:
        if t.predicate != HIERARCHY_PREDICATE:
            continue
        child, parent = names.canonical(t.subject), names.canonical(t.object)
        if child not in classes or parent not in classes or child == parent:
            continue
        # A class-level fact names classes, so spell them as the classes are.
        t.subject, t.object = child, parent
        class_links.append(t)
        # A second parent stated this way is multiple inheritance, kept as is
        # and reported by `multi_parent_summary`, so re-normalizing a project
        # does not warn again about every one of them.
        if classes[child].parent is None:
            classes[child].parent = parent

    parents = {name: cls.parent for name, cls in classes.items()}
    _break_cycles(parents, warnings)
    for name, cls in classes.items():
        cls.parent = parents[name]

    # Every other parent is an extra `est_un` link, kept unless it would close
    # a cycle through the parents and the links already kept.
    links = {name: [p] if p is not None else [] for name, p in parents.items()}
    dropped: set[int] = set()

    def link(child: str, parent: str, triplet: OntologyTriplet | None) -> None:
        if parent in links[child]:
            return
        if child == parent or child in _ancestors(parent, links):
            warnings.append(
                f"Link {child} est_un {parent} would close a hierarchy cycle: removed."
            )
            if triplet is not None:
                dropped.add(id(triplet))
            return
        links[child].append(parent)
        if triplet is None:
            triplets.append(
                OntologyTriplet(
                    subject=child,
                    subject_type=child,
                    predicate=HIERARCHY_PREDICATE,
                    object=parent,
                    object_type=parent,
                )
            )

    for child, parent in extra_parents:
        link(child, parent, None)
    for t in class_links:
        if t.object != classes[t.subject].parent:
            link(t.subject, t.object, t)
    triplets = [t for t in triplets if id(t) not in dropped]

    # --- One type per individual when its types are one lineage.
    types_of: dict[str, set[str]] = {}
    for t in triplets:
        types_of.setdefault(_entity_key(t.subject), set()).add(t.subject_type)
        types_of.setdefault(_entity_key(t.object), set()).add(t.object_type)
    specific = {
        key: best
        for key, types in types_of.items()
        if len(types) > 1 and (best := _most_specific(types, links)) is not None
    }
    for t in triplets:
        t.subject_type = specific.get(_entity_key(t.subject), t.subject_type)
        t.object_type = specific.get(_entity_key(t.object), t.object_type)

    unique_triplets: dict[tuple[str, str, str], OntologyTriplet] = {}
    for t in triplets:
        key = (_entity_key(t.subject), t.predicate, _entity_key(t.object))
        unique_triplets.setdefault(key, t)

    # --- Attributes: snake_case keys, canonical entities, no empty values.
    unique_attributes: dict[tuple[str, str, str], OntologyAttribute] = {}
    for a in raw.attributes:
        owner, key, value = entity(a.entity), to_snake_case(a.key), a.value.strip()
        if not (owner and key and value):
            warnings.append(
                f"Dropped an incomplete attribute ({a.entity!r}, {a.key!r}, "
                f"{a.value!r})."
            )
            continue
        unique_attributes.setdefault(
            (_entity_key(owner), key, value),
            OntologyAttribute(entity=owner, key=key, value=value),
        )

    # A triplet whose object is a literal is an attribute. Keep it as one unless
    # the extraction already states that value for that entity.
    stated = {(owner, value) for owner, _, value in unique_attributes}
    for t in literal_facts:
        owner, key, value = entity(t.subject), to_snake_case(t.predicate), t.object
        value = _clean_text(value)
        if not (owner and key and value):
            warnings.append(f"Dropped an incomplete triplet ({t.subject!r}).")
            continue
        if (_entity_key(owner), value) in stated:
            continue
        stated.add((_entity_key(owner), value))
        unique_attributes.setdefault(
            (_entity_key(owner), key, value),
            OntologyAttribute(entity=owner, key=key, value=value),
        )
        warnings.append(
            f"Triplet ({owner}, {t.predicate}, {value}) read as an attribute."
        )

    ontology = TextOntology(
        classes=list(classes.values()),
        triplets=list(unique_triplets.values()),
        attributes=list(unique_attributes.values()),
    )
    return ontology, warnings
