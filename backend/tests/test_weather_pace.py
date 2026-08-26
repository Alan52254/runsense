"""Pure unit tests -- no DB needed.

Coefficients come from a least-squares fit of El Helou et al. (2012)'s
Table S3 P1 (elite/fastest-finisher) tier (see app/weather_pace.py's module
docstring for the fit methodology and the raw published points). These
tests check the properties that fit must have, not specific fitted
numbers, so they stay meaningful if the coefficients are ever re-fit from
a corrected transcription of the table.
"""

from __future__ import annotations

from app.weather_pace import acclimatization_multiplier, speed_loss_pct, speed_loss_pct_relative_to_normal


def test_at_each_sex_own_optimum_loss_is_near_zero():
    # Men's P1 optimum is ~3.75°C, women's ~9.83°C (paper's own stated P1
    # optima are 3.81°C / 9.9°C) -- loss right at the fitted vertex should
    # be ~0, not just "small".
    assert speed_loss_pct(3.75, "male") < 0.05
    assert speed_loss_pct(9.8, "female") < 0.05


def test_loss_increases_moving_away_from_the_optimum_either_direction():
    optimum = speed_loss_pct(3.75, "male")
    colder = speed_loss_pct(-3.0, "male")
    hotter = speed_loss_pct(25.0, "male")
    assert colder > optimum
    assert hotter > optimum


def test_hotter_than_optimum_costs_more_than_symmetrically_colder():
    # The published table itself isn't perfectly symmetric (e.g. men P1:
    # -10° -> 1.41% vs +10° -> 1.44%), and marathon race temperatures skew
    # warm, so the fit's hot side should be at least as steep as the cold
    # side far from the optimum.
    male_optimum = 3.8
    hot = speed_loss_pct(male_optimum + 20, "male")
    cold = speed_loss_pct(male_optimum - 10, "male")
    assert hot > cold


def test_never_negative():
    assert speed_loss_pct(3.8, "male") >= 0
    assert speed_loss_pct(50.0, "male") >= 0
    assert speed_loss_pct(-30.0, "female") >= 0


def test_men_and_women_curves_differ():
    # Same temperature, different optimum per sex -- the two curves must
    # not collapse to the same number away from where they happen to cross.
    assert speed_loss_pct(20.0, "male") != speed_loss_pct(20.0, "female")


def test_unset_sex_averages_the_two_curves_rather_than_guessing():
    male = speed_loss_pct(22.0, "male")
    female = speed_loss_pct(22.0, "female")
    neutral = speed_loss_pct(22.0, None)
    assert neutral == round((male + female) / 2, 2)


def test_extreme_temperature_holds_flat_at_the_papers_measured_boundary():
    # Table S3 only measured up to vertex+20°C per curve; a genuinely hot
    # day (e.g. 45°C) must not extrapolate the quadratic further out --
    # it should return exactly what vertex+20 returns.
    at_boundary = speed_loss_pct(23.7549, "male")  # men's P1 vertex (3.7549) + 20
    far_past_boundary = speed_loss_pct(45.0, "male")
    assert far_past_boundary == at_boundary


def test_extreme_cold_holds_flat_at_the_papers_measured_boundary():
    at_boundary = speed_loss_pct(-6.2451, "male")  # men's P1 vertex (3.7549) - 10
    far_past_boundary = speed_loss_pct(-30.0, "male")
    assert far_past_boundary == at_boundary


class TestAcclimatizationMultiplier:
    """See weather_pace.py's module docstring for why this is a bounded,
    evidence-anchored heuristic rather than a citation-derived formula."""

    def test_no_change_when_todays_temperature_matches_the_normal(self):
        assert acclimatization_multiplier(20.0, 20.0) == 1.0

    def test_colder_than_normal_discounts_the_penalty(self):
        assert acclimatization_multiplier(15.0, 20.0) < 1.0

    def test_hotter_than_normal_amplifies_the_penalty(self):
        assert acclimatization_multiplier(25.0, 20.0) > 1.0

    def test_discount_saturates_at_the_evidence_anchored_ceiling(self):
        at_5_below = acclimatization_multiplier(15.0, 20.0)
        at_10_below = acclimatization_multiplier(10.0, 20.0)
        assert at_5_below == at_10_below == 0.95  # -5% ceiling, see Zurawlew et al. citation above

    def test_amplification_saturates_at_the_evidence_anchored_ceiling(self):
        at_5_above = acclimatization_multiplier(25.0, 20.0)
        at_10_above = acclimatization_multiplier(30.0, 20.0)
        assert at_5_above == at_10_above == 1.05

    def test_scales_linearly_between_the_ceilings(self):
        quarter_way = acclimatization_multiplier(18.75, 20.0)  # 1.25C colder, 1/4 of the 5C saturation range
        assert quarter_way == round(1 - 0.25 * 0.05, 6)


