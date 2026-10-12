# RunSense 用到的論文與文件

這份文件列出 RunSense 用到的每一篇論文與文件：**它是做什麼的、系統哪個功能用它、論文給了什麼（公式或數字）、系統怎麼算**。

| 部分 | 功能 | 程式位置 |
|---|---|---|
| 第一部分（第一–七節） | 課表分析（判讀、切分、課表推估） | `backend/app/workout_analysis.py`、`workout_segmentation.py`、`workout_prescription.py` |
| 第二部分（第八節） | 天氣配速補償 | `backend/app/weather_pace.py`、`diurnal_temperature.py`、`climate_normals.py`、`weather_forecast.py` |
| 第三部分（第九節） | AI 健康教練（傷痛與恢復指引資料庫） | `backend/migrations/versions/0020`、`0021`、`0027`、`backend/app/evidence_retriever.py`、`safety_triage.py` |
| 第四部分（第十節） | 訓練負荷與排課 | `backend/app/training_load.py`、`schedule_draft.py`、`recommendation_engine.py`、`athlete_pace.py` |
| 第十一節 | 依論文查：每篇用在哪裡 | — |
| 第十二節 | 程式有用到、但沒有標出處的方法 | — |
| 第十三節 | 已知問題（尚未修正） | — |
| 第十四節 | 評估過但沒採用：高強度儲備（D′ 平衡） | 未實作 |

- 查證層級：「全文」＝已讀全文；「摘要」＝數字明確寫在摘要裡；「程式註解」＝論文細節寫在程式註解中，本次只核對書目；「廠商文件」＝官方文件；「衛教頁面」＝專業學會的大眾衛教網頁（不是論文）。
- 例子取自示範選手：10/5（12 × 400 m，目標 82 秒）、10/8（4 × 1200 m，目標 3:45/km）。
- 課表分析各判讀的完整規則與資料品質設定見 `WORKOUT_ANALYSIS_EVIDENCE.md`。

整理日期：2026-10-11。

# 第一部分：課表分析

---

## 一、配速判斷（每趟 vs 目標、配速穩定度、前後段、第一趟）

### Hopkins 2004（*Sportscience* 8:1–7，全文）

- **論文給的**：個人運動的「最小有意義變化」＝ **0.3 × 比賽間個人典型變異**（原文：「0.3 of the typical variation in an athlete's performance from competition to competition」，2011 年由 0.5 改為 0.3）。

### Hopkins & Hewson 2001（*Med Sci Sports Exerc* 33:1588，摘要）

- **論文給的**：跑者比賽成績的個人變異係數。最快四分之一的男性跑者：越野與路跑 **1.2–1.9%**；半馬 2.7% 與 4.2%；全馬 2.6%。

### 系統用的公式

```
最小有意義差距 SWC = 0.3 × 1.9% = 0.57%          （取 1.9% 上限）
每趟目標時間 T     = 目標配速(秒/km) × 距離(m) ÷ 1000
容許範圍 tol%      = max(0.57%, 1 秒 ÷ T × 100%)   （1 秒是手錶記錄解析度）
教練有寫範圍時    tol% = (最慢 − 最快) ÷ 2 ÷ 目標 × 100%
```

**每趟判斷**：偏差 dev% = (實際配速 − 目標配速) ÷ 目標配速 × 100%

- |dev| ≤ tol → 在範圍內；dev < −tol → 太快；dev > tol → 太慢
- 教練寫範圍時，直接看實際配速是否落在最快與最慢之間

**配速穩定度**：偏差的母體標準差

```
SD = √( Σ(devᵢ − 平均 dev)² ÷ n )
SD ≤ 平均 tol → 做得好；否則 → 要加強
```

**前後段配速**：k = max(1, ⌊n/3⌋)；前 1/3 ＝前 k 趟 dev 的平均，後 1/3 ＝後 k 趟 dev 的平均，各自跟平均 tol 比。

**第一趟**：第 1 趟的 dev 跟它自己的 tol 比。

**節奏跑／比賽目標**：整段視為一趟，tol% = max(0.57%, 1 秒 ÷ (目標配速 × 公里數) × 100%)。

### 例子

- **10/5**：T = 82 秒，1 ÷ 82 = 1.22% > 0.57%，所以 tol = **1.22%（約 ±1.0 秒）**。
  - SD 3.4% > 1.22% → ⚠️「每趟離目標忽快忽慢」
  - 前 1/3 = −2.4%（< −1.22%）→ ⚠️「前段太快」；後 1/3 = +3.7%（> 1.22%）→ ⚠️「後段掉速」
- **10/8**：T = 225 × 1.2 = 270 秒，1 ÷ 270 = 0.37% < 0.57%，所以 tol = **0.57%（約 ±1.5 秒）**。
  - 第 4 趟 dev = −1.9% → ⚠️「比目標快」

### 限制

Hopkins 的 0.3 倍與 Hopkins & Hewson 的 1.9%，研究的都是**比賽成績**；套用到單趟配速是延伸用法，不是論文直接研究單趟配速。

### Buchheit & Laursen 2013（*Sports Med* 43:313，摘要）

- **論文給的**：沒有公式。間歇課有多達 9 個設計變數（強度、時間、休息長度與強度、趟數、組數等），改變任何一個都會影響急性生理反應。
- **系統用法**：作為以下兩條規則的理由。
  - 比目標快超過 tol 也標「要加強」（偏離教練設計的強度）。
  - 休息：`平均休息 − 課表休息 > 1 秒 → 要加強`（1 秒是記錄解析度；比課表短不標）。

