"""Climate-equivalent pace adjustment, grounded in El Helou N, Tafflet M,
Berthelot G, et al. (2012) "Impact of Environmental Parameters on Marathon
Running Performance." PLOS ONE 7(5): e37407.
https://doi.org/10.1371/journal.pone.0037407

Supplementary Table S3 reports, for men and women each split into four
marathon-finish-time percentiles (P1 = elite/fastest finishers, Q1, median,
Q3), the running speed lost (%) at seven air-temperature points around that
group's own optimal temperature. This module uses each sex's P1-tier curve
(RunSense targets athletes training competitively, not the full recreational
field the Median tier represents), fit as a least-squares quadratic
(numpy.polyfit, degree 2) of `speed_loss_pct = a*T^2 + b*T + c` through the
7 published P1 points per sex from Table S3:
  Men P1:   (-6.19, 1.41), (-1.19, 0.35), (3.81, 0), (8.81, 0.36),
            (13.81, 1.44), (18.81, 3.29), (23.81, 6.00)
  Women P1: (-0.09, 2.97), (4.91, 0.74), (9.91, 0), (14.91, 0.75),
            (19.91, 3.06), (24.91, 7.16), (29.91, 13.47)
Max residual 0.25 percentage points across both curves, and each fitted
vertex lands within ~0.1°C of the paper's own stated P1 optimum (3.81°C
men, 9.9°C women).

Using P1 instead of Median is NOT a uniform "elite athletes are more
heat-resistant" story -- the paper's own discussion explicitly rejects that
premise at a population level ("these elements... are not supported after
analyzing the full range of finisher's data; at a population level,
temperature causes its full effect whatever the initial capacity"), and the
two sexes' P1 curves actually diverge from Median in OPPOSITE directions at
the hot end: men's P1 curve is much flatter than Median (6.00% vs 17.73% at
peak+20°C -- roughly a third of the slope), while women's P1 curve is
slightly STEEPER than Median at peak+20°C (13.47% vs 12.43%). Both sexes
use P1 here for internal consistency (one tier, not a different tier per
sex), not because the paper shows it's uniformly more conservative.

This returns a *percentage* of speed lost, not a seconds/km figure: turning
that into a pace requires a baseline pace to apply it to, which this module
has no opinion about (see DashboardScreen.tsx's adjustedTargetPace for
where that conversion actually happens, against that day's real target pace).

Table S3 itself only measured seven points per curve, from that curve's own
optimum minus ~10°C to plus ~20°C -- a quadratic fit is well-behaved inside
that span but, being unbounded, keeps accelerating outside it. Left
unclamped, a genuinely hot day would extrapolate well past anything the
paper actually measured. `_DOMAIN` below holds each curve flat at its
boundary value instead of extrapolating past it for the headline absolute
figure (speed_loss_pct) -- e.g. for men, +20°C past peak is already the
paper's own peak+20 data point (6.00%), so clamping there returns exactly a
measured number, not a guess. speed_loss_pct_relative_to_normal uses a
gentler tangent-line extrapolation past this same boundary instead -- see
its own docstring for why.
"""

from __future__ import annotations

# (a, b, c) for speed_loss_pct(T) = a*T^2 + b*T + c, least-squares fit to
# the 7 published P1-tier points per sex from Table S3 (see module
# docstring for the exact points), and that curve's own vertex (optimal
# temperature, -b/2a).
_MEN_P1 = (0.01490000, -0.111895, 0.175031)
_MEN_P1_VERTEX_C = 3.7549
_WOMEN_P1 = (0.03334286, -0.655713, 3.051430)
_WOMEN_P1_VERTEX_C = 9.8329

# Table S3's own measured span around each curve's vertex -- used for the
# headline absolute figure (speed_loss_pct), kept conservative per the
# module docstring so a genuinely extreme reading never extrapolates past
# anything the paper actually measured.
_DOMAIN_BELOW_VERTEX_C = 10.0
_DOMAIN_ABOVE_VERTEX_C = 20.0


def _speed_loss_pct(temperature_c: float, coeffs: tuple[float, float, float], vertex_c: float) -> float:
    clamped = min(
        max(temperature_c, vertex_c - _DOMAIN_BELOW_VERTEX_C),
        vertex_c + _DOMAIN_ABOVE_VERTEX_C,
    )
    a, b, c = coeffs
    return max(0.0, a * clamped**2 + b * clamped + c)


