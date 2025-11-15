// app.js - Patient portal per Medical AI backend

// Backend URL: can be overridden via window.__BACKEND_URL__ (set in config.js or inline script)
const backendUrl = window.__BACKEND_URL__ || "http://127.0.0.1:8000";
const FSE_URL =
  "https://fascicolosanitario.sanita.finanze.it/FseInsAssistitoWeb/pages/includes/documentiHome.jsf?id=1";

const state = {
  patientId: null,
  profile: null,
  token: null,
  email: null,
  tokenExpiresAt: null,
  documents: [],
  documentsBySpecialty: {},
  aggregatesExpanded: false,
  passwordResetToken: null,
  activeTab: "documentsTab",
  documentSearch: "",
  pendingDownload: null,
};

const el = {
  statusBar: document.getElementById("statusBar"),
  loginSection: document.getElementById("loginSection"),
  signupModal: document.getElementById("signupModal"),
  passwordResetModal: document.getElementById("passwordResetModal"),
  resetStepInit: document.getElementById("resetStepInit"),
  resetStepVerify: document.getElementById("resetStepVerify"),
  appShell: document.getElementById("appShell"),
  operationsOutput: document.getElementById("operationsOutput"),
  pendingPatientsList: document.getElementById("pendingPatientsList"),

  patientIdInput: document.getElementById("patientIdInput"),
  emailInput: document.getElementById("emailInput"),
  passwordInput: document.getElementById("passwordInput"),
  inviteTokenInput: document.getElementById("inviteTokenInput"),
  loginStatus: document.getElementById("loginStatus"),

  patientName: document.getElementById("patientName"),
  patientDetails: document.getElementById("patientDetails"),
  aggregatesContainer: document.getElementById("aggregatesContainer"),
  documentsContainer: document.getElementById("documentsContainer"),
  specialtyContainer: document.getElementById("specialtyContainer"),
  chatOutput: document.getElementById("chatOutput"),
  invitesList: document.getElementById("invitesList"),
  accessRequestsList: document.getElementById("accessRequestsList"),

  questionInput: document.getElementById("questionInput"),
  inviteHoursInput: document.getElementById("inviteHoursInput"),
  inviteNoteInput: document.getElementById("inviteNoteInput"),
  inviteCreatorInput: document.getElementById("inviteCreatorInput"),

  downloadSourceInput: document.getElementById("downloadSourceInput"),
  analyzeFolderInput: document.getElementById("analyzeFolderInput"),
  autoAuthorizeCheckbox: document.getElementById("autoAuthorizeCheckbox"),
  ocrCheckbox: document.getElementById("ocrCheckbox"),
  overwriteAnalysisCheckbox: document.getElementById("overwriteAnalysisCheckbox"),
  visionAnalysisCheckbox: document.getElementById("visionAnalysisCheckbox"),
  askVisionCheckbox: document.getElementById("askVisionCheckbox"),
  localPdfInput: document.getElementById("localPdfInput"),
  documentSearchInput: document.getElementById("documentSearchInput"),
  fseDownloadHint: document.getElementById("fseDownloadHint"),

  signupPatientId: document.getElementById("signupPatientId"),
  signupName: document.getElementById("signupName"),
  signupCf: document.getElementById("signupCf"),
  signupDob: document.getElementById("signupDob"),
  signupEmail: document.getElementById("signupEmail"),
  signupPhone: document.getElementById("signupPhone"),
  signupSecurityQuestion: document.getElementById("signupSecurityQuestion"),
  signupSecurityAnswer: document.getElementById("signupSecurityAnswer"),
  signupNote: document.getElementById("signupNote"),
  signupStatus: document.getElementById("signupStatus"),
  resetIdentifierInput: document.getElementById("resetIdentifierInput"),
  resetAnswerInput: document.getElementById("resetAnswerInput"),
  resetNewPasswordInput: document.getElementById("resetNewPasswordInput"),
  resetQuestion: document.getElementById("resetQuestion"),
  resetStatus: document.getElementById("resetStatus"),
  currentPasswordInput: document.getElementById("currentPasswordInput"),
  newPasswordInput: document.getElementById("newPasswordInput"),
  confirmPasswordInput: document.getElementById("confirmPasswordInput"),
  changePasswordStatus: document.getElementById("changePasswordStatus"),
};

const buttons = {
  login: document.getElementById("loginBtn"),
  register: document.getElementById("registerBtn"),
  openSignup: document.getElementById("openSignupBtn"),
  claimInvite: document.getElementById("claimInviteBtn"),
  refreshProfile: document.getElementById("refreshProfileBtn"),
  logout: document.getElementById("logoutBtn"),
  ask: document.getElementById("askBtn"),
  refreshDocs: document.getElementById("refreshDocsBtn"),
  createInvite: document.getElementById("createInviteBtn"),
  download: document.getElementById("downloadBtn"),
  list: document.getElementById("listBtn"),
  analyze: document.getElementById("analyzeBtn"),
  pendingPatients: document.getElementById("pendingPatientsBtn"),
  refreshDownloadList: document.getElementById("refreshDownloadListBtn"),
  uploadLocalPdf: document.getElementById("uploadLocalPdfBtn"),
  signupSubmit: document.getElementById("signupSubmitBtn"),
  startFseDownload: document.getElementById("startFseDownloadBtn"),
  continueFseDownload: document.getElementById("continueFseDownloadBtn"),
  analyzeProfile: document.getElementById("analyzeProfileBtn"),
  toggleAggregates: document.getElementById("toggleAggregatesBtn"),
  closeSignup: document.getElementById("closeSignupBtn"),
  closeSignupBackdrop: document.getElementById("closeSignupBackdrop"),
  forgotPassword: document.getElementById("forgotPasswordBtn"),
  closeReset: document.getElementById("closeResetBtn"),
  closeResetBackdrop: document.getElementById("closeResetBackdrop"),
  resetInit: document.getElementById("resetInitBtn"),
  resetComplete: document.getElementById("resetCompleteBtn"),
  changePassword: document.getElementById("changePasswordBtn"),
  logoutSettings: document.getElementById("logoutSettingsBtn"),
};

const navButtons = Array.from(document.querySelectorAll(".nav-btn"));
const tabPanels = Array.from(document.querySelectorAll(".tab-panel"));

const COLLAPSED_AGGREGATE_HEIGHT = 260;

function setStatus(message, type = "info") {
  if (!el.statusBar) return;
  el.statusBar.textContent = message;
  el.statusBar.classList.remove("status-info", "status-error", "status-success");
  const className =
    type === "error" ? "status-error" : type === "success" ? "status-success" : "status-info";
  el.statusBar.classList.add(className);
}

