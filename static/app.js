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
    return {
      ...row.original,
      text: value("text"),
      skills: splitValues(value("skills")),
      technologies: splitValues(value("technologies")),
      outcomes: value("outcomes").split("\n").map((line) => line.trim()).filter(Boolean),
    };
  }).filter((item) => item.text);
}

function parseLines(id, fields) {
  const remaining = [...(loadedBank[id] || [])];
  return document.querySelector(`#${id}`).value.split("\n").filter((line) => line.trim()).map((line) => {
    const values = line.split("|").map((value) => value.trim());
    const index = remaining.findIndex((item) => item[fields[0]] === values[0]);
    const original = index >= 0 ? remaining.splice(index, 1)[0] : {};
    const parsed = Object.fromEntries(fields.map((field, index) => [
      field,
      field === "skills"
        ? splitValues(values[index] || "")
        : values[index] || (field === "year" ? null : ""),
    ]));
    return { ...original, ...parsed };
  });
}

function readBank() {
  const workExperience = [...document.querySelectorAll(".work-entry")].map((card) => {
    const value = (field) => card.querySelector(`[data-field="${field}"]`).value.trim();
    const skills = splitValues(value("skills"));
    const technologies = splitValues(value("technologies"));
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
    const value = (field) => card.querySelector(`[data-field="${field}"]`).value.trim();
    const skills = splitValues(value("skills"));
    const technologies = splitValues(value("technologies"));
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
    skills: splitValues(document.querySelector("#skills").value),
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

function showList(id, items) {
  const list = document.querySelector(`#${id}`);
  list.replaceChildren();
  (items.length ? items : ["None identified"]).forEach((item) => {
    const element = document.createElement("li");
    element.textContent = typeof item === "string" ? item : `${item.requirement}: ${item.explanation}`;
    list.append(element);
  });
}

function renderMatches(match) {
  showList("strong-matches", match.strong_matches);
  showList("related-matches", match.related_matches);
  showList("missing-requirements", match.missing_requirements);
  const ranked = document.querySelector("#ranked-evidence");
  ranked.replaceChildren();
  (match.ranked_evidence.length ? match.ranked_evidence : [{ explanation: "No relevant evidence found." }]).forEach((item) => {
    const element = document.createElement("li");
    element.textContent = item.evidence ? `${item.evidence.source_label}: ${item.evidence.text} (${item.explanation})` : item.explanation;
    ranked.append(element);
  });
}

document.querySelector("#add-work").addEventListener("click", () => addWorkExperience());
document.querySelector("#add-project").addEventListener("click", () => addProject());

bankForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!bankLoaded) {
    bankMessage.textContent = "Load your experience bank successfully before saving. Reload to retry.";
    return;
  }
  bankMessage.textContent = "Saving...";
  try {
    const saved = await request("/experience-bank", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readBank()),
    });
    populateBank(saved);
    bankMessage.textContent = "Experience bank saved.";
  } catch (error) {
    bankMessage.textContent = error.message;
  }
});

matchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  formError.hidden = true;
  const description = jobDescriptionInput.value.trim();
  if (description.length < MIN_DESCRIPTION_LENGTH) {
    formError.textContent = "Please enter at least 20 characters of job description.";
    formError.hidden = false;
    return;
  }
  setLoading(true);
  try {
    const analysis = await request("/analyse", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ job_description: description }) });
    document.querySelector("#job-title").textContent = analysis.job_title;
    showList("technical-skills", analysis.technical_skills);
    showList("other-keywords", analysis.other_keywords);
    showList("responsibilities", analysis.responsibilities);
    showList("qualifications", analysis.qualifications);
    renderMatches(await request("/match", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ job_analysis: analysis }) }));
    results.hidden = false;
  } catch (error) {
    formError.textContent = error.message || "Something went wrong. Please try again.";
    formError.hidden = false;
  } finally {
    setLoading(false);
  }
});

request("/experience-bank").then((bank) => {
  populateBank(bank);
  bankLoaded = true;
  saveBankButton.disabled = false;
}).catch((error) => {
  bankLoaded = false;
  saveBankButton.disabled = true;
  bankMessage.textContent = `Bank loading failed: ${error.message}. Reload to retry; saving is disabled.`;
});
