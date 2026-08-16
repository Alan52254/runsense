# RunSense 測試規格書 v3.0

**對應文件**：RunSense SRS v3.1（Implementation Freeze Candidate）
**版本異動**：v2.0 的追溯表用 range 表示涵蓋率（如 `REQ-AUTH-001~008 → TC-AUTH-001~003`），這是虛報——三個測試案例不可能自動證明八條需求都被測到。v3.0 改為每一條 REQ 對應明確的單一或多個 TC 編號，沒有測試案例可對應的 REQ 會在追溯表中誠實留白，而不是用 range 掩蓋。

**部署閘門沿用 v2.0**：Release Blocker／Non-Blocker 兩層，S1–S4 為處理時效分類，不是部署閘門。

---

## 一、RLS Actor Model 與 Field-Level Consent 測試（本版新增，對應 SRS 二.二/二.三） `[Release Blocker]`

### TC-RLS-011｜偽造目標選手 ID 不得取得存取權（核心測試，對應 P0-02 修正）
- **對應需求**：REQ-RLS-006
- **前置條件**：Attacker 帳號僅為一般選手，不具備任何教練角色
- **步驟**：Attacker 嘗試在請求中操控代表「目標選手」的參數，將其設為受害者 Y 的 ID（模擬上游授權邏輯若有漏洞的情境）
- **預期結果**：即使該參數被成功操控，RLS 判斷依據的是 `app.actor_user_id`（Attacker 自己），不是被操控的目標參數，查詢結果仍限於 Attacker 自己有權限的資料，不得意外取得 Y 的資料

### TC-RLS-012｜缺少 actor context 時 fail closed
- **步驟**：交易中未設定 `SET LOCAL app.actor_user_id` 即執行查詢（模擬程式碼疏漏）
- **預期結果**：查詢回傳空集合或錯誤，不得預設為「無限制查詢」

### TC-RLS-013｜injury_status consent 無法取得 injury_detail
- **對應需求**：REQ-RLS-007
- **前置條件**：選手僅授權 `injury_status`（has_issue／severity_band），未授權 `injury_detail`
- **步驟**：教練查詢該選手的 `injury_reports`（有權限）與 `injury_report_details`（無權限）
- **預期結果**：前者可查詢到 has_issue／severity_band，後者查詢回傳空集合；驗證即使教練對 `injury_reports` 執行 `SELECT *`，也不會透過任何 join 意外取得 `injury_report_details.free_text`

### TC-RLS-014｜Consent 撤銷與查詢請求的競態
- **對應需求**：REQ-CACHE-AUTH-001
- **步驟**：同時發起「選手撤銷 injury_status consent」與「教練查詢該選手 injury 資料」兩個請求，模擬時間上幾乎同時發生
- **預期結果**：無論何種到達順序，只要撤銷交易已 commit，後續查詢一律拒絕；不存在「查詢請求剛好先讀到快取」而繞過已生效撤銷的情況（驗證 REQ-CACHE-AUTH-001 的處理順序：先授權檢查、後讀快取）

### TC-RLS-010｜RLS 啟用狀態的靜態 CI 檢查
- **對應需求**：REQ-RLS-003
- **步驟**：CI 中查詢 `pg_class.relrowsecurity` 與 `relforcerowsecurity`
- **預期結果**：所有受保護資料表兩者皆為 `true`，缺一則 CI FAIL

（TC-RLS-006~009 沿用 v2.0，測試 owner／BYPASSRLS／連線池殘留／consent 差異情境，內容不變）

---

## 二、LLM 安全測試（本版改為驗證架構隔離，非語意窮舉） `[Release Blocker]`

