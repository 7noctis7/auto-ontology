// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/* Studio UI. French by default; the EN button switches the chrome. */
(function () {
  "use strict";

  var STR = {
    fr: {
      viewGraph: "Graphe", viewTree: "Hiérarchie", viewGlossary: "Glossaire", viewFacts: "Faits",
      viewDocuments: "Documents", viewAnalysis: "Analyse", viewBoards: "Tableaux", viewGuide: "Guide",
      theme: "Sombre", focus: "Focus", communities: "Communautés", fit: "Recentrer",
      layoutForce: "Force", watch: "Dossier à importer", ask: "Question",
      askPlaceholder: "Qui est relié à quoi ?", tourSkip: "Passer", tourNext: "Suivant",
      search: "Rechercher…", add: "Ajouter", undo: "Annuler", redo: "Rétablir",
      download: "Télécharger", settings: "Réglages",
      dropTitle: "Déposez un document", dropHint: "PDF, EPUB, DOCX, HTML, Markdown ou texte",
      paste: "Ou collez un passage…", extract: "Extraire", sample: "Essayer l'exemple",
      showTypes: "Liens de type", classesOnly: "Classes seules", literals: "Littéraux",
      cancel: "Annuler l'extraction", endpoint: "Point d'accès", model: "Modèle", apiKey: "Clé",
      keyHelp: "Laisser vide conserve la clé déjà enregistrée.",
      test: "Tester la connexion", save: "Enregistrer", advanced: "Options avancées",
      chunk: "Taille d'une partie (caractères)", timeout: "Délai d'une réponse (secondes)",
      maxTokens: "Longueur max. d'une réponse", dropNow: "Déposer pour extraire",
      concepts: "Concepts", relations: "Relations", facts: "Faits", documents: "Documents",
      entities: "Entités",
      orphans: "Orphelins", failed: "Échecs",
      ofNodes: "des nœuds", lastDoc: "dans le dernier document", none: "Aucun pour l'instant.",
      insightEmpty: "Déposez un document pour voir de quoi il parle.",
      insight: "Ce corpus parle surtout de ",
      select: "Sélectionnez un élément du graphe, ou parcourez les indicateurs.",
      topClasses: "Classes les plus peuplées", topPredicates: "Relations les plus fréquentes",
      growth: "Faits par document", docs: "Documents", suggestions: "Doublons possibles",
      merge: "Fusionner avec", why: "Pourquoi ce fait ?", noSource: "Pas de passage associé.",
      rename: "Nom", description: "Définition", outgoing: "Relations sortantes",
      incoming: "Relations entrantes", attributes: "Attributs", parent: "Parent", types: "Types",
      class: "Classe", entity: "Entité", literal: "Littéral", saved: "Enregistré",
      deleteFact: "Retirer", deleteClass: "Retirer cette classe",
      support: "appuis", quote: "Passage", chunk: "partie",
      running: "Extraction", eta: "reste environ", seconds: "s",
      cached: "en cache", failedChunk: "échouée", done: "terminée", cancelled: "annulée",
      duplicate: "Déjà présent", emptySide: "Le tableau de bord s'affichera ici.",
      sourceEnv: "Ces valeurs viennent de l'environnement. Le fichier ne les remplace qu'au prochain lancement sans ces variables.",
      sourceFile: "Réglages enregistrés dans le dossier du projet.",
      sourceDefault: "Valeurs NVIDIA par défaut. Aucune clé n'est enregistrée.",
      newProject: "Nouveau projet", path: "Fichier",
      orphanHelp: "Entité sans relation, ou classe isolée.",
      filterOrphans: "Filtrer les orphelins", clearFilter: "Filtre retiré",
      noGraph: "La bibliothèque de graphe n'a pas été chargée. Les autres vues restent disponibles.",
      statusOk: "complet", statusIncomplete: "incomplet", statusFailed: "échec",
      statusCancelled: "annulé", statusRunning: "en cours"
    },
    en: {
      viewGraph: "Graph", viewTree: "Hierarchy", viewGlossary: "Glossary", viewFacts: "Facts",
      viewDocuments: "Documents", viewAnalysis: "Analysis", viewBoards: "Boards", viewGuide: "Guide",
      theme: "Dark", focus: "Focus", communities: "Communities", fit: "Fit",
      layoutForce: "Force", watch: "Folder to import", ask: "Question",
      askPlaceholder: "Who is linked to what?", tourSkip: "Skip", tourNext: "Next",
      search: "Search…", add: "Add", undo: "Undo", redo: "Redo",
      download: "Download", settings: "Settings",
      dropTitle: "Drop a document", dropHint: "PDF, EPUB, DOCX, HTML, Markdown or text",
      paste: "Or paste a passage…", extract: "Extract", sample: "Try the sample",
      showTypes: "Type links", classesOnly: "Classes only", literals: "Literals",
      cancel: "Cancel extraction", endpoint: "Endpoint", model: "Model", apiKey: "Key",
      keyHelp: "Leave blank to keep the saved key.",
      test: "Test connection", save: "Save", advanced: "Advanced",
      chunk: "Chunk size (characters)", timeout: "Answer timeout (seconds)",
      maxTokens: "Max answer length", dropNow: "Drop to extract",
      concepts: "Concepts", relations: "Relations", facts: "Facts", documents: "Documents",
      entities: "Entities",
      orphans: "Orphans", failed: "Failed",
      ofNodes: "of nodes", lastDoc: "in the last document", none: "Nothing yet.",
      insightEmpty: "Drop a document to see what it is about.",
      insight: "This corpus is mainly about ",
      select: "Select something on the graph, or browse the indicators.",
      topClasses: "Largest classes", topPredicates: "Most frequent relations",
      growth: "Facts per document", docs: "Documents", suggestions: "Possible duplicates",
      merge: "Merge with", why: "Why is this here?", noSource: "No passage linked.",
      rename: "Name", description: "Definition", outgoing: "Outgoing relations",
      incoming: "Incoming relations", attributes: "Attributes", parent: "Parent", types: "Types",
      class: "Class", entity: "Entity", literal: "Literal", saved: "Saved",
      deleteFact: "Remove", deleteClass: "Remove this class",
      support: "mentions", quote: "Passage", chunk: "part",
      running: "Extracting", eta: "about", seconds: "s left",
      cached: "cached", failedChunk: "failed", done: "done", cancelled: "cancelled",
      duplicate: "Already ingested", emptySide: "The dashboard will show up here.",
      sourceEnv: "These values come from the environment. The file applies on the next launch without those variables.",
      sourceFile: "Settings saved next to your projects.",
      sourceDefault: "NVIDIA defaults. No key is stored.",
      newProject: "New project", path: "File",
      orphanHelp: "Entity with no relation, or an isolated class.",
      filterOrphans: "Filter orphans", clearFilter: "Filter cleared",
      noGraph: "The graph library did not load. The other views still work.",
      statusOk: "complete", statusIncomplete: "incomplete", statusFailed: "failed",
      statusCancelled: "cancelled", statusRunning: "running"
    }
  };

  var PALETTE = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#D55E00", "#56B4E9", "#882255", "#332288"];
  var FORMATS = [
    ["html", "HTML"], ["mermaid", "Mermaid"], ["turtle", "Turtle"], ["cypher", "Cypher"],
    ["csv", "CSV"], ["jsonld", "JSON-LD"], ["json", "JSON"], ["project", "Projet JSON"],
    ["dashboard", "Tableaux HTML"], ["jsonl", "JSONL"]
  ];

  var lang = localStorage.getItem("ontology.lang") || "fr";
  var viewName = localStorage.getItem("ontology.view") || "graph";
  var state = null;
  var selected = null;
  var filter = null;
  var network = null;
  var nodesDs = null;
  var edgesDs = null;
  var positions = {};
  var jobId = null;
  var queue = [];
  var pumping = false;
  var searchTimer = null;

  function t(key) {
    return (STR[lang] && STR[lang][key]) || STR.fr[key] || key;
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      var value = attrs[key];
      if (key === "class") node.className = value;
      else if (key.slice(0, 2) === "on" && typeof value === "function") node.addEventListener(key.slice(2), value);
      else if (value != null) node.setAttribute(key, value);
    });
    (children || []).forEach(function (child) {
      if (child == null) return;
      node.append(child.nodeType ? child : document.createTextNode(String(child)));
    });
    return node;
  }

  function applyI18n() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach(function (node) {
      node.textContent = t(node.getAttribute("data-i18n"));
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach(function (node) {
      node.setAttribute("placeholder", t(node.getAttribute("data-i18n-placeholder")));
    });
    document.getElementById("lang-btn").textContent = lang === "fr" ? "EN" : "FR";
  }

  function toast(message) {
    var node = document.getElementById("toast");
    node.hidden = false;
    node.textContent = message;
    clearTimeout(toast._timer);
    toast._timer = setTimeout(function () { node.hidden = true; }, 2200);
  }

  function showBanner(message) {
    var node = document.getElementById("banner");
    if (!message) { node.hidden = true; node.textContent = ""; return; }
    node.hidden = false;
    node.textContent = message;
  }

  async function readJson(response) {
    var body = {};
    try { body = await response.json(); } catch (error) { body = {}; }
    if (!response.ok) throw new Error(body.message || response.statusText);
    return body;
  }

  async function refresh() {
    state = await readJson(await fetch("/api/state"));
    if (state.project) {
      try { positions = JSON.parse(localStorage.getItem("ontology.pos." + state.project.id) || "{}"); }
      catch (error) { positions = {}; }
    }
    render();
  }

  function render() {
    syncProject();
    applyI18n();
    var llm = (state && state.llm) || {};
    showBanner(llm.message || "");
    renderChrome();
    renderKpis();
    renderInsight();
    renderStage();
    renderSide();
    renderDownload();
    document.dispatchEvent(new CustomEvent("ontology:render"));
  }

  function syncProject() {
    var project = state && state.project;
    var id = project ? project.id : "";
    if (id === syncProject.current) return;
    syncProject.current = id;
    selected = null;
    filter = null;
    try { positions = JSON.parse(localStorage.getItem("ontology.pos." + id) || "{}"); }
    catch (error) { positions = {}; }
  }

  function renderChrome() {
    var name = document.getElementById("project-name");
    var project = state && state.project;
    if (document.activeElement !== name) {
      name.value = project ? project.name : "";
      name.disabled = !project;
      name.title = project ? t("path") + " " + project.path : "";
    }
    var select = document.getElementById("project-switch");
    var projects = (state && state.projects) || [];
    select.hidden = projects.length < 2;
    select.replaceChildren();
    projects.forEach(function (item) {
      var option = el("option", { value: item.id }, [item.name]);
      if (project && item.id === project.id) option.selected = true;
      select.append(option);
    });
    var undo = state && state.undo;
    document.getElementById("undo-btn").disabled = !(undo && undo.can_undo);
    document.getElementById("redo-btn").disabled = !(undo && undo.can_redo);
    document.querySelectorAll(".views button").forEach(function (button) {
      button.classList.toggle("is-on", button.getAttribute("data-view") === viewName);
    });
  }

  function kpi(key, value, detail, onClick) {
    return el("button", { type: "button", class: "kpi" + (filter && filter.kind === key ? " is-on" : ""), onclick: onClick, title: detail || "" }, [
      el("b", {}, [value]),
      el("span", {}, [t(key === "failed" ? "failed" : key)]),
      detail ? el("small", {}, [detail]) : null
    ]);
  }

  function renderKpis() {
    var stats = (state && state.stats) || {};
    var last = stats.last_document;
    var orphanPct = Math.round((stats.orphan_ratio || 0) * 100);
    var box = document.getElementById("kpis");
    box.replaceChildren(
      kpi("concepts", stats.concepts || 0, "", function () { setFilter(null); }),
      kpi("relations", stats.relations || 0, "", function () { setFilter(null); }),
      kpi("facts", stats.facts || 0, last && stats.documents > 1 ? last.facts + " " + t("lastDoc") : "", function () { setFilter(null); }),
      kpi("documents", stats.documents || 0, "", function () { setFilter(null); }),
      kpi("orphans", stats.orphans || 0, orphanPct + " % " + t("ofNodes"), function () {
        setFilter(filter && filter.kind === "orphan" ? null : { kind: "orphan", value: "" });
      }),
      kpi("failed", stats.failed_chunks || 0, t("orphanHelp") && "", function () { setFilter(null); })
    );
    box.querySelectorAll(".kpi")[4].title = t("orphanHelp");
  }

  function renderInsight() {
    var stats = (state && state.stats) || {};
    var names = stats.insight_classes || [];
    var node = document.getElementById("insight");
    if (!names.length) node.textContent = (stats.documents || stats.concepts) ? t("none") : t("insightEmpty");
    else node.textContent = t("insight") + names.join(", ") + ".";
  }

  function hasContent() {
    var stats = (state && state.stats) || {};
    return (stats.concepts || 0) + (stats.documents || 0) > 0;
  }

  function renderStage() {
    var empty = document.getElementById("empty");
    var graphWrap = document.getElementById("graph-wrap");
    var table = document.getElementById("table-view");
    var tree = document.getElementById("tree-view");
    empty.hidden = hasContent();
    var showGraph = viewName === "graph";
    var panel = document.getElementById("panel-view");
    var panelViews = { documents: 1, analysis: 1, dashboards: 1, guide: 1, schema: 1, explorer: 1 };
    graphWrap.hidden = !showGraph;
    table.hidden = !(viewName === "glossary" || viewName === "facts");
    tree.hidden = viewName !== "hierarchy";
    if (panel) panel.hidden = !panelViews[viewName];
    if (showGraph) renderGraph();
    if (panelViews[viewName] && window.StudioPanels) window.StudioPanels.render(viewName);
    if (viewName === "glossary") renderTable("glossary");
    if (viewName === "facts") renderTable("facts");
    if (viewName === "hierarchy") renderTree();
    if (showGraph && network) network.redraw();
  }

  function familyColor(family) {
    var families = [];
    ((state.graph && state.graph.nodes) || []).forEach(function (node) {
      if (node.family && families.indexOf(node.family) < 0) families.push(node.family);
    });
    families.sort();
    var index = Math.max(0, families.indexOf(family));
    return PALETTE[index % PALETTE.length];
  }

  function nodeColor(node) {
    var box = document.getElementById("communities");
    if (box && box.checked) return PALETTE[(node.community || 0) % PALETTE.length];
    return familyColor(node.family || "");
  }

  function networkOptions(reduce) {
    var layout = (document.getElementById("layout") || {}).value || "force";
    var options = {
      physics: reduce ? false : { stabilization: { iterations: 180 }, barnesHut: { springLength: 140 } },
      interaction: { hover: true, keyboard: true, tooltipDelay: 120 },
      edges: { smooth: { type: "dynamic" } }
    };
    if (layout === "hierarchy") {
      options.layout = { hierarchical: { direction: "UD", sortMethod: "directed", levelSeparation: 90 } };
      options.physics = false;
    }
    return options;
  }

  function inkFor(fill) {
    var hex = fill.replace("#", "");
    var r = parseInt(hex.slice(0, 2), 16);
    var g = parseInt(hex.slice(2, 4), 16);
    var b = parseInt(hex.slice(4, 6), 16);
    return (r * 0.299 + g * 0.587 + b * 0.114) > 150 ? "#1c2430" : "#ffffff";
  }

  function visibleGraph() {
    var nodes = ((state.graph && state.graph.nodes) || []).slice();
    var edges = ((state.graph && state.graph.edges) || []).slice();
    if (document.getElementById("show-literals").checked) {
      nodes.forEach(function (node) {
        (node.attributes || []).forEach(function (attribute) {
          var id = "l:" + node.id + ":" + attribute.key;
          nodes.push({
            id: id, label: attribute.value, kind: "literal", family: node.family,
            degree: 1, orphan: false, documents: node.documents || [], types: [],
            description: attribute.key, parent: null, attributes: []
          });
          edges.push({ id: "la-" + id, from: node.id, to: id, label: attribute.key, kind: "attribute", support: 1 });
        });
      });
    }
    if (document.getElementById("focus-mode") && document.getElementById("focus-mode").checked && selected) {
      var keep = neighborSet(selected, edges);
      nodes = nodes.filter(function (node) { return keep[node.id]; });
      var keepIds = {};
      nodes.forEach(function (node) { keepIds[node.id] = true; });
      edges = edges.filter(function (edge) { return keepIds[edge.from] && keepIds[edge.to]; });
    }
    if (document.getElementById("classes-only").checked) {
      var classIds = {};
      nodes = nodes.filter(function (node) { if (node.kind === "class") { classIds[node.id] = true; return true; } return false; });
      edges = edges.filter(function (edge) { return classIds[edge.from] && classIds[edge.to]; });
    }
    if (!document.getElementById("show-types").checked) {
      edges = edges.filter(function (edge) { return edge.kind !== "type"; });
    }
    var allowed = null;
    if (filter && filter.kind === "orphan") {
      allowed = {};
      nodes.forEach(function (node) { if (node.orphan) allowed[node.id] = true; });
    } else if (filter && filter.kind === "class") {
      allowed = {};
      nodes.forEach(function (node) {
        var types = node.types || [];
        if (node.label === filter.value || node.family === filter.value || types.indexOf(filter.value) >= 0) allowed[node.id] = true;
      });
      expand(allowed, edges);
    } else if (filter && filter.kind === "predicate") {
      allowed = {};
      edges.forEach(function (edge) {
        if (edge.label === filter.value) { allowed[edge.from] = true; allowed[edge.to] = true; }
      });
    } else if (filter && filter.kind === "search" && filter.value) {
      var query = filter.value.toLowerCase();
      allowed = {};
      nodes.forEach(function (node) {
        if (String(node.label).toLowerCase().indexOf(query) >= 0) allowed[node.id] = true;
      });
      expand(allowed, edges);
    } else if (filter && filter.kind === "document") {
      allowed = {};
      nodes.forEach(function (node) {
        if ((node.documents || []).indexOf(filter.value) >= 0) allowed[node.id] = true;
      });
      expand(allowed, edges);
    } else if (filter && filter.kind === "genre") {
      allowed = {};
      nodes.forEach(function (node) {
        if ((node.genres || []).indexOf(filter.value) >= 0) allowed[node.id] = true;
      });
      expand(allowed, edges);
    } else if (filter && filter.kind === "scope") {
      allowed = {};
      nodes.forEach(function (node) {
        if (node.scope === filter.value) allowed[node.id] = true;
      });
    } else if (filter && filter.kind === "ids") {
      allowed = {};
      var wanted = filter.value || [];
      nodes.forEach(function (node) {
        if (wanted.indexOf(node.id) >= 0 || wanted.indexOf(node.label) >= 0) allowed[node.id] = true;
      });
    }
    if (allowed) {
      nodes = nodes.filter(function (node) { return allowed[node.id]; });
      var ids = {};
      nodes.forEach(function (node) { ids[node.id] = true; });
      edges = edges.filter(function (edge) { return ids[edge.from] && ids[edge.to]; });
    }
    return { nodes: nodes, edges: edges };
  }

  function expand(allowed, edges) {
    var extra = {};
    edges.forEach(function (edge) {
      if (allowed[edge.from]) extra[edge.to] = true;
      if (allowed[edge.to]) extra[edge.from] = true;
    });
    Object.keys(extra).forEach(function (id) { allowed[id] = true; });
  }

  function renderLegend(nodes) {
    var box = document.getElementById("legend");
    var seen = [];
    nodes.forEach(function (node) {
      if (node.kind === "literal") return;
      if (seen.indexOf(node.family) < 0) seen.push(node.family);
    });
    seen.sort();
    box.replaceChildren();
    seen.slice(0, 6).forEach(function (family) {
      var color = familyColor(family);
      box.append(el("span", {}, [
        el("i", { class: "swatch class", style: "background:" + color }),
        family
      ]));
    });
  }

  function renderGraph() {
    var built = visibleGraph();
    renderLegend(built.nodes);
    if (typeof vis === "undefined") {
      document.getElementById("graph").textContent = t("noGraph");
      return;
    }
    var focus = selected ? neighborSet(selected, built.edges) : null;
    var visNodes = built.nodes.map(function (node) {
      var color = node.kind === "literal" ? "#5c6b80" : nodeColor(node);
      var shape = node.kind === "class" ? "diamond" : (node.kind === "literal" ? "box" : "dot");
      var size = Math.max(12, Math.min(40, 8 + 7 * Math.sqrt(node.degree || 0)));
      var dim = focus && !focus[node.id];
      var item = {
        id: node.id,
        label: node.label,
        shape: shape,
        size: node.kind === "class" ? Math.max(16, size) : size,
        color: { background: color, border: dim ? "#d9e0ea" : "#1c2430", highlight: { background: color, border: "#1c2430" } },
        font: { color: dim ? "#9aa6b6" : inkFor(color), size: 13, face: "Segoe UI, system-ui, sans-serif" },
        opacity: dim ? 0.18 : 1
      };
      if (positions[node.id]) { item.x = positions[node.id].x; item.y = positions[node.id].y; }
      return item;
    });
    var layoutName = (document.getElementById("layout") || {}).value || "force";
    if (layoutName === "circle") {
      visNodes.forEach(function (item, index) {
        if (item.x != null) return;
        var angle = (Math.PI * 2 * index) / Math.max(1, visNodes.length);
        item.x = Math.cos(angle) * 280;
        item.y = Math.sin(angle) * 280;
      });
    }
    var visEdges = built.edges.map(function (edge) {
      var dim = focus && !(focus[edge.from] && focus[edge.to]);
      return {
        id: edge.id, from: edge.from, to: edge.to,
        label: edge.kind === "type" ? "" : edge.label,
        arrows: "to",
        dashes: edge.kind === "hierarchy" || edge.kind === "type" || edge.kind === "note",
        width: edge.kind === "relation" ? Math.min(6, 1 + Math.sqrt(edge.support || 1)) : 1,
        color: { color: dim ? "#e1e6ee" : (edge.kind === "note" ? "#e69f00" : "#5c6b80") },
        font: { color: "#3e4a5c", strokeWidth: 0, size: 11, align: "middle" }
      };
    });
    if (!nodesDs) {
      nodesDs = new vis.DataSet(visNodes);
      edgesDs = new vis.DataSet(visEdges);
      var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      network = new vis.Network(document.getElementById("graph"), { nodes: nodesDs, edges: edgesDs }, networkOptions(reduce));
      network.on("click", function (params) {
        selected = params.nodes.length ? params.nodes[0] : null;
        renderGraph();
        renderSide();
      });
      network.on("dragEnd", savePositions);
      network.on("stabilizationIterationsDone", function () {
        network.setOptions({ physics: false });
        savePositions();
        network.fit({ animation: false });
      });
    } else {
      nodesDs.clear();
      edgesDs.clear();
      nodesDs.add(visNodes);
      edgesDs.add(visEdges);
      var missing = visNodes.some(function (node) { return !positions[node.id]; });
      var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      network.setOptions({ physics: missing && !reduceMotion });
    }
    if (selected && visNodes.some(function (node) { return node.id === selected; })) {
      network.selectNodes([selected]);
    }
    var signature = visNodes.map(function (node) { return node.id; }).sort().join("\n");
    if (signature && signature !== renderGraph.signature) {
      renderGraph.signature = signature;
      requestAnimationFrame(function () { if (network) network.fit({ animation: false }); });
    }
    drawMinimap();
  }

  function drawMinimap() {
    var canvas = document.getElementById("minimap");
    if (!canvas || !network) return;
    var ctx = canvas.getContext("2d");
    var positionsNow = network.getPositions();
    var ids = Object.keys(positionsNow);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!ids.length) return;
    var xs = ids.map(function (id) { return positionsNow[id].x; });
    var ys = ids.map(function (id) { return positionsNow[id].y; });
    var minX = Math.min.apply(null, xs), maxX = Math.max.apply(null, xs);
    var minY = Math.min.apply(null, ys), maxY = Math.max.apply(null, ys);
    var spanX = Math.max(1, maxX - minX), spanY = Math.max(1, maxY - minY);
    ids.forEach(function (id) {
      var x = 6 + ((positionsNow[id].x - minX) / spanX) * (canvas.width - 12);
      var y = 6 + ((positionsNow[id].y - minY) / spanY) * (canvas.height - 12);
      ctx.fillStyle = "#0072B2";
      ctx.fillRect(x, y, 3, 3);
    });
  }

  function neighborSet(id, edges) {
    var set = {};
    set[id] = true;
    edges.forEach(function (edge) {
      if (edge.from === id) set[edge.to] = true;
      if (edge.to === id) set[edge.from] = true;
    });
    return set;
  }

  function savePositions() {
    if (!network || !state.project) return;
    var current = network.getPositions();
    Object.keys(current).forEach(function (id) { positions[id] = current[id]; });
    localStorage.setItem("ontology.pos." + state.project.id, JSON.stringify(positions));
  }

  function renderTable(kind) {
    var box = document.getElementById("table-view");
    var rows = kind === "glossary" ? (state.glossary || []) : (state.facts || []);
    var query = (document.getElementById("search").value || "").toLowerCase();
    if (query) {
      rows = rows.filter(function (row) {
        return JSON.stringify(row).toLowerCase().indexOf(query) >= 0;
      });
    }
    var columns = kind === "glossary"
      ? [["name", t("class")], ["parent", t("parent")], ["description", t("description")], ["entities", t("entities") || "Entités"]]
      : [["subject", t("entity")], ["predicate", t("relations")], ["object", t("class")], ["support", t("support")], ["documents", t("documents")]];
    var table = el("table", {}, []);
    var head = el("tr", {}, columns.map(function (column) {
      return el("th", { onclick: function () { sortTable(kind, column[0]); } }, [column[1]]);
    }));
    table.append(el("thead", {}, [head]));
    var body = el("tbody", {}, []);
    rows.forEach(function (row) {
      var line = el("tr", {
        onclick: function () {
          if (kind === "glossary") selectByLabel(row.name, "class");
          else selectByLabel(row.subject, "entity");
        }
      }, columns.map(function (column) {
        var value = row[column[0]];
        if (Array.isArray(value)) value = value.join(", ");
        return el("td", {}, [value == null || value === "" ? "—" : String(value)]);
      }));
      body.append(line);
    });
    table.append(body);
    box.replaceChildren(table);
  }

  var sortState = {};
  function sortTable(kind, key) {
    var list = kind === "glossary" ? state.glossary : state.facts;
    var dir = sortState[kind + key] === 1 ? -1 : 1;
    sortState[kind + key] = dir;
    list.sort(function (a, b) {
      var left = a[key];
      var right = b[key];
      if (typeof left === "number" && typeof right === "number") return (left - right) * dir;
      return String(left || "").localeCompare(String(right || ""), lang) * dir;
    });
    renderTable(kind);
  }

  function renderTree() {
    var box = document.getElementById("tree-view");
    var classes = {};
    (state.glossary || []).forEach(function (item) { classes[item.name] = item; });
    var children = {};
    Object.keys(classes).forEach(function (name) {
      var parent = classes[name].parent;
      var key = parent || "";
      (children[key] = children[key] || []).push(name);
    });
    function entitiesOf(name) {
      return (state.graph.nodes || []).filter(function (node) {
        return node.kind === "entity" && (node.types || [])[0] === name;
      });
    }
    function walk(name) {
      var item = classes[name];
      var row = el("li", {}, [
        el("button", { type: "button", class: "row" + (selected === "c:" + name ? " is-on" : ""), onclick: function () { selectByLabel(name, "class"); } }, [
          el("b", {}, [name]),
          el("span", { class: "kind-tag" }, [item.entities ? item.entities + " · " : "", item.description || ""])
        ])
      ]);
      var list = el("ul", {}, []);
      entitiesOf(name).forEach(function (entity) {
        list.append(el("li", {}, [
          el("button", { type: "button", class: "row" + (selected === entity.id ? " is-on" : ""), onclick: function () { selected = entity.id; viewName = "graph"; render(); } }, [
            entity.label
          ])
        ]));
      });
      (children[name] || []).sort().forEach(function (child) { list.append(walk(child)); });
      if (list.childNodes.length) row.append(list);
      return row;
    }
    var root = el("ul", {}, []);
    (children[""] || []).sort().forEach(function (name) { root.append(walk(name)); });
    box.replaceChildren(root);
  }

  function findNode(id) {
    return ((state.graph && state.graph.nodes) || []).filter(function (node) { return node.id === id; })[0] || null;
  }

  function selectByLabel(label, kind) {
    var found = ((state.graph && state.graph.nodes) || []).filter(function (node) {
      return node.label === label && (!kind || node.kind === kind);
    })[0];
    selected = found ? found.id : null;
    if (viewName !== "graph" && viewName !== "hierarchy") viewName = "graph";
    render();
  }

  function renderSide() {
    var side = document.getElementById("side");
    if (!state || !hasContent()) {
      side.replaceChildren(el("p", { class: "muted" }, [t("select")]));
      return;
    }
    var node = selected ? findNode(selected) : null;
    if (!node) side.replaceChildren(dashboard());
    else side.replaceChildren(details(node));
  }

  function dashboard() {
    var stats = state.stats || {};
    var wrap = el("div", {}, [
      el("h2", {}, [state.project ? state.project.name : ""]),
      el("p", { class: "crumb" }, [state.project ? state.project.path : ""])
    ]);
    var ask = el("form", { class: "ask", onsubmit: function (event) {
      event.preventDefault();
      var input = event.target.querySelector("input");
      fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: input.value })
      }).then(readJson).then(function (body) {
        var out = document.getElementById("ask-answer");
        if (!out) return;
        var lines = [body.answer || ""];
        (body.facts || []).slice(0, 3).forEach(function (fact) {
          if (fact.quote) lines.push(fact.filename + " — " + fact.quote);
        });
        out.textContent = lines.join("\n");
      }).catch(function (error) { showBanner(error.message); });
    }}, [
      el("h3", {}, [t("ask")]),
      el("input", { type: "search", placeholder: t("askPlaceholder"), "aria-label": t("ask") }),
      el("p", { id: "ask-answer", class: "muted" }, [])
    ]);
    wrap.append(ask);
    wrap.append(el("h3", {}, [t("topClasses")]));
    wrap.append(bars(stats.top_classes || [], "class"));
    wrap.append(el("h3", {}, [t("topPredicates")]));
    wrap.append(bars(stats.top_predicates || [], "predicate"));
    wrap.append(el("h3", {}, [t("growth")]));
    wrap.append(spark(stats.per_document || []));
    wrap.append(el("h3", {}, [t("docs")]));
    wrap.append(documentList());
    if ((state.suggestions || []).length) {
      wrap.append(el("h3", {}, [t("suggestions")]));
      state.suggestions.forEach(function (pair) {
        wrap.append(el("button", { type: "button", onclick: function () { merge(pair.a, pair.b); } }, [
          pair.a + " → " + pair.b
        ]));
      });
    }
    return wrap;
  }

  function bars(items, kind) {
    var max = items.reduce(function (acc, item) { return Math.max(acc, item.count); }, 1);
    var box = el("div", { class: "bars" }, []);
    if (!items.length) box.append(el("p", { class: "muted" }, [t("none")]));
    items.forEach(function (item) {
      box.append(el("div", { class: "bar-row" }, [
        el("button", { type: "button", onclick: function () { setFilter({ kind: kind, value: item.name }); } }, [
          item.name,
          el("span", { class: "track" }, [el("span", { class: "fill", style: "width:" + Math.round(100 * item.count / max) + "%" })])
        ]),
        el("em", {}, [String(item.count)])
      ]));
    });
    return box;
  }

  function spark(items) {
    var max = items.reduce(function (acc, item) { return Math.max(acc, item.facts); }, 1);
    var box = el("div", { class: "spark" }, []);
    items.forEach(function (item) {
      var height = Math.max(4, Math.round(36 * item.facts / max));
      box.append(el("button", {
        type: "button",
        title: item.filename + " · " + item.facts,
        style: "height:" + height + "px",
        onclick: function () { setFilter({ kind: "document", value: item.id }); }
      }));
    });
    return box;
  }

  function statusLabel(status) {
    var key = { ok: "statusOk", incomplete: "statusIncomplete", failed: "statusFailed", cancelled: "statusCancelled", running: "statusRunning" }[status];
    return key ? t(key) : status;
  }

  function documentList() {
    var list = el("ul", { class: "doc-list" }, []);
    (state.documents || []).forEach(function (document) {
      var failed = (document.chunks_failed || []).length;
      list.append(el("li", {}, [
        el("button", { type: "button", onclick: function () { setFilter({ kind: "document", value: document.id }); } }, [document.filename]),
        el("div", { class: "muted" }, [
          statusLabel(document.status),
          " · ",
          document.chunks_total + " · " + document.duration_s + " s",
          failed ? el("div", { class: "bad" }, [failed + " " + t("failedChunk")]) : null
        ]),
        (document.warnings || []).slice(0, 3).map(function (warning) {
          return el("div", { class: warning.indexOf("INCOMPLETE") >= 0 || warning.indexOf("CANCELLED") >= 0 ? "bad" : "muted" }, [warning]);
        })
      ]));
    });
    return list;
  }

  function details(node) {
    var project = state.project ? state.project.name : "";
    var crumb = [project, node.family, node.label].filter(Boolean).join(" › ");
    var wrap = el("div", {}, [
      el("p", { class: "crumb" }, [crumb]),
      el("h2", {}, [node.label]),
      el("p", { class: "kind-tag" }, [
        (t(node.kind) || node.kind),
        node.group ? " · " + node.group : "",
        node.status ? " · " + node.status : "",
        node.orphan ? " · " + t("orphans") : ""
      ])
    ]);
    wrap.append(el("button", { type: "button", onclick: function () { selected = null; renderGraph(); renderSide(); } }, ["←"]));
    var props = (node.typed_properties || []).filter(function (item) { return item.visibility !== "hidden"; });
    if (props.length) {
      wrap.append(el("h3", {}, [lang === "fr" ? "Propriétés" : "Properties"]));
      props.forEach(function (item) {
        wrap.append(el("p", {}, [item.key + " · " + item.base_type + " · " + item.value]));
      });
    }
    var nameField = el("input", { type: "text", value: node.label });
    nameField.addEventListener("change", function () {
      if (nameField.value.trim() && nameField.value !== node.label) {
        edit(node.kind === "class"
          ? { op: "rename_class", old: node.label, new: nameField.value.trim() }
          : { op: "rename_entity", old: node.label, new: nameField.value.trim() });
      }
    });
    wrap.append(el("label", {}, [t("rename"), nameField]));
    if (node.kind === "class") {
      var description = el("textarea", { rows: "3" }, [node.description || ""]);
      description.addEventListener("change", function () {
        edit({ op: "update_description", old: node.label, description: description.value });
      });
      wrap.append(el("label", {}, [t("description"), description]));
      wrap.append(el("button", { type: "button", class: "danger", onclick: function () {
        edit({ op: "delete_class", old: node.label });
      } }, [t("deleteClass")]));
    }
    (state.suggestions || []).forEach(function (pair) {
      var other = pair.a === node.label ? pair.b : (pair.b === node.label ? pair.a : "");
      if (!other) return;
      wrap.append(el("button", { type: "button", onclick: function () { merge(node.label, other); } }, [
        t("merge") + " " + other
      ]));
    });
    if (node.parent) wrap.append(el("p", {}, [t("parent") + " : " + node.parent]));
    if ((node.types || []).length) wrap.append(el("p", {}, [t("types") + " : " + node.types.join(", ")]));
    relationLists(wrap, node);
    provenance(wrap, node);
    return wrap;
  }

  function relationLists(wrap, node) {
    var edges = (state.graph && state.graph.edges) || [];
    var byId = {};
    (state.graph.nodes || []).forEach(function (item) { byId[item.id] = item; });
    var outgoing = edges.filter(function (edge) { return edge.from === node.id && edge.kind !== "type"; });
    var incoming = edges.filter(function (edge) { return edge.to === node.id && edge.kind === "relation"; });
    function list(title, items, incomingEdge) {
      if (!items.length) return;
      wrap.append(el("h3", {}, [title]));
      items.forEach(function (edge) {
        var other = byId[incomingEdge ? edge.from : edge.to];
        var label = (edge.label || "est_un") + " → " + (other ? other.label : "");
        var line = el("div", { class: "fact-line" }, [
          el("button", { type: "button", onclick: function () { selected = other ? other.id : selected; render(); } }, [label]),
        ]);
        if (edge.kind === "relation") {
          var subject = incomingEdge ? other.label : node.label;
          var object = incomingEdge ? node.label : other.label;
          line.append(el("button", { type: "button", onclick: function () {
            edit({ op: "delete_triplet", subject: subject, predicate: edge.label, object: object });
          } }, [t("deleteFact")]));
        }
        wrap.append(line);
      });
    }
    list(t("outgoing"), outgoing, false);
    list(t("incoming"), incoming, true);
    if ((node.attributes || []).length) {
      wrap.append(el("h3", {}, [t("attributes")]));
      node.attributes.forEach(function (attribute) {
        var line = el("div", { class: "fact-line" }, [
          attribute.key + " : " + attribute.value
        ]);
        if (node.kind === "entity") {
          line.append(el("button", { type: "button", onclick: function () {
            edit({ op: "delete_attribute", entity: node.label, key: attribute.key, value: attribute.value });
          } }, [t("deleteFact")]));
        }
        wrap.append(line);
      });
    }
  }

  function provenance(wrap, node) {
    var related = (state.facts || []).filter(function (fact) {
      return fact.subject === node.label || fact.object === node.label;
    });
    wrap.append(el("h3", {}, [t("why")]));
    if (!related.length) {
      wrap.append(el("p", { class: "muted" }, [t("noSource")]));
      return;
    }
    var shown = 0;
    related.forEach(function (fact) {
      (fact.sources || []).forEach(function (source) {
        if (shown >= 6) return;
        shown += 1;
        wrap.append(el("p", { class: "quote" }, [
          source.filename + " · " + t("chunk") + " " + source.chunk_index,
          el("br"),
          source.quote || t("noSource")
        ]));
      });
    });
    if (!shown) wrap.append(el("p", { class: "muted" }, [t("noSource")]));
  }

  function setFilter(next) {
    filter = next;
    render();
  }

  async function edit(payload) {
    try {
      state = await readJson(await fetch("/api/edits", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }));
      if (payload.op === "rename_class" || payload.op === "rename_entity") {
        var prefix = payload.op === "rename_class" ? "c:" : "e:";
        selected = prefix + payload.new;
      }
      if (payload.op === "delete_class" || payload.op === "delete_triplet") selected = null;
      toast(t("saved") + (state.project ? " · " + state.project.path : ""));
      render();
    } catch (error) {
      showBanner(error.message);
    }
  }

  function merge(source, target) {
    edit({ op: "merge_entities", source: source, target: target });
  }

  async function postJson(url, body) {
    state = await readJson(await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : "{}"
    }));
    render();
  }

  function renderDownload() {
    var list = document.getElementById("download-list");
    list.replaceChildren();
    var disabled = !(state && state.project);
    FORMATS.forEach(function (format) {
      var link = el("a", {
        href: disabled ? "#" : "/api/export?format=" + format[0],
        download: ""
      }, [format[1]]);
      if (disabled) link.addEventListener("click", function (event) { event.preventDefault(); });
      list.append(link);
    });
  }

  function openSettings() {
    var drawer = document.getElementById("settings");
    var llm = state.llm || {};
    var form = document.getElementById("settings-form");
    form.endpoint.value = llm.endpoint || "";
    form.model.value = llm.model || "";
    form.api_key.value = "";
    form.chunk_chars.value = llm.chunk_chars || 12000;
    form.timeout_s.value = llm.timeout_s || 120;
    form.max_tokens.value = llm.max_tokens || 8192;
    if (form.watch_dir) form.watch_dir.value = llm.watch_dir || "";
    var source = { env: t("sourceEnv"), file: t("sourceFile"), default: t("sourceDefault") }[llm.source] || "";
    document.getElementById("settings-source").textContent = source + (llm.key_hint ? " " + llm.key_hint : "");
    document.getElementById("test-result").textContent = "";
    drawer.hidden = false;
  }

  async function upload(file, force) {
    var data = new FormData();
    data.append("file", file, file.name);
    if (force) data.append("force", "1");
    var response = await fetch("/api/ingest", { method: "POST", body: data });
    var body = await readJson(response);
    if (body.job_id) await follow(body.job_id, file.name);
    else { state = body; render(); }
  }

  async function follow(id, filename) {
    jobId = id;
    var box = document.getElementById("progress");
    box.hidden = false;
    document.getElementById("progress-list").replaceChildren();
    var response = await fetch("/api/jobs/" + id + "/events");
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";
    while (true) {
      var step = await reader.read();
      if (step.done) break;
      buffer += decoder.decode(step.value, { stream: true });
      var blocks = buffer.split("\n\n");
      buffer = blocks.pop();
      blocks.forEach(handleEventBlock);
    }
    await refresh();
    box.hidden = true;
    jobId = null;
  }

  function handleEventBlock(block) {
    var line = block.split("\n").filter(function (item) { return item.indexOf("data:") === 0; })[0];
    if (!line) return;
    var event = JSON.parse(line.slice(5).trim());
    var label = document.getElementById("progress-label");
    var list = document.getElementById("progress-list");
    if (event.type === "chunk") {
      var pct = Math.round(100 * event.index / Math.max(1, event.total));
      if (event.status === "started") pct = Math.round(100 * (event.index - 1) / Math.max(1, event.total));
      document.getElementById("progress-bar").style.width = pct + "%";
      var eta = event.eta_s != null ? " · " + t("eta") + " " + event.eta_s + " " + t("seconds") : "";
      label.textContent = t("running") + " " + event.index + "/" + event.total + eta;
      if (event.status !== "started") {
        var cls = event.status === "failed" ? "bad" : "ok";
        var word = event.status === "cached" ? t("cached") : (event.status === "failed" ? t("failedChunk") : t("done"));
        list.append(el("li", { class: cls }, [t("chunk") + " " + event.index + " — " + word]));
      }
      if (event.status === "ok" || event.status === "cached") refresh().catch(function () {});
    } else if (event.type === "duplicate") {
      label.textContent = event.message || t("duplicate");
    } else if (event.type === "error") {
      showBanner(event.message || "");
    } else if (event.type === "read" && (event.warnings || []).length) {
      showBanner(event.warnings[0]);
    }
  }

  async function pump() {
    if (pumping) return;
    pumping = true;
    try {
      while (queue.length) {
        var file = queue.shift();
        document.getElementById("drop-name").textContent = file.name;
        await upload(file, false);
      }
    } catch (error) {
      showBanner(error.message);
      document.getElementById("progress").hidden = true;
    } finally {
      pumping = false;
      if (queue.length) pump();
    }
  }

  function enqueue(files) {
    Array.prototype.forEach.call(files, function (file) { queue.push(file); });
    pump();
  }

  document.getElementById("file-input").addEventListener("change", function (event) {
    enqueue(event.target.files);
    event.target.value = "";
  });
  document.getElementById("add-btn").addEventListener("click", function () {
    document.getElementById("file-input").click();
  });
  document.getElementById("paste-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    var text = document.getElementById("paste").value;
    if (!text.trim()) return;
    try {
      var response = await fetch("/api/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text, filename: "colle.txt" })
      });
      var body = await readJson(response);
      document.getElementById("paste").value = "";
      if (body.job_id) await follow(body.job_id, "colle.txt");
      else { state = body; render(); }
    } catch (error) {
      showBanner(error.message);
    }
  });
  document.getElementById("sample-btn").addEventListener("click", function () {
    postJson("/api/sample").then(function () { toast(t("saved")); }).catch(function (error) { showBanner(error.message); });
  });
  document.querySelectorAll(".views button").forEach(function (button) {
    button.addEventListener("click", function () {
      viewName = button.getAttribute("data-view");
      localStorage.setItem("ontology.view", viewName);
      render();
    });
  });
  document.getElementById("search").addEventListener("input", function (event) {
    clearTimeout(searchTimer);
    var value = event.target.value.trim();
    searchTimer = setTimeout(function () {
      filter = value ? { kind: "search", value: value } : null;
      renderStage();
      if (viewName === "graph" && network) {
        var match = (state.graph.nodes || []).filter(function (node) {
          return node.label.toLowerCase() === value.toLowerCase();
        })[0];
        if (match) { selected = match.id; network.focus(match.id, { scale: 1.1, animation: false }); renderSide(); }
      }
    }, 160);
  });
  document.getElementById("undo-btn").addEventListener("click", function () { postJson("/api/undo").catch(function (error) { showBanner(error.message); }); });
  document.getElementById("redo-btn").addEventListener("click", function () { postJson("/api/redo").catch(function (error) { showBanner(error.message); }); });
  document.getElementById("layout").addEventListener("change", function () {
    nodesDs = null;
    network = null;
    if (viewName === "graph") renderGraph();
  });
  document.getElementById("fit-btn").addEventListener("click", function () {
    if (network) network.fit({ animation: false });
  });
  document.getElementById("theme-btn").addEventListener("click", function () {
    var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("ontology.theme", next);
    document.getElementById("theme-btn").textContent = next === "dark" ? (lang === "fr" ? "Clair" : "Light") : t("theme");
  });
  document.getElementById("lang-btn").addEventListener("click", function () {
    lang = lang === "fr" ? "en" : "fr";
    localStorage.setItem("ontology.lang", lang);
    render();
  });
  document.getElementById("settings-btn").addEventListener("click", openSettings);
  document.getElementById("settings-close").addEventListener("click", function () {
    document.getElementById("settings").hidden = true;
  });
  document.getElementById("settings-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    var form = event.target;
    var payload = {
      endpoint: form.endpoint.value.trim(),
      model: form.model.value.trim(),
      timeout_s: Number(form.timeout_s.value),
      max_tokens: Number(form.max_tokens.value),
      chunk_chars: Number(form.chunk_chars.value),
      watch_dir: form.watch_dir ? form.watch_dir.value.trim() : ""
    };
    if (form.api_key.value.trim()) payload.api_key = form.api_key.value.trim();
    try {
      var llm = await readJson(await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }));
      state.llm = llm;
      toast(t("saved"));
      render();
    } catch (error) {
      document.getElementById("test-result").textContent = error.message;
    }
  });
  document.getElementById("test-connection").addEventListener("click", async function () {
    var result = await readJson(await fetch("/api/settings/test", { method: "POST" }));
    document.getElementById("test-result").textContent = result.message || "";
  });
  document.getElementById("new-project").addEventListener("click", function () {
    postJson("/api/projects", { name: t("newProject") }).catch(function (error) { showBanner(error.message); });
  });
  document.getElementById("project-name").addEventListener("change", async function (event) {
    if (!state.project) return;
    try {
      state = await readJson(await fetch("/api/project", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: event.target.value })
      }));
      toast(t("saved"));
      render();
    } catch (error) { showBanner(error.message); }
  });
  document.getElementById("project-switch").addEventListener("change", function (event) {
    postJson("/api/projects/" + event.target.value + "/open").catch(function (error) { showBanner(error.message); });
  });
  ["show-types", "classes-only", "show-literals", "focus-mode", "communities"].forEach(function (id) {
    document.getElementById(id).addEventListener("change", function () { if (viewName === "graph") renderGraph(); });
  });
  document.getElementById("cancel-btn").addEventListener("click", function () {
    if (jobId) fetch("/api/jobs/" + jobId + "/cancel", { method: "POST" });
  });

  var dragDepth = 0;
  window.addEventListener("dragenter", function (event) {
    if (!event.dataTransfer || !Array.prototype.includes.call(event.dataTransfer.types || [], "Files")) return;
    dragDepth += 1;
    document.body.classList.add("is-dropping");
    var overlay = document.getElementById("drop-overlay");
    overlay.hidden = false;
    var file = event.dataTransfer.files && event.dataTransfer.files[0];
    document.getElementById("drop-name").textContent = file ? file.name + " · " + Math.ceil(file.size / 1024) + " Ko" : "";
  });
  window.addEventListener("dragover", function (event) {
    if (!event.dataTransfer) return;
    event.preventDefault();
  });
  window.addEventListener("dragleave", function () {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) {
      document.body.classList.remove("is-dropping");
      document.getElementById("drop-overlay").hidden = true;
    }
  });
  window.addEventListener("drop", function (event) {
    if (!event.dataTransfer) return;
    event.preventDefault();
    dragDepth = 0;
    document.body.classList.remove("is-dropping");
    document.getElementById("drop-overlay").hidden = true;
    if (event.dataTransfer.files && event.dataTransfer.files.length) enqueue(event.dataTransfer.files);
  });
  window.addEventListener("keydown", function (event) {
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
      event.preventDefault();
      postJson(event.shiftKey ? "/api/redo" : "/api/undo").catch(function (error) { showBanner(error.message); });
    } else if (!typing && event.key === "/") {
      event.preventDefault();
      document.getElementById("search").focus();
    } else if (event.key === "Escape") {
      selected = null;
      filter = null;
      document.getElementById("settings").hidden = true;
      document.getElementById("search").value = "";
      render();
    }
  });

  if (localStorage.getItem("ontology.theme") === "dark") {
    document.documentElement.setAttribute("data-theme", "dark");
  }
  window.StudioUI = {
    get state() { return state; },
    get lang() { return lang; },
    t: t,
    setFilter: setFilter,
    edit: edit,
    postJson: postJson,
    el: el
  };
  refresh().catch(function (error) { showBanner(error.message); });
})();
