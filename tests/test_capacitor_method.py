"""Verification of the capacitive sensor's physics — ``docs/exercises/capacitive-sensor.md`` §8.

Arrays in, arrays out: no job, no server, no envelope.

**The load-bearing test is the benchmark**, and it is the reason this exercise was worth
building first. The answer it is checked against was computed in 2015, by a different code on a
different formulation, and published — so unlike every other check in this repository it is not
a self-consistency test. Two independent things have to be right for it to pass: the
axisymmetric weight, and where the conductor's surface is.

That second one is not a hypothetical. Pinning the electrode's *cells* instead of its *faces*
puts the metal surface half a coarse cell inside the metal, and against a 90 µm gap that is an
order of magnitude of error — with a consistent linear system, both capacitance routes agreeing
and a machine-precision residual to go with it. It came back four times too small and nothing
in the solve complained. The benchmark is what caught it.
"""

import numpy as np
import pytest

from physics_lab.solvers import capacitor

#: The measured fit from the thesis, C in nF with the gap z in millimetres.
PUBLISHED_C0 = 0.031904e-9
NOMINAL_GAP = 90e-6

#: Coarse enough to keep the suite quick. The convergence class below is what shows the answer
#: has stopped moving; every other test here is about a relationship, not a digit.
COARSE = capacitor.Numerics(cell_size=2.5e-5, truncation=2.5)


def published(gap_mm: float) -> float:
    """``C(z)`` as the thesis fitted it, in farads."""
    return 1e-9 / (-298.8 * gap_mm**2 + 369.6 * gap_mm + 0.5)


@pytest.fixture(scope="module")
def nominal():
    return capacitor.solve(capacitor.Electrode(), NOMINAL_GAP, 1.0, COARSE)


class TestAgainstThePublishedMeasurement:
    def test_the_capacitance_reproduces_the_published_value(self, nominal):
        """Within 3%, against a number this repository did not produce."""
        assert nominal.capacitance_energy == pytest.approx(PUBLISHED_C0, rel=0.03)

    def test_the_fit_agrees_with_itself_at_the_nominal_gap(self):
        """A guard on the benchmark rather than on the solver: the two constants §8 quotes —
        the fitted curve and the value 0.031904 nF — have to be the same number, or the test
        above is checking against a typo."""
        assert published(0.090) == pytest.approx(PUBLISHED_C0, rel=1e-4)

    def test_it_lands_above_the_parallel_plate_by_about_a_sixth(self, nominal):
        """§8's real claim. A solver that reproduced ``eps0 A / d`` exactly would have lost the
        fringe field it exists to resolve — the excess *is* the answer."""
        flat = capacitor.Electrode().parallel_plate(NOMINAL_GAP)
        excess = nominal.capacitance_energy / flat - 1.0
        assert 0.12 < excess < 0.20

    def test_the_parallel_plate_value_is_the_one_the_specification_quotes(self):
        assert capacitor.Electrode().parallel_plate(NOMINAL_GAP) == pytest.approx(
            0.027584e-9, rel=1e-4
        )


class TestTheChamferCannotEatTheFace:
    """A finding, kept as a test because it is what fixes the geometry's reading.

    §5 calls the chamfer *the reason C is not a parallel plate*. Modelled as a bevel into the
    facing surface, a nominal 1.5 mm chamfer on each side of a 3.5 mm annulus leaves half a
    millimetre of face and the capacitance falls to 57% **below** the parallel-plate value —
    while the published measurement is 16% above it. So the countersink is in the body behind
    the face, the face spans the full annulus, and the excess is fringe.
    """

    def test_a_flat_annulus_already_carries_the_published_excess(self):
        flat = capacitor.solve(
            capacitor.Electrode(chamfer_width=0.0, chamfer_height=0.0),
            NOMINAL_GAP,
            1.0,
            COARSE,
        )
        assert flat.capacitance_energy == pytest.approx(PUBLISHED_C0, rel=0.03)

    def test_the_countersink_moves_it_by_a_few_per_cent_at_most(self, nominal):
        flat = capacitor.solve(
            capacitor.Electrode(chamfer_width=0.0, chamfer_height=0.0),
            NOMINAL_GAP,
            1.0,
            COARSE,
        )
        moved = abs(nominal.capacitance_energy / flat.capacitance_energy - 1.0)
        assert moved < 0.05, "a countersink behind the face is a small effect, not the effect"

    def test_a_chamfer_that_would_meet_itself_is_refused(self):
        with pytest.raises(ValueError, match="they would meet"):
            capacitor.Electrode(chamfer_width=0.002)

    def test_the_transposed_radii_from_the_thesis_table_are_refused(self):
        """§5 records that the source table lists the two radii the wrong way round. A payload
        copied from it is caught here rather than solved as a negative-width annulus."""
        with pytest.raises(ValueError, match="transposed"):
            capacitor.Electrode(inner_radius=0.0145, outer_radius=0.011)


