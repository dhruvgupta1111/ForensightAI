const state = { user: null, authMode: "login", dashboard: null, history: [] };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.setAttribute("role", isError ? "alert" : "status");
  toast.setAttribute("aria-live", isError ? "assertive" : "polite");
  toast.classList.add("show");
  window.clearTimeout(showToast.timeout);
  showToast.timeout = window.setTimeout(() => toast.classList.remove("show"), 3800);
}

async function csrfToken() {
  const response = await fetch("/api/auth/csrf", { credentials: "same-origin" });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Could not start a secure session.");
  return data.csrf_token;
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (["POST", "PUT", "PATCH", "DELETE"].includes((options.method || "GET").toUpperCase())) {
    headers.set("X-CSRF-Token", await csrfToken());
  }
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  const data = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new ApiError(data?.detail || "The request could not be completed.", response.status);
  return data;
}

function setAuthMode(mode) {
  state.authMode = mode;
  const signupMode = mode === "signup";
  $("#auth-title").textContent = signupMode ? "Create your account" : "Welcome back";
  $("#auth-subtitle").textContent = signupMode ? "Set up your evidence workspace." : "Sign in to your evidence workspace.";
  $("#name-field").classList.toggle("hidden", !signupMode);
  $("#name-field input").required = signupMode;
  $("#password-hint").classList.toggle("hidden", !signupMode);
  $("#auth-form [name=password]").autocomplete = signupMode ? "new-password" : "current-password";
  $("#auth-submit").innerHTML = signupMode ? 'Create account <span aria-hidden="true">→</span>' : 'Sign in <span aria-hidden="true">→</span>';
  $("#auth-switch-copy").textContent = signupMode ? "Already have an account?" : "New to ForenSight?";
  $("#auth-switch").textContent = signupMode ? "Sign in" : "Create an account";
  $("#auth-form").reset();
}

function greetingName(name) {
  return name.trim().split(/\s+/)[0] || "Analyst";
}

function updateUserUI() {
  const shortName = greetingName(state.user.full_name);
  $("#user-name").textContent = state.user.full_name;
  $("#user-email").textContent = state.user.email;
  $("#user-avatar").textContent = state.user.full_name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
  $("#greeting-name").textContent = shortName;
}

function formatDate(value, includeTime = false) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, includeTime
    ? { dateStyle: "medium", timeStyle: "short" }
    : { dateStyle: "medium" }).format(date);
}

function badge(category) {
  const label = category[0].toUpperCase() + category.slice(1);
  return `<span class="risk-badge ${category}"><span class="status-dot ${category}-dot"></span>${label}</span>`;
}

function emptyState(title, message, action = false) {
  const wrapper = document.createElement("div");
  wrapper.className = "empty-state";
  const icon = document.createElement("span");
  icon.className = "empty-state-icon";
  icon.textContent = "⌁";
  const heading = document.createElement("strong");
  heading.textContent = title;
  const description = document.createElement("p");
  description.textContent = message;
  wrapper.append(icon, heading, description);
  if (action) {
    const button = document.createElement("button");
    button.className = "text-button";
    button.type = "button";
    button.dataset.view = "assessment";
    button.style.marginTop = "12px";
    button.textContent = "Create your first assessment →";
    wrapper.append(button);
  }
  return wrapper;
}

