# 本次會話改動紀錄（交接用）

這份文件整理這整個對話 session 裡對 RunSense 做的所有改動，給接手的人快速掌握「改了什麼、為什麼改、改在哪個檔案」。專案本身的建置步驟請看 [HANDOFF.md](HANDOFF.md)，這份只記錄「這次會話新增/修改的內容」。

---

## 1. 天候等效配速：核心邏輯重新設計（歷經多輪修正的最終版本）

這是本次會話討論最深入的一塊，前後經過好幾輪修正，以下是**目前實際跑在程式裡的最終邏輯**（`backend/app/weather_pace.py`）：

### 1-1. 固定參考時刻，不跟「現在幾點」比
所有「天候等效配速」的比較基準，統一是**傍晚 18:30（`_REFERENCE_RUN_HOUR`）這個固定時刻的氣候常態溫度**，不管你現在幾點跑、看的是「現在」、三個時段預覽、還是課表某一段的預計開始時間，全部跟同一個基準比較，數字才有穩定意義（不會因為中午氣候常態本來就比較熱，就顯示「現在很正常」）。

### 1-2. 相對值 = 兩個絕對值查表相減（不是重新推導曲線）
使用者明確要求：「傍晚溫度對應論文曲線上的點、當前溫度對應的點，看速度相差百分之多少」。

- **舊寫法（已淘汰）**：把「跟傍晚溫度差幾度」套進同一個拋物線形狀重新算一次（等於是把傍晚溫度假設成新的最佳溫度）。這寫法在數學上不等價於「查表相減」，而且有個副作用：**永遠不會是負值**，比常態涼的日子也只會顯示 0%，不會有配速加成。
- **現在的寫法**：`speed_loss_pct(當前溫度) − speed_loss_pct(傍晚常態溫度)`，兩邊都是直接查論文曲線的絕對值點再相減。比常態涼的日子現在會正確顯示負值（配速加成）。

### 1-3. 超出論文量測範圍：邊界切線延伸（不是繼續套二次曲線，也不是打平夾住）
論文 Table S3 只實測到「最佳溫度 ±10°C / +20°C」的範圍。台北、東京這種夏天很熱的城市，傍晚常態溫度常常已經超出這個範圍。

- 如果兩個溫度都超出範圍、都被打平夾住同一個值，相減會變成 0%——即使實際溫差有 5°C。這是使用者抓到的第一個問題。
- 直接放寬範圍讓二次曲線繼續往外延伸也不對：二次曲線離頂點越遠爬升越快，會讓外插區間的數字比論文實測邊界的趨勢還要誇張（使用者抓到的第二個問題：「感覺超過曲線圖的幅度」）。
- **最終做法**：超出量測邊界後，不繼續套二次曲線本身，而是用「邊界那一點當下的斜率」直線往外延伸。這是比較保守、也比較站得住腳的外插方式——既不會歸零、也不會讓外插區間自己加速暴衝。

### 1-4. 改用論文 P1（競賽型）曲線，不是 Median（中位數）曲線
原本用的是論文 Table S3 的 Median 層級資料，使用者希望「以田徑運動員角度」再保守一點。實際去抓了論文正文跟 Supplementary Table S3 的原始檔案（不是憑印象），重新擬合了男女 P1 層級各 7 個實測點：

- 男生新最佳溫度 3.75°C（原 Median 是 6.15°C），女生 9.83°C（原 Median 是 6.67°C）。
- **這不是一個「精英選手都比較耐熱」的單一故事**：論文正文自己講「不論實力，溫度影響幅度差不多」。男生 P1 曲線確實比 Median 平緩很多（peak+20°C 時 6.00% vs 17.73%，約 1/3 陡度），但**女生 P1 曲線在論文數據裡反而比 Median 稍陡一點**（13.47% vs 12.43%）。使用者選擇男女都改用 P1，保持一致性，不是因為兩性都變保守。

### 1-5. 前端連帶修正
公式改成可以輸出負值後，順手抓到並修掉了兩個前端 bug：
- 「氣候配速影響」跟每段課表的天候提示文字原本寫死「+{pct}%」，數字變負的時候會顯示成沒意義的「+-9.8%」。改成依正負號顯示「+X% 配速損失」或「X% 配速加成」。
- 教練指派課表的每段配速換算（`applyWeatherToSegmentPace`）原本只在 `pct > 0` 才調整，負值（該有的配速加成）會被直接忽略不套用。

**主要檔案**：`backend/app/weather_pace.py`、`backend/app/schemas.py`（欄位註解）、`backend/tests/test_weather_pace.py`、`backend/tests/test_weather_route.py`、`web/src/screens/athlete/DashboardScreen.tsx`、`web/src/lib/paceCalc.ts`

---

## 2. Garmin 歷史資料匯入（東京選手）

使用者提供了自己的 Garmin Connect 資料匯出檔，要求匯入成東京選手（`runner.tokyo@runsense.demo`）的訓練歷史。

**匯入流程**（`backend/scripts/`，皆為冪等腳本）：
1. `import_garmin_activities.py` — 匯入 545 筆活動的時長、RPE。
2. `backfill_rest_days.py` — 沒有活動紀錄的日子補標記為「已確認休息日」。
3. `backfill_garmin_structure.py` — 用配速/心率把每筆活動的計圈分類成熱身/間歇/收操區段，每一趟自己的配速都有保留（`pacesPerRep`），不是只存平均值。
4. `backfill_garmin_metrics.py` — 補心率、步頻、步幅、爬升/下降、卡路里、訓練效果等裝置指標。

**過程中抓到並修正的 2 個 Garmin 單位換算陷阱**：
- `avgRunCadence` 其實是真實步頻的一半，要用 `avgDoubleCadence` 才對（用「配速 = 步頻 × 步幅 ÷ 60」反推驗證過）。
- `calories` 欄位單位其實是**千焦耳不是大卡**（跟逐圈能量加總逐位元組比對完全一致），已除以 4.184 轉換，否則熱量會虛高 4.2 倍。

**資料庫改動**：`completed_activities` 新增 `structure`、`distance_km`、`device_metrics`（migration `0017`、`0018`）。

---

## 3. 選手端補齊教練同款的課表區塊編輯器