function setLoginStatus(message) {
  if (el.loginStatus) {
    el.loginStatus.textContent = message || "";
  }
}

function storeSession(token, patientId, expiresAt) {
  state.token = token;
  state.patientId = patientId;
  state.tokenExpiresAt = expiresAt || null;
}

function openSignupModal(prefill = {}) {
  if (!el.signupModal) return;
  el.signupModal.classList.remove("hidden");
  el.signupPatientId.value = prefill.patientId || "";
  el.signupName.value = prefill.nome || "";
  el.signupCf.value = prefill.codice_fiscale || "";
  el.signupDob.value = prefill.data_nascita || "";
  el.signupEmail.value = prefill.email || "";
  el.signupPhone.value = prefill.telefono || "";
  el.signupSecurityQuestion.value = prefill.security_question || "";
  el.signupSecurityAnswer.value = "";
  el.signupNote.value = prefill.note || "";
  el.signupStatus.textContent = "";
}

function closeSignupModal() {
  if (!el.signupModal) return;
  el.signupModal.classList.add("hidden");
}

function switchResetStep(step) {
  if (!el.resetStepInit || !el.resetStepVerify) return;
  if (step === "verify") {
    el.resetStepInit.classList.add("hidden");
    el.resetStepVerify.classList.remove("hidden");
  } else {
    el.resetStepInit.classList.remove("hidden");
    el.resetStepVerify.classList.add("hidden");
  }
}

function openPasswordResetModal() {
  if (!el.passwordResetModal) return;
  el.passwordResetModal.classList.remove("hidden");
  switchResetStep("init");
  el.resetIdentifierInput.value = "";
  el.resetAnswerInput.value = "";
  el.resetNewPasswordInput.value = "";
  el.resetQuestion.textContent = "";
  el.resetStatus.textContent = "";
  state.passwordResetToken = null;
}

function closePasswordResetModal() {
  if (!el.passwordResetModal) return;
  el.passwordResetModal.classList.add("hidden");
  switchResetStep("init");
  el.resetIdentifierInput.value = "";
  el.resetAnswerInput.value = "";
  el.resetNewPasswordInput.value = "";
  el.resetQuestion.textContent = "";
  el.resetStatus.textContent = "";
  state.passwordResetToken = null;
}

function clearSession() {
  state.token = null;
  state.patientId = null;
  state.profile = null;
  state.email = null;
  state.tokenExpiresAt = null;
  state.documents = [];
  state.documentsBySpecialty = {};
  state.aggregatesExpanded = false;
  state.passwordResetToken = null;
  state.documentSearch = "";
  state.activeTab = "documentsTab";
  if (window.__docRefreshTimeout) {
    clearTimeout(window.__docRefreshTimeout);
    window.__docRefreshTimeout = null;
  }
  state.pendingDownload = null;
  buttons.continueFseDownload?.classList.add("hidden");
  if (el.fseDownloadHint) {
    el.fseDownloadHint.classList.add("hidden");
    el.fseDownloadHint.textContent = "";
  }
  if (el.documentSearchInput) {
    el.documentSearchInput.value = "";
  }
  if (el.aggregatesContainer) {
    el.aggregatesContainer.innerHTML = "";
    el.aggregatesContainer.classList.remove("expanded", "clamped");
  }
  buttons.toggleAggregates?.classList.add("hidden");
  if (buttons.toggleAggregates) {
    buttons.toggleAggregates.textContent = "Mostra tutto";
  }
  closeSignupModal();
  closePasswordResetModal();
}

function toggleDashboard(show) {
  if (show) {
    el.appShell?.classList.remove("hidden");
    el.loginSection?.classList.add("hidden");
  } else {
    el.appShell?.classList.add("hidden");
    el.loginSection?.classList.remove("hidden");
  }
  closeSignupModal();
  closePasswordResetModal();
}

function switchTab(tabId) {
  state.activeTab = tabId;
  tabPanels.forEach((panel) => panel.classList.toggle("hidden", panel.id !== tabId));
  navButtons.forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tabId));

  if (tabId === "documentsTab") {
    // refresh download list on entry to document area
    listDownloadsHandler();
  } else if (tabId === "profileTab" && state.patientId && state.token) {
    loadDocuments();
  }
}

function escapeHtml(str) {
  return (str || "")
    .toString()
    .replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch] || ch));
}

