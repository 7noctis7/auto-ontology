/* Schema, explorer, lineage, neighbourhood, branches. No external branding. */
(function () {
  "use strict";

  function ui() { return window.StudioUI; }
  function el(tag, attrs, children) { return ui().el(tag, attrs, children); }
  function lang() { return ui().lang; }

  function render(view) {
    var box = document.getElementById("panel-view");
    var state = ui() && ui().state;
    if (!box || !state) return;
    if (view === "schema") box.replaceChildren(schema(state));
    if (view === "explorer") box.replaceChildren(explorer(state));
  }

  function schema(state) {
    var catalog = state.catalog || {};
    var root = el("div", { class: "stack" }, [
      el("h2", {}, [lang() === "fr" ? "Schéma" : "Schema"]),
      el("input", { id: "schema-q", type: "search", placeholder: lang() === "fr" ? "Types, liens, propriétés" : "Types, links, properties" })
    ]);
    var list = el("div", { id: "schema-list" }, []);
    root.append(list);
    function paint() {
      var input = root.querySelector("#schema-q");
      var q = (input && input.value || "").toLowerCase();
      list.replaceChildren();
      section(list, lang() === "fr" ? "Types" : "Types", catalog.object_types || [], q, "object");
      section(list, lang() === "fr" ? "Liens" : "Links", catalog.link_types || [], q, "link");
      section(list, lang() === "fr" ? "Propriétés" : "Properties", catalog.properties || [], q, "property");
    }
    root.querySelector("#schema-q").addEventListener("input", paint);
    paint();
    return root;
  }

  function section(list, title, items, q, kind) {
    var shown = items.filter(function (item) {
      return !q || (item.label + " " + item.id + " " + (item.group || "")).toLowerCase().indexOf(q) >= 0;
    });
    if (!shown.length) return;
    list.append(el("h3", {}, [title]));
    shown.forEach(function (item) {
      var line = el("article", { class: "doc-card" }, [
        el("strong", {}, [item.label || item.id]),
        el("p", { class: "muted" }, [
          (item.status || item.base_type || "") + (item.group ? " · " + item.group : "") +
          (item.shared ? " · " + item.shared : "") + (item.inverse ? " · " + item.inverse : "")
        ])
      ]);
      if (item.status) {
        ["experimental", "active", "deprecated"].forEach(function (status) {
          line.append(el("button", { type: "button", onclick: function () {
            fetch("/api/v1/actions/set_status/apply", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ id: item.id, status: status })
            }).then(function () { return fetch("/api/state"); }).then(function (r) { return r.json(); }).then(function (body) {
              ui().state && (window.location.reload());
            });
          } }, [status]));
        });
      }
      list.append(line);
    });
  }

  function explorer(state) {
    var params = new URLSearchParams(window.location.search);
    var root = el("div", { class: "stack" }, [
      el("h2", {}, ["Explorer"]),
      el("input", { id: "ex-q", type: "search", value: params.get("q") || "" }),
      el("div", { id: "ex-rows" }, []),
      el("button", { type: "button", id: "ex-save" }, [lang() === "fr" ? "Enregistrer l'ensemble" : "Save set"])
    ]);
    function query() {
      var input = root.querySelector("#ex-q");
      return {
        q: input ? input.value.trim() : "",
        type: params.get("type") || "",
        document: params.get("doc") || ""
      };
    }
    function paint() {
      var q = query();
      var url = new URL(window.location.href);
      if (q.q) url.searchParams.set("q", q.q); else url.searchParams.delete("q");
      window.history.replaceState(null, "", url);
      var nodes = ((state.graph && state.graph.nodes) || []).filter(function (node) {
        if (q.q && String(node.label).toLowerCase().indexOf(q.q.toLowerCase()) < 0) return false;
        if (q.type && node.family !== q.type && node.label !== q.type) return false;
        if (q.document && (node.documents || []).indexOf(q.document) < 0) return false;
        return node.kind !== "literal";
      });
      var box = root.querySelector("#ex-rows");
      if (box) {
        box.replaceChildren();
        box.append(el("p", { class: "muted" }, [nodes.length + (lang() === "fr" ? " résultats" : " results")]));
        nodes.slice(0, 40).forEach(function (node) {
          box.append(el("button", { type: "button", onclick: function () {
            ui().setFilter({ kind: "ids", value: nodes.map(function (item) { return item.id; }) });
            var graph = document.querySelector(".views button[data-view='graph']");
            if (graph) graph.click();
          } }, [node.label + " · " + (node.family || "")]));
        });
      }
    }
    var input = root.querySelector("#ex-q");
    if (input) input.addEventListener("input", paint);
    var saveBtn = root.querySelector("#ex-save");
    if (saveBtn) saveBtn.addEventListener("click", function () {
      var name = window.prompt(lang() === "fr" ? "Nom de l'ensemble" : "Set name", query().q || "ensemble");
      if (!name) return;
      fetch("/api/v1/object-sets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name, query: { q: query().q, type: query().type, document: query().document } })
      });
    });
    paint();
    var sets = state.object_sets || [];
    if (sets.length) {
      root.append(el("h3", {}, [lang() === "fr" ? "Ensembles" : "Sets"]));
      sets.forEach(function (set) {
        root.append(el("button", { type: "button", onclick: function () {
          var url = "/api/v1/explore?q=" + encodeURIComponent((set.query && set.query.q) || "");
          fetch(url).then(function (r) { return r.json(); }).then(function (body) {
            ui().setFilter({ kind: "ids", value: (body.rows || []).map(function (row) { return row.id; }) });
            var graph = document.querySelector(".views button[data-view='graph']");
            if (graph) graph.click();
          });
        } }, [set.name]));
      });
    }
    return root;
  }

  function cardExtras() {
    var state = ui() && ui().state;
    var side = document.getElementById("side");
    if (!state || !side) return;
    var heading = side.querySelector("h2");
    if (!heading) return;
    var label = heading.textContent;
    var box = el("div", { class: "stack" }, []);
    box.append(el("h3", {}, [lang() === "fr" ? "Lignée" : "Lineage"]));
    var lineage = el("div", { class: "muted" }, ["…"]);
    box.append(lineage);
    fetch("/api/v1/lineage?name=" + encodeURIComponent(label))
      .then(function (r) { return r.json(); })
      .then(function (body) {
        lineage.replaceChildren();
        (body.steps || []).slice(0, 4).forEach(function (step) {
          lineage.append(el("p", {}, [
            (step.filename || "") + " · morceau " + step.chunk_index + " · " + (step.quote || "")
          ]));
        });
        if (!(body.steps || []).length) lineage.textContent = lang() === "fr" ? "Pas de passage." : "No passage.";
      });
    var depth = el("input", { type: "number", min: "1", max: "3", value: "1" });
    box.append(el("h3", {}, [lang() === "fr" ? "Voisinage" : "Neighbourhood"]));
    var run = el("button", { type: "button" }, [lang() === "fr" ? "Autour" : "Around"]);
    run.addEventListener("click", function () {
      fetch("/api/v1/around", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start: label, depth: Number(depth.value) || 1, direction: "both" })
      }).then(function (r) { return r.json(); }).then(function (body) {
        var note = body.truncated ? (lang() === "fr" ? "Plafond atteint. " : "Cap reached. ") : "";
        ui().setFilter({ kind: "ids", value: body.nodes || [] });
        var graph = document.querySelector(".views button[data-view='graph']");
        if (graph) graph.click();
        if (note) window.alert(note + (body.nodes || []).length);
      });
    });
    box.append(depth);
    box.append(run);
    var near = el("button", { type: "button" }, [lang() === "fr" ? "Candidats proches" : "Similar candidates"]);
    var nearOut = el("div", {}, []);
    near.addEventListener("click", function () {
      fetch("/api/v1/similar").then(function (r) { return r.json(); }).then(function (body) {
        nearOut.replaceChildren();
        (body.candidates || []).forEach(function (pair) {
          if (pair.a !== label && pair.b !== label) return;
          var other = pair.a === label ? pair.b : pair.a;
          nearOut.append(el("button", { type: "button", onclick: function () {
            fetch("/api/v1/actions/merge/preview", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ source: label, target: other })
            }).then(function (r) { return r.json(); }).then(function (diff) {
              var text = (diff.summary || "") + "\n" + (diff.removed || []).join(", ");
              if (window.confirm(text)) {
                ui().postJson("/api/v1/actions/merge/apply", { source: label, target: other });
              }
            });
          } }, [other + " · " + pair.score]));
        });
      });
    });
    box.append(near);
    box.append(nearOut);
    side.append(box);
  }

  function branchBar() {
    var host = document.querySelector(".top");
    if (!host || !ui()) return;
    var bar = document.getElementById("branch-bar");
    if (!bar) {
      bar = el("span", { id: "branch-bar" }, []);
      host.append(bar);
    }
    function paint(body) {
      bar.replaceChildren();
      bar.append(document.createTextNode((body.active || "main") + " "));
      var make = el("button", { type: "button" }, ["+"]);
      make.addEventListener("click", function () {
        var name = window.prompt(lang() === "fr" ? "Branche" : "Branch", "essai");
        if (!name) return;
        ui().postJson("/api/v1/branches", { name: name });
      });
      bar.append(make);
      if ((body.active || "main") !== "main") {
        bar.append(el("button", { type: "button", onclick: function () { ui().postJson("/api/v1/branches/merge", {}); } }, [lang() === "fr" ? "Fusionner" : "Merge"]));
        bar.append(el("button", { type: "button", onclick: function () { ui().postJson("/api/v1/branches/discard", {}); } }, [lang() === "fr" ? "Jeter" : "Discard"]));
      }
    }
    fetch("/api/v1/branches").then(function (r) { return r.json(); }).then(paint).catch(function () {});
  }

  var previous = window.StudioPanels && window.StudioPanels.render;
  window.StudioPanels = {
    render: function (view) {
      if (view === "schema" || view === "explorer") render(view);
      else if (previous) previous(view);
    }
  };

  document.addEventListener("ontology:render", function () {
    var current = document.querySelector(".views button.is-on");
    var view = current ? current.getAttribute("data-view") : "";
    if (view === "schema" || view === "explorer") render(view);
    cardExtras();
    branchBar();
  });

  window.addEventListener("keydown", function (event) {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      var button = document.querySelector(".views button[data-view='schema']");
      if (button) button.click();
      var input = document.getElementById("schema-q");
      if (input) input.focus();
    }
  });
})();
