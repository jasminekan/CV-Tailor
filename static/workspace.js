// View availability only. Feature modules continue to own data, drafts and requests.
(() => {
  const find = selector => document.querySelector(selector);
  const destinations = [
    ["tailor", "#show-workspace", "#workspace-view", "Tailor CV", "Understand the job, review your evidence and focus your CV."],
    ["bank", "#show-bank", "#bank-view", "Experience Bank", "Keep your experience, achievements and skills in one place."],
    ["cv", "#show-current-cv", "#current-cv-view", "My CV", "Manage the content and structure of your baseline CV."],
  ];
  const steps = ["analyse", "match", "tailor"];
  let view = "tailor";
  let stage = "analyse";
  let revision = null;
  let analysisReady = false;
  let matchReady = false;
  let jobPending = false;
  let previewPending = false;
  let previewReady = false;
  let matchFailed = false;
  const locked = () => Boolean(find("#current-cv-form").inert);

  function closeMenu() {
    find("#app-navigation").dataset.open = "false";
    find("#toggle-navigation").setAttribute("aria-expanded", "false");
  }

  function render() {
    for (const [name, button, panel, title, description] of destinations) {
      find(button).setAttribute("aria-pressed", String(view === name));
      find(button).disabled = locked();
      find(panel).hidden = view !== name;
      if (view === name) {
        find("#page-title").textContent = title;
        find("#page-description").textContent = description;
        find("#page-context").textContent = name === "tailor" ? "Your next opportunity" : "My content";
        find("#workspace-location").textContent = `${name === "tailor" ? "Workspace" : "My content"} / ${title}`;
      }
    }
    for (const name of steps) {
      const button = find(`#stage-${name}`);
      button.disabled = locked() || (name !== "analyse" && !analysisReady);
      if (stage === name) button.setAttribute("aria-current", "step");
      else button.removeAttribute("aria-current");
      find(`#${name}-stage`).hidden = stage !== name;
    }
    find("#new-analysis").disabled = locked();
    find("#continue-to-match").disabled = locked() || !matchReady;
    find("#match-generate-preview").disabled = locked() || !analysisReady || jobPending || previewPending;
    find("#match-empty").hidden = matchReady;
    find("#match-empty").textContent = matchFailed
      ? "Matching could not be completed. Your analysis is still available; you can retry Analyse Job or generate a preview."
      : "Matching your saved experience… Results will appear here when ready.";
    find("#workflow-state").textContent = jobPending ? analysisReady ? "Analysis ready. Matching your saved experience…" : "Analysing the job description…"
      : !analysisReady ? "Start with a job description. Match and Tailor become available after analysis."
      : matchFailed ? "Analysis ready. Matching could not be completed; your extracted analysis has been kept."
      : previewPending ? "Generating a read-only tailored preview…"
      : previewReady ? "Your tailored preview is ready. Review it or return to an earlier stage."
      : "Analysis ready. Review your matches, then generate a read-only tailored preview.";
  }

  function navigate(destination, nextStage = stage) {
    if (locked() || !destinations.some(item => item[0] === destination)) return;
    if (!steps.includes(nextStage) || (nextStage !== "analyse" && !analysisReady)) return;
    const changed = view !== destination;
    view = destination;
    stage = nextStage;
    closeMenu();
    render();
    // Management refresh/load remains owned by the feature, never by navigation.
    if (changed) window.dispatchEvent(new CustomEvent("workspace-view-changed", { detail: { view } }));
    if (destination === "tailor") find(`#stage-${stage}`).focus();
    else find("#page-title").focus();
  }

  destinations.forEach(([name, button]) => find(button).addEventListener("click", () => navigate(name)));
  steps.forEach(name => find(`#stage-${name}`).addEventListener("click", () => navigate("tailor", name)));
  find("#continue-to-match").addEventListener("click", () => { if (matchReady) navigate("tailor", "match"); });
  find("#edit-job").addEventListener("click", () => navigate("tailor", "analyse"));
  find("#match-generate-preview").addEventListener("click", () => {
    if (locked() || !analysisReady || jobPending || previewPending) return;
    navigate("tailor", "tailor");
    find("#generate-tailored-preview").click();
  });
  find("#toggle-navigation").addEventListener("click", () => {
    const open = find("#app-navigation").dataset.open !== "true";
    find("#app-navigation").dataset.open = String(open);
    find("#toggle-navigation").setAttribute("aria-expanded", String(open));
  });
  find("#app-navigation").addEventListener("keydown", event => {
    if (event.key === "Escape") { closeMenu(); find("#toggle-navigation").focus(); }
  });
  find("#new-analysis").addEventListener("click", () => {
    if (locked()) return;
    const meaningful = find("#job-description").value.trim() || !find("#analysis-result").hidden
      || analysisReady || jobPending || previewPending || previewReady;
    if (meaningful && !window.confirm("Start a new analysis? This clears the job description, analysis, matches and tailored preview. Your saved content and management drafts will be kept.")) return;
    window.dispatchEvent(new CustomEvent("job-workspace-reset"));
    navigate("tailor", "analyse");
    find("#job-description").focus();
  });

  function invalidate() {
    revision = null;
    analysisReady = false;
    matchReady = false;
    jobPending = false;
    previewPending = false;
    previewReady = false;
    matchFailed = false;
    stage = "analyse";
    render();
  }
  window.addEventListener("job-analysis-invalidated", invalidate);
  window.addEventListener("job-workspace-reset", invalidate);
  window.addEventListener("job-analysis-started", event => {
    invalidate(); revision = event.detail.revision; jobPending = true; render();
  });
  window.addEventListener("job-analysis-ready", event => {
    if (event.detail.revision !== revision) return;
    analysisReady = true; render();
  });
  window.addEventListener("job-match-ready", event => {
    if (event.detail.revision !== revision) return;
    matchReady = true; render();
  });
  window.addEventListener("job-analysis-failed", event => {
    if (event.detail.revision !== revision) return;
    matchFailed = analysisReady; render();
  });
  window.addEventListener("job-analysis-finished", event => {
    if (event.detail.revision !== revision) return;
    jobPending = false; render();
  });
  window.addEventListener("tailoring-preview-state", event => {
    previewPending = event.detail.pending; previewReady = event.detail.ready; render();
  });
  window.addEventListener("current-cv-controls-changed", render);
  render();
})();