### TC-AI-STRUCT-001｜Prescription 欄位與 LLM 輸出無關（永久留在 CI，不得視為一次性驗證）
- **對應需求**：REQ-AI-003, REQ-AI-004
- **修正說明**：v2.0 曾寫「code review 確認後可視為永久通過，不必每次重跑」，這是錯誤的測試哲學——重構程式碼可能在無意間打破這個保證，而測試成本極低，沒有理由拿掉。**本測試永久保留於 CI，每次部署前執行。**
- **步驟與預期結果**：沿用 v2.0（Mock LLM 回傳多種違規 empathy_text，驗證 Prescription 區塊不受影響）

### TC-AI-TONE-001｜Phase 1 僅允許白名單 tone_variant_id（本版新增，對應 P0-01 修正）
- **對應需求**：REQ-AI-006
- **步驟**：呼叫 LLM 服務，檢查其回應是否僅包含 `tone_variant_id`，且該值是否落在人工審核過的白名單集合內
- **預期結果**：若回傳值不在白名單內，系統 fallback 為預設模板，不得使用未經審核的 tone_variant_id 對應到不存在的文案

### TC-AI-STRUCT-002｜Schema 違規 fail closed（修正 v2.0 的 silent ignore 設計）
- **對應需求**：REQ-AI-007
- **修正說明**：v2.0 預期「忽略非白名單欄位，其餘部分照樣使用」，本版改為「整包回應視為無效」
- **步驟**：Mock LLM 回傳 `{"tone_variant_id": "SUPPORTIVE_A", "distance_km": 999}`
- **預期結果**：整個回應被判定為 schema 違規，不使用其中任何欄位（包含原本合法的 tone_variant_id），直接 fallback 為固定模板，並記錄一筆異常事件供觀察

### TC-AI-STRUCT-003｜最小化傳送給 LLM 的資料
- 沿用 v2.0（驗證不含姓名、傷病原文、GPS 座標）

### TC-AI-STRUCT-004｜Prompt injection（沿用 v2.0）
### TC-AI-STRUCT-005｜LLM 供應商失效測試（沿用 v2.0）
### TC-AI-COST-001｜AI 成本 DoS（沿用 v2.0）

---

## 三、Training Load 測試（本版新增 Metric/Alert 分離、rest day 修正、hash 可重現性） `[Release Blocker]`

### TC-LOAD-GOLDEN-001~006｜沿用 v2.0（固定輸入輸出、INSUFFICIENT 判定、分母為零、休息日區分、混合 unit 降級、回溯重算）

### TC-LOAD-007｜全部確認休息時 chronic 判定為 INSUFFICIENT（本版新增）
- **對應需求**：REQ-LOAD-005
- **步驟**：28 天內全部為使用者確認的休息日（session_load 全為 0）
- **預期結果**：`data_quality = INSUFFICIENT`（chronic_load 分母雖非數學上的零，但全零負荷無法反映有意義的訓練基準，依 REQ-ALERT-001 前置條件，此情境亦不進入 Metric 顯示）

### TC-LOAD-008｜裝置無活動事件不得推論為休息（核心測試，對應 P0-07 修正）
- **對應需求**：REQ-LOAD-004（修正版）
- **步驟**：某天 Garmin 未同步任何活動事件（無法區分使用者是真的休息、還是沒戴錶/沒同步）
- **預期結果**：該天判定為缺漏資料，不計入 observation_days 分母；此為 v2.0 邏輯的直接反例，v2.0 版本測試在此情境下會錯誤地將其計為休息日

### TC-LOAD-009｜相同數值不同 unit 不得合併計算
- **對應需求**：REQ-LOAD-006
- **步驟**：Garmin 提供 `session_load = 300 (unit=garmin_epoc)`，手動輸入 `session_load = 300 (unit=AU)` 於同一時間窗
- **預期結果**：即使數值相同，因 unit 不同不得直接相加；`data_quality` 降級為 LOW

### TC-LOAD-010｜Canonical hash 可重現性（對應 P1-08 修正）
- **對應需求**：REQ-LOAD-007（修正版）
- **步驟**：以 key 順序不同但語意相同的兩組輸入 JSON（如 `{"a":1,"b":2}` 與 `{"b":2,"a":1}`）分別計算 `input_snapshot_hash`
- **預期結果**：兩者的 hash 值必須相同（驗證 canonical JSON 排序規則生效）

