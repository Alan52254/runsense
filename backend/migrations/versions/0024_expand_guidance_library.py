"""backfill retrieval facets and expand the reviewed guidance library

Two things happen here, in this order for a reason. First the nine existing
passages get the facets retrieval now narrows on, so nothing already in the
corpus becomes unreachable. Only then is the library grown: with facets in
place, added sources sharpen retrieval instead of diluting it.

The added content is staged: for each body area the interface offers, a
protection stage, a progressive-loading stage, and a return-to-run stage,
each stating what it is for and what would let the Athlete move past it. No
passage states a diagnosis, names a medication, or claims to replace a
clinician; each links to its publisher's own page and carries a manually
authored summary rather than ingested source text.

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

_CORPUS = "sports-medicine-v1"
_REVISION_DATE = "2026-08-30"
_PROVENANCE = "link-and-manually-authored-summary; source text not ingested"


# --------------------------------------------------------------------------
# Facets for what is already there
# --------------------------------------------------------------------------

_EXISTING_FACETS: dict[str, dict[str, object]] = {
    "aaos-calf-strain-return-to-run": {
        "body_parts": ["calf", "小腿", "hamstring", "大腿後側"],
        "topics": ["muscle_strain", "return_to_run"],
    },
    "aaos-runners-knee-load-management": {
        "body_parts": ["knee", "膝蓋"],
        "topics": ["training_load", "strength"],
    },
    "aaos-achilles-tendinopathy-first-steps": {
        "body_parts": ["achilles", "阿基里斯腱", "跟腱"],
        "topics": ["tendon", "training_load"],
    },
    "aaos-plantar-fasciitis-self-care": {
        "body_parts": ["plantar", "足底筋膜", "foot", "腳掌"],
        "topics": ["self_care"],
    },
    "aaos-shin-splints-conservative": {
        "body_parts": ["shin", "小腿脛骨", "脛骨"],
        "topics": ["training_load", "bone_stress"],
    },
    "acsm-low-back-running": {
        "body_parts": ["low back", "下背", "腰"],
        "topics": ["self_care"],
    },
    "aaos-hip-glute-tendinopathy": {
        "body_parts": ["hip", "髖關節", "glute", "臀"],
        "topics": ["tendon", "strength"],
    },
    "runsense-general-load-management": {"body_parts": [], "topics": ["training_load"]},
    "runsense-when-to-see-a-clinician": {"body_parts": [], "topics": ["red_flags"]},
    "aaos-stress-fracture-warning-signs": {
        "body_parts": ["shin", "小腿脛骨", "foot", "腳掌"],
        "topics": ["bone_stress", "red_flags"],
    },
}


# --------------------------------------------------------------------------
# Staged protocols, one set per body area the interface offers
# --------------------------------------------------------------------------

_AREAS: dict[str, dict[str, object]] = {
    "calf": {
        "label": "小腿",
        "body_parts": ["calf", "小腿"],
        "publisher": "AAOS OrthoInfo",
        "source_url": "https://orthoinfo.aaos.org/en/diseases--conditions/muscle-strains-in-the-thigh/",
        "protection": "急性期以保護為主：避免會引發疼痛的推蹬與衝刺，走路以能無痛完成的步幅為準。",
        "loading": "疼痛穩定後開始漸進負荷：從雙腳提踵到單腳提踵，再加入無痛的交叉訓練維持有氧。",
        "return": "回場測試：單腳連續提踵 20 下無痛、原地單腳跳 10 下無痛，才開始走跑交替。",
    },
    "knee": {
        "label": "膝蓋",
        "body_parts": ["knee", "膝蓋"],
        "publisher": "AAOS OrthoInfo",
        "source_url": "https://orthoinfo.aaos.org/en/diseases--conditions/patellofemoral-pain-syndrome/",
        "protection": "先降低會誘發前膝疼痛的動作：長下坡、深蹲與大幅增加的里程暫時避開。",
        "loading": "以無痛範圍的髖外展與股四頭肌訓練為主，配合不引發症狀的交叉訓練維持體能。",
        "return": "回場測試：上下樓梯與深蹲到 60 度皆無痛，再以短距離平路慢跑重新開始。",
    },
    "achilles": {
        "label": "阿基里斯腱",
        "body_parts": ["achilles", "阿基里斯腱", "跟腱"],
        "publisher": "AAOS OrthoInfo",
        "source_url": "https://orthoinfo.aaos.org/en/diseases--conditions/achilles-tendinitis/",
        "protection": "先移除肌腱的尖峰負荷：坡度訓練與速度課表暫停，晨起僵硬程度可作為觀察指標。",
        "loading": "以等長與慢速離心的小腿訓練漸進加載，肌腱在訓練隔天不應比前一天更僵硬。",
        "return": "回場測試：晨起僵硬明顯減少、單腳提踵無痛，再從平路輕鬆跑開始，坡度最後才加回。",
    },
    "plantar": {
        "label": "足底筋膜",
        "body_parts": ["plantar", "足底筋膜", "foot", "腳掌"],
        "publisher": "AAOS OrthoInfo",
        "source_url": "https://orthoinfo.aaos.org/en/diseases--conditions/plantar-fasciitis-and-bone-spurs/",
        "protection": "急性期減少赤足硬地行走與長時間站立；晨起第一步的疼痛程度是最直接的觀察指標。",
        "loading": "加入足底與小腿的漸進負荷訓練，並確認鞋具能支撐目前的訓練量。",
        "return": "回場測試：晨起第一步幾乎無痛、快走 20 分鐘無症狀，再開始短距離慢跑。",
    },
    "shin": {
        "label": "小腿脛骨",
        "body_parts": ["shin", "小腿脛骨", "脛骨"],
        "publisher": "AAOS OrthoInfo",
        "source_url": "https://orthoinfo.aaos.org/en/diseases--conditions/shin-splints/",
        "protection": "先降低衝擊量並改以無衝擊的交叉訓練；若疼痛集中在單一點且負重加劇，屬於需要就醫評估的情況。",
        "loading": "疼痛範圍轉為瀰漫且明顯減輕後，才以小幅度增加的走跑交替重新累積衝擊耐受。",
        "return": "回場測試：單腳跳 10 下無痛、快走 30 分鐘無症狀，之後每週增加量不超過既有基準的一成。",
    },
    "hamstring": {
        "label": "大腿後側",
        "body_parts": ["hamstring", "大腿後側", "腿後"],
        "publisher": "AAOS OrthoInfo",
        "source_url": "https://orthoinfo.aaos.org/en/diseases--conditions/muscle-strains-in-the-thigh/",
        "protection": "急性期避免拉長範圍的動作與加速跑，日常活動以無痛範圍為界。",
        "loading": "以等長與可控範圍的離心訓練漸進加載，配合無痛的有氧交叉訓練。",
        "return": "回場測試：能無痛完成中等強度的加速跑，再逐步把速度課表加回。",
    },
    "hip": {
        "label": "髖關節",
        "body_parts": ["hip", "髖關節", "glute", "臀"],
        "publisher": "AAOS OrthoInfo",
        "source_url": "https://orthoinfo.aaos.org/en/diseases--conditions/hip-strains/",
        "protection": "先避免會壓迫外側的姿勢（翹腳、側躺壓患側）與長距離的側傾路面跑。",
        "loading": "以等長臀中肌訓練起步，再進到可控的負重訓練，過程以隔天症狀不加重為原則。",
        "return": "回場測試：單腳站立 30 秒穩定無痛、上樓梯無症狀，再回到平路慢跑。",
    },
}

_STAGES = (
    (
        "PROTECTION",
        "protection",
        "急性保護期",
        "在不讓組織持續受刺激的前提下維持日常活動，讓修復有機會開始。",
        "疼痛在休息時明顯下降、日常走動不再誘發症狀。",
    ),
    (
        "LOADING",
        "loading",
        "漸進加載期",
        "以可控的負荷讓組織重新適應，避免完全休息帶來的能力流失。",
        "訓練隔天症狀沒有比前一天更嚴重，且能完成無痛的交叉訓練。",
    ),
    (
        "RETURN_TO_RUN",
        "return",
        "回場跑測試",
        "用可重複的測試確認組織已能承受跑步的衝擊，而不是靠感覺猜測。",
        "能通過該部位的回場測試，且測試後 24 小時內症狀沒有回升。",
    ),
)


def _protocol_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for area_id, area in _AREAS.items():
        for phase, key, stage_label, purpose, criterion in _STAGES:
            rows.append(
                {
                    "evidence_id": f"protocol-{area_id}-{phase.lower()}",
                    "title": f"{area['label']}｜{stage_label}",
                    "publisher": area["publisher"],
                    "source_url": area["source_url"],
                    "text": area[key],
                    "keywords": list(area["body_parts"]) + [stage_label],
                    "body_parts": list(area["body_parts"]),
                    "topics": ["staged_protocol"],
                    "phase": phase,
                    "phase_purpose": purpose,
                    "progression_criterion": criterion,
                }
            )
    return rows


# --------------------------------------------------------------------------
# General guidance the coach leans on whatever the Athlete reported
# --------------------------------------------------------------------------

_GENERAL = [
    {
        "evidence_id": "bjsm-acwr-load-paradox",
        "title": "The training-injury prevention paradox",
        "publisher": "British Journal of Sports Medicine",
        "source_url": "https://bjsm.bmj.com/content/50/5/273",
        "text": "近期訓練量相對於長期基準落在約 0.8 至 1.3 之間時，觀察到的受傷率最低；"
        "比值明顯偏高時受傷率隨之上升。這是族群層級的觀察，不是個別跑者的預測。",
        "keywords": ["__general__", "負荷", "訓練量", "acwr", "load", "workload"],
        "body_parts": [],
        "topics": ["training_load"],
        "phase": None,
    },
    {
        "evidence_id": "bjsm-peace-and-love",
        "title": "Soft-tissue injuries simply need PEACE & LOVE",
        "publisher": "British Journal of Sports Medicine",
        "source_url": "https://bjsm.bmj.com/content/54/2/72",
        "text": "軟組織傷害的處理以保護、抬高、適度負重與促進循環為主，取代長時間完全休息；"
        "急性期過度依賴消炎處置可能干擾組織自然修復。",
        "keywords": ["__general__", "軟組織", "急性期", "peace", "love", "soft tissue"],
        "body_parts": [],
        "topics": ["self_care", "staged_protocol"],
        "phase": None,
    },
    {
        "evidence_id": "acsm-exertional-heat-illness",
        "title": "Exertional heat illness during training and competition",
        "publisher": "American College of Sports Medicine",
        "source_url": "https://www.acsm.org/",
        "text": "氣溫與濕度同時偏高時散熱效率下降、心血管負擔上升，配速應主動放慢並提高補水頻率；"
        "出現意識混亂、停止流汗或步態不穩時應立即停止運動並尋求協助。",
        "keywords": ["__general__", "高溫", "濕度", "中暑", "heat", "humidity", "hydration"],
        "body_parts": [],
        "topics": ["heat", "red_flags"],
        "phase": None,
    },
    {
        "evidence_id": "acsm-hydration-for-runners",
        "title": "Fluid replacement for physical activity",
        "publisher": "American College of Sports Medicine",
        "source_url": "https://www.acsm.org/",
        "text": "補水以避免明顯脫水與過量飲水兩端為原則，依個人流汗率與環境調整，"
        "而不是套用固定毫升數；長時間高溫運動時同時補充電解質。",
        "keywords": ["__general__", "補水", "水分", "電解質", "hydration", "fluid"],
        "body_parts": [],
        "topics": ["heat", "nutrition"],
        "phase": None,
    },
    {
        "evidence_id": "bjsm-sleep-and-recovery",
        "title": "Sleep and the athlete: narrative review",
        "publisher": "British Journal of Sports Medicine",
        "source_url": "https://bjsm.bmj.com/content/55/7/356",
        "text": "睡眠不足與訓練耐受度下降、主觀疲勞上升有關；"
        "連續數日睡眠不足時，維持既有訓練量的風險高於少練一次。",
        "keywords": ["__general__", "睡眠", "疲勞", "恢復", "sleep", "recovery", "fatigue"],
        "body_parts": [],
        "topics": ["recovery"],
        "phase": None,
    },
    {
        "evidence_id": "bjsm-return-to-run-criteria",
        "title": "Criteria-based return to running",
        "publisher": "British Journal of Sports Medicine",
        "source_url": "https://bjsm.bmj.com/",
        "text": "回到跑步的時機以能否通過可重複的測試為準，而不是以休息天數為準；"
        "常見門檻包含無痛的單腳跳與快走測試，且測試後 24 小時內症狀不回升。",
        "keywords": ["__general__", "回場", "重新開始跑", "return to run", "criteria"],
        "body_parts": [],
        "topics": ["staged_protocol", "return_to_run"],
        "phase": None,
    },
]


_NEW_EDGES = [
    (f"protocol-{area}-protection", f"protocol-{area}-loading", "PROGRESSES_TO")
    for area in _AREAS
] + [
    (f"protocol-{area}-loading", f"protocol-{area}-return_to_run", "PROGRESSES_TO")
    for area in _AREAS
] + [
    ("bjsm-acwr-load-paradox", "runsense-general-load-management", "SUPPORTS"),
    ("bjsm-peace-and-love", "bjsm-return-to-run-criteria", "PROGRESSES_TO"),
    ("acsm-exertional-heat-illness", "acsm-hydration-for-runners", "SUPPORTS"),
    ("acsm-exertional-heat-illness", "runsense-when-to-see-a-clinician", "ESCALATES_TO"),
]


_ROW_COLUMNS = (
    "evidence_id",
    "title",
    "publisher",
    "source_url",
    "revision_date",
    "license_or_provenance",
    "corpus_version",
    "text",
    "keywords",
    "body_parts",
    "topics",
    "phase",
    "phase_purpose",
    "progression_criterion",
    "approved",
)


def _all_new_rows() -> list[dict[str, object]]:
    """Every row carries every column, explicitly None where it has no value.

    bulk_insert builds one statement for the batch, so a row that simply
    omits a key does not get a NULL -- it either fails or silently drops the
    column for the whole batch. The staged passages would have lost their
    purpose and progression text that way.
    """
    return [
        {
            column: {
                **row,
                "revision_date": _REVISION_DATE,
                "license_or_provenance": _PROVENANCE,
                "corpus_version": _CORPUS,
                "approved": True,
            }.get(column)
            for column in _ROW_COLUMNS
        }
        for row in (*_protocol_rows(), *_GENERAL)
    ]


def upgrade() -> None:
    # 1. Nothing already in the corpus becomes unreachable.
    for evidence_id, facets in _EXISTING_FACETS.items():
        op.execute(
            sa.text(
                "UPDATE evidence_passages "
                "SET body_parts = :body_parts, topics = :topics "
                "WHERE evidence_id = :evidence_id"
            ).bindparams(
                sa.bindparam("body_parts", value=facets["body_parts"], type_=sa.ARRAY(sa.Text())),
                sa.bindparam("topics", value=facets["topics"], type_=sa.ARRAY(sa.Text())),
                sa.bindparam("evidence_id", value=evidence_id),
            )
        )

    # 2. Only then does the library grow.
    passages = sa.table(
        "evidence_passages",
        sa.column("evidence_id", sa.Text()),
        sa.column("title", sa.Text()),
        sa.column("publisher", sa.Text()),
        sa.column("source_url", sa.Text()),
        sa.column("revision_date", sa.Date()),
        sa.column("license_or_provenance", sa.Text()),
        sa.column("corpus_version", sa.Text()),
        sa.column("text", sa.Text()),
        sa.column("keywords", sa.ARRAY(sa.Text())),
        sa.column("body_parts", sa.ARRAY(sa.Text())),
        sa.column("topics", sa.ARRAY(sa.Text())),
        sa.column("phase", sa.Text()),
        sa.column("phase_purpose", sa.Text()),
        sa.column("progression_criterion", sa.Text()),
        sa.column("approved", sa.Boolean()),
    )
    op.bulk_insert(passages, _all_new_rows())

    for source_id, target_id, relationship in _NEW_EDGES:
        op.execute(
            sa.text(
                "INSERT INTO evidence_edges (source_id, target_id, relationship) "
                "VALUES (:s, :t, :r)"
            ).bindparams(s=source_id, t=target_id, r=relationship)
        )


def downgrade() -> None:
    ids = tuple(row["evidence_id"] for row in _all_new_rows())
    op.execute(
        sa.text(
            "DELETE FROM evidence_edges WHERE source_id IN :ids OR target_id IN :ids"
        ).bindparams(sa.bindparam("ids", value=ids, expanding=True))
    )
    op.execute(
        sa.text("DELETE FROM evidence_passages WHERE evidence_id IN :ids").bindparams(
            sa.bindparam("ids", value=ids, expanding=True)
        )
    )
    op.execute(
        "UPDATE evidence_passages SET body_parts = '{}'::text[], topics = '{}'::text[]"
    )
