"""Verification of the heat sink's *third dimension* — ``docs/exercises/heat-sink.md`` §13.

Arrays in, arrays out: no job, no server, no envelope, the same as the plane suite next door.

**The load-bearing test is the first one.** The claim this whole solver rests on is that three
dimensions add exactly one thing — conduction along the extrusion — and nothing else. That is
testable, because there is a configuration in which the extra thing does nothing: a device
heating the base along the whole length, with the two cut ends shut. In that configuration the
3-D solver must reproduce :func:`heatsink.solve` on the same in-plane grid, and not
approximately. It agrees to eleven figures, which is the conjugate-gradient tolerance and
therefore as close as "the same problem" can be demonstrated. If that test ever drifts, the
boundary model has picked up a difference nobody declared and every number below it is a
different model's number.

What the rest of the file checks is that the two effects the third dimension *does* add behave
the way the physics says: the spreading grows with the distance the heat must travel and with
how badly the metal conducts, the ends are surface, and the decomposition of the answer into
those two terms is an identity rather than an apportionment.
"""

import numpy as np
import pytest

from physics_lab.solvers import heatsink
from physics_lab.solvers import heatsink_solid as solid

#: Coarse, so the suite stays quick: a 3-D solve is the section times the stations, and the
#: convergence test below is what shows the answer has stopped moving.
COARSE = heatsink.Numerics(cell_size=0.0025)
PROFILE = heatsink.Profile(base_width=0.060, fin_count=8)


def conditions(**overrides) -> heatsink.Conditions:
    base = {
        "power_w": 30.0,
        "depth": 0.060,
        "footprint_width": 0.030,
    }
    return heatsink.Conditions(**{**base, **overrides})


@pytest.fixture(scope="module")
def nominal():
    """The sink as the page runs it: a 30 mm device on a 60 mm extrusion, ends in open air."""
    return solid.solve(
        PROFILE,
        conditions(),
        solid.Extrusion(footprint_depth=0.030, cell_size=0.005),
        COARSE,
    )


class TestTheExtrudedLimit:
    """The configuration in which three dimensions must add nothing, and must be seen to."""

    @pytest.fixture(scope="class")
    @classmethod
    def limit(cls):
        return solid.solve(
            PROFILE,
            conditions(),
            solid.Extrusion(footprint_depth=0.060, cell_size=0.005, ends_open=False),
            COARSE,
        )

    def test_the_resistance_is_the_plane_solver_s_to_the_solver_tolerance(self, limit):
        assert limit.reference is not None
        assert limit.metrics["thermal_resistance_k_w"] == pytest.approx(
            limit.reference.metrics["thermal_resistance_k_w"], rel=1e-8
        )

    def test_the_agreement_is_reported_rather_than_only_asserted(self, limit):
        """A visitor should be able to read the residual, not take a test's word for it."""
        assert limit.residuals["extruded_limit"] < 1e-8

    def test_the_residual_is_absent_when_it_would_not_be_one(self, nominal):
        """With a real device on a real sink the difference *is* the answer.

        Reporting it as a residual would be the arithmetic saying what it wants to hear: a
        number labelled "how wrong is this" that is in fact "what did we find".
        """
        assert "extruded_limit" not in nominal.residuals

    def test_the_field_does_not_vary_along_the_length(self, limit):
        """The stronger statement behind the resistance agreeing: it is the *same field*."""
        metal = limit.temperature_c[:, limit.mask]
        assert (metal.max(axis=0) - metal.min(axis=0)).max() < 1e-6

    def test_nothing_leaves_through_the_shut_ends(self, limit):
        assert limit.metrics["end_loss_fraction"] == 0.0


class TestTheDecompositionIsAnIdentity:
    def test_the_three_terms_reconstruct_the_answer(self, nominal):
        """``R = R_extruded + spreading - end_gain``, and each term is its own solve.

        Exactly, not nearly: the terms are differences of resistances that were computed, so
        the identity is arithmetic. It is checked because the alternative — apportioning one
        solve's difference between two named effects — would look identical in the result and
        mean nothing.
        """
        m = nominal.metrics
        assert m["thermal_resistance_k_w"] == pytest.approx(
            m["thermal_resistance_extruded_k_w"]
            + m["spreading_resistance_k_w"]
            - m["end_gain_k_w"],
            abs=1e-12,
        )

    def test_the_net_is_what_the_plane_model_was_missing(self, nominal):
        m = nominal.metrics
        assert m["depth_correction_k_w"] == pytest.approx(
            m["thermal_resistance_k_w"] - m["thermal_resistance_extruded_k_w"], abs=1e-12
        )

    def test_without_the_second_solve_only_the_net_is_offered(self):
        """`decompose=False` must drop the two terms rather than guess them."""
        answer = solid.solve(
            PROFILE,
            conditions(),
            solid.Extrusion(footprint_depth=0.030, cell_size=0.006),
            COARSE,
            decompose=False,
        )
        assert answer.metrics["end_gain_k_w"] == 0.0
        assert "depth_correction_k_w" in answer.metrics


