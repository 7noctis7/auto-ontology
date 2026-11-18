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
`ontology mcp` script the same project; [Daily use](#daily-use) covers
`open`, `brief`, tables, playbooks and the MCP tools. The CLI below remains the way to
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
uv run ontology document.txt --clean \
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
uv run ontology clean document.txt -o propre.txt
```

## Command line

Run everything from the repo root. JSON and exports go to standard output
unless `-o` is given. Warnings and errors go to standard error.

```bash
# Extract one document (`extract` can be omitted)
uv run ontology document.txt -o ontologie.json

# Grow a project ontology, document after document
uv run ontology extract doc1.txt --project projet.json
uv run ontology extract doc2.txt --project projet.json

# Merge results produced separately (earliest file first: it wins ties)
uv run ontology merge a.json b.json -o projet.json

# Export
uv run ontology export projet.json -f html -o graphe.html
uv run ontology export projet.json -f mermaid -o graphe.mmd
uv run ontology export projet.json -f turtle -o ontologie.ttl
uv run ontology export projet.json -f cypher -o import.cypher
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
| `--lang auto\|fr\|en\|…` | Language of class, relation and attribute names. `auto` keeps the project's language, else the text's. Without it, a French prompt on an English text mixed `Block` and `Bloc`. |
| `--overlap-chars N` | End of the previous chunk restated as context, so a pronoun or a fact across a cut is understood. The default is 600; 0 turns it off. |
| `--log-level INFO` | Prints one line per chunk, so a long extraction shows its progress. |

Inputs can be text or Markdown files, or PDF, EPUB, DOCX and HTML, read the
way the studio reads them. A text file in another encoding than UTF-8 is read
too. Each chunk's message also tells the model that `est_un` links two
classes only (an entity's type goes in `subject_type` or `object_type`).

The model is chosen as in the studio: `ONTOLOGY_LLM_*`, then `REASONING_*`
(and their fallbacks), then the settings saved in the studio, then the NVIDIA
defaults. The same `.env` therefore picks the same model in both.

`ontology` and `python -m auto_ontology.text_ontology` are the same command:
both accept `extract`, `merge`, `export`, `clean`, `eval` and the studio's
`serve`, `import`, `ask`, `mcp` and `sdk`. `ontology --help` lists them all.

## Measuring extraction quality

`eval` scores an extraction against a reference written by hand: precision,
recall and F1 for classes, hierarchy, entities, triplets, links and
attributes. Both sides are normalized first. `links` counts two entities as
related whatever the predicate's wording or direction, so a good `links`
score with a poor `triplets` score means the facts are found but named
differently.

```bash
# Compare an extraction with a reference
uv run ontology eval found.json gold.json

# Run the configured model on the bundled corpus (two French texts, one English)
uv run ontology eval --corpus --lang auto

# Your own corpus: <name>.txt next to <name>.gold.json
uv run ontology eval --corpus mon-corpus/ --json -o scores.json
```

Run it before and after changing the model, the prompt or `--chunk-chars`.

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

## Large projects

The studio's view is rebuilt on every display; its cost now grows linearly
with the project. Past 1,500 nodes (`ONTOLOGY_GRAPH_MAX_NODES`), the page
draws the most connected ones and says so; the others stay in the glossary
and the facts, and a search for one says where to find it. The class matrix
keeps the 25 most connected classes. While an extraction runs, every API
route that writes answers 409 instead of being overwritten by the
extraction's final save.

## Daily use

The studio keeps one folder per project under `~/AutoOntology`
(`ONTOLOGY_HOME`). These commands work on the project the page has open.

```bash
uv run ontology open ~/Dossiers/Fournisseurs --playbook audit-contrats
uv run ontology import ~/Vault ~/Downloads/export-notion.zip relance.eml
uv run ontology import --paste          # the clipboard, as a document
uv run ontology brief --since 24h       # what came in, what to check
uv run ontology diff --since 7d         # facts added and removed
uv run ontology check                   # the playbook's checks
uv run ontology tables
uv run ontology sql "SELECT * FROM onto_facts LIMIT 5"
uv run ontology ask "budget des contrats qui expirent" --data
uv run ontology report meeting --document compte-rendu --out cr.md
uv run ontology report compare "ACME" "Orbital Lab"
uv run ontology rules add "Un contrat de plus de 50 k€ demande deux signatures." --source "Comité du 18/11"
uv run ontology mcp --allow-writes
```

### What can be brought in

`ontology import`, the watched folder (`ontology open`, or `serve --watch`)
and the page share one intake (`inbox.py`):

| Input | Becomes |
| --- | --- |
| PDF, EPUB, DOCX, HTML, Markdown, text | a document, extracted by the model |
| `.eml` | a document (subject, sender, recipients, date, the new text without quoted replies), and each supported attachment as its own document or table |
| an Obsidian vault (a folder) | its notes, read recursively; hidden folders (`.obsidian`, `.trash`), `node_modules` and the studio's own home are skipped. Front matter, `[[links|aliases]]`, embeds and callout markers read as prose |
| a Notion export (`.zip`) | its pages and databases; the 32-character page ids are dropped from names. The archive is checked for an abnormal expansion first |
| CSV, TSV, Excel, Parquet, SQLite, DuckDB | read-only tables in the project's `data.duckdb`, profiled (types, empty values, samples); no model needed |

The same text is not extracted twice, whatever its file name, its line
breaks or the model: the second copy is reported as a duplicate. `--force`
extracts it again (with another model, for instance) and replaces the
first. An extraction that left chunks unanswered runs again without
`--force`; the chunk cache makes that cost only the missing chunks.

Every arrival is written to `activity.jsonl` in the project folder,
duplicates and failures included (the last 2,000 lines are kept).

### brief and diff

`brief` lists the documents, tables, facts and certified rules added since a
moment (`24h`, `7d`, `2w`, `today`, `hier`, `2026-11-01`), the files that
were skipped as known, and what needs a look: unreadable files, files that
arrived with no model configured, chunks the model did not answer, classes
with several parents, entities linked to nothing, and the playbook's
findings. `diff` compares the project with the snapshot taken just before
that moment (the undo history keeps the last 30).

### Documents and data in one query

Next to the tables, every query sees four views built from the facts:

| View | Columns |
| --- | --- |
| `onto_facts` | `subject`, `subject_key`, `subject_type`, `predicate`, `object`, `object_key`, `object_type`, `document`, `quote` |
| `onto_attributes` | `entity`, `entity_key`, `key`, `value`, `document`, `quote` |
| `onto_entities` | `name`, `key`, `class`, `facts` |
| `onto_rules` | `text`, `source`, `created_at`, `tags` |

`okey(text)` is the join key: case, accents, punctuation and a trailing
legal form (SA, SAS, Inc, GmbH…) do not count, so "ACME S.A." in a
spreadsheet meets "Acme" in a contract:

```sql
SELECT c.client, c.plafond, f.object AS ville, f.quote
FROM clients c
JOIN onto_facts f ON okey(c.client) = f.subject_key
WHERE f.predicate = 'est_situe_a'
```

Every query is one `SELECT`, checked before it runs, on a DuckDB connection
opened read-only with external access off: it cannot read a file, attach a
database or change a setting. Rows are capped and a query is stopped after
20 seconds.

`ontology ask --data` (and `POST /api/v1/ask/data`) has the configured model
write that query from the schema, runs it, sends the error back once if it
fails, then phrases the answer from the rows only, with the passages behind
them. The SQL is always shown.

### Playbooks

A playbook says what a project is for. Three come with the studio:
`audit-contrats`, `suivi-financier` and `base-connaissances`. A YAML file in
`~/AutoOntology/playbooks/` adds one, or replaces a bundled one with the same
`id`. A project's playbook:

- adds its `focus`, `classes` and `predicates` to every extraction prompt
  (the project's own names still win);
- adds `checks`, run without a model by `ontology check`, `brief`, the page
  and MCP `check_playbook`;
- lists the questions the project should answer.

```yaml
id: recrutement
name: Recrutement
description: Candidats, postes et entretiens.
focus: |
  Relève chaque candidat, le poste visé, les dates d'entretien et la décision.
classes: [Candidat, Poste, Entretien]
predicates: [postule_a, passe_entretien, est_retenu_pour]
questions:
  - Quels candidats attendent une réponse ?
checks:
  - id: sans-poste
    title: Candidat sans poste
    kind: missing_relation        # or missing_attribute
    severity: haute               # haute, moyenne, basse
    classes: [Candidat]           # subclasses count too
    predicates: [postule_a]
  - id: entretien-proche
    title: Entretien dans les 7 jours
    kind: date_within             # or date_past
    days: 7
    attributes: [date_entretien]
  - id: salaire-eleve
    title: Prétention au-dessus de 80 k€
    kind: value_above
    threshold: 80000
    attributes: [pretention_salariale]
  - id: sans-decision
    title: Entretien passé sans décision
    kind: sql                     # one read-only SELECT; each row is a finding
    sql: SELECT entity FROM onto_attributes WHERE key = 'statut' AND value = 'en attente'
```

Dates are read as `2027-03-31`, `31/03/2027` or `31 mars 2027`; amounts as
`50 000 €`, `1,2 M€` or `120k`. A finding names its source document.
`ontology check` exits with 1 when a finding is of high priority, so it can
run in a scheduled job.

### Rules and reports

A rule is stated, not extracted: "a contract over 50 k€ needs two
signatures". `ontology rules add`, the page (Documents view) and MCP
`certify_rule` record one with its source; `ontology rules retire <id>` keeps
it for the record but stops listing it. Rules appear in `brief` and in the
`onto_rules` view.

`ontology report meeting` sorts one document's facts into participants,
decisions, actions and figures, each with its passage: the skeleton of a
meeting summary, built without a model. `ontology report compare A B` puts
what the project knows about a few entities side by side.

### MCP server

`ontology mcp` serves the current project over standard input:

```json
{
  "mcpServers": {
    "ontology": {
      "command": "uv",
      "args": ["--directory", "/path/to/auto-ontology", "run", "ontology", "mcp"]
    }
  }
}
```

| Tool | Does |
| --- | --- |
| `brief` | what came in since a moment, and what to check |
| `search`, `get_concept`, `facts`, `lineage`, `list_concepts` | the facts and where they come from |
| `ask_question` | an answer from the facts, with the passages |
| `list_tables`, `describe_table`, `run_sql` | tables and `onto_*` views, one read-only `SELECT` |
| `export_report` | a meeting summary or a comparison table, in Markdown |
| `check_playbook` | the playbook's findings |
| `preview_action` | what a rename or a merge would change |
| `remember_fact`, `certify_rule` | only with `--allow-writes` (below) |

Every tool carries MCP annotations (`readOnlyHint`, `destructiveHint`), the
server negotiates the protocol version (2025-06-18 down to 2024-11-05) and
returns structured content when the client supports it. The first version's
names (`neighbours`, `ask`) still answer.

With `--allow-writes`, an agent can add a fact it was told (with its source)
or certify a rule. Each write takes two calls. The first returns a preview
and a `confirm_token`, and writes nothing. The second, with the same
arguments and the token, writes. The token is an HMAC bound to the
arguments and to the project's state; it expires after five minutes and
works once, so an agent writes exactly what it showed, on the state it
previewed. A write is one undo step in the studio and a line in the action
log under `mcp`. While an extraction runs on the project (in this process
or another), writes wait. This adds to the client's own approval prompt; it
does not replace it.

The product's MCP server (`mcp/`, over HTTP, see [mcp.md](mcp.md)) answers
the same kinds of question on the databases' semantic layer. Its names stay
as they are, since agents and skills already rely on them:

| Question | Studio (`ontology mcp`) | Product (`auto-ontology-mcp`) |
| --- | --- | --- |
| Find a concept | `search` | `search_terms` |
| One concept | `get_concept` | `get_term` |
| One table | `describe_table` | `describe_table` |
| A question | `ask_question` | `ask_question` |
| Can it answer? | `check_playbook`, `brief` | `check_answerable`, `check_readiness` |

### What this does not do yet

Facts and rules stay in the local project: nothing is published to the
Postgres catalog, there is no shared workspace and no question across
projects. Emails are read from `.eml` files, not from a mailbox (no IMAP),
and Notion from its export, not its API. The studio's messages are in
French; the page alone switches to English.

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