function assessmentTable(records, compact = false) {
  if (!records.length) {
    const empty = document.createElement("div");
    empty.className = compact ? "" : "table-empty";
    empty.textContent = compact ? "No assessments yet." : "No assessments match this filter.";
    return empty;
  }
  const wrapper = document.createElement("div");
  wrapper.className = "table-wrap";
  const table = document.createElement("table");
  table.className = "data-table";
  const heading = document.createElement("thead");
  heading.innerHTML = `<tr><th>Evidence reference</th><th>Evidence type</th><th>Risk indicator</th><th>Date recorded</th></tr>`;
  const body = document.createElement("tbody");
  records.forEach((record) => {
    const row = document.createElement("tr");
    row.dataset.riskCategory = record.risk_category;
    row.tabIndex = 0;
    row.setAttribute("aria-label", `View assessment for ${record.evidence_ref}`);
    const reference = document.createElement("td");
    reference.className = "evidence-ref";
    reference.textContent = record.evidence_ref;
    const type = document.createElement("td");
    type.textContent = record.evidence_type;
    const risk = document.createElement("td");
    risk.innerHTML = badge(record.risk_category);
    const date = document.createElement("td");
    date.textContent = formatDate(record.created_at, true);
    row.append(reference, type, risk, date);
    const openRecord = () => showAssessmentDetails(record);
    row.addEventListener("click", openRecord);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openRecord();
      }
    });
    body.append(row);
  });
  table.append(heading, body);
  wrapper.append(table);
  return wrapper;
}

function updateDashboard(data) {
  state.dashboard = data;
  $("#metric-total").textContent = data.total;
  $("#metric-low").textContent = data.low;
  $("#metric-medium").textContent = data.medium;
  $("#metric-high").textContent = data.high;
  $("#chart-low").textContent = data.low;
  $("#chart-medium").textContent = data.medium;
  $("#chart-high").textContent = data.high;
  const max = Math.max(data.low, data.medium, data.high, 1);
  $("#risk-chart").classList.toggle("is-empty", data.total === 0);
  $("#risk-chart").setAttribute(
    "aria-label",
    `Risk distribution. Low: ${data.low}, medium: ${data.medium}, high: ${data.high}. Select a category to view matching assessments.`,
  );
  $("#bar-low").style.width = `${data.low ? Math.max(data.low / max * 100, 4) : 0}%`;
  $("#bar-medium").style.width = `${data.medium ? Math.max(data.medium / max * 100, 4) : 0}%`;
  $("#bar-high").style.width = `${data.high ? Math.max(data.high / max * 100, 4) : 0}%`;
  $("#chart-empty").classList.toggle("hidden", data.total > 0);

  renderAnalyticsRows(
    $("#evidence-type-chart"),
    data.evidence_types,
    "evidence_type",
    data.total,
    "No evidence type data",
    "Saved assessments will appear here.",
  );
  renderAnalyticsRows(
    $("#indicator-chart"),
    [...data.indicators].sort((a, b) => b.count - a.count),
    "label",
    data.total,
    "No handling indicators yet",
    "Indicators are counted from saved handling conditions.",
  );
  renderMonthlyTrend(data.monthly_trend, $("#trend-chart"));
  renderHighRiskAssessments(data.high_risk_assessments, $("#high-risk-content"));
  updateModelEvaluation(data.model_evaluation);
  renderExperimentComparison(data.model_comparison || []);

  const recent = $("#recent-content");
  recent.replaceChildren(data.recent.length
    ? assessmentTable(data.recent, true)
    : emptyState("No assessments yet", "Create a record to see your recent casework here.", true));
}

function formatModelMetric(value) {
  return value === null || value === undefined
    ? "Not available"
    : new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 }).format(value);
}

function renderModelEmptyState(container, title, message) {
  const state = document.createElement("div");
  state.className = "model-empty-state";
  const icon = document.createElement("span");
  icon.className = "model-empty-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = "i";
  const heading = document.createElement("strong");
  heading.textContent = title;
  const description = document.createElement("p");
  description.textContent = message;
  state.append(icon, heading, description);
  container.className = "model-table-empty";
  container.append(state);
}

