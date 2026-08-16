# RunSense 軟體需求規格書（SRS）v3.1 — Implementation Freeze Candidate

**文件狀態**：本版為完整 standalone 規格書。閱讀本文件不需要參照 v1.0／v2.0／v3.0——所有仍然有效的需求都已合併於此，被取代的需求明確標記 `[RETIRED]` 並指向替代編號。這是回應第三輪紅隊審查「v3.0 不是 standalone 文件」的直接修正。

**本版新修正的四個核心問題**（回應第三輪審查 P0）：
1. LLM 結構隔離解決了「不能改數字」，但沒解決「能不能用語氣鼓勵危險行為」——本版把 Phase 1 的 LLM 權限再降一級。
2. RLS 的安全 context 不小心把「查詢目標」當成「操作者身分」，這是可能被利用的設計錯誤，本版改為 actor model。
3. Row-Level Security 不等於 Field-Level Security，`injury_reports` 拆表處理。
4. Garmin 在 Phase 1 是必要功能，但整合規格還沒完成——本版改為 feature-gated，不讓外部 API 審核進度卡死整個 MVP。

---

## 零、Phase 1 範圍決議

```
REQ-SCOPE-001
Phase 1 選手端的跑步紀錄輸入方式：
  (a) 使用者手動輸入的訓練摘要（Phase 1A，MVP 核心，無外部依賴）
  (b) Garmin API 同步的活動摘要（Phase 1B，見十、Garmin 整合，feature-gated）
Phase 1 不提供手機即時 GPS 錄跑（含背景執行、定位權限），此類功能與
手錶/BLE 功能一併歸屬 Phase 2。

REQ-WEATHER-LOCATION-001
氣候等效配速引擎的地點資料來源為使用者於個人設定手動選擇的城市，
不使用即時定位。
```

---

## 一、資料所有權模型

```
REQ-DATAOWN-001
選手完成的訓練紀錄、訓練負荷、選手自述資料，一律為 athlete-owned
canonical record，不得依團隊複製或掛上 team_id。

REQ-AUTHZ-001
Team 對 athlete-owned 資料的存取權，一律透過「有效成員關係 + 角色權限 +
consent scope」動態授予，不得以資料複製或靜態欄位表示。
```

```
Athlete-owned（無 team_id 欄位）：completed_activities、training_load_daily、
  injury_reports（見二.三拆表）、equipment_shoes、athlete_annotations
Team-owned：assigned_workouts、team_notes、team_configuration、team_subscriptions
User-owned：b2c_subscriptions
```

教練儀表板透過 `team_athlete_projection`（Redis 查詢時投影，非正典複製，見二.四快取授權順序規定）彙總資料。

---

## 二、安全與多租戶模型

### 2.1 RLS 基礎需求

```
REQ-RLS-001   Production 執行期資料庫角色不得是受保護資料表的 owner
REQ-RLS-002   執行期角色不得具備 BYPASSRLS 或 superuser 權限
REQ-RLS-003   受保護資料表須同時 ENABLE 與 FORCE ROW LEVEL SECURITY
REQ-RLS-004   請求身分內容以 transaction-local（SET LOCAL）方式設定，
              不得殘留於連線池中被重複使用的連線
REQ-RLS-005   Athlete-owned 敏感資料的存取政策須即時查詢目前有效的
              consent scope，不使用快取的授權狀態作為判斷依據
```

### 2.2 RLS Context 改為 Actor Model（本版修正，取代 v3.0 錯誤設計）

**問題**：v3.0 的交易範本把「被查詢的目標選手 ID」設為 `app.athlete_id`，若上游任何一個 endpoint 授權邏輯有漏洞，攻擊者只要能操控這個查詢參數，就可能讓 RLS「自己」替攻擊者建立起看似合法的存取 context——這是把「查詢目標」誤當成「操作者憑證」的設計錯誤。

```
REQ-RLS-006（新增，本版核心修正）
RLS 安全 context 必須是已驗證的操作者身分（actor），不得是 API 參數
指定的目標資源身分。API 傳入的 target athlete ID 永遠不得被信任為
授權 context 的一部分。
```

修正後的交易範本：

```sql
BEGIN;
SET LOCAL app.actor_user_id = '登入者的使用者 ID';
SET LOCAL app.team_id = '目前操作情境的 team_id（若適用）';
-- 查詢
COMMIT;
```

RLS policy 的判斷邏輯改為：

