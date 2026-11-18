// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/* Home: the step-by-step use of the studio, from a new file to the exports,
   each step with its state in the current project; then how to bring in
   every kind of data. */
(function () {
  "use strict";

  function ui() { return window.StudioUI; }
  function lang() { return (ui() && ui().lang) === "en" ? "en" : "fr"; }
  function el(tag, attrs, children) { return ui().el(tag, attrs, children); }
  function number(value) { return Number(value || 0).toLocaleString(lang() === "fr" ? "fr-FR" : "en-US"); }

  function openView(view) {
    var button = document.querySelector(".views button[data-view='" + view + "']");
    if (button) button.click();
  }
  function click(id) {
    var node = document.getElementById(id);
    if (node) node.click();
  }

  var TEXT = {
    fr: {
      title: "Accueil — mode d'emploi pas à pas",
      lead: "Huit étapes, du premier fichier aux exports. Chaque étape dit où en est ce projet ; le bouton y mène.",
      empty: "Commencez par l'étape 1, ou essayez l'exemple : un graphe s'affiche sans modèle.",
      inSite: "Dans le site", inTerminal: "Au terminal",
      done: "fait", todo: "à faire", optional: "facultatif", running: "en cours", warn: "à revoir", yours: "à vous",
      dataTitle: "Traiter toutes vos données",
      dataLead: "Chaque sorte de fichier a son chemin. Tout ce qui suit marche aussi par glisser-déposer dans cette page.",
      dailyTitle: "Ensuite, chaque jour",
      sample: "Essayer l'exemple"
    },
    en: {
      title: "Home — step by step",
      lead: "Eight steps, from the first file to the exports. Each step shows where this project stands; its button takes you there.",
      empty: "Start with step 1, or try the sample: a graph appears with no model.",
      inSite: "In the page", inTerminal: "In the terminal",
      done: "done", todo: "to do", optional: "optional", running: "running", warn: "check", yours: "your turn",
      dataTitle: "Bringing in all your data",
      dataLead: "Each kind of file has its own path. Everything below also works by dropping the file on this page.",
      dailyTitle: "Then, every day",
      sample: "Try the sample"
    }
  };

  function tx(key) { return TEXT[lang()][key]; }

  /* What the project says about each step: [state, detail]. */
  function progress(state) {
    var fr = lang() === "fr";
    var llm = state.llm || {};
    var docs = state.documents || [];
    var stats = state.stats || {};
    var running = docs.filter(function (d) { return d.status === "running"; });
    var broken = docs.filter(function (d) {
      return d.status === "failed" || (d.chunks_failed || []).length;
    });
    var out = {};

    if (llm.demo) out.model = ["warn", fr ? "Mode démonstration : aucun modèle n'est appelé." : "Demo mode: no model is called."];
    else if (llm.configured) {
      var name = llm.model || (llm.auto_model ? (fr ? "le modèle chargé" : "the loaded model") : "");
      out.model = ["done", name + (llm.endpoint ? " · " + llm.endpoint : "")];
    } else out.model = ["todo", fr ? "Aucun modèle n'est branché." : "No model is connected."];

    out.playbook = state.playbook
      ? ["done", (fr ? "Playbook actif : " : "Active playbook: ") + state.playbook]
      : ["optional", fr ? "Aucun playbook : extraction générale." : "No playbook: general extraction."];

    out.add = docs.length
      ? ["done", number(docs.length) + (fr ? " document(s), " : " document(s), ") + number((state.datasets || []).length) + (fr ? " table(s)." : " table(s).")]
      : ["todo", fr ? "Le projet est vide." : "The project is empty."];

    if (running.length) {
      var doc = running[0];
      var counted = doc.chunks_total ? number(doc.chunks_done) + "/" + number(doc.chunks_total) : "";
      out.extract = state.extracting
        ? ["running", doc.filename + (counted ? " : " + counted + (fr ? " morceaux lus." : " chunks read.") : "")]
        : ["warn", doc.filename + (fr
          ? " : extraction interrompue" + (counted ? " à " + counted : "") + ". Redéposez le fichier : les morceaux déjà lus viennent du cache."
          : ": extraction interrupted" + (counted ? " at " + counted : "") + ". Drop the file again: chunks already read come from the cache.")];
    } else if (broken.length) {
      out.extract = ["warn", broken.map(function (d) { return d.filename; }).join(", ") + (fr
        ? " : des morceaux sont restés sans réponse. Redéposez le fichier."
        : ": some chunks got no answer. Drop the file again.")];
    } else if (docs.length) {
      out.extract = ["done", fr ? "Toutes les extractions sont terminées." : "Every extraction finished."];
    } else out.extract = ["todo", ""];

    var last = docs[docs.length - 1];
    if (last && last.char_count && llm.chunk_chars) {
      var chunks = Math.ceil(last.char_count / llm.chunk_chars);
      out.size = (fr ? "Dernier fichier : " : "Last file: ") + number(last.char_count) +
        (fr ? " caractères, soit environ " : " characters, about ") + number(chunks) +
        (fr ? " morceau(x)." : " chunk(s).");
    }

    out.review = !docs.length ? ["todo", ""]
      : stats.failed_chunks ? ["warn", number(stats.failed_chunks) + (fr ? " morceau(x) en échec." : " failed chunk(s).")]
        : ["done", number(stats.facts) + (fr ? " faits, " : " facts, ") + number(stats.concepts) + (fr ? " concepts." : " concepts.")];

    out.correct = (state.action_log || []).length
      ? ["done", number(state.action_log.length) + (fr ? " correction(s) récente(s), réutilisées au prochain document." : " recent correction(s), reused on the next document.")]
      : ["yours", ""];
    out.ask = ["yours", ""];
    out.finish = ["yours", ""];
    return out;
  }

  var STEPS = {
    fr: [
      {
        key: "model", title: "Brancher le modèle",
        what: "Le modèle lit vos textes et en tire les faits. Avec LM Studio : chargez un modèle, puis démarrez le serveur local (onglet Developer, port 1234).",
        site: "Réglages (icône curseurs) → Point d'accès http://localhost:1234/v1. Laissez « Modèle » vide pour prendre celui qui est chargé, puis « Tester la connexion ».",
        cli: "Le fichier .env du dépôt suffit : ontology open et ontology import le lisent.",
        action: ["Ouvrir les réglages", function () { click("settings-btn"); }]
      },
      {
        key: "playbook", title: "Choisir un playbook (avant d'ajouter les fichiers)",
        what: "Un playbook oriente l'extraction vers le vocabulaire d'un métier et ajoute des contrôles. audit-contrats : parties, échéances, montants. suivi-financier : chiffres, périodes, écarts. base-connaissances : concepts, définitions, auteurs (livres, cours, articles).",
        site: "Documents → Playbook → choisissez, puis « Vérifier » plus tard.",
        cli: "uv run ontology playbook use base-connaissances",
        action: ["Aller aux documents", function () { openView("documents"); }]
      },
      {
        key: "add", title: "Ajouter un fichier",
        what: "Glissez-déposez un ou plusieurs fichiers n'importe où dans la page, ou collez un passage. Un fichier déjà importé (même contenu) n'est pas dupliqué.",
        site: "Bouton « Ajouter » (icône document) en haut à droite, ou glisser-déposer.",
        cli: "uv run ontology import ~/Documents/rapport.pdf   ·   uv run ontology open ~/Dossier (tout un dossier, surveillé)",
        action: ["Choisir des fichiers", function () { click("file-input"); }]
      },
      {
        key: "extract", title: "Suivre l'extraction",
        what: "Le texte est coupé en morceaux d'environ 12 000 caractères ; le modèle lit chaque morceau. Un article : quelques morceaux, quelques minutes. Un livre de 1 000 pages : environ 300 morceaux, plusieurs heures avec un modèle local. Le graphe se remplit au fil de l'eau ; les faits sont comptés à la fin.",
        site: "La barre en bas de la page montre le morceau en cours et le temps restant. « Annuler » garde ce qui est déjà lu. Gardez la page (ou le terminal) ouverte jusqu'au bout.",
        cli: "uv run ontology brief   (dit « extraction en cours, n/N morceaux lus »)",
        action: null
      },
      {
        key: "review", title: "Vérifier ce qui est sorti",
        what: "Les indicateurs du haut donnent concepts, faits et morceaux en échec. Un morceau en échec n'a pas eu de réponse du modèle : redéposez le fichier, seuls les morceaux manquants sont refaits.",
        site: "Documents : statut, type et domaine estimés (corrigeables). Graphe : un nœud isolé est une entité reliée à rien.",
        cli: "uv run ontology brief",
        action: ["Voir les documents", function () { openView("documents"); }]
      },
      {
        key: "correct", title: "Corriger et fusionner",
        what: "Vos corrections sont enregistrées et reprises au document suivant : le studio apprend votre vocabulaire, sans réentraîner le modèle.",
        site: "Graphe → cliquez un nœud → fiche : renommer, changer le type, retirer un fait. Panneau de droite : « Doublons possibles », à fusionner. Ctrl+Z annule tout.",
        cli: "uv run ontology diff --since 7d   (ce qui a changé)",
        action: ["Ouvrir le graphe", function () { openView("graph"); }]
      },
      {
        key: "ask", title: "Interroger",
        what: "Une question trouve les faits qui partagent ses mots et cite le passage. Posez-la avec les mots du document : un livre en anglais s'interroge en anglais (« cost of capital », « WACC »).",
        site: "Panneau de droite : question et passage cité. Glossaire et Faits : tout, triable. Explorer : recherche à facettes, enregistrable.",
        cli: "uv run ontology ask \"cost of capital\"   ·   uv run ontology ask \"budget par directeur\" --data (documents + tableurs)",
        action: ["Ouvrir les faits", function () { openView("facts"); }]
      },
      {
        key: "finish", title: "Contrôler, rendre compte, exporter",
        what: "Le playbook liste ce qui demande une décision (échéance proche, partie manquante…), par priorité. Les exports emportent les faits ailleurs.",
        site: "Documents → Playbook → « Vérifier ». Télécharger (flèche) : HTML autonome, CSV, Turtle (RDF), Cypher (Neo4j), JSON-LD, Mermaid.",
        cli: "uv run ontology check   ·   uv run ontology report meeting (une réunion)   ·   uv run ontology report compare \"A\" \"B\"",
        action: ["Vérifier avec le playbook", function () { openView("documents"); }]
      }
    ],
    en: [
      {
        key: "model", title: "Connect the model",
        what: "The model reads your texts and draws the facts. With LM Studio: load a model, then start the local server (Developer tab, port 1234).",
        site: "Settings (sliders icon) → Endpoint http://localhost:1234/v1. Leave Model empty to use the loaded one, then Test connection.",
        cli: "The repository's .env is enough: ontology open and ontology import read it.",
        action: ["Open settings", function () { click("settings-btn"); }]
      },
      {
        key: "playbook", title: "Pick a playbook (before adding files)",
        what: "A playbook steers the extraction to a trade's vocabulary and adds checks. audit-contrats: parties, deadlines, amounts. suivi-financier: figures, periods, gaps. base-connaissances: concepts, definitions, authors (books, courses, papers).",
        site: "Documents → Playbook → pick one, then Check later.",
        cli: "uv run ontology playbook use base-connaissances",
        action: ["Go to documents", function () { openView("documents"); }]
      },
      {
        key: "add", title: "Add a file",
        what: "Drop one or several files anywhere on the page, or paste a passage. A file already imported (same content) is not duplicated.",
        site: "Add button (document icon) top right, or drag and drop.",
        cli: "uv run ontology import ~/Documents/report.pdf   ·   uv run ontology open ~/Folder (a whole folder, watched)",
        action: ["Choose files", function () { click("file-input"); }]
      },
      {
        key: "extract", title: "Follow the extraction",
        what: "The text is cut into chunks of about 12,000 characters; the model reads each one. A paper: a few chunks, a few minutes. A 1,000-page book: about 300 chunks, several hours with a local model. The graph fills as it goes; facts are counted at the end.",
        site: "The bar at the bottom shows the current chunk and the time left. Cancel keeps what was read. Keep the page (or the terminal) open until the end.",
        cli: "uv run ontology brief   (says \"extraction en cours, n/N morceaux lus\")",
        action: null
      },
      {
        key: "review", title: "Check what came out",
        what: "The figures at the top give concepts, facts and failed chunks. A failed chunk got no answer from the model: drop the file again, only the missing chunks are redone.",
        site: "Documents: status, estimated type and domain (you can correct them). Graph: a lone node is an entity linked to nothing.",
        cli: "uv run ontology brief",
        action: ["See documents", function () { openView("documents"); }]
      },
      {
        key: "correct", title: "Correct and merge",
        what: "Corrections are stored and reused on the next document: the studio learns your vocabulary without retraining the model.",
        site: "Graph → click a node → card: rename, change type, remove a fact. Right panel: Possible duplicates, to merge. Ctrl+Z undoes anything.",
        cli: "uv run ontology diff --since 7d   (what changed)",
        action: ["Open the graph", function () { openView("graph"); }]
      },
      {
        key: "ask", title: "Ask",
        what: "A question finds the facts that share its words and cites the passage. Use the document's words: an English book is asked in English (\"cost of capital\", \"WACC\").",
        site: "Right panel: question and cited passage. Glossary and Facts: everything, sortable. Explorer: faceted search you can save.",
        cli: "uv run ontology ask \"cost of capital\"   ·   uv run ontology ask \"budget per director\" --data (documents + spreadsheets)",
        action: ["Open facts", function () { openView("facts"); }]
      },
      {
        key: "finish", title: "Check, report, export",
        what: "The playbook lists what needs a decision (deadline soon, missing party…), by priority. Exports take the facts elsewhere.",
        site: "Documents → Playbook → Check. Download (arrow): standalone HTML, CSV, Turtle (RDF), Cypher (Neo4j), JSON-LD, Mermaid.",
        cli: "uv run ontology check   ·   uv run ontology report meeting (a meeting)   ·   uv run ontology report compare \"A\" \"B\"",
        action: ["Check with the playbook", function () { openView("documents"); }]
      }
    ]
  };

  var DATA = {
    fr: [
      ["Tout un dossier", "uv run ontology open ~/Dossier --playbook base-connaissances importe le dossier et ses sous-dossiers (fichiers cachés ignorés), puis importe chaque nouveau fichier déposé. Ou Réglages → Options avancées → Dossier à importer."],
      ["PDF, EPUB, DOCX, HTML, Markdown, texte", "Le texte suivi donne les meilleurs faits. Un PDF doit avoir une couche de texte ; un scan n'est lu que si Tesseract (OCR) est installé, sinon la page prévient."],
      ["Livres et gros PDF", "Testez d'abord un chapitre (Aperçu → Fichier → Imprimer → Pages de … à … → PDF → Enregistrer au format PDF) avec le playbook base-connaissances. Si le résultat convient, lancez le livre entier, par exemple la nuit."],
      ["Courriels (.eml) et archives (.zip)", "Un courriel donne son texte sans l'historique cité ; ses pièces jointes sont importées une à une. Un .zip est déplié par ontology open ou ontology import ; sur la page, déposez plutôt les fichiers qu'il contient."],
      ["Notes Obsidian et exports Notion", "Exportez Notion en Markdown, puis importez le dossier. L'en-tête, les liens [[…]] et les encadrés sont lus ; les identifiants Notion disparaissent des noms."],
      ["Tableurs (CSV, Excel, Parquet, SQLite)", "Un tableur devient une table, sans modèle ni attente : il n'est pas transformé en faits. Il se croise avec les documents : uv run ontology sql \"SELECT … FROM budgets b JOIN onto_facts f ON okey(b.nom) = f.subject_key\", ou une question en français avec ontology ask \"…\" --data."],
      ["Assistants (Claude Desktop, Cursor)", "uv run ontology mcp donne à l'assistant la recherche, les faits, les tables et les contrôles. Avec --allow-writes, il peut aussi mémoriser un fait ou certifier une règle, après votre confirmation."]
    ],
    en: [
      ["A whole folder", "uv run ontology open ~/Folder --playbook base-connaissances imports the folder and its subfolders (hidden files skipped), then each new file you drop there. Or Settings → Advanced → Folder to import."],
      ["PDF, EPUB, DOCX, HTML, Markdown, text", "Continuous prose gives the best facts. A PDF needs a text layer; a scan is read only when Tesseract (OCR) is installed, otherwise the page warns."],
      ["Books and large PDFs", "Try one chapter first (Preview → File → Print → Pages from … to … → PDF → Save as PDF) with the base-connaissances playbook. If the result is right, run the whole book, overnight for instance."],
      ["Email (.eml) and archives (.zip)", "An email gives its text without the quoted history; its attachments are imported one by one. A .zip is unpacked by ontology open or ontology import; on the page, drop the files it holds instead."],
      ["Obsidian notes and Notion exports", "Export Notion as Markdown, then import the folder. Front matter, [[…]] links and callouts are read; Notion ids are dropped from the names."],
      ["Spreadsheets (CSV, Excel, Parquet, SQLite)", "A spreadsheet becomes a table, with no model and no wait: it is not turned into facts. It joins the documents: uv run ontology sql \"SELECT … FROM budgets b JOIN onto_facts f ON okey(b.name) = f.subject_key\", or a plain question with ontology ask \"…\" --data."],
      ["Assistants (Claude Desktop, Cursor)", "uv run ontology mcp gives the assistant search, facts, tables and checks. With --allow-writes it can also remember a fact or certify a rule, once you confirm."]
    ]
  };

  var DAILY = {
    fr: "uv run ontology brief            # ce qui est arrivé, ce qui est à vérifier\nuv run ontology diff --since 7d   # ce qui a changé en une semaine\nuv run ontology check            # les contrôles du playbook\nuv run ontology ask \"…\"           # une question, avec le passage cité",
    en: "uv run ontology brief            # what came in, what to check\nuv run ontology diff --since 7d   # what changed this week\nuv run ontology check            # the playbook's checks\nuv run ontology ask \"…\"           # a question, with the cited passage"
  };

  function step(index, item, status) {
    var state = (status && status[0]) || "yours";
    var detail = (status && status[1]) || "";
    var body = [
      el("header", {}, [
        el("span", { class: "step-number", "aria-hidden": "true" }, [String(index + 1)]),
        el("h3", {}, [item.title]),
        el("span", { class: "pill pill-" + state }, [tx(state)])
      ]),
      detail ? el("p", { class: "step-state" }, [detail]) : null,
      el("p", {}, [item.what]),
      el("p", {}, [el("strong", {}, [tx("inSite") + " : "]), item.site]),
      el("p", { class: "muted" }, [el("strong", {}, [tx("inTerminal") + " : "]), el("code", {}, [item.cli])])
    ];
    if (item.action) {
      body.push(el("div", { class: "paste-actions" }, [
        el("button", { type: "button", class: state === "todo" ? "primary" : "", onclick: item.action[1] }, [item.action[0]])
      ]));
    }
    return el("li", { class: "step step-" + state }, body);
  }

  function build(state) {
    var status = progress(state);
    var root = el("div", { class: "stack home" }, [
      el("h2", {}, [tx("title")]),
      el("p", { class: "muted" }, [tx("lead")])
    ]);
    if (!(state.documents || []).length) {
      root.append(el("div", { class: "home-start" }, [
        el("p", {}, [tx("empty")]),
        el("div", { class: "paste-actions" }, [
          el("button", { type: "button", class: "primary", onclick: function () { click("file-input"); } }, [STEPS[lang()][2].action[0]]),
          el("button", { type: "button", onclick: function () { click("sample-btn"); } }, [tx("sample")])
        ])
      ]));
    }
    var list = el("ol", { class: "steps" }, []);
    STEPS[lang()].forEach(function (item, index) {
      var node = step(index, item, status[item.key]);
      if (item.key === "extract" && status.size) node.append(el("p", { class: "muted" }, [status.size]));
      list.append(node);
    });
    root.append(list);
    root.append(el("h2", {}, [tx("dataTitle")]));
    root.append(el("p", { class: "muted" }, [tx("dataLead")]));
    var grid = el("div", { class: "data-grid" }, []);
    DATA[lang()].forEach(function (card) {
      grid.append(el("article", { class: "doc-card" }, [el("h3", {}, [card[0]]), el("p", {}, [card[1]])]));
    });
    root.append(grid);
    root.append(el("h2", {}, [tx("dailyTitle")]));
    root.append(el("pre", { class: "home-daily" }, [DAILY[lang()]]));
    return root;
  }

  window.StudioHome = { build: build, progress: progress };
})();
