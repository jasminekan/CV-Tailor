// Mock DOM/API behavior only: no browser, network, or user data access.
if (typeof print === "undefined") globalThis.print = console.log;
function assert(condition, message) { if (!condition) throw new Error(message); }
function same(actual, expected, message) {
  assert(JSON.stringify(actual) === JSON.stringify(expected), `${message}: ${JSON.stringify(actual)}`);
}
const copy = value => JSON.parse(JSON.stringify(value));
class MockElement {
  constructor(tag = "div") {
    this.tagName = tag;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
    this.value = "";
    this.disabled = false;
    this.hidden = false;
    this.inert = false;
    this._text = "";
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(" "); }
  set innerHTML(value) { throw new Error("Unsafe HTML rendering"); }
  append(...children) { children.forEach(child => { child.parentElement = this; this.children.push(child); }); }
  replaceChildren(...children) { this.children = []; this._text = ""; this.append(...children); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
  focus() { assert(!this.disabled, "Cannot focus a disabled control"); this.focused = true; document.activeElement = this; }
}
const ids = [
  ...shellIds,
  "current-cv-form", "current-cv-fields", "save-current-cv", "retry-current-cv",
  "current-cv-message", "current-cv-warnings", "show-workspace", "show-current-cv",
  "current-cv-state", "cv-add-work", "cv-add-project", "cv-work-list", "cv-project-list",
  "workspace-view", "current-cv-view", "current-cv-title",
  "cv-add-skill-group", "cv-skill-group-list", "cv-tailoring-settings", "cv-preview-content",
];
const nodes = Object.fromEntries(ids.map(id => [`#${id}`, new MockElement()]));
const all = root => [root, ...root.children.flatMap(all)];
globalThis.document = {
  createElement: tag => new MockElement(tag),
  querySelector: selector => nodes[selector] || Object.values(nodes).flatMap(all).find(node =>
    selector === `[data-cv-focus="${node.dataset.cvFocus}"]` || selector === `#${node.id}`),
};
globalThis.window = new MockElement();
globalThis.CustomEvent = class { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } };
window.dispatchEvent = event => { for (const listener of window.listeners[event.type] || []) listener(event); };
window.confirm = () => true;
async function fire(node, type) {
  const event = { prevented: false, preventDefault() { this.prevented = true; } };
  for (const callback of node.listeners[type] || []) await callback(event);
  return event;
}
const settle = async () => { for (let index = 0; index < 25; index++) await Promise.resolve(); };
const bankTemplate = {
  schema_version: 1, skills: ["Python"], education: [], certifications: [], additional_evidence: [],
  work_experience: [
    { id: "role-a", role: "Engineer", employer: "Example", achievements: [
      { id: "a1", text: "Original achievement one." }, { id: "a2", text: "Original achievement two." }, { id: "a3", text: "Third achievement." },
    ] },
    { id: "role-b", role: "Developer", employer: "Other", achievements: [{ id: "b1", text: "Other role bullet." }] },
    { id: "role-c", role: "Tester", employer: "Third", achievements: [] },
  ],
  projects: [
    { id: "project-a", name: "API project", evidence: [
      { id: "p1", text: "Original contribution one." }, { id: "p2", text: "Original contribution two." }, { id: "p3", text: "Third contribution." },
    ] },
    { id: "project-b", name: "Other project", evidence: [{ id: "q1", text: "Other project contribution." }] },
    { id: "project-c", name: "Empty project", evidence: [] },
  ],
};
const cvTemplate = {
  schema_version: 1,
  work_experience: [{ work_experience_id: "role-a", achievement_ids: ["a2", "a1"] }],
  projects: [{ project_id: "project-a", contribution_ids: ["p2", "p1"] }],
  skill_groups: [{ name: "  Languages  ", skill_keys: ["python"] }],
  tailoring_settings: { max_achievements_per_role: null, max_contributions_per_project: 3, max_projects: 0, max_skills: null },
};
let bankJSON = copy(bankTemplate);
let cvJSON = copy(cvTemplate);
let loadIssues = [];
let failBank = scenario === "failed_bank_load";
let failCV = scenario === "failed_cv_load";
let putStatus = 200;
let putDetails = null;
let resolvePut = null;
let deferPut = false;
let lastPut = null;
const requests = [];
if (["missing_placeholders", "replace_broken"].includes(scenario)) {
  cvJSON.work_experience[0].work_experience_id = "deleted-role";
  cvJSON.projects[0].contribution_ids = ["moved-contribution", "p1"];
  loadIssues = [
    { path: "work_experience[0].work_experience_id", reference: "deleted-role", reason: "Missing role." },
    { path: "projects[0].contribution_ids[0]", reference: "moved-contribution", reason: "Wrong parent." },
    { path: "skill_groups[0].skill_keys[0]", reference: "python", reason: "Skill unavailable." },
  ];
}
if (scenario === "safe_text") {
  bankJSON.work_experience[0].role = '<img src=x onerror="alert(1)">';
  bankJSON.work_experience[0].achievements[0].text = "<script>alert('bullet')</script>";
  bankJSON.projects[0].name = "<b>Project</b>";
}
if (scenario === "server_load_issues") {
  // GET /current-cv can observe a bank change after GET /experience-bank.
  loadIssues = [{ path: "work_experience[0].achievement_ids[1]", reference: "a1", reason: "Server detected moved achievement." }];
}
if (scenario === "replace_project") cvJSON.projects[0].project_id = "deleted-project";
if (scenario === "empty_defaults") {
  cvJSON.work_experience = [];
  cvJSON.projects = [];
}
if (scenario === "empty_bank") {
  bankJSON.work_experience = [];
  bankJSON.projects = [];
}
if (/^(groups_|skills_|settings_|phase5_|preview_|release_|polish_)/.test(scenario)) {
  bankJSON.skills = ["Python", "JavaScript", "C", "C++", "C#", "API\tDevelopment"];
}
if (["skills_replace_missing", "skills_remove_missing", "preview_missing"].includes(scenario)) {
  cvJSON.skill_groups[0].skill_keys = ["ghost", "python"];
  loadIssues = [{ path: "skill_groups[0].skill_keys[0]", reference: "ghost", reason: "Skill unavailable." }];
}
if (scenario === "preview_missing") {
  cvJSON.work_experience[0].work_experience_id = "deleted-role";
  cvJSON.projects[0].contribution_ids = ["missing-contribution", "p1"];
}
if (scenario === "preview_exact_text") {
  bankJSON.work_experience[0].achievements[0].text = "  Original <b>bullet</b>.\nSecond line & symbols.  ";
  bankJSON.projects[0].evidence[0].text = " Original contribution.\nSame wording. ";
}
if (scenario === "preview_education") {
  bankJSON.education = [
    { id: "edu-z", qualification: "BSc  Computer Science\n(Placement)", institution: "Example & University", field: "Computer Science", year: "2024" },
    { id: "edu-a", qualification: "Other qualification", institution: "Other institution", field: "", year: null },
  ];
  bankJSON.certifications = [
    { id: "cert-z", name: "<b>AWS Certificate</b>", issuer: "AWS & Co", year: "2025", skills: ["AWS"] },
    { id: "cert-a", name: "Other certificate", issuer: "", year: null, skills: [] },
  ];
}
if (scenario === "catalogue_contract") {
  bankJSON = copy(parityBank);
  cvJSON.work_experience = [];
  cvJSON.projects = [];
  cvJSON.skill_groups = [];
}
if (scenario === "settings_unsafe_loaded") cvJSON.tailoring_settings.max_skills = 9007199254740992;
function response(status, data) { return { ok: status < 400, json: async () => copy(data) }; }
globalThis.fetch = async (url, options = {}) => {
  const method = options.method || "GET";
  requests.push({ url, method });
  if (url === "/experience-bank") return failBank ? response(503, { detail: "Bank load failed." }) : response(200, bankJSON);
  if (method === "GET") return failCV ? response(503, { detail: "CV load failed." }) : response(200, { current_cv: cvJSON, reference_issues: loadIssues });
  lastPut = JSON.parse(options.body);
  if (deferPut) await new Promise(resolve => { resolvePut = resolve; });
  if (putStatus >= 400) return response(putStatus, { detail: putDetails });
  cvJSON = copy(lastPut);
  return response(200, cvJSON);
};

