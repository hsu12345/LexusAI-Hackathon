const state = {
  report: null,
  posts: [],
  personas: [],
  plans: {},
  llmAvailable: false,
};

const $ = (sel) => document.querySelector(sel);

const FALLBACK_FLOW = {
  flow_steps: [
    { step: "1. 蒐集", desc: "抓取 PTT、Dcard、Mobile01、Threads 公開討論" },
    { step: "2. 分析", desc: "標記主題、情緒與流失風險" },
    { step: "3. 歸類", desc: "對應四類車主樣態，銜接輿情摘要" },
    { step: "4. 檢索", desc: "從車主權益手冊找出相關條文" },
    { step: "5. 撰稿", desc: "產出各通路建議文案（可選 AI 改寫）" },
    { step: "6. 審核", desc: "售後人員確認內容與引用是否正確" },
    { step: "7. 發送", desc: "依規則觸發 LINE／App 等（CRM 串接為後續階段）" },
    { step: "8. 回饋", desc: "以回廠率等指標調整規則" },
  ],
  flow_mermaid: `flowchart LR
  subgraph data ["資料層"]
    A[公開輿情]
    B[權益手冊]
  end
  subgraph analysis ["分析層"]
    C[NLP 風險偵測]
    D[車主樣態]
  end
  subgraph action ["行動層"]
    E[手冊檢索]
    F[撰稿]
    G[人工審核]
    H[通路發送]
  end
  A --> C --> D --> E
  B --> E
  E --> F --> G --> H
  H -->|KPI 回寫| C`,
};

let mermaidRenderSeq = 0;

async function renderMermaidDiagram(container, source) {
  if (!container || !source) return;
  const definition = String(source).trim();
  if (!window.mermaid) {
    container.innerHTML = `<pre class="mermaid-fallback">${escapeHtml(definition)}</pre>`;
    return;
  }
  try {
    mermaidRenderSeq += 1;
    const id = `lexus-flow-${mermaidRenderSeq}`;
    const { svg } = await mermaid.render(id, definition);
    container.innerHTML = svg;
  } catch (err) {
    console.warn("Mermaid render failed:", err);
    container.innerHTML = `<pre class="mermaid-fallback">${escapeHtml(definition)}</pre>`;
  }
}

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatAnalyzedAt(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("zh-TW", { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return iso;
  }
}

function renderDataMeta(health, data) {
  const source = data.data_source === "crawled" ? "社群爬蟲資料" : "內建範例資料";
  const analyzed = formatAnalyzedAt(data.analyzed_at);
  const cached = data.cached ? "已快取" : "即時運算";
  const meta = health.crawl_meta;
  let crawlHint = "";
  if (meta?.crawled_at) {
    crawlHint = ` · 資料更新 ${formatAnalyzedAt(meta.crawled_at)}`;
  }
  const line = `${source} · 分析時間 ${analyzed}（${cached}）· 共 ${data.post_count ?? health.post_count ?? "—"} 篇${crawlHint}`;
  const el = $("#data-meta");
  if (el) el.textContent = line;
  const foot = $("#footer-data-line");
  if (foot) foot.textContent = line;
}

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
  const afterTotal = Math.max(after.total_posts || 0, 1);
  const afterHigh = (after.risk_breakdown && after.risk_breakdown.high) || 0;
  const items = [
    { label: "監測討論數", value: report.total_posts },
    { label: "售後相關討論", value: after.total_posts ?? "—" },
    { label: "售後平均風險", value: after.avg_churn_risk != null ? after.avg_churn_risk.toFixed(2) : "—" },
    { label: "售後高風險占比", value: after.total_posts ? `${Math.round(100 * afterHigh / afterTotal)}%` : "—" },
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
  $("#risk-feed").innerHTML = top.map((p) => {
    const title = escapeHtml(p.title || "（無標題）");
    const titleHtml = p.url
      ? `<a class="feed-title" href="${escapeHtml(p.url)}" target="_blank" rel="noopener noreferrer">${title}</a>`
      : `<strong>${title}</strong>`;
    return `
    <div class="feed-item">
      <span class="badge ${p.risk_level}">${riskLabel(p.risk_level)}</span>
      <div>
        ${titleHtml}
        <div class="feed-meta">${escapeHtml(p.source)} · 售後相關 ${(p.service_relevance_score || 0).toFixed(2)} · ${escapeHtml((p.topics || []).join(" / "))} · ${escapeHtml((p.risk_factors || []).slice(0, 2).join("、") || "—")}</div>
      </div>
      <div class="score">${p.churn_risk_score.toFixed(2)}</div>
    </div>
  `;
  }).join("");
}

function renderPersonas(personas) {
  $("#persona-grid").innerHTML = personas.map((p) => `
    <article class="persona-card" data-persona-id="${escapeHtml(p.id)}">
      <span class="badge ${p.risk_level}">${riskLabel(p.risk_level)} · ${p.share_pct}%</span>
      <h3>${escapeHtml(p.name)}</h3>
      <p class="tagline">${escapeHtml(p.tagline)}</p>
      <strong>痛點</strong>
      <ul>${p.pain_points.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>
      <strong>關鍵考量</strong>
      <ul>${p.key_considerations.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>
      ${(p.representative_quotes || []).map((q) => `<div class="quote">${escapeHtml(q)}</div>`).join("")}
      <button type="button" class="btn-persona-comm" data-persona-id="${escapeHtml(p.id)}">查看這類車主的溝通計畫</button>
    </article>
  `).join("");

  $("#persona-select").innerHTML = personas.map((p) =>
    `<option value="${p.id}">${escapeHtml(p.name)}</option>`
  ).join("");

  document.querySelectorAll(".btn-persona-comm").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-persona-id");
      if (id) openCommForPersona(id);
    });
  });
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
      <strong>手冊引用出處</strong>
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