async function fetchJson(path, options = {}) {
  const opts = { ...options };
  opts.headers = opts.headers ? { ...opts.headers } : {};
  if (opts.body && !(opts.body instanceof FormData)) {
    if (typeof opts.body === "object") {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
  }
  if (state.token && !("Authorization" in opts.headers)) {
    opts.headers.Authorization = `Bearer ${state.token}`;
  }
  const response = await fetch(path, opts);
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch (err) {
    throw new Error("Risposta non valida dal server");
  }
  if (!response.ok) {
    const detail = data?.detail || data?.message || response.statusText;
    throw new Error(detail);
  }
  return data;
}

function ensureOk(data) {
  if (!data) {
    throw new Error("Risposta vuota dal backend");
  }
  if (data.status && !["ok", "success"].includes(data.status)) {
    throw new Error(data.message || "Operazione non riuscita");
  }
  return data;
}

function formatIso(dateStr) {
  if (!dateStr) return "-";
  const parsed = new Date(dateStr);
  if (Number.isNaN(parsed.getTime())) return dateStr;
  return parsed.toLocaleString("it-IT", { dateStyle: "medium", timeStyle: "short" });
}

function renderProfile() {
  const profile = state.profile;
  if (!profile) return;
  const name = profile.nome || state.patientId || "Paziente";
  el.patientName.textContent = name;

  const metaParts = [];
  if (profile.codice_fiscale) metaParts.push(`Codice fiscale: <strong>${escapeHtml(profile.codice_fiscale)}</strong>`);
  if (profile.email || state.email) metaParts.push(`Email: <strong>${escapeHtml(profile.email || state.email)}</strong>`);
  if (profile.data_nascita) metaParts.push(`Data di nascita: <strong>${escapeHtml(profile.data_nascita)}</strong>`);
  metaParts.push(`Ultimo aggiornamento: <strong>${formatIso(profile.ultimo_aggiornamento)}</strong>`);
  el.patientDetails.innerHTML = metaParts.join(" | ");

  renderAggregates(profile.aggregati);
}

function updateAggregatesClamp() {
  const container = el.aggregatesContainer;
  const btn = buttons.toggleAggregates;
  if (!container || !btn) return;

  const needsClamp = container.scrollHeight > COLLAPSED_AGGREGATE_HEIGHT + 4;
  container.classList.toggle("expanded", state.aggregatesExpanded);
  container.classList.toggle("clamped", !state.aggregatesExpanded && needsClamp);

  btn.classList.remove("hidden");
  btn.disabled = false;
  btn.textContent = state.aggregatesExpanded ? "Mostra meno" : "Mostra tutto";
}

function renderAggregates(aggregates) {
  if (!el.aggregatesContainer) return;
  const container = el.aggregatesContainer;
  state.aggregatesExpanded = false;
  container.scrollTop = 0;

  if (!aggregates) {
    container.innerHTML = '<p class="muted">Nessuna informazione aggregata disponibile.</p>';
    container.classList.remove("expanded", "clamped");
    buttons.toggleAggregates?.classList.add("hidden");
    if (buttons.toggleAggregates) {
      buttons.toggleAggregates.textContent = "Mostra tutto";
    }
    return;
  }

  const sections = [
    { key: "anamnesi", label: "Anamnesi" },
    { key: "terapie", label: "Terapie" },
    { key: "esami_laboratorio", label: "Esami di laboratorio" },
    { key: "esami_diagnostica", label: "Diagnostica per immagini" },
  ];

  const blocks = sections
    .map(({ key, label }) => {
      const items = aggregates[key];
      if (!items || !items.length) return "";
      const list = items.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
      return `
        <div>
          <h4>${label}</h4>
          <ul>${list}</ul>
        </div>
      `;
    })
    .filter(Boolean);

  container.innerHTML = blocks.length
    ? blocks.join("")
    : "<p class=\"muted\">Ancora nessuna informazione aggregata.</p>";
  container.classList.remove("expanded", "clamped");
  buttons.toggleAggregates?.classList.add("hidden");
  if (buttons.toggleAggregates) buttons.toggleAggregates.textContent = "Mostra tutto";
  requestAnimationFrame(() => updateAggregatesClamp());
}

function renderSpecialtyLibraries() {
  if (!el.specialtyContainer) return;
  if (!state.patientId || !state.token) {
    el.specialtyContainer.innerHTML = "<p class=\"muted\">Accedi per visualizzare i documenti per specialita.</p>";
    return;
  }
  const docs = Array.isArray(state.documents) ? state.documents : [];
  const backendGrouped = state.documentsBySpecialty && typeof state.documentsBySpecialty === "object"
    ? state.documentsBySpecialty
    : {};
  const normalizedGrouped = Object.entries(backendGrouped)
    .filter(([, list]) => Array.isArray(list) && list.length > 0)
    .reduce((acc, [spec, list]) => {
      acc[spec] = list;
      return acc;
    }, {});
  const hasBackendGrouping = Object.keys(normalizedGrouped).length > 0;
  if (!docs.length && !hasBackendGrouping) {
    el.specialtyContainer.innerHTML = "<p class=\"muted\">Nessun documento raggruppato per specialita.</p>";
    return;
  }

  const grouped = hasBackendGrouping
    ? normalizedGrouped
    : docs.reduce((acc, doc) => {
        const spec = (doc.specialita || "altro").trim() || "altro";
        acc[spec] = acc[spec] || [];
        acc[spec].push({
          file: doc.file,
          stored_filename: doc.stored_filename || (doc.pdf_path ? doc.pdf_path.split(/[/\\]/).pop() : ""),
          data_documento: doc.data_documento,
          tipologia: doc.tipologia,
          riassunto: doc.riassunto,
        });
        return acc;
      }, {});

  const cards = Object.entries(grouped)
    .sort((a, b) => a[0].localeCompare(b[0], "it", { sensitivity: "base" }))
    .map(([spec, list]) => {
      const items = list
        .map((doc) => {
          const stored = doc.stored_filename || (doc.pdf_path ? doc.pdf_path.split(/[/\\]/).pop() : "");
          if (!stored) return "";
          const label = doc.file || stored;
          const detailParts = [doc.tipologia, doc.data_documento].filter(Boolean);
          const detail = detailParts.length ? `<br><small>${escapeHtml(detailParts.join(" · "))}</small>` : "";
          const downloadUrl = `${backendUrl}/patients/${encodeURIComponent(
            state.patientId
          )}/documents/download?filename=${encodeURIComponent(stored)}`;
          return `
            <li>
              <div class="doc-entry">
                <span>
                  <strong>${escapeHtml(label)}</strong>
                  ${detail}
                </span>
                <a class="ghost small" href="${downloadUrl}" target="_blank" rel="noopener">
                  Scarica
                </a>
              </div>
            </li>
          `;
        })
        .filter(Boolean)
        .join("");
      if (!items) return "";
      return `
        <div class="specialty-card">
          <h4>${escapeHtml(spec)}</h4>
          <ul>${items}</ul>
        </div>
      `;
    })
    .filter(Boolean);

  el.specialtyContainer.innerHTML = cards.length
    ? cards.join("")
    : "<p class=\"muted\">Nessun documento raggruppato per specialita.</p>";
}
function renderDocuments(docs) {
  if (!el.documentsContainer) return;
  const term = (state.documentSearch || "").trim();
  const termLower = term.toLowerCase();
  if (el.documentSearchInput && el.documentSearchInput.value !== term) {
    el.documentSearchInput.value = term;
  }
  const filtered = Array.isArray(docs)
    ? docs.filter((doc) => {
        if (!termLower) return true;
        const haystack = [
          doc.file,
          doc.tipologia,
          doc.specialita,
          doc.data_documento,
          doc.riassunto,
          ...(doc.diagnosi_principali || []),
          ...(doc.farmaci_prescritti || []),
        ]
          .join(" ")
          .toLowerCase();
        return haystack.includes(termLower);
      })
    : [];

  if (!filtered.length) {
    const message = term
      ? `<p class="muted">Nessun documento corrisponde alla ricerca "<strong>${escapeHtml(term)}</strong>".</p>`
      : "<p>Nessun documento registrato per questo paziente.</p>";
    el.documentsContainer.innerHTML = message;
    return;
  }

  const rows = filtered
    .map((doc) => {
      const diagnoses = (doc.diagnosi_principali || []).map((item) => `<span class=\"tag\">${escapeHtml(item)}</span>`).join(" ") || "-";
      const meds = (doc.farmaci_prescritti || []).map((item) => `<span class=\"tag\">${escapeHtml(item)}</span>`).join(" ") || "-";
      const storedName = doc.stored_filename || doc.file;
      return `
        <tr>
          <td>${escapeHtml(doc.file || "-")}</td>
          <td>${escapeHtml(doc.tipologia || "-")}</td>
          <td>${escapeHtml(doc.specialita || "-")}</td>
          <td>${escapeHtml(doc.data_documento || "-")}</td>
          <td>${escapeHtml(doc.riassunto || "-")}</td>
          <td>${diagnoses}</td>
          <td>${meds}</td>
          <td>
            <button
              class="ghost small"
              data-action="download-doc"
              data-stored="${escapeHtml(storedName || "")}"
              data-name="${escapeHtml(doc.file || storedName || "documento.pdf")}"
            >
              Scarica
            </button>
          </td>
        </tr>
      `;
    })
    .join("");

  el.documentsContainer.innerHTML = `
    <div class=\"table-wrapper\">
      <table class=\"documents-table\">
        <thead>
          <tr>
            <th>File</th>
            <th>Tipologia</th>
            <th>Specialita</th>
            <th>Data</th>
            <th>Riassunto</th>
            <th>Diagnosi principali</th>
            <th>Farmaci</th>
            <th>Azioni</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;

  el.documentsContainer.querySelectorAll('[data-action="download-doc"]').forEach((btn) => {
    btn.addEventListener("click", () => {
      const stored = btn.getAttribute("data-stored");
      const suggested = btn.getAttribute("data-name");
      if (stored) {
        downloadDocument(stored, suggested);
      } else {
        setStatus("File non disponibile per il download.", "error");
      }
    });
  });
}

async function downloadDocument(storedFilename, suggestedName) {
  if (!storedFilename || !state.patientId || !state.token) {
    setStatus("Non sei autorizzato a scaricare questo documento.", "error");
    return;
  }
  try {
    const response = await fetch(
      `${backendUrl}/patients/${encodeURIComponent(state.patientId)}/documents/download?filename=${encodeURIComponent(
        storedFilename
      )}`,
      {
        headers: { Authorization: `Bearer ${state.token}` },
      }
    );
    if (!response.ok) {
      const message = await response.text();
      throw new Error(message || response.statusText);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = suggestedName || storedFilename.split("/").pop() || "documento.pdf";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    setStatus(`Errore nel download del documento: ${error.message}`, "error");
  }
}

function handleDocumentSearch() {
  state.documentSearch = (el.documentSearchInput?.value || "").trim();
  renderDocuments(state.documents || []);
}

function renderInvites(invites) {
  if (!el.invitesList) return;
  if (!Array.isArray(invites) || !invites.length) {
    el.invitesList.innerHTML = "<p class=\"muted\">Nessun invito attivo. Crea un nuovo token per condividere i documenti.</p>";
    return;
  }

  el.invitesList.innerHTML = invites
    .map((invite) => {
      const statusClass = `badge ${invite.status || ""}`.trim();
      return `
        <div class=\"list-item\" data-token=\"${escapeHtml(invite.token)}\">
          <header>
            <span>Token: <code>${escapeHtml(invite.token)}</code></span>
            <span class=\"${statusClass}\">${escapeHtml(invite.status || "")}</span>
          </header>
          <p>Creato da: <strong>${escapeHtml(invite.created_by || "-")}</strong></p>
          <p>Nota: ${escapeHtml(invite.note || "-")}</p>
          <p>Creato il: ${formatIso(invite.created_at)}</p>
          <p>Scadenza: ${formatIso(invite.expires_at)}</p>
          <div class=\"actions\">
            <button class=\"ghost\" data-action=\"copy-token\">Copia token</button>
          </div>
        </div>
      `;
    })
    .join("");

  el.invitesList.querySelectorAll('[data-action="copy-token"]').forEach((btn) => {
    btn.addEventListener("click", () => {
      const token = btn.closest("[data-token]")?.dataset.token;
      if (token && navigator.clipboard) {
        navigator.clipboard.writeText(token).then(() => setStatus("Token copiato negli appunti.", "success"));
      }
    });
  });
}

function renderAccessRequests(requests) {
  if (!el.accessRequestsList) return;
  if (!Array.isArray(requests) || !requests.length) {
    el.accessRequestsList.innerHTML = "<p class=\"muted\">Nessuna richiesta di accesso da approvare.</p>";
    return;
  }

  el.accessRequestsList.innerHTML = requests
    .map((req) => {
      const statusClass = `badge ${req.status || ""}`.trim();
      return `
        <div class=\"list-item\" data-request-id=\"${escapeHtml(req.request_id)}\">
          <header>
            <span>${escapeHtml(req.requester || "Richiedente sconosciuto")}</span>
            <span class=\"${statusClass}\">${escapeHtml(req.status || "-")}</span>
          </header>
          <p>Messaggio: ${escapeHtml(req.message || "-")}</p>
          <p>Contatto: ${escapeHtml(req.contact || "-")}</p>
          <p>Inviata il: ${formatIso(req.created_at)}</p>
          ${req.updated_at ? `<p>Aggiornata il: ${formatIso(req.updated_at)}</p>` : ""}
          <div class=\"actions\">
            ${req.status === "pending"
              ? '<button class=\"primary\" data-action=\"approve\">Approva</button><button class=\"ghost\" data-action=\"reject\">Rifiuta</button>'
              : ""}
          </div>
        </div>
      `;
    })
    .join("");

  el.accessRequestsList.querySelectorAll('[data-action="approve"], [data-action="reject"]').forEach((btn) => {
    btn.addEventListener("click", () => {
      const container = btn.closest("[data-request-id]");
      const requestId = container?.dataset.requestId;
      if (!requestId) return;
      const newStatus = btn.dataset.action === "approve" ? "approved" : "rejected";
      const note = prompt("Inserisci una nota (opzionale)", "");
      updateAccessRequestStatus(requestId, newStatus, note || undefined);
    });
  });
}

async function loadPatientProfile(patientId, { silent = false } = {}) {
  if (!patientId || !state.token) {
    if (!silent) setStatus("Accedi prima di consultare il profilo.", "error");
    return;
  }
  try {
    if (!silent) setStatus("Caricamento profilo in corso...", "info");
    const data = ensureOk(await fetchJson(`${backendUrl}/patients/${encodeURIComponent(patientId)}`));
    state.patientId = patientId;
    state.profile = data.profile;
    state.documents = [];
    state.documentsBySpecialty = data.profile?.documents_by_specialty || {};
    if (data.profile?.email) {
      state.email = data.profile.email;
    } else {
      try {
        const me = ensureOk(await fetchJson(`${backendUrl}/auth/me`));
        state.email = me.email || state.email;
      } catch {
        // ignora errori di /auth/me
      }
    }
    renderProfile();
    renderSpecialtyLibraries();
    toggleDashboard(true);
    if (!silent) {
      setStatus("Profilo paziente caricato con successo.", "success");
    }
    await Promise.all([loadDocuments(), loadInvites(), loadAccessRequests()]);
  } catch (error) {
    if (error.message && error.message.toLowerCase().includes("token")) {
      clearSession();
      toggleDashboard(false);
    }
    setStatus(`Errore durante il caricamento del profilo: ${error.message}`, "error");
  }
}

async function loadDocuments() {
  if (!state.patientId || !state.token) return;
  try {
    const data = ensureOk(
      await fetchJson(`${backendUrl}/patients/${encodeURIComponent(state.patientId)}/documents`)
    );
    state.documents = data.documents || [];
    state.documentsBySpecialty = data.documents_by_specialty || {};
    renderDocuments(state.documents);
    renderSpecialtyLibraries();
  } catch (error) {
    el.documentsContainer.innerHTML = `<p class=\"muted\">Errore nel recupero dei documenti: ${escapeHtml(
      error.message
    )}</p>`;
    state.documents = [];
    state.documentsBySpecialty = {};
    renderSpecialtyLibraries();
  }

  if (window.__docRefreshTimeout) {
    clearTimeout(window.__docRefreshTimeout);
  }
  if (state.patientId) {
    window.__docRefreshTimeout = setTimeout(() => {
      loadDocuments();
    }, 30000);
  }
}

async function loadInvites() {
  if (!state.patientId || !state.token) return;
  try {
    const data = ensureOk(
      await fetchJson(
        `${backendUrl}/patients/${encodeURIComponent(state.patientId)}/invites?include_expired=true`
      )
    );
    renderInvites(data.invites || []);
  } catch (error) {
    el.invitesList.innerHTML = `<p class=\"muted\">Errore nel recupero degli inviti: ${escapeHtml(
      error.message
    )}</p>`;
  }
}

async function loadAccessRequests() {
  if (!state.patientId || !state.token) return;
  try {
    const params = new URLSearchParams({ patient_id: state.patientId });
    const data = ensureOk(await fetchJson(`${backendUrl}/access/requests?${params.toString()}`));
    renderAccessRequests(data.requests || []);
  } catch (error) {
    el.accessRequestsList.innerHTML = `<p class=\"muted\">Errore nel recupero delle richieste: ${escapeHtml(
      error.message
    )}</p>`;
  }
}

async function updateAccessRequestStatus(requestId, status, note) {
  try {
    ensureOk(
      await fetchJson(`${backendUrl}/access/requests/${encodeURIComponent(requestId)}/status`, {
        method: "POST",
        body: { status, note },
      })
    );
    setStatus(`Richiesta ${status === "approved" ? "approvata" : "rifiutata"}.`, "success");
    await loadAccessRequests();
  } catch (error) {
    setStatus(`Impossibile aggiornare la richiesta: ${error.message}`, "error");
  }
}

async function loginHandler() {
  const identifier = (el.emailInput.value || el.patientIdInput.value).trim();
  const password = el.passwordInput.value.trim();
  if (!identifier || !password) {
    setStatus("Inserisci email (o ID paziente) e password per accedere.", "error");
    return;
  }
  try {
    const data = await fetchJson(`${backendUrl}/auth/login`, {
      method: "POST",
      body: { identifier, password },
    });
    storeSession(data.token, data.patient_id, data.expires_at);
    el.passwordInput.value = "";
    el.patientIdInput.value = data.patient_id;
    const emailValue = el.emailInput.value.trim();
    if (emailValue) {
      state.email = emailValue;
    }
    await loadPatientProfile(data.patient_id);
    setLoginStatus("");
    state.documentSearch = "";
    if (el.documentSearchInput) {
      el.documentSearchInput.value = "";
    }
    switchTab("documentsTab");
    setStatus("Accesso effettuato.", "success");
  } catch (error) {
    clearSession();
    setStatus(`Accesso negato: ${error.message}`, "error");
  }
}

async function logoutHandler() {
  try {
    if (state.token) {
      await fetchJson(`${backendUrl}/auth/logout`, { method: "POST" });
    }
  } catch {
    // silenzia errori di logout
  } finally {
    clearSession();
    el.patientIdInput.value = "";
    el.emailInput.value = "";
    el.passwordInput.value = "";
    el.inviteTokenInput.value = "";
    el.questionInput.value = "";
    el.chatOutput.textContent = "";
    el.invitesList.innerHTML = "";
    el.accessRequestsList.innerHTML = "";
    el.documentsContainer.innerHTML = "";
    if (el.specialtyContainer) {
      el.specialtyContainer.innerHTML =
        "<p class=\"muted\">Accedi per visualizzare i documenti per specialita.</p>";
    }
    if (el.pendingPatientsList) {
      el.pendingPatientsList.innerHTML = "";
      el.pendingPatientsList.classList.add("hidden");
    }
    if (el.operationsOutput) {
      el.operationsOutput.innerHTML = "Nessun file elencato. Usa i pulsanti sopra per visualizzare o aggiornare l'archivio.";
    }
    switchTab("documentsTab");
    toggleDashboard(false);
    setLoginStatus("");
    setStatus("Disconnessione effettuata.", "info");
  }
}
function registerHandler() {
  openSignupModal({
    patientId: el.patientIdInput.value.trim(),
    email: el.emailInput.value.trim(),
  });
  setStatus("Compila il modulo di registrazione per completare l'attivazione.", "info");
}

async function claimInviteHandler() {
  const token = el.inviteTokenInput.value.trim();
  if (!token) {
    setLoginStatus("Inserisci un token valido prima di reclamare l'invito.");
    return;
  }
  try {
    const data = ensureOk(
      await fetchJson(`${backendUrl}/access/claim`, {
        method: "POST",
      body: { token },
    })
  );
  const patientId = data.invite?.patient_id;
  if (!patientId) {
    throw new Error("L'invito non contiene un ID paziente.");
  }
  el.patientIdInput.value = patientId;
  setLoginStatus(`Invito valido per il paziente ${patientId}. Completa la registrazione con email e password.`);
  setStatus("Invito reclamato con successo.", "success");
} catch (error) {
  setLoginStatus(`Errore: ${error.message}`);
  setStatus(`Invito non valido: ${error.message}`, "error");
}
}

async function askAIHandler() {
  const question = el.questionInput.value.trim();
  if (!question) {
    setStatus("Scrivi una domanda prima di inviare.", "error");
    return;
  }
  if (!state.patientId || !state.token) {
    setStatus("Accedi con il tuo account prima di interrogare l'assistente.", "error");
    return;
  }
  const mode = el.askVisionCheckbox?.checked ? "direct" : "cached";
  const statusMsg =
    mode === "direct" ? "Analisi Vision e preparazione della risposta in corso..." : "Invio domanda all'assistente...";
  try {
    setStatus(statusMsg, "info");
    const data = ensureOk(
      await fetchJson(`${backendUrl}/patients/${encodeURIComponent(state.patientId)}/ask`, {
        method: "POST",
        body: { question, mode },
      })
    );
    const note =
      data.mode === "direct"
        ? '<p class="muted small">Analisi diretta Vision eseguita prima della risposta.</p>'
        : "";
    el.chatOutput.innerHTML = `
      <p><strong>Domanda:</strong> ${escapeHtml(data.question)}</p>
      <p><strong>Risposta:</strong></p>
      <blockquote>${escapeHtml(data.answer)}</blockquote>
      ${note}
    `;
    setStatus("Risposta ricevuta.", "success");
  } catch (error) {
    setStatus(`Errore durante la richiesta all'AI: ${error.message}`, "error");
  }
}