```
該筆 row 的 athlete_id = actor 自己
  OR
（actor 在 policy 查詢當下確實是某個 active team member
  AND 具備對應教練角色權限
  AND 該筆 row 的 athlete_id 也是同一 team 的 active member
  AND 該 athlete 目前對相應 scope 的 consent 仍為有效）
```

Actor identity 與 target resource identity 必須在程式碼與資料庫政策中被明確視為兩個不同概念，不得混用同一個變數名稱或欄位表達。

### 2.3 Field-Level Consent：拆表，不是靠 RLS 塗黑欄位

**問題**：RLS 只能決定整個 row 能不能被看到，無法在同一個 `SELECT *` 裡「只給部分欄位」。若 `has_issue`／`severity_band`／`free_text` 全部存在同一張表，教練只要具備該 row 的 SELECT 權限，`free_text` 就會被一起送出，即使 consent scope 本意只授權摘要資訊。

```
REQ-RLS-007（新增）
需要欄位層級授權區隔的資料，必須實體拆分為獨立資料表，各自套用
獨立的 RLS 政策，不得以「同一張表、期待應用層自行過濾欄位」的方式
實作 field-level consent。
```

```
injury_reports
- id, athlete_id, has_issue, severity_band, created_at
（consent scope: injury_status 對應此表）

injury_report_details
- injury_report_id, free_text
（consent scope: injury_detail，需獨立授權，非 injury_status 的子集）
```

### 2.4 快取與授權順序（新增，修正快取可能繞過即時 consent 檢查的問題）

```
REQ-CACHE-AUTH-001
team_athlete_projection 等快取資料，任何讀取路徑都必須先完成當下的
授權與 consent 檢查後才能回傳快取內容；快取的 TTL 是資料新鮮度的
考量，不得被當作授權機制本身。換言之，處理順序固定為：
  請求 → 即時授權/consent 檢查 → 通過 → 讀取快取內容（若有）→ 回傳
不得是：快取有資料 → 直接回傳。
```

### 2.5 Auth 需求

```
REQ-AUTH-001  Email 驗證：帳號啟用前需完成 email 驗證
REQ-AUTH-002  登入嘗試頻率限制
REQ-AUTH-003  Refresh token rotation：每次使用後即失效並換發新 token
REQ-AUTH-004  Refresh token 重用偵測：偵測到已失效 token 被重用時，
              整個 token family 立即撤銷
REQ-AUTH-005  使用者可查看與撤銷自己的有效 session 清單
REQ-AUTH-006  Token 儲存：行動端用 OS 安全儲存區，網頁端不用
              localStorage 存放 refresh token；若用 HttpOnly cookie
              需同時實作 CSRF 防護、SameSite、Secure
REQ-AUTH-007  team_role 為 owner 或 head_coach 的帳號，Phase 1 即要求
              MFA 或 Passkey；角色於登入期間被提升為 head_coach 時，
              立即要求補做 MFA 才能繼續操作
REQ-AUTH-008  資料匯出、角色變更、帳單變更等高風險操作要求 step-up 驗證
```

---

## 三、Consent 模型

```
REQ-CONSENT-001   選手加入團隊須經邀請與同意流程，不可由教練單方面授權完成
REQ-CONSENT-002   資料分享範圍須可獨立授權（scope 化，見二.三欄位拆分）
REQ-CONSENT-003   consent 撤銷的資料庫交易 commit 後：
                    - API 查詢下一次請求即拒絕（依 REQ-CACHE-AUTH-001 順序）
                    - team_athlete_projection 快取 ≤5 秒內失效
                    - 已下載的匯出檔案技術上無法追回，屬服務條款約束範疇
REQ-CONSENT-004   選手離隊後：教練儀表板即時移除，不得再查詢其
                    athlete-owned 資料；team-owned 資料（如課表指派歷史）
                    團隊可保留；重新加入須重新走同意流程，不沿用舊 consent
```

---

## 四、Training Load：Metric 與 Alert 分離

### 4.1 命名與單位修正

```
REQ-LOAD-001（修正版，取代 v3.0 的 trimp_srpe 命名）
單次訓練負荷（session_load）依來源分兩種不可互相比較的單位：
  Garmin API 提供裝置負荷數值：直接採用，unit = "garmin_epoc"
  無裝置負荷數值（手動輸入）：session_load = duration_minutes × RPE
    （session-RPE 法），source_metric = "SESSION_RPE"，unit = "AU"
    （不使用 "trimp_srpe" 這個名稱——TRIMP 是另一套獨立方法論，
    與 session-RPE 不應混用同一命名，避免未來做資料分析的人誤解）

REQ-LOAD-006   不同 unit 的 session_load 不得直接加總計算同一組
               acute/chronic 負荷；混合來源時 data_quality 降級為 LOW，
               分別呈現趨勢，不強行合併成單一數字
```

