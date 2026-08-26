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

---

## 11. 已知限制 / 建議後續注意事項

- **`daily_guidance_cache` 快取**：任何會影響「今日課表建議」內容的後端改動，記得清快取才看得到效果（見第 5 節）。
- **前端目前沒有自動化測試**（找不到任何 `*.test.*` 檔案），這次驗證都是用 Playwright 手動跑過畫面截圖 + `tsc --noEmit` + `oxlint` 確認，沒有回歸測試保護。
- **P1 曲線的女生數據不是「更保守」**：見第 1-4 節，只是為了跟男生保持同一層級一致，如果日後想針對女生單獨調整，數字上是有空間的。
- **軟刪除只擋住了目前已知的 4 個讀取點**：如果之後新增其他直接查 `completed_activities` 的 SQL，記得也要加 `deleted_at IS NULL`，否則已刪除的紀錄會悄悄滲回某個畫面或計算。
- Garmin 匯入腳本目前只針對東京選手跑過。

---

## 12. 這次改動觸及的檔案清單

**後端**：
- `backend/app/weather_pace.py`、`backend/app/schemas.py`
- `backend/app/recommendation_engine.py`
- `backend/app/routes/activities.py`、`routes/settings.py`、`routes/teams.py`、`routes/training_load.py`
- `backend/app/training_load_store.py`、`backend/app/errors.py`、`backend/app/main.py`、`backend/app/fingerprint.py`
- `backend/scripts/import_garmin_activities.py`、`backfill_rest_days.py`、`backfill_garmin_structure.py`、`backfill_garmin_metrics.py`
- `backend/migrations/versions/0017_add_activity_structure.py`、`0018_add_activity_distance_and_device_metrics.py`、`0019_soft_delete_completed_activities.py`
- `backend/tests/test_recommendation_engine.py`、`test_weather_pace.py`、`test_weather_route.py`、`test_activities_delete.py`（新增）

**前端**：
- `web/src/components/workoutStructure.tsx`、`workoutBuilder.tsx`
- `web/src/screens/athlete/DashboardScreen.tsx`、`LogWorkoutScreen.tsx`、`HistoryScreen.tsx`、`LiveRunScreen.tsx`
- `web/src/screens/coach/TeamOverviewScreen.tsx`
- `web/src/state/WorkspaceContext.tsx`、`LiveRunContext.tsx`
- `web/src/lib/paceCalc.ts`、`runTimer.ts`、`types.ts`
- `web/src/data/apiClient.ts`、`demoData.ts`
- `web/src/styles/components.css`