async function createInviteHandler() {
  if (!state.patientId || !state.token) {
    setStatus("Accedi ad un profilo prima di creare un invito.", "error");
    return;
  }
  const hours = parseInt(el.inviteHoursInput.value, 10) || 48;
  try {
    ensureOk(
      await fetchJson(`${backendUrl}/patients/${encodeURIComponent(state.patientId)}/invite`, {
        method: "POST",
        body: {
          expires_hours: Math.min(Math.max(hours, 1), 24 * 14),
          note: el.inviteNoteInput.value || undefined,
          created_by: el.inviteCreatorInput.value || undefined,
        },
      })
    );
    setStatus("Invito creato con successo.", "success");
    el.inviteNoteInput.value = "";
    await loadInvites();
  } catch (error) {
    setStatus(`Errore nella creazione dell'invito: ${error.message}`, "error");
  }
}

async function downloadHandler(sourceOverride) {
  if (!state.token) {
    setStatus("Accedi al backend prima di avviare il download automatico.", "error");
    return;
  }

  const source =
    typeof sourceOverride === "string" && sourceOverride.trim().length > 0
      ? sourceOverride.trim()
      : el.downloadSourceInput.value.trim();

  if (!source) {
    setStatus("Inserisci una fonte (URL o percorso) per il download.", "error");
    return;
  }

  buttons.continueFseDownload?.classList.add("hidden");
  if (el.fseDownloadHint) {
    el.fseDownloadHint.classList.add("hidden");
    el.fseDownloadHint.textContent = "";
  }
  state.pendingDownload = null;

  try {
    setStatus("Download avviato...");
    const params = new URLSearchParams({ source });
    if (state.patientId) {
      params.append("patient_id", state.patientId);
    }
    const data = await fetchJson(`${backendUrl}/download?${params.toString()}`);

    if (data.status === "waiting_for_login") {
      state.pendingDownload = {
        source,
        ticket: data.ticket || null,
      };
      buttons.continueFseDownload?.classList.remove("hidden");
      if (el.fseDownloadHint) {
        el.fseDownloadHint.textContent =
          data.message ||
          'Completa il login SPID nella finestra aperta, poi premi "Continua download".';
        el.fseDownloadHint.classList.remove("hidden");
      }
      el.operationsOutput.innerHTML =
        '<p class="muted">Download in attesa: completa l\'autenticazione SPID nella finestra aperta e premi "Continua download".</p>';
      setStatus("Completa il login nella finestra automatica, poi premi \"Continua download\".", "info");
      return;
    }

    buttons.continueFseDownload?.classList.add("hidden");
    if (el.fseDownloadHint) {
      el.fseDownloadHint.classList.add("hidden");
      el.fseDownloadHint.textContent = "";
    }
    state.pendingDownload = null;

    ensureOk(data);
    const summary = {
      result: data.result || {},
      copied_files: data.copied_files || [],
      skipped_files: data.skipped_files || [],
      elapsed_sec: data.elapsed_sec,
    };
    el.operationsOutput.innerHTML = `<pre>${escapeHtml(JSON.stringify(summary, null, 2))}</pre>`;
    if (summary.copied_files.length) {
      setStatus("Download completato. Ricorda di analizzare i nuovi documenti dal tuo profilo.", "success");
    } else {
      setStatus("Download completato.", "success");
    }
  } catch (error) {
    state.pendingDownload = null;
    buttons.continueFseDownload?.classList.add("hidden");
    if (el.fseDownloadHint) {
      el.fseDownloadHint.classList.add("hidden");
      el.fseDownloadHint.textContent = "";
    }
    setStatus(`Errore durante il download: ${error.message}`, "error");
  }
}