---

## 二、跟上次比：配速更快、心率更低

### Buchheit 2014（*Front Physiol* 5:73，全文）

- **論文給的**：
  - 運動中心率「越低，選手越有體能」；固定強度下心率下降，與高強度表現進步有大到非常大的相關。
  - 「心率上升不應被當成疲勞或體能下降的明確指標」。
  - 心率要運動**至少 3–4 分鐘**才穩定，分析取**最後 30–60 秒**的平均。

### Lamberts et al. 2004（*J Strength Cond Res* 18:641，摘要）

- **論文給的**：約 90% 最大心率時，次最大強度心率的測量標準誤 **SEM = 1.1–1.4%**（變異係數的 95% 信賴區間）；心率每天差 5 ± 2 bpm。

### 系統用的公式

```
只用 ≥ 180 秒的趟                              （取 3 分鐘下限）
每趟穩定心率 = 該趟最後 60 秒的平均心率         （取 60 秒上限）
今天 HR_now  = 這些趟穩定心率的平均；上次 HR_prev 同法
配速解析度 R = 1000 ÷ (總強度距離 ÷ 趟數)       （每趟 1 秒換算成 秒/km）
心率誤差 E   = 1.645 × 1.4% × √2 × HR_prev     （取 SEM 上限；√2 是兩次量測相減）

✅ 做得好 ⇔ (今天配速 − 上次配速) ≤ R  且  (HR_prev − HR_now) > E
心率變高超過 E → 只陳述，不標壞（Buchheit 2014）
```

### 例子

- **10/8**：HR_prev = 185 bpm，E = 1.645 × 0.014 × 1.414 × 185 = **6.0 bpm**；HR_now = 175 bpm，低 10 bpm > 6.0，且配速快 6.4 秒/km → ✅「配速更快、心率更低：朝好的方向」。
- **10/5**：400 m 每趟約 82 秒 < 180 秒，不比心率。

---

## 三、休息時的心率恢復（💤 不用在意）

### Bonato et al. 2018（*PLOS ONE* 13，全文 Table 1、2）

- **論文給的**：HRR60 ＝運動結束時峰值心率（最後 5 秒平均）− 恢復 60 秒時的心率。典型誤差 4.07 bpm、**變異係數 CV = 10.9%**（90% 信賴區間 9.0–14.2%）、ICC 0.91、最小有意義變化 2.49 bpm。結論：典型誤差大於最小有意義變化，偵測個人小變化的敏感度不足。

### 系統用的公式

```
峰值      = 休息開始前 3 秒到開始後 30 秒內的最高心率
HRR60     = 峰值 − (峰值後 60 秒那一刻前 3 秒的平均心率)
變化%     = (今天 HRR60 − 過去 k 次平均) ÷ 過去平均 × 100%
誤差範圍  = 1.645 × 10.9% × √(1 + 1/k)
```

- k = 1：±25.4%；k = 2：±22.0%；k = 4：±20.0%；k = 5：±19.6%

### 例子

- **10/5**：k = 4，誤差範圍 = 1.645 × 10.9 × √1.25 = **±20.0%**；今天 11 bpm、過去平均 18 bpm，變化 −38%，超出範圍 →「休息時心率降得比過去慢，超出誤差範圍」，結論仍是 💤 不用在意（見 Aubry 2015）。

### 跟論文的差異

Bonato 的峰值取運動結束時；系統在休息開始前後一段時間內找最高值，因為手腕心率會延遲。這是資料品質設定，不是 Bonato 的做法。

### Aubry et al. 2015（*PLOS ONE* 10，全文）

- **論文給的**：HRR ＝停止運動時心率 − 60 秒時心率。功能性過度訓練組 HRR 從 38 ± 11 變成 45 ± 11 bpm（**+8 ± 5 bpm**）；對照組沒有明顯變化。作者結論：心率恢復變快不一定代表表現變好，要搭配疲勞感與表現解讀。
- **系統用法**：沒有公式。作為「單看不能判斷好壞」的依據；恢復變快且超出誤差範圍時，提醒「如果同時覺得比平常累，告訴教練」。

### Bellenger et al. 2016（*Sports Med* 46:1461，摘要）、Fecchio et al. 2019（*Auton Neurosci* 221:102582，摘要）

- Bellenger：表現進步與過度訓練時，運動後 HRR 都會上升。
- Fecchio：HRR60 在 76.2% 的研究條件下，變異係數符合理想。
- **系統用法**：背景依據，沒有用到公式。

---

## 四、心率脫鉤（連續跑）

### TrainingPeaks〈Aerobic Decoupling and Heart Rate Drift Explained〉（Joe Friel，廠商文件）

- **文件給的**：比較穩定強度的前半與後半（Pa:Hr）。
  - **< 5%**：該強度下有氧耐力良好
  - **5–10%**：耐力有限或有疲勞
  - **> 10%**：強度可能高於有氧閾值，或耐力不足以撐完
  - 影響因素：核心體溫上升、脫水、肝醣耗盡、心血管疲勞

### 系統用的公式

