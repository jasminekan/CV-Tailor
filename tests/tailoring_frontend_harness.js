// Execute the real scripts without a browser, network, persistence or personal data.
if (typeof print === "undefined") globalThis.print = console.log;
function assert(value, message) { if (!value) throw new Error(message); }
function same(actual, expected, message) { assert(JSON.stringify(actual) === JSON.stringify(expected), message); }
const copy = value => JSON.parse(JSON.stringify(value));
class Element {
  constructor(tag = "div") { this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = {}; this.value = ""; this.hidden = false; this.disabled = false; this._text = ""; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(" "); }
  set innerHTML(value) { throw new Error("Unsafe HTML assignment"); }
  append(...children) { children.forEach(child => { child.parent = this; this.children.push(child); }); }
  replaceChildren(...children) { this.children = []; this._text = ""; this.append(...children); }
  insertBefore(child, before) { child.parent = this; this.children.splice(this.children.indexOf(before), 0, child); }
  remove() { this.parent.children = this.parent.children.filter(child => child !== this); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  click() { for (const callback of this.listeners.click || []) callback({ preventDefault() {} }); }
  addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
  querySelectorAll(selector) { return all(this).filter(child => child.className?.split(" ").includes(selector.slice(1))); }
  focus() { this.focused = true; document.activeElement = this; }
}
const all = root => [root, ...root.children.flatMap(all)];
const nodes = Object.fromEntries(htmlIds.map(id => [`#${id}`, new Element()]));
nodes["#tailoring-preview"].hidden = true;
nodes["#tailoring-output"].hidden = true;
nodes["#analysis-result"].hidden = true;
nodes["#generate-tailored-preview"].disabled = true;
globalThis.document = {
  createElement: tag => new Element(tag),
  querySelector: selector => nodes[selector] || Object.values(nodes).flatMap(all).find(item =>
    selector === `#${item.id}` || selector === `[data-cv-focus="${item.dataset.cvFocus}"]`),
  querySelectorAll: selector => Object.values(nodes).flatMap(root => root.querySelectorAll(selector)),
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
  assert((method !== "PUT" || (allowCVSave && url === "/current-cv")) && method !== "PATCH" && method !== "DELETE", "No unintended frontend writes");
  const plan = plans[url]?.shift();
  if (plan) return plan;
  if (url === "/experience-bank" && method === "GET") return reply(200, editorBank);
  if (url === "/current-cv" && method === "GET") return reply(200, { current_cv: savedCV, reference_issues: [] });
  if (url === "/analyse") return reply(200, analysisJSON);
  if (url === "/match") return reply(200, previewJSON.matching_result);
  if (url === "/tailoring/preview") return reply(200, previewJSON);
  throw new Error(`Unexpected endpoint ${url}`);
};
const settle = async () => { for (let i = 0; i < 35; i++) await Promise.resolve(); };
async function fire(target, type) {
  for (const callback of target.listeners[type] || []) await callback({ preventDefault() {} });
}
const action = () => fire(nodes["#generate-tailored-preview"], "click");
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

// INSERT APPLICATION HERE

async function run() {
  await settle();
  assert(previewButton().disabled && nodes["#tailoring-preview"].hidden, "Preview unavailable without a successful analysis");
  if (scenario.startsWith("workspace_")) { await workspaceScenario(); return; }
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
      assert(findBy(content(), "tailoredBulletId", "testing").textContent.includes("Retained"), "Baseline membership label");
      assert(findBy(content(), "tailoredBulletId", "oracle").textContent.includes("Recommended"), "New bank content label");
      assert(!content().textContent.includes("Strong support"), "Selection indicator is not a match classification");
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

async function workspaceScenario() {
  const click = id => fire(nodes[`#${id}`], "click");
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
run().then(() => print(`PASS ${scenario}`)).catch(error => { print(error.stack || error.message); throw error; });
