"""Verification of the sensor's *calibration* — ``docs/exercises/capacitive-sensor.md`` §7, §8.

The layer above :mod:`physics_lab.solvers.capacitor`: a sweep, a fit in the published family,
and the seven numbers a controller would actually be handed. Arrays in, arrays out.

**Two external checks, not one.** The physics module is already benchmarked against the thesis's
``C(z)``. This module is checked against its *second* published curve — the tilt fit — which the
first one implies through §2's hybrid method but does not contain. Reproducing it settles a
question the source leaves open: the printed coefficient is per **degree squared**, and the
radian reading is out by a factor of 3200. That is not a rounding disagreement, and
:class:`TestTheTiltUnit` is where it is nailed down.
"""

import numpy as np
import pytest

from physics_lab.solvers import capacitor, sensor

#: Coarse and short: seven gaps at 25 µm cells run in under three seconds, and every metric
#: below lands within a per cent of the same sweep at the shipped resolution. Convergence of
#: the underlying solve is ``tests/test_capacitor_method.py``'s business, not this file's.
COARSE = capacitor.Numerics(cell_size=2.5e-5, truncation=2.5)
SAMPLES = 7


@pytest.fixture(scope="module")
def calibration():
    return sensor.calibrate(capacitor.Electrode(), sensor.Conditions(), COARSE, samples=SAMPLES)


class TestTheTiltUnit:
    """The one question the thesis does not answer, answered by making the two curves agree."""

    def test_the_tilt_coefficient_reproduces_the_published_one_in_degrees(self, calibration):
        """0.09 nF/deg², from a hybrid quadrature over a curve fitted to our own solves. Nothing
        in this chain was told the tilt answer, so agreeing with it is a real check."""
        assert calibration.metrics["tilt_per_deg2"] == pytest.approx(
            sensor.PUBLISHED_TILT_PER_DEG2, rel=0.05
        )

    def test_and_the_radian_reading_is_off_by_three_thousand(self, calibration):
        """The half of the argument that makes it conclusive: the alternative is not close.
        A unit ambiguity that changed the answer by 10% would be worth hedging over; one that
        changes it by 3200 has already been decided by the numbers."""
        ratio = calibration.metrics["tilt_per_rad2"] / sensor.PUBLISHED_TILT_PER_DEG2
        assert ratio > 1000.0

    def test_the_two_tilt_metrics_are_the_same_number_in_two_units(self, calibration):
        per_deg2 = calibration.metrics["tilt_per_deg2"]
        per_rad2 = calibration.metrics["tilt_per_rad2"]
        assert per_deg2 == pytest.approx(per_rad2 * np.radians(1.0) ** 2, rel=1e-12)


class TestTheHybridInference:
    def test_no_tilt_is_no_change(self, calibration):
        """The quadrature has to collapse onto the curve it integrates, or the coefficient it
        produces is measuring the quadrature."""
        flat = sensor.tilted_capacitance(calibration, capacitor.Electrode(), 90e-6, 0.0)
        assert flat == pytest.approx(calibration.curve(90e-6), rel=1e-9)

    def test_a_tilt_always_reads_high(self, calibration):
        """Convexity, and the reason the cross-sensitivity has a sign at all: the azimuth that
        closes gains more than the one that opens loses, so a tilt looks like an approach."""
        electrode = capacitor.Electrode()
        nominal = calibration.curve(90e-6)
        for tilt in (0.02, 0.05, 0.1, 0.2):
            assert sensor.tilted_capacitance(calibration, electrode, 90e-6, tilt) > nominal

    def test_it_grows_as_the_square_of_the_tilt(self, calibration):
        """What makes a single coefficient the right way to report it. Doubling the tilt has to
        quadruple the excess, or ``tilt_per_deg2`` is not a property of the sensor."""
        electrode = capacitor.Electrode()
        nominal = calibration.curve(90e-6)
        small = sensor.tilted_capacitance(calibration, electrode, 90e-6, 0.05) - nominal
        large = sensor.tilted_capacitance(calibration, electrode, 90e-6, 0.10) - nominal
        assert large / small == pytest.approx(4.0, rel=0.05)

    def test_the_sweep_is_wide_enough_to_be_integrated_over(self):
        """The quadrature reads the curve out at ``z0 ± gamma R``, and reading a fit outside the
        points it was fitted to is extrapolation however tidy it looks."""
        electrode = capacitor.Electrode()
        conditions = sensor.Conditions()
        gaps = sensor.sweep_gaps(electrode, conditions, SAMPLES)
        reach = np.radians(conditions.tilt_deg) * electrode.mean_radius
        assert gaps.min() <= conditions.gap - reach
        assert gaps.max() >= conditions.gap + reach


