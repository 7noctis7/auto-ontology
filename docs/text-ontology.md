<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Ontology extraction from text

`auto_ontology/text_ontology/` reads unstructured text (documents, notes,
specifications) and returns a formal ontology: classes with their hierarchy,
atomic triplets between typed entities, and literal attributes. Results can be
merged into one ontology per project and exported as an interactive graph,
Mermaid, RDF/OWL or Neo4j. It is separate from semantic compilation, which
builds the semantic layer from database tables, but it can reuse that layer's
glossary. It never writes to the store.

The local studio is the way to use it by hand. One command, from the
repository root, opens a page where a document can be dropped:

```bash
uv run ontology serve
```

No Postgres and no login. PDF, EPUB, DOCX, HTML, Markdown and plain text are
accepted. `--fake` runs a deterministic stand-in when no model key is
available, and the page itself includes an example that does not call a
model. The page also types each document, offers a guide, proposed
dashboards, and a read API at `/docs`. Corrections are reused in the next
prompt; they do not train a model. `ontology import`, `ontology ask` and
`ontology mcp` script the same project. The CLI below remains the way to
script one extraction. The page also keeps a schema, saved sets, a lineage
chain, project branches, and `ontology sdk` for a generated Python client.
Export uses OWL 2 Turtle (classes apart from individuals) and JSON-LD with
an `@context`. A competency question says whether the current facts can answer it.

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
    { "entity": "NVIDIA", "key": "annee_fondation", "value": "1993" }
  ]
}
```

## Configuring the LLM

Extraction uses the reasoning model triplet from `.env` at the repo root.

### A local model (LM Studio, Ollama, llama.cpp, vLLM)

```bash
REASONING_API_KEY=lm-studio
REASONING_ENDPOINT=http://127.0.0.1:1234/v1
# REASONING_MODEL is optional: without it, the model the server has loaded is used
```

The key can be any non-empty value. When the endpoint is on this machine or
the private network, extraction talks to it through its OpenAI-compatible API
and works with whatever model is loaded:

- **Model.** `REASONING_MODEL`, or `--model NAME`, picks the model. Leaving it
  unset, or passing `--model auto`, uses the chat model the server has loaded
  (LM Studio's API says which; other servers fall back to `/v1/models`).
  Embedding models are skipped. The model used is printed first.
- **Output format.** The JSON schema is sent first, so the server forces valid
  JSON. If the server or the model refuses it, extraction retries without the
  schema. If the chat template refuses a system message (Gemma, for one), it
  folds the instructions into the user turn. Whatever worked is kept for the
  next chunks.
- **Reading answers.** Reasoning blocks (`<think>...</think>`), Markdown
  fences and text around the JSON are ignored. An answer that does not
  validate is sent back once for repair. An answer cut at the token limit
  keeps its complete items and is reported in the warnings.
- **Context.** A chunk too long for the context the model was loaded with is
  reported as such. Lower `--chunk-chars` or load the model with a longer
  context.

`--provider local` forces this path for a remote OpenAI-compatible server, and
`--provider hosted` forces the application's own client.

The studio (`ontology serve`) takes the same path for a local endpoint. It
reads `.env` the same way, needs no key or model name for a local server, and
records which model answered on each document.

A local model is slower than a hosted one, and a small one extracts better
from short, clean chunks. A good starting point is:

```bash
uv run python -m auto_ontology.text_ontology document.txt --clean \
  --chunk-chars 5000 --timeout 600 --max-tokens 4096 --skip-failed-chunks \
  --log-level INFO -o ontologie.json
