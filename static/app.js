const bankForm = document.querySelector("#bank-form");
const matchForm = document.querySelector("#match-form");
const jobDescriptionInput = document.querySelector("#job-description");
const analyseButton = document.querySelector("#analyse-button");
const buttonLabel = document.querySelector("#button-label");
const loadingLabel = document.querySelector("#loading-label");
const formError = document.querySelector("#form-error");
const bankMessage = document.querySelector("#bank-message");
const results = document.querySelector("#results");
const MIN_DESCRIPTION_LENGTH = 20;
let loadedBank = {};
let bankLoaded = false;
const saveBankButton = document.querySelector("#save-bank-button");
saveBankButton.disabled = true;

let bankFieldSequence = 0;

// Presentation helpers retain each record object; IDs and unedited metadata
// are carried through by the existing readers, never reconstructed from titles.
function bankField(target, field, labelText, value, { multiline = false, required = false, maxLength = null, hint = "" } = {}) {
  const group = node("div", undefined, "bank-field");
  const input = node(multiline ? "textarea" : "input");
  input.id = `bank-field-${++bankFieldSequence}`;
  input.dataset.field = field;
  input.dataset.bankLabel = labelText;
  input.value = value ?? "";
  input.originalValue = value;
  input.required = required;
  if (maxLength) input.dataset.maxLength = String(maxLength);
  if (multiline) input.rows = field === "text" ? 3 : 2;
  const label = node("label", `${labelText}${required ? " (required)" : ""}`);
  label.setAttribute("for", input.id);
  const help = node("p", hint, "field-hint");
  help.id = `${input.id}-hint`;
  help.hidden = !hint;
  const error = node("p", "", "message error");
  error.id = `${input.id}-error`;
  error.hidden = true;
  input.setAttribute("aria-describedby", `${help.id} ${error.id}`);
  input.addEventListener("input", () => {
    input.removeAttribute("aria-invalid");
    error.hidden = true;
  });
  group.append(label, input, help, error);
  target.append(group);
  return input;
}

function bankRecord(container, original, className, title, fallback, deleteLabel, addButton, focus = false) {
  container.querySelector(".bank-empty")?.remove();
  const card = node("details", undefined, `bank-record ${className}`);
  card.original = original;
  card.open = focus;
  const summary = node("summary");
  const heading = node("span", title(), "bank-record-title");
  summary.append(heading, node("span", "Edit details", "bank-record-action"));
  const body = node("div", undefined, "bank-record-body");
  const remove = node("button", deleteLabel, "remove-button");
  remove.type = "button";
  remove.setAttribute("aria-label", `${deleteLabel}: ${title()}`);
  remove.addEventListener("click", () => {
    const siblings = [...container.children].filter(item => item.className?.includes("bank-record"));
    const index = siblings.indexOf(card);
    const next = siblings[index + 1] || siblings[index - 1];
    card.remove();
    if (!next) container.append(node("p", fallback, "bank-empty muted"));
    (next?.querySelector("summary") || addButton).focus();
  });
  body.append(remove);
  card.append(summary, body);
  card.addEventListener("input", () => {
    heading.textContent = title();
    remove.setAttribute("aria-label", `${deleteLabel}: ${title()}`);
  });
  container.append(card);
  return { card, body };
}

function addWorkExperience(work = {}, focus = false) {
  let employer, role;
  const title = () => `${(role?.value ?? work.role) || "Untitled role"}${(employer?.value ?? work.employer) ? ` · ${employer?.value ?? work.employer}` : ""}`;
  const { card, body } = bankRecord(document.querySelector("#work-list"), work, "work-entry", title,
    "No work roles recorded yet.", "Delete role from bank", document.querySelector("#add-work"), focus);
  const grid = node("div", undefined, "input-grid"); body.append(grid);
  employer = bankField(grid, "employer", "Employer", work.employer, { required: true, maxLength: 200 });
  role = bankField(grid, "role", "Role title", work.role, { required: true, maxLength: 200 });
  bankField(grid, "start_date", "Start date", work.start_date, { maxLength: 30 });
  bankField(grid, "end_date", "End date", work.end_date, { maxLength: 30, hint: "Use your recorded date wording; leave blank if not recorded." });
  bankField(body, "summary", "Role summary", work.summary, { multiline: true, maxLength: 2000 });
  for (const field of ["skills", "technologies"]) bankField(body, field, field === "skills" ? "Role skills" : "Role technologies", (work[field] || []).join(", "), { hint: "Comma separated. These tags are separate from individual achievement wording." });
  const achievements = node("div"); achievements.dataset.field = "achievements";
  body.append(node("h4", "Achievements"), node("p", "Each achievement keeps its own wording, skills, technologies and optional outcomes.", "muted"), achievements);
  evidenceEditor(achievements, work.achievements || [], "achievement");
  if (focus) employer.focus();
  return card;
}