function renderConfusionMatrix(matrix, container = $("#model-confusion-matrix")) {
  container.replaceChildren();
  if (!matrix) {
    renderModelEmptyState(
      container,
      "Confusion matrix unavailable",
      "A confusion matrix appears after the bundled synthetic dataset is evaluated."
    );
    return;
  }

  const wrapper = document.createElement("div");
  wrapper.className = "table-wrap";
  const table = document.createElement("table");
  table.className = "data-table model-data-table";
  const caption = document.createElement("caption");
  caption.textContent = "Rows: actual class · Columns: predicted class";
  const head = document.createElement("thead");
  const headerRow = document.createElement("tr");
  const corner = document.createElement("th");
  corner.textContent = "Actual \\ Predicted";
  headerRow.append(corner);
  matrix.predicted_classes.forEach((label) => {
    const header = document.createElement("th");
    header.scope = "col";
    header.textContent = label.replaceAll("_", " ");
    headerRow.append(header);
  });
  head.append(headerRow);
  const body = document.createElement("tbody");
  matrix.actual_classes.forEach((label, rowIndex) => {
    const row = document.createElement("tr");
    const actual = document.createElement("th");
    actual.scope = "row";
    actual.textContent = label.replaceAll("_", " ");
    row.append(actual);
    matrix.counts[rowIndex].forEach((count) => {
      const cell = document.createElement("td");
      cell.textContent = count;
      row.append(cell);
    });
    body.append(row);
  });
  table.append(caption, head, body);
  wrapper.append(table);
  container.className = "model-table-wrap";
  container.append(wrapper);
}

function renderClassMetrics(metrics, container = $("#model-class-metrics")) {
  container.replaceChildren();
  if (!metrics.length) {
    renderModelEmptyState(
      container,
      "Class-wise results unavailable",
      "Class-level metrics will appear after evaluation on the synthetic held-out set."
    );
    return;
  }

  const wrapper = document.createElement("div");
  wrapper.className = "table-wrap";
  const table = document.createElement("table");
  table.className = "data-table model-data-table";
  const head = document.createElement("thead");
  head.innerHTML = "<tr><th>Actual class</th><th>Precision</th><th>Recall</th><th>F1</th><th>Support</th></tr>";
  const body = document.createElement("tbody");
  metrics.forEach((metric) => {
    const row = document.createElement("tr");
    [
      metric.label.replaceAll("_", " "),
      formatModelMetric(metric.precision),
      formatModelMetric(metric.recall),
      formatModelMetric(metric.f1),
      metric.support,
    ].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    });
    body.append(row);
  });
  table.append(head, body);
  wrapper.append(table);
  container.className = "model-table-wrap";
  container.append(wrapper);
}

function renderExperimentComparison(results) {
  const container = $("#experiment-comparison-table");
  container.replaceChildren();
  const selected = results.find((result) => result.selected);
  const selectedMatrix = $("#selected-model-confusion-matrix");
  const selectedClasses = $("#selected-model-class-metrics");
  $("#selected-model-label").textContent = selected
    ? `Selected model: ${selected.algorithm}`
    : "Selected model: unavailable";
  if (!results.length) {
    renderModelEmptyState(
      container,
      "Experiment comparison unavailable",
      "Train the experimental models to show their synthetic holdout comparison.",
    );
    renderConfusionMatrix(null, selectedMatrix);
    renderClassMetrics([], selectedClasses);
    return;
  }

  const wrapper = document.createElement("div");
  wrapper.className = "table-wrap";
  const table = document.createElement("table");
  table.className = "data-table model-data-table";
  const head = document.createElement("thead");
  head.innerHTML = "<tr><th>Algorithm</th><th>Configuration</th><th>Accuracy</th><th>Macro precision</th><th>Macro recall</th><th>Macro F1</th><th>Selection</th></tr>";
  const body = document.createElement("tbody");
  results.forEach((result) => {
    const row = document.createElement("tr");
    const values = [
      result.algorithm,
      result.hyperparameters,
      formatModelMetric(result.accuracy),
      formatModelMetric(result.macro_precision),
      formatModelMetric(result.macro_recall),
      formatModelMetric(result.macro_f1),
      result.selected ? "Selected" : "Compared",
    ];
    values.forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    });
    body.append(row);
  });
  table.append(head, body);
  wrapper.append(table);
  container.className = "model-table-wrap";
  container.append(wrapper);
  renderConfusionMatrix(selected ? selected.confusion_matrix : null, selectedMatrix);
  renderClassMetrics(selected ? selected.class_metrics : [], selectedClasses);
}