```
每公里效率 EF = (1000 ÷ 該公里秒數) ÷ 該公里平均心率     （速度 ÷ 心率）
EF₁ = 前半各公里 EF 的平均；EF₂ = 後半各公里 EF 的平均
脫鉤% = (EF₁ − EF₂) ÷ EF₁ × 100%
< 5% → ✅；5–10% → ⚠️；> 10% → ⚠️
```

### Smyth et al. 2022（*Sports Med* 52:2283，全文）

- **論文給的**：脫鉤 ＝ (%最大心率 ÷ %臨界速度)，比較 35–40 km 與 5–10 km；分級 < 1.1、1.1–1.2、≥ 1.2；82,303 位馬拉松跑者中，脫鉤越少成績越好。
- **系統用法**：只作為「脫鉤是有意義的指標」的背景；**分級沒有採用 Smyth**，採用 TrainingPeaks。

---

## 五、輕鬆跑強度

### Garmin 使用手冊〈About Heart Rate Zones〉（廠商文件）

- **文件給的**：第 1 區 50–60%、第 2 區 60–70%、第 3 區 70–80%、第 4 區 80–90%、第 5 區 90–100% 最大心率。第 2 區描述為「舒適的配速、呼吸稍深、可以交談，適合恢復的配速」。

### Seiler 2010（*Int J Sports Physiol Perform* 5:276，摘要）

- **論文給的**：菁英耐力選手約 80% 課次是低強度（約 2 mM 血乳酸），約 20% 是高強度（約 90% 最大攝氧量）。

### 系統用的公式

```
第 2 區上限 Z2：手錶有設定就用手錶的；
               沒有時 Z2 = 安靜心率 + 0.70 × (最大心率 − 安靜心率)
               （儲備心率模式，比例依示範選手 Garmin 手錶的紀錄）
✅ 做得好 ⇔ 這趟平均心率 ≤ Z2；否則 ⚠️「輕鬆跑跑太快」
```

---

## 六、暖身、收操、GPS

| 文獻 | 論文給的 | 系統公式／用法 |
|---|---|---|
| Bishop 2003（*Sports Med* 33:483，摘要） | 主動暖身能小幅提升短時間與中等時間（10 秒到 5 分鐘）的表現；加入短暫、跟主課表同型態的加速可能有額外幫助。**沒有給最佳長度** | 第一趟前有跑動（> 0 秒）→ ✅；沒有 → ⚠️，建議加幾趟跟課表同配速的短加速 |
| Van Hooren & Peake 2018（*Sports Med* 48:1575，全文） | 主動收操對 4 小時後的當天表現大多無效、隔天大多無效、很可能不能預防受傷 | 收操一律 💤 不用在意 |
| Gilgen-Ammann et al. 2020（*JMIR mHealth uHealth* 8，全文） | MAPE = 平均(\|記錄距離 − 實際距離\| ÷ 實際距離) × 100%；田徑場 8 支錶 **0.9–4.1%**，而且都高估 | 趟內前後半配速一律 💤 不用在意；非操場模式顯示 0.9–4.1% 的提示 |

---

## 七、其他設定

| 文獻 | 論文給的 | 系統公式 |
|---|---|---|
| Tanaka et al. 2001（*J Am Coll Cardiol* 37:153，摘要） | 統合分析 351 篇研究：**最大心率 = 208 − 0.7 × 年齡**（r = −0.90）；實驗室驗證得 209 − 0.7 × 年齡 | 沒有手動輸入、手錶設定、歷史紀錄時，才用 208 − 0.7 × 年齡 |
| Killick et al. 2012（*J Am Stat Assoc* 107:1590） | PELT 演算法：最小化「Σ 分段成本 + β × 變化點數」，並用剪枝讓計算量變成線性 | 成本 C(a,b) = Σx² − (Σx)² ÷ (b − a)（L2）。**懲罰 β = 4σ² ln n、σ² = max((MAD ÷ 0.6745)² ÷ 2, 0.01)、最短分段 5 秒，是我們的設定，不是 Killick 給的**；依據是 40 筆真實課表驗證（35/40 完全吻合，`backend/scripts/validate_segmentation.py`） |

---

# 第二部分：天氣配速補償

首頁的「天候等效配速」、教練課表每段的天候提示、整合建議課表的配速，都會依氣溫把配速放慢（或在比平常涼時加快）。

## 八、天氣配速補償

### El Helou et al. 2012（*PLOS ONE* 7:e37407，摘要＋程式註解）

- **論文是做什麼的**：分析巴黎、倫敦、柏林、波士頓、芝加哥、紐約六大馬拉松 2001–2010 年共 1,791,972 筆完賽成績與當天天氣（摘要已核對），量化氣溫對跑速的影響，並依完賽名次分成 P1（最快）、Q1、中位數、Q3 四個層級。
- **論文給的**：補充表 S3 列出男、女各層級在 7 個氣溫點的**跑速損失（%）**，涵蓋各自最佳氣溫的 −10°C 到 +20°C。P1 層級：
  - 男：(−6.19, 1.41)、(−1.19, 0.35)、(3.81, 0)、(8.81, 0.36)、(13.81, 1.44)、(18.81, 3.29)、(23.81, 6.00)
  - 女：(−0.09, 2.97)、(4.91, 0.74)、(9.91, 0)、(14.91, 0.75)、(19.91, 3.06)、(24.91, 7.16)、(29.91, 13.47)
- **系統用的公式**：

