(() => {
  const originalRunCandidateAction = window.runCandidateAction;
  if (typeof originalRunCandidateAction !== "function") return;

  const classificationLabels = {
    misinformed_or_potentially_misleading: "Misinformed or potentially misleading",
    not_misleading: "Not misleading",
  };
  const tagLabels = {
    disputed_claim_as_fact: "Disputed claim presented as fact",
    factual_error: "Factual error",
    manipulated_media: "Manipulated media",
    misinterpreted_satire: "Misinterpreted satire",
    missing_important_context: "Missing important context",
    outdated_information: "Outdated information",
    other: "Other",
  };

  function installSubmissionMetadataControls() {
    const actionResult = document.querySelector("#action-result");
    if (!actionResult || document.querySelector("#submission-metadata-controls")) return;

    const controls = document.createElement("div");
    controls.id = "submission-metadata-controls";
    controls.className = "codebox";
    controls.innerHTML = `
      <strong>Exact X submission classification</strong>
      <p class="muted">Select these before approval. The selection is bound into the exact approval hash and cannot change without reapproval.</p>
      <label>
        Classification
        <select id="submission-classification" class="filter">
          <option value="">Select classification</option>
          ${Object.entries(classificationLabels).map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}
        </select>
      </label>
      <fieldset id="misleading-tag-fieldset" style="border:0;padding:10px 0 0;margin:0">
        <legend>Misleading tags</legend>
        <div class="stack">
          ${Object.entries(tagLabels).map(([value, label]) => `<label><input type="checkbox" name="misleading-tag" value="${value}"> ${label}</label>`).join("")}
        </div>
      </fieldset>
    `;
    actionResult.parentNode.insertBefore(controls, actionResult);

    const classification = controls.querySelector("#submission-classification");
    const fieldset = controls.querySelector("#misleading-tag-fieldset");
    const updateTagState = () => {
      const notMisleading = classification.value === "not_misleading";
      fieldset.disabled = notMisleading;
      if (notMisleading) {
        fieldset.querySelectorAll('input[name="misleading-tag"]').forEach((input) => {
          input.checked = false;
        });
      }
    };
    classification.addEventListener("change", updateTagState);
    updateTagState();
  }

  window.runCandidateAction = async function runCandidateActionWithSubmissionMetadata(candidateId, action, draftId) {
    if (action !== "approve") {
      return originalRunCandidateAction(candidateId, action, draftId);
    }

    const result = document.querySelector("#action-result");
    result.textContent = "Running...";
    try {
      const classification = document.querySelector("#submission-classification")?.value || "";
      if (!classification) throw new Error("Select the exact Community Notes classification before approval.");
      const misleadingTags = [...document.querySelectorAll('input[name="misleading-tag"]:checked')].map((input) => input.value);
      if (classification === "misinformed_or_potentially_misleading" && !misleadingTags.length) {
        throw new Error("Select at least one misleading tag before approval.");
      }
      const payload = await window.api(`/api/drafts/${draftId}/approve`, {
        method: "POST",
        body: {
          classification,
          misleading_tags: classification === "not_misleading" ? [] : misleadingTags,
        },
      });
      result.textContent = JSON.stringify(payload, null, 2);
      await window.renderCandidateDetail(candidateId);
      return payload;
    } catch (error) {
      result.textContent = error.message;
      return null;
    }
  };

  const observer = new MutationObserver(installSubmissionMetadataControls);
  const app = document.querySelector("#app");
  if (app) observer.observe(app, {childList: true, subtree: true});
  installSubmissionMetadataControls();
})();