class TestTheTwoRoutesToTheCapacitance:
    def test_they_agree(self, nominal):
        assert nominal.consistency < 1e-9

    def test_and_what_that_measures_is_the_solve(self, nominal):
        """Stated as a test so the claim cannot quietly inflate. The two routes are the same
        number for the converged discrete solution — discrete Green's identity — so their gap
        tracks the residual, and it is the mesh study that measures the geometry."""
        assert nominal.consistency < max(nominal.residual, 1e-15) * 1e4


class TestTheScalingsThatMustHold:
    def test_capacitance_does_not_depend_on_the_excitation(self):
        """§5: *C* is voltage-independent and the value only scales *W*. The page says so, so
        it had better be true."""
        one = capacitor.solve(capacitor.Electrode(), NOMINAL_GAP, 1.0, COARSE)
        ten = capacitor.solve(capacitor.Electrode(), NOMINAL_GAP, 10.0, COARSE)
        assert ten.capacitance_energy == pytest.approx(one.capacitance_energy, rel=1e-9)
        assert ten.energy == pytest.approx(100.0 * one.energy, rel=1e-9)

    def test_a_wider_gap_holds_less_charge(self):
        near = capacitor.solve(capacitor.Electrode(), 60e-6, 1.0, COARSE)
        far = capacitor.solve(capacitor.Electrode(), 150e-6, 1.0, COARSE)
        assert near.capacitance_energy > far.capacitance_energy

    def test_the_gap_dependence_follows_the_published_curve(self):
        """Not just monotone — the right shape. Over the working stroke the solve should track
        the fitted curve, which is the claim a calibration rests on."""
        for gap_mm in (0.070, 0.090, 0.120):
            solved = capacitor.solve(capacitor.Electrode(), gap_mm * 1e-3, 1.0, COARSE)
            assert solved.capacitance_energy == pytest.approx(published(gap_mm), rel=0.05)

    def test_a_closed_sensor_is_refused_rather_than_solved(self):
        with pytest.raises(ValueError, match="short circuit"):
            capacitor.solve(capacitor.Electrode(), 0.0, 1.0, COARSE)


class TestTheGridAndTheAxis:
    def test_the_window_never_reaches_a_negative_radius(self):
        """`axisymmetric2d` refuses `rmin < 0`, correctly — it is a plane section mislabelled.
        The truncation reaches inward from an 11 mm electrode, so this is reachable by turning
        one knob, not a hypothetical."""
        r_edges, _z = capacitor.build_grid(
            capacitor.Electrode(), NOMINAL_GAP, capacitor.Numerics(truncation=8.0)
        )
        assert r_edges[0] >= 0.0

    def test_a_line_lands_on_every_edge_the_geometry_has(self):
        electrode = capacitor.Electrode()
        r_edges, z_edges = capacitor.build_grid(electrode, NOMINAL_GAP, COARSE)
        for wanted in (electrode.inner_radius, electrode.outer_radius):
            assert np.min(np.abs(r_edges - wanted)) < 1e-12
        for wanted in (0.0, NOMINAL_GAP, NOMINAL_GAP + electrode.thickness):
            assert np.min(np.abs(z_edges - wanted)) < 1e-12

    def test_the_field_is_finite_everywhere(self, nominal):
        assert np.all(np.isfinite(nominal.field))
        assert np.all(np.isfinite(nominal.potential))


class TestConvergence:
    def test_refining_the_grid_stops_moving_the_answer(self):
        answers = [
            capacitor.solve(
                capacitor.Electrode(),
                NOMINAL_GAP,
                1.0,
                capacitor.Numerics(cell_size=size, truncation=2.5),
            ).capacitance_energy
            for size in (4e-5, 2e-5, 1e-5)
        ]
        assert abs(answers[2] - answers[1]) < abs(answers[1] - answers[0])

    def test_pushing_the_truncation_out_stops_moving_it_too(self):
        near = capacitor.solve(
            capacitor.Electrode(), NOMINAL_GAP, 1.0, capacitor.Numerics(truncation=2.0)
        )
        far = capacitor.solve(
            capacitor.Electrode(), NOMINAL_GAP, 1.0, capacitor.Numerics(truncation=5.0)
        )
        moved = abs(far.capacitance_energy / near.capacitance_energy - 1.0)
        assert moved < 0.02, "the answer must not live on the window's edge"