```

- `--clean` removes PDF noise first (see [Cleaning PDF text](#cleaning-pdf-text)).
- `--timeout 600` waits up to ten minutes for one answer. The default is
  `LLM_INVOKE_TIMEOUT_S`, else 120 seconds, and it can also be set in `.env`.
- `--max-tokens 4096` stops a model that loops instead of letting it run to
  the limit.
- `--skip-failed-chunks` keeps going when one chunk gets no valid answer.
  The result is then marked `INCOMPLETE` in the warnings and names the
  skipped chunks.

A larger model makes fewer hierarchy mistakes. Any model LM Studio can load
works, so switching models takes no change here.

### A hosted model

Any other endpoint goes through the application's client, with the same
`REASONING_*` settings as the rest of Auto-Ontology.

## Cleaning PDF text

Text copied from a PDF carries noise that a model tries to turn into facts:
diagram labels, code, formulas, numeric tables, page numbers, citation markers
and the reference list. Its lines are also cut at the page width. `--clean`
(or `"clean": true` in the API) removes that noise and rejoins wrapped lines
into paragraphs, which also gives better chunks. It only removes or rejoins
lines and never rewrites the prose. The title block (title, authors, contact)
is kept. To preview what will be extracted, without calling a model:

```bash
uv run python -m auto_ontology.text_ontology clean document.txt -o propre.txt
```

## Command line

Run everything from the repo root. JSON and exports go to standard output
unless `-o` is given. Warnings and errors go to standard error.

```bash
# Extract one document (`extract` can be omitted)
uv run python -m auto_ontology.text_ontology document.txt -o ontologie.json

# Grow a project ontology, document after document
uv run python -m auto_ontology.text_ontology extract doc1.txt --project projet.json
uv run python -m auto_ontology.text_ontology extract doc2.txt --project projet.json

# Merge results produced separately (earliest file first: it wins ties)
uv run python -m auto_ontology.text_ontology merge a.json b.json -o projet.json

