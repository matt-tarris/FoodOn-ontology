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
    `<button class="btn" data-act="edit_override" data-id="${d.id}">Edit</button>`);
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

fetch("/api/audit").then(r => r.json()).then(async (d) => {
  DATA = d;
  const h = await (await fetch("/api/health")).json().catch(() => ({}));
  DATA.claim_types = h.claim_types || {contains:1, may_contain:1, shared_compound:1,
                                       cross_reactive:1, disputed:1, not_avoidance_relevant:1};
  render();
});
