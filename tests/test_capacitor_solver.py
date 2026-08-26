"""``lab.capacitor_axi2d`` as a capability: the protocol seam, not the physics.

The physics is ``tests/test_capacitor_method.py`` and the calibration is
``tests/test_sensor_method.py`` — both of which run without a job, a server or an envelope.
What is left for this file is everything that only exists because the solver is reached over a
wire: what the section says, what the declarations promise, what the estimate charges, and what
the envelope carries back.

**The most load-bearing test here is not about a number.** It is
:meth:`TestTheCostEstimate.test_every_shipped_example_fits_the_lab_s_budget`. This capability
is the first in the lab whose cost is a *multiple* of one section's cells, because a
calibration is several solves — and an example whose defaults are past the server's budget is
one that cannot be run by the page that ships it.
"""

import numpy as np
import pytest
from fenixspoon.geometry import Axisymmetric2D
from fenixspoon.solvers.base import SolverContext

from physics_lab.solvers import sensor
from physics_lab.solvers.capacitor_axi2d import CapacitorAxi2D

#: The lab's own cell budget, from ``compose.yaml``. Hard-coded rather than read: a test that
#: took the limit from the same place the server does would pass however either one moved.
LAB_MAX_CELLS = 200_000

#: Short and coarse. The seam is what is under test, and every metric below is checked for
#: being the right *quantity*, not the right digit.
QUICK = {"samples": 5, "cell_size": 5e-5, "truncation": 2.0, "resolution": 64}


def section(
    inner: float = 0.011,
    outer: float = 0.0145,
    thickness: float = 0.004,
    chamfer: float = 0.0015,
    gap: float = 90e-6,
    voltage: float | None = 1.0,
    extra: list[dict] | None = None,
) -> Axisymmetric2D:
    """A meridian section with one chamfered annulus in it, and knobs for the refusals.

    A zero chamfer is drawn as a rectangle rather than as a hexagon whose corners coincide,
    because `polygon2d` refuses duplicate consecutive points — which is the right refusal, and
    it means the page has to draw the two cases as two outlines rather than as one with a
    parameter at zero.
    """
    top = gap + thickness
    material = {} if voltage is None else {"voltage": voltage}
    outline = (
        [[inner, gap], [outer, gap], [outer, top], [inner, top]]
        if chamfer <= 0.0
        else [
            [inner, gap],
            [outer, gap],
            [outer, top - chamfer],
            [outer - chamfer, top],
            [inner + chamfer, top],
            [inner, top - chamfer],
        ]
    )
    regions = [
        {
            "name": "electrode",
            "shape": {"type": "polygon2d", "points": outline},
            "material": material,
        }
    ]
    return Axisymmetric2D(
        bounds=(0.0, 0.0, 0.030, 0.010),
        background={"eps_r": 1.0},
        regions=regions + (extra or []),
    )


def run(geometry: Axisymmetric2D, **overrides):
    solver = CapacitorAxi2D()
    params = solver.Params(**{**QUICK, **overrides})
    return solver.solve(geometry, params, SolverContext(progress_cb=lambda event: None))


@pytest.fixture(scope="module")
def result():
    return run(section())


