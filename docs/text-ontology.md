<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Ontology extraction from text

`auto_ontology/text_ontology/` reads unstructured text (documents, notes,
specifications) and returns a formal ontology: classes with their hierarchy,
atomic triplets between typed entities, and literal attributes. It is separate
from semantic compilation, which builds the semantic layer from database tables,
and it writes nothing to the store.

## Output

```json
{
  "classes": [
    { "name": "Entreprise", "parent": "Organisation", "description": "Société commerciale" }
  ],
  "triplets": [
    {
      "subject": "NVIDIA",
      "subject_type": "Entreprise",
      "predicate": "est_dirige_par",
      "object": "Jensen Huang",
      "object_type": "Personne"
    }
  ],
  "attributes": [
    { "entity": "NVIDIA", "key": "annee_de_fondation", "value": "1993" }
  ]
}
```

## Running it

From the repo root, with the reasoning model configured (`REASONING_API_KEY`,
see `.env`):

```bash
uv run python -m auto_ontology.text_ontology document.txt > ontology.json
```

Standard output carries only the JSON object. Repairs made by normalization are
printed to standard error. `--known-class` and `--known-predicate` (both
repeatable) name concepts that already exist, so they are reused instead of
duplicated.

The backend also serves it on the internal API. The route isn't exposed through
the Next.js gateway yet:

```text
POST /api/text-ontology/extract
{ "text": "...", "known_classes": ["Personne"], "known_predicates": [] }
```

The response is `{ "data": <ontology>, "warnings": [...], "chunks": n }`. It
returns 422 for blank text, 502 when the LLM gives no valid answer, and 503 when
no LLM is configured.

## How the rules are enforced

The system prompt is in
[`prompts/system_prompt.txt`](../auto_ontology/text_ontology/prompts/system_prompt.txt).
The model is asked to follow it, and `normalize.py` then makes the rules hold
whatever the model returned:

| Rule | Enforcement |
| --- | --- |
| 1. No duplicates, singular | Classes that differ only by case, accents or a plural ending (`Personnes` / `Personne`) are merged. A plural is merged only into a singular that is actually present: no name is invented. Individuals spelled two ways (`NVIDIA` / `Nvidia`) become one. Duplicate triplets and attributes are dropped. |
| 2. Naming | Classes become PascalCase (`ServeurGPU`, `DocumentTechnique`). Predicates and attribute keys become ASCII snake_case (`est_dirige_par`, `appartient_a`). |
| 3. Atomic triplets | Left to the prompt. Triplets missing a subject, predicate, object or type are dropped. |
| 4. Hierarchy | `est_un`, `is_a` and `subClassOf` are all read as `est_un`. Between two classes, `est_un` fills the child's `parent`. Every class used as a parent or a type is declared, and cycles are broken. |
| 5. No extrapolation | Repairs use only what the extraction states. An entity typed with two classes of one lineage keeps the most specific type, because the hierarchy implies the other. |

Long texts are split into chunks of about 12,000 characters, at paragraph and
then sentence boundaries. Chunks are extracted in order, and each call is given
the classes, relations and entities found so far, so later chunks reuse earlier
names. If any chunk gets no valid answer, the whole extraction fails. A partial
ontology is never returned as if it were complete.
