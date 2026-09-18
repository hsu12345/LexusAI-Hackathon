# LexusAI｜潛在流失風險洞察與智慧溝通規劃系統

黑客松題目：**AI 流失風險洞察與智慧溝通：打造 Lexus 車主忠誠度的終極防線**

目標使用者：Lexus 售後服務部門決策者

## 兩大產出對應

| 產出 | 系統位置 |
|------|----------|
| 產出 1：AI 網路輿情洞察系統與報告 | Dashboard「輿情總覽 / Persona / 風險議題」+ `/api/report` |
| 產出 2：目標 Persona 的 AI 溝通計畫 | Dashboard「AI 溝通計畫 / 系統流程」+ `/api/communication/{id}` |

## 快速啟動

```bash
cd LexusAI
pip install -r requirements.txt

# 1) 先爬取公開社群資料（PTT / Mobile01）
python scripts/crawl.py
# 或雙擊 crawl.bat

# 2) 啟動分析 Dashboard
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

瀏覽器開啟：http://127.0.0.1:8000

（可選）若要啟用 LLM 即時生成文案，於環境變數設定 `OPENAI_API_KEY`，並呼叫：

```bash
curl -X POST http://127.0.0.1:8000/api/communication/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"persona_id\":\"price_switcher\",\"use_llm\":true}"
```

## 專案結構

```
LexusAI/
├── knowledge/lexus_service_kb.json   # 車主權益手冊結構化知識庫
├── data/sample_posts.json            # PTT/Dcard/Mobile01 示範討論
├── backend/app/
│   ├── main.py                       # FastAPI
│   ├── models.py
│   └── services/
│       ├── nlp_analyzer.py           # 主題／情緒／風險評分
│       ├── insight.py                # Persona 與市場報告
│       └── communication.py          # RAG 溝通計畫生成
└── frontend/                         # 售後決策儀表板
```

## AI 技術說明（簡報可用）

1. **主題自動標籤**：服務體驗、零件保修、價格價值、便利性、回饋忠誠、替代通路
2. **情緒分析**：中文正負向詞典計分（可替換 Transformer）
3. **流失風險模型**：價格敏感、保證轉換、外廠轉向意圖、時間摩擦、信任裂痕加權
4. **Persona 分群**：風險因子共現規則分群
5. **知識庫增強溝通生成（RAG）**：以車主權益手冊話術生成 LINE／App／Email／專員腳本

## 爬蟲說明

```bash
python scripts/crawl.py                     # PTT + Mobile01 + Dcard
python scripts/crawl.py --ptt-only          # 只爬 PTT（較穩定）
python scripts/crawl.py --dcard-only        # 只爬 Dcard
python scripts/crawl.py --skip-dcard        # 跳過 Dcard
python scripts/crawl.py --max-articles 80 --max-search-pages 8
```

**Dcard 特別說明**：Dcard 有 Cloudflare 防護，爬蟲會短暫開啟 Edge 瀏覽器建立 session（預設非 headless）。
首次執行後 cookies 會存到 `data/dcard_cookies.json`。若失敗可重試或執行：
`python -m playwright install chromium`

輸出：
- `data/crawled_posts.json` — 爬取結果（Dashboard 優先讀取）
- `data/crawl_meta.json` — 爬取時間與來源統計

**注意**：僅抓取公開頁面，請遵守 PTT / Mobile01 使用條款，並保留合理請求間隔（預設 1.2 秒）。

## 資料說明

- `knowledge/` 內容整理自附件《車主權益手冊》
- `data/sample_posts.json` 為示範語料；執行爬蟲後會以 `crawled_posts.json` 為主

## 下一步建議

1. 接上真實社群爬蟲／公開資料集
2. 將情緒與主題模型升級為中文 BERT／embedding 聚類
3. 串接 CRM／回廠紀錄做半監督風險標註
4. 補齊簡報用商業可行性與 ROI 試算頁