class TestReadingTheSensorOutOfTheSection:
    """The section is the input. Everything the physics module is parameterised by has to
    come out of a polygon, and what cannot come out of one has to be refused."""

    def test_the_annulus_round_trips(self):
        electrode, gap = sensor.read_electrode(
            np.array(section().regions[0].shape.points, dtype=float), 0.0
        )
        assert electrode.inner_radius == pytest.approx(0.011)
        assert electrode.outer_radius == pytest.approx(0.0145)
        assert electrode.thickness == pytest.approx(0.004)
        assert electrode.chamfer_width == pytest.approx(0.0015)
        assert electrode.chamfer_height == pytest.approx(0.0015)
        assert gap == pytest.approx(90e-6)

    def test_an_unchamfered_annulus_reads_as_one(self):
        electrode, _gap = sensor.read_electrode(
            np.array(section(chamfer=0.0).regions[0].shape.points, dtype=float), 0.0
        )
        assert electrode.chamfer_width == 0.0
        assert electrode.chamfer_height == 0.0

    def test_two_driven_electrodes_are_refused_rather_than_one_of_them_ignored(self):
        """A driven guard ring is a different problem, and the failure mode of accepting it
        silently is a capacitance computed against a conductor that was not in the model.

        A *grounded* region is the other case and is accepted — it is the shell, and
        `TestAgainstTheUpstreamAdapter` is why that distinction is worth drawing."""
        guard = {
            "name": "guard",
            "shape": {"type": "polygon2d", "points": [[0.020, 0.001], [0.024, 0.001],
                                                      [0.024, 0.003], [0.020, 0.003]]},
            "material": {"voltage": 0.5},
        }
        with pytest.raises(ValueError, match="one electrode"):
            run(section(extra=[guard]))

    def test_no_electrode_is_refused_too(self):
        """With nothing held the problem is singular: every constant field solves it, and a
        solver that did not check would return one of them."""
        with pytest.raises(ValueError, match="one electrode"):
            run(section(voltage=None))

    def test_an_electrode_sitting_on_the_floor_has_no_gap(self):
        """Checked against the reader rather than through a job, because a section like this
        never reaches the adapter: `axisymmetric2d` requires a region to lie strictly inside
        the window, so an electrode resting on the floor is refused a layer earlier. The
        reader's own check is what covers the physics module being called directly — which is
        how every test in ``test_sensor_method.py`` calls it."""
        points = np.array(section().regions[0].shape.points, dtype=float)
        with pytest.raises(ValueError, match="gap is not positive"):
            sensor.read_electrode(points, 90e-6)

    def test_an_asymmetric_outline_is_refused_rather_than_averaged(self):
        """This solver knows one shape. An outline with one corner cut would come back as a
        symmetric chamfer of half the size with nothing to say it had been reinterpreted."""
        lopsided = Axisymmetric2D(
            bounds=(0.0, 0.0, 0.030, 0.010),
            regions=[
                {
                    "name": "electrode",
                    "shape": {
                        "type": "polygon2d",
                        "points": [
                            [0.011, 90e-6],
                            [0.0145, 90e-6],
                            [0.0145, 0.00259],
                            [0.013, 0.00409],
                            [0.011, 0.00409],
                        ],
                    },
                    "material": {"voltage": 1.0},
                }
            ],
        )
        with pytest.raises(ValueError, match="chamfers differ"):
            run(lopsided)


class TestWhatComesBack:
    def test_every_declared_metric_is_reported(self, result):
        """A declaration a caller reads before submitting, against what actually arrives.
        ``e_max`` is the exception and it is filled in by the server from its `field`/`max`
        declaration, so the adapter neither computes nor sends it."""
        declared = {spec.name for spec in CapacitorAxi2D.metrics}
        assert declared - {"e_max"} <= set(result.metrics)

    def test_the_metrics_are_the_quantities_they_claim_to_be(self, result):
        assert result.metrics["capacitance"] > 0.0
        assert result.metrics["capacitance"] > result.metrics["parallel_plate"], "fringe"
        assert result.metrics["dC_dz"] < 0.0, "closing the gap must raise the capacitance"
        assert 0.0 < result.metrics["linear_halfstroke"] < 50e-6
        assert result.metrics["tilt_per_deg2"] > 0.0
        assert result.metrics["energy"] == pytest.approx(
            0.5 * result.metrics["capacitance"], rel=1e-9
        ), "W = ½CV² at one volt"

    def test_the_field_travels_under_upstream_s_names(self, result):
        """``V`` and ``E``, as both upstream electrostatics adapters publish them, so a page
        can show either solver without a translation table."""
        assert set(result.data["fields"]) == {"V", "E"}
        potential = np.array(result.data["fields"]["V"])
        assert potential.min() >= 0.0
        assert potential.max() == pytest.approx(1.0, rel=0.05)

    def test_the_metal_travels_as_a_hole_rather_than_as_a_value(self, result):
        """The electrode is outside the solved domain, and `mask` is the protocol's way of
        saying so. Filling it with the electrode's potential instead would draw a block of
        solid colour and invite it to be read as field."""
        mask = np.array(result.data["mask"])
        assert 0 < mask.sum() < mask.size

    def test_the_published_window_is_the_one_that_was_solved(self, result):
        """Not the section's. The solve reaches past the payload because a truncation has to,
        and drawing the solver's array on the caller's bounds would stretch the picture onto a
        window it was never computed on."""
        rmin, zmin, rmax, zmax = result.data["bounds"]
        assert rmax > 0.030 - 0.0145, "the window reaches out past the electrode"
        assert zmin == pytest.approx(0.0), "the floor is the shell's coating"
        assert rmin >= 0.0, "a negative radius is not a domain a body of revolution has"

    def test_the_mesh_output_is_the_grid_the_answer_was_computed_on(self):
        """``grid2d`` is a resampling; ``mesh2d`` is the discretisation. The graded cells are
        what makes a 90 µm gap and a 3 mm truncation affordable in one section, and this is
        where that is visible rather than merely asserted."""
        meshed = run(section(), output="mesh2d")
        assert meshed.kind == "mesh2d"
        points = np.array(meshed.data["points"])
        assert points.shape[1] == 2
        assert set(meshed.data["point_fields"]) == {"V", "E"}
        spacings = np.unique(np.round(np.diff(np.unique(points[:, 0])), 12))
        assert spacings.size > 1, "a graded grid has more than one cell size in it"

    def test_the_solve_reports_how_it_went(self, result):
        assert result.converged is True
        assert result.residual is not None and result.residual < 1e-10
        assert result.stats["solves"] == 5.0
        assert result.stats["dofs"] > 0.0

    def test_the_cost_and_the_answer_stay_apart(self, result):
        """ADR-013's separation, and upstream's: an operator sizes a machine from `stats` and
        an engineer makes a decision from `metrics`. A key in both is a key neither can trust."""
        assert set(result.stats) & set(result.metrics) == set()


