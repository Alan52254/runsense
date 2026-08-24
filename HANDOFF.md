# RunSense 系統交接與開發上手指南 (HANDOFF.md)

歡迎接手 RunSense 專案！本文件旨在提供系統架構導覽、本地資料庫與前後端啟動指引、測試帳密與介面操作說明。

---

## 🛠️ 1. 本地環境與資料庫安裝

### 前端 (Web App - React 19 + Vite)
```bash
cd web
npm install
npm run dev   # 開啟 http://localhost:5173
```

### 後端 (FastAPI & Database)
```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
python scripts/seed_demo_personas.py   # 執行資料庫初始化與 Demo 帳號植入
uvicorn app.main:app --reload --port 8000
```

### 客戶端離線同步單元測試
```bash
cd client
npm test   # 執行 16 個單元測試 (SQLite 離線寫入、冪等性、重試機制)
```

---

## 🔑 2. 內建示範帳號與密碼 (Demo Credentials)

| 角色 (Role) | 姓名 (Name) | 城市與時區 (Location / TZ) | 登入 Email | 密碼 (Password) | 說明 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **教練 (Coach)** | **Coach Chen** | 臺北 (`Asia/Taipei` UTC+8) | `coach@example.com` | `password123` | 具備隊伍管理、課表排程、MFA 權限 |
| **選手 (Athlete)** | **Lin Mei-Ling** | 臺北 (`Asia/Taipei` UTC+8) | `meiling@example.com` | `password123` | 臺北長跑訓練隊主力選手 |
| **選手 (Athlete)** | **Kenji Sato** | 東京 (`Asia/Tokyo` UTC+9) | `kenji@example.com` | `password123` | 東京移地訓練選手 |
| **選手 (Athlete)** | **Emma Watson** | 倫敦 (`Europe/London` BST) | `emma@example.com` | `password123` | 倫敦馬拉松備賽選手 |

> 💡 **MFA 安全驗證碼**：在切換至教練視角或高風險操作時，請輸入 6 位數驗證碼 **`424242`**（支援鍵盤連續自動跳格與一鍵貼上）。

---

## 📱 3. 系統介面與功能特色導覽

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

## 📋 4. 協作開發待辦清單 (Roadmap & Next Steps)

請接手的夥伴依以下清單接續推進：

### 🎯 Phase 1B: Garmin Cloud 整合 (Feature-Gated)
- [ ] 取得 Garmin Developer Program 審核通過。
- [ ] 實作 Garmin Activity API Webhook Adapter（依 `garmin_epoc` 單位解析 session_load）。
- [ ] 啟用 `GARMIN_ACTIVITY_SYNC_ENABLED` Feature Flag。

### 🎯 Phase 1C: LINE Bot 與推播冪等排程
- [ ] 依 SRS v3.1 `REQ-SCHED-003` 實作 LINE Push Message API 的 `X-Line-Retry-Key` 冪等衍生機制。
- [ ] 每日早晨 06:00 依當地時區推播今日課表與天候提醒。

### 🎯 Phase 2: Mobile Native App (Capacitor / React Native)
- [ ] 將 `web/` 前端封裝為 iOS / Android 原生 App。
- [ ] 串接 OS 安全儲存區 (iOS Keychain / Android Keystore) 存放 Refresh Token。
- [ ] 串接手機本機藍牙 BLE 心率帶與運動手錶廣播協定。
