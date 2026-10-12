# 課表分析的數字依據

這份文件逐項列出「課表分析」用到的每個數字和它的出處，涵蓋判讀（`backend/app/workout_analysis.py`）、AI 講評（`workout_narrative.py`）、切分演算法（`workout_segmentation.py`）與課表推估（`workout_prescription.py`）。寫給一起開發的夥伴、評審，以及之後要調整門檻的人。

整理日期：2026-10-11。

## 原則

每個數字都必須屬於下面其中一類；**哪一類都不是的判斷就不做，只顯示數字本身**。

| 類別 | 意思 | 例子 |
|---|---|---|
| 論文 | 同儕審查論文直接給的數字。標明查證層級：**全文**（已讀全文）或**摘要**（數字明確寫在摘要裡） | HRR60 測量誤差 10.9% |
| 廠商文件 | 廠商官方文件或裝置紀錄 | TrainingPeaks 的脫鉤分級、Garmin 心率區間 |
| 量測誤差 | 由論文給的量測誤差推出的門檻 | 休息心率恢復要差超過誤差範圍才算有變化 |
| 個人歷史 | 跟選手自己過去的同課表比（Hopkins 方法，見下） | 配速變異係數高於平常範圍 |
| 數學定義 | 計算本身需要的最少數量 | 算標準差至少要 2 個數值 |
| 資料品質設定 | 決定資料夠不夠好、能不能算，不對選手下判斷；公開列出，不宣稱有論文 | 心率訊號覆蓋率 50% |
| 驗證腳本 | 僅限切分演算法與課表推估：以可重跑的驗證結果為依據 | 切分 35/40 完全吻合 |

### 跟選手自己的歷史比（Hopkins 方法）

拿今天的數值 x，跟過去 k 次同課表的平均 m、標準差 s 比：

> 平常範圍 = m ± z × s × √(1 + 1/k)

- **z = 1.645**，即 90% 信賴水準。這是 Hopkins 在運動科學判斷個人變化時常用的信賴水準。
- **k 至少 2**：算標準差最少需要 2 個數值（數學定義）。
- s 來自選手自己的資料，所以平常範圍不是我們訂的。
- 結果只用中性描述：「高於／低於／在你過去 k 次同課表的平常範圍內」。哪個方向比較好沒有論文依據，所以不標好壞。
- 歷史不足 2 次時，只顯示數字。

## 文獻查證結果