```
跑速損失%(T) = a·T² + b·T + c        （對 7 個 P1 點做最小平方二次擬合）
男：a = 0.01490，b = −0.111895，c = 0.175031，最佳氣溫 3.75°C
女：a = 0.03334，b = −0.655713，c = 3.051430，最佳氣溫 9.83°C
（最大殘差 0.25 個百分點；性別未設定時取兩條曲線平均）

量測範圍外（最佳氣溫 −10°C 以下、+20°C 以上）：
  絕對值 → 停在邊界值，不外插
  相對值 → 用邊界那一點的切線斜率直線外插（避免兩個都超出範圍的溫度相減變成 0）

相對損失% = 跑速損失%(此刻氣溫) − 跑速損失%(傍晚 18:30 的氣候常態氣溫)
            （可以是負值，代表比平常涼、配速可以加快）
```

- **為什麼用 P1 而不是中位數**：RunSense 的對象是有在訓練比賽的選手。論文本身指出「在族群層級，不論實力，氣溫的影響幅度差不多」，男生 P1 曲線比中位數平緩，女生 P1 反而稍陡；兩性都用 P1 是為了一致，不是因為比較保守。

### Tyler et al. 2016（*Sports Med* 46:1699，程式註解）

- **論文是做什麼的**：統合分析熱適應（在熱環境中反覆訓練）對生理、主觀感受和熱環境運動表現的影響。
- **系統用法**：作為「熱適應」調整的依據。論文的結果以 Hedges' g 效果量呈現，**沒有可以直接換算成「配速 %」的數字**，所以系統沒有拿它算公式，只用它來說明這個調整的方向有依據。

### Zurawlew et al. 2016（*Scand J Med Sci Sports* 26:745，經 Tyler 2016 引用，未讀原文）

- **論文是做什麼的**：運動後泡熱水 6 天，誘發熱適應，熱環境下的 5 公里計時成績進步約 5%。
- **系統用的公式**（熱適應調整）：

```
冷於參考 = 參考氣溫 − 此刻氣溫，限制在 ±5°C
倍數 = 1 − (冷於參考 ÷ 5) × 5%
調整後損失% = 跑速損失% × 倍數
```

  比平常熱 5°C 以上時，損失放大到 1.05 倍；比平常涼 5°C 以上時，打 0.95 折。**5% 上限取自 Zurawlew 的結果，5°C 的飽和點與直線形狀是我們的設計**。

### Parton & Logan 1981（*Agricultural Meteorology* 23:205–216，程式註解）

- **論文是做什麼的**：用當天最低溫、最高溫和日出日落時間，推算一天中每個時刻的氣溫（日間正弦、夜間指數遞減）。
- **系統用的公式**（推算早上、中午、傍晚的氣溫）：

```
日長 L = 日落 − 日出
白天：T(t) = (Tmax − Tmin) · sin(π·(t − 日出) ÷ (L + 2a)) + Tmin
夜間：T(t) = Tmin + (T日落 − Tmin) · exp(−b·(距日落時數) ÷ 夜長)
a = 1.5 小時（峰值落後太陽正午）、b = 4.0（夜間降溫速率）、c = 1.0 小時（最低溫落後日出）
```

  參數取自 Parton & Logan 模型的開源 R 套件 `weaana`（R/diurnal.R）。

### 氣候常態與預報資料（官方資料，非論文）

| 來源 | 用途 |
|---|---|
| 臺灣中央氣象署 臺北測站 1991–2020 月平均 | 臺北的氣候常態（最低／最高／平均） |
| 日本氣象廳 東京測站 1991–2020 平年值 | 東京的氣候常態 |
| 英國氣象局 Heathrow 測站 1991–2020 | 倫敦的氣候常態 |
| Open-Meteo 免費小時預報 | 未來 7 天的課表配速；拿不到時降級為氣候常態並標示「氣候估計」 |

# 第三部分：AI 健康教練

健康教練（選手回報傷痛或身體狀況時的對話）有兩層：**規則**決定緊急程度與能不能跑，**指引資料庫**提供有出處的說明。語言模型只能引用資料庫裡附有標題與出版者的內容，不可以自行掛上作者或學會名稱（`backend/app/personas/health_coach/SOUL.md`）。

## 九、健康教練的指引資料庫

### 安全分級（`backend/app/safety_triage.py`）

- **沒有引用論文**。這是固定的規則：無法負重、外觀變形、出血無法控制等紅旗症狀，直接判為需要就醫；其餘依嚴重程度與部位分級。語言模型可以解釋結果，但不能降低緊急程度或改變能不能跑。

### BJSM 論文（指引資料庫，摘要由團隊手寫，未匯入原文）

