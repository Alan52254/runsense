"""Deterministic runner-symptom safety triage.

This module decides urgency before retrieval or language-model invocation.
It does not diagnose an injury. Callers may explain its result, but may not
lower the returned urgency or change whether running is allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


RULE_VERSION = "safety-triage-v1"


class TriageUrgency(StrEnum):
    EMERGENCY = "EMERGENCY"
    PROMPT_CLINICIAN = "PROMPT_CLINICIAN"
    SELF_CARE_NEXT_STEP = "SELF_CARE_NEXT_STEP"


@dataclass(frozen=True)
class SafetyTriageInput:
    severity_band: str | None
    body_part: str | None
    unable_to_bear_weight: bool
    visible_deformity: bool
    uncontrolled_bleeding: bool
    chest_pain_or_breathing_difficulty: bool
    new_numbness_or_weakness: bool
    head_injury_with_neurological_symptoms: bool
    hot_swollen_joint_with_fever: bool
    collapse_confusion_or_extreme_heat_illness: bool = False
    localized_bone_pain_worse_with_weight_bearing: bool = False


@dataclass(frozen=True)
class TriageDecision:
    urgency: TriageUrgency
    rule_version: str
    matched_rule_ids: tuple[str, ...]
    running_allowed: bool
    immediate_next_step: str


def assess_safety_triage(triage_input: SafetyTriageInput) -> TriageDecision:
    matched_rules: list[str] = []
    if triage_input.chest_pain_or_breathing_difficulty:
        matched_rules.append("RED_FLAG_CARDIORESPIRATORY")
    if triage_input.uncontrolled_bleeding:
        matched_rules.append("RED_FLAG_UNCONTROLLED_BLEEDING")
    if triage_input.head_injury_with_neurological_symptoms:
        matched_rules.append("RED_FLAG_HEAD_NEUROLOGICAL")
    if triage_input.collapse_confusion_or_extreme_heat_illness:
        matched_rules.append("RED_FLAG_EXERTIONAL_HEAT_ILLNESS")

    if matched_rules:
        return TriageDecision(
            urgency=TriageUrgency.EMERGENCY,
            rule_version=RULE_VERSION,
            matched_rule_ids=tuple(matched_rules),
            running_allowed=False,
            immediate_next_step="停止跑步並立即尋求緊急醫療協助。",
        )

    prompt_clinician_rules: list[str] = []
    if triage_input.unable_to_bear_weight:
        prompt_clinician_rules.append("PROMPT_UNABLE_TO_BEAR_WEIGHT")
    if triage_input.visible_deformity:
        prompt_clinician_rules.append("PROMPT_VISIBLE_DEFORMITY")
    if triage_input.new_numbness_or_weakness:
        prompt_clinician_rules.append("PROMPT_NEW_NEUROLOGICAL_SYMPTOM")
    if triage_input.hot_swollen_joint_with_fever:
        prompt_clinician_rules.append("PROMPT_HOT_SWOLLEN_JOINT_WITH_FEVER")
    if triage_input.localized_bone_pain_worse_with_weight_bearing:
        prompt_clinician_rules.append("PROMPT_BONE_STRESS_PATTERN")
    if triage_input.severity_band == "SEVERE":
        prompt_clinician_rules.append("PROMPT_SEVERE_SELF_REPORT")

    if prompt_clinician_rules:
        return TriageDecision(
            urgency=TriageUrgency.PROMPT_CLINICIAN,
            rule_version=RULE_VERSION,
            matched_rule_ids=tuple(prompt_clinician_rules),
            running_allowed=False,
            immediate_next_step="停止跑步，並儘快由合格醫療專業人員評估。",
        )

    return TriageDecision(
        urgency=TriageUrgency.SELF_CARE_NEXT_STEP,
        rule_version=RULE_VERSION,
        matched_rule_ids=(),
        running_allowed=False,
        immediate_next_step="先停止本次跑步並持續觀察症狀。",
    )