def _speed_loss_pct_for_difference(
    temperature_c: float, coeffs: tuple[float, float, float], vertex_c: float
) -> float:
    """Same fit as _speed_loss_pct inside the paper's own measured domain
    (vertex -10C..+20C). speed_loss_pct_relative_to_normal (below)
    subtracts two readings off this curve -- if BOTH temperatures it's
    comparing exceed _speed_loss_pct's flat boundary, they'd clamp to the
    identical value and the subtraction would read as 0% even though the
    two genuinely differ by several degrees. That's not a corner case for
    this app: an ordinary August evening in Taipei is already ~31.3C, past
    the men's ~23.75C P1 boundary (women's is higher, ~29.83C), so
    time-of-day/segment comparisons for a hot supported city would
    otherwise flatten to "no difference" for men specifically.

    Past either edge of the measured domain, this does NOT continue the
    quadratic itself -- a quadratic is unbounded and keeps accelerating
    the further out you push it (see the module docstring), so continuing
    it would silently invent a steeper temperature-sensitivity than
    anything the paper's 7 measured points per curve actually support.
    Instead it continues in a straight line at the boundary's own fitted
    slope: the conservative middle ground between a flat clamp (which
    recreates the exact saturation problem this function exists to avoid)
    and the unconstrained quadratic (which overstates the swing for any
    pair of temperatures that both fall past the boundary -- confirmed
    against a real case: Tokyo's ~34.2C vs. a ~28.6C evening reference,
    men's curve, came out to +4.6% with the quadratic continued
    unclamped past the boundary, vs. +3.3% with this tangent-line
    approach)."""
    a, b, c = coeffs
    low_c = vertex_c - _DOMAIN_BELOW_VERTEX_C
    high_c = vertex_c + _DOMAIN_ABOVE_VERTEX_C
    if temperature_c < low_c:
        boundary_value = max(0.0, a * low_c**2 + b * low_c + c)
        tangent_slope = 2 * a * low_c + b
        return max(0.0, boundary_value + tangent_slope * (temperature_c - low_c))
    if temperature_c > high_c:
        boundary_value = max(0.0, a * high_c**2 + b * high_c + c)
        tangent_slope = 2 * a * high_c + b
        return max(0.0, boundary_value + tangent_slope * (temperature_c - high_c))
    return max(0.0, a * temperature_c**2 + b * temperature_c + c)


def speed_loss_pct(temperature_c: float, sex: str | None) -> float:
    """% of running speed lost at this temperature, relative to that curve's
    own optimum -- never negative (a temperature past the optimum in the
    "good" direction doesn't grant a speed bonus, it's simply undiminished).

    `sex` is "male", "female", or None. None (not yet set in the athlete's
    profile) averages the two curves rather than guessing -- picking either
    curve for an unknown athlete would silently bias every unset profile
    toward one sex's optimum.
    """
    if sex == "male":
        return round(_speed_loss_pct(temperature_c, _MEN_P1, _MEN_P1_VERTEX_C), 2)
    if sex == "female":
        return round(_speed_loss_pct(temperature_c, _WOMEN_P1, _WOMEN_P1_VERTEX_C), 2)
    men = _speed_loss_pct(temperature_c, _MEN_P1, _MEN_P1_VERTEX_C)
    women = _speed_loss_pct(temperature_c, _WOMEN_P1, _WOMEN_P1_VERTEX_C)
    return round((men + women) / 2, 2)


