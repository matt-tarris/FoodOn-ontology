/* Patch layer audit.
 *
 * Reads /api/audit, which runs every pinned query twice -- against the full graph and
 * against a graph with the local layer switched off -- so a row can say how much of its
 * answer is ours. Writes go to /api/audit/edit, which lands them in a governed decision
 * file and regenerates the .ttl from it. Nothing here edits Turtle: the .ttl is output,
 * and test/patch_run.py fails the build on a hand-edit of it.
 *
 * Plain DOM on purpose. The graph app carries preact for a 40k-node canvas that has to
 * re-render at 60fps; this is a few hundred rows that change when a person presses a
 * button, and a second rendering model to keep in step would cost more than it saves.
 */
const CC = {contains:"c-hard", "is a":"c-hard", "in taxon":"c-hard", may_contain:"c-soft",
  shared_compound:"c-soft", cross_reactive:"c-soft", disputed:"c-soft",
  not_avoidance_relevant:"c-neg"};
const EM = "—", RSQ = "’", ARR = "→";
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const trim = (s, n) => { s = String(s ?? ""); return s.length > n ? esc(s.slice(0,n-1))+"…" : esc(s); };
const $ = (sel, el=document) => el.querySelector(sel);
let DATA = null, GMAX = 1, BUSY = false;

/* ---------------------------------------------------------------- purpose line
 * Composed, not extracted. The authored notes on these pins are caveats about the
 * modelling ("this root pivots through `cow food product --in taxon--> Bos taurus`"),
 * which is true and is not why a chef opens the card; FoodOn's function-category
 * rollups cover 2,342 of 39,894 classes and describe US CFR product types. So every
 * clause below comes from a count or a flag already on the card, and none of it is a
 * clinical claim, because nothing in the data supports one.
 *
 * A real purpose sentence is one line of human intent per ingredient. When a pin grows
 * an authored `purpose` field, this should defer to it. */
function purpose(c) {
  const alias = c.aliases.filter(a => a !== c.name);
  const who = `A diner asking for <b>${esc(c.name)}</b>` +
              (alias.length ? ` (also ${esc(alias.join(", "))})` : "");
  const size = c.ours <= 2
    ? `is an <b>endpoint</b> ${EM} FoodOn models ${c.ours === 1
        ? "the term itself and nothing derived from it"
        : "only " + c.ours + " forms of it"}, so this answer has to be finished from a label`
    : `gets <b>${c.ours.toLocaleString()} classes</b> to treat as containing it`;
  let ours;
  if (c.removed && c.added) ours = `Our layer adds ${c.added} and suppresses ${c.removed} of FoodOn${RSQ}s ${c.vendor.toLocaleString()}`;
  else if (c.removed)       ours = `Our layer suppresses ${c.removed} of FoodOn${RSQ}s ${c.vendor.toLocaleString()} ${EM} that suppression is the decision to audit here`;
  else if (c.added)         ours = `FoodOn supplies ${c.vendor.toLocaleString()} of those; our layer adds the other ${c.added}`;
  else                      ours = `Entirely FoodOn${RSQ}s answer ${EM} nothing local changes it`;
  const q = c.decisions.filter(d => d.status === "queued").length;
  // said as one clause, not two: "nothing local changes it" and "1 queued decision"
  // read as a contradiction when they sit in separate sentences
  const watch = q ? ` <span class="watch">${q} unreviewed decision${q>1?"s":""} in the queue would change this answer.</span>` : "";
  return `${who} ${size}. ${ours}.${watch}`;
}

/* ------------------------------------------------------------------- rendering */
function bar(c) {
  const kept = c.vendor - c.removed, total = Math.max(c.vendor + c.added, 1);
  const keep = 100*kept/total, cut = 100*c.removed/total, plus = 100*c.added/total;
  const fill = 100*total/GMAX;      // shared scale: full width is the biggest closure
  return `<div class="bar"><span class="t">${c.vendor.toLocaleString()} ${ARR} <b>${c.ours.toLocaleString()}</b></span>
    <span class="track" title="${kept} of FoodOn${RSQ}s ${c.vendor} kept, ${c.removed} suppressed, ${c.added} added ${EM} ${Math.round(fill)}% of the largest closure here">
      <span class="fill" style="width:${fill}%">
        <i class="keep" style="left:0;width:${keep}%"></i>
        <i class="cut" style="left:${keep}%;width:${cut}%"></i>
        <i class="add" style="left:${keep+cut}%;width:${plus}%"></i></span></span></div>`;
}