function addProject(project = {}, focus = false) {
  let name;
  const { card, body } = bankRecord(document.querySelector("#project-list"), project, "project-entry", () => (name?.value ?? project.name) || "Untitled project",
    "No projects recorded yet.", "Delete project from bank", document.querySelector("#add-project"), focus);
  name = bankField(body, "name", "Project name", project.name, { required: true, maxLength: 200 });
  bankField(body, "description", "Project description", project.description, { multiline: true, maxLength: 2000 });
  bankField(body, "link", "Project link (optional)", project.link, { maxLength: 500 });
  for (const field of ["skills", "technologies"]) bankField(body, field, field === "skills" ? "Project skills" : "Project technologies", (project[field] || []).join(", "), { hint: "Comma separated. Contribution-specific tags belong on the contribution below." });
  const contributions = node("div"); contributions.dataset.field = "evidence";
  body.append(node("h4", "Contributions"), node("p", "Record the work you contributed to this project in your original wording.", "muted"), contributions);
  evidenceEditor(contributions, project.evidence || [], "contribution");
  if (focus) name.focus();
  return card;
}

const credentialFields = {
  education: [["qualification", "Qualification", true], ["institution", "Institution", true], ["field", "Field of study"], ["year", "Year"]],
  certifications: [["name", "Certification name", true], ["issuer", "Issuer"], ["year", "Year"], ["skills", "Certification skills"]],
};

function addCredential(kind, original = {}, focus = false) {
  const education = kind === "education";
  let heading;
  const { card, body } = bankRecord(document.querySelector(`#${kind}`), original, "credential-entry", () => (heading?.value ?? original[education ? "qualification" : "name"]) || (education ? "New qualification" : "New certification"),
    education ? "No education recorded yet." : "No certifications recorded yet.", education ? "Delete education from bank" : "Delete certification from bank", document.querySelector(`#add-${kind}`), focus);
  const grid = node("div", undefined, "input-grid"); body.append(grid);
  for (const [field, label, required] of credentialFields[kind]) {
    const input = bankField(grid, field, label, field === "skills" ? (original.skills || []).join(", ") : original[field],
      { required: Boolean(required), maxLength: field === "skills" ? null : field === "year" ? 30 : 200, hint: field === "skills" ? "Comma separated. Only explicitly recorded skills become selectable in My CV." : "" });
    heading ||= input;
  }
  if (focus) heading.focus();
  return card;
}

function splitValues(value) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function readTags(value, original = []) {
  // An unrelated save must not split an existing tag containing a comma.
  const displayed = original.join(", ");
  return value === displayed || value === displayed.replace(/[\r\n]/g, "") ? [...original] : splitValues(value);
}

function readBankField(input, original = "") {
  const normalised = String(original ?? "").replace(/\r\n?/g, "\n");
  const displayed = input.tagName?.toLowerCase() === "input" ? normalised.replace(/\n/g, "") : normalised;
  return input.value === displayed ? original ?? "" : input.value.trim();
}

// Keep each item's metadata attached to its row while editing or reordering.
function evidenceEditor(container, items, kind = "evidence") {
  container.replaceChildren();
  const add = node("button", `Add ${kind}`, "secondary-button");
  add.type = "button";
  const addRow = (item = {}, focus = false) => {
    let wording;
    const { body } = bankRecord(container, item, "evidence-entry", () => (wording?.value ?? item.text) || `New ${kind}`,
      `No ${kind} recorded yet.`, `Delete ${kind} from bank`, add, focus);
    wording = bankField(body, "text", kind === "achievement" ? "Achievement wording" : kind === "contribution" ? "Contribution wording" : "Evidence wording", item.text, { multiline: true, maxLength: 2000, hint: "Keep the wording you want to use on your CV. Blank evidence rows are excluded when saving." });
    const metadata = node("details", undefined, "bank-evidence-metadata");
    metadata.append(node("summary", "Skills, technologies & outcomes (optional)"));
    for (const [field, label] of [["skills", "Skills used"], ["technologies", "Technologies used"], ["outcomes", "Recorded outcomes"]]) {
      bankField(metadata, field, label, (item[field] || []).join(field === "outcomes" ? "\n" : ", "),
        { multiline: field === "outcomes", hint: field === "outcomes" ? "One outcome per line." : "Comma separated; specific to this item." });
    }
    body.append(metadata);
    // Keep the add action after all records; query-based readers do not depend on position.
    container.append(add);
    if (focus) wording.focus();
  };
  container.append(add);
  items.forEach(item => addRow(item));
  if (!items.length) container.append(node("p", `No ${kind} recorded yet.`, "bank-empty muted"));
  add.addEventListener("click", () => addRow({}, true));
}