class TestTheCurvesTheMetricsAreReadOff:
    def test_both_are_there(self, result):
        assert [s.name for s in result.series] == ["calibration", "tilt"]

    def test_the_calibration_carries_the_measurement_beside_the_solve(self, result):
        """§8's benchmark is a curve against a curve. Reducing it to one worst-case percentage
        would hide *where* along the stroke the two part company."""
        curve = next(s for s in result.series if s.name == "calibration")
        traces = {trace.name: np.array(trace.values) for trace in curve.traces}
        assert set(traces) == {"solved", "fitted", "published", "parallel_plate"}
        assert np.max(np.abs(traces["solved"] / traces["published"] - 1.0)) < 0.10
        assert np.all(traces["solved"] > traces["parallel_plate"]), "fringe, at every gap"
        assert len(curve.x.values) == 5

    def test_the_calibration_falls_with_the_gap(self, result):
        curve = next(s for s in result.series if s.name == "calibration")
        solved = next(t for t in curve.traces if t.name == "solved").values
        assert list(solved) == sorted(solved, reverse=True)

    def test_the_tilt_curve_is_the_inference_drawn_out(self, result):
        """§2 says the tilt is inferred rather than solved. Publishing the curve is what makes
        that claim inspectable instead of a sentence on a page."""
        curve = next(s for s in result.series if s.name == "tilt")
        assert curve.x.unit == "deg", "the unit the published fit was made in"
        inferred = np.array(next(t for t in curve.traces if t.name == "inferred").values)
        published = np.array(next(t for t in curve.traces if t.name == "published").values)
        assert curve.x.values[0] == 0.0
        assert np.all(np.diff(inferred) > 0.0), "a tilt only ever reads high"
        assert np.max(np.abs(inferred / published - 1.0)) < 0.05


class TestTheCostEstimate:
    def test_every_shipped_example_fits_the_lab_s_budget(self):
        """The one that matters most, and the one this capability could most easily fail.

        A calibration is several solves, so the cost is a multiple of one section's cells
        rather than one section's cells — and an example whose params are past the server's
        budget is one the page shipping it cannot run. The check is against the lab's own
        200 000, not against upstream's default of two million.
        """
        solver = CapacitorAxi2D()
        geometry = section()
        for example in solver.examples:
            estimate = solver.estimate_cells(geometry, solver.Params(**example.params))
            assert estimate < LAB_MAX_CELLS, f"{example.title!r} asks for {estimate} cells"

    def test_the_defaults_fit_too(self):
        """Because a caller submitting `{}` is submitting the shipped configuration."""
        solver = CapacitorAxi2D()
        assert solver.estimate_cells(section(), solver.Params()) < LAB_MAX_CELLS

    def test_it_charges_for_every_solve_in_the_sweep(self):
        """An estimate that quoted one section's cells would let a twenty-five gap run through
        a budget sized for one, which is the whole failure this method exists to prevent."""
        solver = CapacitorAxi2D()
        geometry = section()
        few = solver.estimate_cells(geometry, solver.Params(**{**QUICK, "samples": 5}))
        many = solver.estimate_cells(geometry, solver.Params(**{**QUICK, "samples": 15}))
        assert many > 2.0 * few

    def test_and_for_the_mesh_study_when_it_was_asked_for(self):
        solver = CapacitorAxi2D()
        geometry = section()
        plain = solver.estimate_cells(geometry, solver.Params(**QUICK))
        checked = solver.estimate_cells(
            geometry, solver.Params(**{**QUICK, "convergence_check": True})
        )
        assert checked > plain

    def test_a_mesh_run_is_not_charged_for_a_raster_it_never_builds(self):
        """``mesh2d`` publishes the solver's own cells and allocates no uniform grid at all.
        Charging for one would bill a job for an array it does not make — and at the shipped
        resolution that is enough to have a run refused for a reason untrue of it."""
        solver = CapacitorAxi2D()
        geometry = section()
        rastered = solver.estimate_cells(geometry, solver.Params(**QUICK))
        meshed = solver.estimate_cells(
            geometry, solver.Params(**{**QUICK, "output": "mesh2d"})
        )
        nz, nr = 64, 64
        assert meshed < rastered
        assert rastered - meshed >= min(nz, nr)


