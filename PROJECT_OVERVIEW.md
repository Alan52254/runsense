# RunSense 專案總覽

這份文件完整介紹 RunSense 這個作品的技術架構、目錄結構、核心設計原則，以及目前實作完成的**所有功能**（選手端 + 教練端）。跟 [ERIC_README.md](ERIC_README.md)（逐次會話的「改了什麼」流水帳）不同，這份是「現在長什麼樣子」的橫向總覽，寫給第一次接觸這個專案、需要快速建立完整心智模型的人看。

---

## 一、專案是什麼

RunSense 是一個「選手主導資料所有權」的跑步訓練與體能負荷管理平台。核心設計理念：

- **選手擁有自己的訓練資料**，教練不是預設能看到全部，而是每一項資料類別都要選手個別授權（`Consent Scope`），選手隨時可以撤銷，撤銷後教練幾乎立即失去存取權限。
- **教練看到的畫面不是資料庫副本**，而是每次查詢當下，依「目前是否還在這個團隊」+「目前授權了哪些範圍」動態組出來的投影（`Coach Roster Row`）。
- **數字只呈現可驗證的原始數據，不做風險燈號判斷**（不會把負荷比值直接對應到「安全／注意／危險」），把最終訓練判斷留給選手跟教練自己。
- **AI 只做「選一句話」的工作，不做任何數值計算**：訓練處方是純規則引擎算出來的固定值，LLM 唯一能做的事是從一份人工預先審核過的文案白名單裡挑一則搭配的語氣文字，選手個資與 GPS 位置絕不會傳給它。

---

## 二、技術架構

### 前端（`web/`）
- **React 19 + TypeScript + Vite**，路由用 `react-router-dom`（`BrowserRouter`）。
- **沒有外部 UI 套件或 CSS 框架**：所有元件（`Card`、`Button`、`Field`、`Switch`、`StatTile`、`Modal`……）都是手刻的 presentational primitive，統一放在 `web/src/components/ui.tsx`；純手寫 CSS（`web/src/styles/*.css`），走設計 token（`--surface`、`--border`、`--accent` 等 CSS 變數）支援亮/暗主題切換。
- **沒有外部狀態管理套件**：全部用 React Context（`web/src/state/`）—— `AuthContext`（登入/身分/MFA）、`WorkspaceContext`（選手所有資料的讀寫入口，含離線同步佇列）、`LiveRunContext`（跑步中的計時器狀態機）、`LocaleContext`（中/英文切換）、`ToastContext`。
- **圖表是手刻 SVG**，不是圖表套件（`web/src/components/charts.tsx`）：長條圖、雙折線圖、hover tooltip 全部手寫，統一走同一套 `position: fixed` + 動態視窗邊緣翻轉的定位邏輯（`web/src/lib/tooltipPosition.ts`），確保 tooltip 不會被卡片自己的 `overflow: hidden` 裁切。
- **`apiConfigured`（`web/src/data/apiClient.ts`）決定連真後端還是走內建示範資料**（`web/src/data/demoData.ts`）——沒設定後端網址時，整個前端仍然可以完整跑起來，用假資料展示所有功能。

### 後端（`backend/`）
- **FastAPI + SQLAlchemy Core（不是 ORM，直接寫參數化 SQL）+ PostgreSQL 16**，資料庫版本控管用 **Alembic**（`backend/migrations/versions/`，目前到 `0019`）。
- **每一張表都是 Row-Level Security（RLS）`ENABLE` + `FORCE`**，這是整個後端安全模型的核心：
  - 一般選手自有資料表（`completed_activities`、`training_load_daily`、`injury_reports`……）預設策略是 `athlete_id = actor`，只有自己能讀寫自己的資料。
  - 教練要讀選手資料時，**後端絕對不會把「要查的選手 id」設成資料庫層的身分**——驗證過的教練身分（`app.actor_user_id`）在整個交易期間維持不變，目標選手 id 永遠只是一個查詢參數。RLS policy 用 `SECURITY DEFINER` 的成員關係判斷函式（例如 `app_actor_can_read_athlete`）在資料庫層面即時重新檢查「這個教練現在還是不是這個團隊的有效教練」+「這個選手現在有沒有授權這個範圍」，兩者缺一都查不到資料。
  - 這個身分是用 `SET LOCAL`（`set_config(..., true)`）在**交易範圍內**設定，不是連線層級或連線池層級的設定，避免身分在連線重用時外洩到別的請求。
