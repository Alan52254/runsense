# RunSense 系統交接與全方位開發指南 (HANDOFF.md)

歡迎加入 RunSense 專案！本文件提供零門檻、Step-by-Step 的系統建置指引。無論是 Docker 資料庫、後端 FastAPI、前端 React 19，或是需要申請的外部 API Key 與系統操作流程，均詳載於此。

---

## 🛠️ 1. 一鍵環境建置 (Full Stack Setup)

### 步驟 A：Docker 資料庫啟動 (PostgreSQL 16)
專案已內建 `docker-compose.yml`（包含支援 Row Level Security 的 PostgreSQL 16）：
```bash
# 進入後端目錄並啟動 PostgreSQL 容器
cd backend
docker compose up -d

# 檢查容器狀態（確保 5432 埠口正常監聽）
docker compose ps
```

### 步驟 B：後端 Python 環境與資料庫遷移
```bash
# 1. 建立並啟用 Python 虛擬環境 (建議 Python >= 3.11)
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 2. 安裝後端相依套件
pip install -r requirements.txt

# 3. 設定環境變數（可參考下方 API Key 說明）
cp .env.example .env

# 4. 執行 Alembic 資料庫版本遷移 (建表與 RLS 政策)
alembic upgrade head

# 5. 植入示範帳號與測試資料 (Demo Personas & Seed Data)
python scripts/seed_demo_personas.py

# 6. 啟動 FastAPI 後端服務
uvicorn app.main:app --reload --port 8000
```
後端 Swagger 介面：`http://localhost:8000/docs`

### 步驟 C：前端 Web App 啟動 (React 19 + Vite)
```bash
cd web
npm install
npm run dev
```
前端開發伺服器：`http://localhost:5173`

### 步驟 D：客戶端離線同步套件單元測試
```bash
cd client
npm install
npm test   # 執行 16 個 SQLite 本地持久化與同步佇列單元測試
```

---

## 🔑 2. 外部 API Key 與環境變數申請清單

請於 `backend/.env` 中配置以下金鑰（未配置時系統將自動 Fallback 至安全預設模式，不影響核心開發）：

