# RunSense 系統交接與環境建置指南 (HANDOFF.md)

給 Eric：照著下面的步驟從零把整套系統（資料庫 + 後端 + 前端）跑起來，最後有一個「驗證清單」，包含確認 AI 教練聊天室真的能回話。架構總覽、目錄結構、功能清單請看 [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)；領域名詞字典看 [CONTEXT.md](CONTEXT.md)。這份文件只講「怎麼把它跑起來」。

> 想偷懶的話：`.\start-runsense.ps1`（Windows PowerShell）會自動做完下面 1~3 的大部分步驟，並開兩個新視窗分別跑後端／前端。仍然建議先讀一次下面的內容，尤其是第 2 節的 API Key 部分，一鍵腳本不會幫你申請金鑰。

---

## 0. 前置需求

- Python 3.11+（`py -3.11` 或 `python3.11` 可用）
- Node.js + npm
- Docker Desktop（跑 PostgreSQL 16，需支援 Row-Level Security，用官方 `postgres:16` image 即可）
- Git

---

## 1. 資料庫 (PostgreSQL 16 via Docker)

```bash
cd backend
docker compose up -d
docker compose ps   # 確認 postgres 容器狀態是 healthy，5432 埠有監聽
```

---

## 2. 後端 (FastAPI)

```bash
cd backend

# 1. 建立虛擬環境
py -3.11 -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 2. 安裝依賴（editable install，套件定義在 pyproject.toml，沒有 requirements.txt）
pip install -e ".[dev]"

# 3. 設定環境變數
cp .env.example .env
# 用編輯器打開 backend/.env，至少確認/填入下面第 2.1 節列的項目

# 4. 資料庫 migration
alembic upgrade head

# 5. 植入 demo 帳號 + demo 資料
python scripts/seed_demo_personas.py
python scripts/seed_rich_athlete_history.py   # 補齊 3 位 demo 選手各自的 28 天訓練歷史，見下方註記

# 6. 啟動後端
uvicorn app.main:app --reload --port 8000
```

Swagger 文件：`http://127.0.0.1:8000/docs`

**`.env` 載入的一個重要細節**：`app/main.py` 會呼叫 `app/runtime_env.py` 的 `load_runtime_environment()`，它一定會讀 `.env`（用 `override=False`，不會蓋掉你在 shell 裡手動 `export` 過的變數）。舊版程式碼曾經在偵測到 `COMPETITION_DEMO_ONLY` 已存在於環境變數時，直接整個跳過讀取 `.env`——如果你在啟動前手動 `export COMPETITION_DEMO_ONLY=true`（例如照抄某些舊腳本的做法），會連 `GROQ_API_KEY` 一起讀不到，導致 AI 教練聊天永遠回覆固定的「雲端健康教練目前無法回覆」。現在的 `runtime_env.py` 已經修掉這個問題，兩種啟動方式都沒問題，這裡記錄原因只是避免以後又踩到類似的坑。

### 2.1 需要準備的環境變數（`backend/.env`）

| 變數 | 用途 | 沒設定的行為 |
| :--- | :--- | :--- |
| `DATABASE_URL` / `COMPETITION_DEMO_ONLY` / `DEMO_JWT_SECRET` | `.env.example` 已經給預設值，本機開發直接用即可 | — |
| `GROQ_API_KEY` | **AI 健康教練聊天室**（`POST /guidance/chat`）用的雲端 LLM，走 Groq 的 OpenAI 相容端點 | 沒填的話，聊天室固定回覆「雲端健康教練目前無法回覆」的安全文案，其他功能不受影響 |
| `OPENWEATHER_API_KEY` | 即時氣溫/濕度（天候等效配速用） | 天候狀態顯示 `UNAVAILABLE`，不影響其他功能 |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | 本地 Ollama，只用在課表語氣挑選（`select_tone_variant`，5 選 1 的白名單文案）——**跟上面的 AI 教練聊天室是兩個不同的功能**，Ollama 沒開不影響聊天室 | 退回固定的 `NEUTRAL_FALLBACK` 語氣文案 |
| `GARMIN_ACTIVITY_SYNC_ENABLED` 等 Garmin 變數 | Phase 1B 尚未真正串接，純 feature flag | 維持關閉 |