function formatGenMethod(method) {
  const map = {
    rag: "手冊引用",
    "rag+llm": "手冊 + AI 改寫",
    template: "固定模板",
  };
  return map[method] || method || "";
}

function renderComm(plan) {
  const ir = plan.insight_response || {};
  const ragNote = plan.rag_enabled
    ? "文案依車主權益手冊條文撰寫"
    : "使用內建模板";
  const llmNote = plan.llm_available
    ? " · 可啟用 AI 改寫"
    : " · 未設定 OpenAI API Key";
  $("#comm-plan").innerHTML = `
    <article class="panel insight-link">
      <h2>對應輿情摘要</h2>
      <p class="lede">${escapeHtml(ir.rationale || "")}</p>
      <div class="insight-stats">
        <span class="chip">討論數 ${ir.segment_post_count ?? "—"}</span>
        <span class="chip">占比 ${ir.segment_share_pct ?? "—"}%</span>
        <span class="chip">平均風險 ${ir.segment_avg_risk != null ? ir.segment_avg_risk.toFixed(2) : "—"}</span>
        <span class="chip">高風險 ${ir.segment_high_risk_count ?? "—"} 則</span>
      </div>
      <div class="chips" style="margin-top:0.6rem">
        ${(ir.linked_topics || []).map((t) => `<span class="chip">常見議題：${escapeHtml(t)}</span>`).join("")}
        ${(ir.linked_risk_factors || []).map((f) => `<span class="chip warn">常見顧慮：${escapeHtml(f)}</span>`).join("")}
      </div>
    </article>

    <article class="panel">
      <h2>${escapeHtml(plan.persona_name)}｜溝通方向</h2>
      <p class="lede">${plan.core_strategy}</p>
      <strong>目標</strong>
      <ul>${plan.objectives.map((o) => `<li>${o}</li>`).join("")}</ul>
    </article>

    <article class="panel">
      <h2>建議接觸時機與通路</h2>
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
      <h2>建議文案範例</h2>
      <p class="subtle">${ragNote}${llmNote}</p>
      ${plan.contents.map((c) => `
        <div class="content-card">
          <div class="channel-tag">${escapeHtml(c.channel)} · ${formatGenMethod(c.generation_method)}</div>
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

}