function decHTML(d, card) {
  const acts = [];
  if (d.status === "queued") acts.push(
    `<button class="btn go" data-act="signoff" data-kind="${d.kind}" data-id="${esc(d.id)}">Sign off</button>`,
    `<button class="btn" data-act="decline" data-kind="${d.kind}" data-id="${esc(d.id)}">Decline</button>`);
  else if (d.kind === "override") acts.push(
    `<button class="btn" data-act="edit_override" data-id="${d.id}">Edit text</button>`,
    d.etype === "superseded" ? "" :
    `<button class="btn" data-act="retire" data-id="${d.id}">Retire</button>`);
  return `<div class="dec" data-row>
    <div><span class="claim ${CC[d.claim]||""}">${esc(d.claim)}</span></div>
    <div><b>${esc(d.tgt_label || EM)}</b>${d.src_label ? ` ${ARR} ${esc(d.src_label)}` : ""}
      <div class="ids">${d.tgt_curie ? "<b>"+esc(d.tgt_curie)+"</b>" :
        '<span class="none">no FoodOn class for this term</span>'}${
        d.src_curie ? ` ${ARR} <b>${esc(d.src_curie)}</b>` : ""}</div>
      <div class="sample">${trim(d.why, 200)}</div>
      <div data-form></div></div>
    <div class="ids">${esc(d.file)}<br>${esc(d.by || EM)}${d.conf ? "<br>"+esc(d.conf) : ""}</div>
    <div><span class="st st-${d.status}">${esc(d.status)}</span>${
      d.impact != null ? `<div class="ids">+${d.impact} classes</div>` : ""}
      <div class="rowacts">${acts.join("")}</div></div>
  </div>`;
}

function card(c) {
  const touched = c.added || c.removed;
  const delta = touched
    ? `${c.added?`<span class="plus">+${c.added}</span>`:""}${c.added&&c.removed?" / ":""}${c.removed?`<span class="minus">−${c.removed}</span>`:""}`
    : `<span class="flat">unchanged</span>`;
  const q = c.decisions.filter(d => d.status === "queued").length;
  return `<details class="card${touched?"":" quiet"}" data-card="${esc(c.name)}">
    <summary>
      <div><span class="nm">${esc(c.name)}</span>
        <div class="al">${esc(c.aliases.filter(a=>a!==c.name).join(", ") || " ")}</div>
        <div class="ids">${esc(c.root_curies.filter(Boolean).join("  "))}</div></div>
      ${bar(c)}
      <div class="delta">${delta}${q?`  <span class="st st-queued">${q} queued</span>`:""}</div>
    </summary>
    <div class="body">
      <div class="purpose">${purpose(c)}</div>
      <p><b>Resolves to</b> ${esc(c.roots.join(", "))}. ${trim(c.rationale, 320)}</p>
      ${c.note ? `<p><b>Note</b> ${trim(c.note, 300)}</p>` : ""}
      ${c.removed ? `<p><b>Suppressed ${c.removed}</b> ${EM} e.g. ${esc(c.removed_sample.join(", "))}</p>` : ""}
      ${c.added ? `<p><b>Added ${c.added}</b> ${EM} e.g. ${esc(c.added_sample.join(", "))}</p>` : ""}
      ${c.decisions.length ? c.decisions.map(d => decHTML(d, c)).join("")
        : `<p>No local decision touches this ingredient ${EM} the answer is FoodOn${RSQ}s, unedited.</p>`}
      <div class="acts">
        <button class="btn go" data-act="statement">State a relationship</button>
        <button class="btn" data-act="add_override" data-roots="${esc(JSON.stringify(c.root_iris))}"
                data-name="${esc(c.name)}">Add a claim for ${esc(c.name)}</button>
        ${c.pin ? `<button class="btn" data-act="edit_pin" data-query="${esc(c.name)}">Edit the pin</button>` : ""}
      </div>
      <div data-cardform></div>
    </div></details>`;
}