- **Demo-only 認證機制**：`COMPETITION_DEMO_ONLY=true` 時才會註冊 `/auth/demo-login`，缺少 `DEMO_JWT_SECRET` 會直接拒絕啟動（避免展示用的弱驗證機制不小心跑到正式環境）。這條路徑沒有 refresh rotation、rate limiting、鎖定機制，純粹是為了展示準備的簡化流程。
- **天候等效配速引擎**（`app/weather_pace.py`）：依 El Helou et al. (2012, PLOS ONE) 論文的男女 P1（競賽型）曲線，把「傍晚 18:30 常態溫度」跟「當前溫度」各自查表得到的速度損失百分比相減，得出「今天比平常熱/涼多少 %」；超出論文實測範圍的部分用邊界斜率線性外插，不繼續套二次曲線本身（避免外插區間數字暴衝）。
- **推薦引擎**（`app/recommendation_engine.py`）：完全確定性的規則表，依選手自己的 7/28 天負荷比與資料完整度決定今天的建議課表，不含任何 LLM 呼叫。
- **語氣層**（`app/llm_client.py`）：可選用本地 Ollama 模型，但輸出被嚴格限制成只能回傳白名單裡 5 個 `tone_variant_id` 之一；任何不符合這個形狀的回應會被整個丟棄，退回固定的 `NEUTRAL_FALLBACK` 文案。Ollama 沒啟動時完全不影響其他功能，`GET /guidance/today` 一樣回 200。
- **每個選手每天只算一次今日課表**（`daily_guidance_cache`），同一天重複呼叫直接回快取結果。

### `client/`：獨立的離線同步套件（尚未接上任何 UI）
一個獨立的 npm 套件，提供 `LocalActivityStore`（Node 內建 `node:sqlite` 本地持久化）跟 `SyncCoordinator`（離線優先同步協調器，含冪等重試）。這是為未來的原生 App（React Native）預先準備的儲存/同步引擎，目前**沒有被 `web/` 呼叫**，也沒有自己的 UI，只有一份完整的單元測試（`npm test`，`node --test` 直接跑 `.ts`，不透過打包器）。

### 開發環境啟動
- 一鍵腳本：`.\start-runsense.ps1`（Windows PowerShell）。
- 個別啟動見 [README.md](README.md) 或 [HANDOFF.md](HANDOFF.md)。資料庫用 `backend/docker-compose.yml` 起一個支援 RLS 的 PostgreSQL 16 容器。

---

## 三、目錄結構導覽

```
runsense-main/
├── backend/                  FastAPI 後端
│   ├── app/
│   │   ├── routes/           每支 API 路由（見下方「後端 API 清單」）
│   │   ├── recommendation_engine.py   確定性訓練處方規則表
│   │   ├── weather_pace.py            天候等效配速核心公式
│   │   ├── training_load.py / training_load_store.py   7/28 天負荷計算與落地
│   │   ├── team_authorization.py      教練角色/團隊權限檢查
│   │   ├── db.py                      連線管理 + RLS actor 交易 context manager
│   │   ├── llm_client.py              語氣白名單挑選（不做數值計算）
│   │   └── schemas.py                 Pydantic 請求/回應模型
│   ├── migrations/versions/  Alembic 資料庫版本（0001–0019）
│   ├── scripts/               冪等維運腳本（匯入 Garmin、補資料、示範資料植入）
│   └── tests/                 pytest（含需要真實 Postgres 的整合測試）
├── web/                        React 前端
│   └── src/
│       ├── screens/
│       │   ├── athlete/       選手端 8 個主畫面 + settings 子頁
│       │   └── coach/         教練端 3 個主畫面
│       ├── components/        共用 UI 元件、圖表、課表結構渲染、教練課表編輯器
│       ├── state/              React Context（見上方「前端」）
│       ├── lib/                 純邏輯（配速計算、負荷計算、分圈生成、格式化……）
│       ├── data/                API client + 內建示範資料集
│       └── app/AppShell.tsx    側邊選單、頂部列、路由外殼、換頁捲動重置
├── client/                     獨立離線同步套件（見上方，未接上 UI）
├── CONTEXT.md                  領域名詞字典（Ubiquitous Language）
├── ERIC_README.md              逐次會話改動紀錄（流水帳）
├── PROJECT_OVERVIEW.md         本檔案
└── HANDOFF.md / README.md      建置與快速上手（部分內容已隨功能演進而過時，架構細節以本檔案與程式碼為準）
```

