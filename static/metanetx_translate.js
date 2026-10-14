// ---------------------------------------------------------------------------
// Annotation & Translation: translate ids through MetaNetX.
// Every id is mapped to its MetaNetX id first, then to the chosen namespace
// (MetaNetX itself, BiGG, VMH, ModelSEED, KEGG or MetaCyc). Built from the
// same panel factory as the SEED -> VMH tab (translate.js).
// Loaded after translate.js.
// ---------------------------------------------------------------------------
const metanetxPanel = createTranslatePanel({
  panelId: "mnxtranslate",
  key: "mnxTranslate",
  title: "Translate via MetaNetX",
  introHtml: `
      Renames the metabolite and reaction ids of the loaded model to another namespace <strong>through MetaNetX</strong>:
      whatever namespace the model is in is detected, each id is mapped to its MetaNetX id, and that is mapped to the
      namespace you choose (or kept as the MetaNetX id). Every id ends up as <strong>mapped</strong>, an
      <strong>error</strong> (the MetaNetX id has several ids in the target namespace, or the new id would clash with
      another id) or <strong>no available mapping</strong>; the last two keep their original id. Exchange, demand and sink
      reactions are renamed from their metabolite. Gene and compartment ids are not translated. The translation starts from
      the model file as uploaded (before any diet), and the loaded model is not changed.`,
  controlsHtml: `
      <label for="mnxTarget">Translate to</label>
      <select id="mnxTarget">
        <option value="metanetx" selected>MetaNetX (MNXM… / MNXR…)</option>
        <option value="bigg">BiGG</option>
        <option value="vmh">VMH</option>
        <option value="seed">ModelSEED</option>
        <option value="kegg">KEGG</option>
        <option value="metacyc">MetaCyc</option>
      </select>
      <label for="mnxStyle">Compartment tags</label>
      <select id="mnxStyle">
        <option value="auto" selected>Target's convention (VMH h2o[c], BiGG h2o_c)</option>
        <option value="keep">Keep the model's own tags</option>
        <option value="underscore">Underscore (h2o_c)</option>
        <option value="bracket">Brackets (h2o[c])</option>
      </select>
      <label title="When a MetaNetX id has several ids in the target namespace, use the first instead of reporting an error"><input id="mnxPickFirst" type="checkbox"> use the first id when ambiguous</label>`,
  runLabel: "Translate",
  endpoint: "/api/translate-metanetx",
  downloadBase: "/api/translate-metanetx",
  requestBody: () => ({ target: $("mnxTarget").value, style: $("mnxStyle").value, pick_first: $("mnxPickFirst").checked }),
  groups: [
    { key: "mapped", label: "Mapped", hint: "Renamed to their id in the target namespace (a note is given when the first of several ids was used).", file: "metanetx_translation_mapped.csv",
      columns: [{ key: "kind", label: "Type" }, { key: "original_id", label: "Original id" }, { key: "mnx_id", label: "MetaNetX id" },
        { key: "target_id", label: "Target id(s)" }, { key: "new_id", label: "New id in model" }, { key: "name", label: "Name" }, { key: "reason", label: "Note" }] },
    { key: "errors", label: "Errors", hint: "Ambiguous in the target namespace, or the new id would clash. Original id kept.", file: "metanetx_translation_errors.csv",
      columns: [{ key: "kind", label: "Type" }, { key: "original_id", label: "Original id" }, { key: "mnx_id", label: "MetaNetX id" },
        { key: "target_id", label: "Candidate id(s)" }, { key: "reason", label: "Problem" }, { key: "name", label: "Name" }] },
    { key: "unmapped", label: "No available mapping", hint: "No MetaNetX id, or none in the target namespace. Original id kept.", file: "metanetx_translation_unmapped.csv",
      columns: [{ key: "kind", label: "Type" }, { key: "original_id", label: "Original id" }, { key: "mnx_id", label: "MetaNetX id" },
        { key: "name", label: "Name" }, { key: "reason", label: "Reason" }] },
  ],
});

function renderMetanetxTranslate() { metanetxPanel.render(); }