function startFseDownloadHandler() {
  downloadHandler(FSE_URL);
}

async function continueFseDownloadHandler() {
  if (!state.pendingDownload) {
    setStatus("Nessun download in attesa di conferma.", "error");
    return;
  }
  try {
    setStatus("Completamento download in corso...");
    const data = await fetchJson(`${backendUrl}/download/continue`, { method: "POST" });
    ensureOk(data);
    buttons.continueFseDownload?.classList.add("hidden");
    state.pendingDownload = null;
    if (el.fseDownloadHint) {
      el.fseDownloadHint.classList.add("hidden");
      el.fseDownloadHint.textContent = "";
    }
    const summary = {
      result: data.result || {},
      copied_files: data.copied_files || [],
      skipped_files: data.skipped_files || [],
      elapsed_sec: data.elapsed_sec,
    };
    el.operationsOutput.innerHTML = `<pre>${escapeHtml(JSON.stringify(summary, null, 2))}</pre>`;
    if (summary.copied_files.length) {
      setStatus("Download completato. Ricorda di analizzare i nuovi documenti dal tuo profilo.", "success");
    } else {
      setStatus("Download completato.", "success");
    }
  } catch (error) {
    setStatus(`Errore nella fase di completamento: ${error.message}`, "error");
  } finally {
    buttons.continueFseDownload?.classList.add("hidden");
    state.pendingDownload = null;
    if (el.fseDownloadHint) {
      el.fseDownloadHint.classList.add("hidden");
      el.fseDownloadHint.textContent = "";
    }
  }
}