### 4.2 時間窗與公式

```
REQ-LOAD-002   acute_load = 過去 7 天 session_load 總和（同一 unit 內）
REQ-LOAD-003   chronic_load = 過去 28 天 session_load 總和 ÷ 4
               load_ratio = acute_load / chronic_load
```

### 4.3 休息日與缺漏資料（本版修正：拿掉「裝置沉默＝休息」的錯誤推論）

**問題**：v3.0 允許「Garmin 同步確認當天零活動」視同休息日，但 Garmin Activity API 本質是同步已產生的活動事件——沒有活動事件，可能代表真的休息，也可能代表手錶沒戴、沒同步、用了別的裝置。缺席的證據不是證據的缺席不能倒過來用。

```
REQ-LOAD-004（修正版）
Phase 1 僅接受使用者主動確認（rest_confirmed_by_user = true）的休息日
才計入 observation_days 分母。裝置端沒有活動事件，不得自動推論為
已確認休息，一律視為缺漏資料，不計入分母。
（若未來取得 Garmin 每日摘要類 API 且能證明裝置確實配戴/同步，
可重新評估是否能以此推論休息，但目前不成立。）

REQ-LOAD-005   observation_days < 21，或 chronic_load = 0，
               data_quality = INSUFFICIENT，不計算並顯示 load_ratio
```

### 4.4 演算法版本化與雜湊可重現性（本版新增 canonicalization 定義）

```
REQ-LOAD-007（修正版，補上 canonicalization 規則，解決雜湊不可重現問題）
input_snapshot_hash 的計算規則：
  - 輸入序列化為 canonical JSON：key 依字母序排序
  - 字元編碼 UTF-8
  - 時間一律正規化為 UTC ISO 8601
  - 數值採固定小數精度（依 unit 定義，例如 AU 類單位取到小數點後 2 位）
  - 雜湊演算法固定為 SHA-256
  - 需記錄 schema_version，schema 變更視為不同 hash 空間

REQ-LOAD-008   回溯修改或補登過去的訓練紀錄後，僅重新計算受影響時間窗
               （依 acute/chronic 視窗定義：異動發生於 D 日，重算範圍為
               D 至 D+27，而非從 D 一路重算至今天），降低大量歷史資料下
               的重算成本
```

### 4.5 Training Load Metric 與 Alert 明確分離（本版核心修正）

**問題**：v3.0 有了 acute/chronic/ratio 公式，但完全沒定義「ratio 多少該顯示什麼警示」，工程師無法把 Training Load Alert 做成產品功能。但直接抄一組 threshold（如 ratio > 1.5 = 危險）又會重演最早那輪「過度宣稱」的錯誤。

```
REQ-METRIC-001（Phase 1 唯一交付範圍）
Phase 1 僅提供「Training Load Trend」，顯示：7 天負荷、28 天週等效
負荷、ratio 數值、data_quality 標籤。不顯示紅/黃/綠燈號，不使用
「警示」（Alert）字樣。

REQ-ALERT-001（Alert 燈號功能的前置條件，目前尚未核准，不進 Phase 1）
若日後要提供 Alert 燈號，alert_state 的 deterministic mapping
（ratio 區間 → 狀態）必須明確定義、附上依據來源，並經產品/運動科學
顧問核准後才能實作。

REQ-ALERT-002   每個 threshold 數值須記錄來源、版本與核准紀錄
REQ-ALERT-003   algorithm_version 變更時，alert policy version 須同步更新
```

`training_load_daily` 資料表：`(athlete_id, date)` 索引，欄位含 `session_load`、`unit`、`source_metric`、`acute_load`、`chronic_load`、`load_ratio`、`data_quality`、`observation_days`、`algorithm_version`、`schema_version`、`computed_at`、`input_snapshot_hash`。

---

## 五、LLM 安全架構（本版再降一級權限）

### 5.1 問題：結構隔離解決了資料完整性，沒解決行為安全