「手動補登」（`/app/log`）跟教練排課表一樣，可以加熱身/間歇/收操區塊，方便選手補記沒即時記錄到的訓練細節。

**主要檔案**：`web/src/screens/athlete/LogWorkoutScreen.tsx`（重用教練端 `workoutBuilder.tsx` 元件）

---

## 4. 歷史紀錄頁面詳細化 + 移除手動新增的舊資料

每筆歷史紀錄可以點擊展開，顯示日期時間、心率、步頻、爬升、卡路里、訓練效果，以及該次訓練的區段結構（可再展開看每一趟自己的配速）。依使用者要求，把先前手動新增（非 Garmin 匯入、非教練指派）的歷史紀錄全部清掉過一次。

**主要檔案**：`web/src/screens/athlete/HistoryScreen.tsx`（`ActivityDetailPanel`）

---

## 5. 演算法自動課表建議：距離／目標配速顯示空白的問題

**問題**：今日課表卡片的「預計距離」「目標配速」永遠顯示 `—`，即使課表區塊本身已經有足夠資訊可以算出來——`recommendation_engine.py` 裡這兩個欄位在四種課表分支裡全部寫死 `None`。

**修法**：新增 `_total_distance_km`（把每段距離加總，沒有明講距離、只有時長的段落用「時長 ÷ 配速區間中點」反推）跟 `_work_segment_pace_sec_per_km`（抓「主課表」那段自己的配速中點，不跟熱身/收操混在一起做加權平均）。

> ⚠️ **重要細節**：`daily_guidance_cache` 表會把「今天」的課表建議快取住，改完 `recommendation_engine.py` 不會讓已經算過的今天課表自動更新，要驗證改動記得先清這張表對應的列。

**主要檔案**：`backend/app/recommendation_engine.py`、`backend/tests/test_recommendation_engine.py`

---

## 6. 「訓練結構」卡片：補上每段預估時間 + 每段天候等效配速

熱身/收操因為只有距離、沒有明確時長欄位，原本完全不顯示時間；且每段只顯示原始建議配速，沒有換算成「今天天氣下」的等效配速。改成沒有明確時長的段落用「距離 ÷ 該段配速中點」推算預估時間（加「≈」標示），並用當天的天候相對值即時換算每段自己的天候等效配速。

**主要檔案**：`web/src/components/workoutStructure.tsx`、`DashboardScreen.tsx`

---

## 7. 「出發開跑！」即時跑步監控：配速改成會自然起伏

原本自動模式的「即時配速」是寫死顯示設定的目標配速，完全不會變動；距離也是假設全程都精準壓在目標配速去算。改成用一條決定性（同樣經過秒數永遠算出同樣結果，方便測試/重播）的配速曲線模擬：開跑前 2~3 分鐘還沒進入節奏的漸進段，加上幾層不同週期的正弦波動。距離、即時配速、每公里分段現在都是從同一條曲線逐秒數值積分算出來的，彼此不會兜不起來。畫面上新增偏離目標配速的秒數標示跟配速走勢 sparkline。

**主要檔案**：`web/src/lib/runTimer.ts`、`web/src/state/LiveRunContext.tsx`、`web/src/screens/athlete/LiveRunScreen.tsx`

---

## 8. 教練「團隊總覽」：移除誤導性的假異動紀錄

「近期異動」卡片永遠顯示同一個人「蔡承翰 5天前離開團隊」，不管登入哪個教練、團隊實際成員是誰都一樣——這是前端寫死的示範資料，從沒跟著「是否連接真實後端」切換過，而且後端根本沒有「最近誰離隊」這個功能可以查（`assignments.py` 的設計是「已離隊」跟「從未加入」刻意查不出差別，避免資料外洩）。改成只在示範模式才顯示這張卡片當示意，連接真實後端時完全不顯示。

**主要檔案**：`web/src/screens/coach/TeamOverviewScreen.tsx`

---

## 9. 歷程回顧：新增刪除功能（軟刪除）

使用者要求手動輸入跟 Garmin 匯入的紀錄都要能刪除。實作時發現資料庫執行期權限（`runsense_runtime` 角色）從一開始建表就**刻意沒有授權 DELETE**——`completed_activities` 被設計成不可竄改的稽核紀錄，migration 0001 的註解明講這是故意的。

**改法：軟刪除**，不改動這個既有設計原則：
- 新增 migration `0019`，`completed_activities` 加一個 `deleted_at` 欄位（原本用 `UPDATE` 就能做，不需要 DELETE 權限）。
- 新增 `DELETE /activities/{id}` API，實際上是把 `deleted_at` 設成現在時間，之後重新計算體能負荷。
- 一併修正了 4 個原本沒過濾已刪除紀錄的地方，否則刪除會「看起來刪了但其實還在算」：歷程列表查詢、體能負荷計算（`training_load_store.py`）、教練看到的選手「最近訓練」日期（`teams.py`）、休息日衝突檢查（`training_load.py`——刪除活動後，那天要能重新標記為休息日）。
- 前端每一列（不分來源）都加了垃圾桶圖示的刪除按鈕，點擊跳確認視窗，講清楚「會從歷程與負荷計算中移除，且無法復原」。

**主要檔案**：`backend/migrations/versions/0019_soft_delete_completed_activities.py`、`backend/app/routes/activities.py`、`backend/app/routes/teams.py`、`backend/app/routes/training_load.py`、`backend/app/training_load_store.py`、`backend/app/errors.py`、`backend/app/main.py`、`web/src/data/apiClient.ts`、`web/src/state/WorkspaceContext.tsx`、`web/src/screens/athlete/HistoryScreen.tsx`

---

## 10. 過程中順便抓到並修掉的既有 bug

這些不是使用者主動回報的，是驗證上面功能時自己發現、順手修掉的：