function readEvidence(container) {
  return [...container.querySelectorAll(".evidence-entry")].map((row) => {
    const value = (field) => row.querySelector(`[data-field="${field}"]`).value.trim();
    const text = row.querySelector('[data-field="text"]').value;
    // Textareas normalise line endings. Keep original bytes when the displayed
    // text is unchanged, and never trim a user's CV-ready bullet wording.
    const originalText = row.original.text;
    return {
      ...row.original,
      text: typeof originalText === "string" && text === originalText.replace(/\r\n?/g, "\n") ? originalText : text,
      skills: readTags(row.querySelector('[data-field="skills"]').value, row.original.skills),
      technologies: readTags(row.querySelector('[data-field="technologies"]').value, row.original.technologies),
      outcomes: row.querySelector('[data-field="outcomes"]').value === (row.original.outcomes || []).join("\n").replace(/\r\n?/g, "\n")
        ? [...(row.original.outcomes || [])]
        : value("outcomes").split("\n").map((line) => line.trim()).filter(Boolean),
    };
  }).filter((item) => item.text.trim());
}

function readCredentials(kind) {
  return [...document.querySelector(`#${kind}`).querySelectorAll(".credential-entry")].map(card => {
    const record = { ...card.original };
    for (const [field] of credentialFields[kind]) {
      const input = card.querySelector(`[data-field="${field}"]`);
      record[field] = field === "skills" ? readTags(input.value, card.original.skills)
        : readBankField(input, card.original[field]);
      if (field === "year") record[field] = record[field] || (card.original[field] === "" ? "" : null);
    }
    return record;
  });
}

function readBank() {
  const workExperience = [...document.querySelectorAll(".work-entry")].map((card) => {
    const value = (field) => readBankField(card.querySelector(`[data-field="${field}"]`), card.original[field]);
    const skills = readTags(card.querySelector('[data-field="skills"]').value, card.original.skills);
    const technologies = readTags(card.querySelector('[data-field="technologies"]').value, card.original.technologies);
    return {
      ...card.original,
      employer: value("employer"),
      role: value("role"),
      start_date: value("start_date") || null,
      end_date: value("end_date") || null,
      summary: value("summary"),
      skills,
      technologies,
      achievements: readEvidence(card.querySelector('[data-field="achievements"]')),
    };
  });
  const projects = [...document.querySelectorAll(".project-entry")].map((card) => {
    const value = (field) => readBankField(card.querySelector(`[data-field="${field}"]`), card.original[field]);
    const skills = readTags(card.querySelector('[data-field="skills"]').value, card.original.skills);
    const technologies = readTags(card.querySelector('[data-field="technologies"]').value, card.original.technologies);
    return {
      ...card.original,
      name: value("name"),
      description: value("description"),
      link: value("link") || (card.original.link === "" ? "" : null),
      skills,
      technologies,
      evidence: readEvidence(card.querySelector('[data-field="evidence"]')),
    };
  });
  return {
    ...loadedBank,
    skills: readTags(document.querySelector("#skills").value, loadedBank.skills),
    work_experience: workExperience,
    projects,
    education: readCredentials("education"),
    certifications: readCredentials("certifications"),
    additional_evidence: readEvidence(document.querySelector("#additional-evidence-editor")),
  };
}

function populateBank(bank) {
  loadedBank = bank;
  document.querySelector("#skills").value = bank.skills.join(", ");
  document.querySelector("#work-list").replaceChildren();
  document.querySelector("#project-list").replaceChildren();
  bank.work_experience.forEach(item => addWorkExperience(item));
  bank.projects.forEach(item => addProject(item));
  for (const kind of ["education", "certifications"]) {
    document.querySelector(`#${kind}`).replaceChildren();
    bank[kind].forEach(item => addCredential(kind, item));
  }
  evidenceEditor(document.querySelector("#additional-evidence-editor"), bank.additional_evidence);

}

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(typeof data.detail === "string" ? data.detail : "The request could not be completed.");
    error.details = data.detail;
    throw error;
  }
  return data;
}

function setLoading(isLoading) {
  analyseButton.disabled = isLoading;
  buttonLabel.hidden = isLoading;
  loadingLabel.hidden = !isLoading;
}

let bankBaseline = null;
let bankVersion = 0;
let resultVersion = null;
let resultDescription = "";
let bankLoading = true;
let saving = false;
let matching = false;
let analysisVersion = 0;
let activeAnalysisRun = null;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function disclosure(label, ...children) {
  const detail = node("details");
  detail.append(node("summary", label), ...children);
  return detail;
}

function bankSnapshot() {
  return JSON.stringify(readBank());
}

function updateBankSummary(bank) {
  document.querySelector("#bank-summary").textContent = `${bank.work_experience.length} roles · ${bank.projects.length} projects · ${bank.skills.length} skills`;
}

