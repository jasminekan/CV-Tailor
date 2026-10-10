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

function addWorkExperience(work = {}) {
  const card = document.createElement("div");
  card.className = "editor-card work-entry";
  card.innerHTML = `<button class="remove-button" type="button">Remove</button>
    <div class="input-grid"><input data-field="employer" placeholder="Employer" value="${work.employer || ""}" required><input data-field="role" placeholder="Role" value="${work.role || ""}" required><input data-field="start_date" placeholder="Start date" value="${work.start_date || ""}"><input data-field="end_date" placeholder="End date" value="${work.end_date || ""}"></div>
    <input data-field="skills" placeholder="Role skills, comma separated" value="${(work.skills || []).join(", ")}">
    <input data-field="technologies" placeholder="Technologies, comma separated" value="${(work.technologies || []).join(", ")}">
    <textarea data-field="summary" rows="2" placeholder="Role summary">${work.summary || ""}</textarea>
    <textarea data-field="achievements" rows="3" placeholder="Achievements, one per line">${(work.achievements || []).map((item) => item.text).join("\n")}</textarea>`;
  card.querySelector(".remove-button").addEventListener("click", () => card.remove());
  document.querySelector("#work-list").append(card);
}

function addProject(project = {}) {
  const card = document.createElement("div");
  card.className = "editor-card project-entry";
  card.innerHTML = `<button class="remove-button" type="button">Remove</button>
    <input data-field="name" placeholder="Project name" value="${project.name || ""}" required>
    <input data-field="skills" placeholder="Skills, comma separated" value="${(project.skills || []).join(", ")}">
    <input data-field="technologies" placeholder="Technologies, comma separated" value="${(project.technologies || []).join(", ")}">
    <textarea data-field="description" rows="2" placeholder="Project description">${project.description || ""}</textarea>
    <textarea data-field="evidence" rows="3" placeholder="Your contributions, one per line">${(project.evidence || []).map((item) => item.text).join("\n")}</textarea>`;
  card.querySelector(".remove-button").addEventListener("click", () => card.remove());
  document.querySelector("#project-list").append(card);
}

function splitValues(value) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function makeEvidence(text, skills = [], technologies = []) {
  return { text: text.trim(), skills, technologies };
}

function parseLines(id, fields) {
  return document.querySelector(`#${id}`).value.split("\n").map((line) => {
    const values = line.split("|").map((value) => value.trim());
    return Object.fromEntries(fields.map((field, index) => [field, field === "skills" ? splitValues(values[index] || "") : values[index] || null]));
  }).filter((item) => item[fields[0]]);
}

function readBank() {
  const workExperience = [...document.querySelectorAll(".work-entry")].map((card) => {
    const value = (field) => card.querySelector(`[data-field="${field}"]`).value.trim();
    const skills = splitValues(value("skills"));
    const technologies = splitValues(value("technologies"));
    return { employer: value("employer"), role: value("role"), start_date: value("start_date") || null, end_date: value("end_date") || null, summary: value("summary"), skills, technologies, achievements: value("achievements").split("\n").map((text) => makeEvidence(text, skills, technologies)).filter((item) => item.text) };
  });
  const projects = [...document.querySelectorAll(".project-entry")].map((card) => {
    const value = (field) => card.querySelector(`[data-field="${field}"]`).value.trim();
    const skills = splitValues(value("skills"));
    const technologies = splitValues(value("technologies"));
    return { name: value("name"), description: value("description"), skills, technologies, evidence: value("evidence").split("\n").map((text) => makeEvidence(text, skills, technologies)).filter((item) => item.text) };
  });
  return { skills: splitValues(document.querySelector("#skills").value), work_experience: workExperience, projects, education: parseLines("education", ["qualification", "institution", "field", "year"]), certifications: parseLines("certifications", ["name", "issuer", "year", "skills"]), additional_evidence: document.querySelector("#additional-evidence").value.split("\n").map((text) => makeEvidence(text)).filter((item) => item.text) };
}

function populateBank(bank) {
  document.querySelector("#skills").value = bank.skills.join(", ");
  document.querySelector("#work-list").replaceChildren();
  document.querySelector("#project-list").replaceChildren();
  bank.work_experience.forEach(addWorkExperience);
  bank.projects.forEach(addProject);
  document.querySelector("#education").value = bank.education.map((item) => [item.qualification, item.institution, item.field, item.year].filter(Boolean).join(" | ")).join("\n");
  document.querySelector("#certifications").value = bank.certifications.map((item) => [item.name, item.issuer, item.year, (item.skills || []).join(", ")].filter(Boolean).join(" | ")).join("\n");
  document.querySelector("#additional-evidence").value = bank.additional_evidence.map((item) => item.text).join("\n");
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
  bankMessage.textContent = "Saving...";
  try {
    await request("/experience-bank", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(readBank()) });
    bankMessage.textContent = "Experience bank saved.";
  } catch (error) { bankMessage.textContent = error.message; }
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
  } finally { setLoading(false); }
});

request("/experience-bank").then(populateBank).catch((error) => { bankMessage.textContent = error.message; });