| Bug | 檔案 | 問題 |
| :--- | :--- | :--- |
| 補登區塊按鈕誤觸表單送出 | `LogWorkoutScreen.tsx` | `<Button>` 在 `<form>` 裡預設 `type="submit"`，點「+熱身」等按鈕會直接送出整張表單。已補 `type="button"`。 |
| 手動補登送出必定 422 失敗 | `WorkspaceContext.tsx` | `logActivity` 把畫面用的假 ID 當成 `clientMutationId` 送給後端，不是合法 UUID，連上真實後端一定被拒絕。已改用 `crypto.randomUUID()`。 |
| 示範假資料混進真實模式 | `WorkspaceContext.tsx` | 不管有沒有連真實後端，`activities` 狀態一開始都會被示範資料的假活動污染。已改成依 `apiConfigured` 決定要不要帶入示範資料。 |
| 天候正負號顯示錯誤 | `DashboardScreen.tsx` | 見第 1-5 節。 |
| 教練配速調整吃掉負值 | `paceCalc.ts` | 見第 1-5 節。 |
| 記圈計時顯示浮點數亂碼 | `runTimer.ts` | 「本圈已經過」曾顯示 `00:1.9000000000000004`，因為記圈時間戳沒有跟其他地方一樣 `Math.floor` 取整數秒。見第 15 節。 |
| 分圈紀錄心率空白 | `lapSynthesis.ts` | 間歇課表前後夾雜獨立恢復慢跑段落時，那幾段心率沒有被任何規則覆蓋到，顯示空白「—」。見第 17 節。 |

---

## 11. 天氣卡片精簡 + 自訂 hover tooltip 元件

- 隱藏三段原本一直顯示的輔助說明文字（對比論文絕對最佳溫度、依今日建議配速換算、依氣候常態＋日出日落換算）：改成 JSX 註解保留在原始碼裡，不渲染。
- 原生 `title` 屬性 tooltip 在深色主題下顯得突兀（白底文字框、滑鼠移過去會先閃一下「?」游標再彈出），改寫成 `.info-tip`/`.info-tip-icon`/`.info-tip-bubble` 這組可重用的自訂 CSS hover 元件，套用 `--surface`/`--border`/`--shadow-md` 等既有 design token，視覺跟既有的 `.chart-tooltip` 一致。
- 「比傍晚常態溫度...+X°C」這行原本永遠顯示，改成掛在氣溫數字本身的動態 hover tooltip（文案吃即時溫度數字算，不是寫死）。
- Bug 修正：`.info-tip-bubble` 一開始用 `left:50%` 置中，當觸發元素貼近卡片左邊緣（例如窄螢幕 2 欄版面裡的氣溫 StatTile）時會被卡片的 `overflow:hidden` 切掉。改成 `left:0` 只往右長，不會再被切。

**主要檔案**：`web/src/screens/athlete/DashboardScreen.tsx`、`web/src/styles/components.css`

---

## 12. 「即時配速」提示文字換行問題（真正原因是雙重 padding）

- 使用者回報「出發開跑」頁面「即時模擬配速，會依目標配速自然起伏」這行字在某些寬度會換行斷得很醜。
- 一開始只縮小字級沒有完全解決，用 Playwright 掃過 1042–1280px 找到真正會斷行的區間是 1090–1250px（`.grid-3` 從 2 欄變 3 欄後，每欄剛好變窄的臨界帶）。
- 深入查 DOM 發現真正原因：3 張 HUD 卡片（距離／即時配速／即時心率）裡 `.card-body` 自己有 22px padding，`StatTile` 自己也有 22px padding，兩層疊加在窄欄位裡硬生生吃掉 88px 寬度。改用 `Card` 元件既有的 `flush` prop 拿掉外層那層重複的 padding，同時把字級微調到 11.5px 當保險。
- 確認過極窄寬度（240px）時原本設計好的自動換行能力沒有被誤鎖住，是真的沒地方擺才會換行。

**主要檔案**：`web/src/screens/athlete/LiveRunScreen.tsx`、`web/src/styles/components.css`

---

## 13. 出發開跑：新增「比賽模式」

開跑前可以額外輸入比賽距離跟目標完賽時間，開跑後即時顯示「照目前平均配速推算的完賽時間」以及跟目標配速差多少秒。純數學推算獨立於既有的自動/手動距離追蹤模式之外，不管用哪種模式量測距離，比賽模式都直接讀取當下已經算出來的 `distanceKm`/`elapsedSec`。

**主要檔案**：`web/src/lib/runTimer.ts`（`raceModeEnabled`/`raceDistanceKm`/`raceTargetFinishSec`/`calculateRaceProjection`）、`web/src/state/LiveRunContext.tsx`、`web/src/screens/athlete/LiveRunScreen.tsx`

---

## 14. 「今日課表」系統建議 vs 教練指派：修 bug + 新增獨立切換

**問題**：截圖顯示上面卡片寫「系統建議／輕鬆有氧跑」，下面訓練結構卻是間歇課表——`demoData.ts` 的示範資料本身兜不起來（`workoutType` 跟 `segments` 對不上）。順便發現 `guidanceStatus`/`refetchGuidance` 這組後端擷取狀態早就寫好了卻完全沒被用到，導致今日課表 API 失敗時畫面會靜默掉回一份內容自相矛盾的示範資料，使用者完全看不出來現在是在看真資料還是壞掉的假資料。

**修法**（使用者確認過方向才動工）：
- 修正示範資料，讓「輕鬆有氧跑」的 `segments` 真的是熱身慢跑→輕鬆有氧跑→收操慢跑，不是間歇結構。
- 把原本閒置的 `guidanceStatus`/`loadingPlan`/`planError` 狀態接上畫面，用跟 `HistoryScreen`/`TeamOverviewScreen` 一致的 Notice + 重試按鈕樣式呈現載入中／錯誤。
- 新增選手可以自己選「系統建議」或「教練安排」兩種課表來源（`preferences.trainingSource`，純前端記憶體狀態，重新整理要求重新登入的既有安全模型下不需要持久化）——這是使用者額外要求的：教練排了課表、系統又同時顯示自己的建議，選手會搞不清楚要練哪個，所以兩者要能獨立切換、互不干擾。

**主要檔案**：`web/src/data/demoData.ts`、`web/src/screens/athlete/DashboardScreen.tsx`、`web/src/state/WorkspaceContext.tsx`（新增 `trainingSource` preference）

---

## 15. Garmin 錶款風格「記圈」功能

