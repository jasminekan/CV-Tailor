// Current CV state is independent of the experience-bank editor.
(() => {
  const find = selector => document.querySelector(selector);
  const form = find("#current-cv-form");
  const fields = find("#current-cv-fields");
  const saveButton = find("#save-current-cv");
  const retryButton = find("#retry-current-cv");
  const message = find("#current-cv-message");
  const warnings = find("#current-cv-warnings");
  let bank = null;
  let draft = null;
  let baseline = null;
  let bankReady = false;
  let cvReady = false;
  let loading = false;
  let savingCV = false;
  let serverIssues = [];
  let skillCatalogue = new Map();
  let settingEdits = {};
  let settingErrors = {};
  const clone = value => JSON.parse(JSON.stringify(value));
  const ready = () => bankReady && cvReady && draft !== null;
  const dirty = () => draft !== null && (JSON.stringify(draft) !== baseline || Object.keys(settingErrors).length > 0);
  const settingFields = [
    ["max_achievements_per_role", "Maximum achievements per work experience role"],
    ["max_contributions_per_project", "Maximum contributions per project"],
    ["max_projects", "Maximum number of projects"],
    ["max_skills", "Maximum number of skills"],
  ];
  const sections = [
    {
      key: "work_experience", parentKey: "work_experience_id", bulletKey: "achievement_ids",
      children: "achievements", name: "experience", bulletName: "bullet point",
      addLabel: "Add Experience", addBulletLabel: "Add Bullet Point",
      picker: "#cv-add-work", list: "#cv-work-list",
      label: record => `${record.role} at ${record.employer}`,
    },
    {
      key: "projects", parentKey: "project_id", bulletKey: "contribution_ids",
      children: "evidence", name: "project", bulletName: "contribution",
      addLabel: "Add Project", addBulletLabel: "Add Contribution",
      picker: "#cv-add-project", list: "#cv-project-list", label: record => record.name,
    },
  ];

  function element(tag, text, className) {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    if (className) result.className = className;
    return result;
  }

  function normaliseSkillKey(value) {
    // Python str.split() whitespace, including separators JS \s omits, and
    // excluding the BOM that JS trim() removes. Keep punctuation unchanged.
    return value.replace(/[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/g, " ").replace(/^ | $/g, "").toLowerCase();
  }

  function buildSkillCatalogue(savedBank) {
    const catalogue = new Map();
    const collect = labels => (labels || []).forEach(label => {
      const key = normaliseSkillKey(label);
      if (!catalogue.has(key)) catalogue.set(key, label);
    });
    const tags = record => { collect(record.skills); collect(record.technologies); };
    collect(savedBank.skills);
    (savedBank.work_experience || []).forEach(work => {
      tags(work);
      (work.achievements || []).forEach(tags);
    });
    (savedBank.projects || []).forEach(project => {
      tags(project);
      (project.evidence || []).forEach(tags);
    });
    (savedBank.certifications || []).forEach(record => collect(record.skills));
    (savedBank.additional_evidence || []).forEach(tags);
    return catalogue;
  }

  function setBank(savedBank) {
    bank = clone(savedBank);
    skillCatalogue = buildSkillCatalogue(bank);
    bankReady = true;
    clearSelectionIssues();
  }

  function inputIssues() {
    if (!draft) return [];
    const issues = [];
    const names = new Set();
    draft.skill_groups.forEach((group, index) => {
      const name = normaliseSkillKey(group.name);
      if (!name) issues.push({ path: `skill_groups[${index}].name`, reason: "Enter a nonblank group heading." });
      else if (names.has(name)) issues.push({ path: `skill_groups[${index}].name`, reason: "Group headings must be unique, ignoring case and whitespace." });
      names.add(name);
    });
    settingFields.forEach(([key]) => {
      const reason = settingError(key);
      if (reason) issues.push({ path: `tailoring_settings.${key}`, reason });
    });
    return issues;
  }

  function settingError(key) {
    const value = draft?.tailoring_settings[key];
    return settingErrors[key] || (value != null && !Number.isSafeInteger(value) ? "This saved limit is too large. Choose a smaller whole number or no limit." : "");
  }

  async function fetchJSON(url, options) {
    const response = await fetch(url, options);
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error("The server returned an unreadable response.");
    }
    if (!response.ok) {
      const error = new Error(typeof data.detail === "string" ? data.detail : "The request could not be completed.");
      error.details = data.detail;
      throw error;
    }
    return data;
  }

  function locationLabel(path) {
    const work = path.match(/^work_experience\[(\d+)\](?:\.achievement_ids\[(\d+)\])?/);
    if (work) return `Work experience ${Number(work[1]) + 1}${work[2] !== undefined ? `, bullet ${Number(work[2]) + 1}` : ""}`;
    const project = path.match(/^projects\[(\d+)\](?:\.contribution_ids\[(\d+)\])?/);
    if (project) return `Project ${Number(project[1]) + 1}${project[2] !== undefined ? `, contribution ${Number(project[2]) + 1}` : ""}`;
    const group = path.match(/^skill_groups\[(\d+)\](?:\.skill_keys\[(\d+)\])?/);
    if (group) return `Skill group ${Number(group[1]) + 1}${group[2] !== undefined ? `, skill ${Number(group[2]) + 1}` : ""}`;
    const setting = settingFields.find(([key]) => path === `tailoring_settings.${key}`);
    return setting ? setting[1] : path.startsWith("tailoring_settings") ? "Tailoring settings" : "Current CV";
  }

  function showMessage(text, error = null) {
    message.replaceChildren(element("p", text));
    message.className = error ? "message error" : "message";
    message.setAttribute("role", error ? "alert" : "status");
    if (Array.isArray(error?.details)) {
      const list = element("ul");
      for (const issue of error.details) {
        const path = issue.path || (issue.loc || []).filter(part => part !== "body").reduce(
          (value, part) => typeof part === "number" ? `${value}[${part}]` : `${value}${value ? "." : ""}${part}`, "",
        );
        list.append(element("li", `${locationLabel(path)}: ${issue.reason || issue.msg || "Invalid selection."}`));
      }
      message.append(list);
    } else if (error) {
      message.append(element("p", error.message));
    }
  }

  function updateControls() {
    const busy = loading || savingCV;
    saveButton.disabled = !ready() || busy || inputIssues().length > 0;
    fields.disabled = !ready() || busy;
    form.inert = savingCV;
    form.setAttribute("aria-busy", String(busy));
    retryButton.hidden = ready();
    retryButton.disabled = busy;
    window.dispatchEvent(new CustomEvent("current-cv-controls-changed"));
    find("#current-cv-state").textContent = savingCV ? "Saving…" : loading ? "Loading…" : !ready() ? "Loading incomplete — saving disabled" : dirty() ? "Unsaved changes" : "Saved";
  }

  function selectedBulletIds() {
    return new Set(sections.flatMap(section => (draft?.[section.key] || []).flatMap(selection => selection[section.bulletKey])));
  }

  function recordsFor(section) {
    return bank?.[section.key] || [];
  }

  function availableParents(section, currentId = null) {
    const selected = new Set((draft?.[section.key] || []).map(selection => selection[section.parentKey]));
    return recordsFor(section).filter(record => !selected.has(record.id) || record.id === currentId);
  }

  function availableBullets(section, record, currentId = null) {
    const selected = selectedBulletIds();
    return (record?.[section.children] || []).filter(item => !selected.has(item.id) || item.id === currentId);
  }

  function change(action, focusKey) {
    if (!ready() || loading || savingCV) return;
    action();
    clearSelectionIssues();
    message.replaceChildren();
    render();
    // Focus keys contain only section names, indices and control names.
    if (focusKey) find(`[data-cv-focus="${focusKey}"]`)?.focus();
  }

  function button(text, action, disabled = false, focusKey = null) {
    const result = element("button", text, "secondary-button");
    result.type = "button";
    result.disabled = disabled;
    if (focusKey) result.dataset.cvFocus = focusKey;
    result.addEventListener("click", action);
    return result;
  }

  function selectOptions(records, label, placeholder, currentId = "") {
    const select = element("select");
    select.setAttribute("aria-label", placeholder);
    const initial = element("option", placeholder);
    initial.value = "";
    initial.disabled = true;
    select.append(initial);
    for (const record of records) {
      const option = element("option", label(record));
      option.value = record.id;
      select.append(option);
    }
    if (currentId && !records.some(record => record.id === currentId)) {
      const missing = element("option", `Unavailable selection (${currentId}) — choose a replacement`);
      missing.value = currentId;
      missing.disabled = true;
      select.append(missing);
    }
    select.value = currentId;
    return select;
  }

  function picker(target, records, label, placeholder, actionLabel, onSelect) {
    const row = element("div", undefined, "cv-picker");
    const select = selectOptions(records, label, placeholder);
    const add = button(actionLabel, () => {
      if (records.some(record => record.id === select.value)) onSelect(select.value);
    }, true);
    select.disabled = records.length === 0;
    select.addEventListener("change", () => { add.disabled = !select.value; });
    row.append(select, add);
    target.append(row);
    if (!records.length) target.append(element("p", "No more saved records available to select.", "muted"));
  }

  function orderingControls(items, index, section, kind, remove) {
    const row = element("div", undefined, "cv-controls");
    const key = `${section.key}-${kind}`;
    const move = direction => {
      const destination = index + direction;
      if (destination < 0 || destination >= items.length) return;
      const nextControl = destination === 0 ? "down" : destination === items.length - 1 ? "up" : direction < 0 ? "up" : "down";
      change(() => {
        [items[index], items[destination]] = [items[destination], items[index]];
      }, `${key}-${destination}-${nextControl}`);
    };
    row.append(
      button("Move Up", () => move(-1), index === 0, `${key}-${index}-up`),
      button("Move Down", () => move(1), index === items.length - 1, `${key}-${index}-down`),
      button(remove, () => change(() => items.splice(index, 1))),
    );
    return row;
  }

  function referenceIssues() {
    // Local checks are UI guidance; PUT validates every reference.
    const issues = [...serverIssues];
    if (!bankReady || !draft) return issues;
    const report = issue => { if (!issues.some(existing => existing.path === issue.path)) issues.push(issue); };
    for (const section of sections) {
      draft[section.key].forEach((selection, index) => {
        const record = recordsFor(section).find(item => item.id === selection[section.parentKey]);
        const path = `${section.key}[${index}]`;
        if (!record) report({ path: `${path}.${section.parentKey}`, reason: `The selected ${section.name} is missing from your saved bank.` });
        selection[section.bulletKey].forEach((id, bulletIndex) => {
          if (!record?.[section.children].some(item => item.id === id)) {
            report({ path: `${path}.${section.bulletKey}[${bulletIndex}]`, reason: `This ${section.bulletName} is missing or no longer belongs to the selected ${section.name}.` });
          }
        });
      });
    }
    draft.skill_groups.forEach((group, groupIndex) => {
      group.skill_keys.forEach((key, skillIndex) => {
        if (!skillCatalogue.has(key)) report({ path: `skill_groups[${groupIndex}].skill_keys[${skillIndex}]`, reason: `Skill (${key}) is unavailable in the saved bank. Remove it or choose a replacement.` });
      });
    });
    return issues;
  }

  function clearSelectionIssues() {
    // Selection paths can change after editing/reordering; recompute their UI
    // warnings from the bank. PUT remains the final authority.
    serverIssues = serverIssues.filter(issue => !["work_experience", "projects", "skill_groups"].some(prefix => issue.path?.startsWith(prefix)));
  }

  function renderWarnings() {
    warnings.replaceChildren();
    const issues = [...referenceIssues(), ...inputIssues()];
    warnings.hidden = !issues.length;
    if (!issues.length) return;
    warnings.append(element("p", "Some selections or inputs need attention. Unavailable references have been kept in your CV; remove them or choose replacements. Correct invalid headings or limits before saving."));
    const list = element("ul");
    issues.forEach(issue => list.append(element("li", `${locationLabel(issue.path || "")}: ${issue.reason}`)));
    warnings.append(list);
  }

  function renderSection(section) {
    const addTarget = find(section.picker);
    const list = find(section.list);
    addTarget.replaceChildren();
    list.replaceChildren();
    if (!draft) return;
    const selections = draft[section.key];
    picker(addTarget, availableParents(section), section.label, `Choose ${section.name}`, section.addLabel, id => change(() => {
      if (!selections.some(selection => selection[section.parentKey] === id)) selections.push({ [section.parentKey]: id, [section.bulletKey]: [] });
    }));
    if (!selections.length) list.append(element("p", `No ${section.name === "experience" ? "work experience" : "projects"} selected.`, "muted"));
    selections.forEach((selection, index) => {
      const id = selection[section.parentKey];
      const record = recordsFor(section).find(item => item.id === id);
      const card = element("article", undefined, record ? "cv-card" : "cv-card cv-missing");
      card.dataset.parentId = id;
      card.append(element("h4", record ? section.label(record) : `Unavailable ${section.name} (${id})`));
      if (record?.start_date || record?.end_date) card.append(element("p", `${record.start_date || ""} – ${record.end_date || ""}`, "muted"));
      card.append(orderingControls(selections, index, section, "parent", `Remove ${section.name}`));
      if (!record) {
        card.append(element("p", "This saved record is unavailable. Replacing it clears its selected bullets; removing it removes the entire selection.", "muted"));
        picker(card, availableParents(section), section.label, `Choose replacement ${section.name}`, `Replace ${section.name} and clear bullets`, replacement => change(() => {
          if (!selections.some(item => item[section.parentKey] === replacement)) {
            selection[section.parentKey] = replacement;
            selection[section.bulletKey] = [];
          }
        }));
      }
      const bullets = element("ul", undefined, "cv-bullets");
      selection[section.bulletKey].forEach((bulletId, bulletIndex) => {
        const item = record?.[section.children].find(child => child.id === bulletId);
        const row = element("li", undefined, item ? "cv-bullet" : "cv-bullet cv-missing");
        row.dataset.bulletId = bulletId;
        row.append(element("p", item ? item.text : `Unavailable ${section.bulletName} (${bulletId})`, "cv-bullet-text"));
        const select = selectOptions(availableBullets(section, record, bulletId), child => child.text, `Choose ${section.bulletName} for ${section.name} ${index + 1}`, bulletId);
        select.disabled = !record;
        select.addEventListener("change", () => change(() => {
          if (record?.[section.children].some(child => child.id === select.value) && !selectedBulletIds().has(select.value)) selection[section.bulletKey][bulletIndex] = select.value;
        }));
        row.append(select, orderingControls(selection[section.bulletKey], bulletIndex, section, `bullet-${index}`, `Remove ${section.bulletName}`));
        bullets.append(row);
      });
      card.append(bullets);
      if (record) picker(card, availableBullets(section, record), child => child.text, `Choose ${section.bulletName} to add`, section.addBulletLabel, bulletId => change(() => {
        if (record[section.children].some(item => item.id === bulletId) && !selectedBulletIds().has(bulletId)) selection[section.bulletKey].push(bulletId);
      }));
      list.append(card);
    });
  }

  function selectedSkillKeys() {
    return new Set((draft?.skill_groups || []).flatMap(group => group.skill_keys));
  }

  function availableSkills(currentKey = null) {
    const selected = selectedSkillKeys();
    return [...skillCatalogue].filter(([key]) => !selected.has(key) || key === currentKey).map(([key, label]) => ({ id: key, label }));
  }

  function updateHeadingValidity() {
    draft.skill_groups.forEach((group, index) => {
      const name = normaliseSkillKey(group.name);
      const duplicate = draft.skill_groups.some((other, otherIndex) => otherIndex !== index && normaliseSkillKey(other.name) === name);
      find(`#cv-group-heading-${index}`)?.setAttribute("aria-invalid", String(!name || duplicate));
    });
  }

  function renderSkillGroups() {
    const addTarget = find("#cv-add-skill-group");
    const list = find("#cv-skill-group-list");
    addTarget.replaceChildren();
    list.replaceChildren();
    if (!draft) return;
    const addRow = element("div", undefined, "cv-picker");
    const heading = element("input");
    heading.type = "text";
    heading.placeholder = "New group heading, e.g. Languages";
    heading.setAttribute("aria-label", "New skills group heading");
    addRow.append(heading, button("Add Skills Group", () => {
      if (!ready() || loading || savingCV) return;
      const name = normaliseSkillKey(heading.value);
      if (!name || draft.skill_groups.some(group => normaliseSkillKey(group.name) === name)) {
        showMessage("Could not add skills group.", new Error("Enter a nonblank, unique group heading (ignoring case and whitespace)."));
        return;
      }
      change(() => draft.skill_groups.push({ name: heading.value, skill_keys: [] }), `skill_groups-group-${draft.skill_groups.length}-heading`);
    }));
    addTarget.append(addRow);
    if (!draft.skill_groups.length) list.append(element("p", "No skills groups selected.", "muted"));
    draft.skill_groups.forEach((group, groupIndex) => {
      const card = element("article", undefined, "cv-card");
      card.dataset.groupIndex = String(groupIndex);
      const title = element("h4", group.name || "Unnamed skills group");
      const headingRow = element("div", undefined, "cv-group-heading");
      const nameInput = element("input");
      nameInput.type = "text";
      nameInput.id = `cv-group-heading-${groupIndex}`;
      nameInput.dataset.cvFocus = `skill_groups-group-${groupIndex}-heading`;
      nameInput.value = group.name;
      const label = element("label", "Group heading");
      label.setAttribute("for", nameInput.id);
      nameInput.addEventListener("input", () => {
        if (!ready() || loading || savingCV) return;
        group.name = nameInput.value;
        title.textContent = group.name || "Unnamed skills group";
        message.replaceChildren();
        // Keep the input and focus intact while typing; update only derived UI.
        updateHeadingValidity();
        renderWarnings();
        renderPreview();
        updateControls();
      });
      headingRow.append(label, nameInput);
      card.append(title, headingRow, orderingControls(draft.skill_groups, groupIndex, { key: "skill_groups" }, "group", "Remove Group"));
      const skills = element("ul", undefined, "cv-skill-list");
      group.skill_keys.forEach((key, skillIndex) => {
        const available = skillCatalogue.has(key);
        const row = element("li", undefined, available ? "cv-skill" : "cv-skill cv-missing");
        row.dataset.skillKey = key;
        row.append(element("p", available ? skillCatalogue.get(key) : `Unavailable skill (${key})`, "cv-source-text"));
        const select = selectOptions(availableSkills(key), record => record.label, `Choose skill for group ${groupIndex + 1}`, key);
        const focusKey = `skill_groups-skill-${groupIndex}-${skillIndex}-select`;
        select.dataset.cvFocus = focusKey;
        select.addEventListener("change", () => change(() => {
          if (skillCatalogue.has(select.value) && !selectedSkillKeys().has(select.value)) group.skill_keys[skillIndex] = select.value;
        }, focusKey));
        row.append(select, orderingControls(group.skill_keys, skillIndex, { key: "skill_groups" }, `skill-${groupIndex}`, "Remove Skill"));
        skills.append(row);
      });
      card.append(skills);
      picker(card, availableSkills(), record => record.label, "Choose a skill to add", "Add Skill", key => change(() => {
        if (skillCatalogue.has(key) && !selectedSkillKeys().has(key)) group.skill_keys.push(key);
      }));
      list.append(card);
    });
    updateHeadingValidity();
  }

  function renderSettings() {
    const target = find("#cv-tailoring-settings");
    target.replaceChildren();
    if (!draft) return;
    settingFields.forEach(([key, labelText]) => {
      const row = element("div");
      const input = element("input");
      input.id = `cv-setting-${key}`;
      input.type = "number";
      input.min = "0";
      input.step = "1";
      input.placeholder = "No limit";
      input.value = String(key in settingEdits ? settingEdits[key] : draft.tailoring_settings[key] ?? "");
      const label = element("label", labelText);
      label.setAttribute("for", input.id);
      const error = element("p", settingError(key), "message error");
      error.id = `${input.id}-error`;
      input.setAttribute("aria-describedby", error.id);
      input.setAttribute("aria-invalid", String(Boolean(settingError(key))));
      input.addEventListener("input", () => {
        if (!ready() || loading || savingCV) return;
        const raw = input.value;
        settingEdits[key] = raw;
        const text = raw.trim();
        const value = text === "" ? null : Number(text);
        if (input.validity?.badInput || (text !== "" && !/^\d+$/.test(text))) {
          settingErrors[key] = "Enter a nonnegative whole number, or leave blank for no limit.";
        } else if (text !== "" && !Number.isSafeInteger(value)) {
          settingErrors[key] = "This number is too large. Choose a smaller whole number.";
        } else {
          delete settingErrors[key];
          draft.tailoring_settings[key] = value;
        }
        error.textContent = settingError(key);
        input.setAttribute("aria-invalid", String(Boolean(settingError(key))));
        message.replaceChildren();
        renderWarnings();
        updateControls();
      });
      row.append(label, input, error);
      target.append(row);
    });
  }

  function renderPreview() {
    const target = find("#cv-preview-content");
    target.replaceChildren();
    if (!draft) {
      target.append(element("p", "Load your saved bank and Current CV to see a preview.", "muted"));
      return;
    }
    if (!bankReady) target.append(element("p", "The saved bank is unavailable. Previously loaded content may be shown until loading succeeds.", "notice"));
    function previewSection(key, title) {
      const section = element("section");
      section.dataset.previewSection = key;
      section.append(element("h3", title));
      target.append(section);
      return section;
    }
    function details(card, record, fields) {
      fields.forEach(field => {
        if (record[field] !== undefined && record[field] !== null && record[field] !== "") card.append(element("p", record[field], "cv-source-text"));
      });
    }
    const skillSection = previewSection("skill_groups", "Skills");
    if (!draft.skill_groups.length) skillSection.append(element("p", "No skills selected.", "muted"));
    draft.skill_groups.forEach(group => {
      const card = element("article");
      card.append(element("h4", group.name || "Unnamed skills group", "cv-source-text"));
      const list = element("ul");
      group.skill_keys.forEach(key => {
        const item = element("li", skillCatalogue.has(key) ? skillCatalogue.get(key) : `Unavailable skill (${key})`, "cv-source-text");
        item.dataset.previewSkillKey = key;
        list.append(item);
      });
      card.append(list);
      skillSection.append(card);
    });
    sections.forEach(config => {
      const section = previewSection(config.key, config.key === "work_experience" ? "Work Experience" : "Projects");
      if (!draft[config.key].length) section.append(element("p", "No selections.", "muted"));
      draft[config.key].forEach(selection => {
        const id = selection[config.parentKey];
        const record = recordsFor(config).find(item => item.id === id);
        const card = element("article");
        card.dataset.previewParentId = id;
        card.append(element("h4", record ? record.role || record.name : `Unavailable ${config.name} (${id})`, "cv-source-text"));
        if (record) details(card, record, config.key === "work_experience" ? ["employer", "start_date", "end_date", "summary"] : ["description", "link"]);
        const bullets = element("ul");
        selection[config.bulletKey].forEach(bulletId => {
          const source = record?.[config.children].find(item => item.id === bulletId);
          const bullet = element("li", source ? source.text : `Unavailable ${config.bulletName} (${bulletId})`, "cv-source-text");
          bullet.dataset.previewBulletId = bulletId;
          bullets.append(bullet);
        });
        card.append(bullets);
        section.append(card);
      });
    });
    for (const [key, title, heading, fields] of [
      ["education", "Education", "qualification", ["institution", "field", "year"]],
      ["certifications", "Certifications", "name", ["issuer", "year"]],
    ]) {
      const section = previewSection(key, title);
      const records = bank?.[key] || [];
      if (!records.length) section.append(element("p", bank ? "None recorded." : "Saved bank not loaded.", "muted"));
      records.forEach(record => {
        const card = element("article");
        card.dataset.previewRecordId = record.id;
        card.append(element("h4", record[heading], "cv-source-text"));
        details(card, record, fields);
        if (record.skills?.length) {
          const list = element("ul");
          record.skills.forEach(label => list.append(element("li", label, "cv-source-text")));
          card.append(list);
        }
        section.append(card);
      });
    }
  }

  function render() {
    sections.forEach(renderSection);
    renderSkillGroups();
    renderSettings();
    renderPreview();
    renderWarnings();
    updateControls();
  }

  async function load() {
    if (loading || savingCV) return;
    loading = true;
    showMessage("Loading saved bank and Current CV…");
    updateControls();
    const requests = [{ name: "bank", url: "/experience-bank" }];
    // A bank retry/refresh must never replace an already loaded CV draft.
    if (!cvReady && draft === null) requests.push({ name: "CV", url: "/current-cv" });
    const outcomes = await Promise.allSettled(requests.map(item => fetchJSON(item.url)));
    const failures = [];
    outcomes.forEach((outcome, index) => {
      const name = requests[index].name;
      if (outcome.status === "fulfilled") {
        if (name === "bank") {
          setBank(outcome.value);
        } else {
          draft = clone(outcome.value.current_cv);
          baseline = JSON.stringify(draft);
          serverIssues = clone(outcome.value.reference_issues);
          cvReady = true;
          settingEdits = {};
          settingErrors = {};
        }
      } else {
        if (name === "bank") bankReady = false;
        else cvReady = false;
        failures.push(`${name}: ${outcome.reason.message}`);
      }
    });
    loading = false;
    if (failures.length) showMessage("Loading failed. Saving is disabled; your loaded selections have been kept. Retry loading after fixing the problem.", new Error(failures.join(" ")));
    else showMessage("Saved bank loaded. Your Current CV selections are ready.");
    render();
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (!ready() || loading || savingCV) return;
    const invalidInputs = inputIssues();
    if (invalidInputs.length) {
      showMessage("Correct the invalid headings or limits before saving.", { details: invalidInputs });
      return;
    }
    savingCV = true;
    showMessage("Checking the latest saved bank and saving…");
    updateControls();
    let bankRefreshed = false;
    try {
      setBank(await fetchJSON("/experience-bank"));
      bankRefreshed = true;
      render();
      const saved = await fetchJSON("/current-cv", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft),
      });
      draft = clone(saved);
      baseline = JSON.stringify(draft);
      serverIssues = [];
      settingEdits = {};
      settingErrors = {};
      showMessage("Current CV saved.");
    } catch (error) {
      if (!bankRefreshed) bankReady = false;
      if (Array.isArray(error.details)) serverIssues = error.details.filter(issue => issue.path && issue.reason);
      showMessage(bankRefreshed ? "Current CV was not saved. Your changes have been kept." : "The saved bank could not be refreshed. Your changes have been kept; retry loading before saving.", error);
    } finally {
      savingCV = false;
      render();
    }
  });

  window.addEventListener("workspace-view-changed", event => {
    if (event.detail.view === "cv") load();
  });
  retryButton.addEventListener("click", load);
  window.addEventListener("experience-bank-saved", event => {
    setBank(event.detail);
    render();
  });
  window.addEventListener("beforeunload", event => {
    if (dirty()) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  updateControls();
})();
