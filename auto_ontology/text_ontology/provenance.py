# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Attach each fact to the passage that produced it.

The model is not asked to quote: a quote it invented would look like
evidence. The quote is a window of the chunk around the longest name the
fact mentions. Names are aligned with the normalized ontology, including a
plural folded into a singular that is actually present.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from auto_ontology.text_ontology.models import TextOntology
from auto_ontology.text_ontology.normalize import (
    _plural_aliases,
    ascii_fold,
    normalize_predicate,
    to_pascal_case,
    to_snake_case,
)
from auto_ontology.text_ontology.studio_models import (
    AttributeProv,
    ClassProv,
    SourceRef,
    TripletProv,
)


@dataclass(frozen=True)
class RawChunk:
    """One chunk answer, still in the model's own spelling."""

    index: int
    text: str
    ontology: TextOntology


def entity_key(name: str) -> str:
    """Identity of a name: case, accents and spacing do not count."""
    return " ".join(ascii_fold(name).casefold().split())


def evidence_quote(text: str, needles: Sequence[str]) -> str:
    """A short excerpt of *text* around the longest *needle* it contains."""
    folded = text.casefold()
    best_at: int | None = None
    best_len = 0
    for needle in needles:
        cleaned = needle.strip()
        if len(cleaned) < 3:
            continue
        at = folded.find(cleaned.casefold())
        if at >= 0 and (best_at is None or len(cleaned) > best_len):
            best_at = at
            best_len = len(cleaned)
    if best_at is None:
        return " ".join(text.split())[:240]
    start = max(0, best_at - 80)
    end = min(len(text), best_at + best_len + 120)
    snippet = " ".join(text[start:end].split())
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet[:400]


def resolve_provenance(
    final: TextOntology,
    chunks: Sequence[RawChunk],
    *,
    document_id: str,
    filename: str,
) -> tuple[list[TripletProv], list[AttributeProv], list[ClassProv]]:
    """Provenance of *chunks* expressed with the names of *final*."""
    mentions: list[str] = [cls.name for cls in final.classes]
    for chunk in chunks:
        mentions.extend(cls.name for cls in chunk.ontology.classes)
        for triplet in chunk.ontology.triplets:
            mentions.extend(
                (
                    triplet.subject_type,
                    triplet.object_type,
                    triplet.subject,
                    triplet.object,
                )
            )
    pascal = [to_pascal_case(name) for name in mentions if to_pascal_case(name)]
    aliases = _plural_aliases(pascal)
    class_by_fold = {cls.name.casefold(): cls.name for cls in final.classes}
    entity_by_key: dict[str, str] = {}
    for triplet in final.triplets:
        entity_by_key.setdefault(entity_key(triplet.subject), triplet.subject)
        entity_by_key.setdefault(entity_key(triplet.object), triplet.object)
    for attribute in final.attributes:
        entity_by_key.setdefault(entity_key(attribute.entity), attribute.entity)
    for cls in final.classes:
        entity_by_key.setdefault(entity_key(cls.name), cls.name)

    def as_class(name: str) -> str | None:
        token = to_pascal_case(name)
        if not token:
            return None
        target = aliases.get(token, token)
        return class_by_fold.get(target.casefold())

    def as_node(name: str) -> str | None:
        folded = as_class(name)
        token = to_pascal_case(name)
        if folded is not None and (
            token in aliases or entity_key(name) == entity_key(folded)
        ):
            return folded
        return entity_by_key.get(entity_key(name))

    triplet_index = {
        (
            entity_key(item.subject),
            normalize_predicate(item.predicate),
            entity_key(item.object),
        ): item
        for item in final.triplets
    }
    attribute_index = {
        (entity_key(item.entity), to_snake_case(item.key), item.value.strip()): item
        for item in final.attributes
    }
    triplets: dict[tuple[str, str, str], TripletProv] = {}
    attributes: dict[tuple[str, str, str], AttributeProv] = {}
    classes: dict[str, ClassProv] = {}

    def source(chunk: RawChunk, needles: Sequence[str]) -> SourceRef:
        return SourceRef(
            document_id=document_id,
            filename=filename,
            chunk_index=chunk.index,
            quote=evidence_quote(chunk.text, needles),
        )

    for chunk in chunks:
        for raw in chunk.ontology.triplets:
            subject = as_node(raw.subject)
            obj = as_node(raw.object)
            if subject is None or obj is None:
                continue
            predicate = normalize_predicate(raw.predicate)
            found = triplet_index.get((entity_key(subject), predicate, entity_key(obj)))
            if found is None:
                continue
            key = (found.subject, found.predicate, found.object)
            item = triplets.get(key)
            if item is None:
                item = TripletProv(
                    subject=found.subject,
                    predicate=found.predicate,
                    object=found.object,
                )
                triplets[key] = item
            item.sources.append(
                source(chunk, (raw.subject, raw.object, found.subject, found.object))
            )
        for raw in chunk.ontology.attributes:
            owner = as_node(raw.entity)
            if owner is None:
                continue
            key_name = to_snake_case(raw.key)
            found_attr = attribute_index.get(
                (entity_key(owner), key_name, raw.value.strip())
            )
            if found_attr is None:
                continue
            key = (found_attr.entity, found_attr.key, found_attr.value)
            item_attr = attributes.get(key)
            if item_attr is None:
                item_attr = AttributeProv(
                    entity=found_attr.entity,
                    key=found_attr.key,
                    value=found_attr.value,
                )
                attributes[key] = item_attr
            item_attr.sources.append(source(chunk, (raw.entity, raw.value)))
        for raw in chunk.ontology.classes:
            name = as_class(raw.name)
            if name is None:
                continue
            item_cls = classes.get(name)
            if item_cls is None:
                item_cls = ClassProv(name=name)
                classes[name] = item_cls
            item_cls.sources.append(source(chunk, (raw.name, name)))

    return list(triplets.values()), list(attributes.values()), list(classes.values())


