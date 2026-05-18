(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.ReverseWiktionaryLanguageFilters = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  /*
   * Language filtering keeps two related states:
   * - selectedLanguages is the exact flat set submitted to the backend.
   * - selectionIntents preserves how the user got there so chips can explain
   *   broad selections, exclusions, and explicit add-backs compactly.
   */
  class LanguageFilterState {
    /*
     * Pure selection model. This class has no DOM dependency, which keeps the
     * chip-collapse rules testable outside the browser.
     */
    constructor({ families, allLanguages = [], initialSelectedLabels = [] }) {
      this.languageById = new Map();
      this.languageIdByLabel = new Map();
      this.languagesByFamily = new Map();
      this.languagesByBranch = new Map();
      this.branchById = new Map();
      this.familyById = new Map();
      this.selectedLanguages = new Set();
      this.selectionIntents = [];
      this.intentClock = 0;

      families.forEach((family) => this.addFamily(family));
      this.addSearchOnlyLanguages(allLanguages);

      initialSelectedLabels.forEach((label) => {
        const languageId = this.languageIdByLabel.get(label);
        if (languageId) {
          this.selectedLanguages.add(languageId);
          this.selectionIntents.push(this.createIntent("language", languageId));
        }
      });

      this.normalizeIntents();
    }

    addFamily(family) {
      this.familyById.set(family.id, {
        id: family.id,
        label: family.label,
        branches: family.branches,
      });
      this.languagesByFamily.set(family.id, []);

      family.branches.forEach((branch) => {
        this.branchById.set(branch.id, {
          id: branch.id,
          label: branch.label,
          family_id: family.id,
        });
        this.languagesByBranch.set(branch.id, []);

        branch.languages.forEach((language) => {
          this.languageById.set(language.id, {
            id: language.id,
            label: language.label,
            family_id: family.id,
            branch_id: branch.id,
          });
          this.languageIdByLabel.set(language.label, language.id);
          this.languagesByFamily.get(family.id).push(language.id);
          this.languagesByBranch.get(branch.id).push(language.id);
        });
      });
    }

    addSearchOnlyLanguages(languages) {
      languages.forEach((language) => {
        if (!language.label || this.languageIdByLabel.has(language.label)) {
          return;
        }

        this.languageById.set(language.id, {
          id: language.id,
          label: language.label,
          family_id: "",
          branch_id: "",
          search_only: true,
        });
        this.languageIdByLabel.set(language.label, language.id);
      });
    }

    createIntent(type, id) {
      this.intentClock += 1;
      return { type, id, createdAt: this.intentClock };
    }

    toggleAll() {
      if (this.selectedLanguages.size === this.languageById.size) {
        this.selectedLanguages = new Set();
        this.selectionIntents = [];
      } else {
        this.selectedLanguages = new Set(this.languageById.keys());
        this.selectionIntents = [this.createIntent("all", "all")];
      }

      this.normalizeIntents();
    }

    toggleGroup(type, id, checked) {
      const languageIds = this.groupLanguageIds(type, id);

      if (checked) {
        const fillsExistingExclusion = this.isExactExcludedItem(type, id);
        languageIds.forEach((languageId) => this.selectedLanguages.add(languageId));

        if (!fillsExistingExclusion) {
          this.removeCoveredIntents(type, id);
          this.selectionIntents.push(this.createIntent(type, id));
        }
      } else {
        languageIds.forEach((languageId) => this.selectedLanguages.delete(languageId));
        this.selectionIntents = this.selectionIntents.filter((intent) => {
          return !(intent.type === type && intent.id === id) && !this.isIntentInside(intent, type, id);
        });
      }

      this.normalizeIntents();
    }

    toggleLanguage(languageId, checked) {
      if (checked) {
        const fillsExistingExclusion = this.isExactExcludedItem("language", languageId);
        this.selectedLanguages.add(languageId);

        if (
          !fillsExistingExclusion &&
          (!this.coveringGroupIntent(languageId) || this.isInsidePartialAncestorSelection(languageId))
        ) {
          this.selectionIntents.push(this.createIntent("language", languageId));
        }
      } else {
        this.selectedLanguages.delete(languageId);
        this.selectionIntents = this.selectionIntents.filter((intent) => {
          return !(intent.type === "language" && intent.id === languageId);
        });
      }

      this.normalizeIntents();
    }

    normalizeIntents() {
      this.selectionIntents = this.dedupeIntents(this.selectionIntents)
        .filter((intent) => this.selectedCountForIntent(intent) > 0);

      this.branchById.forEach((branch) => {
        const ids = this.languagesByBranch.get(branch.id) || [];
        const selectedAll = ids.length > 0 && ids.every((languageId) => this.selectedLanguages.has(languageId));
        const explicitLanguageCoverage = ids.length > 0 && ids.every((languageId) => this.hasIntent("language", languageId));
        const alreadyHasBranch = this.hasIntent("branch", branch.id);
        const hasFullAncestor = this.selectionIntents.some((intent) => {
          return (
            intent.type === "all" && this.isFullIntent("all", "all")
          ) || (
            intent.type === "family" &&
            intent.id === branch.family_id &&
            this.isFullIntent("family", branch.family_id)
          );
        });

        if (selectedAll && !hasFullAncestor && (explicitLanguageCoverage || alreadyHasBranch)) {
          this.removeCoveredIntents("branch", branch.id);
          this.ensureIntent("branch", branch.id);
        }
      });

      if (this.languageById.size > 0 && this.selectedLanguages.size === this.languageById.size) {
        this.selectionIntents = this.selectionIntents.filter((intent) => intent.type === "all");
        this.ensureIntent("all", "all");
      }

      this.familyById.forEach((family) => {
        const ids = this.languagesByFamily.get(family.id) || [];
        const hasAllIntent = this.selectionIntents.some((intent) => intent.type === "all");
        const selectedAll = ids.length > 0 && ids.every((languageId) => this.selectedLanguages.has(languageId));
        const explicitBranchCoverage = family.branches.every((branch) => this.hasIntent("branch", branch.id));

        if (selectedAll && !hasAllIntent && explicitBranchCoverage) {
          this.removeCoveredIntents("family", family.id);
          this.ensureIntent("family", family.id);
        }
      });

      this.selectionIntents = this.dedupeIntents(this.selectionIntents)
        .filter((intent) => this.selectedCountForIntent(intent) > 0)
        .filter((intent) => !this.hasFullAncestorIntent(intent))
        .sort((left, right) => left.createdAt - right.createdAt);
    }

    dedupeIntents(intents) {
      const seen = new Set();
      const deduped = [];

      intents.forEach((intent) => {
        const key = `${intent.type}:${intent.id}`;
        if (!seen.has(key)) {
          seen.add(key);
          deduped.push(intent);
        }
      });

      return deduped;
    }

    ensureIntent(type, id) {
      if (!this.hasIntent(type, id)) {
        this.selectionIntents.push(this.createIntent(type, id));
      }
    }

    hasIntent(type, id) {
      return this.selectionIntents.some((intent) => intent.type === type && intent.id === id);
    }

    removeCoveredIntents(type, id) {
      this.selectionIntents = this.selectionIntents.filter((intent) => {
        return !(intent.type === type && intent.id === id) && !this.isIntentInside(intent, type, id);
      });
    }

    isIntentInside(intent, type, id) {
      if (type === "family") {
        if (intent.type === "all") {
          return false;
        }
        if (intent.type === "branch") {
          return this.branchById.get(intent.id)?.family_id === id;
        }
        if (intent.type === "language") {
          return this.languageById.get(intent.id)?.family_id === id;
        }
      }

      if (type === "branch" && intent.type === "language") {
        return this.languageById.get(intent.id)?.branch_id === id;
      }

      if (type === "all") {
        return intent.type !== "all";
      }

      return false;
    }

    hasFullAncestorIntent(intent) {
      if (
        intent.type !== "all" &&
        this.selectionIntents.some((candidate) => candidate.type === "all")
      ) {
        return this.isFullIntent("all", "all");
      }

      if (intent.type === "branch") {
        return this.selectionIntents.some((candidate) => {
          return (
            candidate.type === "family" &&
            candidate.id === this.branchById.get(intent.id)?.family_id &&
            this.isFullIntent(candidate.type, candidate.id)
          );
        });
      }

      if (intent.type === "language") {
        const language = this.languageById.get(intent.id);
        if (!language || language.search_only) {
          return false;
        }
        return this.selectionIntents.some((candidate) => {
          return (
            candidate.type === "family" &&
            candidate.id === language.family_id &&
            this.isFullIntent(candidate.type, candidate.id)
          ) || (
            candidate.type === "branch" &&
            candidate.id === language.branch_id &&
            this.isFullIntent(candidate.type, candidate.id)
          );
        });
      }

      return false;
    }

    isFullIntent(type, id) {
      const ids = this.groupLanguageIds(type, id);
      return ids.length > 0 && ids.every((languageId) => this.selectedLanguages.has(languageId));
    }

    coveringGroupIntent(languageId) {
      const language = this.languageById.get(languageId);
      if (!language || language.search_only) {
        return false;
      }
      return this.selectionIntents.some((intent) => {
        return (
          (intent.type === "family" && intent.id === language.family_id) ||
          (intent.type === "branch" && intent.id === language.branch_id)
        );
      });
    }

    isInsidePartialAncestorSelection(languageId) {
      const language = this.languageById.get(languageId);
      if (!language || language.search_only) {
        return false;
      }
      return this.selectionIntents.some((intent) => {
        if (intent.type === "all") {
          return this.selectedLanguages.size < this.languageById.size;
        }

        if (intent.type === "family" && intent.id === language.family_id) {
          const familyIds = this.languagesByFamily.get(intent.id) || [];
          return familyIds.some((id) => !this.selectedLanguages.has(id));
        }

        if (intent.type === "branch" && intent.id === language.branch_id) {
          const branchIds = this.languagesByBranch.get(intent.id) || [];
          return branchIds.some((id) => !this.selectedLanguages.has(id));
        }

        return false;
      });
    }

    groupLanguageIds(type, id) {
      if (type === "family") {
        return this.languagesByFamily.get(id) || [];
      }
      if (type === "branch") {
        return this.languagesByBranch.get(id) || [];
      }
      if (type === "all") {
        return Array.from(this.languageById.keys());
      }
      return [id];
    }

    selectedCountForIntent(intent) {
      return this.groupLanguageIds(intent.type, intent.id)
        .filter((languageId) => this.selectedLanguages.has(languageId))
        .length;
    }

    submittedLanguages() {
      return Array.from(this.selectedLanguages)
        .map((languageId) => this.languageById.get(languageId))
        .sort((left, right) => left.label.localeCompare(right.label));
    }

    searchOnlyLanguages(query) {
      const normalizedQuery = query.toLowerCase();
      return Array.from(this.languageById.values())
        .filter((language) => {
          return language.search_only && language.label.toLowerCase().includes(normalizedQuery);
        })
        .sort((left, right) => left.label.localeCompare(right.label));
    }

    chipModels() {
      return this.selectionIntents
        .map((intent) => ({
          intent,
          label: this.intentLabel(intent),
          exclusions: this.exclusionItems(intent),
        }))
        .filter((chip) => this.selectedCountForIntent(chip.intent) > 0);
    }

    intentLabel(intent) {
      if (intent.type === "family") {
        return this.familyById.get(intent.id)?.label || intent.id;
      }
      if (intent.type === "all") {
        return "All languages";
      }
      if (intent.type === "branch") {
        return this.branchById.get(intent.id)?.label || intent.id;
      }
      return this.languageById.get(intent.id)?.label || intent.id;
    }

    exclusionItems(intent) {
      if (intent.type === "language") {
        return [];
      }

      return this.groupedExclusionItems(intent, { includeLaterIntents: true });
    }

    groupedExclusionItems(intent, { includeLaterIntents }) {
      const missing = new Set(
        this.groupLanguageIds(intent.type, intent.id).filter((languageId) => {
          return (
            !this.selectedLanguages.has(languageId) ||
            (includeLaterIntents && this.isCoveredByLaterIntent(languageId, intent))
          );
        })
      );
      const exclusions = [];

      if (intent.type === "all") {
        this.familyById.forEach((family) => {
          const familyLanguageIds = this.languagesByFamily.get(family.id) || [];
          const allMissing = familyLanguageIds.length > 0 && familyLanguageIds.every((id) => missing.has(id));
          if (allMissing) {
            exclusions.push({ label: family.label, languageIds: familyLanguageIds });
            familyLanguageIds.forEach((id) => missing.delete(id));
          }
        });

        this.familyById.forEach((family) => {
          family.branches.forEach((branch) => {
            const branchLanguageIds = this.languagesByBranch.get(branch.id) || [];
            const allMissing = branchLanguageIds.length > 0 && branchLanguageIds.every((id) => missing.has(id));
            if (allMissing) {
              exclusions.push({ label: branch.label, languageIds: branchLanguageIds });
              branchLanguageIds.forEach((id) => missing.delete(id));
            }
          });
        });
      }

      if (intent.type === "family") {
        const family = this.familyById.get(intent.id);
        family.branches.forEach((branch) => {
          const branchLanguageIds = this.languagesByBranch.get(branch.id) || [];
          const allMissing = branchLanguageIds.length > 0 && branchLanguageIds.every((id) => missing.has(id));
          if (allMissing) {
            exclusions.push({ label: branch.label, languageIds: branchLanguageIds });
            branchLanguageIds.forEach((id) => missing.delete(id));
          }
        });
      }

      Array.from(missing)
        .map((languageId) => this.languageById.get(languageId))
        .sort((left, right) => left.label.localeCompare(right.label))
        .forEach((language) => {
          exclusions.push({ label: language.label, languageIds: [language.id] });
        });

      return exclusions;
    }

    isExactExcludedItem(type, id) {
      const targetIds = sortedIds(this.groupLanguageIds(type, id));
      return this.selectionIntents.some((intent) => {
        if (!this.isIntentInside({ type, id }, intent.type, intent.id)) {
          return false;
        }

        return this.groupedExclusionItems(intent, { includeLaterIntents: true }).some((exclusion) => {
          return arraysEqual(sortedIds(exclusion.languageIds), targetIds);
        });
      });
    }

    isCoveredByLaterIntent(languageId, intent) {
      return this.selectionIntents.some((candidate) => {
        return (
          candidate.createdAt > intent.createdAt &&
          candidate.type !== "all" &&
          this.groupLanguageIds(candidate.type, candidate.id).includes(languageId)
        );
      });
    }
  }

  class LanguageFilterController {
    /*
     * DOM adapter for the language filter. It translates checkbox/search/chip
     * events into state transitions, then renders hidden form inputs and chips.
     */
    constructor({
      tree,
      chipList,
      emptyState,
      inputHost,
      selectAll,
      selectAllLabel,
      searchResults,
    }) {
      this.tree = tree;
      this.chipList = chipList;
      this.emptyState = emptyState;
      this.inputHost = inputHost;
      this.selectAll = selectAll;
      this.selectAllLabel = selectAllLabel;
      this.searchResults = searchResults;
      this.state = new LanguageFilterState({
        families: readFamiliesFromDom(tree),
        allLanguages: JSON.parse(tree.dataset.allLanguages || "[]"),
        initialSelectedLabels: JSON.parse(tree.dataset.selectedLangs || "[]"),
      });
    }

    bind() {
      this.tree.addEventListener("click", (event) => {
        if (
          event.target.closest("[data-language-group-row]") ||
          event.target.closest("[data-language-select-all-row]") ||
          event.target.matches("[data-language-group]") ||
          event.target.matches("[data-language-checkbox]") ||
          event.target.matches("[data-language-select-all]")
        ) {
          event.stopPropagation();
        }
      });

      this.tree.addEventListener("change", (event) => {
        const target = event.target;
        this.handleLanguageChange(target);
      });

      if (this.searchResults) {
        this.searchResults.addEventListener("change", (event) => {
          this.handleLanguageChange(event.target);
        });
      }

      document.addEventListener("input", (event) => {
        if (event.target.matches("[data-language-search]")) {
          this.applyLanguageSearch(event.target.value);
        }
      });

      document.addEventListener("search", (event) => {
        if (event.target.matches("[data-language-search]")) {
          this.applyLanguageSearch(event.target.value);
        }
      });

      document.addEventListener("change", (event) => {
        if (event.target.matches("[name='pos']")) {
          this.renderChips();
        }
      });

      this.syncUi();
    }

    handleLanguageChange(target) {
      if (target.matches("[data-language-select-all]")) {
        this.state.toggleAll();
        this.syncUi();
        return;
      }

      if (target.matches("[data-language-group]")) {
        this.state.toggleGroup(target.dataset.languageGroup, target.dataset.groupId, target.checked);
        this.syncUi();
        return;
      }

      if (target.matches("[data-language-checkbox], [data-language-search-checkbox]")) {
        this.state.toggleLanguage(target.dataset.languageId, target.checked);
        this.syncUi();
      }
    }

    syncUi() {
      this.syncCheckboxes();
      this.syncHiddenInputs();
      this.renderChips();
    }

    syncCheckboxes() {
      this.tree.querySelectorAll("[data-language-checkbox]").forEach((checkbox) => {
        checkbox.checked = this.state.selectedLanguages.has(checkbox.dataset.languageId);
      });

      if (this.searchResults) {
        this.searchResults.querySelectorAll("[data-language-search-checkbox]").forEach((checkbox) => {
          checkbox.checked = this.state.selectedLanguages.has(checkbox.dataset.languageId);
        });
      }

      this.tree.querySelectorAll("[data-language-group]").forEach((checkbox) => {
        const ids = this.state.groupLanguageIds(checkbox.dataset.languageGroup, checkbox.dataset.groupId);
        const selectedCount = ids.filter((languageId) => this.state.selectedLanguages.has(languageId)).length;
        checkbox.checked = ids.length > 0 && selectedCount === ids.length;
        checkbox.indeterminate = selectedCount > 0 && selectedCount < ids.length;
      });

      if (this.selectAll) {
        const allSelected = (
          this.state.selectedLanguages.size === this.state.languageById.size &&
          this.state.languageById.size > 0
        );
        this.selectAll.checked = allSelected;
        this.selectAll.indeterminate = this.state.selectedLanguages.size > 0 && !allSelected;
        this.selectAllLabel.textContent = allSelected ? "Deselect all" : "Select all";
      }
    }

    syncHiddenInputs() {
      this.inputHost.innerHTML = "";

      if (this.state.selectedLanguages.size === 0) {
        return;
      }

      this.state.submittedLanguages().forEach((language) => {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = "langs";
        input.value = language.label;
        this.inputHost.appendChild(input);
      });
    }

    renderChips() {
      this.chipList.innerHTML = "";

      this.state.chipModels().forEach((chipModel) => {
        this.chipList.appendChild(this.buildLanguageChip(chipModel));
      });

      document.querySelectorAll("[name='pos']:checked").forEach((checkbox) => {
        this.chipList.appendChild(buildPosChip(checkbox, () => this.renderChips()));
      });

      if (this.emptyState) {
        this.emptyState.hidden = this.chipList.children.length > 0;
      }
    }

    buildLanguageChip(chipModel) {
      const chip = document.createElement("span");
      chip.className = "filter-chip filter-chip-complex";
      chip.dataset.languageChip = `${chipModel.intent.type}:${chipModel.intent.id}`;

      const label = document.createElement("span");
      label.textContent = chipModel.label;
      chip.appendChild(label);

      if (chipModel.exclusions.length > 0) {
        const exclusionList = document.createElement("span");
        exclusionList.className = "chip-exclusions";
        exclusionList.append(" (- ");
        chipModel.exclusions.forEach((exclusion, index) => {
          if (index > 0) {
            exclusionList.append(", ");
          }
          const exclusionButton = document.createElement("button");
          exclusionButton.type = "button";
          exclusionButton.className = "chip-exclusion";
          exclusionButton.textContent = exclusion.label;
          exclusionButton.addEventListener("click", () => {
            exclusion.languageIds.forEach((languageId) => this.state.selectedLanguages.add(languageId));
            this.state.normalizeIntents();
            this.syncUi();
          });
          exclusionList.appendChild(exclusionButton);
        });
        exclusionList.append(")");
        chip.appendChild(exclusionList);
      }

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "chip-remove";
      remove.textContent = "x";
      remove.setAttribute("aria-label", `Remove ${chipModel.label}`);
      remove.addEventListener("click", () => {
        this.state.groupLanguageIds(chipModel.intent.type, chipModel.intent.id).forEach((languageId) => {
          this.state.selectedLanguages.delete(languageId);
        });
        this.state.selectionIntents = this.state.selectionIntents.filter((candidate) => {
          return candidate !== chipModel.intent;
        });
        this.state.normalizeIntents();
        this.syncUi();
      });
      chip.appendChild(remove);

      return chip;
    }

    applyLanguageSearch(rawQuery) {
      const query = rawQuery.trim().toLowerCase();
      const matchingFamilies = new Set();
      const matchingBranches = new Set();

      this.tree.querySelectorAll("[data-language-row]").forEach((row) => {
        const languageId = row.dataset.languageId;
        const language = this.state.languageById.get(languageId);
        const matches = !query || language.label.toLowerCase().includes(query);
        row.classList.toggle("is-hidden", !matches);
        if (matches && query) {
          matchingFamilies.add(language.family_id);
          matchingBranches.add(language.branch_id);
        }
      });

      this.tree.querySelectorAll("[data-branch-id]").forEach((details) => {
        const matches = !query || matchingBranches.has(details.dataset.branchId);
        details.classList.toggle("is-hidden", !matches);
        if (matches && query) {
          details.open = true;
        }
      });

      this.tree.querySelectorAll("[data-family-id]").forEach((details) => {
        const matches = !query || matchingFamilies.has(details.dataset.familyId);
        details.classList.toggle("is-hidden", !matches);
        if (matches && query) {
          details.open = true;
        }
      });

      this.renderSearchOnlyMatches(query);
    }

    renderSearchOnlyMatches(query) {
      if (!this.searchResults) {
        return;
      }

      this.searchResults.innerHTML = "";
      this.searchResults.hidden = !query;

      if (!query) {
        return;
      }

      const matches = this.state.searchOnlyLanguages(query).slice(0, 50);
      if (matches.length === 0) {
        this.searchResults.hidden = true;
        return;
      }

      matches.forEach((language) => {
        const row = document.createElement("label");
        row.className = "check-row";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.dataset.languageSearchCheckbox = "";
        checkbox.dataset.languageId = language.id;
        checkbox.value = language.label;
        checkbox.checked = this.state.selectedLanguages.has(language.id);
        row.appendChild(checkbox);

        const label = document.createElement("span");
        label.textContent = language.label;
        row.appendChild(label);
        this.searchResults.appendChild(row);
      });
    }
  }

  function readFamiliesFromDom(tree) {
    return Array.from(tree.querySelectorAll("[data-family-id]")).map((familyElement) => {
      return {
        id: familyElement.dataset.familyId,
        label: familyElement.dataset.familyLabel,
        branches: Array.from(familyElement.querySelectorAll("[data-branch-id]")).map((branchElement) => {
          return {
            id: branchElement.dataset.branchId,
            label: branchElement.dataset.branchLabel,
            languages: Array.from(branchElement.querySelectorAll("[data-language-row]")).map((languageElement) => {
              const checkbox = languageElement.querySelector("[data-language-checkbox]");
              return {
                id: languageElement.dataset.languageId,
                label: checkbox.value,
              };
            }),
          };
        }),
      };
    });
  }

  function buildPosChip(checkbox, onRemove) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "filter-chip";
    chip.setAttribute("aria-label", `Remove ${checkbox.value}`);
    chip.append(checkbox.value, " x");
    chip.addEventListener("click", () => {
      checkbox.checked = false;
      onRemove();
    });
    return chip;
  }

  function initializeLanguageFilters() {
    const tree = document.querySelector("[data-language-tree]");
    const chipList = document.querySelector("[data-filter-chips]");
    const emptyState = document.querySelector("[data-filter-chip-empty]");
    const inputHost = document.querySelector("[data-language-inputs]");
    const selectAll = document.querySelector("[data-language-select-all]");
    const selectAllLabel = document.querySelector("[data-language-select-all-label]");
    const searchResults = document.querySelector("[data-language-search-results]");

    if (!tree || !chipList || !inputHost) {
      return null;
    }

    const controller = new LanguageFilterController({
      tree,
      chipList,
      emptyState,
      inputHost,
      selectAll,
      selectAllLabel,
      searchResults,
    });
    controller.bind();
    return controller;
  }

  function sortedIds(ids) {
    return Array.from(ids).sort();
  }

  function arraysEqual(left, right) {
    return left.length === right.length && left.every((value, index) => value === right[index]);
  }

  return {
    LanguageFilterState,
    initializeLanguageFilters,
  };
});