async function uploadLocalPdfsHandler() {
  if (!state.token) {
    setStatus("Accedi al backend prima di caricare file locali.", "error");
    return;
  }

  const input = el.localPdfInput;
  const files = input?.files;
  if (!files || !files.length) {
    setStatus("Seleziona almeno un file PDF dal dispositivo.", "error");
    return;
  }

  const formData = new FormData();
  Array.from(files).forEach((file) => formData.append("files", file));

  try {
    setStatus("Caricamento PDF in corso...");
    const data = ensureOk(
      await fetchJson(`${backendUrl}/download/upload`, {
        method: "POST",
        body: formData,
      })
    );
    el.operationsOutput.innerHTML = `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
    setStatus(`Caricati ${data.count || 0} PDF.`, "success");
    if (input) {
      input.value = "";
    }
    await listDownloadsHandler();
  } catch (error) {
    setStatus(`Errore nel caricamento: ${error.message}`, "error");
  }
}

async function analyzeHandler() {
  if (!state.patientId || !state.token) {
    setStatus("Accedi al tuo profilo prima di avviare l'analisi.", "error");
    return;
  }

  const overwrite = el.overwriteAnalysisCheckbox?.checked ?? true;
  const visionOnly = el.visionAnalysisCheckbox?.checked ?? false;
  const ocrEnabled = !visionOnly && (el.ocrCheckbox?.checked ?? true);

  const payload = {
    overwrite,
    ocr: ocrEnabled,
    ocr_lang: "ita+eng",
    ocr_psm: "6",
    ocr_zoom: 3.0,
    dump_text: false,
    vision_only: visionOnly,
  };
  try {
    const statusMsg = visionOnly
      ? "Analisi Vision dei documenti in corso..."
      : "Analisi dei documenti personali in corso...";
    setStatus(statusMsg, "info");
    const data = ensureOk(
      await fetchJson(`${backendUrl}/patients/${encodeURIComponent(state.patientId)}/analyze`, {
        method: "POST",
        body: payload,
      })
    );
    el.operationsOutput.innerHTML = `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
    setStatus("Analisi completata.", "success");
    await loadPatientProfile(state.patientId, { silent: true });
    await loadDocuments();
  } catch (error) {
    setStatus(`Errore durante l'analisi: ${error.message}`, "error");
  }
}