class TestTheFit:
    def test_it_recovers_a_curve_that_is_already_in_the_family(self):
        """Exactly, because the fit is linear in its coefficients and this is the family it is
        linear in. A tolerance here would be hiding something."""
        gaps = np.linspace(40e-6, 140e-6, 9)
        exact = np.array([sensor._published(g) for g in gaps])
        assert sensor.fit_reciprocal(gaps, exact) == pytest.approx(sensor.PUBLISHED_FIT, rel=1e-9)

    def test_the_solved_points_are_in_the_family_too(self, calibration):
        """§8's third row. The reciprocal quadratic is the *measurement's* reduction, and this
        is the check that our geometry belongs to it — if the residual were percent-sized the
        benchmark below would be comparing two different shapes."""
        assert calibration.residuals["fit_residual"] < 0.01

    def test_the_slope_is_the_derivative_of_the_curve(self, calibration):
        """Analytic against numerical, since every sensitivity below is read off the analytic
        one and a sign slip there would survive every other test in this file."""
        step = 1e-9
        for gap in (60e-6, 90e-6, 130e-6):
            numerical = (calibration.curve(gap + step) - calibration.curve(gap - step)) / (2 * step)
            assert calibration.slope(gap) == pytest.approx(numerical, rel=1e-5)

    def test_the_curvature_is_the_second_derivative(self, calibration):
        step = 1e-8
        for gap in (60e-6, 90e-6, 130e-6):
            numerical = (
                calibration.curve(gap + step)
                - 2 * calibration.curve(gap)
                + calibration.curve(gap - step)
            ) / step**2
            assert calibration.curvature(gap) == pytest.approx(numerical, rel=1e-3)


class TestTheSevenNumbers:
    """§7, each one checked against what it claims to be rather than against a digit."""

    def test_they_are_all_there_and_all_finite(self, calibration):
        wanted = {
            "c0",
            "c0_charge",
            "dc_dz",
            "linear_halfstroke",
            "tilt_per_deg2",
            "tilt_per_rad2",
            "tilt_error",
            "fringe_excess",
            "parallel_plate",
        }
        assert wanted <= set(calibration.metrics)
        assert all(np.isfinite(v) for v in calibration.metrics.values())

    def test_the_nominal_capacitance_is_solved_rather_than_fitted(self, calibration):
        """``c0`` is read off the solve at the nominal gap, which is why :func:`sensor.sweep_gaps`
        puts a sample exactly there. Reporting the fit's value instead would quietly turn a
        measurement into an interpolation — they agree here, and that is the point."""
        assert np.min(np.abs(calibration.gaps - 90e-6)) < 1e-12
        assert calibration.metrics["c0"] == pytest.approx(calibration.curve(90e-6), rel=0.01)

    def test_the_sensitivity_is_negative_and_of_the_published_size(self, calibration):
        """Closing the gap raises the capacitance: a sensor whose ``dC/dz`` came out positive
        has its geometry inside out."""
        published_slope = -0.3215e-9 / 1e-3
        assert calibration.metrics["dc_dz"] < 0.0
        assert calibration.metrics["dc_dz"] == pytest.approx(published_slope, rel=0.05)

    def test_the_fringe_excess_is_the_measured_one(self, calibration):
        """§8's first row: 15.7% above the parallel plate. The countersink carries it a couple
        of points further, which ``tests/test_capacitor_method.py`` pins down separately."""
        assert 0.14 < calibration.metrics["fringe_excess"] < 0.22
        assert calibration.metrics["c0"] / calibration.metrics["parallel_plate"] - 1.0 == (
            pytest.approx(calibration.metrics["fringe_excess"], rel=1e-9)
        )

    def test_the_tilt_error_is_a_displacement_the_sensor_never_made(self, calibration):
        """Microns of phantom motion from a tenth of a degree — the number that decides whether
        a tilt matters, and it is the tilt excess read through the sensitivity."""
        conditions = sensor.Conditions()
        excess = calibration.metrics["tilt_per_deg2"] * conditions.tilt_deg**2
        assert calibration.metrics["tilt_error"] == pytest.approx(
            abs(excess / calibration.metrics["dc_dz"]), rel=1e-9
        )
        assert 1e-6 < calibration.metrics["tilt_error"] < 1e-5

    def test_the_two_capacitance_routes_agree(self, calibration):
        """§8's second row. An identity for a converged discrete solution, so what it measures
        is the linear solve rather than the mesh."""
        assert calibration.residuals["energy_charge_consistency"] < 0.01
        assert calibration.metrics["c0"] == pytest.approx(
            calibration.metrics["c0_charge"], rel=0.01
        )