| 文獻 | 查證層級 | 用到的數字 |
|---|---|---|
| Bonato et al. 2018, *PLOS ONE* 13 | 全文（Table 1、2） | HRR60 變異係數 **10.9%**（90% 信賴區間 9.0–14.2%）、典型誤差 4.07 bpm、最小有意義變化 2.49 bpm；作者結論：典型誤差大於最小有意義變化 |
| Aubry et al. 2015, *PLOS ONE* 10 | 全文 | 功能性過度訓練組 HRR 從 38 ± 11 變成 45 ± 11 bpm（+8 ± 5 bpm）；作者結論：心率恢復變快不一定代表表現變好 |
| Smyth et al. 2022, *Sports Med* 52:2283 | 全文 | 82,303 位馬拉松跑者，後段心率與速度脫鉤越少，成績越好（支持「脫鉤」這個概念；本系統的分級採 TrainingPeaks） |
| Van Hooren & Peake 2018, *Sports Med* 48:1575 | 全文 | 主動收操對 4 小時後的當天表現大多無效、隔天大多無效、很可能不能預防受傷 |
| Gilgen-Ammann et al. 2020, *JMIR mHealth uHealth* 8 | 全文（田徑場表格） | 田徑場上 8 支運動錶都高估距離，平均絕對誤差 **0.9–4.1%** |
| Silva Oliveira et al. 2024, *Sports Med* | 全文 | 極化式訓練對最大攝氧量 SMD 0.24，其他表現指標無差異；沒有任何「多少比例時間超過某區間就算太累」的門檻 |
| Lamberts et al. 2004, *J Strength Cond Res* 18:641 | 摘要 | 次最大強度心率的測量標準誤 **1.1–1.4%**（約 90% 最大心率時） |
| Tanaka et al. 2001, *J Am Coll Cardiol* 37:153 | 摘要 | 最大心率 = **208 − 0.7 × 年齡**；摘要沒有個體誤差，所以系統不寫誤差數字 |
| Hopkins & Hewson 2001, *Med Sci Sports Exerc* 33:1588 | 摘要 | 跑者比賽成績的個人變異係數 1.2–1.9%（目前未用於門檻） |
| Bellenger et al. 2016, *Sports Med* 46:1461 | 摘要 | 表現進步與過度訓練時，HRR 都可能上升 |
| Fecchio et al. 2019, *Auton Neurosci* 221:102582 | 摘要 | HRR60 在多數研究條件下再現性良好 |
| Bishop 2003, *Sports Med* 33:483 | 摘要 | 暖身沒有固定的最佳長度 |
| Hopkins 2004, *Sportscience* 8:1–7 | 全文 | 判斷個人變化要比較典型誤差與最小有意義變化 |
| Buchheit 2014, *Front Physiol* 5:73 | 全文 | 運動中心率「越低，選手越有體能」，固定強度下心率下降與高強度表現進步有大到非常大的相關；但「心率上升不應被當成疲勞或體能下降的明確指標」；心率要運動至少 3–4 分鐘才穩定，比較時取最後 30–60 秒平均 |
| Buchheit & Laursen 2013, *Sports Med* 43:313 | 摘要 | 間歇課的生理反應取決於強度、時間、休息等設計變數 |
| Seiler 2010, *Int J Sports Physiol Perform* 5:276 | 摘要 | 菁英耐力選手約 80% 課次是低強度（約 2 mM 血乳酸） |
| Killick, Fearnhead & Eckley 2012, *J Am Stat Assoc* 107:1590 | — | PELT 變化點偵測演算法（切分使用） |
| TrainingPeaks〈Aerobic Decoupling and Heart Rate Drift Explained〉（Joe Friel） | 廠商文件 | 脫鉤 **< 5%** 有氧耐力良好、**5–10%** 耐力有限或疲勞、**> 10%** 強度可能高於有氧閾值；核心體溫上升、脫水、肝醣耗盡、心血管疲勞都會讓脫鉤變大 |
| Garmin 使用手冊〈Heart Rate Zone Calculations〉〈About Heart Rate Zones〉 | 廠商文件 | 預設區間為最大心率的 50／60／70／80／90／100%；第 2 區是「舒適的配速、可以交談、適合恢復」 |
| 示範選手的 Garmin FIT 檔 | 廠商裝置紀錄 | 手錶在儲備心率模式下的區間為 50／60／70／80／90／100%（約 180 個檔案）；Garmin 官方手冊沒有列出這組儲備心率預設 |

## 判讀逐項

每一項都給選手一個結論：**✅ 做得好**、**⚠️ 要加強**，或 **💤 不用在意**（研究顯示這項不能單獨判斷好壞，並說明原因）。沒有好壞結論的資料項標「數據」，有歷史可比時標「跟平常不同／跟平常一樣」。畫面依「要加強 → 做得好 → 跟平常不同 → 其他 → 不用在意」排序，每項都附一行「這代表：…」說明數字的意思。

### 配速跟教練目標比的「容許範圍」

只有真實課表（教練排課、選手輸入、Garmin 活動名稱）才判斷；系統從這次紀錄推估的課表不判斷（循環論證）。

- 教練寫了範圍（排課配速欄「3:40–3:45」、選手文字「86±1 秒」）：用教練的範圍。
- 教練只寫單一配速：容許範圍取下面兩者的較大者
  - **表現上最小有意義的差距 0.57%** ＝ 0.3 × 1.9%。Hopkins 2004（全文）：個人運動最小有意義變化是比賽間個人變異的 0.3 倍；Hopkins & Hewson 2001（摘要）：跑者比賽成績個人變異 1.2–1.9%，取上限。**這是把比賽變異套用到單趟配速的延伸用法**，評審問到時要說明。
  - **手錶 1 秒的計時解析度**換算成這一趟的百分比（400 m 跑 82 秒 ≈ 1.2%）。
- 「X 秒內」上限型：實際 ≤ 上限就達標。

### 逐項規則

