// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/* Documents, analysis, dashboards, guide and the first-run tour. */
(function () {
  "use strict";

  var GENRE = {
    fr: {
      contract: "Contrat", scientific_paper: "Article", report: "Rapport",
      book_chapter: "Chapitre", financial_statement: "État financier",
      email: "Courriel", notes: "Notes", other: "Autre"
    },
    en: {
      contract: "Contract", scientific_paper: "Paper", report: "Report",
      book_chapter: "Chapter", financial_statement: "Financial statement",
      email: "Email", notes: "Notes", other: "Other"
    }
  };

  var GUIDE = {
    fr: [
      ["Une ontologie, en deux lignes", "C'est le vocabulaire du corpus : des concepts, des individus, et les faits qui les relient. Le graphe montre ces faits ; le glossaire donne le sens des mots."],
      ["Parcours", "1. Déposez un document ou essayez l'exemple. 2. Lisez l'indicateur du haut, puis le graphe. 3. Ouvrez un nœud pour voir le passage. 4. Corrigez le nom ou le type. 5. Ajoutez un autre document et comparez."],
      ["Quels documents", "Un texte suivi marche mieux qu'un scan ou qu'un tableau. PDF avec une couche de texte, EPUB, DOCX, HTML, Markdown, texte brut. Un PDF image affiche un avertissement : il n'y a pas d'OCR."],
      ["Lire les vues", "Graphe : forme = sorte (losange classe, rond entité), couleur = famille, taille = nombre de liens. Focus ne garde que le voisinage. Documents : type, domaine, métadonnées. Analyse : matrice des classes, chronologie, couverture. Tableaux : graphiques proposés, à épingler."],
      ["Corriger et fusionner", "Renommez dans le panneau, ou fusionnez un doublon proposé. Annuler restaure le fichier. Un fait retiré et un renommage sont réutilisés au document suivant."],
      ["Exporter", "Télécharger : HTML autonome, Mermaid, Turtle (RDF), Cypher (Neo4j), CSV, JSON-LD, JSONL. Le JSONL est un jeu de triplets validés pour un entraînement ultérieur, que cette application ne lance pas."],
      ["Le modèle", "Sans clé, l'exemple fonctionne et la page le dit. ONTOLOGY_LLM_API_KEY, ONTOLOGY_LLM_ENDPOINT et ONTOLOGY_LLM_MODEL visent un serveur compatible OpenAI. Le défaut reste NVIDIA. ontology serve --fake n'appelle aucun modèle."],
      ["Ce qu'apprendre veut dire", "Rien n'est réentraîné. Vos corrections (alias, faits refusés, types) sont écrites dans le projet et dans ~/AutoOntology/memory.json, puis ajoutées au prompt suivant. Le score du jeu d'or mesure l'exemple de la bibliothèque. Un vrai affinage est une étape possible plus tard, à partir du JSONL."],
      ["Cas", "Un dossier de contrats : types, parties, clauses partagées. Un lot d'articles : auteurs et concepts communs. Des notes de réunion : qui décide quoi, puis une question dans le panneau, avec le passage cité."],
      ["Fiche", "Un clic ouvre la fiche : type, groupe, statut, propriétés typées, liens, citation. Les corrections se font là, avec annulation."],
      ["Actions", "Renommer, fusionner, changer le type, retirer un fait, éditer une propriété, changer un statut. Chaque action a un aperçu, puis une ligne de journal. Le journal alimente le prompt suivant."],
      ["Lignée", "Document, morceau, citation, fait, puis les actions qui ont suivi. Depuis un document, la liste de ce qu'il a encore produit."],
      ["Schéma", "L'onglet Schéma sépare les types, les propriétés et les liens des instances. Un type nouveau reste expérimental tant que vous ne le marquez pas actif."],
      ["Explorer", "Recherche à facettes, puis « Enregistrer ». L'ensemble s'applique au graphe et s'exporte. L'adresse de la page reprend la recherche."],
      ["Voisinage", "Depuis une fiche, profondeur 1 à 3, sens et types de liens. Le dessin s'arrête à 500 nœuds et le dit. Une note en pointillés n'est pas un fait exporté."],
      ["Pipeline", "Lecture, nettoyage, morceaux, extraction, normalisation, fusion. Des attentes (échecs, citations, cycles) marquent le document incomplet sans effacer le reste. Un PDF sans texte prévient si Tesseract est absent."],
      ["API et client", "/docs décrit l'API. /api/tester interroge un type. ontology sdk écrit un client Python. Hors de cette machine, le jeton est requis et l'écriture reste coupée sans ONTOLOGY_API_ALLOW_WRITE=1."],
      ["Branches", "Une branche est une copie du projet. On y essaie une extraction ou des fusions, on compare, on fusionne vers main ou on jette. Jeter ne modifie pas main."],
      ["Similarité", "Un index local (trigrammes, pas un modèle téléchargé) propose des candidats de fusion et une recherche par phrase. Rien n'est fusionné tout seul. Une classe n'est jamais proposée comme double d'un individu."],
      ["Bonnes pratiques d'ontologie", "Le schéma (classes, propriétés, sous-classes) reste distinct des individus. L'export Turtle est de l'OWL 2 : rdfs:label et skos:prefLabel en français, propriétés objet ou données, domaine et portée quand ils sont univoques, PROV pour le document et l'extraction. Les noms d'IRI sont en CamelCase ; le libellé français est conservé. Le pipeline affiche un rapport (cycles de sous-classe, classes orphelines, définitions, libellés, domaine). Les correspondances FOAF, schema.org ou Dublin Core sont des suggestions : rien n'est aligné tout seul. Une question de compétence, saisie plus bas, dit si les faits actuels peuvent y répondre."]
    ],
    en: [
      ["An ontology, in two lines", "The vocabulary of the corpus: concepts, individuals, and the facts that link them. The graph shows the facts; the glossary gives the words a meaning."],
      ["Workflow", "1. Drop a document or try the sample. 2. Read the figures, then the graph. 3. Open a node to see the passage. 4. Correct a name or a type. 5. Add another document and compare."],
      ["Which documents", "Continuous prose works better than a scan or a spreadsheet. PDF with a text layer, EPUB, DOCX, HTML, Markdown, plain text. An image PDF shows a warning: there is no OCR."],
      ["Reading the views", "Graph: shape is kind, colour is family, size is degree. Focus keeps the neighbourhood. Documents: type, domain, metadata. Analysis: class matrix, timeline, coverage. Boards: suggested charts you can pin."],
      ["Correct and merge", "Rename in the side panel, or merge a suggested duplicate. Undo restores the file. A removed fact and a rename are reused on the next document."],
      ["Export", "Download: standalone HTML, Mermaid, Turtle (RDF), Cypher (Neo4j), CSV, JSON-LD, JSONL. JSONL is a set of validated triplets for a later training run. This app does not train a model."],
      ["The model", "With no key, the sample still works and the page says so. ONTOLOGY_LLM_API_KEY, ONTOLOGY_LLM_ENDPOINT and ONTOLOGY_LLM_MODEL point at an OpenAI-compatible server. The default stays NVIDIA. ontology serve --fake calls no model."],
      ["What learning means", "Nothing is fine-tuned. Corrections (aliases, rejected facts, types) are stored in the project and in ~/AutoOntology/memory.json, then added to the next prompt. The gold score measures the library example. Real fine-tuning is a possible later step, from the JSONL file."],
      ["Uses", "A folder of contracts: types, parties, shared clauses. A batch of papers: authors and shared concepts. Meeting notes: who decides what, then a question in the side panel, with the cited passage."],
      ["Card", "A click opens the card: type, group, status, typed properties, links, citation. Corrections happen there, and can be undone."],
      ["Actions", "Rename, merge, change type, reject a fact, edit a property, set a status. Each action has a preview, then a log line. The log feeds the next prompt."],
      ["Lineage", "Document, chunk, citation, fact, then the actions that followed. From a document, what it still produced."],
      ["Schema", "The Schema tab separates types, properties and links from instances. A new type stays experimental until you mark it active."],
      ["Explorer", "Faceted search, then Save. The set applies to the graph and exports. The page address keeps the search."],
      ["Neighbourhood", "From a card, depth 1 to 3, direction and link types. Drawing stops at 500 nodes and says so. A dashed note is not an exported fact."],
      ["Pipeline", "Read, clean, chunk, extract, normalize, merge. Expectations (failures, citations, cycles) mark the document incomplete without deleting the rest. A textless PDF warns when Tesseract is missing."],
      ["API and client", "/docs describes the API. /api/tester queries a type. ontology sdk writes a Python client. Off this machine the token is required, and writes stay off without ONTOLOGY_API_ALLOW_WRITE=1."],
      ["Branches", "A branch is a copy of the project. Try an extraction or some merges, compare, merge into main, or discard. Discard does not change main."],
      ["Similarity", "A local index (trigrams, not a downloaded model) suggests merge candidates and a phrase search. Nothing is merged on its own. A class is never offered as a duplicate of an individual."],
      ["Ontology practice", "The schema (classes, properties, subclasses) stays apart from individuals. Turtle export is OWL 2: rdfs:label and skos:prefLabel, object or datatype properties, domain and range when every use agrees, PROV for the document and the extraction. IRI names are CamelCase; the French label is kept. The pipeline shows a report (subclass cycles, orphan classes, definitions, labels, domain). FOAF, schema.org and Dublin Core links are suggestions and are never applied on their own. A competency question, entered below, says whether the current facts can answer it."]
    ]
  };

  function ui() { return window.StudioUI; }
  function lang() { return (ui() && ui().lang) || "fr"; }
  function t(key) { return ui() ? ui().t(key) : key; }
  function el(tag, attrs, children) { return ui().el(tag, attrs, children); }

  function showOnGraph(next) {
    ui().setFilter(next);
    var button = document.querySelector(".views button[data-view='graph']");
    if (button) button.click();
  }

  function genreLabel(id) {
    return (GENRE[lang()] && GENRE[lang()][id]) || id;
  }

  function render(view) {
    var box = document.getElementById("panel-view");
    var state = ui() && ui().state;
    if (!box || !state) return;
    if (view === "documents") box.replaceChildren(documents(state));
    else if (view === "analysis") box.replaceChildren(analysis(state));
    else if (view === "dashboards") box.replaceChildren(boards(state));
    else if (view === "guide") box.replaceChildren(guide());
  }

  function documents(state) {
    var root = el("div", { class: "stack" }, [
      el("h2", {}, [lang() === "fr" ? "Documents" : "Documents"]),
      el("p", { class: "muted" }, [lang() === "fr"
        ? "Le type et le domaine sont estimés. Vous pouvez les corriger."
        : "Type and domain are estimates. You can correct them."])
    ]);
    var checks = (state.standards && state.standards.checks) || [];
    if (checks.length) {
      root.append(el("h3", {}, [lang() === "fr" ? "Qualité du schéma" : "Schema quality"]));
      checks.forEach(function (item) {
        root.append(el("p", { class: item.status === "failed" ? "bad" : "muted" }, [
          item.name + " — " + item.detail
        ]));
      });
    }
    var picks = [];
    (state.documents || []).forEach(function (doc) {
      var select = el("select", { "aria-label": "Type" }, Object.keys(GENRE.fr).map(function (id) {
        var option = el("option", { value: id }, [genreLabel(id)]);
        if (id === doc.genre) option.selected = true;
        return option;
      }));
      select.addEventListener("change", function () {
        ui().edit({ op: "set_genre", document_id: doc.id, new: select.value });
      });
      var card = el("article", { class: "doc-card" }, [
        el("header", {}, [
          el("strong", {}, [doc.title || doc.filename]),
          el("span", { class: "muted" }, [" " + Math.round((doc.genre_confidence || 0) * 100) + " %"])
        ]),
        el("p", {}, [
          doc.filename,
          doc.author ? " · " + doc.author : "",
          doc.date ? " · " + doc.date : "",
          doc.language ? " · " + doc.language : "",
          doc.pages ? " · " + doc.pages + (lang() === "fr" ? " p." : " pp.") : ""
        ]),
        el("p", {}, [
          (lang() === "fr" ? "Domaine : " : "Domain: ") + (doc.domain || "—"),
          " · " + (doc.genre_source === "user" ? (lang() === "fr" ? "corrigé" : "corrected") : (lang() === "fr" ? "estimé" : "estimated"))
        ]),
        select,
        (doc.steps || []).length ? el("p", { class: "muted" }, [(doc.steps || []).map(function (step) { return step.name; }).join(" → ")]) : null,
        (doc.expectations || []).some(function (step) { return step.status === "failed"; })
          ? el("p", { class: "bad" }, [(doc.expectations || []).filter(function (step) { return step.status === "failed"; }).map(function (step) { return step.detail; }).join(" ")])
          : null,
        el("div", { class: "paste-actions" }, [
          el("button", { type: "button", onclick: function () { showOnGraph({ kind: "document", value: doc.id }); } }, [lang() === "fr" ? "Voir dans le graphe" : "Show on the graph"]),
          el("button", { type: "button", onclick: function () { showOnGraph({ kind: "genre", value: doc.genre }); } }, [genreLabel(doc.genre)])
        ])
      ]);
      var mark = el("input", { type: "checkbox", "aria-label": doc.filename });
      mark.addEventListener("change", function () {
        if (mark.checked) picks.push(doc.id);
        else picks = picks.filter(function (id) { return id !== doc.id; });
        var out = document.getElementById("compare-out");
        if (picks.length === 2 && out) {
          fetch("/api/v1/compare?left=" + encodeURIComponent(picks[0]) + "&right=" + encodeURIComponent(picks[1]))
            .then(function (response) { return response.json(); })
            .then(function (body) {
              out.textContent = (lang() === "fr" ? "Communs : " : "Shared: ")
                + (body.shared || []).slice(0, 12).join(", ");
            });
        }
      });
      card.prepend(mark);
      root.append(card);
    });
    root.append(el("p", { id: "compare-out", class: "muted" }, [
      lang() === "fr" ? "Cochez deux documents pour les comparer." : "Tick two documents to compare them."
    ]));
    root.append(el("div", { class: "paste-actions" }, [
      el("button", { type: "button", onclick: function () { showOnGraph({ kind: "scope", value: "shared" }); } }, [lang() === "fr" ? "Concepts communs" : "Shared concepts"]),
      el("button", { type: "button", onclick: function () { showOnGraph({ kind: "scope", value: "specific" }); } }, [lang() === "fr" ? "Propres à un document" : "Specific to one document"])
    ]));
    return root;
  }

  function analysis(state) {
    var data = state.analysis || {};
    var root = el("div", { class: "stack" }, [el("h2", {}, [lang() === "fr" ? "Analyse" : "Analysis"])]);
    root.append(el("h3", {}, [lang() === "fr" ? "Classes les plus peuplées" : "Largest classes"]));
    root.append(bars((state.stats && state.stats.top_classes) || []));
    root.append(el("h3", {}, [lang() === "fr" ? "Relations les plus fréquentes" : "Most frequent relations"]));
    root.append(bars((state.stats && state.stats.top_predicates) || []));
    var matrix = data.matrix || { labels: [], rows: [] };
    if (matrix.truncated) {
      root.append(el("p", { class: "muted" }, [
        lang() === "fr"
          ? "Matrice limitée aux " + matrix.truncated.shown + " classes les plus reliées sur " + matrix.truncated.total + "."
          : "Matrix limited to the " + matrix.truncated.shown + " most connected classes of " + matrix.truncated.total + "."
      ]));
    }
    if ((matrix.labels || []).length) {
      root.append(el("h3", {}, [lang() === "fr" ? "Relations entre classes" : "Relations between classes"]));
      root.append(matrixTable(matrix));
    }
    if ((data.timeline || []).length) {
      root.append(el("h3", {}, [lang() === "fr" ? "Repères" : "Dates"]));
      var line = el("ol", { class: "timeline" }, []);
      data.timeline.forEach(function (item) {
        line.append(el("li", {}, [item.year + " — " + item.label]));
      });
      root.append(line);
    }
    var coverage = data.coverage || { concepts: [], documents: [] };
    if ((coverage.concepts || []).length && (coverage.documents || []).length) {
      root.append(el("h3", {}, [lang() === "fr" ? "Documents et concepts" : "Documents and concepts"]));
      root.append(coverageTable(coverage));
    }
    return root;
  }

  function bars(items) {
    var max = items.reduce(function (acc, item) { return Math.max(acc, item.count || 0); }, 1);
    var box = el("div", { class: "bars" }, []);
    items.forEach(function (item) {
      var width = Math.max(item.count ? 4 : 0, Math.round(100 * (item.count || 0) / max));
      box.append(el("div", { class: "bar-row" }, [
        el("button", { type: "button", class: "bar-hit" }, [
          el("span", { class: "bar-name" }, [item.name || ""]),
          el("span", { class: "track" }, [
            el("span", { class: "fill", style: "width:" + width + "%" }, [])
          ]),
          el("em", {}, [String(item.count || 0)])
        ])
      ]));
    });
    return box;
  }

  function matrixTable(matrix) {
    var head = el("tr", {}, [el("th", {}, [""])].concat(matrix.labels.map(function (label) {
      return el("th", {}, [label]);
    })));
    var table = el("table", { class: "matrix" }, [head]);
    (matrix.rows || []).forEach(function (row) {
      var max = Math.max.apply(null, row.cells.concat([1]));
      table.append(el("tr", {}, [el("th", {}, [row.name])].concat(row.cells.map(function (value) {
        var ink = Math.round(255 - 180 * value / max);
        return el("td", { style: "background:rgb(" + ink + "," + (ink + 20) + ",255)" }, [value ? String(value) : ""]);
      }))));
    });
    return table;
  }

  function coverageTable(coverage) {
    var head = el("tr", {}, [el("th", {}, [""])].concat(coverage.concepts.map(function (name) {
      return el("th", {}, [name]);
    })));
    var table = el("table", {}, [head]);
    coverage.documents.forEach(function (row) {
      table.append(el("tr", {}, [el("th", {}, [row.filename])].concat((row.present || []).map(function (flag) {
        return el("td", {}, [flag ? "●" : ""]);
      }))));
    });
    return table;
  }

  function boards(state) {
    var data = state.analysis || {};
    var pinned = data.pinned || [];
    var root = el("div", { class: "stack" }, [
      el("h2", {}, [lang() === "fr" ? "Tableaux proposés" : "Suggested boards"]),
      el("p", { class: "muted" }, [lang() === "fr"
        ? "Épinglez ceux que vous voulez garder. Le téléchargement « Tableaux HTML » reprend les épinglés."
        : "Pin the ones you want to keep. The HTML download uses the pinned boards."])
    ]);
    (data.dashboards || []).forEach(function (board) {
      var on = pinned.indexOf(board.id) >= 0;
      root.append(el("article", { class: "doc-card" }, [
        el("h3", {}, [board.title]),
        el("p", {}, [board.why]),
        board.kind === "bars" ? bars(board.items || []) : el("p", { class: "muted" }, [board.kind]),
        el("button", { type: "button", onclick: function () {
          ui().postJson("/api/dashboards/pin", { id: board.id, pinned: !on });
        } }, [on ? (lang() === "fr" ? "Retirer" : "Unpin") : (lang() === "fr" ? "Épingler" : "Pin")])
      ]));
    });
    var scores = data.scores || [];
    if (scores.length) {
      root.append(el("h3", {}, [lang() === "fr" ? "Qualité dans le temps" : "Quality over time"]));
      root.append(el("p", { class: "muted" }, [scores.map(function (point) {
        var gold = point.f1 == null ? "" : " · F1 " + point.f1;
        return point.quality + gold;
      }).join("  →  ")]));
    }
    return root;
  }

  function guide() {
    var root = el("div", { class: "stack guide" }, [
      el("h2", {}, [lang() === "fr" ? "Mode d'emploi" : "Guide"])
    ]);
    (GUIDE[lang()] || GUIDE.fr).forEach(function (section) {
      root.append(el("h3", {}, [section[0]]));
      root.append(el("p", {}, [section[1]]));
    });
    var standards = (ui() && ui().state && ui().state.standards) || {};
    root.append(el("h3", {}, [lang() === "fr" ? "Questions de compétence" : "Competency questions"]));
    (standards.questions || []).forEach(function (item) {
      root.append(el("p", {}, [
        (item.answerable ? "● " : "○ ") + item.text,
        el("button", { type: "button", onclick: function () {
          fetch("/api/v1/questions/" + encodeURIComponent(item.id), { method: "DELETE" })
            .then(function (response) { return response.json(); })
            .then(function (body) { ui().replace(body); });
        } }, ["×"])
      ]));
    });
    var form = el("form", { class: "ask", onsubmit: function (event) {
      event.preventDefault();
      var input = event.target.querySelector("input");
      ui().postJson("/api/v1/questions", { text: input.value });
    } }, [
      el("input", { type: "text", placeholder: lang() === "fr" ? "Quelle question l'ontologie doit-elle trancher ?" : "Which question should the ontology answer?" }),
      el("button", { type: "submit" }, [lang() === "fr" ? "Ajouter" : "Add"])
    ]);
    root.append(form);
    if ((standards.checks || []).length) {
      root.append(el("h3", {}, [lang() === "fr" ? "Rapport de qualité" : "Quality report"]));
      (standards.checks || []).forEach(function (item) {
        root.append(el("p", { class: item.status === "failed" ? "bad" : "muted" }, [
          item.name + " — " + item.detail
        ]));
      });
    }
    root.append(el("h3", {}, [lang() === "fr" ? "Depuis le terminal" : "From the terminal"]));
    root.append(el("pre", {}, [
      "uv run ontology serve\nuv run ontology import a.pdf b.epub --fake\nuv run ontology ask \"qui dirige la bibliothèque\"\nuv run ontology mcp"
    ]));
    return root;
  }

  var STEPS = {
    fr: [
      ["Déposez un document", "PDF, EPUB, DOCX, HTML ou texte. Ou collez un passage."],
      ["L'exemple", "Sans clé de modèle, le bouton bleu ouvre un graphe tout de suite."],
      ["Les vues", "Graphe, documents, analyse, tableaux. Le guide explique chaque lecture."],
      ["Le guide", "Ouvrez Guide pour le parcours, les exports et ce que « apprendre » veut dire."]
    ],
    en: [
      ["Drop a document", "PDF, EPUB, DOCX, HTML or text. Or paste a passage."],
      ["The sample", "With no model key, the blue button opens a graph immediately."],
      ["The views", "Graph, documents, analysis, boards. The guide explains each one."],
      ["The guide", "Open Guide for the workflow, the exports, and what learning means."]
    ]
  };
  var step = 0;

  function showTour() {
    var box = document.getElementById("tour");
    var pages = STEPS[lang()] || STEPS.fr;
    if (!box || step >= pages.length) {
      if (box) box.hidden = true;
      localStorage.setItem("ontology.tour", "1");
      return;
    }
    box.hidden = false;
    document.getElementById("tour-title").textContent = pages[step][0];
    document.getElementById("tour-body").textContent = pages[step][1];
  }

  document.addEventListener("ontology:render", function () {
    var view = localStorage.getItem("ontology.view") || "graph";
    var current = document.querySelector(".views button.is-on");
    if (current) view = current.getAttribute("data-view") || view;
    render(view);
  });

  document.getElementById("tour-next").addEventListener("click", function () {
    step += 1;
    showTour();
  });
  document.getElementById("tour-skip").addEventListener("click", function () {
    step = 99;
    showTour();
  });
  if (!localStorage.getItem("ontology.tour")) showTour();

  window.StudioPanels = { render: render };
})();