v3.0 保證 LLM 不能竄改 Prescription 的數字欄位，但使用者實際看到的畫面可能是「今天可以跑更多，試著突破自己！」旁邊放著「30 分鐘輕鬆跑」——數字沒被改，但人的行為判斷仍然被 LLM 的自由文字影響了。「LLM 不能改數字」不等於「LLM 不能給出不安全的訓練建議」。

### 5.2 修正：Phase 1 Runtime 不做自由文字生成

```
REQ-AI-006（本版新增，最高優先）
Phase 1 Runtime 階段，LLM 的輸出限縮為從人工預先審核過的文案庫中
選擇一個 tone_variant_id，不進行即時自由文字生成：

  Deterministic Engine → emotional_context
        ↓
  LLM → { "tone_variant_id": "SUPPORTIVE_A" }
        ↓
  伺服器依 tone_variant_id 從人工審核過的白名單模板取出對應文字

自由文字生成（若日後產品需要）可在背景/離線流程由 LLM 產生候選文案，
但一律須經人工審核後才能進入 template library，不得在使用者請求的
當下即時生成並直接顯示。
```

```
REQ-AI-003   LLM 輸出不得作為任何處方欄位（距離／時長／配速／強度／
             訓練類型）的資料來源
REQ-AI-004   使用者畫面上的處方資訊必須直接源自 Recommendation Object
             的伺服器端渲染，不經過 LLM
REQ-AI-005   傳送給 LLM 的輸入僅限 adjustment_reason_code 與必要數值
             context，不傳送姓名、傷病原文、GPS 資料或其他自由文字
```

### 5.3 Fail-closed，而非 silent ignore（本版修正 v3.0 的錯誤處理方式）

```
REQ-AI-007（修正 v3.0，取代原本的「忽略非白名單欄位」）
LLM 回應必須嚴格符合預期 schema（例如 Pydantic 設定 extra="forbid"）。
若回應包含 schema 之外的欄位（不論欄位內容是否看似無害），整包回應
視為無效，不得只忽略多餘欄位、其餘部分照樣使用；須記錄此異常供
觀察，並 fallback 為固定模板。
```

---

## 六、Webhook：Provider Adapter

```
REQ-WEBHOOK-PROVIDER-001   Webhook 驗證邏輯依各 provider 實際簽章、
                            重送與順序語意個別實作，不套用跨 provider
                            的通用規則（如統一 timestamp 過期窗口）
REQ-WEBHOOK-003            webhook_events 對 (provider, event_id) 建立
                            資料庫 UNIQUE 限制，寫入採
                            INSERT ... ON CONFLICT DO NOTHING
```

**LINE Adapter**：對原始未 deserialize 的 body 驗證 channel secret 簽章 → 以 `webhookEventId`（ULID）做 DB 層 idempotency → `deliveryContext.isRedelivery` 供監控使用，不作為拒收依據 → `timestamp` 僅用於事件排序。

**Garmin／付款服務商 Adapter**：見十、Garmin 整合章節，付款服務商 Adapter 待補（不得由工程師自行假設套用 LINE 邏輯）。

### webhook_metadata vs 原始 payload

```
webhook_metadata（預設一律儲存）：provider, event_id, received_at, body_hash, status
原始 payload：僅除錯/處理需要時儲存，需加密並設定明確 TTL
```

---

## 七、去重

```
REQ-DEDUP-001   completed_activities 對 (provider, provider_activity_id)
                建立 UNIQUE 限制（不是單獨 provider_activity_id UNIQUE）
REQ-DEDUP-002   時間/距離相近但 provider_activity_id 不同的紀錄僅標記
                duplicate_candidate，交由使用者確認，系統不自動刪除或合併，
                合併時原始版本保留於 athlete_annotations
```

---

## 八、Offline 同步與本地安全

```
REQ-SYNC-001   已確認的本地寫入不得有靜默資料遺失，顯示「已儲存」前
               須先完成本地持久化提交
REQ-SYNC-002   95% 的佇列記錄應在網路恢復穩定後 30 秒內完成同步
REQ-SYNC-003   欄位層級衝突解決採 optimistic concurrency
               （server_version／base_version 比對），不使用裝置
               wall-clock 時間戳作為判定依據

REQ-LOCAL-SEC-001   本地資料庫記錄依已驗證帳號做命名空間隔離
REQ-LOCAL-SEC-002   Refresh token 存於 OS 安全儲存區（同 REQ-AUTH-006）
REQ-LOCAL-SEC-003   帳號登出/移除時，該帳號本地敏感快取一併清除
```

---

## 九、排程可靠性（本版補上 LINE 官方冪等機制）