| 項目 | ✅ 做得好 | ⚠️ 要加強 | 依據 |
|---|---|---|---|
| 每趟 vs 目標 | 每趟都在容許範圍內 | 有趟次比目標快或慢超過容許範圍（跑太快也算：偏離教練設計的強度） | 教練目標＋上述容許範圍；跑太快：Buchheit & Laursen 2013（摘要：課表的生理反應取決於強度等設計變數） |
| 配速穩定度 | 每趟偏差的標準差 ≤ 容許範圍 | 大於容許範圍 | 同上 |
| 前後段配速 | 前 1/3、後 1/3 都在容許範圍內 | 前段太快／太慢、後段掉速／比目標快 | 同上 |
| 第一趟 | 在容許範圍內 | 太快或太慢 | 同上 |
| 上限型課表 | 每趟都在上限以內 | 有趟次超出 | 教練要求本身 |
| 休息時間（課表有指定） | 平均沒有比課表長超過 1 秒 | 平均比課表長超過 1 秒 | 手錶 1 秒解析度；休息長度是課表設計的一部分（Buchheit & Laursen 2013） |
| 跟上次同課表比 | 配速相同或更快、每趟最後 60 秒心率低於上次且超過測量誤差（只用 ≥ 3 分鐘的趟） | — （心率變高只陳述，不標壞） | Buchheit 2014 全文（心率越低越有體能；心率上升不是疲勞的明確指標；3–4 分鐘、最後 30–60 秒取下限）；Lamberts 2004 摘要（測量誤差 1.1–1.4%，取上限） |
| 心率脫鉤（連續跑） | < 5% | 5–10%、> 10% | TrainingPeaks（廠商文件） |
| 節奏跑／比賽目標配速 | 平均在容許範圍內 | 比目標快或慢 | 同「容許範圍」 |
| 輕鬆跑強度 | 平均心率 ≤ 第 2 區上限 | 高於第 2 區上限 | Garmin 手冊：第 2 區是「舒適、還能交談、適合恢復的配速」；Seiler 2010 摘要：低強度課約 2 mM 血乳酸 |
| 暖身（強度課） | 第一趟前有暖身 | 沒有暖身；建議暖身最後加幾趟跟課表同配速的短加速 | Bishop 2003 摘要 |

| 💤 不用在意 | 原因 | 依據 |
|---|---|---|
| 每趟心率逐趟上升 | 研究沒有建立用這個數字判斷好壞的標準 | — |
| 休息時的心率下降、跟過去比的變化 | 單看不能判斷好壞；恢復變快加上自覺疲勞時，可能是過度訓練的早期訊號，所以恢復變快時提醒「如果同時覺得比平常累，告訴教練」 | Aubry 2015 全文、Bellenger 2016 摘要；誤差範圍：Bonato 2018 全文（HRR60 變異係數 10.9%） |
| 趟內前後半配速 | GPS 估算，誤差（0.9–4.1%）跟差距差不多大 | Gilgen-Ammann 2020 全文 |
| 收操 | 收操長短對之後的表現和預防受傷幾乎沒有影響 | Van Hooren & Peake 2018 全文 |

### 其他
| 項目 | 數字 | 依據 |
|---|---|---|
| 「平常範圍」 | 平均 ± 1.645 × 標準差 × √(1 + 1/k)，至少 2 次同課表 | Hopkins 方法（見上） |
| 只比站著／走路的恢復 | — | 方法學：只比同一種恢復方式 |
| 步頻 | 只在數據欄顯示前 1/3 與後 1/3 的平均 | 沒有證據支持刻意維持步頻 |
| 最大心率來源 | 208 − 0.7 × 年齡 | Tanaka 2001 摘要；只在沒有手動、手錶、歷史紀錄時使用 |
| 預設心率區間 | 儲備心率 50–100% | 廠商裝置紀錄（示範選手的 Garmin FIT 檔）；只在手錶沒有提供區間時使用 |
| 非操場模式提示 | 0.9–4.1% | Gilgen-Ammann 2020 全文 |

### AI 講評

- 講評裡的每個數字都必須出現在計算結果中，否則退回重寫。
- 不可以自行加上因果：出現「導致、造成、因為、所以、因此」就退回重寫。
- 提示詞規定：先講要加強的、再講做得好的，用「這代表」把意思講白；不講「不用在意」的項目；判讀結果沒有寫的評價一律不寫；「下次：」只能沿用判讀結果裡的建議。

## 資料品質設定（公開列出，不宣稱有論文）

| 設定 | 數值 | 作用 |
|---|---|---|
| 每段心率訊號覆蓋率 | ≥ 50% | 低於此值不計算該段平均／最高心率 |
| HRR 視窗心率覆蓋率 | ≥ 60% | 低於此值不計算休息心率下降 |
| 整堂心率覆蓋率提示 | < 80% | 加註「心率判讀僅供參考」 |
| HRR 量測視窗 | 峰值取休息開始前 3 秒到開始後 30 秒；視窗至少 40 秒 | 計算休息心率下降 |
| 每趟結束心率、起跑心率 | 最後 10 秒、最初 5 秒的平均 | 計算每趟心率 |
| 判讀每趟心率的最短趟長 | 60 秒 | 更短的趟不判讀每趟心率（跟上次比心率方向時另外要求 ≥ 180 秒，依 Buchheit 2014） |
| 趟內前後半配速 | 趟長 ≥ 60 秒且 GPS ≥ 300 m | 太短的趟 GPS 無法分出前後半 |
| 另存的暖身／收操紀錄 | 前後 2 小時內 | 自動併入這堂課 |
| 同課表歷史 | 近 365 天、最多 5 次 | 跟自己比較的範圍 |
| 輕鬆跑配速基準 | 近 365 天至少 5 筆連續跑 | 計算選手的輕鬆跑配速 |
| 歷史最大心率 | 近 365 天第二高的 30 秒平均心率 | 排除單次感測器異常 |
| 歷史最大心率高於設定時提醒 | 高 3 bpm 以上 | 建議更新最大心率設定 |
| 配速顯示上限 | 3600 秒／公里 | 超過就不顯示配速 |

