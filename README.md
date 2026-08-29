# RunSense

> **Athlete-First Endurance Training & Physiological Load Intelligence Platform**
> 專為跑者打造的自主訓練數據中心與運動生理負荷智慧平台。

一套整合訓練負荷 (ACWR)、天氣配速補償、安全傷痛分流、實證知識圖譜檢索 (Graph RAG)
與 AI 健康教練的跑步訓練系統。包含：

| 目錄 | 內容 | 技術 |
| --- | --- | --- |
| `backend/` | REST API、訓練負荷計算、課表排序器 (deterministic + 實驗性 ML)、傷痛分流、AI 教練 | FastAPI · PostgreSQL (RLS) · SQLAlchemy · Alembic |
| `web/` | 選手 + 教練網頁介面（**主要前端**） | Vite · React · TypeScript |
| `mobile/` | Expo 行動 App（次要 / 展示用） | Expo · React Native |

---

## 1. 環境需求 (Prerequisites)

- **Python** ≥ 3.11（`py -3.11` on Windows）
- **Node.js** ≥ 20 與 npm
- **Docker Desktop**（用來跑 PostgreSQL 16；也可自備本機 Postgres）
- 選用：OpenWeather API key、Groq API key（啟用即時天氣與 AI 教練）

---

## 2. 一鍵啟動（Windows PowerShell）

在專案根目錄執行：

```powershell
.\start-runsense.ps1
# 若指令碼被封鎖：
powershell -ExecutionPolicy Bypass -File .\start-runsense.ps1
```

指令碼會自動：建立 `backend/.venv` → 安裝後端依賴 → `docker compose up -d` 啟動
Postgres → 跑 migration → 灌 demo 資料 → 安裝並建置前端 → 另開兩個視窗分別跑
後端 (`:8000`) 與前端 (`:5173`)，並開啟瀏覽器。

可帶參數注入金鑰：

```powershell
.\start-runsense.ps1 -OpenWeatherApiKey "xxxx" -DemoJwtSecret "一段夠長的隨機字串"
```

---

## 3. 手動啟動

### 3.1 資料庫

```bash
cd backend
docker compose up -d          # postgres:16，帳密 postgres/postgres，DB=runsense，port 5432
```

### 3.2 後端 API

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate  |  macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env           # 視需要填入金鑰（見第 5 節）
alembic upgrade head           # 建立所有資料表
python scripts/seed_demo_personas.py        # demo 帳號 + 團隊 + 基本活動
python scripts/seed_rich_athlete_history.py # 選用：28 天豐富歷史數據

uvicorn app.main:app --reload --port 8000
```

- API 文件：<http://localhost:8000/docs>
- `app/main.py` 會在非測試環境自動載入 `backend/.env`，金鑰不需另外 export。
- 預設 `DATABASE_URL` 已指向 `postgresql+psycopg://postgres:postgres@localhost:5432/runsense`。

### 3.3 前端 Web

```bash
cd web
npm install
npm run dev                                    # 純 demo 資料模式，http://localhost:5173
# 連真實後端：
VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

不設 `VITE_API_BASE_URL` 時，前端用 `src/data/demoData.ts` 的內建假資料，
每個畫面都能瀏覽而不需後端。

### 3.4 行動 App（選用）

```bash
cd mobile
npm install
npx expo start
# 預設打 http://localhost:8000（Android 模擬器為 http://10.0.2.2:8000）
# 覆寫： EXPO_PUBLIC_API_BASE_URL=http://<你的IP>:8000 npx expo start
```

---

## 4. Demo 登入帳號

需 `COMPETITION_DEMO_ONLY=true`（`.env.example` 已預設）。透過
`POST /auth/demo-login` 或前端登入頁使用：

| 角色 | Email | 密碼 |
| --- | --- | --- |
| 臺北 · 教練 | `runner.taipei@runsense.demo` | `TaipeiDemo!2026` |
| 東京 · 選手 | `runner.tokyo@runsense.demo` | `TokyoDemo!2026` |
| 倫敦 · 選手 | `runner.london@runsense.demo` | `LondonDemo!2026` |

---

## 5. 選用整合（AI 與天氣）

編輯 `backend/.env`：

| 變數 | 說明 |
| --- | --- |
| `OPENWEATHER_API_KEY` | 即時天氣；未設定時對支援城市（Taipei/Tokyo/London）回退到氣候平均值 |
| `GROQ_API_KEY` | 啟用 AI 健康教練聊天 (`/guidance/chat`)、LLM 語氣選擇 |
| `GUIDANCE_PROVIDER` | `static`（預設安全回退）/ `groq` / `gemini` |
| `GEMINI_API_KEY` | 使用 Gemini 作為傷痛指引 provider 時 |
| `PLAN_RANKER_MODE` | `deterministic`（預設，正式）/ `experimental_ml`（載入 `app/ml_models/` 的訓練模型） |

未提供任何金鑰時系統仍可完整運作，只是天氣用氣候平均值、AI 教練回傳固定安全建議。

---

## 6. 測試

```bash
# 後端：不需 DB 的測試直接跑；需 DB 的測試要另一個 TEST_DATABASE_URL（見 backend/README.md）
cd backend && pytest

# 前端
cd web && npm test
```

---

## 7. 常用埠與疑難排解

| 服務 | 埠 |
| --- | --- |
| 後端 API | 8000 |
| 前端 Web | 5173 |
| PostgreSQL | 5432 |

- **前端一直顯示 demo 資料**：確認啟動時有帶 `VITE_API_BASE_URL`。
- **瀏覽器 fetch 全部失敗**：多半是 CORS，檢查 `CORS_ALLOWED_ORIGINS` 是否含前端網址。
- **`alembic upgrade head` 連不上**：確認 `docker compose up -d` 的 Postgres 已 healthy。
- **登入被拒**：確認 `COMPETITION_DEMO_ONLY=true` 且已跑 `seed_demo_personas.py`。

---

## 8. 延伸文件

- [`backend/README.md`](./backend/README.md) — 後端細節、DB 測試設定、demo 身分機制
- [`web/README.md`](./web/README.md) — 前端兩種資料模式與各畫面資料串接
- [`PROJECT_OVERVIEW.md`](./PROJECT_OVERVIEW.md) — 系統整體設計
- [`HANDOFF.md`](./HANDOFF.md) — 交接手冊