function updateModelEvaluation(evaluation) {
  if (!evaluation) return;
  $("#model-status").textContent = evaluation.model_status;
  $("#model-status").dataset.state = evaluation.status;
  $("#model-status-detail").textContent = evaluation.model_status;
  $("#model-scope").textContent = evaluation.evaluation_scope;
  $("#model-source").textContent = evaluation.dataset_source || "Not configured";
  $("#model-training-count").textContent = evaluation.training_records ?? "—";
  $("#model-testing-count").textContent = evaluation.testing_records ?? "—";
  [
    ["#model-accuracy", evaluation.accuracy],
    ["#model-precision", evaluation.precision_macro],
    ["#model-recall", evaluation.recall_macro],
    ["#model-f1", evaluation.macro_f1],
  ].forEach(([selector, value]) => {
    const metric = $(selector);
    const unavailable = value === null || value === undefined;
    metric.textContent = formatModelMetric(value);
    metric.classList.toggle("is-unavailable", unavailable);
  });
  renderConfusionMatrix(evaluation.confusion_matrix);
  renderClassMetrics(evaluation.class_metrics || []);
}

function renderAnalyticsRows(container, rows, labelKey, total, emptyTitle, emptyMessage) {
  container.replaceChildren();
  if (!total) {
    container.append(emptyState(emptyTitle, emptyMessage));
    return;
  }

  const max = Math.max(...rows.map((row) => row.count), 1);
  rows.forEach((row) => {
    const item = document.createElement("div");
    item.className = "analytics-row";
    const label = document.createElement("span");
    label.className = "analytics-label";
    label.textContent = row[labelKey];
    const track = document.createElement("span");
    track.className = "bar-track";
    const fill = document.createElement("span");
    fill.className = "bar-fill analytics-fill";
    fill.style.width = `${row.count ? Math.max(row.count / max * 100, 4) : 0}%`;
    track.append(fill);
    const count = document.createElement("strong");
    count.textContent = row.count;
    item.append(label, track, count);
    container.append(item);
  });
}

function renderMonthlyTrend(months, container) {
  container.replaceChildren();
  if (!months.length) {
    container.append(emptyState("No assessment trend yet", "Monthly counts will appear after assessments are recorded."));
    return;
  }

  const max = Math.max(...months.map((month) => month.count), 1);
  months.forEach((month) => {
    const column = document.createElement("div");
    column.className = "trend-column";
    column.title = `${month.count} assessment${month.count === 1 ? "" : "s"}`;
    const count = document.createElement("strong");
    count.textContent = month.count;
    const track = document.createElement("span");
    track.className = "trend-track";
    const fill = document.createElement("span");
    fill.className = "trend-fill";
    fill.style.height = `${Math.max(month.count / max * 100, 4)}%`;
    track.append(fill);
    const label = document.createElement("span");
    label.className = "trend-label";
    const date = new Date(`${month.month}-01T00:00:00Z`);
    label.textContent = Number.isNaN(date.getTime())
      ? month.month
      : new Intl.DateTimeFormat(undefined, { month: "short", year: "2-digit", timeZone: "UTC" }).format(date);
    column.append(count, track, label);
    container.append(column);
  });
}

function renderHighRiskAssessments(records, container) {
  container.replaceChildren();
  if (!records.length) {
    container.append(emptyState("No high-risk assessments", "High-risk records will be listed here when present."));
    return;
  }

  const wrapper = document.createElement("div");
  wrapper.className = "table-wrap";
  const table = document.createElement("table");
  table.className = "data-table high-risk-table";
  const head = document.createElement("thead");
  head.innerHTML = "<tr><th>Evidence reference</th><th>Type</th><th>Score</th><th>Date</th><th></th></tr>";
  const body = document.createElement("tbody");
  records.forEach((record) => {
    const row = document.createElement("tr");
    row.dataset.riskCategory = "high";
    const reference = document.createElement("td");
    reference.className = "evidence-ref";
    reference.textContent = record.evidence_ref;
    const type = document.createElement("td");
    type.textContent = record.evidence_type;
    const score = document.createElement("td");
    score.className = "high-risk-score";
    score.textContent = record.risk_score;
    const date = document.createElement("td");
    date.textContent = formatDate(record.created_at);
    const action = document.createElement("td");
    const link = document.createElement("button");
    link.className = "text-button";
    link.type = "button";
    link.dataset.assessmentId = record.id;
    link.textContent = "Open details";
    action.append(link);
    row.append(reference, type, score, date, action);
    body.append(row);
  });
  table.append(head, body);
  wrapper.append(table);
  container.append(wrapper);
}