class TestWhatTheRunSaysAboutItself:
    def test_a_stroke_wider_than_the_gap_is_clipped_and_said_so(self):
        """The stroke is a parameter default and the gap is in the geometry, so the two can
        disagree without anyone having asked for it. Failing the job on a number the visitor
        never typed would be the wrong answer; doing it silently would be worse."""
        narrow = run(section(gap=40e-6), stroke=50e-6)
        assert any("clipped" in note for note in narrow.warnings)
        assert narrow.metrics["linear_halfstroke"] < 40e-6

    def test_a_short_sweep_says_the_fit_is_following_its_points(self):
        short = run(section(), samples=3)
        assert any("three-coefficient fit" in note for note in short.warnings)

    def test_the_mesh_study_reports_what_it_moved(self):
        studied = run(section(), samples=3, convergence_check=True)
        assert any("mesh and truncation study" in note for note in studied.warnings)

    def test_a_healthy_run_says_nothing(self, result):
        """Warnings are for what did not go to plan. A verification that passed is not news,
        and a result that narrates its own success teaches a reader to skim the list."""
        assert result.warnings == []


class TestTheDeclarations:
    """What a caller can learn before spending a solve."""

    def test_it_takes_the_axisymmetric_kind_and_only_that(self):
        """The refusal the kind exists for: the same outline sent as `regions2d` means a
        plane slice, and a solver that accepted both would answer the wrong one silently."""
        assert CapacitorAxi2D.geometry_types == ["axisymmetric2d"]

    def test_the_tilt_metrics_declare_which_unit_they_are_in(self):
        """The one ambiguity the source leaves open, closed on the wire rather than in prose:
        a caller reading the catalogue can tell the two apart without running anything."""
        units = {spec.name: spec.unit for spec in CapacitorAxi2D.metrics}
        assert units["tilt_per_deg2"] == "F/deg2"
        assert units["tilt_per_rad2"] == "F/rad2"

    def test_the_inference_is_declared_as_an_assumption(self):
        """§2's hybrid method is a modelling decision, and `excludes` is what lets a caller
        ask 'can this tell me about an azimuthal variation?' and get a definite no."""
        tilt = next(a for a in CapacitorAxi2D.assumptions if a.name == "tilt_is_inferred")
        assert "three_dimensional_tilt" in tilt.excludes

    def test_it_declares_what_its_residual_measures(self):
        """A bare float is what `ConvergenceSpec` exists to stop. `return` rather than `fail`
        because a CG solve stopped at its cap is still the iterate it reached."""
        assert CapacitorAxi2D.convergence is not None
        assert CapacitorAxi2D.convergence.on_failure == "return"
        assert CapacitorAxi2D.convergence.unit is None


