"""``lab.heatsink3d`` as the protocol sees it — ``docs/exercises/heat-sink.md`` §13.

The physics is verified in ``test_heatsink_solid_method.py`` against the plane solver and
against the behaviour of the two effects the third dimension adds. What is checked here is the
*adapter*: that the depth really does travel in the geometry rather than in a parameter, that
what comes back is a well-formed ``mesh3d``, that the retiled mesh is small enough to be worth
sending inline and is declared honestly to the cell budget — and that the two solvers refuse
each other's geometry, which is the refusal protocol 1.17 was admitted to make.
"""

import numpy as np
import pytest
from fenixspoon.geometry import Regions2D, Regions3D
from fenixspoon.protocol import Mesh3DData
from fenixspoon.solvers.registry import registered_solvers

from physics_lab.solvers.heatsink2d import HeatSink2D
from physics_lab.solvers.heatsink3d import HeatSink3D

#: Coarse everywhere, so the suite stays quick. Every claim here is about shape and
#: declaration; the numbers are the method suite's business.
COARSE = {
    "cell_size": 0.0030,
    "depth_cell_size": 0.0060,
    "display_cell_size": 0.0060,
    "decompose": False,
}


def envelope(width=0.060, height=0.030, depth=0.060):
    """The space the sink may occupy, as ``regions3d``.

    The same "site" role the plane adapter's geometry plays, with one coordinate added — and
    that coordinate is the whole point: it is where the extrusion length lives now. Inset by a
    hair, because a region's bounding box must lie strictly inside the domain bounds.
    """
    eps = 1e-6
    return Regions3D.model_validate(
        {
            "type": "regions3d",
            "bounds": [0.0, 0.0, 0.0, width, height, depth],
            "background": {},
            "regions": [
                {
                    "name": "envelope",
                    "shape": {
                        "type": "box3d",
                        "min": [eps, eps, eps],
                        "max": [width - eps, height - eps, depth - eps],
                    },
                    "material": {},
                }
            ],
        }
    )


class _Context:
    def __init__(self):
        self.events = []

    def progress(self, event):
        self.events.append(event)


def run(geometry=None, **params):
    solver = HeatSink3D()
    ctx = _Context()
    validated = HeatSink3D.Params(**{**COARSE, **params})
    return solver.solve(geometry or envelope(), validated, ctx), ctx


@pytest.fixture(scope="module")
def nominal():
    return run()[0]


class TestTheTwoAdaptersRefuseEachOthersGeometry:
    """The refusal protocol 1.17 exists to make, seen from the lab's side.

    Before it, a caller who meant a body could send a section and get a per-unit-depth answer
    scaled by a number in `params` — confidently, and wrong by whatever the spreading was. The
    kinds are what make that a `422` instead, and the two adapters are what make it a `422`
    *here*: it costs one line each and no code.
    """

    def test_the_plane_adapter_takes_only_a_section(self):
        assert HeatSink2D.geometry_types == ["regions2d"]

    def test_the_solid_adapter_takes_only_a_body(self):
        assert HeatSink3D.geometry_types == ["regions3d"]

    def test_they_are_two_capabilities_and_not_a_switch(self):
        """A boolean parameter would have made both refusals a wrong number instead."""
        names = {getattr(s, "name", None) for s in registered_solvers()}
        assert {"lab.heatsink2d", "lab.heatsink3d"} <= names

    def test_a_page_filtering_on_physics_finds_both(self):
        assert HeatSink3D.physics == HeatSink2D.physics == "heatsink"


class TestTheDepthTravelsInTheGeometry:
    def test_a_longer_envelope_is_a_longer_sink(self):
        """`depth` is not in `params` at all, so the only way to make the sink longer is to
        send a longer body. The mass is the cheapest proof that the solver read it."""
        assert "depth" not in HeatSink3D.Params.model_fields
        short = run(envelope(depth=0.060))[0]
        long_ = run(envelope(depth=0.120))[0]
        assert long_.metrics["mass"] == pytest.approx(2.0 * short.metrics["mass"], rel=1e-9)

    def test_the_width_still_comes_from_the_envelope_too(self):
        wide = run(envelope(width=0.120))[0]
        narrow = run(envelope(width=0.060))[0]
        assert wide.metrics["mass"] > narrow.metrics["mass"]