/* ----------------------------------------------------------------------- forms */
const FIELD = {
  signoff: (d) => [["rationale", "textarea", "Why this is right. It is recorded as the evidence for the bridge.", true]],
  decline: (d) => [["rationale", "textarea", "Why not. Kept so the reasoning survives the rejection.", true]],
  edit_override: () => [
    ["claim", "select", "claim type", false, Object.keys(DATA.claim_types || {})],
    ["reason", "textarea", "reason", false],
    ["confidence", "select", "confidence", false, ["high","medium","low"]],
    ["review_note", "textarea", "review note", false]],
  add_override: () => [
    ["target_class", "text", "target class IRI — the thing to report or avoid", true],
    ["claim", "select", "claim type", true, Object.keys(DATA.claim_types || {})],
    ["reason", "textarea", "reason", true],
    ["confidence", "select", "confidence", false, ["high","medium","low"]],
    ["source", "text", "evidence or source", false]],
  edit_pin: () => [
    ["rationale", "textarea", "rationale", false],
    ["note", "textarea", "note", false],
    ["confidence", "select", "confidence", false, ["high","medium","low"]]],
};
function formHTML(act, prefill) {
  const rows = FIELD[act]().map(([k, type, label, req, opts]) => {
    const v = esc((prefill || {})[k] ?? "");
    const input = type === "textarea" ? `<textarea name="${k}"${req?" required":""}>${v}</textarea>`
      : type === "select" ? `<select name="${k}">${(opts||[]).map(o =>
          `<option${o===(prefill||{})[k]?" selected":""}>${esc(o)}</option>`).join("")}</select>`
      : `<input name="${k}" value="${v}"${req?" required":""}>`;
    return `<label>${esc(label)}${req?" *":""}${input}</label>`;
  }).join("");
  return `<form class="ed">${rows}<div class="msg" data-msg></div>
    <div class="acts"><button class="btn go" type="submit">Save</button>
      <button class="btn" type="button" data-cancel>Cancel</button></div></form>`;
}

async function send(action, payload, msgEl) {
  if (BUSY) return;
  BUSY = true;
  banner("ok", "saving and regenerating…");
  try {
    const r = await fetch("/api/audit/edit", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({action, payload})});
    const j = await r.json();
    if (!r.ok) {
      if (msgEl) msgEl.textContent = j.error || "failed";
      banner("err", j.error || "edit failed");
      return false;
    }
    DATA = Object.assign(DATA, j.audit);
    render();
    banner("stale", `saved to ${j.files.join(", ")}. The graph is reloaded; the SPARQL build is now behind.`);
    return true;
  } finally { BUSY = false; }
}

function banner(kind, text, withRebuild) {
  const b = $("#banner");
  b.innerHTML = `<div class="bnr ${kind}">${esc(text)}${
    withRebuild || kind === "stale"
      ? '<button class="btn" id="rebuild">Rebuild SPARQL graph (~19s)</button>' : ""}</div>`;
  const rb = $("#rebuild");
  if (rb) rb.onclick = async () => {
    rb.disabled = true; rb.textContent = "merging…";
    const r = await fetch("/api/audit/rebuild", {method:"POST"});
    const j = await r.json();
    banner(j.ok ? "ok" : "err",
      j.ok ? "SPARQL graph rebuilt — the app and the exported .ttl agree again."
           : "rebuild failed; see the server log");
  };
}

