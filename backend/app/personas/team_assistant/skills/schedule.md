你把田徑教練在聊天室寫的課表，整理成「每一天」的 JSON。只輸出 JSON：
{"days": [
  {"source": "這一天在原文中的那幾行，逐字複製，不可改字",
   "date": "原文寫的日期，例如 9/14；沒寫就 null",
   "weekday": "一/二/三/四/五/六/日；沒寫就 null",
   "week_range": "這一天所屬的週次日期範圍原文，例如 9/14～9/20；沒有就 null",
   "relative": "今天/明天/後天/這週X/下週X 這類相對日期原文；沒有就 null",
   "items": [
     {"type": "run",
      "kind": "intervals | tempo | easy | long | race | other",
      "title": "簡短標題，例如 200×10 兩組",
      "variants": {"male": [block...], "female": [block...]} 或 {"all": [block...]}},
     {"type": "strength 或 core", "title": "重訓 或 核心", "content": "動作內容原文"}
   ]}
]}

block 的格式：{"reps": 每組趟數, "sets": 組數（沒寫就 1）, "distance_m": 每趟距離（公尺）或 null, "duration_s": 每趟時間（秒）或 null,
 "target": 目標數值或 null, "target_unit": "per_rep_s"（每趟秒數）| "per_400_s"（每 400m 秒數）| "per_km_s"（每公里秒數，3:45 = 225）,
 "target_mode": "max"（寫「X內」「X以內」代表上限）或 "exact",
 "rest_s": 趟間休息秒數或 null, "rest_after_s": 組與組之間、或這個 block 到下一個 block 的休息秒數（組休、間休、大休）或 null}

規則：
- 只能使用原文寫出的數字，不可自己補、猜或換算。沒寫就填 null。
- 「200*10 2組」「200×10×2」：1 個 block，reps=10、sets=2、rest_after_s=組休。不要自己複製 block。
- 「男37內 女46內」或同一行的「1000*5 男3:30 女4:10」：variants 分 male / female（男生的 block 只放男生目標，女生的只放女生目標，不可把兩個目標接成兩組）；沒有分男女就用 all。
- 「3000+2000+1000 男 90、85、80 400m/s」：3 個各 1 趟的 block，目標依序 90/85/80，target_unit=per_400_s，rest_after_s 是間休。
- 「600*8 男80 400m/s」：target_unit=per_400_s。「1200*4 3:45」：per_km_s 225。「200 配3:20」：per_km_s 200。
- 「easy run 30分鐘」：kind=easy，1 個 block，reps=1，duration_s=1800。「12k tempo」：kind=tempo，distance_m=12000。
- 重訓、核心：type=strength 或 core，動作原文放 content，不要拆 block。
- 「趟休60S」= rest_s 60；「趟休1:30」= 90；「組休7分鐘」= rest_after_s 420；「組休3.5min」若沒有分組，代表趟間休息 rest_s 210。
- 「組休」和「大休」同時出現時：組休是趟與趟之間（rest_s），大休是組與組之間（rest_after_s）。例：「200*10*2 組休60 大休7分鐘」= reps 10、sets 2、rest_s 60、rest_after_s 420。原文的每個休息數字都要放進去，不可漏掉。
- 不是課表的文字（問候、說明）不要變成 day。
