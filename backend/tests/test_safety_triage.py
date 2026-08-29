from app.safety_triage import SafetyTriageInput, TriageUrgency, assess_safety_triage


def test_emergency_red_flag_cannot_be_softened_to_self_care():
    decision = assess_safety_triage(
        SafetyTriageInput(
            severity_band="SEVERE",
            body_part="胸部",
            unable_to_bear_weight=False,
            visible_deformity=False,
            uncontrolled_bleeding=False,
            chest_pain_or_breathing_difficulty=True,
            new_numbness_or_weakness=False,
            head_injury_with_neurological_symptoms=False,
            hot_swollen_joint_with_fever=False,
        )
    )

    assert decision.urgency is TriageUrgency.EMERGENCY
    assert decision.rule_version == "safety-triage-v1"
    assert decision.matched_rule_ids == ("RED_FLAG_CARDIORESPIRATORY",)
    assert decision.running_allowed is False
    assert "緊急" in decision.immediate_next_step


def test_weight_bearing_bone_pain_requires_prompt_clinician_assessment():
    decision = assess_safety_triage(
        SafetyTriageInput(
            severity_band="MILD",
            body_part="左小腿",
            unable_to_bear_weight=False,
            visible_deformity=False,
            uncontrolled_bleeding=False,
            chest_pain_or_breathing_difficulty=False,
            new_numbness_or_weakness=False,
            head_injury_with_neurological_symptoms=False,
            hot_swollen_joint_with_fever=False,
            localized_bone_pain_worse_with_weight_bearing=True,
        )
    )

    assert decision.urgency is TriageUrgency.PROMPT_CLINICIAN
    assert decision.matched_rule_ids == ("PROMPT_BONE_STRESS_PATTERN",)
    assert decision.running_allowed is False