/* --------------------------------------------------------------------- wire-up */
document.addEventListener("click", (ev) => {
  const b = ev.target.closest("button[data-act]");
  if (!b) return;
  ev.preventDefault();
  const act = b.dataset.act;
  const row = b.closest("[data-row]");
  const slot = row ? row.querySelector("[data-form]")
                   : b.closest(".body").querySelector("[data-cardform]");
  if (slot.dataset.open === act) { slot.innerHTML = ""; slot.dataset.open = ""; return; }
  if (act === "statement") {
    slot.innerHTML = statementForm({});
    slot.dataset.open = act;
    const f = slot.querySelector("form");
    f.querySelector("[data-cancel]").onclick = () => { slot.innerHTML=""; slot.dataset.open=""; };
    wireStatement(f);
    return;
  }
  if (act === "retire") {
    slot.innerHTML = `<form class="ed"><label>why it is being retired *
      <textarea name="reason" required></textarea></label>
      <p class="sample">The entry stays on the record as <code>superseded</code>. To
      repoint a relationship, retire it and state the new one \u2014 both halves survive,
      which is the only version an audit can check.</p>
      <div class="msg" data-msg></div>
      <div class="acts"><button class="btn go" type="submit">Retire</button>
        <button class="btn" type="button" data-cancel>Cancel</button></div></form>`;
    slot.dataset.open = act;
    const f = slot.querySelector("form");
    f.querySelector("[data-cancel]").onclick = () => { slot.innerHTML=""; slot.dataset.open=""; };
    f.onsubmit = async (e) => { e.preventDefault();
      await send("retire", {id: b.dataset.id, reason: f.reason.value},
                 f.querySelector("[data-msg]")); };
    return;
  }
  let prefill = {};
  if (act === "edit_override") {
    const d = allDecisions().find(x => x.kind === "override" && String(x.id) === b.dataset.id);
    prefill = {claim: d.claim, reason: d.why, confidence: d.conf};
  }
  if (act === "edit_pin") {
    const c = DATA.cards.find(x => x.name === b.dataset.query);
    prefill = {rationale: c.rationale, note: c.note, confidence: c.confidence};
  }
  slot.innerHTML = formHTML(act, prefill);
  slot.dataset.open = act;
  const form = slot.querySelector("form");
  form.querySelector("[data-cancel]").onclick = () => { slot.innerHTML = ""; slot.dataset.open = ""; };
  form.onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(form).entries());
    const msg = form.querySelector("[data-msg]");
    let payload;
    if (act === "signoff" || act === "decline")
      payload = {kind: b.dataset.kind, id: b.dataset.id, rationale: f.rationale};
    else if (act === "edit_override") payload = {id: b.dataset.id, fields: f};
    else if (act === "edit_pin")      payload = {query: b.dataset.query, fields: f};
    else if (act === "add_override")
      payload = {...f, query_roots: JSON.parse(b.dataset.roots), query_class: b.dataset.name};
    await send(act === "decline" ? "decline" : act, payload, msg);
  };
});


/* ------------------------------------------------------- the statement editor
 * The first edit form offered `reason`, `confidence` and `review_note`: prose about a
 * relationship, with no way to state the relationship. This is the missing vocabulary.
 * A reviewer says SUBJECT - PREDICATE - OBJECT and the predicate decides which of the
 * six decision files it lands in, so nobody has to know that a `derives from` is claim
 * `contains` in overrides.json while an `in taxon` is a signed entry in
 * taxon-bridges.json.
 *
 * The preview is the part that makes a relationship editable rather than merely
 * writable: it says which ingredients change and by how much BEFORE anything is saved.
 * It caught my own mistyped IRI while this was being built -- `fermented beverage` in
 * place of `pasta food product`, which read as "gluten gains Barbera wine". */
let VOCAB = null;

function picker(name, value, label) {
  return `<label>${esc(label)}
    <input class="pick" name="${name}" autocomplete="off" placeholder="type a class name…"
           value="${esc(value||"")}" data-iri="">
    <div class="hits" hidden></div></label>`;
}

function statementForm(prefill) {
  const p = prefill || {};
  const opts = Object.entries(VOCAB.predicates).map(([k, v]) =>
    `<option value="${esc(k)}"${k===p.predicate?" selected":""}>${esc(v.label)}${
      v.enters ? "" : "  (reported, not traversed)"}</option>`).join("");
  return `<form class="ed stmt">
    ${picker("subject", p.subject_label, "subject")}
    <label>relationship<select name="predicate">${opts}</select>
      <div class="phelp"></div></label>
    ${picker("object", p.object_label, "object")}
    <div class="two">
      <label>confidence<select name="confidence">
        ${["high","medium","low"].map(c=>`<option${c===(p.confidence||"medium")?" selected":""}>${c}</option>`).join("")}
      </select></label>
      <label>evidence or source<input name="source" value="${esc(p.source||"")}"></label>
    </div>
    <label>why this is right *<textarea name="reason" required>${esc(p.reason||"")}</textarea></label>
    <div class="prev" data-prev>Fill both ends to see what this changes.</div>
    <div class="msg" data-msg></div>
    <div class="acts"><button class="btn go" type="submit">Save statement</button>
      <button class="btn" type="button" data-cancel>Cancel</button></div></form>`;
}

