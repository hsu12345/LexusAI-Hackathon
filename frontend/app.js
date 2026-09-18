const state = {
  report: null,
  posts: [],
  personas: [],
  plans: {},
};

const $ = (sel) => document.querySelector(sel);

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error(`API ${path} failed`);
  return res.json();
}

function riskLabel(level) {
  return ({ high: "高風險", medium: "中風險", low: "低風險" }[level] || level);
}

function sentimentLabel(s) {
  return ({ positive: "正向", neutral: "中立", negative: "負向" }[s] || s);
}

function renderMetrics(report) {
  const items = [
    { label: "監測討論數", value: report.total_posts },
    { label: "平均流失風險", value: report.avg_churn_risk.toFixed(2) },
    { label: "高風險占比", value: `${Math.round(100 * (report.risk_breakdown.high || 0) / report.total_posts)}%` },
    { label: "Persona 數", value: report.personas.length },
  ];
  $("#metric-row").innerHTML = items.map((m) => `
    <div class="metric">
      <div class="label">${m.label}</div>
      <div class="value">${m.value}</div>
    </div>
  `).join("");
}

function renderSentiment(report) {
  const total = report.total_posts || 1;
  const order = ["negative", "neutral", "positive"];
  $("#sentiment-bars").innerHTML = order.map((k) => {
    const n = report.sentiment_breakdown[k] || 0;
    const pct = Math.round(100 * n / total);
    return `
      <div class="bar-row">
        <span>${sentimentLabel(k)}</span>
        <div class="bar-track"><div class="bar-fill ${k}" style="width:${pct}%"></div></div>
        <span>${pct}%</span>
      </div>
    `;
  }).join("");

  $("#source-chips").innerHTML = Object.entries(report.source_breakdown).map(([k, v]) =>
    `<span class="chip">${k} · ${v}</span>`
  ).join("");
}

function renderTopics(report) {
  const rows = report.topic_insights.map((t) => `
    <tr>
      <td>${t.topic}</td>
      <td>${t.count}</td>
      <td>${Math.round(t.negative_ratio * 100)}%</td>
      <td>${t.avg_risk.toFixed(2)}</td>
    </tr>
  `).join("");
  $("#topic-table").innerHTML = `
    <table>
      <thead><tr><th>主題</th><th>討論數</th><th>負向比</th><th>平均風險</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderRiskFeed(posts) {
  const top = [...posts].sort((a, b) => b.churn_risk_score - a.churn_risk_score).slice(0, 6);
  $("#risk-feed").innerHTML = top.map((p) => `
    <div class="feed-item">
      <span class="badge ${p.risk_level}">${riskLabel(p.risk_level)}</span>
      <div>
        <strong>${p.title}</strong>
        <div class="feed-meta">${p.source} · ${p.topics.join(" / ")} · ${(p.risk_factors || []).slice(0, 2).join("、") || "—"}</div>
      </div>
      <div class="score">${p.churn_risk_score.toFixed(2)}</div>
    </div>
  `).join("");
}

function renderPersonas(personas) {
  $("#persona-grid").innerHTML = personas.map((p) => `
    <article class="persona-card">
      <span class="badge ${p.risk_level}">${riskLabel(p.risk_level)} · ${p.share_pct}%</span>
      <h3>${p.name}</h3>
      <p class="tagline">${p.tagline}</p>
      <strong>痛點</strong>
      <ul>${p.pain_points.map((x) => `<li>${x}</li>`).join("")}</ul>
      <strong>關鍵考量</strong>
      <ul>${p.key_considerations.map((x) => `<li>${x}</li>`).join("")}</ul>
      ${(p.representative_quotes || []).map((q) => `<div class="quote">${q}</div>`).join("")}
    </article>
  `).join("");

  $("#persona-select").innerHTML = personas.map((p) =>
    `<option value="${p.id}">${p.name}</option>`
  ).join("");
}

function renderFactors(report) {
  const max = Math.max(...report.top_risk_factors.map((f) => f.count), 1);
  $("#factor-list").innerHTML = report.top_risk_factors.map((f) => `
    <div class="factor-item">
      <span>${f.factor}</span>
      <strong>${f.count}（${f.share_pct}%）</strong>
      <div class="factor-track"><div class="factor-fill" style="width:${Math.round(100 * f.count / max)}%"></div></div>
    </div>
  `).join("");
  $("#ai-methods").innerHTML = report.ai_methods.map((m) => `<li>${m}</li>`).join("");
}

function renderComm(plan) {
  $("#comm-plan").innerHTML = `
    <article class="panel">
      <h2>${plan.persona_name}｜核心策略</h2>
      <p class="lede">${plan.core_strategy}</p>
      <strong>目標</strong>
      <ul>${plan.objectives.map((o) => `<li>${o}</li>`).join("")}</ul>
      <strong>接觸點</strong>
      <div class="chips" style="margin:0.6rem 0 1rem">
        ${plan.touchpoints.map((t) => `<span class="chip">${t.channel}：${t.purpose}</span>`).join("")}
      </div>
      <strong>AI 生成內容範例</strong>
      ${plan.contents.map((c) => `
        <div class="content-card">
          <div class="channel-tag">${c.channel}</div>
          <h4>${c.title}</h4>
          <p>${c.body}</p>
          <div class="chips">${c.talking_points.map((t) => `<span class="chip">${t}</span>`).join("")}</div>
          <div class="cta">${c.cta}</div>
        </div>
      `).join("")}
      <strong>KPI</strong>
      <ul>${plan.kpi.map((k) => `<li>${k}</li>`).join("")}</ul>
    </article>
  `;

  $("#system-flow").innerHTML = plan.flow_steps.map((s) => `
    <div class="flow-step">
      <div class="step">${s.step}</div>
      <p>${s.desc}</p>
    </div>
  `).join("");
}

async function loadComm(personaId) {
  if (!state.plans[personaId]) {
    state.plans[personaId] = await api(`/api/communication/${personaId}`);
  }
  renderComm(state.plans[personaId]);
}

function bindNav() {
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
      btn.classList.add("active");
      $(`#view-${btn.dataset.view}`).classList.add("active");
    });
  });
}

async function init() {
  bindNav();
  const data = await api("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ use_sample: true }),
  });
  state.report = data.report;
  state.posts = data.posts;
  state.personas = data.report.personas;

  $("#executive-summary").textContent = data.report.executive_summary;
  renderMetrics(data.report);
  renderSentiment(data.report);
  renderTopics(data.report);
  renderRiskFeed(data.posts);
  renderPersonas(data.report.personas);
  renderFactors(data.report);

  const first = data.report.personas[0]?.id || "price_switcher";
  $("#persona-select").value = first;
  $("#persona-select").addEventListener("change", (e) => loadComm(e.target.value));
  await loadComm(first);
}

init().catch((err) => {
  $("#executive-summary").textContent = `載入失敗：${err.message}。請確認後端已啟動。`;
});
