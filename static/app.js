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

function escapeHTML(value) {
  return String(value).replace(/[&<>"']/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
}

function addWorkExperience(work = {}) {
  const card = document.createElement("div");
  card.className = "editor-card work-entry";
  card.original = work;
  // Static markup only; saved values are assigned as DOM properties below.
  card.innerHTML = `<button class="remove-button" type="button">Remove</button>
    <div class="input-grid"><input data-field="employer" placeholder="Employer" required><input data-field="role" placeholder="Role" required><input data-field="start_date" placeholder="Start date"><input data-field="end_date" placeholder="End date"></div>
    <input data-field="skills" placeholder="Role skills, comma separated">
    <input data-field="technologies" placeholder="Technologies, comma separated">
    <textarea data-field="summary" rows="2" placeholder="Role summary"></textarea>
    <div data-field="achievements"></div>`;
  for (const field of ["employer", "role", "start_date", "end_date", "summary"]) {
    card.querySelector(`[data-field="${field}"]`).value = work[field] || "";
  }
  for (const field of ["skills", "technologies"]) {
    card.querySelector(`[data-field="${field}"]`).value = (work[field] || []).join(", ");
  }
  evidenceEditor(card.querySelector('[data-field="achievements"]'), work.achievements || []);
  card.querySelector(".remove-button").addEventListener("click", () => card.remove());
  document.querySelector("#work-list").append(card);
}

function addProject(project = {}) {
  const card = document.createElement("div");
  card.className = "editor-card project-entry";
  card.original = project;
  card.innerHTML = `<button class="remove-button" type="button">Remove</button>
    <input data-field="name" placeholder="Project name" required>
    <input data-field="skills" placeholder="Skills, comma separated">
    <input data-field="technologies" placeholder="Technologies, comma separated">
    <textarea data-field="description" rows="2" placeholder="Project description"></textarea>
    <div data-field="evidence"></div>`;
  for (const field of ["name", "description"]) {
    card.querySelector(`[data-field="${field}"]`).value = project[field] || "";
  }
  for (const field of ["skills", "technologies"]) {
    card.querySelector(`[data-field="${field}"]`).value = (project[field] || []).join(", ");
  }
  evidenceEditor(card.querySelector('[data-field="evidence"]'), project.evidence || []);
  card.querySelector(".remove-button").addEventListener("click", () => card.remove());
  document.querySelector("#project-list").append(card);
}

function splitValues(value) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function readTags(value, original = []) {
  // An unrelated save must not split an existing tag containing a comma.
  return value === original.join(", ") ? [...original] : splitValues(value);
}

function readBankField(input, original = "") {
  const displayed = String(original ?? "").replace(/\r\n?/g, "\n");
  return input.value === displayed ? original ?? "" : input.value.trim();
}

// Keep each item's metadata attached to its row while editing or reordering.
function evidenceEditor(container, items) {
  container.replaceChildren();
  const add = document.createElement("button");
  add.type = "button";
  add.textContent = "Add evidence";
  const addRow = (item = {}) => {
    const row = document.createElement("div");
    row.className = "evidence-entry";
    row.original = item;
    const fields = [
      ["text", "Achievement or evidence"],
      ["skills", "This item's skills, comma separated"],
      ["technologies", "This item's technologies, comma separated"],
      ["outcomes", "Outcomes, one per line"],
    ];
    for (const [field, label] of fields) {
      const input = document.createElement(field === "text" || field === "outcomes" ? "textarea" : "input");
      input.dataset.field = field;
      input.setAttribute("aria-label", label);
      input.placeholder = label;
      input.value = Array.isArray(item[field]) ? item[field].join(field === "outcomes" ? "\n" : ", ") : item[field] || "";
      row.append(input);
    }
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove evidence";
    remove.addEventListener("click", () => row.remove());
    row.append(remove);
    container.insertBefore(row, add);
  };
  container.append(add);
  items.forEach(addRow);
  add.addEventListener("click", () => addRow());
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

function parseLines(id, fields) {
  const originals = loadedBank[id] || [];
  const input = document.querySelector(`#${id}`).value;
  const displayed = originals.map(item => fields.map(field => Array.isArray(item[field]) ? item[field].join(", ") : item[field] || "").join(" | ")).join("\n");
  if (input === displayed.replace(/\r\n?/g, "\n")) return originals.map(item => ({ ...item }));
  const remaining = [...originals];
  return input.split("\n").filter((line) => line.trim()).map((line) => {
    const values = line.split("|").map((value) => value.trim());
    const index = remaining.findIndex((item) => item[fields[0]] === values[0]);
    const original = index >= 0 ? remaining.splice(index, 1)[0] : {};
    const parsed = Object.fromEntries(fields.map((field, index) => [
      field,
      field === "skills"
        ? readTags(values[index] || "", original[field])
        : values[index] || (field === "year" ? null : ""),
    ]));
    return { ...original, ...parsed };
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
    education: parseLines("education", ["qualification", "institution", "field", "year"]),
    certifications: parseLines("certifications", ["name", "issuer", "year", "skills"]),
    additional_evidence: readEvidence(document.querySelector("#additional-evidence-editor")),
  };
}

function populateBank(bank) {
  loadedBank = bank;
  document.querySelector("#skills").value = bank.skills.join(", ");
  document.querySelector("#work-list").replaceChildren();
  document.querySelector("#project-list").replaceChildren();
  bank.work_experience.forEach(addWorkExperience);
  bank.projects.forEach(addProject);
  document.querySelector("#education").value = bank.education.map((item) => [item.qualification, item.institution, item.field, item.year || ""].join(" | ")).join("\n");
  document.querySelector("#certifications").value = bank.certifications.map((item) => [item.name, item.issuer, item.year || "", (item.skills || []).join(", ")].join(" | ")).join("\n");
  evidenceEditor(document.querySelector("#additional-evidence-editor"), bank.additional_evidence);
}

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "The request could not be completed.");
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
}

function renderAnalysis(analysis) {
  const sections = [
    ["Technical skills & technologies", analysis.technical_skills, 6],
    ["Responsibilities", analysis.responsibilities, 3],
    ["Qualifications", analysis.qualifications, 2],
    ["Other capabilities", analysis.other_keywords, 3],
  ];
  const overview = document.querySelector("#overview");
  const full = document.querySelector("#full-analysis");
  overview.replaceChildren();
  full.replaceChildren();
  for (const [label, values, limit] of sections) {
    for (const [target, items] of [[overview, values.slice(0, limit)], [full, values]]) {
      const card = node("article", undefined, "overview-card");
      card.append(node("h4", label));
      const list = node("ul");
      (items.length ? items : ["None identified"]).forEach(value => list.append(node("li", value)));
      card.append(list);
      if (target === overview && values.length > limit) card.append(node("p", `+${values.length - limit} in full analysis`, "muted"));
      target.append(card);
    }
  }
}

function requirementRow(item) {
  const row = node("li", undefined, "requirement-row");
  row.append(node("p", item.requirement, "requirement-name"));
  if (!item.evidence.length) {
    return row;
  }
  const list = node("ul", undefined, "support-list");
  const seen = new Set();
  for (const evidence of item.evidence) {
    const key = `${evidence.source_type}:${evidence.evidence_id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const record = node("li");
    record.append(node("p", evidence.source_label, "source-label"), node("p", evidence.text || "Support comes from declared skills or technologies."));
    list.append(record);
  }
  row.append(disclosure(`Supporting experience (${seen.size})`, list));
  return row;
}

function renderMatches(match) {
  const groups = document.querySelector("#match-groups");
  groups.replaceChildren();
  for (const [label, items, status, explanation] of [
    ["Strong matches", match.strong_matches, "strong", "Strong evidence support"],
    ["Related matches", match.related_matches, "related", "Related evidence support"],
    ["Not evidenced", match.missing_requirements, "missing", "No supporting evidence found"],
  ]) {
    const card = node("article", undefined, `result-card status-${status}`);
    const heading = node("h4", undefined, "status-heading");
    const count = node("span", String(items.length), "status-count");
    count.setAttribute("aria-label", `${items.length} requirements`);
    heading.append(node("span", label), count);
    card.append(heading, node("p", explanation, "muted"));
    const list = node("ul", undefined, "requirement-list");
    items.slice(0, 3).forEach(item => list.append(requirementRow(item)));
    card.append(list);
    if (!items.length) card.append(node("p", "None identified", "muted"));
    if (items.length > 3) {
      const rest = node("ul", undefined, "requirement-list");
      items.slice(3).forEach(item => rest.append(requirementRow(item)));
      card.append(disclosure(`Show ${items.length - 3} more requirements`, rest));
    }
    groups.append(card);
  }
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
    const items = match.ranked_evidence.filter(item => {
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

document.querySelector("#add-work").addEventListener("click", () => addWorkExperience());
document.querySelector("#add-project").addEventListener("click", () => addProject());

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
  bankMessage.textContent = "Saving...";
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