function wireStatement(form, onSave) {
  const help = form.querySelector(".phelp");
  const sel = form.predicate;
  const showHelp = () => {
    const v = VOCAB.predicates[sel.value];
    help.innerHTML = `<b>${esc(v.subject)}</b> ${ARR} <b>${esc(v.object)}</b> &middot; ${esc(v.obo)}
      <div>${esc(v.help)}</div>`;
  };
  sel.onchange = () => { showHelp(); doPreview(); };
  showHelp();

  form.querySelectorAll(".pick").forEach(inp => {
    const box = inp.parentElement.querySelector(".hits");
    let timer;
    inp.oninput = () => {
      inp.dataset.iri = "";
      clearTimeout(timer);
      timer = setTimeout(async () => {
        if (inp.value.trim().length < 2) { box.hidden = true; return; }
        const r = await fetch("/api/audit/lookup?q=" + encodeURIComponent(inp.value));
        const {hits} = await r.json();
        box.innerHTML = hits.map(h =>
          `<button type="button" class="hit" data-iri="${esc(h.iri)}" data-label="${esc(h.label)}">
             <b>${esc(h.label)}</b> <span class="ids">${esc(h.curie)}</span>
             <span class="cnt">${h.closure} in closure</span>
             ${h.excluded ? '<span class="warn">excluded branch</span>' : ""}
             <span class="how">${esc(h.how)}</span></button>`).join("")
          || '<div class="hit none">no class matches</div>';
        box.hidden = false;
      }, 160);
    };
    box.onclick = (e) => {
      const b = e.target.closest(".hit[data-iri]");
      if (!b) return;
      inp.value = b.dataset.label; inp.dataset.iri = b.dataset.iri;
      box.hidden = true; doPreview();
    };
  });

  const prev = form.querySelector("[data-prev]");
  async function doPreview() {
    const s = form.subject.dataset.iri, o = form.object.dataset.iri;
    if (!s || !o) { prev.className = "prev"; prev.textContent =
      "Pick both ends from the list to see what this changes."; return; }
    prev.className = "prev busy"; prev.textContent = "checking\u2026";
    const r = await fetch("/api/audit/preview", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({predicate: form.predicate.value, subject: s, object: o})});
    const j = await r.json();
    if (!r.ok) { prev.className = "prev bad"; prev.textContent = j.error; return; }
    if (j.changes && j.changes.length) {
      prev.className = "prev hit";
      prev.innerHTML = "<b>This would change:</b>" + j.changes.map(c =>
        `<div>${esc(c.ingredient)} <b>${c.gained?"+"+c.gained:"\u2212"+c.lost}</b>
         <span class="ids">${esc(c.sample.slice(0,3).join(", "))}</span></div>`).join("");
    } else {
      prev.className = "prev";
      prev.textContent = j.note || "No pinned ingredient changes.";
    }
  }
  form.oninput = (e) => { if (e.target.name === "reason") return; };
  form.onsubmit = async (e) => {
    e.preventDefault();
    const msg = form.querySelector("[data-msg]");
    const s = form.subject.dataset.iri, o = form.object.dataset.iri;
    if (!s || !o) { msg.textContent = "pick both ends from the suggestion list"; return; }
    await send("statement", {predicate: form.predicate.value, subject: s, object: o,
      reason: form.reason.value, confidence: form.confidence.value,
      source: form.source.value}, msg);
  };
}

const allDecisions = () => DATA.cards.flatMap(c => c.decisions).concat(DATA.rest);

