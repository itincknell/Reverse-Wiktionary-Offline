#!/usr/bin/env node

const { LanguageFilterState } = require("../../src/web/static/language_filters.js");

const families = [
  {
    id: "indo",
    label: "Indo-European",
    branches: [
      {
        id: "germanic",
        label: "Germanic",
        languages: [
          { id: "english", label: "English" },
          { id: "german", label: "German" },
          { id: "dutch", label: "Dutch" },
        ],
      },
      {
        id: "slavic",
        label: "Slavic",
        languages: [
          { id: "russian", label: "Russian" },
          { id: "polish", label: "Polish" },
        ],
      },
    ],
  },
  {
    id: "japonic",
    label: "Japonic",
    branches: [
      {
        id: "japonic-branch",
        label: "Japonic",
        languages: [
          { id: "japanese", label: "Japanese" },
          { id: "okinawan", label: "Okinawan" },
        ],
      },
    ],
  },
];

function chipLabels(state) {
  return state.chipModels().map((chip) => {
    const exclusions = chip.exclusions.map((item) => item.label);
    return exclusions.length > 0
      ? `${chip.label} (- ${exclusions.join(", ")})`
      : chip.label;
  });
}

function submittedLabels(state) {
  return state.submittedLanguages().map((language) => language.label);
}

function assertDeepEqual(actual, expected, name) {
  const actualJson = JSON.stringify(actual);
  const expectedJson = JSON.stringify(expected);

  if (actualJson !== expectedJson) {
    console.error(`FAIL ${name}`);
    console.error(`actual:   ${actualJson}`);
    console.error(`expected: ${expectedJson}`);
    process.exit(1);
  }

  console.log(`ok ${name}`);
}

function testFamilyExclusionWithLanguageAddBacks() {
  const state = new LanguageFilterState({ families });

  state.toggleGroup("family", "indo", true);
  state.toggleGroup("branch", "germanic", false);
  assertDeepEqual(chipLabels(state), ["Indo-European (- Germanic)"], "family minus branch");

  state.toggleLanguage("english", true);
  assertDeepEqual(
    chipLabels(state),
    ["Indo-European (- Germanic)", "English"],
    "single language add-back"
  );

  state.toggleLanguage("german", true);
  assertDeepEqual(
    chipLabels(state),
    ["Indo-European (- Germanic)", "English", "German"],
    "second language add-back remains explicit"
  );
  assertDeepEqual(
    submittedLabels(state),
    ["English", "German", "Polish", "Russian"],
    "submitted labels after partial add-back"
  );

  state.toggleLanguage("dutch", true);
  assertDeepEqual(chipLabels(state), ["Indo-European"], "completed branch collapses to family");
}

function testAllExclusionWithBranchAddBack() {
  const state = new LanguageFilterState({ families });

  state.toggleAll();
  state.toggleGroup("family", "indo", false);
  assertDeepEqual(chipLabels(state), ["All languages (- Indo-European)"], "all minus family");

  state.toggleLanguage("english", true);
  state.toggleLanguage("german", true);
  assertDeepEqual(
    chipLabels(state),
    ["All languages (- Indo-European)", "English", "German"],
    "language add-backs below all exclusion"
  );

  state.toggleLanguage("dutch", true);
  assertDeepEqual(
    chipLabels(state),
    ["All languages (- Indo-European)", "Germanic"],
    "completed branch add-back collapses to branch chip"
  );
  assertDeepEqual(
    submittedLabels(state),
    ["Dutch", "English", "German", "Japanese", "Okinawan"],
    "submitted labels after branch add-back"
  );
}

function testSearchOnlyLanguagesParticipateInAll() {
  const state = new LanguageFilterState({
    families,
    allLanguages: [
      { id: "english-flat", label: "English" },
      { id: "akkadian", label: "Akkadian" },
      { id: "sumerian", label: "Sumerian" },
    ],
  });

  state.toggleAll();
  assertDeepEqual(
    submittedLabels(state),
    ["Akkadian", "Dutch", "English", "German", "Japanese", "Okinawan", "Polish", "Russian", "Sumerian"],
    "all includes search-only languages"
  );

  state.toggleLanguage("akkadian", false);
  assertDeepEqual(
    chipLabels(state),
    ["All languages (- Akkadian)"],
    "all can exclude search-only language"
  );

  state.toggleLanguage("akkadian", true);
  assertDeepEqual(chipLabels(state), ["All languages"], "search-only language can be restored");
}

testFamilyExclusionWithLanguageAddBacks();
testAllExclusionWithBranchAddBack();
testSearchOnlyLanguagesParticipateInAll();