---

## 四、核心概念（精簡版，完整定義見 [CONTEXT.md](CONTEXT.md)）

| 名詞 | 意思 |
| :--- | :--- |
| **Athlete / 選手** | 訓練紀錄跟自述資料的所有權人。 |
| **Completed Activity / 已完成活動** | 選手實際跑過的訓練紀錄（手動輸入或裝置匯入），是唯一的正典來源。 |
| **Assigned Workout / 指派課表** | 教練排給選手、某天該練什麼的「計畫」——跟 Completed Activity（選手實際做了什麼）是兩件不同的事。 |
| **Session Load / 訓練負荷** | 一筆活動的負荷數值，永遠跟它的單位一起解讀，`AU`（手動 duration×RPE）跟 `garmin_epoc`（裝置量測）**永遠不相加、不換算**，分開呈現趨勢。 |
| **Consent Scope / 授權範圍** | 選手把哪一類資料開放給教練看，四種：`activity_summary`（訓練摘要）、`training_load`（負荷趨勢）、`injury_status`（身體狀況摘要）、`injury_detail`（自述原文，獨立授權）。 |
| **Coach Roster Row** | 教練畫面上看到的每一位選手資料，是查詢當下即時組出來的投影，不是儲存的副本。 |
| **Data Quality** | `SUFFICIENT`/`LOW`/`INSUFFICIENT` 三種，純粹描述「資料夠不夠支撐這個數字」，不是風險或表現評級。 |
| **Local Training Date** | 依選手自己時區換算出的「今天」，不是伺服器所在時區。 |

---

## 五、選手端功能完整清單（`/app/*`）

### 1. 今日訓練首頁（`/app`）
- **今日課表 Hero 卡片**：可在「系統建議」（依負荷趨勢自動生成的處方）跟「教練安排」（教練指派的課表）之間切換，兩者互不干擾、各自記憶；顯示預計時長／距離／目標配速／天候等效配速（依當地即時氣溫換算，含配速損失或加成百分比）。
- **課表結構卡片**：熱身／主課表／收操逐段顯示距離、配速範圍、天候等效配速；教練排的間歇課表每一趟自己的配速都獨立顯示。
- **教練洞見**：搭配課表的一句提示文字，可展開看「建議產生方式」說明。
- **4 格體能負荷 HUD**：近 7 天負荷、28 天基準負荷、短長期負荷比、有效觀測天數，數字旁的 ⓘ 圖示提供簡短定義。
- **每日訓練負荷長條圖 + 每日跑量與配速圖**：兩張圖各自可自訂查詢日期區間（預設近 28 天，最長 366 天），跟上面 4 格固定 28 天視窗的正式數字互不影響。
- **天候狀況與配速補償卡片**：即時氣溫、濕度、配速影響百分比，可展開看早/中/晚溫度預估。
- **身體與疲勞狀況快覽**：最新自述狀態摘要，可快速回報。
- **教練指派課表清單**：列出即將到來/已完成/未執行的指派。
- **「出發開跑！」「手動補登」快速入口**。

### 2. 出發開跑！即時跑步監控（`/app/run`）
- 大型計時器 + 距離／即時配速／即時心率／即時步頻／估算消耗即時面板，心率區間（Z1–Z5）視覺化燈條。
- **手動記圈**：仿 Garmin 錶款操作，跑步中按一次記一圈，即時顯示分段配速/時間表格。
- **比賽模式**：可設定比賽距離（含 5K/10K/半馬/全馬快選）與目標完賽時間，開跑後即時顯示「照目前平均配速推算的完賽時間」與跟目標差幾秒。
- 結束訓練後評定 RPE（1–10），存成一筆 Completed Activity，自動計入負荷。
- 支援離線：斷線時本地先寫入，恢復連線後自動同步，畫面上有待同步筆數提示。

### 3. 手動補登（`/app/log`）
- 補登過去或離線完成的訓練：日期、開始時間、時長、距離（選填）、RPE、備註。
- **新增課表段落**：跟教練排課表用同一套區塊編輯器，可依序加熱身／間歇／休息／慢跑／收操，適合回頭補記課表結構。
- 即時預覽計算出的負荷（AU = 時長 × RPE）。
- 側欄「單位說明」解釋 AU（手動）跟 EPOC（裝置）兩種負荷單位不會混算。