function updateState() {
  const dirty = bankBaseline !== null && bankSnapshot() !== bankBaseline;
  document.querySelector("#bank-state").textContent = bankLoading ? "" : dirty ? "Unsaved changes" : "Saved";
  document.querySelector("#saved-bank-notice").hidden = !dirty;
  const reasons = [];
  if (resultVersion !== null) {
    if (resultVersion !== bankVersion) reasons.push("Your saved bank has changed. Analyse and match again to refresh these results.");
    if (jobDescriptionInput.value.trim() !== resultDescription) reasons.push("The job description has changed. Analyse and match again to refresh these results.");
    if (dirty) reasons.push("These results exclude unsaved bank edits. Save and match again to include them.");
  }
  const notice = document.querySelector("#refresh-notice");
  notice.textContent = reasons.join(" ");
  notice.hidden = !reasons.length;
  for (const [id, selector, label, countId] of [["work-list", ".work-entry", "work roles", "bank-work-count"], ["project-list", ".project-entry", "projects", "bank-project-count"], ["education", ".credential-entry", "education records"], ["certifications", ".credential-entry", "certifications"]]) {
    const container = document.querySelector(`#${id}`);
    const count = container.querySelectorAll(selector).length;
    if (!count && !container.querySelector(".bank-empty")) container.append(node("p", `No ${label} recorded yet.`, "bank-empty muted"));
    if (countId) document.querySelector(`#${countId}`).textContent = String(count);
  }
}

function validateBankFields() {
  let first = null;
  for (const input of bankForm.querySelectorAll("[data-bank-label]")) {
    // Validate the value the existing reader would send. Untouched saved
    // metadata stays intact; length uses Unicode characters as the API does.
    const value = readBankField(input, input.originalValue);
    const limit = Number(input.dataset.maxLength);
    const invalid = input.required && !value ? "Enter a nonblank value."
      : limit > 0 && [...value].length > limit ? `Use at most ${limit} characters.` : "";
    const error = document.querySelector(`#${input.id}-error`);
    error.textContent = invalid;
    error.hidden = !invalid;
    input.setAttribute("aria-invalid", String(Boolean(invalid)));
    if (invalid && !first) first = input;
  }
  if (!first) return true;
  for (let parent = first.parentElement; parent; parent = parent.parentElement) {
    if (parent.tagName.toLowerCase() === "details") parent.open = true;
  }
  bankMessage.textContent = `Check ${first.dataset.bankLabel.toLowerCase()} before saving. Your changes have been kept.`;
  bankMessage.setAttribute("role", "alert");
  first.focus();
  return false;
}

function appendRequirementMetadata(target, requirement) {
  const metadata = node("span", undefined, "requirement-metadata");
  const importance = { required: "Required", preferred: "Preferred", unspecified: "Unspecified" };
  metadata.append(node("span", importance[requirement?.importance] || "Unspecified", "requirement-importance"));
  target.append(metadata);
  if (requirement?.alternatives?.length > 1) {
    target.append(node("span", `Acceptable options: ${requirement.alternatives.join(" OR ")}`, "requirement-alternatives"));
  }
}

function renderAnalysis(analysis) {
  const structured = Array.isArray(analysis.requirements);
  const requirements = structured ? analysis.requirements : [
    ["skill", analysis.technical_skills], ["other_keyword", analysis.other_keywords],
    ["responsibility", analysis.responsibilities], ["qualification", analysis.qualifications],
  ].flatMap(([category, values]) => (values || []).map(text => ({ text, category, importance: "unspecified" })));
  const overview = document.querySelector("#overview");
  const full = document.querySelector("#full-analysis");
  overview.replaceChildren();
  full.replaceChildren();
  const note = document.querySelector("#analysis-format-note");
  note.hidden = structured;
  note.textContent = structured ? "" : "Legacy analysis: importance and grouped alternatives were not recorded. No additional distinctions have been inferred.";
  if (!requirements.length) overview.append(node("p", "No job requirements were identified in this analysis.", "muted"));
  else for (const [label, categories] of [
    ["Technical skills & capabilities", ["skill"]],
    ["Responsibilities", ["responsibility"]], ["Qualifications", ["qualification"]],
    ["Other keywords", ["other_keyword"]],
  ]) {
    const items = requirements.filter(item => categories.includes(item.category));
    if (categories.includes("other_keyword") && !items.length) continue;
    const section = node("article", undefined, "analysis-category");
    section.append(node("h4", label));
    const list = node("ul", undefined, "analysis-requirement-list");
    if (!items.length) list.append(node("li", "None identified", "muted"));
    for (const item of items) {
      const row = node("li");
      if (item.id) row.dataset.requirementId = item.id;
      row.append(node("p", item.text, "requirement-wording"));
      appendRequirementMetadata(row, item);
      list.append(row);
    }
    section.append(list);
    overview.append(section);
  }
  const sources = [...new Set(requirements.map(item => item.source_text).filter(Boolean))];
  for (const text of sources) full.append(node("blockquote", text, "original-source-text"));
  if (!sources.length) full.append(node("p", structured ? "No source wording was returned." : "Original source wording is unavailable for this legacy analysis.", "muted"));
}

