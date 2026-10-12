選手在描述自己的身體狀況。只根據「選手本人」說的話，輸出 JSON：
{"body_part": "部位（原文用詞），沒提就 null",
 "pain_score": 選手自己說的 0-10 疼痛分數，沒說就 null（不可自己估）,
 "description": "用一句話整理選手描述的狀況（不加入原文沒有的內容）",
 "red_flags": {"chest_pain_or_breathing_difficulty": false, "collapse_confusion_or_extreme_heat_illness": false,
   "head_injury_with_neurological_symptoms": false, "uncontrolled_bleeding": false,
   "localized_bone_pain_worse_with_weight_bearing": false, "unable_to_bear_weight": false,
   "new_numbness_or_weakness": false, "hot_swollen_joint_with_fever": false, "visible_deformity": false}}
只有選手明確描述到的症狀才設為 true。