- 開跑頁面比照 Garmin 手錶加上手動記圈：跑步中一顆醒目的「記圈」按鈕，按一次記一圈；即時顯示記圈表格（圈數／距離／分段配速／分段時間）跟本圈已經過秒數；結束訓練的摘要畫面同樣有一張記圈表格。
- 存檔時把記圈資料轉換成既有的 `WorkoutAssignmentSegment`（`kind:"interval"`、`distancesMeters`/`pacesPerRep`）結構——這個結構原本是為了 Garmin 逐趟匯入設計的，重用它讓「歷史紀錄」點開就能直接顯示每一圈的秒數/配速/距離，完全不用改後端或 `HistoryScreen.tsx` 的顯示邏輯。

**主要檔案**：`web/src/lib/runTimer.ts`（`LapMark`/`Lap`/`recordLap`/`calculateLaps`）、`web/src/state/LiveRunContext.tsx`、`web/src/screens/athlete/LiveRunScreen.tsx`

---

## 16. 移除「匯入 Garmin CSV」功能

使用者要求拿掉。這個畫面其實只會在瀏覽器本地端解析 CSV 給你預覽用的表格，從來沒有真的寫回訓練歷程（沒接後端），是個半成品功能，直接整支刪除沒有殘留依賴：拿掉「歷程回顧」頁的按鈕、`/app/import` 路由，`GarminCsvImportScreen.tsx` 整個檔案刪除。

**主要檔案**：`web/src/App.tsx`、`web/src/screens/athlete/HistoryScreen.tsx`（刪除 `GarminCsvImportScreen.tsx`）

---

## 17. 歷史紀錄新增「分圈紀錄」：沒有真實逐圈資料的舊紀錄，依課表結構推算生成

使用者截圖的 Garmin 匯入紀錄只有整段的「慢跑 8.06km」，沒有逐公里分圈。要求「沒有紀錄的話幫我根據課表結構生成像真正跑的分圈數據」，每圈要有配速、時間、平均心率、最高心率。

**設計**：
- 新增 `web/src/lib/lapSynthesis.ts`：優先重用課表結構裡「真的有」的資料（間歇區塊自己的 `distancesMeters`/`pacesPerRep`，包含上一節記圈功能存的真實記圈資料），只補生從沒被記錄過的部分（例如連續慢跑段自動切成每公里一圈，模擬手錶的自動分圈）。
- 心率完全是推算的（這個 App 從來沒有任何路徑收集過「每一圈」層級的心率）：慢跑型課表心率低到中、隨圈數緩慢爬升；間歇型課表每一組衝高峰、休息心率部分回落、下一組接著再往上爬（模擬恢復不完全的疲勞堆積），最後一趟的最高心率會精確對到這筆紀錄本身記錄的最大心率。
- 用活動 ID 當種子做決定性亂數（`web/src/lib/random.ts`，從 `demoData.ts` 抽出來共用），同一筆紀錄每次展開都是同樣的數字，不會重新整理就跳來跳去。
- 用 Playwright 掃過帳號裡全部 100 筆歷史紀錄裡 93 筆有分圈資料的紀錄，抓到並修好一個 bug：間歇課表如果在間歇前後夾了獨立的恢復慢跑段落，那兩段的心率一開始會是空白——已修好（gap-fill 內插），複測全部 93 筆都不再有空白。

**主要檔案**：`web/src/lib/lapSynthesis.ts`（新增）、`web/src/lib/random.ts`（新增，從 `demoData.ts` 抽出共用）、`web/src/screens/athlete/HistoryScreen.tsx`

---

## 18. Dashboard 新增「每日跑量與配速」圖表 + 兩張圖表都可自訂日期區間

使用者要求在既有的「每日負荷趨勢」旁邊，再加一張跟它風格一致的「每日跑量／平均配速」圖表，而且兩張圖表都要能自己選日期區間（預設近 28 天）。

- 新增 `DailyDistancePaceChart`（長條=距離，折線=平均配速，右側獨立座標軸），沒有跑步的日子用跟原圖一致的空心圈標記。
- 新增可重用的 `DateRangePicker` 元件（`web/src/components/ui.tsx`），兩張圖表個別擁有自己的日期區間狀態，最寬可以拉到 366 天，超過預設範圍會出現「重設為近 28 天」。
- **刻意不動**上方「近 7 天負荷／28 天基準負荷／短長期負荷比／有效觀測天數」這四張卡片：那是規格書明訂死的固定 28 天正式演算法數字，圖表的日期區間只是純視覺瀏覽功能，兩者資料來源特意分開（新增 `dailyLoadPointsForRange`/`dailyDistancePointsForRange`，不動原本 `computeTrainingLoad` 的固定視窗邏輯），已用 Playwright 驗證拉動圖表日期不會連動改掉那四張卡片的數字。
- 使用者事後回報配速折線太亂（每天都畫一個點、一條折線橫跨整張圖很雜），改成配速線預設完全不畫，只有滑鼠移到某一天的長條上時才畫出那一天的配速圓點（跟既有的 hover tooltip 共用同一組互動狀態），畫面乾淨很多。

**主要檔案**：`web/src/lib/trainingLoad.ts`（新增 `dailyLoadPointsForRange`/`dailyDistancePointsForRange`/`DailyRunPoint`）、`web/src/components/charts.tsx`（新增 `DailyDistancePaceChart`）、`web/src/components/ui.tsx`（新增 `DateRangePicker`）、`web/src/screens/athlete/DashboardScreen.tsx`

---

## 19. 移除「休息日」功能：沒紀錄就是沒跑

使用者要求整個拿掉休息日概念，不要再區分「已確認休息日」跟「單純沒紀錄」。

**範圍決定**：這個功能其實橫跨前後端（真的有 `PUT /rest-days/{date}` API、`athlete_rest_days` 資料表、一整批後端測試），跟使用者確認過後選擇**只拿掉前端**——後端 API/資料表原封不動保留，只是前端不會再呼叫。

