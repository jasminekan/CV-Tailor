const form = document.querySelector("#analyse-form");
const descriptionInput = document.querySelector("#job-description");
const analyseButton = document.querySelector("#analyse-button");
const buttonLabel = document.querySelector("#button-label");
const loadingLabel = document.querySelector("#loading-label");
const formError = document.querySelector("#form-error");
const characterCount = document.querySelector("#character-count");
const results = document.querySelector("#results");

const MIN_DESCRIPTION_LENGTH = 20;

function updateCharacterCount() {
  const count = descriptionInput.value.length;
  characterCount.textContent = `${count.toLocaleString()} character${count === 1 ? "" : "s"}`;
}

function showError(message) {
  formError.textContent = message;
  formError.hidden = false;
}

function clearError() {
  formError.textContent = "";
  formError.hidden = true;
}

function renderList(elementId, items) {
  const list = document.querySelector(`#${elementId}`);
  list.replaceChildren();

  if (!items.length) {
    const emptyItem = document.createElement("li");
    emptyItem.className = "empty-list";
    emptyItem.textContent = "None identified";
    list.append(emptyItem);
    return;
  }

  items.forEach((item) => {
    const listItem = document.createElement("li");
    listItem.textContent = item;
    list.append(listItem);
  });
}

function renderResults(analysis) {
  document.querySelector("#job-title").textContent = analysis.job_title;
  renderList("technical-skills", analysis.technical_skills);
  renderList("other-keywords", analysis.other_keywords);
  renderList("responsibilities", analysis.responsibilities);
  renderList("qualifications", analysis.qualifications);
  results.hidden = false;
}

function setLoading(isLoading) {
  analyseButton.disabled = isLoading;
  buttonLabel.hidden = isLoading;
  loadingLabel.hidden = !isLoading;
}

descriptionInput.addEventListener("input", updateCharacterCount);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearError();

  const jobDescription = descriptionInput.value.trim();
  if (!jobDescription) {
    showError("Paste a job description before analysing it.");
    descriptionInput.focus();
    return;
  }

  if (jobDescription.length < MIN_DESCRIPTION_LENGTH) {
    showError("Please enter at least 20 characters of job description.");
    descriptionInput.focus();
    return;
  }

  setLoading(true);

  try {
    const response = await fetch("/analyse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_description: jobDescription }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "The job description could not be analysed.");
    }

    renderResults(data);
  } catch (error) {
    showError(error.message || "Something went wrong. Please try again.");
  } finally {
    setLoading(false);
  }
});

updateCharacterCount();