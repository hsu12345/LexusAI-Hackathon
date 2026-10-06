const state = {
  report: null,
  posts: [],
  personas: [],
  plans: {},
  llmAvailable: false,
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

function priorityLabel(p) {
  return ({ high: "高優先", medium: "中優先", low: "低優先" }[p] || p);
}

function renderMetrics(report) {
  const after = report.aftersales_insight || {};
  const items = [
    { label: "監測討論數", value: report.total_posts },
    { label: "售後相關討論", value: after.total_posts ?? "—" },
    { label: "售後平均風險", value: after.avg_churn_risk != null ? after.avg_churn_risk.toFixed(2) : "—" },
    { label: "高風險占比", value: `${Math.round(100 * (report.risk_breakdown.high || 0) / report.total_posts)}%` },
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
  const pool = posts.filter((p) => p.is_aftersales_focus).length
    ? posts.filter((p) => p.is_aftersales_focus)
    : posts;
  const top = [...pool].sort((a, b) => b.churn_risk_score - a.churn_risk_score).slice(0, 8);
  $("#risk-feed").innerHTML = top.map((p) => `
    <div class="feed-item">
      <span class="badge ${p.risk_level}">${riskLabel(p.risk_level)}</span>
      <div>
        <strong>${p.title}</strong>
        <div class="feed-meta">${p.source} · 售後相關 ${(p.service_relevance_score || 0).toFixed(2)} · ${p.topics.join(" / ")} · ${(p.risk_factors || []).slice(0, 2).join("、") || "—"}</div>
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

function renderCitations(citations) {
  if (!citations?.length) return "";
  return `
    <div class="kb-citations">
      <strong>知識庫引用（RAG）</strong>
      ${citations.map((c) => `
        <div class="citation">
          <span class="cite-id">${c.chunk_id}</span>
          <span>${c.title}</span>
          <p>${c.excerpt}…</p>
        </div>
      `).join("")}
    </div>
  `;
}

function renderComm(plan) {
  const ir = plan.insight_response || {};
  $("#comm-plan").innerHTML = `
    <article class="panel insight-link">
      <h2>回應產出 1 洞察</h2>
      <p class="lede">${ir.rationale || ""}</p>
      <div class="insight-stats">
        <span class="chip">討論數 ${ir.segment_post_count ?? "—"}</span>
        <span class="chip">占比 ${ir.segment_share_pct ?? "—"}%</span>
        <span class="chip">平均風險 ${ir.segment_avg_risk != null ? ir.segment_avg_risk.toFixed(2) : "—"}</span>
        <span class="chip">高風險 ${ir.segment_high_risk_count ?? "—"} 則</span>
      </div>
      <div class="chips" style="margin-top:0.6rem">
        ${(ir.linked_topics || []).map((t) => `<span class="chip">議題：${t}</span>`).join("")}
        ${(ir.linked_risk_factors || []).map((f) => `<span class="chip warn">因子：${f}</span>`).join("")}
      </div>
    </article>

    <article class="panel">
      <h2>${plan.persona_name}｜核心溝通策略</h2>
      <p class="lede">${plan.core_strategy}</p>
      <strong>目標</strong>
      <ul>${plan.objectives.map((o) => `<li>${o}</li>`).join("")}</ul>
    </article>

    <article class="panel">
      <h2>精準接觸點規劃</h2>
      <div class="touchpoint-table">
        <table>
          <thead>
            <tr>
              <th>通路</th><th>目的</th><th>觸發條件</th><th>時機</th><th>優先級</th><th>訊息主軸</th>
            </tr>
          </thead>
          <tbody>
            ${(plan.touchpoint_timeline || []).map((t) => `
              <tr>
                <td>${t.channel}</td>
                <td>${t.purpose}</td>
                <td>${t.trigger}</td>
                <td>${t.timing}</td>
                <td><span class="badge ${t.priority === "high" ? "high" : t.priority === "medium" ? "medium" : "low"}">${priorityLabel(t.priority)}</span></td>
                <td>${t.message_theme}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </article>

    <article class="panel">
      <h2>AI 生成內容範例</h2>
      <p class="subtle">${plan.rag_enabled ? "由 RAG 检索車主權益手冊後生成" : "模板文案"}${plan.llm_available ? " · LLM 已就緒" : " · 離線 RAG 模式（未設定 API Key）"}</p>
      ${plan.contents.map((c) => `
        <div class="content-card">
          <div class="channel-tag">${c.channel} · ${c.generation_method || "template"}</div>
          ${c.trigger ? `<div class="meta-line">觸發：${c.trigger}｜時機：${c.timing || "—"}</div>` : ""}
          <h4>${c.title}</h4>
          <p>${c.body}</p>
          <div class="chips">${c.talking_points.map((t) => `<span class="chip">${t}</span>`).join("")}</div>
          ${renderCitations(c.kb_citations)}
          <div class="cta">${c.cta}</div>
        </div>
      `).join("")}
      <strong>KPI</strong>
      <ul>${plan.kpi.map((k) => `<li>${k}</li>`).join("")}</ul>
    </article>
  `;

  renderFlow(plan);
}

function renderFlow(plan) {
  $("#system-flow").innerHTML = (plan.flow_steps || []).map((s) => `
    <div class="flow-step">
      <div class="step">${s.step}</div>
      <p>${s.desc}</p>
    </div>
  `).join("");

  const mermaidEl = $("#mermaid-flow");
  if (mermaidEl && plan.flow_mermaid) {
    mermaidEl.innerHTML = plan.flow_mermaid;
    mermaidEl.removeAttribute("data-processed");
    if (window.mermaid) {
      mermaid.run({ nodes: [mermaidEl] }).catch(() => {
        mermaidEl.textContent = plan.flow_mermaid;
      });
    }
  }
}

async function loadComm(personaId, { useLlm = false, force = false } = {}) {
  const cacheKey = `${personaId}:${useLlm ? "llm" : "rag"}`;
  if (!force && state.plans[cacheKey]) {
    renderComm(state.plans[cacheKey]);
    return;
  }

  if (useLlm) {
    state.plans[cacheKey] = await api("/api/communication/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ persona_id: personaId, use_llm: true, use_rag: true }),
    });
  } else {
    state.plans[cacheKey] = await api(`/api/communication/${personaId}`);
  }
  renderComm(state.plans[cacheKey]);
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
  if (window.mermaid) {
    mermaid.initialize({ startOnLoad: false, theme: "neutral", securityLevel: "loose" });
  }

  const [health, data] = await Promise.all([
    api("/api/health"),
    api("/api/dashboard"),
  ]);

  state.llmAvailable = health.llm_available;
  state.report = data.report;
  state.posts = data.posts;
  state.personas = data.report.personas;

  const statusEl = $("#llm-status");
  if (statusEl) {
    statusEl.textContent = health.llm_available
      ? "LLM 已就緒"
      : "離線 RAG（設定 OPENAI_API_KEY 可啟用 LLM）";
    statusEl.className = `llm-status ${health.llm_available ? "ok" : ""}`;
  }
  const llmBtn = $("#btn-llm");
  if (llmBtn && !health.llm_available) {
    llmBtn.disabled = true;
  }

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

  $("#btn-rag")?.addEventListener("click", () => {
    const id = $("#persona-select").value;
    loadComm(id, { force: true });
  });
  $("#btn-llm")?.addEventListener("click", () => {
    const id = $("#persona-select").value;
    loadComm(id, { useLlm: true, force: true });
  });

  await loadComm(first);
}

init().catch((err) => {
  $("#executive-summary").textContent = `載入失敗：${err.message}。請確認後端已啟動。`;
});