class TestTheResultEnvelope:
    def test_it_is_a_well_formed_mesh3d(self, nominal):
        assert nominal.kind == "mesh3d"
        Mesh3DData.model_validate(nominal.data)

    def test_every_node_carries_every_field(self, nominal):
        nodes = len(nominal.data["points"])
        for name in ("T", "flux"):
            assert len(nominal.data["point_fields"][name]) == nodes

    def test_the_points_have_three_coordinates(self, nominal):
        assert all(len(point) == 3 for point in nominal.data["points"][:50])

    def test_the_bounds_are_the_body_and_not_the_envelope(self, nominal):
        """The envelope is 30 mm tall and the nominal profile is 30 mm of metal, but the mesh
        bounds are the *sink*: a `mesh3d` carries what exists, with no mask and no air."""
        xmin, ymin, zmin, xmax, ymax, zmax = nominal.data["bounds"]
        assert (xmin, ymin, zmin) == (0.0, 0.0, 0.0)
        assert ymax == pytest.approx(0.030)
        assert zmax == pytest.approx(0.060)

    def test_the_mesh_is_smaller_than_the_solve(self, nominal):
        """Six tetrahedra per solved cell would be tens of megabytes of JSON. The retiling is
        what makes an inline solid affordable, and this is the assertion that it happened."""
        assert nominal.stats["display_tets"] < 6 * nominal.stats["cells"]

    def test_the_progress_stream_says_what_it_is_doing(self, nominal):
        result, ctx = run()
        assert any("meshing" in event.message for event in ctx.events)


class TestTheCostIsDeclaredBeforeTheJobIsAccepted:
    def test_the_estimate_covers_every_solve_the_job_will_run(self):
        """Upstream's note on `mesh3d` is that an adapter emitting one and not estimating its
        cost honestly is a defect rather than an omission. Honest here means the decomposition's
        second solve counts, because it is a second solve."""
        one = HeatSink3D.estimate_cells(envelope(), HeatSink3D.Params(**COARSE))
        two = HeatSink3D.estimate_cells(
            envelope(), HeatSink3D.Params(**{**COARSE, "decompose": True})
        )
        assert two > one

    def test_it_is_not_an_under_estimate(self, nominal):
        estimate = HeatSink3D.estimate_cells(envelope(), HeatSink3D.Params(**COARSE))
        assert estimate >= nominal.stats["cells"] + nominal.stats["display_tets"]

    def test_a_profile_that_cannot_exist_defers_to_the_parameter_error(self):
        """Sixty fins of 2 mm do not fit across a 60 mm base. The estimate says nothing rather
        than raising, so the job reaches the validator whose message explains it."""
        params = HeatSink3D.Params(**{**COARSE, "fin_count": 60, "fin_thickness": 0.002})
        assert HeatSink3D.estimate_cells(envelope(), params) is None