### TC-LOAD-011｜algorithm_version 僅因刻意變更而改變
- **對應需求**：REQ-LOAD-007
- **步驟**：對演算法程式碼做不影響邏輯的重構（如變數重新命名）
- **預期結果**：`algorithm_version` 不應因純重構而改變；只有邏輯本身變更且經 review 確認後才手動遞增版本號

### TC-METRIC-001｜Phase 1 不顯示燈號僅顯示 Trend（對應 P0-05 修正）
- **對應需求**：REQ-METRIC-001
- **步驟**：檢查前端與 API 回應，搜尋是否存在紅/黃/綠燈號相關的欄位或 UI 元件
- **預期結果**：Phase 1 版本不存在任何 alert_state 燈號顯示，僅顯示數值趨勢與 data_quality 標籤

---

## 四、Webhook 與排程測試（本版新增 LINE 官方冪等機制驗證）

### TC-WEBHOOK-LINE-001~003｜沿用 v2.0

### TC-SCHED-003｜LINE 已受理但伺服器當機的崩潰窗口（本版新增，對應 P1-11）
- **對應需求**：REQ-SCHED-003（修正版）
- **步驟**：
  1. 排程任務呼叫 LINE Push Message API 並帶上穩定的 `X-Line-Retry-Key`
  2. 模擬 LINE 已回應受理（200/202），但伺服器在寫入本地「已發送」狀態前 crash
  3. Cron 觸發 retry，同一 `(user_id, job_type, local_date)` 再次觸發，衍生出**相同**的 `X-Line-Retry-Key`
- **預期結果**：LINE 平台對相同 retry key 回傳 `409 Conflict`（"retry key already accepted"），使用者最終只收到一則邏輯上的通知，不因伺服器崩潰重試而重複收到推播

### TC-SCHED-001~002｜沿用 v2.0（內部端點未授權拒絕、部分失敗續跑）

---

## 五、Garmin Feature-Gated 測試（本版新增，對應 P0-04 修正）

### TC-GARMIN-FLAG-001｜Feature flag 關閉時系統不依賴 Garmin
- **對應需求**：REQ-GARMIN-001
- **步驟**：`GARMIN_ACTIVITY_SYNC_ENABLED = false`，執行完整的手動輸入訓練紀錄、Training Load 計算、教練儀表板查詢流程
- **預期結果**：全部功能正常運作，系統任何路徑都不因 Garmin 整合未完成而出現錯誤或功能缺失

### TC-GARMIN-FLAG-002｜Flag 開啟前置條件檢查（部署層級，非執行期測試）
- **對應需求**：REQ-GARMIN-002
- **驗收方式**：人工檢查清單（Developer Program 審核文件、sandbox payload 驗證紀錄、整合契約文件、對應測試案例），非自動化測試案例，於部署前作為 release checklist 一項

---

## 六、Auth 測試（本版展開為 1:1 對應，不再用 range 虛報覆蓋率） `[Release Blocker]`

| REQ 編號 | 測試案例 |
|---|---|
| REQ-AUTH-001 | TC-AUTH-004：未完成 email 驗證的帳號無法存取需驗證後才開放的功能 |
| REQ-AUTH-002 | TC-AUTH-005：連續錯誤登入達門檻後觸發頻率限制（如短暫鎖定或要求驗證碼） |
| REQ-AUTH-003 | TC-AUTH-006：正常 refresh token 使用後立即失效，新 token 可正常使用 |
| REQ-AUTH-004 | TC-AUTH-001（沿用 v2.0）：已失效 token 被重用時，token family 全部撤銷 |
| REQ-AUTH-005 | TC-AUTH-007：使用者可於 session 清單中查看並手動撤銷任一 session |
| REQ-AUTH-006 | TC-AUTH-008：檢查行動端 token 儲存位置（OS 安全儲存區）；TC-AUTH-009：檢查網頁端 cookie 屬性（HttpOnly／SameSite／Secure）與 CSRF token 驗證 |
| REQ-AUTH-007 | TC-AUTH-002（沿用 v2.0，教練帳號 MFA 強制）；TC-AUTH-010：帳號於已登入狀態下被提升為 head_coach，須立即要求補做 MFA 才能繼續操作團隊資料 |
| REQ-AUTH-008 | TC-AUTH-003（沿用 v2.0，高風險操作 step-up 驗證） |