class TestSpeedLossPctRelativeToNormal:
    """See speed_loss_pct_relative_to_normal's docstring: this is literally
    speed_loss_pct read at two temperatures and subtracted -- two ordinary
    lookups on the paper's own published curve, not a curve re-derived
    around the reference. That's why it can go negative (a day genuinely
    cooler than the reference is a real pace bonus) and why "moving away
    from the reference" doesn't always cost more in both directions once
    the reference itself is already far from the paper's true P1 optimum
    (~3.75C men, ~9.83C women) -- moving from a hot reference *toward*
    that true optimum reduces the cost, it doesn't increase it."""

    def test_is_exactly_zero_at_the_reference_temperature(self):
        # A point minus itself, always exactly 0 -- not just "small".
        assert speed_loss_pct_relative_to_normal(29.5, 29.5, "male") == 0.0
        assert speed_loss_pct_relative_to_normal(15.0, 15.0, "female") == 0.0

    def test_equals_the_plain_difference_of_two_absolute_lookups(self):
        # The defining contract: not an approximation, the literal
        # subtraction of two speed_loss_pct readings. Both points must
        # stay inside the men's P1 measured domain (boundary ~23.75C) --
        # past it, speed_loss_pct_relative_to_normal intentionally departs
        # from speed_loss_pct (tangent-line extrapolation vs. a flat
        # clamp, see _speed_loss_pct_for_difference's docstring).
        temp, reference, sex = 20.0, 10.0, "male"
        expected = round(speed_loss_pct(temp, sex) - speed_loss_pct(reference, sex), 2)
        assert speed_loss_pct_relative_to_normal(temp, reference, sex) == expected

    def test_hotter_than_reference_costs_more(self):
        # Reference (15C) is inside the paper's measured domain; the
        # hotter point (25C) is just past the men's P1 boundary (~23.75C)
        # and uses the tangent-line extrapolation -- still strictly
        # increasing past the reference either way.
        at_reference = speed_loss_pct_relative_to_normal(15.0, 15.0, "male")
        hotter = speed_loss_pct_relative_to_normal(25.0, 15.0, "male")
        assert hotter > at_reference

    def test_moving_from_a_hot_reference_toward_the_true_optimum_is_a_bonus_not_a_cost(self):
        # Reference is a hot evening (29.5C, well past the paper's ~3.75C
        # P1 optimum); 24C is still hot but closer to the true optimum, so
        # the paper's own curve says it costs LESS than the reference --
        # a negative relative figure, i.e. a genuine pace bonus. A
        # re-centered-curve implementation could never produce this
        # (floored every case at >= 0), which is exactly what this fix
        # corrects per the paper's actual published values.
        assert speed_loss_pct_relative_to_normal(24.0, 29.5, "male") < 0

    def test_moving_the_reference_moves_the_zero_point_with_it(self):
        # Same actual temperature, different climate normal on file --
        # a Taipei summer's 30C should read as "close to normal" while a
        # London summer's 30C should read as "unusually hot".
        taipei_like = speed_loss_pct_relative_to_normal(30.0, 29.5, "male")
        london_like = speed_loss_pct_relative_to_normal(30.0, 19.0, "male")
        assert taipei_like < london_like

    def test_equals_the_absolute_curve_when_the_reference_is_the_papers_own_optimum(self):
        # speed_loss_pct at the curve's own vertex floors to exactly 0
        # (the fitted vertex value is a hair below 0), so subtracting it
        # is a no-op and this must reduce to speed_loss_pct exactly --
        # true for any t inside speed_loss_pct's own (narrower) domain.
        # Past that boundary the two intentionally diverge (see
        # _speed_loss_pct_for_difference), so this only checks values
        # within both domains (men's P1 boundary is vertex+20 = 23.7549).
        men_vertex_c = 3.7549
        assert speed_loss_pct(men_vertex_c, "male") == 0.0
        for t in (-3.0, 3.7549, 15.0, 20.0):
            assert speed_loss_pct_relative_to_normal(t, men_vertex_c, "male") == speed_loss_pct(t, "male")

    def test_past_the_measured_boundary_keeps_a_hot_citys_intraday_comparisons_meaningful(self):
        # The concrete problem the tangent-line extrapolation fixes: an
        # ordinary Taipei August evening (~31.3C) already exceeds
        # speed_loss_pct's ~23.75C men's P1 boundary. Comparing any two
        # points that both exceed that boundary (e.g. a hot midday against
        # that hot evening) would, under a flat clamp, both read as the
        # identical value and subtract to 0%, hiding a real multi-degree
        # gap -- confirmed here that it does not.
        evening_reference_c = 31.3
        hotter_midday_c = 33.8
        assert speed_loss_pct(evening_reference_c, "male") == speed_loss_pct(hotter_midday_c, "male")  # both clamp
        assert speed_loss_pct_relative_to_normal(hotter_midday_c, evening_reference_c, "male") > 0

    def test_extrapolation_past_the_boundary_is_more_conservative_than_continuing_the_quadratic(self):
        # The tangent-line extrapolation must grow slower than the raw
        # quadratic would past the measured boundary (23.7549C for men
        # P1) -- that's the whole point of not continuing the quadratic's
        # own ever-steepening curvature into unvalidated territory.
        men_vertex_c = 3.7549
        a, b, c = 0.01490000, -0.111895, 0.175031
        far_past_boundary_c = 34.2
        raw_quadratic_value = a * far_past_boundary_c**2 + b * far_past_boundary_c + c
        tangent_value = speed_loss_pct_relative_to_normal(far_past_boundary_c, men_vertex_c, "male")
        assert tangent_value < raw_quadratic_value

    def test_men_and_women_differ_at_the_same_reference(self):
        assert speed_loss_pct_relative_to_normal(25.0, 15.0, "male") != speed_loss_pct_relative_to_normal(
            25.0, 15.0, "female"
        )

    def test_unset_sex_averages_the_two_curves(self):
        male = speed_loss_pct_relative_to_normal(25.0, 10.0, "male")
        female = speed_loss_pct_relative_to_normal(25.0, 10.0, "female")
        neutral = speed_loss_pct_relative_to_normal(25.0, 10.0, None)
        assert neutral == round((male + female) / 2, 2)