## 切分演算法與課表推估（驗證腳本）

`backend/scripts/validate_segmentation.py` 用示範選手 Garmin 匯出裡的 40 筆課表驗證。這 40 筆的活動名稱寫明了每一趟，標準答案由選手逐筆確認（`backend/scripts/segmentation_labels.json`）。重跑方式：

```powershell
cd backend
python scripts/validate_segmentation.py ../dataset/<export>.zip
```

2026-10-11 的結果：

| 項目 | 結果 |
|---|---|
| 趟數吻合 | **38/40** |
| 每趟距離也完全吻合 | **35/40（87.5%）** |
| 課表推估的結構吻合 | 35/40 |
| 用標準答案當課表，能跟偵測到的趟次對上（距離容許 20%） | 35/40 |

沒有完全吻合的 5 筆：

| # | 日期 | 活動名稱 | 標準答案 | 偵測結果 |
|---|---|---|---|---|
| 10 | 2025-10-23 | 熱身3k 1600x4 | 4 × 1600 | 2000、2000、2000、1000 |
| 15 | 2025-10-09 | 1000間歇x6 3:45/km | 6 × 1000 | 1200、2000、1200、1500 |
| 16 | 2025-10-02 | 200 150 120 150 120 | 200、150、120、150、120 | 最後一趟判成 100 |
| 28 | 2025-08-03 | 1000m x 4 配速4:10～3:50 | 4 × 1000 | 最後一趟判成 400 |
| 34 | 2025-07-07 | 2000m x 3 配速4:00/km | 3 × 2000 | 2000、1200、800、1200、800 |

舊文件寫的「43 次中 37 次完全吻合」沒有驗證腳本可以重跑，已改用上表。切分結果在分析前都會先讓選手確認或修正。

**10/11 修正：最後一趟不再吃進按停止鍵前的那段。** 選手跑完最後一趟後慢跑幾秒才按停止鍵，舊版會把結束點對齊到停止鍵（`TIMER_SNAP_S` 12 秒內），把那幾秒算進最後一趟。例如 10/8 的 4 × 1200，第 4 趟被算成 274 秒（3:48/km），實際是 265 秒（3:41/km）。現在如果手錶的自動距離分圈從這一趟開始累計剛好達到標準距離，而之後只剩結束那一圈、長度不超過 12 秒，就以那一圈的終點作為結束點（`_end_on_distance_laps`）。在 Garmin 匯出的全部紀錄上比對：只有 10 筆的最後一趟縮短 1–9 秒，沒有任何紀錄的類型或趟數改變；40 筆驗證維持 35/40。

依據這份驗證的設定：`workout_segmentation.py` 檔案開頭的常數（`MOVING_SPEED`、`MIN_SEPARATION`、`EASY_MARGIN`、`LAP_SNAP_S`、`TIMER_SNAP_S`、`RESUME_LAG_S` 等）與函式內的調校數字，以及 `workout_prescription.py` 的推估規則（距離比對容許 20%、漸速分組 2 秒／5 秒、休息進位到 15 秒）。

課表推估的配速進位（每公里取到 5 秒、每趟取到偶數或 5 的倍數秒）只影響推估結構的**顯示**；推估的目標不評分，這次也沒有驗證。課表要求的配速合理範圍下限 120 秒／公里，比男子 1000 m 世界紀錄（2:11.96，約 132 秒／公里）還快，作為安全下限。

## 對外說法

- 可以說：判讀裡的每個數字都有出處，包括論文、廠商文件、量測誤差，或選手自己的歷史；沒有出處的判斷不做，只顯示數字。
- 可以說：休息心率恢復與同配速心率的比較，門檻來自已發表的量測誤差，並用運動科學常用的統計方法推算。
- 可以說：切分演算法用 40 筆選手確認過的真實課表驗證，35 筆完全吻合，驗證腳本可以重跑。
- 可以說：好壞判斷只在有依據時才給——教練自己設定的範圍或上限，以及「同樣或更快的配速下心率更低」（Buchheit 2014）。
- 不要說：心率變高代表疲勞（Buchheit 2014 明確反對）；「平常範圍」只說明數字是否不尋常，不代表好壞。