```
REQ-SCHED-002   內部排程端點僅接受具備 service-to-service 憑證的請求
REQ-SCHED-003（修正版，整合 provider 層冪等）
排程任務的 idempotency key 為 (user_id, job_type, local_date) 組合，
且用於推播的 LINE Push Message API 呼叫須同時帶上由此 key 衍生出的
穩定 X-Line-Retry-Key（開發者自行產生的 UUID，同一 key 重複呼叫時
LINE 官方會回傳 409 並拒絕重複送出）。此設計同時處理兩種重複情境：
  - 內部 DB 層級重複觸發 → 靠 job idempotency key 擋下
  - LINE 已受理請求但伺服器在寫入「已發送」狀態前當機 → retry 時
    靠 X-Line-Retry-Key 讓 LINE 平台本身擋下重複發送
```

---

## 十、Garmin 整合：Feature-Gated（本版新增，解決 Phase 1 未完成外部依賴問題）

**問題**：REQ-SCOPE-001 把 Garmin 同步列為 Phase 1 功能，但 Garmin Adapter 規格、真實 sandbox payload、資料映射規則都還沒完成。查證 Garmin 官方文件確認 Activity API 屬 cloud-to-cloud 整合，需使用者 consent、裝置先同步至 Garmin Connect，第三方平台才能取得活動資料，正式整合也需要 Developer Program 審核通過，且官方不保證每一種 metric（包含本規格假設的 `garmin_epoc` 負荷數值）在所有情況下都可取得。這代表 Garmin 整合是一個時程不完全掌握在工程團隊手上的外部依賴，不應該卡死整個 Phase 1 release。

```
REQ-GARMIN-001
Garmin 整合以 feature flag（GARMIN_ACTIVITY_SYNC_ENABLED）控制，
Phase 1 核心交付範圍（Phase 1A）僅依賴手動輸入，不依賴 Garmin 整合
是否完成。

REQ-GARMIN-002
Garmin 整合（Phase 1B）須完成以下前置條件才能開啟 feature flag：
  Developer Program 審核通過、取得真實 sandbox payload 驗證資料映射、
  完成 webhook/pull 整合契約、完成對應測試案例
在此之前，flag 保持關閉，系統以 Phase 1A（手動輸入）運作不受影響。

REQ-GARMIN-003
Phase 2 啟動自訂 Connect IQ 手錶 App 前，須先做架構驗證，確認 Garmin
官方 Training API（將結構化課表推送至 Garmin Connect，經使用者同步
後即可在相容裝置執行）是否已足以滿足課表推送需求；若已足夠，
不開發自訂 CIQ App。
```

---

## 十一、隱私生命週期（本版新增，v3.0 完全缺失）

查證台灣個資主管機關公開說明確認資料主體具有查詢/閱覽、複製、補充/更正、停止蒐集處理利用、刪除等權利；蒐集資料時亦須告知蒐集目的、類別、期間、利用對象與權利行使方式。以下為對應的工程需求（實際法律適用與資料分類仍須由法律專業於上線前確認）：

```
REQ-PRIV-001   使用者可請求匯出自己的完整資料（athlete-owned 範圍）
REQ-PRIV-002   使用者可請求更正錯誤的個人資料
REQ-PRIV-003   使用者可請求刪除帳號與對應資料，須定義刪除後的
               保留期限（如法規要求的交易紀錄除外）
REQ-PRIV-004   使用者可請求停止特定用途的資料處理（如停用 LLM
               情緒建議功能但保留基礎課表功能）
REQ-PRIV-005   各類資料的保留期限須明確定義並排程執行刪除/去識別化
REQ-PRIV-006   隱私權政策/服務條款須版本化，記錄使用者同意的版本
               與時間
```

---

## 十二、時區（本版尋回，v3.0 遺漏）

```
REQ-TZ-001
事件時間一律以 UTC 儲存；使用者所屬時區獨立記錄；「今天」
（local_training_date，用於 training load 分日與排程 job key）由
UTC + 使用者時區換算得出，不得直接用伺服器所在時區判斷日期邊界。
```

---

## 十三、年齡與未成年政策