| 論文 | 是做什麼的 | 健康教練用它說什麼 |
|---|---|---|
| Gabbett 2016（*Br J Sports Med* 50:273–280） | 「訓練與傷害預防的悖論」：急性負荷（近 1 週）÷ 慢性負荷（近 4 週）落在約 0.8–1.3 時受傷率最低，超過約 1.5 受傷風險明顯上升；訓練量高本身不是問題，突然增加才是 | 近期訓練量相對長期基準落在 0.8–1.3 時受傷率最低；也是第四部分負荷門檻的來源 |
| Dubois & Esculier 2020（*Br J Sports Med* 54:72–73） | 軟組織傷害的 PEACE & LOVE 原則：急性期保護、抬高、避免消炎、加壓、衛教；之後漸進負重、保持樂觀、促進循環、運動 | 軟組織傷害以保護、抬高、適度負重與促進循環為主，取代長時間完全休息 |
| Walsh et al. 2021（*Br J Sports Med* 55:356–368，2020 線上發表） | 運動員睡眠的回顧與 2021 專家共識建議 | 睡眠不足與訓練耐受度下降、主觀疲勞上升有關 |
| 「Criteria-based return to running」（BJSM） | 以測試標準決定回到跑步的時機 | 回到跑步看能不能通過可重複的測試，而不是休息天數。**資料庫連結只指向 BJSM 首頁，沒有對應到特定論文，建議補上確切出處** |

### ACSM（美國運動醫學會，指引資料庫）

| 條目 | 健康教練用它說什麼 | 注意 |
|---|---|---|
| Exertional heat illness during training and competition | 高溫高濕時散熱效率下降，配速應主動放慢並提高補水頻率 | **連結只指向 ACSM 首頁**，建議改成對應的 ACSM 立場聲明 |
| Fluid replacement for physical activity | 補水以避免明顯脫水與過量飲水兩端為原則，依個人流汗率調整 | 同上 |
| Low Back Pain and Physical Activity | 下背痛與活動的建議 | 同上 |

### AAOS OrthoInfo（美國骨科醫學會衛教頁面，不是論文）

| 頁面 | 用途 |
|---|---|
| Stress Fractures of the Foot and Ankle | 疲勞性骨折的警訊、骨頭壓力型疼痛的保守處理 |
| Muscle Strains in the Thigh / Calf | 小腿、大腿拉傷後回到跑步 |
| Patellofemoral Pain Syndrome（Runner's Knee） | 跑者膝的負荷管理 |
| Achilles Tendinitis | 阿基里斯腱炎的初步處理 |
| Plantar Fasciitis and Bone Spurs | 足底筋膜炎的自我照護 |
| Shin Splints（Medial Tibial Stress Syndrome） | 脛前疼痛的保守處理 |
| Hip Strains／Hip Pain in the Active Adult | 髖部與臀肌肌腱問題 |
| Staying Healthy | 新出現小傷痛的一般負荷管理、什麼時候該看醫生 |

另外有 7 個部位的分階段復健條目（`protocol-*`），內容以上表的 AAOS 頁面為來源。

# 第四部分：訓練負荷與排課

## 十、訓練負荷與排課

| 功能 | 數字 | 依據 |
|---|---|---|
| 訓練負荷（AU） | 每次訓練負荷 ＝ 時間（分鐘）× RPE（1–10） | 這是 session RPE 方法（Foster et al. 2001）。**程式沒有標出處**，見第十二節 |
| 急慢性負荷比 | 急性（近 7 天）÷ 慢性（近 28 天） | Gabbett 2016 |
| 負荷分級（整合建議課表） | < 0.8 偏低、0.8–1.3 正常、1.3–1.5 偏高、≥ 1.5 很高 | 對應 Gabbett 2016 的 0.8–1.3「甜蜜點」與約 1.5 的高風險區。**程式沒有直接標出處**，數值與健康教練資料庫中的 Gabbett 2016 一致 |
| 今日建議 | 負荷比 > 1.3 時調降強度 | 同上 |
| 輕鬆跑配速 | 近 180 天、RPE ≤ 4、至少 2 km 的跑步的配速中位數，至少 5 筆；各課表類型在這個基準周圍的固定配速帶 | **團隊自訂的規則（RunSense pace bands v1）**，沒有引用論文 |
| 熱天配速 | 用第八節的跑速損失放慢配速帶，比平常涼時不加快 | El Helou 2012 |

## 十一、依論文查：每篇用在哪裡

| 論文／文件 | 用在 | 查證層級 |
|---|---|---|
| Hopkins 2004 | 配速容許範圍（0.3 倍）、平常範圍的概念 | 全文 |
| Hopkins & Hewson 2001 | 配速容許範圍（1.9%） | 摘要 |
| Buchheit 2014 | 同配速心率更低、心率變高不標壞、3 分鐘與 60 秒規則 | 全文 |
| Buchheit & Laursen 2013 | 跑太快要加強、休息比課表長要加強 | 摘要 |
| Lamberts et al. 2004 | 心率的測量誤差 1.4% | 摘要 |
| Bonato et al. 2018 | 休息心率恢復的誤差範圍 10.9% | 全文 |
| Aubry et al. 2015 | 休息心率恢復不用在意；「恢復變快又覺得累要告訴教練」 | 全文 |
| Bellenger et al. 2016 | 休息心率恢復的背景依據 | 摘要 |
| Fecchio et al. 2019 | HRR60 再現性的背景依據 | 摘要 |
| Gilgen-Ammann et al. 2020 | 趟內前後半不用在意、GPS 提示 | 全文 |
| Van Hooren & Peake 2018 | 收操不用在意 | 全文 |
| Bishop 2003 | 暖身 | 摘要 |
| Seiler 2010 | 輕鬆跑強度 | 摘要 |
| Garmin 使用手冊 | 輕鬆跑強度（第 2 區定義）、心率區間 | 廠商文件 |
| TrainingPeaks | 心率脫鉤分級 | 廠商文件 |
| Smyth et al. 2022 | 心率脫鉤的背景依據 | 全文 |
| Tanaka et al. 2001 | 最大心率估算 | 摘要 |
| Killick et al. 2012 | 切分演算法 | — |
| El Helou et al. 2012 | 天氣配速補償的跑速損失曲線 | 程式註解 |
| Tyler et al. 2016 | 熱適應調整的方向依據 | 程式註解 |
| Zurawlew et al. 2016 | 熱適應調整的 5% 上限 | 經 Tyler 2016 引用 |
| Parton & Logan 1981 | 一天中各時刻的氣溫推算 | 程式註解 |
| Gabbett 2016 | 健康教練的負荷說明、急慢性負荷比門檻 | 指引資料庫 |
| Dubois & Esculier 2020 | 健康教練的軟組織傷害處理 | 指引資料庫 |
| Walsh et al. 2021 | 健康教練的睡眠與恢復 | 指引資料庫 |
| ACSM 熱傷害、補水、下背痛 | 健康教練的熱天、補水、下背痛說明 | 指引資料庫（連結待補） |
| AAOS OrthoInfo 衛教頁面 | 健康教練各部位傷痛的處理與復健 | 衛教頁面 |
| 中央氣象署、日本氣象廳、英國氣象局、Open-Meteo | 氣候常態與預報 | 官方資料 |