class TestTheLinearStroke:
    def test_the_tangent_still_holds_inside_it(self, calibration):
        """The definition, from the inside: at the returned excursion the straight line a
        controller inverts with is still within tolerance of the curve."""
        conditions = sensor.Conditions()
        half = calibration.metrics["linear_halfstroke"]
        at_nominal = calibration.curve(conditions.gap)
        slope = calibration.slope(conditions.gap)
        for direction in (-1.0, 1.0):
            z = conditions.gap + direction * half * 0.98
            straight = at_nominal + direction * half * 0.98 * slope
            error = abs(calibration.curve(z) - straight) / abs(calibration.curve(z))
            assert error <= conditions.linear_tolerance

    def test_and_stops_holding_outside_it(self, calibration):
        """The same definition from the outside, which is what stops the answer being the
        search's upper bound in disguise."""
        conditions = sensor.Conditions()
        half = calibration.metrics["linear_halfstroke"]
        assert half < conditions.stroke, "the search saturated: nothing was actually measured"
        at_nominal = calibration.curve(conditions.gap)
        slope = calibration.slope(conditions.gap)
        worst = max(
            abs(
                calibration.curve(conditions.gap + d * half * 1.3)
                - (at_nominal + d * half * 1.3 * slope)
            )
            / abs(calibration.curve(conditions.gap + d * half * 1.3))
            for d in (-1.0, 1.0)
        )
        assert worst > conditions.linear_tolerance

    def test_a_looser_tolerance_buys_a_longer_stroke(self, calibration):
        """Monotone in the tolerance, which is the only thing that makes the number comparable
        between two attempts at the geometry."""
        loose = sensor._linear_halfstroke(sensor.Conditions(linear_tolerance=0.03), calibration)
        tight = sensor._linear_halfstroke(sensor.Conditions(linear_tolerance=0.003), calibration)
        assert tight < calibration.metrics["linear_halfstroke"] < loose


class TestTheChallengeIsWinnable:
    """§1's draft targets, against the sensor as built. A target the nominal design already
    meets is not a challenge, and one nothing can reach is not one either."""

    def test_the_sensitivity_target_is_already_met(self, calibration):
        """0.30 nF/mm. This one is a floor to hold on to while the other two are chased — the
        interesting failure is trading it away for stroke."""
        assert abs(calibration.metrics["dc_dz"]) * 1e-3 / 1e-9 > 0.30

    def test_the_stroke_target_is_not(self, calibration):
        """10 µm, and the P45 geometry gets 9.6. Close enough that the exercise is a design
        problem rather than a wall — and it is reached by widening the gap, which costs
        sensitivity. That trade is the challenge."""
        assert 8e-6 < calibration.metrics["linear_halfstroke"] < 10e-6

    def test_a_wider_gap_buys_stroke_and_sells_sensitivity(self, calibration):
        """The trade, demonstrated rather than asserted — read off the same fitted curve at a
        gap it already covers, so it costs no solve."""
        near, far = 70e-6, 130e-6
        assert abs(calibration.slope(near)) > abs(calibration.slope(far))
        conditions = sensor.Conditions
        stroke_near = sensor._linear_halfstroke(conditions(gap=near, stroke=60e-6), calibration)
        stroke_far = sensor._linear_halfstroke(conditions(gap=far, stroke=60e-6), calibration)
        assert stroke_far > stroke_near


class TestWhatIsRefused:
    def test_a_stroke_that_closes_the_gap_is_a_collision(self):
        with pytest.raises(ValueError, match="collision"):
            sensor.Conditions(gap=90e-6, stroke=90e-6)

    def test_the_sweep_never_asks_for_a_closed_sensor(self):
        """The span widens for a large tilt, and the clamp is what keeps it from widening
        through zero — where the physics module would refuse it, several solves in."""
        gaps = sensor.sweep_gaps(
            capacitor.Electrode(), sensor.Conditions(tilt_deg=5.0), SAMPLES
        )
        assert gaps.min() > 0.0


class TestAgainstThePublishedCurve:
    def test_the_whole_sweep_tracks_the_measurement(self, calibration):
        """§8's benchmark, over the range rather than at a point: a solver that happened to hit
        one gap would still show here."""
        assert calibration.residuals["benchmark"] < 0.06

    def test_the_tilt_curve_too(self, calibration):
        assert calibration.residuals["tilt_benchmark"] < 0.05

    def test_the_linear_solve_converged_at_every_gap(self, calibration):
        """A sweep is nine chances to quietly not converge, and the metrics above would average
        over a failure rather than show it."""
        assert calibration.residuals["cg_residual"] < 1e-11
        assert calibration.solves == len(calibration.gaps)
