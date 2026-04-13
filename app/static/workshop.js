// Personality Workshop — client-side builder logic.
// No frameworks. Reads form, writes live preview + Agent Card JSON, downloads.

(function () {
  const form = document.getElementById("builder-form");
  if (!form) return;

  const previewCard = document.getElementById("preview-card");
  const jsonPre = document.querySelector("#preview-json-pre code");
  const downloadBtn = document.getElementById("download-btn");
  const seedEl = document.getElementById("seed-data");

  const splitLines = (v) =>
    (v || "")
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);

  const splitSpaces = (v) =>
    (v || "")
      .split(/\s+/)
      .map((s) => s.trim())
      .filter(Boolean);

  const slugify = (name) =>
    (name || "persona")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "persona";

  function readForm() {
    const data = new FormData(form);
    const get = (k) => (data.get(k) || "").toString().trim();

    const persona = {};
    if (get("voice")) persona.voice = get("voice");

    const aesthetic = {};
    if (get("color")) aesthetic.color = get("color");
    if (get("motif")) aesthetic.motif = get("motif");
    if (get("style")) aesthetic.style = get("style");
    const emoji = splitSpaces(get("emoji"));
    if (emoji.length) aesthetic.emoji = emoji;
    if (Object.keys(aesthetic).length) persona.aesthetic = aesthetic;

    if (get("origin")) persona.origin = get("origin");
    const values = splitLines(get("values"));
    if (values.length) persona.values = values;
    const interests = splitLines(get("interests"));
    if (interests.length) persona.interests = interests;
    const rules = splitLines(get("critical_rules"));
    if (rules.length) persona.critical_rules = rules;
    if (get("pronouns")) persona.pronouns = get("pronouns");

    return {
      name: get("name"),
      description: get("description"),
      archetype: get("archetype"),
      persona,
    };
  }

  function buildAgentCard(tpl) {
    const card = {
      name: tpl.name || "Unnamed Persona",
      description: tpl.description || "",
      url: "https://YOUR-INSTANCE/agents/YOUR-AGENT-ID",
      version: "1.0.0",
      provider: {
        organization: "YOUR-ORGANIZATION",
        url: "https://YOUR-SITE",
      },
      capabilities: {
        streaming: true,
        pushNotifications: false,
        stateTransitionHistory: false,
      },
      skills: [],
      extensions: {
        "playground/persona": tpl.persona,
      },
    };
    return card;
  }

  function setText(selector, value, fallback) {
    const el = previewCard.querySelector(`[data-preview="${selector}"]`);
    if (!el) return;
    if (value) {
      el.textContent = value;
      el.classList.remove("dim");
    } else if (fallback !== undefined) {
      el.textContent = fallback;
      if (selector === "archetype") el.classList.add("dim");
    }
  }

  function updatePreview() {
    const tpl = readForm();
    const color =
      (tpl.persona.aesthetic && tpl.persona.aesthetic.color) || "#7b68ee";
    previewCard.style.setProperty("--accent", color);

    setText("name", tpl.name, "Unnamed");
    setText("archetype", tpl.archetype, "no archetype");
    setText(
      "description",
      tpl.description,
      "Your persona's description will appear here as you type.",
    );
    const emojiEl = previewCard.querySelector('[data-preview="emoji"]');
    if (emojiEl) {
      const emoji =
        (tpl.persona.aesthetic && tpl.persona.aesthetic.emoji) || [];
      emojiEl.textContent = emoji.join(" ");
    }

    const card = buildAgentCard(tpl);
    jsonPre.textContent = JSON.stringify(card, null, 2);
  }

  function download() {
    const tpl = readForm();
    if (!tpl.name) {
      const nameInput = form.querySelector('[name="name"]');
      if (nameInput) {
        nameInput.focus();
        nameInput.reportValidity();
      }
      return;
    }
    const card = buildAgentCard(tpl);
    const blob = new Blob([JSON.stringify(card, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${slugify(tpl.name)}-agent-card.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function prefillFromSeed() {
    if (!seedEl) return;
    let seed;
    try {
      seed = JSON.parse(seedEl.textContent || "null");
    } catch (e) {
      return;
    }
    if (!seed) return;

    const set = (name, value) => {
      const el = form.querySelector(`[name="${name}"]`);
      if (el && value !== undefined && value !== null) el.value = value;
    };

    set("name", seed.name);
    set("description", seed.description);
    set("archetype", seed.archetype);

    const p = seed.persona || {};
    set("voice", p.voice);
    set("origin", p.origin);
    set("pronouns", p.pronouns);
    set("values", (p.values || []).join("\n"));
    set("interests", (p.interests || []).join("\n"));
    set("critical_rules", (p.critical_rules || []).join("\n"));

    const a = p.aesthetic || {};
    if (a.color) set("color", a.color);
    set("motif", a.motif);
    set("style", a.style);
    set("emoji", (a.emoji || []).join(" "));
  }

  prefillFromSeed();
  updatePreview();

  form.addEventListener("input", updatePreview);
  form.addEventListener("reset", () => {
    // Give the browser a tick to apply the reset before we re-render.
    setTimeout(updatePreview, 0);
  });
  downloadBtn.addEventListener("click", download);
})();