class TestSpreadingBehavesLikeSpreading:
    """The effect that raises the resistance, isolated by shutting the ends."""

    def spreading(self, depth=0.060, footprint=0.030, conductivity=201.0):
        answer = solid.solve(
            PROFILE,
            conditions(depth=depth, conductivity=conductivity),
            solid.Extrusion(
                footprint_depth=footprint, cell_size=depth / 12.0, ends_open=False
            ),
            COARSE,
        )
        return answer.metrics["spreading_resistance_k_w"]

    def test_it_is_positive(self):
        """Heat that has to travel to reach a fin arrives cooler. There is no configuration in
        which making the device smaller than the extrusion helps."""
        assert self.spreading() > 0.0

    def test_it_grows_with_the_distance_the_heat_must_travel(self):
        assert self.spreading(depth=0.200) > 3.0 * self.spreading(depth=0.060)

    def test_it_grows_when_the_metal_conducts_worse(self):
        """Steel rather than aluminium: a thirteenth of the conductivity, and the same
        geometry. This is the check that the number is a *conduction* penalty and not an
        artefact of where the power is applied."""
        assert self.spreading(conductivity=15.0) > 5.0 * self.spreading(conductivity=201.0)

    def test_it_vanishes_when_the_device_covers_the_length(self):
        assert self.spreading(footprint=0.060) == pytest.approx(0.0, abs=1e-6)


class TestTheEndsAreSurface:
    def test_opening_them_lowers_the_resistance(self):
        shut, open_ = (
            solid.solve(
                PROFILE,
                conditions(),
                solid.Extrusion(footprint_depth=0.030, cell_size=0.005, ends_open=ends),
                COARSE,
                decompose=False,
            )
            for ends in (False, True)
        )
        assert open_.metrics["thermal_resistance_k_w"] < shut.metrics["thermal_resistance_k_w"]

    def test_they_carry_a_share_worth_reporting(self, nominal):
        """On a 60 mm extrusion the two ends are a twentieth of the surface and carry about
        that. The point of the number is that it is *not* negligible — it is what makes the
        net correction come out negative here and positive on a longer sink."""
        assert 0.02 < nominal.metrics["end_loss_fraction"] < 0.12

    def test_a_longer_extrusion_leans_on_them_less(self):
        long_sink = solid.solve(
            PROFILE,
            conditions(depth=0.200),
            solid.Extrusion(footprint_depth=0.030, cell_size=0.010),
            COARSE,
        )
        assert long_sink.metrics["end_loss_fraction"] < 0.04
        # And the sign of the finding flips: on a long extrusion the plane model is optimistic.
        assert long_sink.metrics["depth_correction_k_w"] > 0.0


class TestEnergyIsConserved:
    def test_what_goes_in_comes_out(self, nominal):
        assert nominal.residuals["energy_balance"] < 1e-3

    def test_the_enclosures_are_closed(self, nominal):
        worst = max(v for k, v in nominal.residuals.items() if "summation" in k)
        assert worst < 1e-8


class TestConvergence:
    def test_the_spreading_stops_moving_as_the_stations_are_refined(self):
        """The one number the third dimension exists to produce, against the one knob that
        only the third dimension has."""
        answers = [
            solid.solve(
                PROFILE,
                conditions(),
                solid.Extrusion(footprint_depth=0.030, cell_size=size, ends_open=False),
                COARSE,
            ).metrics["spreading_resistance_k_w"]
            for size in (0.006, 0.003, 0.0015)
        ]
        assert abs(answers[2] - answers[1]) < 0.4 * abs(answers[1] - answers[0])


class TestTheGridResolvesWhatItMustResolve:
    def test_a_line_lands_on_each_edge_of_the_device(self):
        """The same rule the fin edges get, for the same reason: a boundary that falls between
        two cell centres is a boundary whose position moves with the resolution."""
        edges = solid.build_z_edges(0.060, 0.030, 0.004)
        for wanted in (0.015, 0.045):
            assert np.min(np.abs(edges - wanted)) < 1e-12

    def test_a_device_covering_the_length_needs_no_interior_line(self):
        edges = solid.build_z_edges(0.060, 0.060, 0.004)
        assert edges[0] == 0.0 and edges[-1] == pytest.approx(0.060)


class TestTheDisplayLattice:
    @pytest.fixture(scope="class")
    @classmethod
    def lattice(cls, nominal):
        return solid.display_lattice(
            PROFILE,
            conditions(),
            solid.Extrusion(footprint_depth=0.030, cell_size=0.005),
            nominal,
            0.005,
        )

    def test_every_tetrahedron_indexes_real_nodes(self, lattice):
        assert lattice.tets.min() >= 0
        assert lattice.tets.max() < len(lattice.points)

    def test_the_six_tetrahedra_of_a_cell_fill_it(self, lattice):
        """The mesh's volume is the metal's volume — which is what says the decomposition
        tiles each cell exactly, with no gap and no overlap."""
        a, b, c, d = (lattice.points[lattice.tets[:, i]] for i in range(4))
        volume = np.abs(np.einsum("ij,ij->i", np.cross(b - a, c - a), d - a)).sum() / 6.0
        assert volume == pytest.approx(PROFILE.solid_area * 0.060, rel=2e-2)

    def test_no_node_carries_air(self, lattice):
        """A NaN here would be a piece of the metal's surface painted with a cell that was
        never solved — the failure the containment lookup exists to prevent."""
        assert np.all(np.isfinite(lattice.temperature_c))
        assert lattice.temperature_c.min() > 20.0

    def test_the_fins_are_still_there(self, lattice):
        """A display grid coarser than a 1.5 mm fin would quietly lose the fins, and the
        picture would be of a plate. The lattice is built by the rule that puts a line on
        every fin edge, so it cannot."""
        assert lattice.bounds[4] == pytest.approx(PROFILE.total_height)
        assert lattice.points[:, 1].max() == pytest.approx(PROFILE.total_height)