**申請 `GROQ_API_KEY`**（免費額度足夠開發用）：
1. 開 https://console.groq.com/keys
2. 用 Google/GitHub 帳號登入，按「Create API Key」
3. 貼到 `backend/.env` 的 `GROQ_API_KEY=`（值一定是 `gsk_` 開頭）

> 金鑰只放在你自己的 `backend/.env`（已被 `.gitignore` 排除），不要放進任何會被 commit 的檔案或直接貼進 Slack/PR。

---

## 3. 前端 (React 19 + Vite)

```bash
cd web
npm install
npm run dev
```

前端網址：`http://localhost:5173`（沒接後端網址時前端仍可用內建示範資料跑起來；要接真後端請確認 `web/.env` 或啟動時的 `VITE_API_BASE_URL` 指到 `http://127.0.0.1:8000`）

---

## 4. Demo 帳號

登入頁的角色選擇器會自動帶入，來源是 `web/src/state/AuthContext.tsx` 對應 `backend/scripts/seed_demo_personas.py`：

| 角色 | Email | 密碼 | 時區 | 備註 |
| :--- | :--- | :--- | :--- | :--- |
| 教練（同時也是選手） | `runner.taipei@runsense.demo` | `TaipeiDemo!2026` | Asia/Taipei | 高負荷/衝量期選手畫像（ACWR 偏高） |
| 選手 | `runner.tokyo@runsense.demo` | `TokyoDemo!2026` | Asia/Tokyo | 穩定有氧選手畫像（ACWR 接近 1） |
| 選手 | `runner.london@runsense.demo` | `LondonDemo!2026` | Europe/London | 減量/恢復期選手畫像（觀測天數刻意偏低，示範「資料不足」UI 狀態） |

切換教練視角或高風險操作的 MFA 驗證碼固定是 **`424242`**。

---

## 5. 驗證清單（跑完 1~4 後，確認系統真的完整可用）

1. **後端活著**：瀏覽器打開 `http://127.0.0.1:8000/docs`，看到 Swagger UI。
2. **前端活著**：`http://localhost:5173` 能看到登入頁，選一個 demo 角色能登入。
3. **訓練負荷數字正常**：登入 `runner.taipei@runsense.demo` 後看首頁 4 格 HUD，「短長期負荷比」應該顯示一個數字（不是「計算中」），「有效觀測天數」應該 ≥ 21/28（若看到「資料不足」，通常代表 `seed_rich_athlete_history.py` 沒跑或跑在舊版程式碼上，重跑一次該腳本即可）。
4. **AI 教練聊天室真的能回話**（這是最容易漏掉、看起來像「功能正常」但其實是安全 fallback 文案在頂替的地方）：
   - 進入任一選手帳號，找到 AI 教練聊天入口，隨便問一句話。
   - **正常**：幾秒後出現一段完整、針對你問題展開的繁中回覆，通常會引用 ACWR 數值或 Graph RAG 檢索到的醫學文獻來源。
   - **不正常**：立刻（不到 1 秒）出現固定的「雲端健康教練目前無法回覆。請維持系統既有的固定安全分流結果...」——代表 `GROQ_API_KEY` 沒有生效，回頭檢查 `backend/.env` 裡的值，並確認啟動後端的那個終端機視窗沒有印出關於 `.env` 沒讀到的訊息。
5. （選用）**ML Plan Ranker 實驗模式**：預設是保守的規則式排序（`PLAN_RANKER_MODE=deterministic`，語音正式環境的預設值，理由見 `docs/adr/0002-rank-bounded-training-plan-candidates.md`）。想看訓練好的 XGBoost/邏輯迴歸排序器實際運作，啟動後端前設 `PLAN_RANKER_MODE=experimental_ml`，然後打 `GET /training-plan/today`。三位 demo 選手因為負荷畫像不同（衝量/穩定/減量），應該會看到不同的排序分數與 `reason_code`。

---

更完整的功能導覽、目錄結構、後端 API 清單，見 [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)。逐次會話的改動紀錄看 [ERIC_README.md](ERIC_README.md)。