function render() {
  GMAX = Math.max(...DATA.cards.map(c => c.vendor + c.added), 1);
  const big = DATA.cards.reduce((a,c) => (c.vendor+c.added) > (a.vendor+a.added) ? c : a);
  const touched = DATA.cards.filter(c => c.added || c.removed);
  const clean = DATA.cards.filter(c => !(c.added || c.removed));
  const addT = DATA.cards.reduce((s,c) => s+c.added, 0);
  const remT = DATA.cards.reduce((s,c) => s+c.removed, 0);
  const queued = allDecisions().filter(d => d.status === "queued").length;
  $("#sub").textContent = `${DATA.cards.length} ingredients against FoodOn ${DATA.ontology}`
    + ` · adds ${addT}, suppresses ${remT} · ${queued} awaiting review`;
  $("#key").innerHTML =
    `<span><i style="background:var(--n-derivative)"></i>FoodOn${RSQ}s answer, kept</span>
     <span><i style="background:#d8a29a"></i>suppressed by a signed decision</span>
     <span><i style="background:#8fabc9"></i>added by a repair, bridge or override</span>
     <span>bars share one scale ${EM} full width is ${GMAX.toLocaleString()} classes (${esc(big.name)})</span>`;
  $("#out").innerHTML =
    `<h2 class="sec">Our layer changes the answer ${EM} ${touched.length}</h2>` + touched.map(card).join("") +
    `<h2 class="sec">Vendor answer, unedited ${EM} ${clean.length}, nothing to audit</h2>` + clean.map(card).join("") +
    `<h2 class="sec">Not tied to one ingredient ${EM} ${DATA.rest.length}</h2>
     <p class="why">Mostly label-convention repairs: edges between a food product and its own
     plant, which belong to whichever query passes through them. Filter rather than browse.</p>
     <input class="f" id="f" placeholder="filter ${EM} try tahini, oat, pepper">
     <table class="rest"><thead><tr><th>claim</th><th>decision</th><th>source</th><th>status</th></tr></thead>
     <tbody id="rb"></tbody></table>`;
  const f = $("#f"), rb = $("#rb");
  const draw = () => {
    const q = (f.value||"").toLowerCase();
    const rows = DATA.rest.filter(r => !q ||
      ((r.tgt_label||"")+(r.src_label||"")).toLowerCase().includes(q));
    rb.innerHTML = rows.slice(0,60).map(r =>
      `<tr><td><span class="claim ${CC[r.claim]||""}">${esc(r.claim)}</span></td>
        <td><b>${esc(r.tgt_label||EM)}</b>${r.src_label?` ${ARR} ${esc(r.src_label)}`:""}
          <div class="ids">${r.tgt_curie?esc(r.tgt_curie):"<i>no FoodOn class</i>"}${
            r.src_curie?` ${ARR} ${esc(r.src_curie)}`:""}</div></td>
        <td class="ids">${esc(r.file)}</td>
        <td><span class="st st-${r.status}">${esc(r.status)}</span></td></tr>`).join("")
      || `<tr><td colspan="4" style="padding:11px 12px;color:var(--muted)">no match</td></tr>`;
    if (rows.length > 60) rb.insertAdjacentHTML("beforeend",
      `<tr><td colspan="4" style="padding:9px 12px;color:var(--muted)">${rows.length-60} more — narrow the filter</td></tr>`);
  };
  f.oninput = draw; draw();
  if (DATA.sparql_stale) banner("stale",
    "A decision has changed since the SPARQL graph was built. The app is current; exported queries are not.");
}



/* ====================================================================== *
 * Ingredient mappings: batch review
 *
 * 500 terms is too many to decide one at a time and too few to accept blind. The
 * queue is ordered by USE because the vocabulary is steeply headed -- the top 20
 * terms carry about a third of it -- so working top-down buys the most coverage per
 * decision. Select, then approve or decline the selection.
 *
 * `Select all shown` is scoped to the current filter on purpose. A button that
 * selected all 500 regardless of what was on screen would make it trivial to approve
 * the 30 risky ones and the 75 with no candidate along with the easy 273.
 * ====================================================================== */
let ING = null, SEL = new Set(), FILTER = "oneclick", SHOW = 25;
const CHOICE = {};             // term -> the FoodOn iri the reviewer picked
const LAYER_INTRO = document.querySelector(".why").outerHTML;

const FILTERS = {
  signed:    {label: "signed \u2014 correct one", fn: e => !!e.signed_off_by},
  oneclick:  {label: "one click",          fn: e => (e.shortlist||[]).length === 1},
  choose:    {label: "needs a choice",     fn: e => (e.shortlist||[]).length > 1},
  nocand:    {label: "no class in FoodOn", fn: e => !(e.shortlist||[]).length && !e.declined_reason},
  declined:  {label: "proposed decline", fn: e => !!e.declined_reason},
  all:       {label: "everything",       fn: () => true},
};

// signed mappings are reviewable too: one signed in good faith and later found coarse
// has to be fixable here rather than by hand-editing the file this interface replaces
const pool = () => (FILTER === "signed" ? (ING.signed || []) : (ING.queue || []))
  .filter(FILTERS[FILTER].fn);
const shown = () => pool().slice(0, SHOW);