- 拿掉「標記為休息日／復原」按鈕（Dashboard）、「今天沒有訓練？」可標記休息日的卡片（手動補登頁）。
- 圖表（每日負荷趨勢／每日跑量與配速／深度分析頁）沒紀錄的日子統一只用一種空心圈標記，不再區分兩種語意。
- `observationDays` 計算改成只算「有實際訓練紀錄」的天數（原本是 `hasActivity || restConfirmed`）。
- 拿掉 `confirmRestDay`、`RestDay` 型別、`setRestDay` API 呼叫、`confirmedRestDatesThisSession` 這些前端狀態機制；示範資料集把原本 5 個「休息日」改成真的輕鬆跑紀錄，讓 28 天觀測天數維持在門檻之上；一併更新了 `CONTEXT.md`、`web/README.md` 裡過時的休息日說明。

**主要檔案**：`web/src/lib/trainingLoad.ts`、`web/src/lib/liveTrainingLoad.ts`、`web/src/lib/types.ts`、`web/src/data/apiClient.ts`、`web/src/data/demoData.ts`、`web/src/state/WorkspaceContext.tsx`、`web/src/components/charts.tsx`、`web/src/screens/athlete/DashboardScreen.tsx`、`LogWorkoutScreen.tsx`、`TrainingLoadScreen.tsx`、`settings/PrivacySettings.tsx`

---

## 20. 倫敦選手：補上跟東京選手同量級的假 Garmin 資料，刪掉手動資料

使用者要求倫敦選手（`runner.london@runsense.demo`）也要有跟東京選手差不多數量的假 Garmin 訓練資料，但實力要更強一點，並且把倫敦選手原本手動新增的資料刪掉。

- 新增 `backend/scripts/seed_synthetic_garmin_history.py`：仿照東京選手真實 Garmin 匯入資料的規模（536 筆、跨度約 19.5 個月），生成 **483 筆**假 Garmin 活動，時間範圍對齊東京選手的匯入區間（2025/01/15–2026/08/27），內含恢復跑／輕鬆跑／節奏跑／間歇／長跑週期化訓練排程（每 4 週安排一次減量週），平均約每週 5.7 天訓練。
- 「實力更強」：輕鬆跑配速 4:20–4:55/km（東京選手真實資料約 5:11–5:42/km），節奏跑 3:50–4:05/km，間歇 3:20–3:42/km，同配速心率相對更低、RPE 也設定更低，模擬訓練效率更好的選手。
- 資料庫層面直接寫入 `completed_activities`（`provider='garmin'`，含 `distance_km`/`device_metrics`/`structure`），寫完呼叫既有的 `recompute_training_load` 重算最近 28 天的體能負荷。
- 把倫敦選手原本 8 筆 `provider='manual'` 的示範資料**硬刪除**（不是軟刪除）——這幾支管理腳本本來就是連 `postgres` 這個有 `DELETE` 權限、會略過 RLS 的帳號在跑，跟 `completed_activities` 本身「執行期角色不給 DELETE」的既有設計並不衝突。

**主要檔案**：`backend/scripts/seed_synthetic_garmin_history.py`（新增）

---

## 21. 已知限制 / 建議後續注意事項

- **`daily_guidance_cache` 快取**：任何會影響「今日課表建議」內容的後端改動，記得清快取才看得到效果（見第 5 節）。
- **前端目前沒有自動化測試**（找不到任何 `*.test.*` 檔案），這次驗證都是用 Playwright 手動跑過畫面截圖 + `tsc --noEmit` + `oxlint` 確認，沒有回歸測試保護。
- **P1 曲線的女生數據不是「更保守」**：見第 1-4 節，只是為了跟男生保持同一層級一致，如果日後想針對女生單獨調整，數字上是有空間的。
- **軟刪除只擋住了目前已知的 4 個讀取點**：如果之後新增其他直接查 `completed_activities` 的 SQL，記得也要加 `deleted_at IS NULL`，否則已刪除的紀錄會悄悄滲回某個畫面或計算。
- **Garmin 資料來源**：東京選手是真實個人 Garmin 匯出資料（`import_garmin_activities.py` 等三支腳本），倫敦選手是全部用腳本生成的假資料（`seed_synthetic_garmin_history.py`，見第 20 節）——兩邊資料的「真實性」不一樣，錄影/展示時如果要強調「這是真實資料」要注意分清楚是哪個帳號。
- **休息日功能只拿掉前端**（見第 19 節）：後端 `PUT /rest-days/{date}` API 跟 `athlete_rest_days` 資料表都還在，只是前端不會再呼叫；如果之後要徹底清乾淨（含資料庫），要另外處理 migration、後端路由、既有測試。
- **「分圈紀錄」的心率一律是推算的**（見第 17 節）：包括看起來像「真的」逐圈資料的間歇課表，心率都不是裝置實測值，只是配速/距離部分在有真實 `pacesPerRep` 時才是真的。
- **`trainingSource`（系統建議／教練安排）選擇跟 Race Mode 都只存在瀏覽器記憶體**，重新整理或重新登入會重置，符合這個 App「重整需要重新登入」的既有安全模型，但 demo 時如果中途重整頁面，選擇會跳回預設值。

---

## 22. 圖表 hover 文字框：改成跟著滑鼠、貼齊真實視窗邊緣

第 11 節做的是第一版（CSS-only hover、`left:0` 避免被卡片左邊裁切）。這次是更徹底的重寫：

- 文字框從卡片內部的 `position: absolute` 改成整個網頁層級的 `position: fixed`，位置直接讀 `event.clientX/clientY`（滑鼠在瀏覽器視窗裡的實際座標，不是卡片內的相對座標）。
- 判斷「要不要翻到滑鼠另一側」的依據，改成跟**真實瀏覽器視窗邊緣**比較（`window.innerWidth`/`innerHeight`），不是跟卡片自己的邊緣比較——原本的問題是：卡片在版面偏左，滑鼠移到卡片右側時，明明頁面右邊還有大把空間，文字框卻誤判成「快超出邊界」而提前翻到左邊。
- 預設出現在滑鼠右下方，只有在真的會超出視窗右緣/下緣時才分別翻成左側/上方。
- 背景透明度從 92% 一路調整到最終的 74%（`color-mix(in srgb, var(--surface) 74%, transparent)`），保留 8px 模糊（`backdrop-filter: blur`），維持文字可讀性但底下的圖表看得更清楚。

**主要檔案**：`web/src/components/charts.tsx`、`web/src/styles/charts.css`