---

## 十二、程式有用到、但沒有標出處的方法

| 方法 | 用在哪裡 | 建議引用 |
|---|---|---|
| 訓練負荷 ＝ 時間 × RPE | 訓練負荷、急慢性負荷比、上傳手錶檔案必填 RPE | Foster C, Florhaug JA, Franklin J, et al. (2001). A new approach to monitoring exercise training. *J Strength Cond Res* 15:109–115. doi:10.1519/1533-4287(2001)015<0109:anatme>2.0.co;2 |
| 負荷分級 0.8／1.3／1.5 | 整合建議課表、今日建議 | Gabbett 2016（已在健康教練資料庫中，建議在程式註解與畫面說明直接引用） |
| 健康教練資料庫的 ACSM 三條、BJSM 回到跑步 | 健康教練 | 連結只指向首頁，建議改成確切的立場聲明或論文 |
| 安全分級、輕鬆跑配速帶 | 健康教練、建議課表配速 | 團隊自訂規則，對外說明時要說是規則，不要說有論文依據 |

## 十三、已知問題（尚未修正）

### 「平常範圍」應該用 t 分布

目前「跟平常不同／跟平常一樣」用的公式是：

```
平常範圍 = 平均 m ± 1.645 × s × √(1 + 1/k)
```

這是統計上的預測區間。但 s 是用選手自己少數幾次的資料估出來的，**應該用 t 分布（自由度 k − 1），不能用 1.645**。歷史次數少時差距很大：

| 歷史次數 k | 正確的 t 值（90%） | 目前用的 |
|---|---|---|
| 2 | 6.31 | 1.645 |
| 3 | 2.92 | 1.645 |
| 4 | 2.35 | 1.645 |
| 5 | 2.13 | 1.645 |

所以目前的平常範圍**太窄**，「跟平常不同」被標得太頻繁。休息心率恢復與同配速心率用的是論文給的已知誤差（10.9%、1.4%），不是自己估的 s，所以用 1.645 是正確的，不受影響。

### 兩點說法要更正

- 平常範圍的公式是標準的統計預測區間，**不是 Hopkins 論文裡的公式**；Hopkins 提供的是「用典型誤差判斷個人變化」的概念。
- 90% 信賴水準是 Bonato 2018 等使用 Hopkins 試算表的研究所採用的慣例；**沒有讀到 Hopkins 原文明確規定 90%**。

## 十四、評估過但沒採用：高強度儲備（D′ 平衡）

目標是算出一堂課從開始到結束，選手的「體力」從 100% 掉到多少。2026-10-12 決定**先不做**：依「驗證不過就不做進產品」的原則，現有資料無法完成驗證。

### 原本的設計（已和團隊確認每個細節）

| 項目 | 設計 | 依據 |
|---|---|---|
| CS、D′ | 該課之前 16 週內 400、800、5000 m 各自最快的一段，用 D = D′ + CS × T 回歸；16 週內少於 24 筆活動就不算 | Smyth & Muniz-Pumares 2020 |
| 模型 | 微分式 D′ 平衡，每秒原始速度，不平滑、不修正坡度 | Skiba 2015，公式取自 Vassallo 2020 式 6–7 |
| 顯示 | 名稱「高強度儲備」，最低顯示 0%，依 D′ 誤差 14.56% 標出範圍；只在有跑到 CS 以上的課顯示 | Smyth 2020（D′ 的 CV） |

微分式寫成跑步單位（每秒）：

```
速度 v > CS：D′bal ← D′bal − (v − CS) × 1 秒
速度 v ≤ CS：已用掉的量 ← 已用掉的量 × e^(−(CS − v) × 1 秒 / D′)   （回補時間常數 τ = D′ ÷ (CS − v)）
```

### 讀過的論文