## 參考文獻

- Aubry A, Hausswirth C, Louis J, Coutts AJ, Buchheit M, Le Meur Y (2015). The development of functional overreaching is associated with a faster heart rate recovery in endurance athletes. *PLOS ONE* 10. doi:10.1371/journal.pone.0139754
- Bellenger CR, Fuller JT, Thomson RL, Davison K, Robertson EY, Buckley JD (2016). Monitoring athletic training status through autonomic heart rate regulation: a systematic review and meta-analysis. *Sports Medicine* 46:1461–1486. doi:10.1007/s40279-016-0484-2
- Bishop D (2003). Warm up II: performance changes following active warm up and how to structure the warm up. *Sports Medicine* 33:483–498. doi:10.2165/00007256-200333070-00002
- Bonato M, Meloni A, Merati G, La Torre A, Agnello L, Vernillo G (2018). Effect of repeated-sprints on the reliability of short-term parasympathetic reactivation. *PLOS ONE* 13. doi:10.1371/journal.pone.0192231
- Buchheit M, Laursen PB (2013). High-intensity interval training, solutions to the programming puzzle: Part I: cardiopulmonary emphasis. *Sports Medicine* 43:313–338. doi:10.1007/s40279-013-0029-x
- Buchheit M (2014). Monitoring training status with HR measures: do all roads lead to Rome? *Frontiers in Physiology* 5:73. doi:10.3389/fphys.2014.00073
- Fecchio RY, Brito L, Leicht AS, Forjaz CLM, Peçanha T (2019). Reproducibility of post-exercise heart rate recovery indices: a systematic review. *Autonomic Neuroscience* 221:102582. doi:10.1016/j.autneu.2019.102582
- Gilgen-Ammann R, Schweizer T, Wyss T (2020). Accuracy of distance recordings in eight positioning-enabled sport watches: instrument validation study. *JMIR mHealth and uHealth* 8. doi:10.2196/17118
- Hopkins WG (2004). How to interpret changes in an athletic performance test. *Sportscience* 8:1–7. <https://sportsci.org/jour/04/wghtests.htm>
- Hopkins WG, Hewson DJ (2001). Variability of competitive performance of distance runners. *Medicine & Science in Sports & Exercise* 33:1588–1592. doi:10.1097/00005768-200109000-00023
- Killick R, Fearnhead P, Eckley IA (2012). Optimal detection of changepoints with a linear computational cost. *Journal of the American Statistical Association* 107:1590–1598.
- Lamberts RP, Lemmink KA, Durandt JJ, Lambert MI (2004). Variation in heart rate during submaximal exercise: implications for monitoring training. *Journal of Strength and Conditioning Research* 18:641–645.
- Seiler S (2010). What is best practice for training intensity and duration distribution in endurance athletes? *International Journal of Sports Physiology and Performance* 5:276–291. doi:10.1123/ijspp.5.3.276
- Silva Oliveira P, Boppre G, Fonseca H (2024). Comparison of polarized versus other types of endurance training intensity distribution on athletes' endurance performance: a systematic review with meta-analysis. *Sports Medicine*. doi:10.1007/s40279-024-02034-z
- Smyth B, Maunder E, Meyler S, Hunter B, Muniz-Pumares D (2022). Decoupling of internal and external workload during a marathon: an analysis of durability in 82,303 recreational runners. *Sports Medicine* 52:2283–2295. doi:10.1007/s40279-022-01680-5
- Tanaka H, Monahan KD, Seals DR (2001). Age-predicted maximal heart rate revisited. *Journal of the American College of Cardiology* 37:153–156. doi:10.1016/s0735-1097(00)01054-8
- Van Hooren B, Peake JM (2018). Do we need a cool-down after exercise? A narrative review of the psychophysiological effects and the effects on performance, injuries and the long-term adaptive response. *Sports Medicine* 48:1575–1595.
- Friel J. Aerobic Decoupling and Heart Rate Drift Explained. TrainingPeaks. <https://www.trainingpeaks.com/coach-blog/aerobic-endurance-and-decoupling/>
- Garmin. Heart Rate Zone Calculations（Forerunner 245 等機型使用手冊）. <https://www8.garmin.com/manuals/webhelp/forerunner245/EN-US/GUID-30C91919-943C-44E9-8048-901AC0881AEA.html>