async function listDownloadsHandler() {
  try {
    const data = ensureOk(await fetchJson(`${backendUrl}/downloaded-pdfs-list`));
    const files = data.files || [];
    el.operationsOutput.innerHTML = files.length
      ? `<ul>${files.map((file) => `<li>${escapeHtml(file)}</li>`).join("")}</ul>`
      : "<p class=\"muted\">Nessun file scaricato al momento.</p>";
  } catch (error) {
    setStatus(`Errore nel recupero dei file scaricati: ${error.message}`, "error");
  }
}

async function signupSubmitHandler() {
  const statusEl = el.signupStatus;
  const payload = {
    patient_id: el.signupPatientId?.value.trim() || "",
    nome: el.signupName?.value.trim() || undefined,
    codice_fiscale: el.signupCf?.value.trim() || undefined,
    data_nascita: el.signupDob?.value || undefined,
    email: el.signupEmail?.value.trim() || "",
    telefono: el.signupPhone?.value.trim() || undefined,
    note: el.signupNote?.value.trim() || undefined,
    security_question: el.signupSecurityQuestion?.value.trim() || "",
    security_answer: el.signupSecurityAnswer?.value.trim() || "",
  };

  if (!payload.patient_id || !payload.email || !payload.security_question || !payload.security_answer) {
    if (statusEl) {
      statusEl.textContent = "Compila ID paziente, email e domanda di sicurezza.";
      statusEl.classList.remove("status-success");
      statusEl.classList.add("status-error");
    }
    return;
  }

  if (statusEl) {
    statusEl.textContent = "Invio richiesta...";
    statusEl.classList.remove("status-success", "status-error");
  }

  try {
    const data = await fetchJson(`${backendUrl}/public/signup`, {
      method: "POST",
      body: payload,
    });
    const password = data?.password;
    if (statusEl) {
      if (password) {
        const escaped = escapeHtml(password);
        statusEl.innerHTML = `Registrazione completata.<br><strong>Password temporanea:</strong> <code>${escaped}</code><br><small>Copia la password e poi chiudi questa finestra.</small>`;
      } else {
        statusEl.textContent = "Registrazione completata.";
      }
      statusEl.classList.remove("status-error");
      statusEl.classList.add("status-success");
    }
    if (el.patientIdInput) {
      el.patientIdInput.value = payload.patient_id;
    }
    if (el.passwordInput && password) {
      el.passwordInput.value = password;
    }
    setStatus("Registrazione completata.", "success");
  } catch (error) {
    if (statusEl) {
      statusEl.textContent = `Errore durante la registrazione: ${error.message}`;
      statusEl.classList.remove("status-success");
      statusEl.classList.add("status-error");
    }
    setStatus(`Registrazione non riuscita: ${error.message}`, "error");
  }
}

async function passwordResetInitHandler() {
  const identifier = el.resetIdentifierInput?.value.trim();
  if (!identifier) {
    el.resetStatus.textContent = "Inserisci un ID paziente o un'email valida.";
    return;
  }
  el.resetStatus.textContent = "Invio richiesta...";
  try {
    const data = ensureOk(
      await fetchJson(`${backendUrl}/auth/password-reset/init`, {
        method: "POST",
        body: { identifier },
      })
    );
    const question = data.question;
    const token = data.token;
    state.passwordResetToken = token || null;
    if (question && token) {
      el.resetQuestion.textContent = `Domanda di sicurezza: ${question}`;
      el.resetStatus.textContent =
        data.message || "Rispondi alla domanda di sicurezza e imposta una nuova password.";
      switchResetStep("verify");
      el.resetAnswerInput.focus();
    } else {
      el.resetStatus.textContent =
        data.message ||
        "Se l'account esiste, riceverai un'email con ulteriori istruzioni. Controlla anche la cartella spam.";
    }
  } catch (error) {
    el.resetStatus.textContent = `Impossibile avviare il reset: ${error.message}`;
  }
}

async function passwordResetCompleteHandler() {
  if (!state.passwordResetToken) {
    el.resetStatus.textContent = "Token di reset mancante o scaduto. Ripeti la procedura.";
    switchResetStep("init");
    return;
  }
  const answer = el.resetAnswerInput?.value.trim();
  const newPassword = el.resetNewPasswordInput?.value;
  if (!answer || !newPassword) {
    el.resetStatus.textContent = "Compila la risposta alla domanda e la nuova password.";
    return;
  }
  if (newPassword.length < 8) {
    el.resetStatus.textContent = "La nuova password deve contenere almeno 8 caratteri.";
    return;
  }
  el.resetStatus.textContent = "Aggiornamento password in corso...";
  try {
    ensureOk(
      await fetchJson(`${backendUrl}/auth/password-reset/complete`, {
        method: "POST",
        body: {
          token: state.passwordResetToken,
          answer,
          new_password: newPassword,
        },
      })
    );
    el.resetStatus.textContent = "Password aggiornata con successo. Ora puoi accedere con la nuova password.";
    setStatus("Password aggiornata correttamente. Accedi con le nuove credenziali.", "success");
    closePasswordResetModal();
  } catch (error) {
    el.resetStatus.textContent = `Impossibile completare il reset: ${error.message}`;
  }
}