**Vassallo et al. 2020（*Eur J Appl Physiol* 120:219–230，全文）**：這是唯一一篇在跑步上比較 W′ 平衡模型的研究，9 名團隊運動員，用 30-15 間歇測驗跑到力竭：
- 實際力竭時間 968 ± 117 秒。
- 微分式預測 938 ± 84 秒，和實際沒有差異。
- 積分式（Skiba 2012）預測 848 ± 91 秒，顯著太早（P = 0.001）；作者不建議用在跑步。
- 限制：模型輸入是 GPS 推算的「地面跑步功率」，不是速度；只適用平地。

**Smyth & Muniz-Pumares 2020（*Med Sci Sports Exerc* 52:2637–2645，全文）**：從超過 25,000 名跑者的原始訓練資料估 CS：
- D = D′ + CS × T 的 R² 為 0.9999。
- CS 的 CV 是 0.73%，D′ 是 14.56%。
- 用 CS 預測馬拉松成績的誤差是 7.67%。
- 作者自己指出：訓練資料無法確認那一段是不是全力跑。

**Jones & Vanhatalo 2017（*Sports Med* 47:65–78，全文）**：
- CS 模型的測驗時間約 2–15 分鐘。
- 轉述 Skiba 2014：力竭時 W′bal 為 0.5 ± 1.3 kJ，沒力竭時最低值為 3.6 ± 2.0 kJ。
- 要用在個人身上，需要每個人自己的回補時間常數。

**Skiba et al. 2015（*Eur J Appl Physiol* 115:703–713）**：不是開放取用，未讀原文；公式取自 Vassallo 2020 與 Jones & Vanhatalo 2017 的全文。

### 為什麼沒採用

1. **用「速度」算 D′ 平衡在跑步上沒有驗證論文。** Vassallo 用的是功率；Jones & Vanhatalo 只把「用 GPS 速度對照 CS」列為未來方向。
2. **驗證所需的資料不存在。**
   - 原本打算用示範選手的比賽或全力測驗驗證，及格線是 Smyth 的 7.67%。
   - 結果符合 2–15 分鐘、而且是連續全力跑的紀錄一筆都沒有。
   - 唯一能用的 3 筆（兩次 10 公里、一次 4 公里測驗）都超出適用範圍；其中 4 公里的配速還比當時的 CS 慢。
3. **app 沒辦法對每位選手驗證。** 驗證要靠人工標記「撐不住」的課，或需要連續的全力比賽紀錄；一般選手兩者都不會有。

### 過程中的發現：Garmin 個人紀錄不能當成全力跑

Garmin 算 PR 時**不計入按暫停的時間**，所以會把間歇課的好幾組接成一段。例如：
- 「1 公里 178 秒」其實是 300 m 間歇課的 3–5 組接起來的；
- 「5 公里 1127.8 秒」其實是 400 m × 12 間歇課的各組接起來的。

以後任何功能要用 PR，都要改用**含暫停的實際經過時間**重新計算最佳成績。

驗證用的腳本放在 scratchpad（處理個人資料，沒有放進專案）：`dprime_stage1.py`、`dprime_stage2.py`、`dprime_planb.py`。

---

## 參考文獻