---

## 七、隱私生命週期測試（本版新增，對應 SRS 十一） `[Release Blocker]`

| REQ 編號 | 測試案例 |
|---|---|
| REQ-PRIV-001 | TC-PRIV-001：使用者請求匯出資料，收到涵蓋其 athlete-owned 範圍的完整匯出檔 |
| REQ-PRIV-002 | TC-PRIV-002：使用者請求更正資料，更正後歷史版本保留於 audit trail |
| REQ-PRIV-003 | TC-PRIV-003：使用者請求刪除帳號，依定義的保留期限規則處理，非法規要求保留的資料須實際刪除 |
| REQ-PRIV-004 | TC-PRIV-004：使用者請求停止特定用途處理（如關閉 LLM 情緒建議），對應功能立即停止，其餘功能不受影響 |
| REQ-PRIV-005 | TC-PRIV-005：模擬資料超過保留期限，排程任務正確執行刪除/去識別化 |
| REQ-PRIV-006 | TC-PRIV-006：使用者同意的隱私權政策版本與時間正確記錄，政策更新後需重新取得同意 |

---

## 八、年齡測試（本版補齊邊界案例，對應 P1-10）

### TC-AGE-001｜邊界日期測試
- **對應需求**：REQ-AGE-001
- **測試情境**：
  - 今天恰為 18 歲生日 → 允許註冊
  - 明天才滿 18 歲 → 拒絕註冊
  - 若採用完整 DOB：閏年 2 月 29 日出生者的邊界計算需有明確定義行為
- **前提**：若法律顧問確認自我聲明已足夠，本測試僅需驗證勾選/聲明機制與時間戳記錄是否正確，不需要驗證完整 DOB 邏輯（依 REQ-AGE-001 修正版，DOB 儲存與否由法律顧問決定）

---

## 九、其餘章節（沿用 v2.0，內容不變，僅更新編號對照）

- 資料所有權與跨租戶測試（TC-DATAOWN-001~002）
- 資料去重測試（TC-DEDUP-001~002）
- Offline 同步測試（TC-SYNC-001, TC-SYNC-003，範圍已於 v2.0 修正為排除即時錄跑情境）
- 本地資料安全測試（TC-LOCAL-SEC-001）
- 天氣 Fallback 測試（TC-WEATHER-001~003，v2.0 已移除越權新增的百分比要求）
- Consent 與離隊政策測試（TC-CONSENT-001~004）
- Billing 測試（TC-BILLING-001~003）
- 備份還原測試（TC-BACKUP-001，v2.0 已移除 Phase 1 不存在的 GPS object storage 檢查）
- 效能測試（TC-PERF-001~002，暖/冷快取分離）
- 日誌/Sentry 洩密掃描測試（新增，對應 REQ-AUDIT-002：自動掃描 log 與 Sentry event 內容，確認不含密碼、token、傷病原文、LLM 原始輸入輸出）

---

## 十、追溯總表覆蓋率自我檢查

本版追溯表原則：**每一條 REQ 編號要嘛有明確對應的 TC 編號，要嘛在下表中誠實列為「尚無自動化測試，僅人工檢查清單」，不得用 range 語法製造已覆蓋的假象。**