/* The final call is a human picking a CLASS, not approving a string. The model's
 * narrowing leads the list as the recommendation; the alternatives sit under it so the
 * reviewer can overrule without leaving the page. Every row carries the id and the
 * closure size, which is the number that decides whether a class is the right grain --
 * FoodOn's own `tree nut` reaches 2 classes and looks perfect. */
function ingRow(e) {
  const sl = e.shortlist || [];
  const chosen = CHOICE[e.term] ?? e.maps_to_iri ?? (sl.length ? sl[0].iri : null);
  const risky = (e.candidates || []).filter(
    c => c.risky && (!e.proposed || c.term === e.proposed));
  const opts = sl.map((c, i) => `
    <label class="opt${chosen === c.iri ? " on" : ""}">
      <input type="radio" name="pick-${esc(e.term)}" value="${esc(c.iri)}"
             ${chosen === c.iri ? "checked" : ""} data-pick="${esc(e.term)}">
      <span class="olab">${esc(c.label)}</span>
      <span class="ids">${esc(c.curie)}</span>
      <span class="cnt">${c.closure} in closure</span>
      ${c.recommended ? '<span class="rec">recommended</span>' : ""}
      ${c.excluded ? '<span class="riskflag">excluded branch</span>' : ""}
      <span class="how">${esc(c.why)}</span>
    </label>`).join("");
  return `<tr class="${SEL.has(e.term) ? "sel" : ""}" data-term="${esc(e.term)}">
    <td><input type="checkbox" data-cb ${SEL.has(e.term) ? "checked" : ""}></td>
    <td><span class="term">${esc(e.term)}</span>
      ${risky.length ? `<span class="riskflag">${esc(risky[0].warning)}</span>` : ""}</td>
    <td class="uses">${(e.uses || 0).toLocaleString()}</td>
    <td>${e.signed_off_by ? `<div class="ids" style="margin-bottom:4px">now: <b>${
        esc(e.maps_to || "?")}</b>${e.corrected_from ? ` (was ${esc(e.corrected_from)})` : ""}</div>` : ""}
      ${sl.length ? `<div class="opts">${opts}</div>`
      : e.declined_reason
        ? `<span class="noprop">not an ingredient</span><div class="ids">${esc(e.declined_reason)}</div>`
        : `<span class="noprop">${esc(e.proposed_note || "FoodOn has no class for this")}</span>`}</td>
  </tr>`;
}

function renderIngredients() {
  const q = ING.queue || [];
  const list = shown();
  const inPool = pool();
  $("#sub").textContent =
    `${ING.queued_total.toLocaleString()} terms awaiting review · `
    + `${ING.queued_uses.toLocaleString()} ingredient uses · `
    + `${ING.signed.length} signed`;
  $("#key").innerHTML = "";
  $(".why").remove();          // the patch-layer intro belongs to the other view
  $("#out").innerHTML = `
    ${ING.signed.length ? `<div class="done">${ING.signed.length} mapping${
      ING.signed.length>1?"s":""} signed off and live in build/ingest.py — 
      ${ING.signed.reduce((s,m)=>s+(m.uses||0),0).toLocaleString()} ingredient uses.</div>` : ""}
    <p class="why"><b>${ING.deterministic_share}%</b> of
      ${(ING.corpus_lines||0).toLocaleString()} ingredient uses in
      <code>${esc(ING.corpus||"the corpus")}</code> already resolve without any of this.
      These are what is left: ${ING.proposed} carry a proposal, ${ING.declined_proposals}
      are proposed as not-an-ingredient, ${ING.abstained} abstained because FoodOn has
      nothing. <b>A proposal is not a decision</b> — nothing here affects ingestion
      until it is signed.</p>
    <div class="batchbar">
      <div class="filters2">${Object.entries(FILTERS).map(([k,v]) =>
        `<button data-filter="${k}" aria-pressed="${k===FILTER}">${esc(v.label)} (${
          (k === "signed" ? (ING.signed||[]) : q).filter(v.fn).length})</button>`).join("")}</div>
      <span class="spacer"></span>
      <span class="count">showing <b>${list.length}</b> of ${inPool.length}
        · <b>${SEL.size}</b> selected</span>
      <button class="btn" data-all>Select all shown</button>
      <button class="btn" data-none>Clear</button>
      <button class="btn go" data-approve ${SEL.size?"":"disabled"}>Approve ${SEL.size||""}</button>
      <button class="btn" data-declineb ${SEL.size?"":"disabled"}>Decline ${SEL.size||""}</button>
    </div>
    <table class="ing"><thead><tr>
      <th style="width:26px"></th><th>recipe term</th><th class="uses">uses</th>
      <th>maps to</th></tr></thead>
      <tbody>${list.map(ingRow).join("") ||
        '<tr><td colspan="4" style="padding:12px;color:var(--muted)">nothing matches this filter</td></tr>'}</tbody>
    </table>
    ${pool.length > SHOW ? `<div class="acts"><button class="btn" data-more>Show ${
      Math.min(25, pool.length-SHOW)} more — ${pool.length-SHOW} left</button></div>` : ""}`;
}