---

## 23. 教練點課表日期看選手當天實際訓練紀錄 + 東京選手資料補到今天

教練在「課表指派紀錄」畫面看到某天課表，但沒辦法直接看選手那天實際跑了什麼——只能自己切去選手詳情頁面對照日期找。新增後端路由 `GET /teams/{team_id}/athletes/{athlete_id}/activities?local_date=YYYY-MM-DD`（重用 `activities.py` 既有的列序化邏輯），前端點擊指派紀錄的日期列即可展開，顯示跟選手自己「歷程回顧」同一份 `ActivityDetailPanel`（距離、配速、心率、課表結構、分圈）；沒有對應紀錄、尚未到那天、或選手未授權 `activity_summary` 時，分別顯示對應的空狀態或遮罩訊息。

順便把 `HistoryScreen.tsx` 原本寫死在檔案內部的 `ActivityDetailPanel` 抽成共用元件 `web/src/components/activityDetail.tsx`，教練端跟選手端共用同一套渲染邏輯，不是各寫一份。

另外用一支新的冪等腳本 `backend/scripts/seed_tokyo_recent_activities.py` 把東京選手真實 Garmin 匯入資料（到 8/22 為止）跟今天之間的空檔補上兩筆貼近真實課表配速/時長的訓練紀錄，讓這個新功能有實際資料可以展示，不是空畫面。

**主要檔案**：`backend/app/routes/teams.py`、`backend/tests/test_teams_roster.py`、`backend/scripts/seed_tokyo_recent_activities.py`（新增）、`web/src/components/activityDetail.tsx`（新增）、`web/src/screens/coach/AthleteDetailScreen.tsx`、`web/src/screens/athlete/HistoryScreen.tsx`、`web/src/data/apiClient.ts`、`web/src/state/WorkspaceContext.tsx`

---

## 24. 全站 UI 文案稽核：拿掉洩漏內部實作/開發用語的文字

使用者發現「負荷趨勢」卡片副標寫著「兩條線都是同一個 y 軸、同一個單位，沒有第二座標軸」這種明顯是講給開發者聽、不是講給使用者聽的話，要求把整個網站掃過一遍，找出所有類似的問題。判斷標準是使用者給的一句話：**「如果這個作品可以拿去賣當產品，這句話留不留得住」**。逐檔案盤點後分成「直接刪除」跟「簡化成使用者看得懂的說法」兩類動手，沒有用到原本規劃的 ⓘ 圖示做法（因為每一項都能乾脆地歸類成這兩種之一）。

拿掉/簡化的內容包括：
- **裸露的內部欄位名/事件代碼**：`session_load`、`garmin_epoc`、`acute_load`/`chronic_load`（連圖表圖例都寫死英文欄位名）、`timezone_snapshot`、`CROSS_TENANT_DENIED`、`head_coach`、`severity_band`、`X-Line-Retry-Key`、`GARMIN_ACTIVITY_SYNC_ENABLED` 等，全部換成人看得懂的中/英文標籤。
- **開發/QA 驗證用的操作說明**：教練選手詳情頁底部一整塊教怎麼用瀏覽器網址列改參數驗證 RLS 是否生效的 Notice，整段刪除。
- **不存在的功能**：`IntegrationSettings.tsx` 裡整段 Webhook 事件處理機制說明（`provider`/`event_id`/`received_at`/`body_hash`/UNIQUE constraint）、Connect IQ App／Garmin Training API 的「Phase 2 才會有的功能」規劃卡片，都刪除。
- **規格書/開發階段用語**：「Phase 1」「MVP」「對應規格書中的一條需求」「讓評審看到」這類字眼，全部換成一般使用者看得懂的敘述或直接刪除。
- **隱私設定頁**（`PrivacySettings.tsx`）：資料保留期限表格從 7 列砍到 4 列（拿掉 `webhook_metadata`、webhook 原始封包、訂閱與付款紀錄——這些功能整個 App 裡根本不存在），剩下的資料表名稱全部換成人話標籤；拿掉「此版本目前只存在展示狀態」「此頁不是法律意見」這類法遵免責聲明式文字。
- **後續使用者看過畫面後又要求更進一步簡化**：`IntegrationSettings.tsx` 整個 Garmin OAuth 審核流程包裝（Notice + 卡片標題/副標/「尚未開放」標籤 + 一大段審核流程說明文字）整段刪除，只留下真的有作用的「納入裝置資料」預覽開關本身；`TrainingLoadScreen.tsx` 的「觀測天數怎麼算」「為什麼只顯示數字，不顯示燈號」兩張說明卡片直接整張刪除。

**主要檔案**：`web/src/components/charts.tsx`、`web/src/lib/format.ts`、`web/src/screens/athlete/{TrainingLoadScreen,HistoryScreen,LiveRunScreen,LogWorkoutScreen,TeamScreen,BodyStatusScreen,DashboardScreen}.tsx`、`web/src/screens/athlete/settings/{IntegrationSettings,PrivacySettings,ProfileSettings,SecuritySettings,SettingsLayout}.tsx`、`web/src/screens/coach/{AssignmentsScreen,AthleteDetailScreen}.tsx`

---

## 25. 比賽情境文案清理：拿掉會暴露「這是推算/模擬」的字眼

使用者說明：這個作品要拿去參加競賽展示，但受限於時間只能用模擬/推算出來的資料呈現即時跑步數據，這件事**不能被看出來**。於是把畫面上所有會透露「這其實是算出來的、不是裝置實測」的措辭都改掉或刪除，開關本身的功能完全不動，只改文字：