# Export
uv run python -m auto_ontology.text_ontology export projet.json -f html -o graphe.html
uv run python -m auto_ontology.text_ontology export projet.json -f mermaid -o graphe.mmd
uv run python -m auto_ontology.text_ontology export projet.json -f turtle -o ontologie.ttl
uv run python -m auto_ontology.text_ontology export projet.json -f cypher -o import.cypher
```

### Extract options

| Option | Effect |
| --- | --- |
| `--project FILE.json` | Reads the file if it exists, tells every LLM call its classes, relations and entities so they are reused, then writes the merged result back to the file. |
| `--glossary` | Reuses the glossary's Term names as classes, so a document about "orders" lands on the existing `PurchaseOrder` class. It needs the application's database (the `POSTGRES_*` settings). |
| `--known-class NAME`, `--known-predicate NAME` | Names to reuse. Both are repeatable. |
| `--chunk-chars N` | Characters of text per LLM call. The default is 12,000. |
| `--timeout SECONDS` | How long to wait for one LLM answer. The default is `LLM_INVOKE_TIMEOUT_S`, else 120. |
| `--max-tokens N` | Longest answer per LLM call. The default is 8,192. |
| `--skip-failed-chunks` | Skips a chunk the LLM cannot answer instead of failing. The result is marked `INCOMPLETE`. |
| `--clean` | Removes PDF noise and rejoins wrapped lines before extracting. |
| `--model NAME` | Model to use instead of `REASONING_MODEL`. `auto` uses the model the local server has loaded. |
| `--provider auto\|local\|hosted` | `auto` (the default) uses the local-server path for an endpoint on this machine or the private network. |
| `--log-level INFO` | Prints one line per chunk, so a long extraction shows its progress. |

## Exports

| Format | File | Use it for |
| --- | --- | --- |
| `html` | `.html` | Opening in a browser. Classes are blue boxes and entities are orange dots. A class with several parents has a dashed outline and a ⚠. Selecting a node highlights its neighbours. The **Classes** tab is the class tree with instance counts, and clicking a class highlights its whole family. The **Table** tab lists every relation and attribute and can be filtered. There are network and hierarchy layouts, PNG export, and light and dark themes. The studio's Download menu inlines the graph library, so that copy opens offline. |
| `mermaid` | `.mmd` | Pasting into anything that renders Mermaid (mermaid.live, GitHub, Notion, Obsidian). Classes are hexagons and individuals are boxes. Dotted arrows are `est_un`. |
| `turtle` | `.ttl` | RDF/OWL tools (Protégé, a triple store, SPARQL). Classes are `owl:Class` with `rdfs:subClassOf`, predicates are `owl:ObjectProperty`, attribute keys are `owl:DatatypeProperty`, and entities are `owl:NamedIndividual`. Integers, decimals, booleans and ISO dates get an `xsd` type. A number with a leading zero stays a string. `--base-iri` sets the namespace. |
| `cypher` | `.cypher` | Neo4j, through cypher-shell or the Browser. The script uses `MERGE` only, so running it twice changes nothing. Classes are `:Classe` nodes linked by `EST_UN`. Entities are `:Entite` nodes that carry their classes as labels and link to them with `A_POUR_TYPE`. |

```bash
cypher-shell -u neo4j -p <password> -f import.cypher
```

## API

The routes are served by the backend and exposed through the Next.js gateway.
All three need `catalog:read`.

| Route | Body | Returns |
| --- | --- | --- |
| `POST /api/text-ontology/extract` | `text`, plus optional `known_classes`, `known_predicates`, `reuse_glossary`, `base` (an ontology to grow), `skip_failed_chunks` and `clean` | `{data, warnings, chunks, failed_chunks}`. It returns 422 for blank text, 502 when the LLM gives no valid answer, and 503 when no LLM is configured. |
| `POST /api/text-ontology/merge` | `ontologies` (earliest first) and optional `known_classes` | `{data, warnings}`. No LLM is called. |
| `POST /api/text-ontology/export` | `ontology`, `format` (`html`, `mermaid`, `turtle` or `cypher`), and optional `base_iri` and `title` | `{data, format, media_type}`, where `data` is the rendered text. |

## How the rules are enforced

The system prompt is in
[`prompts/system_prompt.txt`](../auto_ontology/text_ontology/prompts/system_prompt.txt).
The model is asked to follow it, and `normalize.py` then makes the rules hold
whatever the model returned. Merging runs the same normalization over the
union.

| Rule | Enforcement |
| --- | --- |
| 1. No duplicates, singular | Classes that differ only by case, accents or a plural ending (`Personnes` / `Personne`) are merged. A plural is merged only into a singular that is actually present: no name is invented. Individuals spelled two ways (`NVIDIA` / `Nvidia`) become one. Duplicate triplets and attributes are dropped. |
| 2. Naming | Classes become PascalCase (`ServeurGPU`, `DocumentTechnique`). Predicates and attribute keys become ASCII snake_case (`est_dirige_par`, `appartient_a`). |
| 3. Atomic triplets | Left to the prompt. Triplets missing a subject, predicate, object or type are dropped. A triplet whose object is typed `null` is a literal, so it becomes an attribute. |
| 4. Hierarchy | `est_un`, `is_a` and `subClassOf` are all read as `est_un`. Between two classes, `est_un` fills the child's `parent`. A second parent is never dropped: it stays as an extra `est_un` link (multiple inheritance), and a warning lists the classes with several parents to check. Every class used as a parent or a type is declared. A link that would close a cycle is removed. |
| 5. No extrapolation | Repairs use only what the extraction states. An entity typed with two classes of one lineage keeps the most specific type, because the hierarchy implies the other. Exports state no domain or range. |

Long texts are split into chunks at paragraph and then sentence boundaries.
Chunks are extracted in order, and each call is given the names found so far,
so later chunks and later documents reuse them. If any chunk gets no valid
answer, the whole extraction fails unless `--skip-failed-chunks` is set. Then
the skipped chunks are listed and the result is marked `INCOMPLETE`. A partial
ontology is never returned as if it were complete.