class TestAgainstTheUpstreamAdapter:
    """§8's third row, and the receipt for ADR-026.

    Upstream ships ``mock.electrostatics_axi2d`` for exactly this geometry kind — and the
    kind's own documentation names *this sensor* as the case that motivated it. So the first
    question any reviewer should ask about this exercise is why the lab wrote a solver at all,
    and the answer has two halves. The half that would hold even if the mock were perfect is
    ADR-026's: a calibration is a curve, and none of §7's three headline numbers is a reduction
    of any single field. The half measured here is that on this configuration the mock cannot
    be used as the check either.

    Both solvers are given the **same section**, which is why
    :func:`physics_lab.solvers.capacitor_axi2d._read` accepts a grounded region: a cross-check
    between two payloads is a comparison of two geometries.
    """

    @staticmethod
    def both_plates(shell_top: float = 1.0e-3, gap: float = 90e-6) -> Axisymmetric2D:
        """The section with the shell drawn as a region, which upstream needs and this solver
        merely tolerates.

        The coating is a millimetre thick here and a micron thick in life. That is not sloppy,
        it is the first half of the finding: at the real thickness no grid point of a uniform
        raster over a 10 mm window falls inside it, so the mock pins one potential instead of
        two, warns that there is no capacitance to report, and returns a uniform field — which
        it is right to do and which cannot be checked against.
        """
        inner, outer, thickness, chamfer = 0.011, 0.0145, 0.004, 0.0015
        bottom = shell_top + gap
        top = bottom + thickness
        return Axisymmetric2D(
            bounds=(0.0, 0.0, 0.030, 0.010),
            background={"eps_r": 1.0},
            regions=[
                {
                    "name": "shell",
                    "shape": {
                        "type": "polygon2d",
                        "points": [[1e-7, 1e-7], [0.0299, 1e-7], [0.0299, shell_top],
                                   [1e-7, shell_top]],
                    },
                    "material": {"voltage": 0.0},
                },
                {
                    "name": "electrode",
                    "shape": {
                        "type": "polygon2d",
                        "points": [
                            [inner, bottom],
                            [outer, bottom],
                            [outer, top - chamfer],
                            [outer - chamfer, top],
                            [inner + chamfer, top],
                            [inner, top - chamfer],
                        ],
                    },
                    "material": {"voltage": 1.0},
                },
            ],
        )

    @staticmethod
    def upstream(geometry: Axisymmetric2D, resolution: int) -> float:
        from fenixspoon.solvers.mock_electrostatics import MockElectrostaticsAxi2D

        mock = MockElectrostaticsAxi2D()
        result = mock.solve(
            geometry,
            mock.Params(resolution=resolution, iterations=40000, write_vtk=False),
            SolverContext(progress_cb=lambda event: None),
        )
        assert result.converged, "the relaxation stopped short; this is not the comparison"
        return result.metrics["capacitance"]

    def test_the_shell_is_read_as_the_floor_so_one_section_serves_both(self):
        """The precondition for everything below. Drawn or left out, the coating means the
        same thing, and the capacitance is the same number either way."""
        drawn = run(self.both_plates())
        implied = run(section())
        assert drawn.metrics["capacitance"] == pytest.approx(
            implied.metrics["capacitance"], rel=0.01
        )

    def test_a_grounded_region_floating_in_the_gap_is_refused(self):
        """Tolerating the shell is not the same as tolerating a conductor anywhere. One that
        does not reach the floor would be ignored, and the capacitance would come back as
        though it were not there."""
        with pytest.raises(ValueError, match="floats"):
            floating = self.both_plates()
            shell = floating.regions[0]
            shell.shape.points = [[0.001, 0.002], [0.020, 0.002], [0.020, 0.003],
                                  [0.001, 0.003]]
            run(floating)

    def test_the_uniform_grid_cannot_reach_this_configuration(self):
        """The measurement ADR-026 rests on.

        A 90 µm gap in a 10 mm window is a fraction of a cell at every resolution the mock's
        schema allows: 512 — its ceiling — is a 59 µm cell, and the gap the whole answer
        depends on is one and a half of them. The capacitance comes back around half of the
        measured one, and it stays there.
        """
        geometry = self.both_plates()
        published = 0.031904e-9
        for resolution in (128, 256):
            assert self.upstream(geometry, resolution) < 0.6 * published

    def test_and_refining_it_does_not_converge_the_answer(self):
        """The half that makes it a wrong grid rather than a coarse one — ADR-018's finding,
        on a different mock and a sharper case.

        Between 128 and 256 the answer does not approach anything: it moves by tens of per
        cent and not always in the same direction, because what changes with the resolution is
        whether a grid line happens to fall inside the gap. There is no refinement path along
        which this sensor stays the same sensor, which is precisely why a benchmark against it
        would tell the lab's solver nothing.
        """
        geometry = self.both_plates()
        coarse = self.upstream(geometry, 128)
        finer = self.upstream(geometry, 256)
        assert abs(finer / coarse - 1.0) > 0.01, "if these agreed, the argument above is wrong"

    def test_where_the_lab_s_own_solver_lands_on_the_same_section(self):
        """For contrast, and it is the whole of the contrast: the grid is fitted to the
        geometry, so the gap is resolved across cells at a total cost the mock spends on one
        of its coarser attempts."""
        solved = run(self.both_plates()).metrics["capacitance"]
        assert solved == pytest.approx(0.031904e-9, rel=0.05)