- Aubry A, Hausswirth C, Louis J, Coutts AJ, Buchheit M, Le Meur Y (2015). The development of functional overreaching is associated with a faster heart rate recovery in endurance athletes. *PLOS ONE* 10. doi:10.1371/journal.pone.0139754
- Bellenger CR, Fuller JT, Thomson RL, Davison K, Robertson EY, Buckley JD (2016). Monitoring athletic training status through autonomic heart rate regulation: a systematic review and meta-analysis. *Sports Medicine* 46:1461–1486. doi:10.1007/s40279-016-0484-2
- Bishop D (2003). Warm up II: performance changes following active warm up and how to structure the warm up. *Sports Medicine* 33:483–498. doi:10.2165/00007256-200333070-00002
- Bonato M, Meloni A, Merati G, La Torre A, Agnello L, Vernillo G (2018). Effect of repeated-sprints on the reliability of short-term parasympathetic reactivation. *PLOS ONE* 13. doi:10.1371/journal.pone.0192231
- Buchheit M (2014). Monitoring training status with HR measures: do all roads lead to Rome? *Frontiers in Physiology* 5:73. doi:10.3389/fphys.2014.00073
- Buchheit M, Laursen PB (2013). High-intensity interval training, solutions to the programming puzzle: Part I: cardiopulmonary emphasis. *Sports Medicine* 43:313–338. doi:10.1007/s40279-013-0029-x
- Fecchio RY, Brito L, Leicht AS, Forjaz CLM, Peçanha T (2019). Reproducibility of post-exercise heart rate recovery indices: a systematic review. *Autonomic Neuroscience* 221:102582. doi:10.1016/j.autneu.2019.102582
- Gilgen-Ammann R, Schweizer T, Wyss T (2020). Accuracy of distance recordings in eight positioning-enabled sport watches: instrument validation study. *JMIR mHealth and uHealth* 8. doi:10.2196/17118
- Hopkins WG (2004). How to interpret changes in an athletic performance test. *Sportscience* 8:1–7. <https://sportsci.org/jour/04/wghtests.htm>
- Hopkins WG, Hewson DJ (2001). Variability of competitive performance of distance runners. *Medicine & Science in Sports & Exercise* 33:1588–1592. doi:10.1097/00005768-200109000-00023
- Killick R, Fearnhead P, Eckley IA (2012). Optimal detection of changepoints with a linear computational cost. *Journal of the American Statistical Association* 107:1590–1598.
- Lamberts RP, Lemmink KA, Durandt JJ, Lambert MI (2004). Variation in heart rate during submaximal exercise: implications for monitoring training. *Journal of Strength and Conditioning Research* 18:641–645.
- Seiler S (2010). What is best practice for training intensity and duration distribution in endurance athletes? *International Journal of Sports Physiology and Performance* 5:276–291. doi:10.1123/ijspp.5.3.276
- Smyth B, Maunder E, Meyler S, Hunter B, Muniz-Pumares D (2022). Decoupling of internal and external workload during a marathon: an analysis of durability in 82,303 recreational runners. *Sports Medicine* 52:2283–2295. doi:10.1007/s40279-022-01680-5
- Tanaka H, Monahan KD, Seals DR (2001). Age-predicted maximal heart rate revisited. *Journal of the American College of Cardiology* 37:153–156. doi:10.1016/s0735-1097(00)01054-8
- Jones AM, Vanhatalo A (2017). The 'critical power' concept: applications to sports performance with a focus on intermittent high-intensity exercise. *Sports Medicine* 47:65–78. doi:10.1007/s40279-017-0688-0（第十四節，未採用）
- Skiba PF, Fulford J, Clarke DC, Vanhatalo A, Jones AM (2015). Intramuscular determinants of the ability to recover work capacity above critical power. *European Journal of Applied Physiology* 115:703–713. doi:10.1007/s00421-014-3050-3（第十四節，未讀原文）
- Smyth B, Muniz-Pumares D (2020). Calculation of critical speed from raw training data in recreational marathon runners. *Medicine & Science in Sports & Exercise* 52:2637–2645. doi:10.1249/MSS.0000000000002412（第十四節，未採用）
- Vassallo C, Gray A, Cummins C, Murphy A, Waldron M (2020). Exercise tolerance during flat over-ground intermittent running: modelling the expenditure and reconstitution kinetics of work done above critical power. *European Journal of Applied Physiology* 120:219–230. doi:10.1007/s00421-019-04266-8（第十四節，未採用）
- Van Hooren B, Peake JM (2018). Do we need a cool-down after exercise? A narrative review of the psychophysiological effects and the effects on performance, injuries and the long-term adaptive response. *Sports Medicine* 48:1575–1595.
- Dubois B, Esculier JF (2020). Soft-tissue injuries simply need PEACE and LOVE. *British Journal of Sports Medicine* 54:72–73. doi:10.1136/bjsports-2019-101253
- El Helou N, Tafflet M, Berthelot G, Tolaini J, Marc A, Guillaume M, Hausswirth C, Toussaint JF (2012). Impact of environmental parameters on marathon running performance. *PLOS ONE* 7:e37407. doi:10.1371/journal.pone.0037407
- Foster C, Florhaug JA, Franklin J, Gottschall L, Hrovatin LA, Parker S, Doleshal P, Dodge C (2001). A new approach to monitoring exercise training. *Journal of Strength and Conditioning Research* 15:109–115.（系統有用，程式未標註，見第十二節）
- Gabbett TJ (2016). The training-injury prevention paradox: should athletes be training smarter and harder? *British Journal of Sports Medicine* 50:273–280. doi:10.1136/bjsports-2015-095788
- Parton WJ, Logan JA (1981). A model for diurnal variation in soil and air temperature. *Agricultural Meteorology* 23:205–216.
- Tyler CJ, Reeve T, Hodges GJ, Cheung SS (2016). The effects of heat adaptation on physiology, perception and exercise performance in the heat: a meta-analysis. *Sports Medicine* 46:1699–1724. doi:10.1007/s40279-016-0538-5
- Walsh NP, Halson SL, Sargent C, et al. (2021). Sleep and the athlete: narrative review and 2021 expert consensus recommendations. *British Journal of Sports Medicine* 55:356–368. doi:10.1136/bjsports-2020-102025
- Zurawlew MJ, Walsh NP, Fortes MB, Potter C (2016). Post-exercise hot water immersion induces heat acclimation and improves endurance exercise performance in the heat. *Scandinavian Journal of Medicine & Science in Sports* 26:745–754. doi:10.1111/sms.12638
- AAOS OrthoInfo（美國骨科醫學會衛教網站）. <https://orthoinfo.aaos.org/>
- American College of Sports Medicine. <https://www.acsm.org/>
- 交通部中央氣象署 氣候資料（臺北測站 1991–2020 月平均）. <https://www.cwa.gov.tw/V8/E/C/Statistics/monthlymean.html>
- 日本氣象廳 平年值（東京）. <https://www.data.jma.go.jp/stats/data/en/normal/normal.html>
- UK Met Office climate averages（Heathrow 1991–2020）.
- Open-Meteo 天氣預報 API. <https://open-meteo.com/>
- weaana（Parton & Logan 模型的 R 套件）. <https://github.com/byzheng/weaana>
- Friel J. Aerobic Decoupling and Heart Rate Drift Explained. TrainingPeaks. <https://www.trainingpeaks.com/coach-blog/aerobic-endurance-and-decoupling/>
- Garmin. About Heart Rate Zones / Heart Rate Zone Calculations（Forerunner 745、245 等機型使用手冊）. <https://www8.garmin.com/manuals-apac/webhelp/forerunner745/EN-SG/GUID-7ABF65EE-073D-4CB8-B5A0-B25DB8356CE9-1600.html>