async function loadDashboard() {
  updateDashboard(await api("/api/dashboard"));
}

async function loadHistory() {
  const category = $("#risk-filter").value;
  const query = category ? `?risk=${encodeURIComponent(category)}` : "";
  state.history = await api(`/api/assessments${query}`);
  $("#history-content").replaceChildren(assessmentTable(state.history));
}

function navigate(view) {
  const titles = {
    dashboard: "Overview",
    assessment: "New assessment",
    model: "Model insights",
    history: "Assessment history",
  };
  $$(".page-view").forEach((section) => section.classList.toggle("hidden", section.id !== `view-${view}`));
  $$(".nav-link").forEach((button) => {
    const active = button.dataset.view === view;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  $("#page-crumb").textContent = titles[view] || titles.dashboard;
  if (view === "dashboard") loadDashboard().catch((error) => showToast(error.message, true));
  if (view === "model") loadDashboard().catch((error) => showToast(error.message, true));
  if (view === "history") loadHistory().catch((error) => showToast(error.message, true));
}

function showWorkspace(user) {
  state.user = user;
  $("#landing-page").classList.add("hidden");
  $("#auth-screen").classList.add("hidden");
  $("#workspace").classList.remove("hidden");
  updateUserUI();
  $("#today-label").textContent = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date());
  navigate("dashboard");
}

function showAuth(mode = "login") {
  state.user = null;
  $("#landing-page").classList.add("hidden");
  $("#workspace").classList.add("hidden");
  $("#auth-screen").classList.remove("hidden");
  setAuthMode(mode);
  $("#auth-form [name=email]").focus();
}

function showLanding() {
  state.user = null;
  $("#workspace").classList.add("hidden");
  $("#auth-screen").classList.add("hidden");
  $("#landing-page").classList.remove("hidden");
}

function renderList(container, title, values) {
  const heading = document.createElement("h3");
  heading.textContent = title;
  const list = document.createElement("ul");
  values.forEach((value) => {
    const item = document.createElement("li");
    item.textContent = value;
    list.append(item);
  });
  container.append(heading, list);
}

function renderRiskExplanation(container, factors, score) {
  const section = document.createElement("section");
  section.className = "risk-explanation";

  const heading = document.createElement("h3");
  heading.textContent = "Factors increasing risk";
  const list = document.createElement("ul");
  list.className = "risk-factor-list";
  const contributions = [];

  factors.forEach((factor) => {
    const item = document.createElement("li");
    const match = factor.match(/^(.*?) \(\+(\d+) points?\)$/);
    const description = document.createElement("span");
    description.textContent = match ? match[1] : factor;
    item.append(description);

    if (match) {
      const points = Number(match[2]);
      contributions.push(points);
      const contribution = document.createElement("strong");
      contribution.textContent = `+${points}`;
      contribution.setAttribute("aria-label", `${points} points`);
      item.append(contribution);
    } else if (!factor.startsWith("No elevated handling indicators")) {
      const unavailable = document.createElement("small");
      unavailable.textContent = "Point contribution not recorded for this saved assessment.";
      item.append(unavailable);
    }

    list.append(item);
  });

  const calculation = document.createElement("p");
  calculation.className = "score-calculation";
  if (contributions.length) {
    calculation.textContent = `${contributions.join(" + ")} = ${score} preliminary points`;
  } else if (factors.some((factor) => !factor.startsWith("No elevated handling indicators"))) {
    calculation.textContent = `${score} preliminary points (detailed point contributions unavailable for this saved assessment)`;
  } else {
    calculation.textContent = "0 preliminary points (no elevated indicators recorded)";
  }

  const thresholdHeading = document.createElement("h4");
  thresholdHeading.textContent = "Category thresholds";
  const thresholds = document.createElement("p");
  thresholds.className = "risk-thresholds";
  thresholds.textContent = "Low: 0–2 points · Medium: 3–5 points · High: 6+ points";

  const disclaimer = document.createElement("p");
  disclaimer.className = "risk-disclaimer";
  disclaimer.textContent = "Preliminary rule-based scoring only; this is not a trained ML model and does not confirm contamination.";

  section.append(heading, list, calculation, thresholdHeading, thresholds, disclaimer);
  container.append(section);
}

function showAssessmentDetails(record) {
  $("#detail-dialog").dataset.riskCategory = record.risk_category;
  const content = $("#dialog-content");
  content.replaceChildren();
  const title = document.createElement("h2");
  title.className = "dialog-title";
  title.textContent = record.evidence_ref;
  const meta = document.createElement("div");
  meta.className = "dialog-meta";
  meta.textContent = `${record.evidence_type} · Recorded ${formatDate(record.created_at, true)}`;
  const badgeWrap = document.createElement("div");
  badgeWrap.style.marginTop = "13px";
  badgeWrap.innerHTML = badge(record.risk_category);
  const details = document.createElement("div");
  details.className = "detail-grid";
  const items = [
    ["Collection conditions", record.collection_conditions],
    ["PPE compliant", record.ppe_compliant ? "Yes" : "No"],
    ["Tool condition", record.tool_condition],
    ["Packaging condition", record.packaging_condition],
    ["Storage condition", record.storage_condition],
    ["Separately packaged", record.separately_packaged ? "Yes" : "No"],
    ["Custody documented", record.chain_of_custody_documented ? "Yes" : "No"],
    ["Preliminary score", record.risk_score],
  ];
  items.forEach(([label, value]) => {
    const cell = document.createElement("div");
    cell.className = "detail-item";
    const key = document.createElement("span");
    key.textContent = label;
    const val = document.createElement("strong");
    val.textContent = String(value).replaceAll("_", " ");
    cell.append(key, val);
    details.append(cell);
  });
  content.append(title, meta, badgeWrap, details);
  renderRiskExplanation(content, record.risk_factors, record.risk_score);
  renderList(content, "Precaution recommendations", record.recommendations);
  $("#detail-dialog").showModal();
}

function showAssessmentResult(result) {
  const container = $("#assessment-result");
  container.dataset.riskCategory = result.risk_category;
  container.replaceChildren();
  container.classList.remove("hidden");
  const heading = document.createElement("div");
  heading.className = "result-heading";
  const title = document.createElement("h2");
  title.textContent = "Assessment recorded";
  const badgeElement = document.createElement("span");
  badgeElement.innerHTML = badge(result.risk_category);
  heading.append(title, badgeElement);
  const score = document.createElement("div");
  score.className = "result-score";
  score.textContent = String(result.risk_score);
  const suffix = document.createElement("small");
  suffix.textContent = " preliminary points";
  score.append(suffix);
  const reference = document.createElement("p");
  reference.className = "muted";
  reference.style.fontSize = "10px";
  reference.textContent = `Saved as ${result.evidence_ref}`;
  container.append(heading, score, reference);
  renderRiskExplanation(container, result.risk_factors, result.risk_score);
  renderList(container, "Precaution recommendations", result.recommendations);
}

function showExperimentalPrediction(result) {
  const container = $("#experimental-prediction-result");
  container.replaceChildren();
  const heading = document.createElement("strong");
  heading.textContent = `Synthetic outcome: ${result.prediction.replaceAll("_", " ")}`;
  const algorithm = document.createElement("p");
  algorithm.textContent = `Algorithm: ${result.algorithm}`;
  const probabilities = document.createElement("ul");
  Object.entries(result.class_probabilities).forEach(([label, probability]) => {
    const item = document.createElement("li");
    item.textContent = `${label.replaceAll("_", " ")}: ${new Intl.NumberFormat(undefined, {
      style: "percent",
      maximumFractionDigits: 1,
    }).format(probability)}`;
    probabilities.append(item);
  });
  const note = document.createElement("p");
  note.textContent = result.disclaimer;
  container.append(heading, algorithm, probabilities, note);
  container.classList.add("has-result");
}

$("#run-experimental-prediction").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const form = $("#assessment-form");
  const featureNames = [
    "evidence_type",
    "collection_conditions",
    "ppe_compliant",
    "tool_condition",
    "packaging_condition",
    "storage_condition",
    "separately_packaged",
    "chain_of_custody_documented",
  ];
  const values = Object.fromEntries(new FormData(form).entries());
  if (featureNames.some((name) => !values[name])) {
    showToast("Select every handling feature before running the experimental model.", true);
    return;
  }
  values.ppe_compliant = values.ppe_compliant === "true";
  values.separately_packaged = values.separately_packaged === "true";
  values.chain_of_custody_documented = values.chain_of_custody_documented === "true";
  const predictionInput = Object.fromEntries(
    featureNames.map((name) => [name, values[name]]),
  );
  button.disabled = true;
  try {
    showExperimentalPrediction(await api("/predict", {
      method: "POST",
      body: JSON.stringify(predictionInput),
    }));
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
});