def _marker(source: SourceRef) -> tuple[str, int, str]:
    return (source.document_id, source.chunk_index, source.quote)


def _add_sources(current: list[SourceRef], extra: Sequence[SourceRef]) -> None:
    seen = {_marker(source) for source in current}
    for source in extra:
        key = _marker(source)
        if key not in seen:
            current.append(source)
            seen.add(key)


def merge_provenance(
    base_triplets: Sequence[TripletProv],
    base_attributes: Sequence[AttributeProv],
    base_classes: Sequence[ClassProv],
    extra_triplets: Sequence[TripletProv],
    extra_attributes: Sequence[AttributeProv],
    extra_classes: Sequence[ClassProv],
) -> tuple[list[TripletProv], list[AttributeProv], list[ClassProv]]:
    """Union of two provenance sets. The same passage is stored once."""
    triplets = {
        (entity_key(item.subject), item.predicate, entity_key(item.object)): item
        for item in base_triplets
    }
    for item in extra_triplets:
        key = (
            entity_key(item.subject),
            normalize_predicate(item.predicate),
            entity_key(item.object),
        )
        found = triplets.get(key)
        if found is None:
            triplets[key] = item
        else:
            _add_sources(found.sources, item.sources)

    attributes = {
        (entity_key(item.entity), item.key, item.value): item
        for item in base_attributes
    }
    for item in extra_attributes:
        key = (entity_key(item.entity), to_snake_case(item.key), item.value.strip())
        found = attributes.get(key)
        if found is None:
            attributes[key] = item
        else:
            _add_sources(found.sources, item.sources)

    classes = {entity_key(item.name): item for item in base_classes}
    for item in extra_classes:
        found = classes.get(entity_key(item.name))
        if found is None:
            classes[entity_key(item.name)] = item
        else:
            found.name = item.name or found.name
            _add_sources(found.sources, item.sources)
    return list(triplets.values()), list(attributes.values()), list(classes.values())