async function renderFlow(plan) {
  const payload = plan?.flow_steps?.length ? plan : FALLBACK_FLOW;
  $("#system-flow").innerHTML = (payload.flow_steps || []).map((s) => `
    <div class="flow-step">
      <div class="step">${escapeHtml(s.step)}</div>
      <p>${escapeHtml(s.desc)}</p>
    </div>
  `).join("");

  const mermaidEl = $("#mermaid-flow");
  if (mermaidEl && payload.flow_mermaid) {
    await renderMermaidDiagram(mermaidEl, payload.flow_mermaid);
  }
}

async function ensureFlowDiagram(personaId) {
  try {
    const plan = await api(`/api/communication/${personaId}`);
    await renderFlow(plan);
    const cacheKey = `${personaId}:rag`;
    if (!state.plans[cacheKey]) state.plans[cacheKey] = plan;
    return plan;
  } catch {
    await renderFlow(FALLBACK_FLOW);
    return null;
  }
}

function switchView(viewId) {
  document.querySelectorAll(".nav-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === viewId);
  });
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  const view = $(`#view-${viewId}`);
  if (view) view.classList.add("active");
}

function openCommForPersona(personaId) {
  const sel = $("#persona-select");
  if (sel) sel.value = personaId;
  switchView("comm");
  loadComm(personaId).catch((err) => {
    $("#comm-plan").innerHTML = `<article class="panel"><p class="lede">載入溝通計畫失敗：${escapeHtml(err.message)}</p></article>`;
  });
}

async function loadComm(personaId, { useLlm = false, force = false } = {}) {
  const cacheKey = `${personaId}:${useLlm ? "llm" : "rag"}`;
  if (!force && state.plans[cacheKey]) {
    renderComm(state.plans[cacheKey]);
    await renderFlow(state.plans[cacheKey]);
    return;
  }

  const commEl = $("#comm-plan");
  if (commEl) commEl.innerHTML = `<article class="panel"><p class="lede">載入中…</p></article>`;

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
  await renderFlow(state.plans[cacheKey]);
}

function bindNav() {
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
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
      ? "AI 改寫可用"
      : "目前為手冊文案模式（設定 API Key 可改寫）";
    statusEl.className = `llm-status ${health.llm_available ? "ok" : ""}`;
  }
  const llmBtn = $("#btn-llm");
  if (llmBtn && !health.llm_available) {
    llmBtn.disabled = true;
  }

  renderDataMeta(health, data);
  $("#executive-summary").textContent = data.report.executive_summary;
  renderMetrics(data.report);
  renderSentiment(data.report);
  renderTopics(data.report);
  renderRiskFeed(data.posts);
  renderPersonas(data.report.personas);
  renderFactors(data.report);

  const first = data.report.personas[0]?.id || "price_switcher";
  $("#persona-select").value = first;
  $("#persona-select").addEventListener("change", (e) => {
    loadComm(e.target.value).catch((err) => {
      $("#comm-plan").innerHTML = `<article class="panel"><p class="lede">載入失敗：${escapeHtml(err.message)}</p></article>`;
    });
  });

  await ensureFlowDiagram(first);

  $("#btn-rag")?.addEventListener("click", () => {
    const id = $("#persona-select").value;
    loadComm(id, { force: true }).catch((err) => {
      $("#comm-plan").innerHTML = `<article class="panel"><p class="lede">載入失敗：${escapeHtml(err.message)}</p></article>`;
    });
  });
  $("#btn-llm")?.addEventListener("click", () => {
    const id = $("#persona-select").value;
    loadComm(id, { useLlm: true, force: true }).catch((err) => {
      $("#comm-plan").innerHTML = `<article class="panel"><p class="lede">AI 改寫失敗：${escapeHtml(err.message)}</p></article>`;
    });
  });

  try {
    await loadComm(first);
  } catch (err) {
    $("#comm-plan").innerHTML = `<article class="panel"><p class="lede">載入溝通計畫失敗：${escapeHtml(err.message)}</p></article>`;
  }
}

init().catch((err) => {
  $("#executive-summary").textContent = `載入失敗：${err.message}。請確認後端已啟動。`;
});