- 「出發開跑！」頁「即時模擬配速，會依目標配速自然起伏」整句刪除。
- 存檔時自動寫入的訓練備註，原本寫「自動模式，設定配速 X /km **推算**距離、步頻與心率」，拿掉「自動模式」「推算」字眼。
- 模式切換開關原本標題是「**自動推算**距離、步頻與心率」、說明寫「依目標配速**自動計算**」，改成「即時追蹤距離、步頻與心率」/「依你的配速即時更新」。
- 「目標配速」卡片說明「距離、步頻與心率都依這個配速即時**計算**」，改成「即時更新」。
- 「訓練結構」卡片裡熱身/收操這類沒有明確時長的段落，原本會用「距離 ÷ 配速」自動推算出一個「≈6:00」的估計時間並顯示——這個「≈」本身就是「這是猜的」的訊號，整段估算邏輯拿掉，這類段落現在只顯示距離跟配速範圍，不再顯示推算出來的時間。
- 「教練洞見」旁邊原本有一行灰字「由 系統預設 審核之安全建議庫」，講的是這段激勵文字其實是從一個預先審核過的文案庫裡選出來的、不是真人教練寫的——整行刪除（連帶清掉變成無用的 `displayedReviewer` 變數跟對應文案 key）。
- 後續使用者要求更進一步：直接把「模式」整張卡片（含開關本身）刪除，畫面上不再有任何切換自動/手動的入口，底層邏輯預設值本來就是即時追蹤模式，功能沒受影響；「比賽模式」卡片標題跟底下重複的「開啟比賽模式」開關合併成一列，不再顯示兩次同樣的字。

**主要檔案**：`web/src/screens/athlete/LiveRunScreen.tsx`、`web/src/screens/athlete/DashboardScreen.tsx`、`web/src/components/workoutStructure.tsx`

---

## 26. 文字框（info-tip）系統重構：全部改成跟圖表 tooltip 同一套定位邏輯

上面兩節把不少常駐可見的說明文字改成滑鼠移過去才顯示的 ⓘ 圖示（沿用第 11 節建立的 `.info-tip` 樣式）。但很快發現這批 ⓘ 文字框跟第 11 節之前的圖表 tooltip 有同樣的舊問題：`position: absolute` 會被卡片自己的 `overflow: hidden` 裁切掉一截。

**重構做法**：
- 新增共用模組 `web/src/lib/tooltipPosition.ts`，把第 22 節圖表 tooltip 用的「翻轉邏輯」（`tooltipTransform`）抽出來，圖表 tooltip 跟 ⓘ 文字框現在共用同一份定位演算法，不再各寫一套。
- `InfoTip` 元件（`web/src/components/ui.tsx`）改寫成滑鼠移入時抓圖示自己在畫面上的 `getBoundingClientRect()`，用 `position: fixed` + 該演算法動態算出文字框位置，只在顯示時才掛進 DOM（不是「一直存在但用 CSS 藏起來」）。也支援用 `children` 換掉預設圖示，改用其他元素（例如氣溫數字本身）當觸發點。
- 文字框寬度從 220px 依實際內容長度陸續調整到 260px、300px，讓較長的說明文字剛好落在兩行，不會擠成三行。
- `StatTile`／`Field`／`Card` 的 `label`/`title` 參數型別放寬成可以塞 `ReactNode`（原本只能傳純文字），`SwitchRow` 新增 `hint`（灰字說明改走 ⓘ）跟 `large`（標題字級比照卡片標題）兩個參數，方便把 ⓘ 圖示直接放在標題文字右邊，而不是另外一行。
- 全站目前用到這組文字框的地方（首頁 4 格負荷卡片、氣溫數字、調整後配速、出發開跑頁的模式/比賽模式說明、手動補登「新增課表段落」、身體感知「自述內容」、體能與疲勞「資料如何計算」）全部套用新版本。

**主要檔案**：`web/src/lib/tooltipPosition.ts`（新增）、`web/src/components/{ui.tsx,charts.tsx}`、`web/src/styles/components.css`、`web/src/screens/athlete/{DashboardScreen,LiveRunScreen,LogWorkoutScreen,BodyStatusScreen,TrainingLoadScreen}.tsx`

---

## 27. 版面收斂微調（比賽模式／資料如何計算／欄位對齊）

延續第 25、26 節的整理，順手修掉幾個一起冒出來的版面小問題：

- 「開啟比賽模式」展開後，「比賽距離（公里）」跟「目標完賽時間（時:分:秒）」兩個欄位標籤沒有對齊在同一條水平線上——根因是外層 `.row` 預設 `align-items: center`，「比賽距離」欄位下面多了一排預設距離按鈕、整體變高，就把旁邊比較矮的欄位往下擠。改成 `alignItems: "flex-start"`，兩欄標籤現在頂部對齊。
- 「資料如何計算」卡片原本收合時卡片內部會有一截明顯的空白（`card-body` 的固定 padding 包住一個空的 `<div>`），展開後又會同時出現卡片標題底線＋內部手動加的分隔線＋卡片 footer 頂線，總共疊出三條分隔線。改成跟「開啟比賽模式」一樣的版型：拿掉 Card 自己的 `title`/`subtitle`/`footer`，卡片內第一行自己排「標題＋按鈕」，收合時完全無空白，展開時只有一條分隔線。
- 「開啟比賽模式」原本文字大小跟其他開關列一樣小（13.5px），使用者要求比照「填寫訓練日誌」卡片標題的大小/字重（16px、字重 700）——`SwitchRow` 新增的 `large` 參數即為此而加。

**主要檔案**：`web/src/screens/athlete/LiveRunScreen.tsx`、`web/src/screens/athlete/TrainingLoadScreen.tsx`、`web/src/components/ui.tsx`、`web/src/styles/components.css`

---

## 28. 首頁「系統建議／教練安排」切換鈕：位置固定，不再跳來跳去

切換按鈕原本跟「今日課表」徽章、課表名稱文字、來源標籤擠在同一個左側群組裡，而這個群組的內容長度會隨模式改變（只有「系統建議」模式才會多顯示課表名稱文字），導致同一行裡的切換按鈕跟著左右移位，每次切換都閃一下位置不同的畫面。改成把切換按鈕獨立移到最右側、天氣資訊移到它左邊，兩種模式間切換時按鈕位置完全固定不動。

**主要檔案**：`web/src/screens/athlete/DashboardScreen.tsx`

---

## 29. 換頁自動捲動回頂部

原本從左側選單切換頁面（例如「手動補登」切到「出發開跑！」）不會自動回到頁面頂部，會停留在上一頁的捲動位置——因為真正在捲動的是 `.content` 這個帶 `overflow-y: auto` 的容器，不是整個瀏覽器視窗，React Router 換路由不會自動處理這種容器的捲動位置。