class TestTheHeadlineMetrics:
    @pytest.mark.parametrize(
        "metric",
        [
            "thermal_resistance",
            "thermal_resistance_extruded",
            "depth_correction",
            "end_loss_fraction",
            "t_max",
            "t_rise",
            "mass",
            "score",
        ],
    )
    def test_each_is_declared_and_returned(self, nominal, metric):
        assert metric in {m.name for m in HeatSink3D.metrics}
        assert metric in nominal.metrics

    def test_the_two_reductions_are_not_declared_as_reductions(self):
        """`t_max` and `flux_max` carry no `field`/`reduction` here, where the plane adapter
        gives both. The mesh that travels back is a coarser retiling, so a reduction over it is
        not the number the solve found — and declaring one would promise a payload that cannot
        keep it."""
        declared = {m.name: m for m in HeatSink3D.metrics}
        assert declared["t_max"].field is None
        assert declared["t_max"].reduction is None
        plane = {m.name: m for m in HeatSink2D.metrics}
        assert plane["t_max"].field == "T"

    def test_the_peak_comes_from_the_solve_and_not_from_the_picture(self, nominal):
        """Which is why it is supplied rather than left to be computed: the coarse mesh's own
        maximum is lower, and two answers to one question is the failure."""
        coarse_peak = max(nominal.data["point_fields"]["T"])
        assert nominal.metrics["t_max"] >= coarse_peak - 1e-9

    def test_the_third_dimension_reports_both_of_its_effects(self):
        full = run(decompose=True)[0]
        assert full.metrics["spreading_resistance"] > 0.0
        assert full.metrics["end_gain"] > 0.0


class TestTheModelSwitchesAnnounceThemselves:
    def test_a_device_covering_the_length_is_told_it_found_nothing(self):
        result, _ = run(footprint_depth=1.0)
        assert any("whole length" in note for note in result.warnings)

    def test_shut_ends_are_declared_an_idealisation(self):
        result, _ = run(ends_open=False)
        assert any("adiabatic" in note for note in result.warnings)

    def test_skipping_the_decomposition_says_what_was_lost(self):
        result, _ = run(decompose=False)
        assert any("cancelled" in note for note in result.warnings)

    def test_the_nominal_run_is_quiet(self):
        result, _ = run(decompose=True)
        assert result.warnings == []


class TestTheDeclarationsSayWhatTheThirdDimensionIsDoing:
    def test_the_plane_assumption_is_replaced_rather_than_kept(self):
        names = {a.name for a in HeatSink3D.assumptions}
        assert "three_dimensional_solid" in names
        assert "two_dimensional_extrusion" not in names

    def test_the_radiation_model_declares_what_it_did_not_carry_into_3d(self):
        prismatic = {a.name: a for a in HeatSink3D.assumptions}["prismatic_radiation"]
        assert "axial_radiative_exchange" in prismatic.excludes

    def test_what_is_unchanged_is_the_same_declaration_and_not_a_copy(self):
        """A second wording of "conductivity is constant" is a second thing to keep true."""
        plane = {a.name: a for a in HeatSink2D.assumptions}
        solid = {a.name: a for a in HeatSink3D.assumptions}
        for name in ("steady_state", "grey_diffuse_radiation", "constant_properties"):
            assert solid[name] is plane[name]


class TestParametersAreRefused:
    def test_an_unknown_finish(self):
        with pytest.raises(ValueError, match="finish must be one of"):
            HeatSink3D.Params(finish="chrome")

    def test_a_fan_with_no_speed(self):
        with pytest.raises(ValueError, match="face_velocity"):
            HeatSink3D.Params(cooling="forced")

    def test_a_section_where_a_body_belongs(self):
        """Belt and braces on the type itself: the server refuses this from `geometry_types`
        before the adapter runs, and the adapter would not know what to do with it either."""
        section = Regions2D(
            type="regions2d",
            bounds=[0.0, 0.0, 0.060, 0.030],
            background={},
            regions=[
                {
                    "name": "envelope",
                    "shape": {
                        "type": "polygon2d",
                        "points": [
                            [1e-6, 1e-6],
                            [0.060 - 1e-6, 1e-6],
                            [0.060 - 1e-6, 0.030 - 1e-6],
                            [1e-6, 0.030 - 1e-6],
                        ],
                    },
                    "material": {},
                }
            ],
        )
        with pytest.raises((AttributeError, ValueError, TypeError)):
            HeatSink3D().solve(section, HeatSink3D.Params(**COARSE), _Context())


def test_the_field_the_page_draws_is_finite_everywhere(nominal):
    """A NaN in a `point_fields` array is a hole in the picture, and `slice` would carry it
    straight through to the canvas."""
    for values in nominal.data["point_fields"].values():
        assert np.all(np.isfinite(values))