### 4. 歷程回顧（`/app/history`）
- 所有歷史訓練清單，含來源標示（手動／Garmin）跟同步狀態。
- 點擊展開單筆詳情：距離、配速、心率、步頻、爬升、卡路里、訓練效果，以及課表結構（可再展開看每一趟自己的配速/時間/心率）。
- 沒有真實逐圈資料的舊紀錄，會依課表結構跟這筆紀錄本身的統計數字，用決定性演算法（同一筆紀錄每次展開結果一致）推算生成看起來合理的分圈明細——心率一律是推算值，只有結構裡本來就有真實 `pacesPerRep` 的部分才是真的。
- 支援刪除（軟刪除，`deleted_at`，非硬刪除，仍保有稽核紀錄；刪除後負荷會自動重算）。

### 5. 體能與疲勞深度分析（`/app/load`）
- 7 天 Acute 與 28 天 Chronic 雙折線趨勢圖，滑鼠移到任一天可看到當天精確數值。
- 每日訓練負荷長條圖（可切換圖表/表格檢視）。
- 「資料如何計算」可展開看 `algorithm_version`／`schema_version`／輸入快照雜湊等技術細節（面向想驗證數字來源的使用者，預設收合）。

### 6. 身體感知（`/app/body`）
- 快速回報當天是否有不適、嚴重程度分級、部位，以及一段自述文字。
- 自述文字跟「有無不適」摘要是**分開授權**的兩個範圍，教練即使看得到摘要也不代表看得到自述原文。
- 顯示「教練現在看得到什麼」——依目前授權範圍即時反映，不是靜態說明。
- 顯示目前所屬團隊/教練，以及過往回報紀錄。

### 7. 跑團與隱私（`/app/team`）
- 待處理的教練邀請（接受/婉拒）。
- 已加入團隊：逐項授權範圍開關（訓練摘要／負荷趨勢／身體狀況摘要／自述原文），每項獨立生效，撤銷後教練幾秒內失去存取權。
- 已離開的團隊紀錄。
- 「資料歸屬」說明：哪些是選手個人資料、哪些是團隊建立的內容（例如課表指派歷史），離隊後各自的去留規則。

### 8. 個人偏好（`/app/settings/*`）
- **個人資料**：姓名、Email、時區、所在城市（用於氣候等效配速，非即時定位）、性別（用於配速估算曲線選擇）、年齡聲明。
- **安全**：登入 session 清單（裝置/位置/最後活動）、可個別登出、團隊擁有者與主教練需要的 MFA 驗證入口。
- **隱私與資料**：資料匯出、更正、刪除帳號的申請入口；資料保留期限一覽表；可個別停用「情緒/語氣建議」「訓練提醒推播」等非必要用途，不影響核心功能。
- **整合與通知**：裝置資料預覽開關（打開後把裝置來源的紀錄跟手動紀錄並列顯示，兩種負荷單位永遠分開，不相加）；LINE 通知連結狀態，可隨時解除。

---

## 六、教練端功能完整清單（`/coach/*`）

進入教練視角需要先通過一次 MFA 驗證（示範用固定驗證碼）。

### 1. 團隊總覽（`/coach`）
- 團隊所有選手名單，逐位顯示依授權範圍投影出來的體能數據：7 天/28 天負荷、短長期負荷比、資料品質、近 14 天負荷走勢 sparkline。
- 沒有授權的欄位不會顯示假資料或零值，而是明確標示「未授權」。

### 2. 選手詳情（`/coach/athletes/:athleteId`）
- 顯示「目前的授權範圍」清單（每次載入都重新檢查，不是快取的舊狀態）。
- 統計卡片、近 14 天負荷趨勢圖。
- 身體狀況摘要 + 自述原文（依各自獨立的授權範圍分別顯示或遮罩）。
- **課表指派紀錄**：每一筆指派可點擊展開，直接顯示選手當天實際跑了什麼（距離/配速/心率/課表結構/分圈）——沒有對應紀錄、還沒到那天、或選手未授權時分別顯示對應的空狀態說明，不會誤導成「選手沒有練」。