$("#auth-switch").addEventListener("click", () => setAuthMode(state.authMode === "login" ? "signup" : "login"));
$("#auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form).entries());
  const button = $("#auth-submit");
  button.disabled = true;
  try {
    const path = state.authMode === "signup" ? "/api/auth/signup" : "/api/auth/login";
    const response = await api(path, { method: "POST", body: JSON.stringify(values) });
    showWorkspace(response.user);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
});

$("#assessment-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form).entries());
  values.ppe_compliant = values.ppe_compliant === "true";
  values.separately_packaged = values.separately_packaged === "true";
  values.chain_of_custody_documented = values.chain_of_custody_documented === "true";
  const button = form.querySelector('[type="submit"]');
  button.disabled = true;
  try {
    const result = await api("/api/assessments", { method: "POST", body: JSON.stringify(values) });
    showAssessmentResult(result);
    form.reset();
    showToast("Assessment saved to your history.");
    loadDashboard().catch((error) => showToast(error.message, true));
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
});

$("#risk-filter").addEventListener("change", () => loadHistory().catch((error) => showToast(error.message, true)));
async function logout() {
  try {
    await api("/api/auth/logout", { method: "POST" });
    showAuth();
  } catch (error) {
    showToast(error.message, true);
  }
}
$("#logout-button").addEventListener("click", logout);
$("#logout-mobile").addEventListener("click", logout);
$("#close-dialog").addEventListener("click", () => $("#detail-dialog").close());
$("#detail-dialog").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});
document.addEventListener("click", (event) => {
  const authButton = event.target.closest("[data-auth-view]");
  if (authButton) {
    showAuth(authButton.dataset.authView);
    return;
  }
  if (event.target.closest("[data-show-landing]")) {
    showLanding();
    return;
  }
  const riskFilter = event.target.closest("[data-risk-filter]");
  if (riskFilter && state.user) {
    $("#risk-filter").value = riskFilter.dataset.riskFilter;
    navigate("history");
    return;
  }
  const detailButton = event.target.closest("[data-assessment-id]");
  if (detailButton && state.dashboard) {
    const record = state.dashboard.high_risk_assessments.find(
      (assessment) => assessment.id === Number(detailButton.dataset.assessmentId),
    );
    if (record) showAssessmentDetails(record);
    return;
  }
  const button = event.target.closest("[data-view]");
  if (button && state.user) navigate(button.dataset.view);
});

(async function initialize() {
  try {
    await csrfToken();
    const response = await api("/api/auth/me");
    showWorkspace(response.user);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      showLanding();
    } else {
      showLanding();
      showToast(error.message || "Could not connect to the workspace.", true);
    }
  }
})();