在 `AppShell.tsx` 加了一段邏輯，監聽路由 `pathname` 變化，換頁時把 `.content` 的捲動位置重置回頂部。第一版用 `useEffect` 會在畫面已經畫出來之後才執行，使用者會先看到一瞬間舊的捲動畫面才跳回頂部；改成 `useLayoutEffect`（在瀏覽器真正繪製畫面前、DOM 更新完就同步執行）解決了這個閃爍問題。

**主要檔案**：`web/src/app/AppShell.tsx`

---

## 30. Git 遠端倉庫整併（非程式碼異動，但影響交接）

發現本機這份專案最初被推到我自己新建的 `ericsung0428/runsense`，但團隊真正共用的 repo 是 `Alan52254/runsense`，兩邊 commit 歷史完全沒有共同祖先。取得使用者明確授權後，**force-push** 把這份完整專案覆蓋到 `Alan52254/runsense` 的 `main`，覆蓋前已先把該 repo 原本的 `main` 備份到同一個遠端的 `backup-before-eric-overwrite` 分支（沒有遺失任何東西，只是不在預設分支上了）。目前 `origin`（`ericsung0428/runsense`）與 `shared`（`Alan52254/runsense`）兩個遠端維持同步，這次 session 之後的所有 commit 都同時推送到兩邊。

> ⚠️ 如果 Alan 那邊本機還有舊的 `Alan52254/runsense` clone，需要 `git fetch` + `git reset --hard origin/main` 才能跟新的歷史同步（直接 `git pull` 會因為歷史不共祖先而衝突）。

---

## 31. 上一輪（第 1–21 節）改動觸及的檔案清單

**後端**：
- `backend/app/weather_pace.py`、`backend/app/schemas.py`
- `backend/app/recommendation_engine.py`
- `backend/app/routes/activities.py`、`routes/settings.py`、`routes/teams.py`、`routes/training_load.py`
- `backend/app/training_load_store.py`、`backend/app/errors.py`、`backend/app/main.py`、`backend/app/fingerprint.py`
- `backend/scripts/import_garmin_activities.py`、`backfill_rest_days.py`、`backfill_garmin_structure.py`、`backfill_garmin_metrics.py`
- `backend/scripts/seed_synthetic_garmin_history.py`（新增，第 20 節）
- `backend/migrations/versions/0017_add_activity_structure.py`、`0018_add_activity_distance_and_device_metrics.py`、`0019_soft_delete_completed_activities.py`
- `backend/tests/test_recommendation_engine.py`、`test_weather_pace.py`、`test_weather_route.py`、`test_activities_delete.py`（新增）

**前端**：
- `web/src/App.tsx`（第 16 節：移除 CSV 匯入路由）
- `web/src/components/workoutStructure.tsx`、`workoutBuilder.tsx`、`charts.tsx`（新增 `DailyDistancePaceChart`）、`ui.tsx`（新增 `DateRangePicker`）
- `web/src/screens/athlete/DashboardScreen.tsx`、`LogWorkoutScreen.tsx`、`HistoryScreen.tsx`、`LiveRunScreen.tsx`、`TrainingLoadScreen.tsx`
- `web/src/screens/athlete/GarminCsvImportScreen.tsx`（第 16 節：整檔刪除）
- `web/src/screens/athlete/settings/PrivacySettings.tsx`
- `web/src/screens/coach/TeamOverviewScreen.tsx`
- `web/src/state/WorkspaceContext.tsx`、`LiveRunContext.tsx`
- `web/src/lib/paceCalc.ts`、`runTimer.ts`、`types.ts`、`trainingLoad.ts`、`liveTrainingLoad.ts`
- `web/src/lib/lapSynthesis.ts`（新增，第 17 節）、`random.ts`（新增，第 17 節）
- `web/src/data/apiClient.ts`、`demoData.ts`
- `web/src/styles/components.css`、`charts.css`
- `CONTEXT.md`、`web/README.md`（第 19 節：更新過時的休息日說明）

---

## 32. 這一輪（第 22–29 節，第 30 節為 git 操作無程式碼異動）改動觸及的檔案清單

**後端**：
- `backend/app/routes/teams.py`（第 23 節：新增選手當日活動查詢路由）
- `backend/tests/test_teams_roster.py`（新增測試）
- `backend/scripts/seed_tokyo_recent_activities.py`（新增，第 23 節）

**前端**：
- `web/src/components/charts.tsx`（第 22、24 節：tooltip 重寫 + 拿掉裸露欄位名）
- `web/src/components/ui.tsx`（第 26、27 節：`InfoTip`、`SwitchRow`、`Field`、`StatTile`、`Card` 調整）
- `web/src/components/activityDetail.tsx`（新增，第 23 節，從 `HistoryScreen.tsx` 抽出）
- `web/src/components/workoutStructure.tsx`（第 25 節：拿掉推算時間顯示）
- `web/src/lib/tooltipPosition.ts`（新增，第 26 節）
- `web/src/lib/format.ts`（第 24 節）
- `web/src/app/AppShell.tsx`（第 29 節：換頁捲動回頂部）
- `web/src/screens/athlete/DashboardScreen.tsx`（第 24、25、28 節）
- `web/src/screens/athlete/LiveRunScreen.tsx`（第 25、27 節）
- `web/src/screens/athlete/TrainingLoadScreen.tsx`（第 22、24、27 節）
- `web/src/screens/athlete/{HistoryScreen,LogWorkoutScreen,TeamScreen,BodyStatusScreen}.tsx`（第 23、24、26 節）
- `web/src/screens/athlete/settings/{IntegrationSettings,PrivacySettings,ProfileSettings,SecuritySettings,SettingsLayout}.tsx`（第 24 節）
- `web/src/screens/coach/{AthleteDetailScreen,AssignmentsScreen}.tsx`（第 23、24 節）
- `web/src/data/apiClient.ts`、`web/src/state/WorkspaceContext.tsx`（第 23 節）
- `web/src/styles/components.css`（第 26、27 節）

**其他**：
- `ERIC_README.md`（本檔案，第 22–32 節新增）
- `PROJECT_OVERVIEW.md`（新增，完整架構與功能總覽）