// Presentation state only: classification and support always come from /match.
let matchRequirements = [];
let requirementFilter = "all";
let selectedRequirement = null;
const matchLabels = { strong: "Strong", related: "Related", missing: "Not evidenced" };

function filteredRequirements() {
  return matchRequirements.filter(entry => requirementFilter === "all" || entry.status === requirementFilter);
}

function renderRequirementEvidence(entry) {
  document.querySelector("#requirement-evidence").scrollTop = 0;
  const title = document.querySelector("#selected-requirement-title");
  const selected = document.querySelector("#selected-requirement");
  const content = document.querySelector("#requirement-evidence-content");
  selected.replaceChildren();
  content.replaceChildren();
  const announcement = document.querySelector("#requirement-selection-status");
  if (!entry) {
    title.textContent = "Supporting evidence";
    content.append(node("p", matchRequirements.length ? "There is no requirement to inspect in this filter." : "No requirements are available to inspect.", "muted"));
    announcement.textContent = "No requirement selected.";
    return;
  }
  const item = entry.item;
  const details = item.requirement_details;
  title.textContent = item.requirement;
  selected.append(node("p", matchLabels[entry.status], `match-classification match-${entry.status}`));
  appendRequirementMetadata(selected, details);
  if (details?.activity) selected.append(node("p", `Requirement activity: ${{ technology_usage: "Technology usage", api_development: "API development", cloud_deployment: "Cloud deployment" }[details.activity] || details.activity}`, "muted"));
  if (!details) selected.append(node("p", "Structured requirement metadata was not supplied for this legacy result.", "muted"));
  if (details?.source_text) selected.append(disclosure("Job description wording", node("blockquote", details.source_text, "original-source-text")));
  const references = [];
  const seen = new Set();
  for (const evidence of item.evidence || []) {
    const key = JSON.stringify([evidence.source_type, evidence.evidence_id]);
    if (seen.has(key)) continue;
    seen.add(key);
    references.push(evidence);
  }
  announcement.textContent = `${item.requirement}. ${matchLabels[entry.status]}. ${references.length} supporting records.`;
  if (!references.length) {
    content.append(node("p", item.explanation || (entry.status === "missing" ? "No supporting evidence was found in your saved Experience Bank." : "No supporting records were supplied for this requirement."), "evidence-empty"));
    return;
  }
  if (item.explanation) {
    const explanation = node("p", item.explanation, "requirement-explanation");
    selected.append(item.evidence_support?.length ? disclosure("Requirement explanation", explanation) : explanation);
  }
  const types = { achievement: "Achievement", project_evidence: "Project contribution", work_experience: "Work role context", project: "Project context", skill: "Recorded skill", education: "Education", certification: "Certification", additional_evidence: "Additional evidence" };
  const origins = { wording: "Original wording", outcome: "Recorded outcome", standalone_skill: "Declared skill", skill_tag: "Skill tag", technology_tag: "Technology tag", credential: "Credential" };
  for (const evidence of references) {
    // Never apply the requirement's best alternative/classification to every record.
    const support = (item.evidence_support || []).find(record => record.evidence_id === evidence.evidence_id && (!details?.id || record.requirement_id === details.id));
    const record = node("article", undefined, "requirement-evidence-record");
    record.dataset.evidenceId = evidence.evidence_id;
    record.dataset.sourceType = evidence.source_type;
    record.append(node("h4", `${types[evidence.source_type] || evidence.source_type} · ${evidence.source_label}`));
    const status = support?.status;
    record.append(node("p", status === "strong" ? "Strong support" : status === "related" ? "Related support" : "Per-record classification not recorded", "evidence-support-status"));
    record.append(node("p", evidence.text || "No original wording was recorded for this evidence.", "original-evidence-text"));
    if (support?.selected_alternative) record.append(node("p", `Matched option: ${support.selected_alternative}`, "evidence-option"));
    else if (details?.alternatives?.length > 1) record.append(node("p", "Matched option not recorded for this evidence.", "muted"));
    if (support?.explanation) record.append(node("p", support.explanation, "evidence-caveat"));
    if (!support) record.append(node("p", "Detailed support provenance was not supplied for this record.", "muted"));
    const signals = support?.signals || [];
    const basis = [...new Set(signals.map(signal => origins[signal.origin] || signal.origin))];
    if (basis.length) record.append(node("p", `Support basis: ${basis.join(" · ")}`, "muted"));
    const provenance = node("div", undefined, "evidence-provenance");
    provenance.append(node("p", `Experience Bank record: ${evidence.evidence_id}`, "muted"));
    const list = node("ul");
    for (const signal of signals) {
      const row = node("li", `${origins[signal.origin] || signal.origin}: ${signal.signal}`);
      if (signal.relationship) {
        const relationship = signal.relationship;
        row.append(node("p", `Relationship: ${relationship.source} → ${relationship.target} · ${relationship.type} · ${relationship.confidence} confidence`, "muted"));
      }
      if (signal.demonstrated_activity) row.append(node("p", `Recorded demonstrated activity: ${signal.demonstrated_activity}`, "muted"));
      list.append(row);
    }
    provenance.append(list);
    record.append(disclosure("Support details", provenance));
    content.append(record);
  }
}