def speed_loss_pct_relative_to_normal(
    temperature_c: float, reference_temperature_c: float, sex: str | None
) -> float:
    """Two ordinary readings off the same published curve as speed_loss_pct,
    subtracted: the % loss the paper's curve predicts at `temperature_c`,
    minus the % loss it predicts at `reference_temperature_c`. This is not
    a re-derived curve re-centered on the reference, just the plain
    difference between two points read off the one curve the paper
    actually published (Table S3), which is what directly answers "how
    much does the paper's data say speed differs between a typical
    evening and right now" rather than approximating it.

    Each reading keeps speed_loss_pct's zero-floor (never claims a point
    is "better than the paper's own optimum"), but past either edge of the
    paper's own measured domain, extrapolates in a straight line at that
    edge's own fitted slope instead of flatly clamping -- see
    _speed_loss_pct_for_difference's docstring for why (in short: a flat
    clamp would make two temperatures that both exceed the paper's
    measured ceiling, which an ordinary hot-city evening routinely does,
    subtract to a flat 0%, hiding a real several-degree gap between them).

    Unlike speed_loss_pct, this CAN be negative -- if `temperature_c` is
    genuinely cooler than the reference, that's a real pace bonus relative
    to what's typical, not something to floor away at 0.

    `reference_temperature_c` is deliberately generic: callers pass
    whatever counts as "typical" for the comparison they need. All callers
    in routes/weather.py pass the SAME climatological normal for one fixed
    assumed reference hour (early evening -- see _REFERENCE_RUN_HOUR),
    from diurnal_temperature.py, not the flat monthly mean and not
    whichever hour it happens to be right now. Two reasons: (1) a monthly
    mean blends the hot midday peak into what's otherwise a cool evening,
    so comparing an evening reading against the mean would misreport an
    ordinary evening as "cooler than normal"; (2) comparing against
    whatever hour it currently is would make an ordinary midday read as
    "0% unusual" even though midday is still genuinely hotter than the
    evening a pace is assumed calibrated for -- exactly the information a
    runner needs when deciding whether to run at an atypical time.

    Use this for a coach-set target pace, never speed_loss_pct itself. A
    coach planning a summer training block has typically already
    calibrated that pace for a typical evening run, not for the paper's
    absolute optimum -- applying speed_loss_pct on top would compare today
    against a cold-weather ideal the coach was never targeting in the
    first place, double-counting the heat their own number already
    accounts for.
    """
    if sex == "male":
        return round(
            _speed_loss_pct_for_difference(temperature_c, _MEN_P1, _MEN_P1_VERTEX_C)
            - _speed_loss_pct_for_difference(reference_temperature_c, _MEN_P1, _MEN_P1_VERTEX_C),
            2,
        )
    if sex == "female":
        return round(
            _speed_loss_pct_for_difference(temperature_c, _WOMEN_P1, _WOMEN_P1_VERTEX_C)
            - _speed_loss_pct_for_difference(reference_temperature_c, _WOMEN_P1, _WOMEN_P1_VERTEX_C),
            2,
        )
    men = _speed_loss_pct_for_difference(
        temperature_c, _MEN_P1, _MEN_P1_VERTEX_C
    ) - _speed_loss_pct_for_difference(reference_temperature_c, _MEN_P1, _MEN_P1_VERTEX_C)
    women = _speed_loss_pct_for_difference(
        temperature_c, _WOMEN_P1, _WOMEN_P1_VERTEX_C
    ) - _speed_loss_pct_for_difference(reference_temperature_c, _WOMEN_P1, _WOMEN_P1_VERTEX_C)
    return round((men + women) / 2, 2)


# ---------------------------------------------------------------------------
# Acclimatization modulation.
#
# The El Helou curve above pools every marathon finisher regardless of
# where they train -- it's an *unacclimatized* physiological cost. A
# runner training somewhere that's normally this hot has some genuine heat
# acclimatization the pooled curve doesn't credit them for; conversely, an
# anomalously hot day (hotter than what's typical this month) hits an
# under-acclimatized body harder than the curve alone suggests.
#
# Unlike the curve above, there is no single peer-reviewed coefficient for
# "how much acclimatization per °C of typical local heat" that this module
# can honestly cite -- the closest available evidence, Tyler CJ, Reeve T,
# Hodges GJ, Cheung SS (2016) "The Effects of Heat Adaptation on
# Physiology, Perception and Exercise Performance in the Heat: A
# Meta-Analysis." Sports Medicine 46(11):1699-1724, reports its pooled
# result as a Hedges' g effect size, not a percentage -- converting that to
# "% pace change" would need variance data the meta-analysis doesn't
# publish in a directly reusable form, and doing so anyway would be a
# rigor mistake, not a rigor win.
#
# What IS a concrete, directly-usable number: one constituent study inside
# that same meta-analysis (Zurawlew et al., cited therein) measured ~5%
# improvement in 5km time-trial pace after 6 days of heat exposure. This
# module uses that ~5% as a documented, bounded ceiling for the modulation
# -- not a claim that it's the correct number for every deviation, just
# the most concrete evidence-anchored bound available. The modulation is a
# straight-line scale from 0% (today matches the reference) to +-5% (today
# is 5C or more colder/hotter than the reference), symmetric because there
# is no evidence available here to justify an asymmetric shape.
_ACCLIMATIZATION_CEILING_PCT = 5.0
_ACCLIMATIZATION_SATURATION_C = 5.0


def acclimatization_multiplier(actual_temperature_c: float, reference_temperature_c: float) -> float:
    """Multiply the base speed_loss_pct by this to account for how typical
    (or anomalous) today's temperature is against `reference_temperature_c`
    -- 1.0 is "no change", <1.0 discounts the penalty (today is at or below
    the reference), >1.0 amplifies it (today is an anomalous hot spell).
    Callers should pass a time-of-day-aware reference (see
    speed_loss_pct_relative_to_normal's docstring) rather than a flat
    monthly mean, for the same reason."""
    colder_than_reference_by = reference_temperature_c - actual_temperature_c
    clamped = max(-_ACCLIMATIZATION_SATURATION_C, min(_ACCLIMATIZATION_SATURATION_C, colder_than_reference_by))
    fraction = (clamped / _ACCLIMATIZATION_SATURATION_C) * (_ACCLIMATIZATION_CEILING_PCT / 100)
    return 1 - fraction