async function reviewBatch(action) {
  const terms = [...SEL];
  if (!terms.length) return;
  banner("ok", `${action === "approve" ? "signing off" : "declining"} ${terms.length}…`);
  const choices = {};
  for (const t of terms) {
    const e = (ING.queue || []).find(x => x.term === t)
           || (ING.signed || []).find(x => x.term === t);
    const sl = (e && e.shortlist) || [];
    const iri = CHOICE[t] ?? (sl.length ? sl[0].iri : null);
    if (iri) choices[t] = iri;
  }
  const r = await fetch("/api/audit/ingredients/review", {method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({terms, action, choices})});
  const j = await r.json();
  if (!r.ok) { banner("err", j.error || "review failed"); return; }
  ING = j.ingredients; SEL.clear(); renderIngredients();
  const skipped = (j.skipped || []).length;
  banner(skipped ? "stale" : "ok",
    `${j.done.length} ${action === "approve" ? "signed off" : "declined"}`
    + (skipped ? ` · ${skipped} skipped: ${j.skipped.map(s => s[0]+" ("+s[1]+")").join("; ")}` : "")
    + (action === "approve" ? " — live in build/ingest.py now" : ""));
}

document.addEventListener("click", async (ev) => {
  const t = ev.target;
  if (t.closest("#tabs button")) {
    const b = t.closest("button");
    [...$("#tabs").children].forEach(c => c.setAttribute("aria-pressed", c === b));
    $("#hd").firstChild.textContent = b.dataset.view === "ingredients"
      ? "Ingredient mappings " : "Patch layer audit ";
    if (b.dataset.view === "ingredients") {
      if (!ING) ING = await (await fetch("/api/audit/ingredients")).json();
      renderIngredients();
    } else {
      if (!$(".why")) $("#out").insertAdjacentHTML("beforebegin", LAYER_INTRO);
      render();
    }
    return;
  }
  if (!ING || !$("#tabs button[data-view=ingredients][aria-pressed=true]")) return;
  if (t.closest("[data-filter]")) {
    FILTER = t.closest("[data-filter]").dataset.filter; SHOW = 25; SEL.clear();
    renderIngredients(); return;
  }
  if (t.closest("[data-more]"))  { SHOW += 25; renderIngredients(); return; }
  if (t.closest("[data-all]"))   { shown().forEach(e => SEL.add(e.term)); renderIngredients(); return; }
  if (t.closest("[data-none]"))  { SEL.clear(); renderIngredients(); return; }
  if (t.closest("[data-approve]"))  { await reviewBatch("approve"); return; }
  if (t.closest("[data-declineb]")) { await reviewBatch("decline"); return; }
  if (t.closest("[data-pick]")) {
    const inp = t.closest("label").querySelector("[data-pick]");
    CHOICE[inp.dataset.pick] = inp.value;
    SEL.add(inp.dataset.pick);      // choosing a class is intent; select the row too
    renderIngredients();
    return;
  }
  const row = t.closest("tr[data-term]");
  if (row) {
    const term = row.dataset.term;
    SEL.has(term) ? SEL.delete(term) : SEL.add(term);
    renderIngredients();
  }
});

fetch("/api/audit").then(r => r.json()).then(async (d) => {
  DATA = d;
  VOCAB = await (await fetch("/api/audit/vocabulary")).json();
  const h = await (await fetch("/api/health")).json().catch(() => ({}));
  DATA.claim_types = h.claim_types || {contains:1, may_contain:1, shared_compound:1,
                                       cross_reactive:1, disputed:1, not_avoidance_relevant:1};
  render();
});