// INSERT BUILDER HERE

function card(id) {
  return [...all(nodes["#cv-work-list"]), ...all(nodes["#cv-project-list"])].find(node => node.dataset.parentId === id);
}
function bullet(id) { return [...all(nodes["#cv-work-list"]), ...all(nodes["#cv-project-list"])].find(node => node.dataset.bulletId === id); }
function options(select) { return select.children.filter(node => node.tagName === "option").map(node => node.value); }
function pickerRow(root, text) { return all(root).find(node => node.className === "cv-picker" && node.children.some(child => child.tagName === "button" && child.textContent === text)); }
async function choose(root, text, id) {
  const row = pickerRow(root, text);
  assert(row, `Missing picker ${text}`);
  row.children[0].value = id;
  await fire(row.children[0], "change");
  await fire(row.children[1], "click");
}
async function control(root, text) {
  const node = all(root).find(node => node.tagName === "button" && (node.textContent === text || node.attributes["aria-label"]?.startsWith(`${text} `)));
  assert(node, `Missing control ${text}`);
  await fire(node, "click");
}
const parentOrder = selector => nodes[selector].children.filter(node => node.tagName === "article").map(node => node.dataset.parentId);
const bulletOrder = id => all(card(id)).filter(node => node.dataset.bulletId).map(node => node.dataset.bulletId);
async function submit() { await fire(nodes["#current-cv-form"], "submit"); }
async function start() {
  await fire(nodes["#show-current-cv"], "click");
  await settle();
}
function group(index) { return nodes["#cv-skill-group-list"].children.find(node => node.dataset.groupIndex === String(index)); }
function skill(index, key) { return all(group(index)).find(node => node.dataset.skillKey === key); }
const skillOrder = index => all(group(index)).filter(node => node.dataset.skillKey).map(node => node.dataset.skillKey);
const groupNames = () => nodes["#cv-skill-group-list"].children.filter(node => node.tagName === "article").map(node => node.children[0].textContent);
function previewSection(key) { return all(nodes["#cv-preview-content"]).find(node => node.dataset.previewSection === key); }
const previewBullets = section => all(previewSection(section)).filter(node => node.dataset.previewBulletId).map(node => node.textContent);
async function addGroup(name) {
  all(nodes["#cv-add-skill-group"]).find(node => node.tagName === "input").value = name;
  await control(nodes["#cv-add-skill-group"], "Add Skills Group");
}
async function renameGroup(index, name) {
  const input = document.querySelector(`#cv-group-heading-${index}`);
  input.value = name;
  await fire(input, "input");
}
async function editLimit(key, value, badInput = false) {
  const input = document.querySelector(`#cv-setting-${key}`);
  input.value = value;
  input.validity = { badInput };
  await fire(input, "input");
}
async function run() {
  assert(nodes["#save-current-cv"].disabled, "Save starts disabled");
  await start();
  switch (scenario) {
    case "navigation":
      assert(nodes["#workspace-view"].hidden && !nodes["#current-cv-view"].hidden, "CV navigation");
      assert(!nodes["#save-current-cv"].disabled, "Both loads enable saving");
      assert(nodes["#show-current-cv"].attributes["aria-pressed"] === "true", "Selected navigation exposed");
      await fire(nodes["#show-workspace"], "click");
      assert(!nodes["#workspace-view"].hidden && nodes["#current-cv-view"].hidden, "Workspace preserved");
      break;
    case "parent_dropdowns":
      same(options(pickerRow(nodes["#cv-add-work"], "Add Experience").children[0]), ["", "role-b", "role-c"], "Selected roles excluded");
      same(options(pickerRow(nodes["#cv-add-project"], "Add Project").children[0]), ["", "project-b", "project-c"], "Selected projects excluded");
      break;
    case "bullet_dropdowns":
      same(options(pickerRow(card("role-a"), "Add Bullet Point").children[0]), ["", "a3"], "Only unselected bullets from role");
      same(options(pickerRow(card("project-a"), "Add Contribution").children[0]), ["", "p3"], "Only unselected contributions from project");
      same(options(all(bullet("a2")).find(node => node.tagName === "select")), ["", "a2", "a3"], "Replacement excludes sibling selection");
      break;
    case "duplicates": {
      await choose(nodes["#cv-add-work"], "Add Experience", "role-a");
      await choose(nodes["#cv-add-project"], "Add Project", "project-a");
      await choose(card("role-a"), "Add Bullet Point", "a1");
      await choose(card("project-a"), "Add Contribution", "p1");
      const selected = all(bullet("a2")).find(node => node.tagName === "select");
      selected.value = "a1";
      await fire(selected, "change");
      same(parentOrder("#cv-work-list"), ["role-a"], "Duplicate role rejected");
      same(bulletOrder("role-a"), ["a2", "a1"], "Duplicate bullet rejected");
      same(parentOrder("#cv-project-list"), ["project-a"], "Duplicate project rejected");
      same(bulletOrder("project-a"), ["p2", "p1"], "Duplicate contribution rejected");
      break;
    }
    case "add_remove_reorder":
      for (const [target, parent, other, addParent, addBullet, extra, removeParent, removeBullet, selector] of [
        ["#cv-add-work", "role-a", "role-b", "Add Experience", "Add Bullet Point", "a3", "Remove experience", "Remove bullet point", "#cv-work-list"],
        ["#cv-add-project", "project-a", "project-b", "Add Project", "Add Contribution", "p3", "Remove project", "Remove contribution", "#cv-project-list"],
      ]) {
        assert(all(card(parent)).find(node => node.textContent === "Move Up").disabled, "First move-up disabled");
        await choose(nodes[target], addParent, other);
        await control(card(other), "Move Up");
        same(parentOrder(selector), [other, parent], "Parent order changes");
        assert(document.activeElement.textContent === "Move Down", "Focus follows moved parent to an enabled control");
        await control(card(other), "Move Down");
        same(parentOrder(selector), [parent, other], "Parent moves back down");
        await choose(card(parent), addBullet, extra);
        await control(bullet(extra), "Move Up");
        assert(bulletOrder(parent)[1] === extra, "Bullet reordered");
        await control(bullet(extra), "Move Down");
        assert(bulletOrder(parent)[2] === extra, "Bullet moved back down");
        await control(bullet(extra), removeBullet);
        assert(!bulletOrder(parent).includes(extra), "Bullet removed");
        await control(card(other), removeParent);
        same(parentOrder(selector), [parent], "Parent removed");
      }
      assert(nodes["#current-cv-state"].textContent === "Saved", "Returning to baseline is clean");
      break;
    case "round_trip":
      await control(bullet("a1"), "Move Up");
      await control(bullet("p1"), "Move Up");
      assert(nodes["#current-cv-state"].textContent === "Unsaved changes", "Dirty state");
      await submit();
      same(lastPut.work_experience[0].achievement_ids, ["a1", "a2"], "Saved achievement order");
      same(lastPut.projects[0].contribution_ids, ["p1", "p2"], "Saved contribution order");
      same(lastPut.skill_groups, cvTemplate.skill_groups, "Skills preserved exactly");
      same(lastPut.tailoring_settings, cvTemplate.tailoring_settings, "Settings preserved exactly");
      assert(!JSON.stringify(lastPut).includes("Original achievement"), "No copied text");
      assert(nodes["#current-cv-state"].textContent === "Saved", "Baseline updated");
      break;
    case "missing_placeholders":
      same(parentOrder("#cv-work-list"), ["deleted-role"], "Missing parent preserved");
      same(bulletOrder("deleted-role"), ["a2", "a1"], "Missing parent's bullets preserved");
      same(bulletOrder("project-a"), ["moved-contribution", "p1"], "Moved contribution preserved");
      assert(card("deleted-role").textContent.includes("Unavailable experience"), "Missing parent label");
      assert(bullet("moved-contribution").textContent.includes("Unavailable contribution"), "Missing bullet label");
      assert(!nodes["#current-cv-warnings"].hidden, "Warnings visible");
      assert(nodes["#current-cv-warnings"].textContent.includes("Skill unavailable"), "Server skill issue preserved");
      break;
    case "replace_broken": {
      await choose(card("deleted-role"), "Replace experience and clear bullets", "role-b");
      same(parentOrder("#cv-work-list"), ["role-b"], "Parent replaced in place");
      same(bulletOrder("role-b"), [], "Explicit replacement clears old bullets");
      const select = all(bullet("moved-contribution")).find(node => node.tagName === "select");
      select.value = "p2";
      await fire(select, "change");
      same(bulletOrder("project-a"), ["p2", "p1"], "Broken bullet replaced in place");
      await submit();
      same(lastPut.skill_groups, cvTemplate.skill_groups, "Broken recovery preserves other sections");
      break;
    }
    case "failed_cv_load":
      assert(nodes["#save-current-cv"].disabled && nodes["#current-cv-fields"].disabled, "CV load failure blocks editing/saving");
      await submit();
      assert(lastPut === null, "No overwrite after failed load");
      failCV = false;
      await fire(nodes["#retry-current-cv"], "click");
      await settle();
      same(parentOrder("#cv-work-list"), ["role-a"], "Retry loads actual selections");
      break;
    case "failed_bank_load":
      assert(nodes["#save-current-cv"].disabled, "Bank load failure blocks saving");
      same(parentOrder("#cv-work-list"), ["role-a"], "Successfully loaded CV kept");
      await submit();
      assert(lastPut === null, "Incomplete load cannot save");
      failBank = false;
      await fire(nodes["#retry-current-cv"], "click");
      await settle();
      await submit();
      same(lastPut, cvTemplate, "Retry preserves loaded CV including hidden sections");
      break;
    case "failed_save":
      await control(bullet("a1"), "Move Up");
      putStatus = 422;
      putDetails = [{ path: "work_experience[0].achievement_ids[0]", reference: "a1", reason: "Achievement was removed." }];
      await submit();
      same(bulletOrder("role-a"), ["a1", "a2"], "Failed save keeps draft order");
      assert(nodes["#current-cv-state"].textContent === "Unsaved changes", "Failed save keeps dirty baseline");
      assert(nodes["#current-cv-message"].textContent.includes("Achievement was removed"), "Reference errors readable");
      assert(!nodes["#save-current-cv"].disabled, "Retry enabled");
      putStatus = 503;
      putDetails = "The Current CV could not be saved.";
      await submit();
      assert(nodes["#current-cv-message"].textContent.includes("could not be saved"), "503 displayed without losing draft");
      break;
    case "structural_error":
      putStatus = 422;
      putDetails = [{ loc: ["body", "projects", 0, "project_id"], msg: "Field required" }];
      await submit();
      assert(nodes["#current-cv-message"].textContent.includes("Project 1: Field required"), "Structural errors readable");
      assert(!nodes["#current-cv-message"].textContent.includes("[object Object]"), "No object stringification");
      break;
    case "fresh_bank":
      await control(bullet("a1"), "Move Up");
      bankJSON.work_experience[0].achievements = bankJSON.work_experience[0].achievements.filter(item => item.id !== "a1");
      putStatus = 422;
      putDetails = [{ path: "work_experience[0].achievement_ids[0]", reference: "a1", reason: "Missing achievement." }];
      await submit();
      same(requests.slice(-2), [{ url: "/experience-bank", method: "GET" }, { url: "/current-cv", method: "PUT" }], "Refresh before server validation");
      assert(bullet("a1").textContent.includes("Unavailable"), "Latest bank used for placeholder");
      same(lastPut.work_experience[0].achievement_ids, ["a1", "a2"], "Invalid selections are not silently stripped");
      failBank = true;
      const count = requests.filter(request => request.method === "PUT").length;
      await submit();
      assert(nodes["#save-current-cv"].disabled, "Failed refresh blocks saving");
      assert(requests.filter(request => request.method === "PUT").length === count, "No PUT after failed refresh");
      same(bulletOrder("role-a"), ["a1", "a2"], "Failed refresh keeps changes");
      break;
    case "saving_lock": {
      deferPut = true;
      const pending = submit();
      await settle();
      assert(resolvePut, "Save in flight");
      assert(nodes["#current-cv-fields"].disabled && nodes["#save-current-cv"].disabled && nodes["#current-cv-form"].inert, "Editing locked");
      assert(nodes["#show-workspace"].disabled, "Cannot switch to bank during save");
      await control(bullet("a1"), "Move Up");
      same(bulletOrder("role-a"), ["a2", "a1"], "In-flight mutation ignored");
      await submit();
      assert(requests.filter(request => request.method === "PUT").length === 1, "No duplicate submission");
      resolvePut();
      await pending;
      assert(!nodes["#current-cv-fields"].disabled && !nodes["#current-cv-form"].inert, "Editing restored");
      break;
    }
    case "refresh_preserves_draft":
      await control(bullet("a1"), "Move Up");
      failBank = true;
      await fire(nodes["#show-workspace"], "click");
      await start();
      same(bulletOrder("role-a"), ["a1", "a2"], "Refresh failure does not reset draft");
      assert(nodes["#save-current-cv"].disabled, "Refresh failure disables saving");
      failBank = false;
      await fire(nodes["#retry-current-cv"], "click");
      await settle();
      same(bulletOrder("role-a"), ["a1", "a2"], "Retry preserves edits");
      assert(requests.filter(request => request.url === "/current-cv" && request.method === "GET").length === 1, "Draft not reloaded");
      break;
    case "bank_saved_event":
      await control(bullet("a1"), "Move Up");
      bankJSON.work_experience[0].achievements[0].text = "Changed bank wording.";
      for (const listener of window.listeners["experience-bank-saved"]) listener({ detail: bankJSON });
      assert(bullet("a1").textContent.includes("Changed bank wording"), "New wording resolved from saved bank");
      same(bulletOrder("role-a"), ["a1", "a2"], "Bank save keeps draft order");
      await submit();
      assert(!JSON.stringify(lastPut).includes("Changed bank wording"), "No text copied into CV");
      break;
    case "beforeunload":
      assert(!(await fire(window, "beforeunload")).prevented, "Clean draft has no warning");
      await control(bullet("a1"), "Move Up");
      assert((await fire(window, "beforeunload")).prevented, "Dirty draft warns");
      break;
    case "safe_text":
      assert(card("role-a").textContent.includes("<img"), "Role rendered as literal text");
      assert(bullet("a1").textContent.includes("<script>"), "Bullet rendered as literal text");
      assert(card("project-a").textContent.includes("<b>Project</b>"), "Project rendered as literal text");
      assert(!Object.values(nodes).flatMap(all).some(node => ["script", "img", "textarea"].includes(node.tagName)), "No bank markup or text editing controls");
      break;
    case "server_load_issues":
      assert(!nodes["#current-cv-warnings"].hidden, "Server issues shown even if bank snapshot differs");
      assert(nodes["#current-cv-warnings"].textContent.includes("Server detected moved achievement"), "Server reason retained");
      same(bulletOrder("role-a"), ["a2", "a1"], "Server issues never drop bullets");
      break;
    case "replace_project":
      await choose(card("deleted-project"), "Replace project and clear bullets", "project-b");
      same(parentOrder("#cv-project-list"), ["project-b"], "Missing project replaced in place");
      same(bulletOrder("project-b"), [], "Explicit project replacement clears old contributions");
      await choose(card("project-b"), "Add Contribution", "q1");
      await submit();
      same(lastPut.projects, [{ project_id: "project-b", contribution_ids: ["q1"] }], "New project references saved");
      break;
    case "empty_defaults":
      same(parentOrder("#cv-work-list"), [], "Empty work allowed");
      same(parentOrder("#cv-project-list"), [], "Empty projects allowed");
      await choose(nodes["#cv-add-work"], "Add Experience", "role-c");
      await choose(nodes["#cv-add-project"], "Add Project", "project-c");
      await submit();
      same(lastPut.work_experience, [{ work_experience_id: "role-c", achievement_ids: [] }], "Role without bullets allowed");
      same(lastPut.projects, [{ project_id: "project-c", contribution_ids: [] }], "Project without contributions allowed");
      break;
    case "empty_bank":
      same(parentOrder("#cv-work-list"), ["role-a"], "Empty bank does not strip saved roles");
      assert(pickerRow(nodes["#cv-add-work"], "Add Experience").children[0].disabled, "No role options disabled");
      assert(pickerRow(nodes["#cv-add-project"], "Add Project").children[0].disabled, "No project options disabled");
      break;
    case "groups_actions":
      await addGroup("Backend");
      await addGroup("Cloud");
      same(groupNames(), ["  Languages  ", "Backend", "Cloud"], "Groups added in order");
      await renameGroup(1, "  Backend Tools  ");
      same(groupNames(), ["  Languages  ", "  Backend Tools  ", "Cloud"], "Rename preserves heading spelling");
      assert(previewSection("skill_groups").textContent.includes("  Backend Tools  "), "Preview follows heading typing");
      await control(group(2), "Move Up");
      same(groupNames(), ["  Languages  ", "Cloud", "  Backend Tools  "], "Groups reorder up");
      await control(group(1), "Move Down");
      await control(group(1), "Remove Group");
      same(groupNames(), ["  Languages  ", "Cloud"], "Group removal");
      await submit();
      same(lastPut.skill_groups, [{ name: "  Languages  ", skill_keys: ["python"] }, { name: "Cloud", skill_keys: [] }], "Group order and empty groups persist");
      break;
    case "groups_validation":
      await addGroup(" \t ");
      await addGroup("languages");
      same(groupNames(), ["  Languages  "], "Blank and duplicate groups rejected");
      await addGroup("Backend");
      await renameGroup(1, "LANGUAGES");
      assert(nodes["#save-current-cv"].disabled, "Duplicate renamed heading blocks save");
      await submit();
      assert(lastPut === null, "Invalid heading cannot be submitted");
      await renameGroup(1, "\t");
      assert(nodes["#current-cv-warnings"].textContent.includes("nonblank"), "Blank heading warning");
      assert(document.querySelector("#cv-group-heading-1").attributes["aria-invalid"] === "true", "Invalid input marked");
      await renameGroup(1, "Backend");
      assert(!nodes["#save-current-cv"].disabled, "Corrected heading enables save");
      break;
    case "skills_actions":
      await choose(group(0), "Add Skill", "c++");
      await choose(group(0), "Add Skill", "c#");
      same(skillOrder(0), ["python", "c++", "c#"], "Skill order on add");
      assert(skill(0, "c++").children[0].textContent === "C++", "Human label shown instead of key");
      await control(skill(0, "c#"), "Move Up");
      same(skillOrder(0), ["python", "c#", "c++"], "Skill moves up");
      await control(skill(0, "c#"), "Move Down");
      await control(skill(0, "c++"), "Remove Skill");
      same(skillOrder(0), ["python", "c#"], "Skill removed");
      await submit();
      same(lastPut.skill_groups[0].skill_keys, ["python", "c#"], "Skill order persists");
      same(lastPut.work_experience, cvTemplate.work_experience, "Skills do not change work");
      same(lastPut.projects, cvTemplate.projects, "Skills do not change projects");
      break;
    case "skills_duplicates": {
      await addGroup("Backend");
      assert(!options(pickerRow(group(1), "Add Skill").children[0]).includes("python"), "Other group's skill excluded");
      await choose(group(1), "Add Skill", "python");
      same(skillOrder(1), [], "Duplicate add rejected");
      await choose(group(1), "Add Skill", "c++");
      const replacement = all(skill(1, "c++")).find(node => node.tagName === "select");
      assert(!options(replacement).includes("python"), "Other group's skill excluded from replacements");
      replacement.value = "python";
      await fire(replacement, "change");
      same(skillOrder(1), ["c++"], "Duplicate replacement rejected");
      await control(skill(0, "python"), "Remove Skill");
      await choose(group(1), "Add Skill", "python");
      same(skillOrder(1), ["c++", "python"], "Removed skill can move into another group");
      break;
    }
    case "skills_replace_missing": {
      assert(skill(0, "ghost").textContent.includes("Unavailable skill"), "Missing skill placeholder");
      assert(!nodes["#current-cv-warnings"].hidden, "Missing skill warning");
      const replacement = all(skill(0, "ghost")).find(node => node.tagName === "select");
      replacement.value = "javascript";
      await fire(replacement, "change");
      same(skillOrder(0), ["javascript", "python"], "Unavailable skill replaced in place");
      assert(nodes["#current-cv-warnings"].hidden, "Resolved skill warning removed");
      await submit();
      same(lastPut.skill_groups[0].skill_keys, ["javascript", "python"], "Recovery persisted");
      break;
    }
    case "skills_remove_missing":
      await control(skill(0, "ghost"), "Remove Skill");
      same(skillOrder(0), ["python"], "Unavailable skill removed explicitly");
      assert(nodes["#current-cv-warnings"].hidden, "Removed skill warning cleared");
      await submit();
      same(lastPut.skill_groups[0].skill_keys, ["python"], "Removal persisted");
      break;
    case "settings_values": {
      const beforePreview = nodes["#cv-preview-content"].textContent;
      await editLimit("max_achievements_per_role", "0");
      await editLimit("max_contributions_per_project", "5");
      await editLimit("max_projects", "");
      await editLimit("max_skills", "12");
      same(bulletOrder("role-a"), ["a2", "a1"], "Zero does not truncate manual bullets");
      same(nodes["#cv-preview-content"].textContent, beforePreview, "Limits do not change preview");
      await submit();
      same(lastPut.tailoring_settings, { max_achievements_per_role: 0, max_contributions_per_project: 5, max_projects: null, max_skills: 12 }, "Settings saved as integers/null");
      assert(document.querySelector("#cv-setting-max_projects").value === "", "Null displays as no limit");
      assert(document.querySelector("#cv-setting-max_skills").value === "12", "Stored number reloads into control");
      break;
    }
    case "settings_invalid":
      for (const invalid of ["-1", "1.5", "1e3", "NaN", "9007199254740992"]) {
        await editLimit("max_skills", invalid);
        assert(nodes["#save-current-cv"].disabled, `Invalid ${invalid} blocks save`);
        assert(nodes["#current-cv-state"].textContent === "Unsaved changes", "Invalid edits marked dirty");
        await submit();
        assert(lastPut === null, "Invalid limit never submitted");
      }
      await addGroup("Backend");
      assert(document.querySelector("#cv-setting-max_skills").value === "9007199254740992", "Invalid raw value kept through rerender");
      await editLimit("max_skills", "");
      assert(!nodes["#save-current-cv"].disabled, "Cleared limit recovers");
      await submit();
      assert(lastPut.tailoring_settings.max_skills === null, "Cleared limit saved as null");
      break;
    case "settings_bad_input":
      await editLimit("max_skills", "", true);
      assert(nodes["#save-current-cv"].disabled, "Native incomplete number not silently treated as null");
      await submit();
      assert(lastPut === null, "Bad input does not save old value or null");
      await editLimit("max_skills", "0");
      await submit();
      assert(lastPut.tailoring_settings.max_skills === 0, "Correction persists");
      break;
    case "settings_unsafe_loaded":
      assert(nodes["#save-current-cv"].disabled, "Unsafe imported limit blocks silent resave");
      assert(document.querySelector("#cv-setting-max_skills").attributes["aria-invalid"] === "true", "Imported limit marked invalid");
      await submit();
      assert(lastPut === null, "Unsafe imported limit never saved implicitly");
      await editLimit("max_skills", "12");
      await submit();
      assert(lastPut.tailoring_settings.max_skills === 12, "Explicit correction allows saving");
      break;
    case "phase5_failed_save":
      await renameGroup(0, "Programming");
      await choose(group(0), "Add Skill", "c#");
      await editLimit("max_skills", "4");
      putStatus = 503;
      putDetails = "The Current CV could not be saved.";
      await submit();
      same(groupNames(), ["Programming"], "Failed save preserves heading");
      same(skillOrder(0), ["python", "c#"], "Failed save preserves skills");
      assert(document.querySelector("#cv-setting-max_skills").value === "4", "Failed save preserves setting");
      assert(nodes["#current-cv-state"].textContent === "Unsaved changes", "Failed save retains dirty baseline");
      putStatus = 200;
      await submit();
      assert(nodes["#current-cv-state"].textContent === "Saved", "Retry updates baseline");
      break;
    case "preview_order":
      await choose(nodes["#cv-add-work"], "Add Experience", "role-b");
      await choose(card("role-b"), "Add Bullet Point", "b1");
      await control(card("role-b"), "Move Up");
      await control(bullet("a1"), "Move Up");
      await choose(nodes["#cv-add-project"], "Add Project", "project-b");
      await choose(card("project-b"), "Add Contribution", "q1");
      await control(card("project-b"), "Move Up");
      await control(bullet("p1"), "Move Up");
      same(previewBullets("work_experience"), ["Other role bullet.", "Original achievement one.", "Original achievement two."], "Work preview follows role and bullet order");
      same(previewBullets("projects"), ["Other project contribution.", "Original contribution one.", "Original contribution two."], "Project preview follows order");
      await addGroup("Tools");
      await choose(group(1), "Add Skill", "c++");
      await control(group(1), "Move Up");
      same(all(previewSection("skill_groups")).filter(node => node.tagName === "h4").map(node => node.textContent), ["Tools", "  Languages  "], "Preview follows group order");
      break;
    case "preview_exact_text":
      assert(previewBullets("work_experience")[1] === bankJSON.work_experience[0].achievements[0].text, "Exact work text including whitespace and markup");
      assert(previewBullets("projects")[1] === bankJSON.projects[0].evidence[0].text, "Exact project text including whitespace");
      await submit();
      same(lastPut.work_experience, cvTemplate.work_experience, "Only work references saved");
      same(lastPut.projects, cvTemplate.projects, "Only project references saved");
      assert(!JSON.stringify(lastPut).includes("Second line"), "Preview text never copied into document");
      break;
    case "preview_education":
      same(all(previewSection("education")).filter(node => node.tagName === "h4").map(node => node.textContent), bankJSON.education.map(record => record.qualification), "All education in bank order, unchanged");
      same(all(previewSection("certifications")).filter(node => node.tagName === "h4").map(node => node.textContent), bankJSON.certifications.map(record => record.name), "All certifications in bank order, unchanged");
      assert(previewSection("education").textContent.includes("Example & University"), "Institution included");
      assert(previewSection("certifications").textContent.includes("AWS & Co"), "Issuer included");
      assert(!all(nodes["#cv-preview-content"]).some(node => ["button", "input", "select", "textarea"].includes(node.tagName)), "Preview is read-only");
      await submit();
      assert(!("education" in lastPut) && !("certifications" in lastPut), "Education/certifications stay bank sourced");
      break;
    case "preview_missing":
      assert(previewSection("skill_groups").textContent.includes("Unavailable skill (ghost)"), "Preview missing skill placeholder");
      assert(previewSection("work_experience").textContent.includes("Unavailable experience (deleted-role)"), "Preview missing role placeholder");
      assert(previewSection("projects").textContent.includes("Unavailable contribution (missing-contribution)"), "Preview missing contribution placeholder");
      same(skillOrder(0), ["ghost", "python"], "Preview does not strip invalid keys");
      break;
    case "phase5_saving_lock": {
      await editLimit("max_skills", "4");
      deferPut = true;
      const pending = submit();
      await settle();
      await renameGroup(0, "Ignored heading");
      await editLimit("max_skills", "99");
      await addGroup("Ignored group");
      await choose(group(0), "Add Skill", "c#");
      resolvePut();
      await pending;
      same(lastPut.skill_groups, cvTemplate.skill_groups, "Skills edits ignored during save");
      assert(lastPut.tailoring_settings.max_skills === 4, "Setting edits ignored during save");
      break;
    }
    case "skills_bank_refresh":
      await renameGroup(0, "Programming");
      bankJSON.skills = bankJSON.skills.filter(label => label !== "Python");
      for (const listener of window.listeners["experience-bank-saved"]) listener({ detail: bankJSON });
      assert(skill(0, "python").textContent.includes("Unavailable"), "Deleted skill stays selected with warning");
      assert(previewSection("skill_groups").textContent.includes("Unavailable skill"), "Preview reflects bank change");
      same(groupNames(), ["Programming"], "Bank refresh preserves heading draft");
      bankJSON.skills.push("PYTHON");
      for (const listener of window.listeners["experience-bank-saved"]) listener({ detail: bankJSON });
      assert(skill(0, "python").children[0].textContent === "PYTHON", "Bank label updates without changing key");
      assert(nodes["#current-cv-warnings"].hidden, "Restored key clears warning");
      break;
    case "phase5_edit_isolation":
      await renameGroup(0, "Programming");
      await choose(group(0), "Add Skill", "c++");
      await editLimit("max_skills", "8");
      await control(bullet("a1"), "Move Up");
      await submit();
      same(lastPut.skill_groups, [{ name: "Programming", skill_keys: ["python", "c++"] }], "Work edit preserves skill changes");
      assert(lastPut.tailoring_settings.max_skills === 8, "Work edit preserves setting changes");
      same(lastPut.projects, cvTemplate.projects, "Unrelated projects preserved");
      break;
    case "catalogue_contract": {
      await addGroup("All Skills");
      const select = pickerRow(group(0), "Add Skill").children[0];
      same(select.children.filter(node => node.tagName === "option" && node.value).map(node => [node.value, node.textContent]), expectedSkills, "Catalogue matches Python backend exactly");
      break;
    }
    case "phase5_reload": {
      await renameGroup(0, "Programming");
      await choose(group(0), "Add Skill", "c++");
      await control(skill(0, "c++"), "Move Up");
      await addGroup("Tools");
      await choose(group(1), "Add Skill", "api development");
      await control(group(1), "Move Up");
      await editLimit("max_projects", "");
      await editLimit("max_skills", "12");
      await submit();
      const saved = copy(lastPut);
      // Recreate DOM and controller state, retaining only the mock server's CV.
      Object.keys(nodes).forEach(selector => { nodes[selector] = new MockElement(); });
      window.listeners = {};
      recreateBuilder();
      await start();
      same(groupNames(), saved.skill_groups.map(item => item.name), "Group order reloads from GET");
      same(skillOrder(0), ["api development"], "First group's skills reload");
      same(skillOrder(1), ["c++", "python"], "Nested skill order reloads");
      assert(document.querySelector("#cv-setting-max_projects").value === "", "Null reloads as blank");
      assert(document.querySelector("#cv-setting-max_skills").value === "12", "Numeric setting reloads");
      assert(nodes["#current-cv-state"].textContent === "Saved", "Reload starts with saved baseline");
      await submit();
      same(lastPut, saved, "Reload/resave preserves the complete document");
      break;
    }
    case "release_round_trip":
      await addGroup("Tools");
      await choose(group(1), "Add Skill", "c++");
      await choose(group(1), "Add Skill", "c#");
      await control(skill(1, "c#"), "Move Up");
      await control(group(1), "Move Up");
      await control(bullet("a1"), "Move Up");
      await control(bullet("p1"), "Move Up");
      await editLimit("max_skills", "4");
      await submit();
      print(`DOCUMENT ${JSON.stringify(lastPut)}`);
      print(`BANK ${JSON.stringify(bankJSON)}`);
      break;
    case "polish_compact_rows": {
      for (const id of ["a2", "a1", "p2", "p1"]) {
        const row = bullet(id);
        const actions = all(row).find(node => node.className === "cv-item-actions");
        const change = all(actions).find(node => node.tagName === "details");
        assert(actions && change.children[0].textContent === "Change" && !change.open, "Compact actions include a closed, labelled Change disclosure");
        const controls = all(actions).filter(node => node.tagName === "button");
        same(controls.map(node => node.textContent), ["↑", "↓", "Remove"], "Compact actions replace repetitive long button labels");
        assert(controls.every(node => node.attributes["aria-label"]), "All compact actions have accessible names");
        assert(controls[0].attributes["aria-label"].startsWith("Move Up ") && controls[1].attributes["aria-label"].startsWith("Move Down "), "Arrow controls communicate direction and context");
        assert(controls[2].attributes["aria-label"].includes("bank record is kept"), "Removal is a CV selection action");
        const original = bankJSON.work_experience.flatMap(record => record.achievements).concat(bankJSON.projects.flatMap(record => record.evidence)).find(item => item.id === id);
        same(row.children[0].textContent, original.text, "The complete original bullet remains prominent");
        change.open = true; change.open = false;
      }
      assert(nodes["#current-cv-state"].textContent === "Saved" && !requests.some(item => item.method === "PUT"), "Opening/closing Change does not edit or save the CV");
      break;
    }
    case "polish_change_references": {
      const originalBank = JSON.stringify(bankJSON);
      for (const [oldId, newId] of [["a2", "a3"], ["p2", "p3"]]) {
        const select = all(bullet(oldId)).find(node => node.tagName === "select");
        select.parentElement.open = true;
        select.value = newId; await fire(select, "change");
        assert(!bullet(oldId) && bullet(newId), "Change updates the selected reference");
        assert(document.activeElement.value === newId && document.activeElement.parentElement.open, "Focus follows the rebuilt Change control");
      }
      same(bulletOrder("role-a"), ["a3", "a1"], "Work ownership and order preserved");
      same(bulletOrder("project-a"), ["p3", "p1"], "Project ownership and order preserved");
      assert(nodes["#current-cv-state"].textContent === "Unsaved changes" && !lastPut, "Changes stay in the independent draft");
      await submit();
      same(lastPut.work_experience[0].achievement_ids, ["a3", "a1"], "Explicit save persists the replacement IDs");
      same(lastPut.projects[0].contribution_ids, ["p3", "p1"], "Contribution IDs use the existing contract");
      same(JSON.stringify(bankJSON), originalBank, "Changing or saving selections never modifies bank wording or IDs");
      assert(nodes["#current-cv-state"].textContent === "Saved", "Explicit save restores the saved state");
      break;
    }
    case "polish_reorder_focus": {
      await control(bullet("a1"), "Move Up");
      same(bulletOrder("role-a"), ["a1", "a2"], "Compact arrow reorders the same references");
      assert(document.activeElement.textContent === "↓" && document.activeElement.attributes["aria-label"].startsWith("Move Down "), "Focus follows the moved item to its enabled control");
      await control(bullet("a1"), "Remove bullet point");
      assert(document.activeElement === nodes["#cv-work-title"] && !bullet("a1"), "Compact Remove preserves focus recovery");
      assert(bankJSON.work_experience[0].achievements.some(item => item.id === "a1"), "Removing a selection keeps its source record");
      break;
    }
    case "polish_skill_actions": {
      await choose(group(0), "Add Skill", "javascript");
      const row = skill(0, "javascript");
      const actions = all(row).find(node => node.className === "cv-item-actions");
      assert(actions && all(actions).some(node => node.textContent === "↑"), "Skills share compact selection controls");
      await control(row, "Move Up"); same(skillOrder(0), ["javascript", "python"], "Skill reorder preserved");
      const select = all(skill(0, "javascript")).find(node => node.tagName === "select");
      select.value = "c#"; await fire(select, "change");
      assert(document.activeElement.value === "c#", "Skill replacement preserves focus and explicit catalogue identity");
      await control(skill(0, "c#"), "Remove Skill");
      same(skillOrder(0), ["python"], "Remove changes only the skill selection");
      assert(document.activeElement === nodes["#cv-skills-title"] && bankJSON.skills.includes("C#"), "Focus and source data are preserved");
      break;
    }
    case "editor_disclosures": {
      const choices = all(card("role-a")).filter(node => node.className?.includes("cv-choice"));
      assert(choices.length && choices.every(node => node.tagName === "details" && !node.open), "Selection lists are collapsed behind native disclosures");
      const change = all(bullet("a2")).find(node => node.className?.includes("cv-change-choice"));
      assert(change.children[0].tagName === "summary" && change.children[0].textContent === "Change", "Change is a concise accessible disclosure");
      const select = all(change).find(node => node.tagName === "select");
      assert(change.children.some(node => node.tagName === "label" && node.attributes.for === select.id), "A replacement has a visible associated label");
      assert(all(card("role-a")).find(node => node.textContent === "Remove experience").attributes["aria-label"].includes("bank record is kept"), "Removing a CV selection is distinguished from bank deletion");
      assert(!requests.some(request => request.method === "PUT"), "Presentation controls do not autosave");
      break;
    }
    case "editor_focus": {
      await choose(nodes["#cv-add-work"], "Add Experience", "role-b");
      assert(document.activeElement.textContent === "Developer at Other", "Adding a role focuses its new heading");
      await control(bullet("a2"), "Remove bullet point");
      assert(document.activeElement === nodes["#cv-work-title"], "Removing content returns focus to its section heading");
      const select = all(skill(0, "python")).find(node => node.tagName === "select");
      // Select the same option: the draft stays unchanged but focus still follows the rebuilt control.
      await fire(select, "change");
      assert(document.activeElement.tagName === "select" && document.activeElement.parentElement.open, "Focus recovery reveals the enclosing Change disclosure");
      break;
    }
    case "editor_validation_labels": {
      const heading = all(group(0)).find(node => node.id === "cv-group-heading-0");
      const errorId = heading.attributes["aria-describedby"];
      heading.value = " "; await fire(heading, "input");
      assert(all(group(0)).find(node => node.id === errorId).textContent.includes("nonblank"), "Group-heading validation is associated with its input");
      assert(nodes["#save-current-cv"].disabled, "Invalid headings cannot be saved");
      break;
    }
    case "bank_text_preservation": {
      const original = "  Original bullet.\r\nSecond line.  ";
      const rows = [
        { original: { id: "unchanged", text: original, skills: ["AWS (EC2, S3)", " Python "], technologies: ["C++"], outcomes: ["Kept\r\nmultiline outcome"] }, text: original.replace(/\r\n/g, "\n") },
        { original: { id: "edited", text: "Old wording." }, text: "  Explicit new wording.\nWith spaces.  " },
        { original: {}, text: "  New bullet with preserved spaces.  " },
        { original: {}, text: " \t " },
      ];
      rows.forEach(row => {
        row.querySelector = selector => {
          const field = selector.match(/data-field="([^"]+)"/)[1];
          const value = field === "text" ? row.text : (row.original[field] || []).join(field === "outcomes" ? "\n" : ", ");
          return { value: value.replace(/\r\n?/g, "\n") };
        };
      });
      const read = readEvidence({ querySelectorAll: () => rows });
      same(read.map(item => item.text), [original, rows[1].text, rows[2].text], "Preserve wording and line endings; exclude blank new rows");
      same(read.slice(0, 2).map(item => item.id), ["unchanged", "edited"], "Keep evidence IDs");
      same(read[0].skills, rows[0].original.skills, "Keep unedited comma-containing tags and whitespace");
      same(read[0].outcomes, rows[0].original.outcomes, "Keep unedited multiline outcomes");
      same(readBankField({ value: "  Original name  " }, "  Original name  "), "  Original name  ", "Keep unedited names");
      same(readBankField({ value: original.replace(/\r\n/g, "\n") }, original), original, "Keep unedited summary line endings");
      same(readBankField({ value: "  Changed name  " }, "Old name"), "Changed name", "Explicit metadata edits retain existing trim behavior");
      break;
    }
    case "bank_rows_preservation": {
      const fixtures = [
        ["education", ["qualification", "institution", "field", "year"], { id: "edu-1", qualification: " BSc | Applied Computing ", institution: " University ", field: " Computing ", year: "2024" }],
        ["certifications", ["name", "issuer", "year", "skills"], { id: "cert-1", name: " Certificate | With Separator ", issuer: " Issuer ", year: null, skills: ["AWS (EC2, S3)"] }],
      ];
      for (const [id, fields, record] of fixtures) {
        const values = Object.fromEntries(fields.map(field => [field, { value: Array.isArray(record[field]) ? record[field].join(", ") : record[field] ?? "" }]));
        const row = { original: copy(record), querySelector: selector => values[selector.match(/data-field="([^"]+)"/)[1]] };
        nodes[`#${id}`] = { querySelectorAll: () => [row] };
        same(readCredentials(id), [record], "Unrelated saves preserve every field and stable ID");
        same(row.original, record, "Reading rows never mutates originals");
        values[fields[0]].value = "Renamed | credential";
        same(readCredentials(id)[0].id, record.id, "Renaming a credential preserves its ID without title matching");
        same(readCredentials(id)[0][fields[0]], "Renamed | credential", "Pipe characters are ordinary record text");
      }
      break;
    }
    default: throw new Error(`Unknown scenario ${scenario}`);
  }
  assert(requests.every(request => request.url !== "/experience-bank" || request.method === "GET"), "Builder never writes the bank");
  print(`PASS ${scenario}`);
}
run().catch(error => {
  print(`FAIL ${scenario}: ${error.message}`);
  if (typeof quit === "function") quit(1);
  else process.exitCode = 1;
});