| REQ 編號 | 對應測試 | 覆蓋方式 |
|---|---|---|
| REQ-SCOPE-001, REQ-WEATHER-LOCATION-001 | 沿用 v2.0 TC-SYNC-001 範圍修正 | 自動化測試 |
| REQ-DATAOWN-001, REQ-AUTHZ-001 | TC-DATAOWN-001~002 | 自動化測試 |
| REQ-RLS-001~002 | TC-RLS-006~007 | 自動化測試（CI 靜態檢查） |
| REQ-RLS-003 | TC-RLS-010 | 自動化測試（CI 靜態檢查） |
| REQ-RLS-004 | TC-RLS-008 | 自動化測試（併發模擬） |
| REQ-RLS-005 | TC-RLS-009 | 自動化測試 |
| REQ-RLS-006 | TC-RLS-011~012 | 自動化測試 |
| REQ-RLS-007 | TC-RLS-013 | 自動化測試 |
| REQ-CACHE-AUTH-001 | TC-RLS-014 | 自動化測試（時序模擬） |
| REQ-AUTH-001~008 | 見六、Auth 測試對照表逐條列出 | 自動化測試（逐條 1:1） |
| REQ-CONSENT-001~004 | TC-CONSENT-001~004 | 自動化測試 |
| REQ-LOAD-001~008 | TC-LOAD-GOLDEN-001~006, TC-LOAD-007~011 | 自動化測試 |
| REQ-METRIC-001 | TC-METRIC-001 | 自動化測試 |
| REQ-ALERT-001~003 | 無測試案例 | **尚無實作，功能未核准前不適用** |
| REQ-AI-003~007 | TC-AI-STRUCT-001~005, TC-AI-TONE-001, TC-AI-COST-001 | 自動化測試 |
| REQ-WEBHOOK-PROVIDER-001, REQ-WEBHOOK-003 | TC-WEBHOOK-LINE-001~003, TC-WEBHOOK-RACE-001 | 自動化測試 |
| REQ-DEDUP-001~002 | TC-DEDUP-001~002 | 自動化測試 |
| REQ-SYNC-001~003 | TC-SYNC-001, TC-SYNC-003 | 自動化測試 |
| REQ-LOCAL-SEC-001~003 | TC-LOCAL-SEC-001 | 自動化測試（僅涵蓋帳號隔離，token 儲存見 REQ-AUTH-006） |
| REQ-SCHED-002~003 | TC-SCHED-001~003 | 自動化測試 |
| REQ-GARMIN-001~002 | TC-GARMIN-FLAG-001~002 | TC-GARMIN-FLAG-002 為人工檢查清單，非自動化 |
| REQ-GARMIN-003 | 無測試案例 | **架構驗證（spike），非可執行測試** |
| REQ-PRIV-001~006 | TC-PRIV-001~006 | 自動化測試 |
| REQ-TZ-001 | 沿用 v2.0 TC-TZ-001 | 自動化測試 |
| REQ-AGE-001~002 | TC-AGE-001 | 自動化測試（REQ-AGE-002 為 Phase 2 範疇，暫無測試） |
| REQ-ERROR-001 | 隱含於所有 API 測試的錯誤碼斷言 | 分散於各功能測試中，非獨立測試案例 |
| REQ-AUDIT-001 | 隱含於各安全測試（consent 撤銷、跨租戶拒絕等）的 audit_log 斷言 | 分散驗證 |
| REQ-AUDIT-002 | 日誌洩密掃描測試（九、新增） | 自動化測試 |

**誠實留白項目**：REQ-ALERT-001~003（功能尚未核准，不適用）、REQ-GARMIN-003（屬架構驗證非執行期測試）。這兩項留白不代表遺漏，而是這些需求本身現階段就不該有可執行的測試案例——這正是 v2.0「有 REQ 就該有對應測試」原則的正確應用：功能還沒定案前，寫測試案例反而是測試規格搶先幫產品做決策。