| 服務項目 | 環境變數名稱 | 申請管道與說明 | 預設 / Fallback 行為 |
| :--- | :--- | :--- | :--- |
| **氣象配速引擎** | `OPENWEATHER_API_KEY` | 前往 [OpenWeatherMap](https://openweathermap.org/api) 申請免費 API Key，用於獲取選手所在城市之氣溫與濕度。 | 未填寫時天候狀態顯示 `UNAVAILABLE`，不影響手動訓練。 |
| **本地 AI 建議模型** | `OLLAMA_BASE_URL`<br>`OLLAMA_MODEL` | 本地安裝 [Ollama](https://ollama.com/) 並執行 `ollama pull llama3.2:3b` 與 `ollama serve`。 | 未啟動時自動退回固定白名單模板 `NEUTRAL_FALLBACK`。 |
| **展示環境 JWT 密鑰** | `DEMO_JWT_SECRET`<br>`COMPETITION_DEMO_ONLY` | 設定一段自訂長字串（如 `runsense-dev-secret-key-2026`），並設 `COMPETITION_DEMO_ONLY=true`。 | 啟用 Demo 帳號快速登入端點。 |
| **Garmin 雲端同步 (Phase 1B)** | `GARMIN_CONSUMER_KEY`<br>`GARMIN_CONSUMER_SECRET` | 需向 [Garmin Developer Program](https://developer.garmin.com/) 申請 Activity API 審核權限。 | Feature Flag `GARMIN_ACTIVITY_SYNC_ENABLED` 預設關閉。 |
| **LINE Bot 推播 (Phase 1C)** | `LINE_CHANNEL_SECRET`<br>`LINE_CHANNEL_ACCESS_TOKEN` | 前往 [LINE Developers Console](https://developers.line.biz/) 建立 Messaging API Channel。 | 用於早晨 06:00 每日訓練推播。 |

---

## 🏃 3. 示範帳號與測試憑證 (Demo Credentials)

前端登入頁已提供一鍵填入功能，各帳號對應不同的身分與時區：

| 角色 (Role) | 姓名 (Name) | 城市與時區 (Location / TZ) | 登入 Email | 密碼 (Password) | 權限與用途 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **教練 (Coach)** | **Coach Chen** | 臺北 (`Asia/Taipei` UTC+8) | `coach@example.com` | `password123` | 跑團管理、課表排程、MFA 驗證 |
| **選手 (Athlete)** | **Lin Mei-Ling** | 臺北 (`Asia/Taipei` UTC+8) | `meiling@example.com` | `password123` | 臺北訓練隊主力選手 |
| **選手 (Athlete)** | **Kenji Sato** | 東京 (`Asia/Tokyo` UTC+9) | `kenji@example.com` | `password123` | 東京移地訓練選手 |
| **選手 (Athlete)** | **Emma Watson** | 倫敦 (`Europe/London` BST) | `emma@example.com` | `password123` | 倫敦馬拉松選手 |

> 🔐 **MFA 驗證碼**：切換教練視角或執行高風險操作時，請輸入 6 位數安全驗證碼 **`424242`**。

---

## 📱 4. 系統介面與功能特色導覽

1. **今日訓練基地 (`/app`)**：
   - **今日課表 Hero Card**：包含預計時長、目標距離、基準配速與**天候等效配速補償 (+8s/km)**。
   - **教練洞見 (Coach Insight)**：安全白名單激勵語境，點擊可展開查看演算法與隱私說明。
   - **快速行動**：一鍵「出發開跑！」、「手動補登」與「今日休息日標記」。
   - **體能與疲勞 4-Metric HUD**：7 天短期負荷 (Acute)、28 天每週基準 (Chronic)、短長期比 (Ratio)、有效觀測天數 (Observations)。
   - **28 天每日負荷圖**：每日運動量條狀圖，清晰區隔訓練日、已確認休息日與缺漏資料。
2. **出發開跑！即時跑步監控 (`/app/run`)**：
   - **動態運動儀表板 (Live Telemetry HUD)**：超大計時器、即時跑步呼吸燈。
   - **即時科學指標**：累積里程、即時配速、即時步頻 (Cadence, spm)、卡路里消耗 (Calories, kcal)。
   - **心率區間儀表 (HR Zone 1~5)**：5 段視覺化動態燈條。
   - **每公里分段計時 (Kilometer Splits)**：每完成 1.0 km 即時記錄單圈分段時間與配速表。
   - **結束結算**：評定 RPE 自覺強度 (1-10) 後即時寫入本地資料庫並自動同步。
3. **手動補登 (`/app/log`)**：
   - 供選手補登過去未即時開啟 App 記錄的跑步，填寫時長、RPE 與備忘，自動推算 Session Load (AU)。
4. **歷程回顧 (`/app/history`)**：
   - 所有過往跑步清單、多維度篩選（全部、待同步、失敗、疑似重複）、離線佇列狀態監控。
5. **體能與疲勞深度分析 (`/app/load`)**：
   - 7 天 Acute 與 28 天 Chronic 雙折線趨勢圖，完整呈現體能上升與疲勞累積曲線。
6. **身體感知與疲勞回報 (`/app/body`)**：
   - 快速回報身體痠痛部位與嚴重程度等級，提供獨立自述隱私保護。
7. **教練總覽與課表排程 (`/coach`, `/coach/assignments`)**：
   - 教練專屬視角：檢視隊伍選手之即時體能投影矩陣、指派與調整團體/個人課表。

---

## 📋 5. 接續開發待辦清單 (Roadmap & Next Tasks)

請接手的夥伴依以下優先級接續推進：

### 🎯 任務 1: Garmin Cloud 活動串接 (Phase 1B)
- [ ] 申請 Garmin Developer Program 並取得 Sandbox 憑證。
- [ ] 於 `backend/app/routes/webhooks.py` 實作 Garmin Webhook Adapter。
- [ ] 開啟 `GARMIN_ACTIVITY_SYNC_ENABLED=true` 並驗證 `garmin_epoc` 單位之負荷解析。

### 🎯 任務 2: LINE Bot 早晨課表推播 (Phase 1C)
- [ ] 實作 LINE Push Message API 整合，搭配 `X-Line-Retry-Key` 冪等防重送機制。
- [ ] 設定 Celery / Cron 排程，於每日當地時間 06:00 推播今日訓練課表與天候補償。

### 🎯 任務 3: Mobile Native App 打包 (Phase 2)
- [ ] 使用 Capacitor 或 React Native 將 `web/` 打包至 iOS / Android 雙平台。
- [ ] 串接手機本機藍牙 BLE 心率帶與運動手錶廣播協定。