async function changePasswordHandler() {
  if (!state.patientId || !state.token) {
    el.changePasswordStatus.textContent = "Effettua l'accesso per modificare la password.";
    return;
  }
  const currentPassword = el.currentPasswordInput?.value || "";
  const newPassword = el.newPasswordInput?.value || "";
  const confirmPassword = el.confirmPasswordInput?.value || "";
  if (!currentPassword || !newPassword || !confirmPassword) {
    el.changePasswordStatus.textContent = "Compila tutti i campi della password.";
    return;
  }
  if (newPassword.length < 8) {
    el.changePasswordStatus.textContent = "La nuova password deve contenere almeno 8 caratteri.";
    return;
  }
  if (newPassword !== confirmPassword) {
    el.changePasswordStatus.textContent = "La conferma non coincide con la nuova password.";
    return;
  }
  el.changePasswordStatus.textContent = "Aggiornamento in corso...";
  try {
    ensureOk(
      await fetchJson(`${backendUrl}/auth/password/change`, {
        method: "POST",
        body: {
          current_password: currentPassword,
          new_password: newPassword,
        },
      })
    );
    el.changePasswordStatus.textContent = "Password aggiornata con successo.";
    el.currentPasswordInput.value = "";
    el.newPasswordInput.value = "";
    el.confirmPasswordInput.value = "";
    setStatus("Password aggiornata.", "success");
  } catch (error) {
    el.changePasswordStatus.textContent = `Impossibile aggiornare la password: ${error.message}`;
  }
}

async function pendingPatientsHandler() {
  try {
    const data = ensureOk(await fetchJson(`${backendUrl}/patients/pending`));
    const entries = Object.values(data.patients || {});
    if (!entries.length) {
      el.pendingPatientsList.classList.add("hidden");
      setStatus("Nessun paziente in attesa di autorizzazione.", "info");
      return;
    }
    const markup = entries
      .map(
        (meta) => `
          <div class=\"list-item\">
            <header>
              <span>${escapeHtml(meta.patient_id || "ID sconosciuto")}</span>
              <span class=\"badge pending\">pending</span>
            </header>
            <p>Nome: ${escapeHtml(meta.nome || "-")}</p>
            <p>Codice fiscale: ${escapeHtml(meta.codice_fiscale || "-")}</p>
            <p>Data di nascita: ${escapeHtml(meta.data_nascita || "-")}</p>
            <p>Ultimo rilevamento: ${formatIso(meta.last_seen)}</p>
          </div>
        `
      )
      .join("");
    el.pendingPatientsList.innerHTML = markup;
    el.pendingPatientsList.classList.remove("hidden");
    setStatus("Elenco pazienti in attesa aggiornato.", "info");
  } catch (error) {
    setStatus(`Errore nel recupero dei pazienti in attesa: ${error.message}`, "error");
  }
}

function registerEventListeners() {
  navButtons.forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab || "documentsTab"));
  });

  buttons.startFseDownload?.addEventListener("click", startFseDownloadHandler);
  buttons.continueFseDownload?.addEventListener("click", continueFseDownloadHandler);
  buttons.analyzeProfile?.addEventListener("click", () => analyzeHandler());

  buttons.login?.addEventListener("click", loginHandler);
  buttons.register?.addEventListener("click", registerHandler);
  buttons.openSignup?.addEventListener("click", () => openSignupModal({}));
  buttons.claimInvite?.addEventListener("click", claimInviteHandler);
  buttons.refreshProfile?.addEventListener("click", () => {
    if (state.patientId) {
      loadPatientProfile(state.patientId);
    }
  });
  buttons.logout?.addEventListener("click", logoutHandler);
  buttons.ask?.addEventListener("click", askAIHandler);
  buttons.refreshDocs?.addEventListener("click", loadDocuments);
  buttons.createInvite?.addEventListener("click", createInviteHandler);
  buttons.download?.addEventListener("click", () => downloadHandler());
  buttons.list?.addEventListener("click", listDownloadsHandler);
  buttons.analyze?.addEventListener("click", analyzeHandler);
  buttons.pendingPatients?.addEventListener("click", pendingPatientsHandler);
  buttons.refreshDownloadList?.addEventListener("click", listDownloadsHandler);
  buttons.uploadLocalPdf?.addEventListener("click", uploadLocalPdfsHandler);
  buttons.signupSubmit?.addEventListener("click", signupSubmitHandler);
  buttons.toggleAggregates?.addEventListener("click", () => {
    state.aggregatesExpanded = !state.aggregatesExpanded;
    if (!state.aggregatesExpanded && el.aggregatesContainer) {
      el.aggregatesContainer.scrollTo({ top: 0, behavior: "smooth" });
    }
    updateAggregatesClamp();
  });
  buttons.closeSignup?.addEventListener("click", closeSignupModal);
  buttons.closeSignupBackdrop?.addEventListener("click", closeSignupModal);
  buttons.forgotPassword?.addEventListener("click", openPasswordResetModal);
  buttons.closeReset?.addEventListener("click", closePasswordResetModal);
  buttons.closeResetBackdrop?.addEventListener("click", closePasswordResetModal);
  buttons.resetInit?.addEventListener("click", passwordResetInitHandler);
  buttons.resetComplete?.addEventListener("click", passwordResetCompleteHandler);
  buttons.changePassword?.addEventListener("click", changePasswordHandler);
  buttons.logoutSettings?.addEventListener("click", logoutHandler);

  el.documentSearchInput?.addEventListener("input", handleDocumentSearch);

  el.patientIdInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") loginHandler();
  });
  el.emailInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") loginHandler();
  });
  el.passwordInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") loginHandler();
  });
  el.questionInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.ctrlKey) askAIHandler();
  });

  window.addEventListener("resize", () => {
    if (!state.aggregatesExpanded) {
      requestAnimationFrame(updateAggregatesClamp);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeSignupModal();
      closePasswordResetModal();
    }
  });
}

function init() {
  registerEventListeners();
  switchTab(state.activeTab || "documentsTab");
}

window.addEventListener("DOMContentLoaded", init);