### 3. 課表排程（`/coach/assignments`）
- 新增指派：選擇選手、日期、標題、時長、強度標籤，並可用跟選手端同一套區塊編輯器排課表結構（熱身/主課表/收操，含配速範圍與每趟細節）。
- 距離/時長會依課表結構自動即時估算，教練也可以手動覆寫。
- 所有指派列表，最新日期在前。

---

## 七、Demo 帳號

登入頁的角色選擇器會自動帶入以下帳密（來源：`web/src/state/AuthContext.tsx`，與 `backend/scripts/seed_demo_personas.py` 對應）：

| 角色 | Email | 密碼 | 時區 |
| :--- | :--- | :--- | :--- |
| 教練（臺北教練，同時也是選手身分） | `runner.taipei@runsense.demo` | `TaipeiDemo!2026` | Asia/Taipei |
| 選手（東京選手，真實 Garmin 匯入資料） | `runner.tokyo@runsense.demo` | `TokyoDemo!2026` | Asia/Tokyo |
| 選手（倫敦選手，腳本生成的假 Garmin 資料） | `runner.london@runsense.demo` | `LondonDemo!2026` | Europe/London |

切換到教練視角，或執行高風險操作時，MFA 驗證碼固定是 **`424242`**。

---

## 八、後端 API 一覽（依路由檔案分組）

| 檔案 | 端點 |
| :--- | :--- |
| `demo_auth.py` | `POST /auth/demo-login`（僅 `COMPETITION_DEMO_ONLY=true` 時註冊） |
| `activities.py` | `GET/POST /activities`、`DELETE /activities/{id}` |
| `training_load.py` | `PUT /rest-days/{date}`（後端仍存在，前端已不呼叫）、`GET /training-load/trend` |
| `profile.py` | `PATCH /profile` |
| `weather.py` | `GET /weather` |
| `guidance.py` | `GET /guidance/today` |
| `injury_reports.py` | `GET/POST /injury-reports` |
| `me.py` | `GET /me/team-memberships`、`PATCH /me/team-memberships/{team_id}`、`GET /me/consent-grants`、`PATCH /me/consent-grants/{scope}` |
| `teams.py` | `GET /teams/mine`、`GET /teams/{team_id}/roster`、`GET /teams/{team_id}/athletes/{athlete_id}`、`GET /teams/{team_id}/athletes/{athlete_id}/activities` |
| `assignments.py` | `POST/GET /teams/{team_id}/assignments`、`DELETE /teams/{team_id}/assignments/{id}`、`GET /me/assigned-workouts` |
| `settings.py`（prefix `/me/settings`） | `GET/DELETE sessions`、`POST mfa/verify`、`GET privacy/export`、`POST privacy/deletion-request`、`GET integrations/garmin`、`GET audit-log` |

完整的請求/回應範例與每支端點的權限模型，見 [backend/README.md](backend/README.md)。

---

## 九、已知限制

- **`client/` 離線同步套件尚未接上 `web/` 前端**，目前是獨立驗證過的儲存/同步引擎，供未來原生 App 使用。
- **休息日功能只拿掉了前端**：後端 `PUT /rest-days/{date}` API 與資料表仍在，選手端已無入口可以建立休息日紀錄，畫面上不再區分「已確認休息日」跟「單純沒紀錄」。
- **Garmin／LINE 都沒有真正的外部串接**：`GET /me/settings/integrations/garmin` 只讀一個環境變數旗標（預設關閉），前端的「裝置資料預覽」開關是本地示範資料的併入預覽，不是真的 OAuth 連線；LINE 通知的連結狀態同樣是示範資料。
- **「分圈紀錄」心率一律是推算值**：包括看起來像真實逐圈資料的間歇課表，心率都不是裝置實測，只有配速/距離在課表結構裡本來就有真實資料時才是真的。
- **`trainingSource`（系統建議/教練安排選擇）與比賽模式設定只存在瀏覽器記憶體**，重新整理或重新登入會重置。
- **前端目前沒有自動化測試**（找不到 `*.test.*` 檔案），後端 `pytest`/`client/` 的 `node --test` 有完整測試覆蓋，但前端驗證目前仰賴手動走查與 Playwright 截圖，沒有回歸測試保護。
- **`daily_guidance_cache` 快取**：任何會影響「今日課表建議」內容的後端改動，記得清快取才看得到效果。