```
REQ-AGE-001（修正：加入資料極小化考量）
Phase 1 僅開放年滿 18 歲的使用者註冊。若法律顧問確認「使用者自我
聲明已滿 18 歲」已足夠作為合規依據，系統僅需保存聲明紀錄
（勾選 + 時間戳），不需要長期保存完整出生年月日；是否需要完整 DOB
由法律顧問決定，不由工程團隊自行假設。

REQ-AGE-002
Phase 2 若擴及未成年選手，須完成監護人同意流程設計，並由法律專業
確認資料分類是否落入醫療/健康資料的加強規範。
```

---

## 十四、錯誤格式與 Audit Log

```
REQ-ERROR-001   FastAPI/Pydantic 預設驗證錯誤回傳 422，採用此預設，
                不額外攔截轉換為 400
REQ-AUDIT-001   audit_log 記錄：AUTH_LOGIN／AUTH_FAILURE／ROLE_CHANGE／
                CONSENT_GRANT／CONSENT_REVOKE／DATA_EXPORT／
                CROSS_TENANT_DENIED／BILLING_CHANGE
REQ-AUDIT-002   audit_log 與應用程式 log／Sentry 一律禁止記錄密碼、
                JWT／refresh token 原文、選手傷病自述原文、LLM 呼叫
                原始輸入輸出、webhook 原始生理資料 payload
```

---

## 十五、其餘沿用需求（內容不變，僅列編號避免遺漏）

```
REQ-SEC-001~002, REQ-TEN-001~003      多租戶基礎授權
REQ-RISK-001~002                      Data Quality Gate 命名與分級邏輯
REQ-WEATHER-001                       天氣 API 四狀態 fallback
REQ-BILLING-001~002                   訂閱狀態以付款服務商 webhook 為準
PERF-001                              效能非功能需求
BACKUP-001                            備份 RPO/RTO 與還原演練
```

---

## 十六、前端／後端／資料庫技術選型（決策不變，摘要）

React Native（TypeScript）+ Next.js（教練網頁儀表板）／Python + FastAPI／PostgreSQL 16。決策理由與 Flutter／Java／C 的比較分析維持先前討論結論，不重複列出。

---

## 十七、`[RETIRED]` 需求對照表

| 舊編號 | 狀態 | 替代編號 |
|---|---|---|
| v3.0 的 `SET LOCAL app.athlete_id = target` 交易範本 | RETIRED | REQ-RLS-006（二.二，改為 actor model） |
| v3.0 REQ-LOAD-004（Garmin 零活動視為休息） | RETIRED | REQ-LOAD-004 修正版（四.三，僅接受使用者主動確認） |
| v3.0「trimp_srpe」命名 | RETIRED | REQ-LOAD-001 修正版（unit = "AU", source_metric = "SESSION_RPE"） |
| v3.0 REQ-AI-003~005（規則式 Validator 為主要防線） | RETIRED | REQ-AI-006~007（五、架構隔離為主要防線） |
| v3.0「HIGH/MEDIUM 規則於實作階段補齊」 | RETIRED | REQ-METRIC-001／REQ-ALERT-001（Phase 1 不做燈號，僅 Trend） |
| v3.0 Garmin 隱含為 Phase 1 必要依賴 | RETIRED | REQ-GARMIN-001~003（十、feature-gated） |

---

## 十八、追溯總表（全量，供測試規格書 v3.0 對照）

| 章節 | REQ 編號 |
|---|---|
| 零 | REQ-SCOPE-001, REQ-WEATHER-LOCATION-001 |
| 一 | REQ-DATAOWN-001, REQ-AUTHZ-001 |
| 二 | REQ-RLS-001~007, REQ-CACHE-AUTH-001, REQ-AUTH-001~008 |
| 三 | REQ-CONSENT-001~004 |
| 四 | REQ-LOAD-001~008, REQ-METRIC-001, REQ-ALERT-001~003 |
| 五 | REQ-AI-003~007 |
| 六 | REQ-WEBHOOK-PROVIDER-001, REQ-WEBHOOK-003 |
| 七 | REQ-DEDUP-001~002 |
| 八 | REQ-SYNC-001~003, REQ-LOCAL-SEC-001~003 |
| 九 | REQ-SCHED-002~003 |
| 十 | REQ-GARMIN-001~003 |
| 十一 | REQ-PRIV-001~006 |
| 十二 | REQ-TZ-001 |
| 十三 | REQ-AGE-001~002 |
| 十四 | REQ-ERROR-001, REQ-AUDIT-001~002 |
| 十五 | REQ-SEC-001~002, REQ-TEN-001~003, REQ-RISK-001~002, REQ-WEATHER-001, REQ-BILLING-001~002, PERF-001, BACKUP-001 |
