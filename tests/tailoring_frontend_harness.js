// Execute the real scripts without a browser, network, persistence or personal data.
if (typeof print === "undefined") globalThis.print = console.log;
function assert(value, message) { if (!value) throw new Error(message); }
function same(actual, expected, message) { assert(JSON.stringify(actual) === JSON.stringify(expected), message); }
const copy = value => JSON.parse(JSON.stringify(value));
class Element {
  constructor(tag = "div") { this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = {}; this.value = ""; this.hidden = false; this.disabled = false; this._text = ""; }
  set value(value) { this._value = this.tagName === "input" ? String(value).replace(/[\r\n]/g, "") : this.tagName === "textarea" ? String(value).replace(/\r\n?/g, "\n") : value; }
  get value() { return this._value; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(" "); }
  set innerHTML(value) { throw new Error("Unsafe HTML assignment"); }
  append(...children) { children.forEach(child => { if (child.parent) child.remove(); child.parent = this; child.parentElement = this; this.children.push(child); }); }
  replaceChildren(...children) { this.children = []; this._text = ""; this.append(...children); }
  insertBefore(child, before) { child.parent = this; child.parentElement = this; this.children.splice(this.children.indexOf(before), 0, child); }
  remove() { this.parent.children = this.parent.children.filter(child => child !== this); this.parent = null; this.parentElement = null; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  click() { for (const callback of this.listeners.click || []) callback({ preventDefault() {} }); }
  addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
  querySelectorAll(selector) { return all(this).slice(1).filter(child => matches(child, selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  focus() { this.focused = true; document.activeElement = this; }
  scrollIntoView(options) { this.scrollRequest = options; }
}
const all = root => [root, ...root.children.flatMap(all)];
function matches(item, selector) {
  if (selector.startsWith(".")) return item.className?.split(" ").includes(selector.slice(1));
  if (selector.startsWith("#")) return item.id === selector.slice(1);
  const attribute = selector.match(/^\[data-([\w-]+)(?:="([^"]*)")?\]$/);
  if (attribute) {
    const key = attribute[1].replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    return key in item.dataset && (attribute[2] === undefined || item.dataset[key] === attribute[2]);
  }
  return item.tagName === selector;
}
const nodes = Object.fromEntries(htmlIds.map(id => [`#${id}`, new Element()]));
nodes["#tailoring-preview"].hidden = true;
nodes["#tailoring-output"].hidden = true;
nodes["#analysis-result"].hidden = true;
nodes["#generate-tailored-preview"].disabled = true;
globalThis.document = {
  createElement: tag => new Element(tag),
  querySelector: selector => nodes[selector] || Object.values(nodes).flatMap(all).find(item =>
    selector === `#${item.id}` || selector === `[data-cv-focus="${item.dataset.cvFocus}"]`),
  querySelectorAll: selector => [...new Set(Object.values(nodes).flatMap(all))].filter(item => matches(item, selector)),
};
globalThis.CustomEvent = class { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } };
globalThis.window = new Element();
window.dispatchEvent = event => { for (const callback of window.listeners[event.type] || []) callback(event); };
let confirmations = 0;
let discard = true;
window.confirm = () => { confirmations += 1; return discard; };
globalThis.queueMicrotask ||= callback => Promise.resolve().then(callback);
globalThis.localStorage = { setItem() { throw new Error("Preview must not persist locally"); } };
globalThis.sessionStorage = globalThis.localStorage;
const requests = [];
const plans = {};
let analysisJSON = copy(fixtureAnalysis);
let previewJSON = copy(fixturePreview);
let allowCVSave = false;
let allowBankSave = false;
const editorBank = { schema_version: 1, skills: ["Unrelated editor skill"], work_experience: [], projects: [], education: [], certifications: [], additional_evidence: [] };
const savedCV = { schema_version: 1, work_experience: [], projects: [], skill_groups: [{ name: "Original group", skill_keys: ["unrelated editor skill"] }], tailoring_settings: { max_achievements_per_role: null, max_projects: null, max_contributions_per_project: null, max_skills: null } };
const reply = (status, data) => ({ ok: status < 400, json: async () => copy(data) });
const enqueue = (url, value) => (plans[url] ||= []).push(value);
function deferred() {
  const result = {};
  result.promise = new Promise((resolve, reject) => { result.resolve = resolve; result.reject = reject; });
  return result;
}
globalThis.fetch = async (url, options = {}) => {
  const method = options.method || "GET";
  const body = options.body ? JSON.parse(options.body) : null;
  requests.push({ url, method, body });
  assert((method !== "PUT" || (allowCVSave && url === "/current-cv") || (allowBankSave && url === "/experience-bank")) && method !== "PATCH" && method !== "DELETE", "No unintended frontend writes");
  const plan = plans[url]?.shift();
  if (plan) return plan;
  if (url === "/experience-bank" && method === "GET") return reply(200, editorBank);
  if (url === "/experience-bank" && method === "PUT") {
    const saved = copy(body);
    let counter = 0;
    for (const field of ["work_experience", "projects", "education", "certifications", "additional_evidence"]) {
      for (const record of saved[field]) {
        record.id ||= `new-${field}-${++counter}`;
        for (const child of record.achievements || record.evidence || []) child.id ||= `new-evidence-${++counter}`;
      }
    }
    Object.assign(editorBank, saved);
    return reply(200, saved);
  }
  if (url === "/current-cv" && method === "GET") return reply(200, { current_cv: savedCV, reference_issues: [] });
  if (url === "/analyse") return reply(200, analysisJSON);
  if (url === "/match") return reply(200, previewJSON.matching_result);
  if (url === "/tailoring/preview") return reply(200, previewJSON);
  throw new Error(`Unexpected endpoint ${url}`);
};
const settle = async () => { for (let i = 0; i < 35; i++) await Promise.resolve(); };
async function fire(target, type) {
  const event = { preventDefault() {} };
  // Browser propagation uses the original path even when a handler removes a row.
  const path = [target];
  if (scenario.startsWith("management_") && ["input", "click"].includes(type)) {
    for (let parent = target.parentElement; parent; parent = parent.parentElement) path.push(parent);
  }
  for (const element of path) for (const callback of element.listeners[type] || []) await callback(event);
}
const action = () => fire(nodes["#generate-tailored-preview"], "click");
const click = id => fire(nodes[`#${id}`], "click");
const countRequests = url => requests.filter(item => item.url === url).length;
async function edit(value) { nodes["#job-description"].value = value; await fire(nodes["#job-description"], "input"); }
async function analyse(value = fixtureDescription) { await edit(value); await fire(nodes["#match-form"], "submit"); }
const content = () => nodes["#tailored-cv-content"];
const changes = () => nodes["#tailoring-decisions"];
const coverage = () => nodes["#tailoring-coverage"];
const previewButton = () => nodes["#generate-tailored-preview"];
const findBy = (root, field, value) => all(root).find(item => item.dataset[field] === value);
const source = fixturePreview.source_bank;
const originalPreview = JSON.stringify(fixturePreview);
if (scenario.startsWith("management_")) {
  Object.assign(editorBank, copy(source));
  editorBank.education[0].qualification = " BSc | Applied Computing ";
  editorBank.certifications[0].skills = ["AWS (EC2, S3)", "Testing"];
  editorBank.work_experience[0].achievements[0].text = "  Exact achievement.\r\nKeep these spaces.  ";
  editorBank.work_experience[0].achievements[0].outcomes = ["Outcome\r\nwith original lines"];
  editorBank.work_experience[0].achievements[0].skills = ["AWS (EC2, S3)"];
  if (scenario === "management_additional") editorBank.additional_evidence = [{ id: "note", text: "Original additional evidence.", skills: ["Mentoring"], technologies: [], outcomes: ["Recorded outcome"] }];
  if (scenario === "management_metadata_edges") {
    editorBank.education[0].qualification = "Degree\r\n(placement)";
    editorBank.education[0].institution = " ";
    editorBank.certifications[0].issuer = "😀".repeat(200);
    editorBank.certifications[0].skills = ["Cloud\nplatforms", "AWS (EC2, S3)"];
    editorBank.certifications[0].year = "";
    editorBank.projects[0].link = "";
  }
  for (const id of ["work-list", "project-list", "skills", "education", "certifications", "additional-evidence-editor"]) nodes["#bank-form"].append(nodes[`#${id}`]);
  Object.assign(savedCV, { work_experience: [{ work_experience_id: "role-a", achievement_ids: ["testing", "oracle"] }], projects: [{ project_id: "jobmatch", contribution_ids: ["api"] }], skill_groups: [{ name: "Languages", skill_keys: ["python"] }] });
  if (scenario === "management_load_failure") enqueue("/experience-bank", reply(503, { detail: "Fictional load failure." }));
}

// INSERT APPLICATION HERE

async function run() {
  await settle();
  assert(previewButton().disabled && nodes["#tailoring-preview"].hidden, "Preview unavailable without a successful analysis");
  if (scenario.startsWith("management_")) { await managementScenario(); return; }
  if (scenario.startsWith("workspace_")) { await workspaceScenario(); return; }
  if (scenario.startsWith("results_")) { await resultsScenario(); return; }
  if (scenario.startsWith("tailor_")) { await tailorScenario(); return; }
  if (scenario === "initial") { await action(); assert(countRequests("/tailoring/preview") === 0, "No preview request before analysis"); return; }
  if (scenario === "analysis_error") {
    enqueue("/analyse", reply(502, { detail: "Analysis unavailable." }));
    await analyse();
    assert(previewButton().disabled && nodes["#tailoring-preview"].hidden, "Failed analysis has no preview");
    assert(nodes["#form-error"].textContent === "Analysis unavailable.", "Existing error retained");
    return;
  }
  if (["edit_during_analyse", "analysis_duplicate", "stale_analysis_failure", "edit_back_to_original"].includes(scenario)) {
    const pending = deferred(); enqueue("/analyse", pending.promise);
    await edit(fixtureDescription);
    const task = fire(nodes["#match-form"], "submit"); await settle();
    if (["edit_during_analyse", "stale_analysis_failure", "edit_back_to_original"].includes(scenario)) await edit("A different job description with different requirements.");
    else await fire(nodes["#match-form"], "submit");
    if (scenario === "edit_back_to_original") await edit(fixtureDescription);
    pending.resolve(scenario === "stale_analysis_failure" ? reply(502, { detail: "Old provider failure." }) : reply(200, analysisJSON)); await task;
    assert(countRequests("/analyse") === 1, "No duplicate analysis");
    if (scenario !== "analysis_duplicate") {
      assert(countRequests("/match") === 0, "Stale extraction cannot start matching");
      assert(nodes["#tailoring-preview"].hidden && previewButton().disabled, "Stale analysis cannot enable preview");
      assert(nodes["#form-error"].hidden, "Outdated errors do not replace the current state");
    }
    return;
  }
  if (scenario === "edit_during_match") {
    const pending = deferred(); enqueue("/match", pending.promise);
    await edit(fixtureDescription);
    const task = fire(nodes["#match-form"], "submit"); await settle();
    await edit("A different job description while matching is in flight.");
    pending.resolve(reply(200, previewJSON.matching_result)); await task;
    assert(nodes["#tailoring-preview"].hidden && previewButton().disabled, "Old match cannot enable preview");
    assert(nodes["#diagnostics"].textContent === "", "Stale match cannot overwrite diagnostics");
    return;
  }
  if (scenario === "match_error_after_analysis") enqueue("/match", reply(503, { detail: "Matching unavailable." }));
  await analyse();
  assert(!previewButton().disabled && !nodes["#tailoring-preview"].hidden, "Successful analysis enables explicit action");
  assert(countRequests("/tailoring/preview") === 0, "Preview is never automatic");
  if (["loading_duplicate", "edit_during_preview"].includes(scenario)) {
    const pending = deferred(); enqueue("/tailoring/preview", pending.promise);
    const task = action(); await settle();
    assert(previewButton().disabled && nodes["#tailoring-preview"].attributes["aria-busy"] === "true", "Loading locks action");
    assert(nodes["#tailoring-state"].textContent.includes("Generating"), "Visible loading state");
    await action(); assert(countRequests("/tailoring/preview") === 1, "Duplicate submissions ignored");
    if (scenario === "edit_during_preview") await edit("A newer job description invalidates the pending preview.");
    pending.resolve(reply(200, previewJSON)); await task;
    if (scenario === "edit_during_preview") assert(nodes["#tailoring-preview"].hidden && nodes["#tailoring-output"].hidden, "Stale preview stays hidden");
    else assert(!previewButton().disabled && !nodes["#tailoring-output"].hidden, "Loading recovers on success");
    return;
  }
  if (["new_analysis_pending_preview", "old_preview_failure", "old_preview_finally"].includes(scenario)) {
    const old = deferred(); enqueue("/tailoring/preview", old.promise);
    const oldTask = action(); await settle();
    analysisJSON.job_title = "New target role";
    await analyse(fixtureDescription + "\nNew target description.");
    assert(nodes["#tailoring-output"].hidden, "New analysis clears old preview");
    previewJSON.source_bank.work_experience[0].summary = "New snapshot marker";
    if (scenario === "old_preview_finally") {
      const fresh = deferred(); enqueue("/tailoring/preview", fresh.promise);
      const freshTask = action(); await settle();
      old.resolve(reply(200, fixturePreview)); await oldTask;
      assert(previewButton().disabled, "Old finally cannot unlock a newer request");
      fresh.resolve(reply(200, previewJSON)); await freshTask;
    } else {
      await action();
      if (scenario === "old_preview_failure") old.reject(new Error("Old request failed."));
      else old.resolve(reply(200, fixturePreview));
      await oldTask;
    }
    assert(content().textContent.includes("New snapshot marker"), "Newest preview stays displayed");
    assert(nodes["#tailoring-target"].textContent === "For: New target role", "Latest target retained");
    assert(nodes["#tailoring-error"].hidden, "Stale errors ignored");
    return;
  }
  if (["api_error", "retry"].includes(scenario)) {
    enqueue("/tailoring/preview", reply(503, { detail: "The Current CV could not be loaded." }));
    await action();
    assert(!nodes["#tailoring-error"].hidden, "Error is visible");
    assert(nodes["#tailoring-error"].textContent === "The Current CV could not be loaded.", "Safe API message");
    assert(!previewButton().disabled && nodes["#tailoring-output"].hidden, "Retry remains available");
    assert(nodes["#diagnostics"].textContent.includes(fixtureAnalysis.job_title), "Existing analysis preserved");
    if (scenario === "api_error") return;
  }
  if (["empty", "missing_baseline"].includes(scenario)) {
    previewJSON.proposed_cv = { work_experience: [], projects: [], skill_groups: [] };
    previewJSON.source_bank = { skills: [], work_experience: [], projects: [], education: [], certifications: [], additional_evidence: [] };
    previewJSON.decisions = [];
  }
  if (scenario === "empty_requirements") { previewJSON.coverage = []; previewJSON.skill_coverage = []; }
  if (scenario === "limited_coverage") {
    previewJSON.coverage.find(item => item.requirement_id === "r2").selected_status = "not_selected";
    previewJSON.coverage.find(item => item.requirement_id === "r2").selected_evidence_ids = [];
  }
  if (scenario === "related_only") { previewJSON.matching_result.strong_matches = []; }
  if (scenario === "stale_refs") {
    previewJSON.warnings.push("baseline_reference_issues");
    previewJSON.reference_issues.push({ path: "work_experience[0]", reference: "stale-role", reason: "Saved role no longer exists." });
  }
  if (scenario === "missing_destinations") {
    previewJSON.proposed_cv.work_experience[0].achievement_ids.push("oracle"); // Wrong parent: never relocate.
    previewJSON.proposed_cv.work_experience.push({ work_experience_id: "gone", achievement_ids: [] });
    previewJSON.proposed_cv.skill_groups[0].skill_keys.push("inferred-missing-skill");
  }
  if (scenario === "unsupported_destination") previewJSON.decisions.push({ ...previewJSON.decisions[0], source_type: "additional_evidence", source_id: "other", selected: false, was_in_current_cv: false });
  if (scenario === "safe_text") {
    previewJSON.source_bank.work_experience[0].role = '<img src=x onerror="alert(1)">';
    previewJSON.source_bank.work_experience[0].achievements.find(item => item.id === "oracle").text = "  <script>alert('bullet')</script>\n& keep whitespace.  ";
    previewJSON.source_bank.projects[0].description = "<svg onload=alert(1)>";
    previewJSON.source_bank.projects[0].link = "javascript:alert(1)";
    previewJSON.source_bank.skills[0] = "<img src=x onerror=alert(1)>";
    previewJSON.decisions.find(item => item.source_type === "skill" && item.source_id === "python").original_text = previewJSON.source_bank.skills[0];
    previewJSON.source_bank.education[0].qualification = "<script>degree</script>";
    previewJSON.source_bank.certifications[0].name = "<script>certificate</script>";
    previewJSON.proposed_cv.skill_groups[0].name = "<b>Skill group</b>";
    previewJSON.reference_issues.push({ reference: "<img src=x>", reason: "<script>warning</script>" });
    previewJSON.decisions.find(item => item.source_id === "old").original_text = "<script>omitted text</script>";
  }
  const before = JSON.stringify(previewJSON);
  await action();
  assert(!nodes["#tailoring-output"].hidden, "Preview succeeded");
  switch (scenario) {
    case "explicit_request":
    case "match_error_after_analysis":
      same(requests.find(item => item.url === "/tailoring/preview").body, { job_analysis: fixtureAnalysis }, "Exact existing analysis sent");
      assert(countRequests("/analyse") === 1, "Preview does not reanalyse");
      break;
    case "exact_work":
      for (const role of source.work_experience) for (const original of role.achievements) {
        const rendered = findBy(content(), "tailoredBulletId", original.id);
        if (rendered) same(rendered.children[0].textContent, original.text, "Exact original work wording");
      }
      assert(content().textContent.includes(source.work_experience[0].summary), "Original summary preserved");
      assert(!content().textContent.includes("Helped with an internal database task."), "Omitted bullet not in CV");
      break;
    case "project_text":
      assert(content().textContent.includes(source.projects[0].description), "Project description preserved");
      same(findBy(content(), "tailoredBulletId", "api").children[0].textContent, source.projects[0].evidence[0].text, "Exact contribution wording");
      assert(!findBy(content(), "tailoredBulletId", "unselected"), "Only selected contributions");
      break;
    case "skills": {
      const section = findBy(content(), "tailoredSection", "skills");
      same(section.children.slice(1).map(item => item.children[0].textContent), fixturePreview.proposed_cv.skill_groups.map(item => item.name), "Exact skill group headings");
      same(findBy(content(), "tailoredSkillKey", "python").children[0].textContent, " Python\t", "Exact catalogue label");
      assert(!findBy(content(), "tailoredSkillKey", "aws"), "No inferred skill");
      break;
    }
    case "credentials":
      assert(content().textContent.includes("Example University") && content().textContent.includes("2024"), "Education fields rendered");
      assert(content().textContent.includes("Original certificate") && content().textContent.includes("Example issuer"), "Certification rendered");
      break;
    case "order":
      same(all(content()).filter(item => item.dataset.tailoredParentId).map(item => item.dataset.tailoredParentId), ["role-b", "role-a", "jobmatch"], "Returned role and project order");
      same(all(content()).filter(item => item.dataset.tailoredBulletId).map(item => item.dataset.tailoredBulletId), ["general", "testing", "oracle", "api"], "Returned bullet order");
      break;
    case "indicators":
      assert(findBy(changes(), "selectionGroup", "retained").textContent.includes(source.work_experience[0].achievements[0].text), "Retained content in review");
      assert(findBy(changes(), "selectionGroup", "recommended").textContent.includes(source.work_experience[0].achievements[2].text), "Recommended content in review");
      assert(!all(content()).some(item => item.className?.includes("selection-indicator")), "No selection badges in the document");
      assert(!content().textContent.includes("Strong support"), "Evidence strength stays outside the document");
      break;
    case "omissions":
      assert(changes().textContent.includes("Omitted from Current CV"), "Omission group exists");
      assert(changes().textContent.includes("Helped with an internal database task."), "Old baseline only in changes");
      assert(changes().textContent.includes("section limit"), "Controlled omission explanation");
      break;
    case "explanations":
      assert(changes().textContent.includes("maintenance"), "Original maintenance caveat preserved");
      assert(changes().textContent.includes("Required") && changes().textContent.includes("Preferred"), "Importance displayed");
      assert(changes().textContent.includes("Original wording") && changes().textContent.includes("Technology tag"), "Origins displayed");
      assert(changes().textContent.includes("Matched option: Python"), "Selected OR option exposed");
      break;
    case "coverage":
      assert(coverage().textContent.includes("Experience Bank: 4 strong · 1 related · 2 not evidenced"), "Bank-wide baseline");
      assert(coverage().textContent.includes("Selected work/projects:"), "Separate selected coverage");
      assert(findBy(coverage(), "coverageRequirementId", "r7").textContent.includes("Education: BSc"), "Degree remains separate from work coverage");
      assert(coverage().textContent.includes("Recorded skills:"), "Skill labels distinct from engineering support");
      break;
    case "empty":
      assert(content().textContent.includes("No CV content was selected"), "Empty state");
      assert(!all(content()).some(item => item.dataset.tailoredSection), "No broken empty headings");
      break;
    case "missing_baseline":
      assert(nodes["#tailoring-warnings"].textContent.includes("missing or empty Current CV"), "Baseline limitation reported accurately");
      break;
    case "stale_refs":
      assert(nodes["#tailoring-warnings"].textContent.includes("Saved role no longer exists"), "Stale references surfaced");
      assert(!nodes["#tailoring-warnings"].hidden, "Warnings nonblocking");
      break;
    case "missing_destinations":
      assert(nodes["#tailoring-warnings"].textContent.includes("not relocated"), "Ownership issue reported");
      assert(nodes["#tailoring-warnings"].textContent.includes("not inferred"), "Unavailable skills not guessed");
      assert(all(content()).filter(item => item.dataset.tailoredBulletId === "oracle").length === 1, "Wrong-parent reference cannot duplicate a bullet");
      break;
    case "unsupported_destination":
      assert(nodes["#tailoring-warnings"].textContent.includes("no supported CV destination"), "Unsupported content warning");
      break;
    case "safe_text":
      assert(content().textContent.includes("<script>alert('bullet')</script>"), "HTML-like bullet remains text");
      assert(content().textContent.includes("<svg onload=alert(1)>"), "Project text literal");
      assert(nodes["#tailoring-warnings"].textContent.includes("<script>warning</script>"), "Warnings literal");
      assert(content().textContent.includes("<script>degree</script>") && content().textContent.includes("<script>certificate</script>"), "Credentials remain text");
      assert(content().textContent.includes("<b>Skill group</b>"), "Group name remains text");
      assert(!all(content()).some(item => ["script", "img", "svg", "a"].includes(item.tagName)), "No injected elements or executable links");
      break;
    case "regenerate":
      await action();
      assert(countRequests("/tailoring/preview") === 2 && countRequests("/analyse") === 1, "Regeneration reuses analysis only");
      break;
    case "no_mutation":
      same(JSON.stringify(previewJSON), before, "Frontend did not mutate preview response");
      same(JSON.stringify(fixturePreview), originalPreview, "Original API fixture unchanged");
      same(analysisJSON, fixtureAnalysis, "Existing analysis unchanged");
      break;
    case "snapshot_use":
      assert(content().textContent.includes("Example & Co"), "Returned source snapshot supplies content");
      assert(!content().textContent.includes("Unrelated editor skill"), "Editor bank not combined with proposal");
      assert(countRequests("/experience-bank") === 1 && countRequests("/current-cv") === 0, "Preview does not fetch stores again");
      break;
    case "empty_requirements":
      assert(coverage().textContent.includes("No job requirements were reported"), "Empty requirement state");
      break;
    case "limited_coverage": {
      const row = findBy(coverage(), "coverageRequirementId", "r2");
      assert(row.textContent.includes("Strong support") && row.textContent.includes("Not represented"), "Excluded support not relabelled missing from bank");
      assert(nodes["#tailoring-warnings"].textContent.includes("not represented in selected work/projects"), "Selection coverage limitation visible");
      break;
    }
    case "related_only":
      assert(nodes["#tailoring-warnings"].textContent.includes("Only related bank evidence"), "Limited support warning");
      break;
  }
  assert(requests.every(item => ["GET", "POST"].includes(item.method)), "No automatic persistence");
  assert(countRequests("/analyse") === 1, "No explanation or preview OpenAI calls");
  assert(JSON.stringify(previewJSON) === before, "Rendering did not modify returned references or source data");
}

async function managementScenario() {
  const rows = (id, type) => nodes[`#${id}`].querySelectorAll(`.${type}`);
  const role = () => rows("work-list", "work-entry")[0];
  const education = () => rows("education", "credential-entry")[0];
  const certification = () => rows("certifications", "credential-entry")[0];
  const field = (record, name) => record.querySelector(`[data-field="${name}"]`);
  const press = async (root, label) => {
    const button = all(root).find(item => item.tagName === "button" && item.textContent === label);
    assert(button, `Action exists: ${label}`); await fire(button, "click"); await settle();
  };
  const input = async (target, value) => { target.value = value; await fire(target, "input"); await settle(); };
  const save = async () => { allowBankSave = true; await fire(nodes["#bank-form"], "submit"); await settle(); };
  const puts = () => requests.filter(item => item.method === "PUT" && item.url === "/experience-bank");
  if (scenario === "management_load_failure") {
    assert(nodes["#save-bank-button"].disabled && nodes["#bank-message"].textContent.includes("Fictional load failure"), "Loading failure disables save and explains retry");
    await save(); assert(puts().length === 0, "Failed loading cannot overwrite the bank"); return;
  }
  const baselineBank = copy(readBank());
  assert(nodes["#bank-state"].textContent === "Saved", "Initial record forms preserve the loaded baseline");
  if (scenario === "management_additional") {
    const root = nodes["#additional-evidence-editor"];
    const record = root.querySelector(".evidence-entry");
    assert(record && !record.open, "Additional evidence uses the same collapsed record treatment");
    await input(field(record, "text"), "  Updated additional evidence.  ");
    const value = readBank().additional_evidence[0];
    assert(value.id === "note" && value.text === "  Updated additional evidence.  ", "Additional evidence keeps its ID and exact wording");
    same(value.outcomes, ["Recorded outcome"], "Additional evidence optional metadata is kept");
    await press(root, "Delete evidence from bank");
    assert(readBank().additional_evidence.length === 0 && document.activeElement.textContent === "Add evidence", "Removing the last item focuses its Add action");
    same(readBank().work_experience, baselineBank.work_experience, "Additional evidence edits never affect work roles");
  } else if (scenario === "management_labels") {
    for (const id of ["work-list", "project-list", "education", "certifications"]) {
      const records = nodes[`#${id}`].querySelectorAll(".bank-record");
      assert(records.every(item => item.tagName === "details" && !item.open), "Loaded records are collapsed without discarding fields");
      for (const control of nodes[`#${id}`].querySelectorAll("[data-bank-label]")) {
        assert(all(nodes[`#${id}`]).some(item => item.tagName === "label" && item.attributes.for === control.id), "Every input has a persistent associated label");
        assert(control.attributes["aria-describedby"].includes(`${control.id}-error`), "Validation is associated with its input");
      }
    }
    role().open = true;
    await input(field(role(), "role"), "Updated role title");
    assert(role().querySelector("summary").textContent.includes("Updated role title") && nodes["#bank-state"].textContent === "Unsaved changes", "Heading and dirty state follow edits");
    assert(puts().length === 0, "Editing and disclosures do not autosave");
  } else if (["management_add_delete_role", "management_add_delete_project"].includes(scenario)) {
    const work = scenario.endsWith("role");
    const id = work ? "work-list" : "project-list", type = work ? "work-entry" : "project-entry";
    const before = rows(id, type).length;
    await click(work ? "add-work" : "add-project"); await settle();
    const added = rows(id, type)[before];
    assert(added.open && document.activeElement === field(added, work ? "employer" : "name"), "New record opens and focuses its first field");
    await input(field(added, work ? "employer" : "name"), "Fictional new record");
    if (work) await input(field(added, "role"), "Engineer");
    await press(added, `Add ${work ? "achievement" : "contribution"}`);
    const evidence = added.querySelector(".evidence-entry");
    assert(evidence.open && document.activeElement === field(evidence, "text"), "Adding evidence focuses its wording");
    await input(field(evidence, "text"), "  New CV-ready wording.\nPreserve this.  ");
    const value = readBank()[work ? "work_experience" : "projects"][before];
    assert(!value.id && (value.achievements || value.evidence)[0].text === "  New CV-ready wording.\nPreserve this.  ", "New records leave identity generation to the existing save API and preserve wording");
    await press(evidence, `Delete ${work ? "achievement" : "contribution"} from bank`);
    assert(!added.querySelector(".evidence-entry"), "Evidence removal affects only its own row");
    await press(added, work ? "Delete role from bank" : "Delete project from bank");
    assert(rows(id, type).length === before && document.activeElement.tagName === "summary", "Deletion restores focus to a neighbouring record");
    same(readBank(), baselineBank, "Adding then deleting returns to the exact baseline");
  } else if (scenario === "management_credential_edit") {
    await input(field(education(), "qualification"), "Renamed | qualification");
    await input(field(certification(), "issuer"), "Changed issuer");
    const changed = readBank();
    assert(changed.education[0].id === baselineBank.education[0].id && changed.education[0].qualification === "Renamed | qualification", "A title edit does not change education identity");
    assert(changed.certifications[0].id === baselineBank.certifications[0].id && changed.certifications[0].year === "2025", "Certification optional fields and identity remain intact");
    same(changed.certifications[0].skills, ["AWS (EC2, S3)", "Testing"], "Comma-containing tags are not split on unrelated edits");
    await save();
    same(readBank(), changed, "Server response repopulates record forms without altering identities or metadata");
    assert(nodes["#bank-state"].textContent === "Saved" && puts().length === 1, "Only explicit save persists the change");
  } else if (scenario === "management_credentials_add_remove") {
    await click("add-education"); await settle();
    const record = rows("education", "credential-entry")[1];
    assert(record.open && document.activeElement === field(record, "qualification"), "New qualification is ready to edit");
    await input(field(record, "qualification"), "New qualification"); await input(field(record, "institution"), "Fictional institute");
    await click("add-certifications"); await settle();
    const cert = rows("certifications", "credential-entry")[1];
    await input(field(cert, "name"), "New certificate");
    await save();
    assert(readBank().education[1].id && readBank().certifications[1].id, "New credential IDs come back from the save response");
    await press(education(), "Delete education from bank");
    assert(readBank().education.length === 1 && readBank().education[0].qualification === "New qualification", "Delete targets an education record rather than its title");
    assert(puts().length === 1 && nodes["#bank-state"].textContent === "Unsaved changes", "Deletion remains a draft until explicitly saved");
  } else if (scenario === "management_evidence_metadata") {
    same(readBank(), baselineBank, "No-op reading preserves raw wording, CRLF and optional metadata");
    const evidence = role().querySelector(".evidence-entry");
    await input(field(evidence, "text"), "  Explicitly edited wording.\nKeep spaces.  ");
    const value = readBank().work_experience[0].achievements[0];
    assert(value.id === "testing" && value.text === "  Explicitly edited wording.\nKeep spaces.  ", "Wording edits preserve exact new text and existing evidence identity");
    same(value.outcomes, baselineBank.work_experience[0].achievements[0].outcomes, "Unedited multiline outcomes survive");
    same(value.skills, ["AWS (EC2, S3)"], "Unedited evidence tags survive");
    assert(field(role(), "summary").value.includes("Original role context"), "Role context stays independent from the achievement");
  } else if (scenario === "management_validation") {
    await input(field(education(), "institution"), "   ");
    await save();
    const target = field(education(), "institution");
    assert(puts().length === 0 && target.attributes["aria-invalid"] === "true", "Required credential fields are validated before sending");
    assert(education().open && document.activeElement === target, "Validation opens and focuses a collapsed invalid record");
    assert(!document.querySelector(`#${target.id}-error`).hidden && nodes["#bank-message"].attributes.role === "alert", "The field and save error are announced");
    await input(target, "Corrected institute"); await save();
    assert(puts().length === 1 && nodes["#bank-state"].textContent === "Saved", "Corrected form can be explicitly saved");
  } else if (scenario === "management_server_validation") {
    enqueue("/experience-bank", reply(422, { detail: [{ loc: ["body", "education", 0, "institution"], msg: "Institution is invalid." }] }));
    await save();
    assert(nodes["#bank-message"].textContent.includes("education → 0 → institution: Institution is invalid."), "Server validation is readable, with its field path");
    same(readBank(), baselineBank, "Server rejection does not rewrite the record draft");
  } else if (scenario === "management_save_failure") {
    await input(field(education(), "qualification"), "Draft qualification");
    enqueue("/experience-bank", reply(503, { detail: "Fictional save failure." })); await save();
    assert(nodes["#bank-message"].textContent.includes("Fictional save failure") && nodes["#bank-state"].textContent === "Unsaved changes", "Failure keeps the draft and dirty state");
    assert(!nodes["#bank-form"].inert && !nodes["#save-bank-button"].disabled, "Save becomes usable again after failure");
    await save(); assert(readBank().education[0].qualification === "Draft qualification" && puts().length === 2, "Explicit retry saves the same draft");
  } else if (scenario === "management_saving_lock") {
    const pending = deferred(); enqueue("/experience-bank", pending.promise);
    allowBankSave = true; const task = fire(nodes["#bank-form"], "submit"); await settle();
    assert(nodes["#bank-form"].inert && nodes["#save-bank-button"].disabled, "The bank is locked while saving");
    await fire(nodes["#bank-form"], "submit"); assert(puts().length === 1, "Duplicate saves are ignored");
    pending.resolve(reply(200, baselineBank)); await task;
    assert(!nodes["#bank-form"].inert && !nodes["#save-bank-button"].disabled, "Successful save unlocks controls");
  } else if (["management_navigation_drafts", "management_new_analysis", "management_no_analysis"].includes(scenario)) {
    if (scenario === "management_new_analysis") await analyse();
    await click("show-bank"); await input(field(role(), "role"), "Unsaved role draft");
    await click("show-current-cv"); await settle();
    await input(document.querySelector("#cv-setting-max_projects"), "0");
    await click("show-workspace"); await click("new-analysis"); await settle();
    await click("show-bank"); assert(field(role(), "role").value === "Unsaved role draft", "Navigation and New Analysis preserve bank drafts");
    await click("show-current-cv"); await settle();
    assert(document.querySelector("#cv-setting-max_projects").value === "0" && nodes["#current-cv-state"].textContent === "Unsaved changes", "Bank refreshes do not overwrite CV limit edits");
    assert(puts().length === 0 && !requests.some(item => item.method === "PUT"), "Navigation and New Analysis never save management drafts");
  } else if (scenario === "management_stale_references") {
    await click("show-current-cv"); await settle();
    await click("show-bank"); await press(role().querySelector(".evidence-entry"), "Delete achievement from bank"); await save();
    assert(nodes["#current-cv-warnings"].textContent.includes("missing or no longer belongs"), "Saving bank deletion reports stale CV references");
    assert(all(nodes["#cv-work-list"]).some(item => item.dataset.bulletId === "testing"), "The CV draft keeps unavailable references for explicit correction");
    assert(!requests.some(item => item.method === "PUT" && item.url === "/current-cv"), "Bank save never silently repairs or saves CV selections");
  } else if (scenario === "management_safe_text") {
    await input(field(education(), "qualification"), '<script>alert("credential")</script>');
    assert(education().querySelector("summary").textContent.includes("<script>"), "Untrusted headings remain literal text");
    assert(!all(nodes["#bank-form"]).some(item => ["script", "img", "svg"].includes(item.tagName)), "Record headings and fields do not create executable elements");
  } else if (scenario === "management_payload_roundtrip") {
    await input(field(education(), "qualification"), "Renamed | qualification");
    await input(field(certification(), "year"), "");
    await save(); print(`BANKDOCUMENT ${JSON.stringify(readBank())}`);
  } else if (scenario === "management_metadata_edges") {
    await save();
    assert(puts().length === 1 && nodes["#bank-state"].textContent === "Saved", "Native input normalisation and Unicode validation do not rewrite or reject valid saved metadata");
    same(readBank(), baselineBank, "Unedited metadata survives an explicit save exactly");
    print(`BANKDOCUMENT ${JSON.stringify(readBank())}`);
  } else throw new Error(`Unknown management scenario ${scenario}`);
  assert(countRequests("/analyse") === (scenario === "management_new_analysis" ? 1 : 0), "Management controls never trigger extra extraction");
  assert(countRequests("/tailoring/preview") === 0, "Management controls never generate a tailored preview");
}

async function tailorScenario() {
  await analyse();
  await click("stage-tailor");
  const empty = nodes["#tailoring-empty"];
  const output = nodes["#tailoring-output"];
  const state = nodes["#tailoring-state"];
  const summary = nodes["#tailoring-summary"];
  if (scenario === "tailor_pregeneration") {
    assert(!empty.hidden && output.hidden && !previewButton().disabled, "Explicit generation has its own empty state");
    assert(countRequests("/tailoring/preview") === 0, "Entering Tailor does not generate automatically");
    return;
  }
  if (scenario === "tailor_loading") {
    const pending = deferred(); enqueue("/tailoring/preview", pending.promise);
    const task = action(); await settle();
    assert(empty.hidden && output.hidden && previewButton().disabled, "Loading replaces the pre-generation state");
    assert(state.textContent.includes("Generating") && nodes["#tailoring-preview"].attributes["aria-busy"] === "true", "Loading is announced");
    await action(); assert(countRequests("/tailoring/preview") === 1, "No duplicate generation");
    pending.resolve(reply(200, previewJSON)); await task;
    assert(empty.hidden && !output.hidden, "Success replaces loading");
    return;
  }
  if (scenario === "tailor_empty_sections") {
    previewJSON.proposed_cv.projects = [];
    previewJSON.proposed_cv.skill_groups = [];
    previewJSON.source_bank.education = [];
    previewJSON.source_bank.certifications = [];
  }
  if (scenario === "tailor_declaration_coverage") {
    const row = previewJSON.coverage.find(item => item.requirement_id === "r2");
    row.selected_status = "related";
    row.meaningful_evidence_ids = [];
  }
  if (scenario === "tailor_missing_credential") previewJSON.source_bank.education = [];
  const before = JSON.stringify(previewJSON);
  await action();
  assert(empty.hidden && !output.hidden && !previewButton().disabled, "Generated preview is ready");
  if (scenario === "tailor_document") {
    same(all(content()).filter(item => item.dataset.tailoredSection).map(item => item.dataset.tailoredSection),
      ["work_experience", "projects", "education", "certifications", "skills"], "All document sections in the existing order");
    for (const record of all(content()).filter(item => item.dataset.tailoredBulletId)) {
      assert(record.children.length === 1, "Document bullets contain only their original text");
    }
    assert(!content().textContent.includes("Retained") && !content().textContent.includes("Recommended"), "Review labels are outside the CV");
    assert(!all(content()).some(item => ["button", "details", "input"].includes(item.tagName)), "Document is read only");
    assert(content().textContent.includes("2023") && content().textContent.includes(source.work_experience[0].summary), "Original work dates and context preserved");
  } else if (scenario === "tailor_review_groups") {
    for (const [name, include] of [
      ["retained", item => item.selected && item.was_in_current_cv && !["education", "certification"].includes(item.source_type)],
      ["recommended", item => item.selected && !item.was_in_current_cv && !["education", "certification"].includes(item.source_type)],
      ["omitted", item => !item.selected && item.was_in_current_cv],
    ]) {
      const expected = previewJSON.decisions.filter(include);
      const group = findBy(changes(), "selectionGroup", name);
      assert(group.tagName === "details" && !group.open && group.children[0].tagName === "summary", "Recommendation groups start collapsed with native disclosure semantics");
      assert(group.children[0].textContent.endsWith(`(${expected.length})`), "The closed group exposes the accurate backend decision count");
      same(all(group).filter(item => item.dataset.decisionId).map(item => [item.dataset.decisionType, item.dataset.decisionId]),
        expected.map(item => [item.source_type, item.source_id]), "Classification uses backend decisions exactly");
      same(findBy(summary, "selectionSummary", name).children[0].textContent, String(expected.length), "Counts follow record decisions");
    }
    assert(!changes().textContent.includes("replaced"), "No invented replacement pairing");
  } else if (scenario === "tailor_group_expansion") {
    const retained = findBy(changes(), "selectionGroup", "retained");
    const recommended = findBy(changes(), "selectionGroup", "recommended");
    assert(all(changes()).filter(item => item.dataset.selectionGroup).every(item => item.tagName === "details" && !item.open), "Every selection group starts collapsed");
    retained.open = true; recommended.open = true;
    const decision = findBy(recommended, "decisionId", "api"); decision.open = true;
    same(decision.children[1].children[0].textContent, source.projects[0].evidence[0].text, "Expansion exposes complete exact original wording");
    assert(decision.textContent.includes("maintenance") && decision.textContent.includes("Original wording"), "Full caveats and provenance remain available");
    const count = requests.length;
    await click("show-bank"); await click("show-workspace"); await click("stage-tailor");
    assert(retained.open && recommended.open && decision.open, "Navigation retains the expanded review and the preview snapshot");
    same(requests.length, count, "Expanding and returning never regenerates or writes the preview");
    same(nodes["#tailoring-coverage-title"].textContent, `Requirement coverage (${previewJSON.coverage.length})`, "Coverage count is visible without expanding it");
  } else if (scenario === "tailor_visible_warnings") {
    assert(all(changes()).filter(item => item.dataset.selectionGroup).every(item => !item.open), "Detailed lists can stay closed");
    assert(!nodes["#tailoring-warnings"].hidden && nodes["#tailoring-warnings"].textContent.includes("no recorded bank evidence"), "Important limitations are visible independently of the collapsed groups");
    assert(summary.textContent.includes("Retained") && summary.textContent.includes("Newly recommended"), "Summary counts remain separate from evidence strength");
  } else if (scenario === "tailor_disclosures") {
    for (const item of previewJSON.decisions) {
      const element = all(changes()).find(value => value.dataset.decisionId === item.source_id && value.dataset.decisionType === item.source_type);
      assert(element.tagName === "details" && !element.open && element.children[0].tagName === "summary", "Native closed disclosure per decision");
      assert(element.children[1].textContent.includes(item.recommendation), "Full reason is available on expansion");
      if (item.original_text !== null) same(element.children[1].children[0].textContent, item.original_text, "Full original wording remains exact");
    }
    assert(changes().textContent.includes("maintenance") && changes().textContent.includes("Technology tag"), "Caveats and provenance retained");
    assert(changes().textContent.includes("Matched option: Python"), "OR option is not flattened");
  } else if (scenario === "tailor_coverage") {
    same(all(coverage()).filter(item => item.dataset.coverageRequirementId).map(item => item.dataset.coverageRequirementId),
      previewJSON.coverage.map(item => item.requirement_id), "Every coverage row remains ordered");
    assert(!all(coverage()).some(item => item.tagName === "table"), "Coverage adapts to a narrow panel without a wide table");
    for (const row of previewJSON.coverage) {
      const element = findBy(coverage(), "coverageRequirementId", row.requirement_id);
      assert(element.textContent.includes("Bank evidence:") && element.textContent.includes("Selected work/projects:"), "Bank and selected evidence are explicitly separate");
    }
    assert(coverage().textContent.includes("Recorded skills:"), "Skill labels remain separate from engineering support");
  } else if (scenario === "tailor_declaration_coverage") {
    const row = findBy(coverage(), "coverageRequirementId", "r2");
    assert(row.textContent.includes("Related support") && row.textContent.includes("Declarations only; practical activity is not established"), "Declarations preserve their reported status with a practical-activity caveat");
  } else if (scenario === "tailor_credentials") {
    const credentials = findBy(changes(), "selectionGroup", "credentials");
    assert(credentials.textContent.includes("BSc Hons Computer Science") && credentials.textContent.includes("Original certificate"), "Unchanged credentials have their own review group");
    const row = findBy(coverage(), "coverageRequirementId", "r7");
    assert(row.textContent.includes("Education: BSc Hons Computer Science"), "Credential support is present even without a work bullet");
    assert(row.textContent.includes("Not represented in work/projects") && row.textContent.includes("Strong support"), "Qualification is not relabelled absent from the bank");
  } else if (scenario === "tailor_empty_sections") {
    same(all(content()).filter(item => item.dataset.tailoredSection).map(item => item.dataset.tailoredSection), ["work_experience"], "Absent sections do not leave empty document headings");
  } else if (scenario === "tailor_missing_credential") {
    assert(!findBy(content(), "tailoredSection", "education"), "Unavailable snapshot credentials cannot be invented from a decision");
    assert(!findBy(coverage(), "coverageRequirementId", "r7").textContent.includes("Education: BSc"), "Coverage does not claim an unavailable credential is displayed");
    assert(changes().textContent.includes("not shown in the proposed CV") && nodes["#tailoring-warnings"].textContent.includes("selected credential is unavailable"), "Stale credential references are explained");
  } else if (scenario.startsWith("tailor_regenerate_") || scenario === "tailor_render_failure") {
    const previous = content().textContent;
    const pending = deferred(); enqueue("/tailoring/preview", pending.promise);
    const task = action(); await settle();
    assert(output.hidden && empty.hidden && previewButton().disabled, "The previous preview is not presented as a fresh result while regenerating");
    if (scenario === "tailor_regenerate_stale_failure") {
      await analyse("A different job description.");
      pending.resolve(reply(503, { detail: "Old regeneration failed." })); await task;
      assert(output.hidden && !empty.hidden && nodes["#tailoring-error"].hidden, "Late failure never restores selections for an older analysis");
      assert(content().textContent === "" && summary.textContent === "", "New analysis clears both document and review counts");
      return;
    }
    if (scenario === "tailor_regenerate_loading") {
      await action(); assert(countRequests("/tailoring/preview") === 2, "No duplicate regeneration");
      pending.resolve(reply(200, previewJSON)); await task;
      assert(!output.hidden && nodes["#tailoring-error"].hidden && state.textContent.includes("Preview ready"), "Successful regeneration restores the result");
    } else if (scenario === "tailor_render_failure") {
      pending.resolve(reply(200, {})); await task;
      assert(output.hidden && !nodes["#tailoring-error"].hidden, "A render error cannot label partially changed DOM as a valid preceding preview");
    } else {
      pending.resolve(reply(503, { detail: "Preview unavailable. Try again." })); await task;
      assert(!output.hidden && !nodes["#tailoring-error"].hidden && !previewButton().disabled, "A same-analysis request failure preserves the valid preceding preview and retry");
      same(content().textContent, previous, "Failed request leaves preceding content intact");
      assert(state.textContent.includes("previous successful preview") && state.textContent.includes("saved content may have changed"), "Preceding preview is labelled accurately");
      if (scenario === "tailor_regenerate_retry") {
        await action();
        assert(nodes["#tailoring-error"].hidden && !output.hidden && state.textContent.includes("Preview ready"), "A later success clears the failure and preceding-preview notice");
      } else if (scenario === "tailor_regenerate_invalidation") {
        await edit("Changed job description");
        assert(output.hidden && content().textContent === "" && summary.textContent === "", "Invalidation removes preceding selections and counts");
        assert(nodes["#tailoring-preview"].hidden && previewButton().disabled, "No stale preview remains available");
      }
    }
  } else throw new Error(`Unknown Tailor scenario ${scenario}`);
  same(JSON.stringify(previewJSON), before, "Tailor presentation does not modify the response snapshot");
  assert(requests.every(item => ["GET", "POST"].includes(item.method)), "No save/apply writes");
  assert(countRequests("/analyse") === 1 && countRequests("/current-cv") === 0, "No extra extraction or store reloads");
}

async function workspaceScenario() {
  const stage = name => !nodes[`#${name}-stage`].hidden;
  const checkInitial = () => {
    assert(!nodes["#workspace-view"].hidden && stage("analyse"), "Default Tailor CV / Analyse");
    assert(nodes["#bank-view"].hidden && nodes["#current-cv-view"].hidden, "Management starts hidden");
    assert(nodes["#stage-match"].disabled && nodes["#stage-tailor"].disabled, "Later stages require analysis");
  };
  checkInitial();
  if (scenario === "workspace_new_empty") {
    nodes["#job-description"].value = "  \n\t ";
    await click("new-analysis");
    assert(confirmations === 0, "No needless empty-workspace confirmation");
    same(requests.map(item => item.url), ["/experience-bank"], "Reset does not load or save content");
    return;
  }
  if (scenario === "workspace_new_management_only") {
    await click("show-bank"); nodes["#skills"].value = "Unsaved bank-only draft";
    await click("show-current-cv"); await settle();
    const input = document.querySelector("#cv-group-heading-0"); input.value = "Unsaved CV-only draft"; await fire(input, "input");
    await click("new-analysis");
    assert(confirmations === 0, "Unrelated management drafts are not job work to discard");
    assert(nodes["#skills"].value === "Unsaved bank-only draft", "Bank-only draft survives empty job reset");
    assert(document.querySelector("#cv-group-heading-0").value === "Unsaved CV-only draft", "CV-only draft survives empty job reset");
    assert(!nodes["#workspace-view"].hidden && stage("analyse"), "Empty job reset returns to Analyse");
    return;
  }
  if (scenario === "workspace_new_cancel") {
    await edit("Unsubmitted job-specific draft."); discard = false;
    await click("new-analysis");
    assert(confirmations === 1 && nodes["#job-description"].value === "Unsubmitted job-specific draft.", "Cancel preserves typed job draft");
    return;
  }
  if (scenario === "workspace_new_cleared_source") {
    await analyse(); await edit(""); discard = false;
    await click("new-analysis");
    assert(confirmations === 1 && !nodes["#analysis-result"].hidden, "Clearing source text does not silently discard existing analysis");
    return;
  }
  if (scenario === "workspace_mobile_menu") {
    await click("toggle-navigation");
    assert(nodes["#app-navigation"].dataset.open === "true" && nodes["#toggle-navigation"].attributes["aria-expanded"] === "true", "Accessible mobile disclosure");
    for (const listener of nodes["#app-navigation"].listeners.keydown) listener({ key: "Escape" });
    assert(nodes["#app-navigation"].dataset.open === "false" && document.activeElement === nodes["#toggle-navigation"], "Escape closes and restores focus");
    await click("toggle-navigation"); await click("show-bank");
    assert(nodes["#app-navigation"].dataset.open === "false", "Selecting a destination closes mobile navigation");
    return;
  }
  if (scenario === "workspace_navigation") {
    const initialRequests = requests.length;
    await click("show-bank");
    assert(!nodes["#bank-view"].hidden && nodes["#workspace-view"].hidden, "Bank has its own destination");
    assert(nodes["#show-bank"].attributes["aria-pressed"] === "true", "Active bank destination");
    assert(nodes["#page-title"].textContent === "Experience Bank", "Destination title");
    await click("show-workspace");
    assert(requests.length === initialRequests, "Workspace/bank navigation never reruns requests");
    await click("show-current-cv"); await settle();
    assert(!nodes["#current-cv-view"].hidden && nodes["#page-title"].textContent === "My CV", "Existing builder under My CV");
    assert(countRequests("/current-cv") === 1, "Only first-open CV read, not a save");
    await click("show-current-cv"); await settle();
    assert(countRequests("/current-cv") === 1, "Clicking the active destination does not reload it");
    return;
  }
  if (["workspace_reset_analysis", "workspace_reset_match", "workspace_navigation_while_matching"].includes(scenario)) {
    const old = deferred();
    enqueue(scenario === "workspace_reset_analysis" ? "/analyse" : "/match", old.promise);
    await edit(fixtureDescription);
    const oldTask = fire(nodes["#match-form"], "submit"); await settle();
    if (scenario === "workspace_navigation_while_matching") {
      await click("show-bank");
      old.resolve(reply(200, fixturePreview.matching_result)); await oldTask;
      assert(!nodes["#bank-view"].hidden && document.activeElement === nodes["#page-title"], "Completion does not navigate away from management or steal focus");
      await click("show-workspace");
      assert(!nodes["#stage-match"].disabled, "Completed results preserved on return");
      return;
    }
    await click("new-analysis");
    assert(nodes["#job-description"].value === "" && stage("analyse"), "In-flight reset starts a fresh session");
    analysisJSON.job_title = "Fresh job after reset";
    const fresh = deferred(); enqueue("/analyse", fresh.promise);
    await edit(fixtureDescription + "\nFresh job.");
    const freshTask = fire(nodes["#match-form"], "submit"); await settle();
    old.resolve(reply(200, scenario === "workspace_reset_analysis" ? fixtureAnalysis : fixturePreview.matching_result)); await oldTask;
    assert(nodes["#analyse-button"].disabled, "Old finally cannot unlock the fresh analysis");
    fresh.resolve(reply(200, analysisJSON)); await freshTask;
    assert(nodes["#results-title"].textContent === "Fresh job after reset", "Discarded response cannot overwrite new analysis");
    assert(!nodes["#continue-to-match"].disabled, "Fresh workflow progresses normally");
    return;
  }
  if (scenario === "workspace_match_loading") {
    const pending = deferred(); enqueue("/match", pending.promise);
    await edit(fixtureDescription);
    const task = fire(nodes["#match-form"], "submit"); await settle();
    assert(!nodes["#stage-match"].disabled && nodes["#continue-to-match"].disabled, "Analysis opens Match, but Continue waits for matching");
    await click("stage-match");
    assert(!nodes["#match-empty"].hidden && nodes["#match-empty"].textContent.includes("Matching"), "Match loading state");
    pending.resolve(reply(200, previewJSON.matching_result)); await task;
    assert(nodes["#match-empty"].hidden && !nodes["#continue-to-match"].disabled, "Results unlock Continue");
    return;
  }
  if (scenario === "workspace_match_failure") enqueue("/match", reply(503, { detail: "Matching unavailable." }));
  await analyse();
  if (scenario === "workspace_match_failure") {
    await click("stage-match");
    assert(!nodes["#match-empty"].hidden && nodes["#match-empty"].textContent.includes("could not be completed"), "Stage-specific failure presentation");
    assert(!nodes["#match-generate-preview"].disabled, "Existing successful analysis still supports preview retry");
    await click("stage-tailor"); assert(!previewButton().disabled, "Preview owns its own retryable request");
    return;
  }
  if (["workspace_stages", "workspace_return_stage", "workspace_accessibility", "workspace_pregeneration"].includes(scenario)) {
    const before = requests.length;
    await click("continue-to-match"); assert(stage("match"), "Continue switches to Match");
    assert(!nodes["#job-context"].hidden && nodes["#results-title"].textContent === fixtureAnalysis.job_title, "Target role remains visible across workflow stages");
    assert(nodes["#match-groups"].textContent.includes("Related matches") && nodes["#match-groups"].textContent.includes("Not evidenced"), "Visible labels retain matching classifications");
    await click("stage-tailor"); assert(stage("tailor"), "Tailor pre-generation stage");
    assert(nodes["#tailoring-output"].hidden && !previewButton().disabled, "Pre-generation state needs an explicit action");
    if (scenario === "workspace_return_stage") { await click("show-bank"); await click("show-workspace"); assert(stage("tailor"), "Tailor CV remembers last workflow stage"); }
    assert(requests.length === before, "Stage navigation does not rerun any requests");
    if (scenario === "workspace_accessibility") {
      assert(nodes["#stage-tailor"].attributes["aria-current"] === "step", "Current stage exposed");
      assert(!nodes["#stage-analyse"].attributes["aria-current"] && !nodes["#stage-match"].attributes["aria-current"], "Only one current stage");
      assert(document.activeElement === nodes["#stage-tailor"], "Stage focus remains visible");
    }
    await click("stage-analyse"); assert(stage("analyse"), "Can return to analysis without losing results");
    assert(!nodes["#analysis-result"].hidden, "Extracted analysis stays mounted");
    return;
  }
  if (scenario === "workspace_cv_save_lock") {
    await click("show-current-cv"); await settle();
    allowCVSave = true;
    const pending = deferred(); enqueue("/current-cv", pending.promise);
    const saveTask = fire(nodes["#current-cv-form"], "submit"); await settle();
    assert(nodes["#current-cv-form"].inert, "Existing save guard remains active");
    await click("new-analysis"); await click("show-bank"); await click("stage-match");
    assert(!nodes["#current-cv-view"].hidden && confirmations === 0, "Navigation and reset blocked during CV save");
    assert(nodes["#new-analysis"].disabled && nodes["#show-bank"].disabled, "All new navigation controls honour save lock");
    pending.resolve(reply(200, savedCV)); await saveTask;
    await click("show-workspace"); assert(!nodes["#workspace-view"].hidden, "Navigation restored after save");
    return;
  }
  if (scenario === "workspace_reset_preview") {
    const old = deferred(); enqueue("/tailoring/preview", old.promise);
    const task = action(); await settle();
    await click("new-analysis");
    old.resolve(reply(200, fixturePreview)); await task;
    assert(nodes["#tailoring-preview"].hidden && nodes["#stage-tailor"].disabled, "Discarded preview cannot return or unlock Tailor");
    assert(content().textContent === "", "Discarded preview content cleared");
    return;
  }
  if (scenario === "workspace_generate_action") {
    await click("continue-to-match"); await click("match-generate-preview"); await settle();
    assert(stage("tailor") && !nodes["#tailoring-output"].hidden, "Match action generates through existing preview owner");
    assert(countRequests("/tailoring/preview") === 1 && countRequests("/analyse") === 1, "One preview, no extra extraction");
    return;
  }
  await action();
  const beforePreview = content().textContent;
  const beforeDiagnostics = nodes["#diagnostics"].textContent;
  if (scenario === "workspace_preserve_session") {
    await click("stage-tailor"); await click("show-current-cv"); await settle(); await click("show-bank"); await click("show-workspace");
    assert(stage("tailor"), "Returns to last active stage");
    assert(content().textContent === beforePreview && nodes["#diagnostics"].textContent === beforeDiagnostics, "Feature state survives management visits");
    assert(countRequests("/analyse") === 1 && countRequests("/tailoring/preview") === 1, "No feature request repeated by navigation");
    return;
  }
  if (scenario === "workspace_cancel_preview") {
    discard = false; await click("new-analysis");
    assert(confirmations === 1 && content().textContent === beforePreview, "Cancel keeps completed preview");
    assert(nodes["#job-description"].value === fixtureDescription, "Cancel keeps source description");
    return;
  }
  if (scenario === "workspace_drafts") {
    await click("show-bank"); nodes["#skills"].value = "Unrelated editor skill, Unsaved bank skill";
    await fire(nodes["#bank-form"], "input");
    await click("show-current-cv"); await settle();
    const heading = document.querySelector("#cv-group-heading-0"); heading.value = "Unsaved CV group"; await fire(heading, "input");
    const limit = document.querySelector("#cv-setting-max_skills"); limit.value = "4"; await fire(limit, "input");
    await click("show-bank"); await click("new-analysis"); await click("show-current-cv"); await settle();
    assert(document.querySelector("#cv-group-heading-0").value === "Unsaved CV group", "CV draft survives navigation and job reset");
    assert(document.querySelector("#cv-setting-max_skills").value === "4", "CV draft limits preserved");
    assert(nodes["#skills"].value.includes("Unsaved bank skill"), "Bank draft preserved");
    assert(nodes["#current-cv-state"].textContent === "Unsaved changes", "Draft state remains honest");
    assert(countRequests("/current-cv") === 1, "Returning never replaces a loaded CV draft");
    assert(requests.every(item => item.method !== "PUT"), "Job reset never saves management drafts");
    return;
  }
  assert(scenario === "workspace_new_confirm", "Every workspace scenario has assertions");
  await click("new-analysis");
  assert(confirmations === 1, "Meaningful job work requires confirmation");
  checkInitial();
  assert(nodes["#job-description"].value === "" && nodes["#diagnostics"].textContent === "", "Job source and matches cleared");
  assert(content().textContent === "" && nodes["#analysis-result"].hidden, "Analysis and preview discarded");
  assert(countRequests("/analyse") === 1 && countRequests("/tailoring/preview") === 1, "New Analysis is local, not a request");
}
async function resultsScenario() {
  const requirement = (id, text, category, importance, alternatives = [text], activity = null) => ({
    id, text, category, importance, alternatives, activity, source_text: `Original source: ${text}.`,
  });
  const requirements = [
    requirement("r1", "Python or Java", "skill", "required", ["Python", "Java"]),
    requirement("r2", "AWS or Azure", "skill", "preferred", ["AWS", "Azure"]),
    requirement("r3", "Develop and maintain backend APIs", "responsibility", "unspecified", ["Develop and maintain backend APIs"], "api_development"),
    requirement("r4", "Collaborate with engineers to design software solutions", "responsibility", "unspecified"),
    requirement("r5", "Computer Science degree or a related field", "qualification", "preferred", ["Computer Science degree", "Degree in a related field"]),
    requirement("r6", "Deploy applications to cloud infrastructure", "responsibility", "unspecified", ["Deploy applications to cloud infrastructure"], "cloud_deployment"),
    requirement("r7", "AWS", "skill", "required"),
  ];
  const reference = (id, type, owner, text) => ({ evidence_id: id, source_type: type, source_label: owner, text });
  const python = reference("python-record", "achievement", "Software Engineer at Example & Co", "  Built Python services.\nOriginal achievement wording.  ");
  const java = reference("java-record", "project_evidence", "Java experiment", "Original contribution, with a Java technology tag.");
  const azure = reference("azure-record", "project_evidence", "Search project", "Used Azure AI Search to index documents.");
  const certificate = reference("cert-record", "certification", "Cloud fundamentals certificate", "Original certification wording.");
  const api = reference("api-record", "project_evidence", "JobMatch", "  Designed and implemented REST API endpoints.\nKeep this exact wording.  ");
  const degree = reference("degree-record", "education", "Computer Science degree", "Original degree wording.");
  const support = (req, evidence, status, alternative, origin, explanation, extra = {}) => ({
    requirement_id: req.id, evidence_id: evidence.evidence_id, status, selected_alternative: alternative,
    explanation, signals: [{ signal: alternative, origin, relationship: null, demonstrated_activity: null, ...extra }],
  });
  const match = (req, status, evidence = [], supports = []) => ({
    requirement: req.text, requirement_details: copy(req), status, evidence, evidence_support: supports,
    selected_alternative: supports[0]?.selected_alternative || null, matched_signals: supports.map(row => row.selected_alternative),
    explanation: evidence.length ? "Recorded support is specific to each evidence item." : "No supporting evidence was found in the experience bank.",
  });
  analysisJSON = { job_title: "Backend Engineer", requirements: copy(requirements) };
  for (const [category, field] of [["skill", "technical_skills"], ["other_keyword", "other_keywords"], ["responsibility", "responsibilities"], ["qualification", "qualifications"]]) {
    analysisJSON[field] = requirements.filter(row => row.category === category).map(row => row.text);
  }
  previewJSON.matching_result = {
    job_title: "Backend Engineer",
    strong_matches: [
      match(requirements[0], "strong", [python, java], [
        support(requirements[0], python, "strong", "Python", "wording", "Python engineering is demonstrated."),
        support(requirements[0], java, "related", "Java", "technology_tag", "Java is recorded as a tag; practical activity is not established."),
      ]),
      match(requirements[2], "strong", [api], [support(requirements[2], api, "strong", requirements[2].text, "wording", "API development is demonstrated; maintenance is not established.", { demonstrated_activity: "api_development" })]),
      match(requirements[4], "strong", [degree], [support(requirements[4], degree, "strong", "Computer Science degree", "credential", "Degree level and subject are recorded.")]),
    ],
    related_matches: [match(requirements[1], "related", [azure, certificate], [
      support(requirements[1], azure, "related", "Azure", "technology_tag", "Related cloud technology; deployment is not established.", { relationship: { source: "azure_ai_search", target: "cloud_technologies", type: "broader", confidence: "high" } }),
      support(requirements[1], certificate, "related", "AWS", "credential", "Certification records knowledge, not demonstrated cloud deployment."),
    ])],
    missing_requirements: [match(requirements[3], "missing"), match(requirements[5], "missing"), match(requirements[6], "missing")],
    ranked_evidence: [],
  };
  if (scenario === "results_structured") {
    analysisJSON.technical_skills.push("Contradictory legacy-only technology");
    const keyword = requirement("r8", "Financial services", "other_keyword", "unspecified");
    analysisJSON.requirements.push(keyword);
    previewJSON.matching_result.missing_requirements.push(match(keyword, "missing"));
  }
  if (scenario === "results_legacy") delete analysisJSON.requirements;
  if (["results_legacy", "results_legacy_support"].includes(scenario)) {
    for (const field of ["strong_matches", "related_matches", "missing_requirements"]) for (const item of previewJSON.matching_result[field]) {
      delete item.requirement_details; delete item.evidence_support; delete item.selected_alternative;
    }
  }
  if (scenario === "results_empty_structured") {
    analysisJSON.requirements = [];
    for (const field of ["strong_matches", "related_matches", "missing_requirements"]) previewJSON.matching_result[field] = [];
  }
  if (scenario === "results_empty_category") analysisJSON.requirements = analysisJSON.requirements.filter(row => row.category !== "qualification");
  if (scenario === "results_empty_filter") previewJSON.matching_result.related_matches = [];
  if (scenario === "results_unknown_support") previewJSON.matching_result.strong_matches[0].evidence_support.pop();
  if (scenario === "results_independent") {
    const independent = requirement("r8", "Java", "skill", "required");
    analysisJSON.requirements[0] = requirement("r1", "Python", "skill", "required");
    analysisJSON.requirements.push(independent);
    previewJSON.matching_result.strong_matches[0].requirement = "Python";
    previewJSON.matching_result.strong_matches[0].requirement_details = copy(analysisJSON.requirements[0]);
    previewJSON.matching_result.missing_requirements.push(match(independent, "missing"));
  }
  if (scenario === "results_safe_text") {
    analysisJSON.requirements[0].text = '<img src=x onerror="alert(1)">';
    analysisJSON.requirements[0].source_text = '<script>Original source</script>';
    const item = previewJSON.matching_result.strong_matches[0];
    item.requirement = analysisJSON.requirements[0].text;
    item.evidence[0].text = "  <script>alert('evidence')</script>\nExact whitespace.  ";
    item.evidence[0].source_label = "<svg onload=alert(1)>";
    item.evidence_support[0].explanation = "<b>literal caveat</b>";
  }
  if (["results_all_requirements", "results_long_keyboard"].includes(scenario)) {
    const many = Array.from({ length: 40 }, (_, index) => requirement(`many-${index}`, `Independent skill ${index}`, "skill", "unspecified"));
    analysisJSON.requirements.push(...many);
    previewJSON.matching_result.missing_requirements.push(...many.map(row => match(row, "missing")));
  }
  const beforeAnalysis = JSON.stringify(analysisJSON);
  const beforeMatches = JSON.stringify(previewJSON.matching_result);
  if (scenario === "results_stale_match") {
    const pending = deferred(); enqueue("/match", pending.promise);
    await edit(fixtureDescription);
    const task = fire(nodes["#match-form"], "submit"); await settle();
    await click("new-analysis");
    pending.resolve(reply(200, previewJSON.matching_result)); await task;
    assert(!all(nodes["#requirement-list"]).some(row => row.dataset.requirementKey), "Stale match cannot repopulate requirement choices");
    assert(!nodes["#requirement-evidence-content"].textContent.includes(python.text), "Stale evidence cannot return after reset");
    return;
  }
  await analyse();
  const rows = () => all(nodes["#requirement-list"]).filter(row => row.dataset.requirementKey !== undefined);
  const analysisRows = () => all(nodes["#overview"]).filter(row => row.dataset.requirementId);
  const selected = () => nodes["#selected-requirement"];
  const evidence = () => nodes["#requirement-evidence-content"];
  const choose = async text => { const row = rows().find(item => item.children[0].textContent === text); assert(row, `Requirement exists: ${text}`); await fire(row, "click"); };
  const record = id => findBy(evidence(), "evidenceId", id);
  if (scenario === "results_structured") {
    assert(analysisRows().length === 8 && rows().length === 8, "Structured requirements shown once, without legacy duplicates");
    assert(!nodes["#overview"].textContent.includes("Contradictory legacy-only"), "Structured list is authoritative");
    const keywords = nodes["#overview"].children.find(row => row.children[0]?.textContent === "Other keywords");
    const technical = nodes["#overview"].children.find(row => row.children[0]?.textContent === "Technical skills & capabilities");
    assert(keywords.textContent.includes("Financial services") && !technical.textContent.includes("Financial services"), "Nontechnical keywords are not relabelled as technical capabilities");
    assert(nodes["#results-title"].textContent === "Backend Engineer", "Extracted title preserved");
    same(nodes["#full-analysis"].children.map(item => item.textContent), analysisJSON.requirements.map(item => item.source_text), "Exact original source wording");
  } else if (scenario === "results_importance") {
    const texts = analysisRows().map(row => row.textContent).join("\n");
    for (const importance of ["Required", "Preferred", "Unspecified"]) assert(texts.includes(importance), `Importance retained: ${importance}`);
    await choose("AWS"); assert(selected().textContent.includes("Required"), "Independent required AWS metadata");
    await choose("AWS or Azure"); assert(selected().textContent.includes("Preferred"), "Preferred cloud alternative metadata");
  } else if (scenario === "results_or") {
    assert(analysisRows().filter(row => row.children[0].textContent === "Python or Java").length === 1, "Python OR Java remains one obligation");
    assert(analysisRows()[0].textContent.includes("Python OR Java"), "OR options explicit");
    const combined = analysisRows().find(row => row.children[0].textContent.startsWith("Collaborate"));
    assert(!combined.textContent.includes("Acceptable options"), "Combined responsibility is not invented alternatives");
  } else if (scenario === "results_independent") {
    assert(analysisRows().length === 8 && rows().length === 8, "Independent obligations are never merged");
    assert(analysisRows().some(row => row.children[0].textContent === "Python") && analysisRows().some(row => row.children[0].textContent === "Java"), "Python AND Java remain separate");
  } else if (scenario === "results_legacy") {
    assert(!nodes["#analysis-format-note"].hidden, "Legacy metadata limitation visible");
    assert(nodes["#overview"].textContent.includes("Python or Java"), "Legacy strings displayed unchanged");
    assert(!nodes["#overview"].textContent.includes("Required") && !nodes["#overview"].textContent.includes("Acceptable options"), "No invented legacy importance or grouping");
  } else if (scenario === "results_legacy_support") {
    assert(selected().textContent.includes("Unspecified") && selected().textContent.includes("legacy"), "Missing match metadata is not borrowed from analysis");
    assert(record("java-record").textContent.includes("Per-record classification not recorded"), "No aggregate classification applied to a legacy record");
    assert(!evidence().textContent.includes("Matched option:"), "No inferred legacy matched options");
  } else if (scenario === "results_empty_structured") {
    assert(nodes["#overview"].textContent.includes("No job requirements"), "Empty authoritative structured list stays empty");
    assert(!nodes["#overview"].textContent.includes("Python"), "No fallback to conflicting legacy lists");
    assert(nodes["#requirement-list"].textContent.includes("No job requirements"), "Empty matching result explained");
  } else if (scenario === "results_empty_category") {
    const category = nodes["#overview"].children.find(row => row.children[0]?.textContent === "Qualifications");
    assert(category.textContent.includes("None identified"), "Empty category remains clear");
  } else if (scenario === "results_filters") {
    for (const [filter, count] of [["strong", 3], ["related", 1], ["missing", 3], ["all", 7]]) {
      await click(`filter-${filter}`); assert(rows().length === count, `Filter ${filter} only changes presentation`);
      assert(nodes[`#filter-${filter}`].attributes["aria-pressed"] === "true", "Filter selection exposed");
      assert(nodes["#requirement-count"].textContent === `${count} of 7 requirements`, "Honest filtered count");
    }
    assert(nodes["#match-groups"].textContent.includes("3 Strong matches"), "Summary stays bank-wide");
  } else if (scenario === "results_empty_filter") {
    await click("filter-related");
    assert(nodes["#requirement-list"].textContent.includes("No requirements classified as Related."), "Filter-specific empty state");
    assert(!evidence().textContent.includes(python.text), "Filtered-out selection and evidence are cleared");
  } else if (scenario === "results_selection") {
    nodes["#requirement-evidence"].scrollTop = 500;
    await choose(requirements[2].text);
    assert(nodes["#requirement-evidence"].scrollTop === 0, "A new selection starts at the evidence heading");
    same(record("api-record").children.find(row => row.className === "original-evidence-text").textContent, api.text, "Exact original contribution and whitespace");
    assert(evidence().textContent.includes("Project contribution · JobMatch"), "Recorded ownership retained");
    assert(!evidence().textContent.includes(python.text), "Inspector shows only selected requirement evidence");
  } else if (scenario === "results_alternative_provenance") {
    assert(record("python-record").textContent.includes("Matched option: Python") && record("python-record").textContent.includes("Strong support"), "Python record has its own strong option");
    assert(record("java-record").textContent.includes("Matched option: Java") && record("java-record").textContent.includes("Related support"), "Java record retains its own related option");
    assert(!record("java-record").textContent.includes("Matched option: Python"), "Best OR alternative is never copied to all evidence");
    assert(record("java-record").textContent.includes("Technology tag") && record("java-record").textContent.includes("practical activity is not established"), "Weak tag provenance and caveat retained");
  } else if (scenario === "results_caveats") {
    await choose(requirements[2].text);
    assert(evidence().textContent.includes("maintenance is not established"), "Unproven maintenance caveat preserved");
    assert(evidence().textContent.includes("api_development"), "Only recorded activity exposed");
    await choose(requirements[1].text);
    assert(evidence().textContent.includes("azure_ai_search → cloud_technologies · broader · high confidence"), "Directional relationship provenance retained");
    assert(!evidence().textContent.includes("Recorded demonstrated activity: cloud_deployment"), "Cloud technology is not promoted to deployment");
  } else if (scenario === "results_credentials") {
    await choose(requirements[1].text);
    assert(record("cert-record").textContent.includes("Certification · Cloud fundamentals certificate"), "Credential ownership visible");
    assert(record("cert-record").textContent.includes("Certification records knowledge, not demonstrated cloud deployment."), "Certification caveat is not engineering experience");
  } else if (scenario === "results_missing") {
    await choose(requirements[5].text);
    assert(selected().textContent.includes("Not evidenced") && selected().textContent.includes("Cloud deployment"), "Missing activity requirement stays missing");
    assert(evidence().textContent.includes("No supporting evidence was found"), "Absence of recorded support explained");
    assert(!all(evidence()).some(row => row.dataset.evidenceId), "No invented evidence or recommendations");
  } else if (scenario === "results_unknown_support") {
    assert(record("java-record").textContent.includes("Per-record classification not recorded"), "Missing provenance not upgraded from aggregate strong result");
    assert(record("java-record").textContent.includes("Matched option not recorded"), "Missing alternative stays unknown");
  } else if (scenario === "results_safe_text") {
    assert(nodes["#overview"].textContent.includes('<img src=x onerror="alert(1)">'), "Requirement text is literal");
    assert(evidence().textContent.includes("<script>alert('evidence')</script>") && evidence().textContent.includes("<b>literal caveat</b>"), "Evidence and caveats are literal");
    assert(!all(evidence()).some(row => ["script", "img", "svg"].includes(row.tagName)), "No executable elements created");
  } else if (["results_keyboard", "results_filtered_keyboard", "results_long_keyboard"].includes(scenario)) {
    if (scenario !== "results_keyboard") await click("filter-missing");
    const count = requests.length;
    const press = async key => { const row = rows().find(item => item.attributes["aria-pressed"] === "true"); for (const handler of row.listeners.keydown) handler({ key, preventDefault() {} }); };
    await press("ArrowDown"); assert(document.activeElement === rows()[1] && rows()[1].attributes["aria-pressed"] === "true", "Arrow moves focus and selection together");
    await press("End"); assert(document.activeElement === rows()[rows().length - 1], "End reaches final requirement");
    same(document.activeElement.scrollRequest, { block: "nearest", inline: "nearest" }, "Keyboard selection explicitly scrolls the chosen requirement into view");
    assert(nodes["#selected-requirement"].textContent.includes(document.activeElement.children[0].textContent), "The inspector follows the scrolled selection");
    await press("Home"); assert(document.activeElement === rows()[0], "Home reaches first requirement");
    await press("ArrowUp"); assert(document.activeElement === rows()[0], "Arrow boundary stays valid");
    assert(rows().every(row => row.type === "button" && row.attributes["aria-controls"] === "requirement-evidence"), "Native keyboard buttons control the named inspector");
    same(requests.length, count, "Keyboard scrolling and filtered selection make no API requests");
  } else if (scenario === "results_reset") {
    await click("filter-related"); await click("new-analysis");
    assert(rows().length === 0 && !evidence().textContent.includes(azure.text), "Reset clears cached evidence and requirement selection");
    assert(nodes["#filter-all"].attributes["aria-pressed"] === "true", "Reset restores default filter");
  } else if (scenario === "results_new_analysis") {
    await click("filter-related"); await analyse();
    assert(rows().length === 7 && nodes["#filter-all"].attributes["aria-pressed"] === "true", "New analysis resets filtering and selection");
    assert(record("python-record"), "Fresh result selects its own first requirement");
  } else if (scenario === "results_no_requests") {
    const count = requests.length;
    for (const filter of ["related", "missing", "all"]) await click(`filter-${filter}`);
    await choose(requirements[2].text); await click("continue-to-match"); await click("stage-analyse"); await click("stage-match");
    await click("show-bank"); await click("show-workspace");
    assert(requests.length === count, "Selection, filters and stage navigation use the existing snapshot only");
    assert(countRequests("/tailoring/preview") === 0, "No automatic preview generation");
  } else if (scenario === "results_preview") {
    await click("continue-to-match"); await click("filter-missing"); await click("match-generate-preview"); await settle();
    assert(countRequests("/tailoring/preview") === 1 && !nodes["#tailoring-output"].hidden, "Existing explicit preview integration works after filtering");
    same(requests.find(row => row.url === "/tailoring/preview").body, { job_analysis: analysisJSON }, "Unmodified analysis sent to preview");
  } else if (scenario === "results_all_requirements") {
    assert(analysisRows().length === 47 && rows().length === 47, "No truncated or dropped requirements");
    await click("filter-missing"); assert(rows().length === 43, "All independent missing requirements remain reachable");
  } else throw new Error(`Unknown results scenario ${scenario}`);
  same(JSON.stringify(analysisJSON), beforeAnalysis, "Analysis not mutated by presentation");
  same(JSON.stringify(previewJSON.matching_result), beforeMatches, "Classifications, provenance, scores and OR options not mutated");
}

run().then(() => print(`PASS ${scenario}`)).catch(error => { print(`${error.name}: ${error.message}\n${error.stack || ""}`); throw error; });
