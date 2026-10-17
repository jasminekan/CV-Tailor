// Read-only presentation of one response snapshot; no selection or persistence.
(() => {
  const find = selector => document.querySelector(selector);
  const panel = find("#tailoring-preview");
  const button = find("#generate-tailored-preview");
  const state = find("#tailoring-state");
  const error = find("#tailoring-error");
  const output = find("#tailoring-output");
  const empty = find("#tailoring-empty");
  let analysis = null;
  let revision = null;
  let requestVersion = 0;
  let pending = false;
  let analysing = false;

  const types = { work_experience: "Work role", achievement: "Achievement", project: "Project",
    project_evidence: "Contribution", skill: "Skill", education: "Education", certification: "Certification" };
  const origins = { wording: "Original wording", outcome: "Recorded outcome", standalone_skill: "Declared skill",
    skill_tag: "Skill tag", technology_tag: "Technology tag", credential: "Credential" };
  const statuses = { strong: "Strong support", related: "Related support", missing: "Not evidenced in bank",
    not_selected: "Not represented in work/projects" };
  const importance = value => ({ required: "Required", preferred: "Preferred", unspecified: "Importance unspecified" }[value] || "Importance unspecified");
  const key = (type, id) => JSON.stringify([type, id]);
  const credential = item => ["education", "certification"].includes(item.source_type);

  function reset() {
    requestVersion += 1;
    pending = false;
    analysis = null;
    revision = null;
    analysing = false;
    panel.hidden = true;
    panel.setAttribute("aria-busy", "false");
    output.hidden = true;
    empty.hidden = false;
    error.hidden = true;
    state.textContent = "";
    button.disabled = true;
    button.textContent = "Generate Tailored CV Preview";
    find("#tailoring-coverage-title").textContent = "Requirement coverage";
    for (const id of ["tailored-cv-content", "tailoring-coverage", "tailoring-decisions", "tailoring-summary", "tailoring-warnings", "tailoring-target"]) find(`#${id}`).replaceChildren();
    window.dispatchEvent(new CustomEvent("tailoring-preview-state", { detail: { pending: false, ready: false } }));
  }

  window.addEventListener("job-analysis-invalidated", reset);
  window.addEventListener("job-workspace-reset", reset);
  window.addEventListener("job-analysis-started", event => {
    reset();
    revision = event.detail.revision;
    analysing = true;
  });
  window.addEventListener("job-analysis-ready", event => {
    if (event.detail.revision !== revision) return;
    analysis = JSON.parse(JSON.stringify(event.detail.analysis));
    panel.hidden = false;
    find("#tailoring-target").textContent = `For: ${analysis.job_title}`;
    state.textContent = "Finishing job matching…";
  });
  window.addEventListener("job-analysis-finished", event => {
    if (event.detail.revision !== revision) return;
    analysing = false;
    button.disabled = !analysis;
    if (analysis) state.textContent = "Ready to generate a preview from this analysis.";
  });

  function context(data) {
    const records = new Map();
    const add = (type, record, parent) => records.set(key(type, record.id), { record, parent });
    for (const role of data.source_bank.work_experience) {
      add("work_experience", role);
      for (const item of role.achievements) add("achievement", item, role);
    }
    for (const project of data.source_bank.projects) {
      add("project", project);
      for (const item of project.evidence) add("project_evidence", item, project);
    }
    for (const item of data.source_bank.education) add("education", item);
    for (const item of data.source_bank.certifications) add("certification", item);
    const requirements = new Map();
    for (const row of [...data.matching_result.strong_matches, ...data.matching_result.related_matches, ...data.matching_result.missing_requirements]) {
      if (row.requirement_details) requirements.set(row.requirement_details.id, row.requirement_details);
    }
    const labels = new Set(data.source_bank.skills);
    const tags = record => [...(record.skills || []), ...(record.technologies || [])].forEach(label => labels.add(label));
    for (const role of data.source_bank.work_experience) { tags(role); role.achievements.forEach(tags); }
    for (const project of data.source_bank.projects) { tags(project); project.evidence.forEach(tags); }
    data.source_bank.certifications.forEach(tags);
    data.source_bank.additional_evidence.forEach(tags);
    // The backend supplies canonical key -> original catalogue label. Validate
    // against the same snapshot's explicit labels without new normalisation rules.
    const skills = new Map(data.decisions.filter(item => item.source_type === "skill" && labels.has(item.original_text))
      .map(item => [item.source_id, item.original_text]));
    return { records, requirements, skills };
  }

  function originalFields(target, record, fields) {
    for (const field of fields) {
      if (record[field] !== null && record[field] !== undefined && record[field] !== "") {
        target.append(node("p", record[field], `cv-source-text cv-field-${field}`));
      }
    }
  }

  function renderCV(data, ctx, warnings) {
    const target = find("#tailored-cv-content");
    target.replaceChildren();
    function section(name, title) {
      const result = node("section");
      result.dataset.tailoredSection = name;
      result.append(node("h3", title));
      target.append(result);
      return result;
    }
    let displayed = 0;
    for (const config of [
      { field: "work_experience", title: "Work Experience", type: "work_experience", id: "work_experience_id", children: "achievements", ids: "achievement_ids", heading: "role", fields: ["employer", "start_date", "end_date", "summary"] },
      { field: "projects", title: "Projects", type: "project", id: "project_id", children: "evidence", ids: "contribution_ids", heading: "name", fields: ["description", "link"] },
    ]) {
      const selections = data.proposed_cv[config.field];
      if (!selections.length) continue;
      const area = section(config.field, config.title);
      for (const selection of selections) {
        const id = selection[config.id];
        const source = ctx.records.get(key(config.type, id));
        if (!source) { warnings.push(`A selected ${types[config.type].toLowerCase()} is unavailable in this snapshot (${id}). It was not displayed.`); continue; }
        const card = node("article");
        card.dataset.tailoredParentId = id;
        card.append(node("h4", source.record[config.heading], "cv-source-text"));
        originalFields(card, source.record, config.fields);
        const list = node("ul");
        for (const childId of selection[config.ids]) {
          const child = source.record[config.children].find(item => item.id === childId);
          if (!child) { warnings.push(`Selected content is unavailable under its returned parent (${childId}). It was not relocated or displayed.`); continue; }
          const item = node("li");
          item.dataset.tailoredBulletId = childId;
          item.append(node("span", child.text, "cv-source-text"));
          list.append(item);
        }
        card.append(list);
        area.append(card);
        displayed += 1;
      }
      if (area.children.length === 1) area.remove();
    }
    for (const [field, title, heading, fields] of [
      ["education", "Education", "qualification", ["institution", "field", "year"]],
      ["certifications", "Certifications", "name", ["issuer", "year"]],
    ]) {
      if (!data.source_bank[field].length) continue;
      const area = section(field, title);
      for (const record of data.source_bank[field]) {
        const card = node("article");
        card.dataset.tailoredRecordId = record.id;
        card.append(node("h4", record[heading], "cv-source-text"));
        originalFields(card, record, fields);
        if (record.skills?.length) {
          const list = node("ul");
          record.skills.forEach(label => list.append(node("li", label, "cv-source-text")));
          card.append(list);
        }
        area.append(card);
        displayed += 1;
      }
    }
    if (data.proposed_cv.skill_groups.length) {
      const area = section("skills", "Skills");
      for (const group of data.proposed_cv.skill_groups) {
        const card = node("article");
        card.append(node("h4", group.name, "cv-source-text"));
        const list = node("ul", undefined, "tailored-skills");
        for (const skillKey of group.skill_keys) {
          if (!ctx.skills.has(skillKey)) { warnings.push(`A selected skill label is unavailable in this snapshot (${skillKey}). It was not inferred or displayed.`); continue; }
          const item = node("li");
          item.dataset.tailoredSkillKey = skillKey;
          item.append(node("span", ctx.skills.get(skillKey), "cv-source-text"));
          list.append(item);
        }
        if (list.children.length) { card.append(list); area.append(card); displayed += 1; }
      }
      if (area.children.length === 1) area.remove();
    }
    if (!displayed) target.append(node("p", "No CV content was selected. Review the saved baseline, available content and tailoring limits.", "muted"));
  }

  function renderCoverage(data, ctx) {
    const target = find("#tailoring-coverage");
    target.replaceChildren();
    find("#tailoring-coverage-title").textContent = `Requirement coverage (${data.coverage.length})`;
    const match = data.matching_result;
    target.append(node("p", `Experience Bank: ${match.strong_matches.length} strong · ${match.related_matches.length} related · ${match.missing_requirements.length} not evidenced.`));
    const count = status => data.coverage.filter(row => row.selected_status === status).length;
    target.append(node("p", `Selected work/projects: ${count("strong")} strong · ${count("related")} related · ${count("not_selected")} not represented.`));
    if (!data.coverage.length) { target.append(node("p", "No job requirements were reported.", "muted")); return; }
    const list = node("ul", undefined, "tailoring-coverage-list");
    for (const row of data.coverage) {
      const requirement = row.requirement_details || ctx.requirements.get(row.requirement_id);
      const line = node("li");
      line.dataset.coverageRequirementId = row.requirement_id;
      line.append(node("h5", requirement?.text || row.requirement_id, "cv-source-text"), node("p", importance(requirement?.importance), "muted"),
        node("p", `Bank evidence: ${statuses[row.bank_status] || "Support not reported"}`));
      const selected = node("div");
      selected.append(node("p", `Selected work/projects: ${statuses[row.selected_status] || "Support not reported"}`));
      if (row.selected_status !== "not_selected" && !row.meaningful_evidence_ids.length) selected.append(node("p", "Declarations only; practical activity is not established.", "muted"));
      const skillKeys = data.skill_coverage.find(item => item.requirement_id === row.requirement_id)?.selected_skill_keys || [];
      const labels = skillKeys.filter(id => ctx.skills.has(id)).map(id => ctx.skills.get(id));
      if (labels.length) selected.append(node("p", `Recorded skills: ${labels.join(", ")}`, "cv-source-text muted"));
      const credentials = data.decisions.filter(item => item.selected && credential(item)
        && ctx.records.has(key(item.source_type, item.source_id)) && item.supported_requirement_ids.includes(row.requirement_id));
      credentials.forEach(item => selected.append(node("p", `${types[item.source_type]}: ${item.original_text}`, "cv-source-text muted")));
      line.append(selected);
      list.append(line);
    }
    target.append(list);
  }

  function renderDecisions(data, ctx, warnings) {
    const target = find("#tailoring-decisions");
    target.replaceChildren();
    const summary = find("#tailoring-summary");
    summary.replaceChildren();
    const groups = [
      ["Retained from Current CV", "retained", item => item.selected && item.was_in_current_cv && !credential(item)],
      ["Recommended from Experience Bank", "recommended", item => item.selected && !item.was_in_current_cv && !credential(item)],
      ["Omitted from Current CV", "omitted", item => !item.selected && item.was_in_current_cv],
      ["Other bank content not selected", "other", item => !item.selected && !item.was_in_current_cv],
      ["Education and certifications unchanged", "credentials", item => item.selected && credential(item)],
    ];
    for (const [title, group, include] of groups) {
      const items = data.decisions.filter(include);
      if (["retained", "recommended", "omitted"].includes(group)) {
        const count = node("p");
        count.dataset.selectionSummary = group;
        count.append(node("strong", String(items.length)), node("span", group === "recommended" ? "Newly recommended" : group === "retained" ? "Retained" : "Omitted baseline"));
        summary.append(count);
      }
      if (!items.length) continue;
      const list = node("div", undefined, "tailoring-decision-list");
      for (const item of items) {
        const source = ctx.records.get(key(item.source_type, item.source_id));
        const record = source?.record;
        const parent = source?.parent;
        if (!types[item.source_type]) warnings.push("Some recommendation content has no supported CV destination. It is shown only in the changes area.");
        const missingCredential = item.selected && credential(item) && !source;
        if (missingCredential) warnings.push("A selected credential is unavailable in this snapshot. It was not displayed in the CV or counted as a displayed credential in coverage.");
        const label = record?.role || record?.name || parent?.role || parent?.name || types[item.source_type] || "Other content";
        const card = node("details", undefined, "tailoring-decision");
        card.dataset.decisionId = item.source_id;
        card.dataset.decisionType = item.source_type;
        const heading = node("summary");
        heading.append(node("span", label === types[item.source_type] ? label : `${types[item.source_type] || "Content"}: ${label}`, "tailoring-decision-context cv-source-text"),
          node("span", item.original_text ?? `Unavailable reference (${item.source_id}).`, "tailoring-decision-excerpt cv-source-text"));
        card.append(heading);
        const body = node("div", undefined, "tailoring-decision-body");
        if (item.original_text !== null) body.append(node("p", item.original_text, "cv-source-text"));
        else body.append(node("p", `Unavailable reference (${item.source_id}).`, "muted"));
        body.append(node("p", item.recommendation));
        if (missingCredential) body.append(node("p", "This credential reference is unavailable in the source snapshot; it is not shown in the proposed CV.", "muted"));
        if (item.group_name || item.previous_group_name) body.append(node("p", `Skill group: ${item.group_name || item.previous_group_name}`, "cv-source-text muted"));
        const requirements = node("ul");
        for (const id of item.supported_requirement_ids) {
          const requirement = ctx.requirements.get(id);
          const entry = node("li");
          entry.append(node("p", `${requirement?.text || id} · ${importance(item.requirement_importance[id])}`, "cv-source-text"));
          for (const support of item.evidence_support.filter(value => value.requirement_id === id)) {
            const originLabels = [...new Set(support.signals.map(signal => origins[signal.origin] || "Other recorded source"))];
            entry.append(node("p", `${statuses[support.status] || "Support not reported"} for this requirement · ${originLabels.join(", ")}`),
              node("p", `Matched option: ${support.selected_alternative}`, "cv-source-text"), node("p", support.explanation));
          }
          requirements.append(entry);
        }
        body.append(requirements);
        if (item.bundle_evidence_ids.length) body.append(node("p", "Project support can include its selected contributions; each contribution retains its own evidence.", "muted"));
        card.append(body);
        list.append(card);
      }
      const groupArea = disclosure(`${title} (${items.length})`, list);
      groupArea.className = "tailoring-decision-group";
      groupArea.dataset.selectionGroup = group;
      target.append(groupArea);
    }
    if (!target.children.length) target.append(node("p", "No content decisions were reported.", "muted"));
  }

  function render(data) {
    const ctx = context(data);
    const warnings = [];
    const messages = {
      baseline_reference_issues: "Some saved Current CV references are stale or unavailable. No saved references were repaired.",
      matching_metadata_unavailable: "Some matching metadata is unavailable; relevance explanations are limited.",
      ambiguous_skill_identity: "Some skill evidence could not be attributed to one explicit skill. No skill identity was guessed.",
    };
    for (const value of data.warnings) warnings.push(messages[value] || "The preview reports a limitation; review the returned recommendations.");
    for (const issue of data.reference_issues) warnings.push(`${issue.reason} (${issue.reference})`);
    if (!data.decisions.some(item => item.was_in_current_cv && !credential(item))) warnings.push("No baseline work, project or skill selections were reported. A missing or empty Current CV does not introduce work roles.");
    if (data.matching_result.missing_requirements.length) warnings.push("Some job requirements have no recorded bank evidence. This does not establish a lack of experience.");
    if (!data.matching_result.strong_matches.length && data.matching_result.related_matches.length) warnings.push("Only related bank evidence was reported. Review the evidence caveats before using these recommendations.");
    if (data.coverage.some(row => row.bank_status !== "missing" && row.selected_status === "not_selected" && row.requirement_details?.category !== "qualification")) warnings.push("Some bank-supported requirements are not represented in selected work/projects. Review limits, selected skills and the recommendations.");
    renderCV(data, ctx, warnings);
    renderCoverage(data, ctx);
    renderDecisions(data, ctx, warnings);
    const target = find("#tailoring-warnings");
    target.replaceChildren();
    const unique = [...new Set(warnings)];
    if (unique.length) {
      const list = node("ul"); unique.forEach(value => list.append(node("li", value))); target.append(node("h4", "Notes & limitations"), list);
    }
    target.hidden = !unique.length;
  }

  button.addEventListener("click", async () => {
    if (!analysis || pending || analysing) return;
    const version = ++requestVersion;
    const hadPreview = !output.hidden;
    pending = true;
    button.disabled = true;
    panel.setAttribute("aria-busy", "true");
    state.textContent = "Generating tailored CV preview…";
    error.hidden = true;
    output.hidden = true;
    empty.hidden = true;
    window.dispatchEvent(new CustomEvent("tailoring-preview-state", { detail: { pending: true, ready: false } }));
    let rendering = false;
    try {
      const data = await request("/tailoring/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ job_analysis: analysis }) });
      if (version !== requestVersion) return;
      rendering = true;
      render(data);
      output.hidden = false;
      state.textContent = "Preview ready. No changes have been saved or applied.";
      button.textContent = "Regenerate Preview";
    } catch (failure) {
      if (version !== requestVersion) return;
      // Only restore a preceding response if rendering has not touched its DOM.
      const keepPreview = hadPreview && !rendering;
      output.hidden = !keepPreview;
      empty.hidden = keepPreview;
      error.textContent = failure.message || "The preview could not be generated. Please try again.";
      error.hidden = false;
      state.textContent = keepPreview
        ? "Regeneration failed. Showing the previous successful preview for this job analysis; saved content may have changed. Retry to refresh it."
        : "Your job analysis is still available. You can retry the preview.";
    } finally {
      if (version === requestVersion) {
        pending = false;
        button.disabled = !analysis || analysing;
        panel.setAttribute("aria-busy", "false");
        window.dispatchEvent(new CustomEvent("tailoring-preview-state", { detail: { pending: false, ready: !output.hidden } }));
      }
    }
  });
})();