function renderRequirementList(focusSelection = false) {
  const visible = filteredRequirements();
  if (!visible.some(entry => entry.key === selectedRequirement)) selectedRequirement = visible[0]?.key ?? null;
  const list = document.querySelector("#requirement-list");
  list.replaceChildren();
  document.querySelector("#requirement-count").textContent = `${visible.length} of ${matchRequirements.length} requirements`;
  for (const filter of ["all", "strong", "related", "missing"]) document.querySelector(`#filter-${filter}`).setAttribute("aria-pressed", String(filter === requirementFilter));
  if (!visible.length) list.append(node("p", matchRequirements.length ? `No requirements classified as ${matchLabels[requirementFilter]}.` : "No job requirements were returned.", "evidence-empty"));
  for (const [index, entry] of visible.entries()) {
    const button = node("button", undefined, "requirement-choice");
    button.id = `match-requirement-${entry.key}`;
    button.type = "button";
    button.dataset.requirementKey = String(entry.key);
    button.setAttribute("aria-controls", "requirement-evidence");
    button.setAttribute("aria-pressed", String(entry.key === selectedRequirement));
    button.append(node("span", entry.item.requirement, "requirement-wording"));
    appendRequirementMetadata(button, entry.item.requirement_details);
    button.append(node("span", matchLabels[entry.status], `match-classification match-${entry.status}`));
    const select = key => { selectedRequirement = key; renderRequirementList(true); };
    button.addEventListener("click", () => select(entry.key));
    button.addEventListener("keydown", event => {
      const next = { ArrowDown: Math.min(index + 1, visible.length - 1), ArrowUp: Math.max(index - 1, 0), Home: 0, End: visible.length - 1 }[event.key];
      if (next === undefined) return;
      event.preventDefault();
      select(visible[next].key);
    });
    list.append(button);
  }
  renderRequirementEvidence(visible.find(entry => entry.key === selectedRequirement));
  if (focusSelection && selectedRequirement !== null) {
    const selected = document.querySelector(`#match-requirement-${selectedRequirement}`);
    selected.focus({ preventScroll: true });
    selected.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
}

function clearMatchPresentation() {
  matchRequirements = [];
  requirementFilter = "all";
  selectedRequirement = null;
  document.querySelector("#results").hidden = true;
  for (const id of ["match-groups", "recommendations", "diagnostics"]) document.querySelector(`#${id}`).replaceChildren();
  renderRequirementList();
}

function renderMatches(match) {
  matchRequirements = [
    ["strong", match.strong_matches], ["related", match.related_matches], ["missing", match.missing_requirements],
  ].flatMap(([status, items]) => (items || []).map(item => ({ item, status })));
  matchRequirements.forEach((entry, index) => { entry.key = index; });
  requirementFilter = "all";
  selectedRequirement = null;
  const groups = document.querySelector("#match-groups");
  groups.replaceChildren();
  for (const [status, label] of [
    ["strong", "Strong matches"], ["related", "Related matches"], ["missing", "Not evidenced"],
  ]) {
    const summary = node("p", undefined, `match-summary-item match-${status}`);
    summary.append(node("strong", String(matchRequirements.filter(entry => entry.status === status).length)), node("span", label));
    groups.append(summary);
  }
  renderRequirementList();
  renderSupplementaryEvidence(match);
}

function renderSupplementaryEvidence(match) {
  const recommendations = document.querySelector("#recommendations");
  recommendations.replaceChildren();
  const categories = [
    ["Work experience", ["achievement", "work_experience"]],
    ["Projects", ["project_evidence", "project"]],
    ["Skills", ["skill"]],
    ["Education & certifications", ["education", "certification"]],
    ["Additional evidence", ["additional_evidence"]],
  ];
  const seen = new Set();
  for (const [label, types] of categories) {
    const items = (match.ranked_evidence || []).filter(item => {
      const key = `${item.evidence.source_type}:${item.evidence.evidence_id}`;
      if (!types.includes(item.evidence.source_type) || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    const section = node("section", undefined, "recommendation-group");
    section.append(node("h4", label));
    if (!items.length) section.append(node("p", "No relevant evidence found in this group.", "muted"));
    const buildCard = item => {
      const specific = ["achievement", "project_evidence"].includes(item.evidence.source_type);
      const card = node("article", undefined, `evidence-card ${specific ? "specific-evidence" : "context-evidence"}`);
      const kind = specific ? "achievement" === item.evidence.source_type ? "Achievement" : "Project contribution" : ["project", "work_experience"].includes(item.evidence.source_type) ? "Summary / declared context" : "Evidence";
      card.append(node("p", `${kind} · ${item.evidence.source_label}`, "source-label"));
      card.append(node("p", item.evidence.text || "Relevant declared skills or technologies; no summary recorded."));
      const signals = item.matched_signals;
      card.append(node("p", `Relevant to: ${signals.slice(0, 2).join("; ")}${signals.length > 2 ? ` (+${signals.length - 2} more)` : ""}`, "muted"));
      const supported = node("ul");
      signals.forEach(signal => supported.append(node("li", signal)));
      card.append(disclosure("All supported requirements", supported));
      return card;
    };
    const context = items.filter(item => ["work_experience", "project"].includes(item.evidence.source_type));
    const primary = items.filter(item => !["work_experience", "project"].includes(item.evidence.source_type));
    const compact = types.includes("skill") || types.includes("education");
    const buildCompact = item => {
      const supported = node("ul");
      item.matched_signals.forEach(signal => supported.append(node("li", signal)));
      const detail = disclosure(item.evidence.text || item.evidence.source_label,
        node("p", "Relevant to:", "muted"), supported);
      detail.className = types.includes("skill") ? "skill-chip" : "education-row";
      return detail;
    };
    const renderItem = compact ? buildCompact : buildCard;
    const preview = node("div", undefined, types.includes("skill") ? "skill-chips" : "evidence-preview");
    const limit = types.includes("skill") ? 6 : 2;
    primary.slice(0, limit).forEach(item => preview.append(renderItem(item)));
    section.append(preview);
    if (primary.length > limit) {
      const remaining = node("div", undefined, types.includes("skill") ? "skill-chips" : "evidence-preview");
      primary.slice(limit).forEach(item => remaining.append(renderItem(item)));
      section.append(disclosure(`Show ${primary.length - limit} more recommendations`, remaining));
    }
    if (context.length) section.append(disclosure(
      `${types.includes("achievement") ? "Role" : "Project"} context (${context.length})`,
      ...context.map(buildCard)
    ));
    recommendations.append(section);
  }
}

for (const filter of ["all", "strong", "related", "missing"]) {
  document.querySelector(`#filter-${filter}`).addEventListener("click", () => {
    requirementFilter = filter;
    renderRequirementList();
  });
}
window.addEventListener("job-analysis-invalidated", clearMatchPresentation);
window.addEventListener("job-analysis-started", () => {
  clearMatchPresentation();
  document.querySelector("#analysis-result").hidden = true;
  document.querySelector("#job-context").hidden = true;
});

bankForm.addEventListener("input", updateState);
// Structural edits (add/remove) complete before the deferred state check.
bankForm.addEventListener("click", () => queueMicrotask(updateState));
jobDescriptionInput.addEventListener("input", () => {
  analysisVersion += 1;
  window.dispatchEvent(new CustomEvent("job-analysis-invalidated"));
  updateState();
});
document.querySelector("#edit-job").addEventListener("click", () => {
  document.querySelector("#job-editor").open = true;
  jobDescriptionInput.focus();
});
window.addEventListener("beforeunload", event => {
  if (bankBaseline !== null && bankSnapshot() !== bankBaseline) {
    event.preventDefault();
    event.returnValue = "";
  }
});

document.querySelector("#add-work").addEventListener("click", () => addWorkExperience({}, true));
document.querySelector("#add-project").addEventListener("click", () => addProject({}, true));

for (const kind of ["education", "certifications"]) document.querySelector(`#add-${kind}`).addEventListener("click", () => addCredential(kind, {}, true));

window.addEventListener("job-workspace-reset", () => {
  analysisVersion += 1;
  activeAnalysisRun = null;
  matching = false;
  jobDescriptionInput.value = "";
  resultVersion = null;
  resultDescription = "";
  formError.textContent = "";
  formError.hidden = true;
  results.hidden = true;
  clearMatchPresentation();
  document.querySelector("#analysis-result").hidden = true;
  document.querySelector("#job-context").hidden = true;
  for (const id of ["results-title", "overview", "full-analysis", "match-groups", "recommendations", "diagnostics"]) {
    document.querySelector(`#${id}`).replaceChildren();
  }
  document.querySelector("#job-editor").open = true;
  setLoading(false);
  saveBankButton.disabled = !bankLoaded || saving;
  updateState();
});

bankForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (saving || matching) return;
  if (!bankLoaded) {
    bankMessage.textContent = "Load your experience bank successfully before saving. Reload to retry.";
    return;
  }
  if (!validateBankFields()) return;
  bankMessage.textContent = "Saving...";
  bankMessage.setAttribute("role", "status");
  try {
    const submitted = readBank();
    const snapshot = JSON.stringify(submitted);
    saving = true;
    bankForm.inert = true;
    saveBankButton.disabled = true;
    const saved = await request("/experience-bank", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(submitted),
    });
    const changed = JSON.stringify(saved) !== JSON.stringify(loadedBank);
    // Keep editing during save from discarding newer changes or server-generated IDs.
    if (bankSnapshot() === snapshot) {
      populateBank(saved);
      bankBaseline = bankSnapshot();
      bankMessage.textContent = "Experience bank saved.";
    } else {
      loadedBank = saved;
      bankBaseline = snapshot;
      bankMessage.textContent = "Submitted changes saved. Newer edits are still unsaved.";
    }
    if (changed) bankVersion += 1;
    window.dispatchEvent(new CustomEvent("experience-bank-saved", { detail: saved }));
    updateBankSummary(saved);
    updateState();
  } catch (error) {
    bankMessage.textContent = error.message;
    bankMessage.setAttribute("role", "alert");
    if (Array.isArray(error.details)) {
      const list = node("ul");
      for (const issue of error.details) list.append(node("li", `${(issue.loc || []).filter(part => part !== "body").join(" → ")}: ${issue.msg || "Invalid record."}`));
      bankMessage.append(list);
    }
  } finally {
    saving = false;
    bankForm.inert = false;
    saveBankButton.disabled = false;
  }
});

matchForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (matching) return;
  document.querySelector("#job-editor").open = true;
  formError.hidden = true;
  const description = jobDescriptionInput.value.trim();
  if (description.length < MIN_DESCRIPTION_LENGTH || description.length > 20000) {
    formError.textContent = "Please enter between 20 and 20,000 characters of job description.";
    formError.hidden = false;
    return;
  }
  if (saving) {
    formError.textContent = "Please wait for the experience bank to finish saving, then match again.";
    formError.hidden = false;
    return;
  }
  const version = bankVersion;
  const analysisRun = ++analysisVersion;
  activeAnalysisRun = analysisRun;
  matching = true;
  window.dispatchEvent(new CustomEvent("job-analysis-started", { detail: { revision: analysisRun } }));
  document.querySelector("#save-bank-button").disabled = true;
  setLoading(true);
  try {
    const analysis = await request("/analyse", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ job_description: description }) });
    if (analysisRun !== analysisVersion) return;
    document.querySelector("#results-title").textContent = analysis.job_title;
    document.querySelector("#job-context").hidden = false;
    renderAnalysis(analysis);
    document.querySelector("#analysis-result").hidden = false;
    window.dispatchEvent(new CustomEvent("job-analysis-ready", { detail: { analysis, revision: analysisRun } }));
    const match = await request("/match", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ job_analysis: analysis }) });
    if (analysisRun !== analysisVersion) return;
    renderMatches(match);
    document.querySelector("#diagnostics").textContent = JSON.stringify({ analysis, match }, null, 2);
    resultVersion = version;
    resultDescription = description;
    results.hidden = false;
    window.dispatchEvent(new CustomEvent("job-match-ready", { detail: { revision: analysisRun } }));
    updateState();
    // Preserve edits made during the request; only collapse the analysed description.
    document.querySelector("#job-editor").open = jobDescriptionInput.value.trim() !== description;
    if (!document.querySelector("#workspace-view").hidden && !document.querySelector("#analyse-stage").hidden) document.querySelector("#results-title").focus();
  } catch (error) {
    if (analysisRun !== analysisVersion) return;
    document.querySelector("#job-editor").open = true;
    formError.textContent = error.message || "Something went wrong. Please try again.";
    formError.hidden = false;
    window.dispatchEvent(new CustomEvent("job-analysis-failed", { detail: { revision: analysisRun } }));
  } finally {
    if (activeAnalysisRun === analysisRun) {
      activeAnalysisRun = null;
      matching = false;
      document.querySelector("#save-bank-button").disabled = bankLoading;
      setLoading(false);
      window.dispatchEvent(new CustomEvent("job-analysis-finished", { detail: { revision: analysisRun } }));
    }
  }
});

request("/experience-bank").then((bank) => {
  populateBank(bank);
  bankBaseline = bankSnapshot();
  bankLoading = false;
  updateBankSummary(bank);
  updateState();
  bankLoaded = true;
  saveBankButton.disabled = false;
}).catch((error) => {
  bankLoaded = false;
  saveBankButton.disabled = true;
  bankMessage.textContent = `Bank loading failed: ${error.message}. Reload to retry; saving is disabled.`;
});
