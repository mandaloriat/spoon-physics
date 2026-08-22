"""``lab.heatsink3d`` — the heat-sink exercise with a body instead of a section.

``docs/exercises/heat-sink.md`` §13. The physics is in
:mod:`physics_lab.solvers.heatsink_solid`, which imports no Fenix Spoon; this file is the only
one that speaks the protocol. Its sibling ``lab.heatsink2d`` is not replaced and not deprecated
— it is the faster, finer answer to the question the exercise is *about*, which is fin count,
and this one is the answer to the question it could not ask.

**Why a second adapter rather than a switch on the first.** Because the geometry kind is
different, and that is the whole point of protocol 1.17. ``lab.heatsink2d`` declares
``regions2d`` and ``lab.heatsink3d`` declares ``regions3d``, so sending a solid to the plane
solver is a `422` from the server before any of this code runs, and sending a section to the
solid one likewise. A boolean parameter would have made both of those a wrong number instead —
which is precisely the failure upstream's
[ADR 0006](https://github.com/mandaloriat/fenix-spoon/blob/main/docs/adr/0006-three-dimensions.md)
admitted the kind to prevent. See ADR-023.

**Where the depth went.** It was ``params.depth`` on the plane adapter, because a `regions2d`
has nowhere to put a length and every number it reports is per unit depth until something
multiplies it back up. Here it is the geometry's own ``z`` extent, read off ``bounds``. That
move is the entire content of "the third coordinate exists": the same quantity, in the place
that can refuse to be inconsistent with it.

**Where the rest of the geometry lives** is unchanged from the plane adapter and for the
unchanged reason: the envelope travels as geometry, the profile travels as five numbers in
``params``, because the correlation needs the *channel width* and recovering that from a list of
solids would be inferring a quantity from a picture (ADR-019).

**What comes back is a ``mesh3d``**, retiled coarser than the solve — see
:class:`~physics_lab.solvers.heatsink_solid.Lattice` for why that is the right way round — and
a page draws it by asking for a `slice`, which is a `grid2d` and needs no new rendering code
anywhere. That is ADR 0006 §6 working as advertised.
"""

import numpy as np
from fenixspoon.geometry import Regions3D
from fenixspoon.solvers.base import (
    Assumption,
    CapabilityExample,
    MetricSpec,
    ProgressEvent,
    Solver,
    SolverContext,
    SolverResult,
)
from fenixspoon.solvers.registry import register
from pydantic import BaseModel, Field, model_validator

from . import heatsink, heatsink2d, heatsink_solid

VERSION = "1.0.0"

#: Everything the plane adapter already says correctly, by name rather than by copy. A second
#: wording of "conductivity is constant" is a second thing to keep true.
_SHARED_METRICS = {spec.name: spec for spec in heatsink2d.HEATSINK_METRICS}
_SHARED_ASSUMPTIONS = {a.name: a for a in heatsink2d.HEATSINK_ASSUMPTIONS}

HEATSINK3D_METRICS = [
    # `t_max` and `flux_max` are declared **without** a field and a reduction here, where the
    # plane adapter declares both. The reason is the mesh that travels back: it is a coarser
    # retiling of the body, so `max` over its `T` is not the peak the solve found, and a
    # declaration saying "this metric is that reduction" would be a promise the payload cannot
    # keep. Upstream's `fill_declared_metrics` is right to compute a declared reduction; what
    # is wrong is declaring one whose input is not the field the number came from.
    MetricSpec(
        name="t_max",
        unit="degC",
        description=(
            "Peak temperature in the metal — the number the device's rating is read against. "
            "Taken from the solve, which is finer than the mesh this result carries."
        ),
    ),
    _SHARED_METRICS["t_rise"],
    MetricSpec(
        name="flux_max",
        unit="W/m^2",
        description=(
            "Peak conductive flux magnitude, k|grad T|, over all three directions. Where the "
            "metal is working hardest — which under a small device is the base beside it, not "
            "a fin root."
        ),
    ),
    _SHARED_METRICS["thermal_resistance"],
    MetricSpec(
        name="thermal_resistance_extruded",
        unit="K/W",
        description=(
            "What the plane model says the same sink does: `lab.heatsink2d`'s answer, on the "
            "same in-plane grid and the same conditions. Reported beside the real one so the "
            "difference below is a comparison rather than a claim."
        ),
    ),
    MetricSpec(
        name="spreading_resistance",
        unit="K/W",
        description=(
            "What it costs that the device is shorter than the extrusion. Heat has to run "
            "along the base to reach the far fins, and that run has a temperature drop the "
            "plane problem has nowhere to put. Always positive, and it grows with the length "
            "the heat has to travel and with how poorly the base conducts."
        ),
    ),
    MetricSpec(
        name="end_gain",
        unit="K/W",
        description=(
            "What the two cut ends are worth. They are surface, they are not in the plane "
            "model at all, and on a short extrusion they are worth more than the spreading "
            "costs — which is why the plane model has been getting away with it."
        ),
    ),
    MetricSpec(
        name="depth_correction",
        unit="K/W",
        description=(
            "spreading_resistance - end_gain: the net of the two, and the number to add to "
            "thermal_resistance_extruded to get the answer. Its *sign* is the finding — "
            "negative on a stubby sink, positive on a long one."
        ),
    ),
    MetricSpec(
        name="end_loss_fraction",
        unit="1",
        description=(
            "Share of the heat leaving through the two cut ends. Reported so end_gain is a "
            "measurement rather than a residual: it says how much surface the ends really are."
        ),
    ),
    _SHARED_METRICS["mass"],
    _SHARED_METRICS["score"],
    _SHARED_METRICS["fin_efficiency"],
    _SHARED_METRICS["radiative_fraction"],
    _SHARED_METRICS["view_factor_to_room"],
    _SHARED_METRICS["h_convective"],
]

HEATSINK3D_ASSUMPTIONS = [
    _SHARED_ASSUMPTIONS["steady_state"],
    Assumption(
        name="three_dimensional_solid",
        statement=(
            "The body is meshed in all three directions and conduction along the extrusion is "
            "solved, so the device may heat only part of the length and the two cut ends are "
            "surfaces like any other. This is what replaces the plane adapter's "
            "`two_dimensional_extrusion`, and it is the only physics the third dimension "
            "adds: everything on the boundary — the correlation, the enclosure, the view "
            "factors — is the same model, evaluated on a longer body."
        ),
    ),
    _SHARED_ASSUMPTIONS["correlated_convection_coefficient"],
    Assumption(
        name="prismatic_radiation",
        statement=(
            "A channel's radiative enclosure is the one its cross-section defines, solved at "
            "every station along the length with that station's wall temperatures. The "
            "enclosure geometry is exact — a channel between two fins really is prismatic — "
            "and what is neglected is exchange **along** it, a hot station seeing a cooler "
            "one. That transfer is small where the axial temperature gradient is small, which "
            "is the case wherever the metal conducts well; it is the first thing to distrust "
            "on a poor conductor with a small device. The two cut ends are treated as looking "
            "straight at the room."
        ),
        excludes=["axial_radiative_exchange", "end_cap_view_factors"],
    ),
    _SHARED_ASSUMPTIONS["grey_diffuse_radiation"],
    _SHARED_ASSUMPTIONS["constant_properties"],
]


@register
class HeatSink3D(Solver):
    """Steady conduction in the solid sink, with convection and radiation off every face."""

    name = "lab.heatsink3d"
    title = "Heat sink — the solid body, and what the section could not say"
    summary = (
        "The heat-sink exercise on a body with a length: the same conduction, the same "
        "correlated convection coefficient and the same radiative enclosures, solved in three "
        "dimensions so the device can heat part of the extrusion rather than all of it. "
        "Reports the spreading resistance that costs, the two cut ends that pay some of it "
        "back, and the plane model's answer beside them."
    )
    geometry_types = ["regions3d"]
    physics = "heatsink"
    availability = "finite-volume"
    requires = ["numpy"]
    version = VERSION
    deterministic = True
    metrics = HEATSINK3D_METRICS
    assumptions = HEATSINK3D_ASSUMPTIONS
    examples = [
        CapabilityExample(
            title="the nominal sink, with a real device on it",
            description=(
                "30 W through a 30 x 30 mm die on a 60 mm extrusion. Short enough that the "
                "two cut ends are worth more than the spreading costs, so the answer comes "
                "out *below* the plane model's — which is the result to look at twice."
            ),
            params={"footprint_depth": 0.030},
        ),
        CapabilityExample(
            title="the same die on a long extrusion",
            description=(
                "The envelope stretched to 200 mm and the die left where it is. Now the heat "
                "has 85 mm of base to cross on each side, the spreading dominates, and the "
                "plane model is optimistic by about a seventh."
            ),
            params={"footprint_depth": 0.030},
        ),
        CapabilityExample(
            title="the plane model, reproduced exactly",
            description=(
                "Device along the whole length and the ends shut: this is the problem "
                "`lab.heatsink2d` solves, and the two agree to the solver tolerance. The "
                "residual `extruded_limit` is that agreement, reported rather than asserted."
            ),
            params={"footprint_depth": 1.0, "ends_open": False},
        ),
    ]

    class Params(BaseModel):
        """The profile, the duty, and the two knobs that only move the error.

        Almost the plane adapter's, with three differences that are all the third dimension:
        ``depth`` is gone because the geometry carries it, ``footprint_depth`` and
        ``ends_open`` are new because a length is a thing a device can be shorter than, and the
        fin-count sweep is gone — twenty solves is what the plane adapter is *for*.
        """

        # --- Design: the profile
        base_thickness: float = Field(
            0.005, gt=0.0, le=0.05, description="Base slab thickness, m."
        )
        fin_count: int = Field(10, ge=1, le=60, description="Number of fins across the base.")
        fin_thickness: float = Field(0.0015, gt=0.0, le=0.02, description="Fin thickness, m.")
        fin_height: float = Field(0.025, gt=0.0, le=0.2, description="Fin height, m.")
        conductivity: float = Field(
            201.0, gt=0.0, description="Solid conductivity, W/m.K. Aluminium 6063 is 201."
        )
        density: float = Field(2700.0, gt=0.0, description="Solid density, kg/m^3.")
        finish: str = Field(
            "black_anodised",
            description=(
                "Surface finish, which sets the emissivity: mill (0.05), clear_anodised "
                "(0.6), black_anodised (0.8)."
            ),
        )

        # --- Conditions: the duty
        power: float = Field(30.0, gt=0.0, description="Dissipated power, W.")
        t_ambient: float = Field(25.0, description="Ambient air temperature, degC.")
        footprint_width: float = Field(
            0.030, gt=0.0, description="Contact width of the device across the base, m."
        )
        footprint_depth: float = Field(
            0.030,
            gt=0.0,
            description=(
                "Contact length of the device **along** the extrusion, m — the input the "
                "plane adapter has no way to accept. The device sits centred; a value at or "
                "above the extrusion length means it heats the whole of it, which is what the "
                "plane model assumes."
            ),
        )
        cooling: str = Field("natural", description='"natural" or "forced".')
        face_velocity: float = Field(
            0.0, ge=0.0, le=20.0, description="Air speed along the channels, m/s. Forced only."
        )
        base_mounted_flush: bool = Field(
            True, description="Is the underside blocked by the mounting?"
        )
        ends_open: bool = Field(
            True,
            description=(
                "Do the two cut ends lose heat? True is a sink in open air. False is the "
                "idealisation the plane model makes — set it *and* let the device span the "
                "whole length and this solver reproduces `lab.heatsink2d` exactly, which is "
                "what the `extruded_limit` residual reports."
            ),
        )

        # --- Advanced
        cell_size: float = Field(
            0.0015,
            gt=2e-4,
            le=0.01,
            description=(
                "Target cell edge in the cross-section, m. Coarser than the plane adapter's "
                "default because the cell count is now multiplied by the number of stations."
            ),
        )
        depth_cell_size: float = Field(
            0.0025,
            gt=5e-4,
            le=0.02,
            description=(
                "Target cell edge along the extrusion, m. Its own knob because there is no "
                "geometric feature along the length except the two edges of the device, and "
                "what it resolves is a smooth spread rather than a boundary layer."
            ),
        )
        display_cell_size: float = Field(
            0.0025,
            gt=1e-3,
            le=0.02,
            description=(
                "Cell edge of the tetrahedral mesh that travels back, m. It is not the solve "
                "grid: six tetrahedra per solved cell would be tens of megabytes of JSON for "
                "a picture nobody can see that finely."
            ),
        )
        radiation: bool = Field(
            True,
            description=(
                "Switch radiation off to reproduce the model upstream's heat adapters solve. "
                "A *model* change rather than a setting, and the run row records it."
            ),
        )
        h_override: float | None = Field(
            None,
            ge=0.0,
            description="Pin the convection coefficient instead of taking it from the channel.",
        )
        decompose: bool = Field(
            True,
            description=(
                "Run the second solve — the same body with its ends shut — that separates the "
                "spreading from what the ends give back. Off halves the run time and leaves "
                "only their net, `depth_correction`."
            ),
        )

        @model_validator(mode="after")
        def _check(self) -> "HeatSink3D.Params":
            if self.finish not in heatsink2d.FINISHES:
                raise ValueError(
                    f"finish must be one of {sorted(heatsink2d.FINISHES)}, not {self.finish!r}"
                )
            if self.cooling not in ("natural", "forced"):
                raise ValueError('cooling must be "natural" or "forced"')
            if self.cooling == "forced" and self.face_velocity <= 0.0:
                raise ValueError(
                    "forced cooling needs a face_velocity above zero — otherwise say natural"
                )
            return self

    @classmethod
    def estimate_cells(cls, geometry: Regions3D, params: "HeatSink3D.Params") -> int | None:
        """What this job will ask for, before it is accepted.

        Overridden rather than left to the wall-clock timeout because a `mesh3d` is the first
        payload whose *size* is the problem, and upstream's own note is that an adapter
        emitting one without estimating honestly is a defect. Honest here means counting all
        three costs: the solve, the second solve the decomposition runs, and the tetrahedra that
        travel back — six per display cell, which for a coarse-enough display grid is the
        largest of the three.
        """
        try:
            profile, depth = _profile_and_depth(geometry, params)
        except ValueError:
            # An unusable profile is the parameter validator's refusal to make, with its
            # message. Saying nothing here lets the job through to that better error.
            return None
        solves = 2 if (params.decompose and params.ends_open) else 1
        footprint = min(params.footprint_depth, depth)
        solved = _section_cells(profile, params.cell_size) * _stations(
            depth, footprint, params.depth_cell_size
        )
        display = _section_cells(profile, params.display_cell_size) * _stations(
            depth, footprint, params.display_cell_size
        )
        return solves * solved + 6 * display

    def solve(
        self,
        geometry: Regions3D,
        params: "HeatSink3D.Params",
        ctx: SolverContext,
    ) -> SolverResult:
        profile, depth = _profile_and_depth(geometry, params)
        conditions = _conditions(params, depth)
        extrusion = heatsink_solid.Extrusion(
            footprint_depth=min(params.footprint_depth, depth),
            cell_size=params.depth_cell_size,
            ends_open=params.ends_open,
        )
        numerics = heatsink.Numerics(cell_size=params.cell_size)

        total = 3 if (params.decompose and params.ends_open) else 2
        ctx.progress(
            ProgressEvent(iteration=0, total=total, message="meshing the body")
        )
        solution = heatsink_solid.solve(
            profile, conditions, extrusion, numerics, decompose=params.decompose
        )
        ctx.progress(
            ProgressEvent(
                iteration=total,
                total=total,
                message=(
                    f"converged in {solution.passes} passes, "
                    f"energy closes to {solution.residuals['energy_balance']:.1e}"
                ),
            )
        )

        lattice = heatsink_solid.display_lattice(
            profile, conditions, extrusion, solution, params.display_cell_size
        )
        metrics = {
            key: solution.metrics[source]
            for key, source in _METRIC_SOURCES.items()
            if source in solution.metrics
        }

        return SolverResult(
            kind="mesh3d",
            data=_as_mesh(lattice),
            stats={
                "cells": float(solution.cells),
                "display_tets": float(lattice.cells),
                "dofs": float(solution.cells),
                "picard_passes": float(solution.passes),
                "cg_iterations": float(solution.cg_iterations),
            },
            metrics={k: float(v) for k, v in metrics.items() if np.isfinite(v)},
            converged=solution.passes < numerics.max_passes,
            residual=solution.residuals["energy_balance"],
            warnings=_warnings(solution, params, depth),
        )


#: Metric name on the wire, to the key the physics module reports it under. A table rather than
#: a rename inside the solver, so the exercise's vocabulary and the protocol's stay separable.
_METRIC_SOURCES = {
    # Supplied rather than left to `fill_declared_metrics`, and the reason is the display mesh:
    # the declared reduction would take `t_max` over the *coarse* field that travels back, and
    # report a number a degree below the one `t_rise` is computed from. Two answers to one
    # question is the failure; the solve knows which one is right.
    "t_max": "t_max_c",
    "t_rise": "t_rise_k",
    "flux_max": "flux_max_w_m2",
    "thermal_resistance": "thermal_resistance_k_w",
    "thermal_resistance_extruded": "thermal_resistance_extruded_k_w",
    "spreading_resistance": "spreading_resistance_k_w",
    "end_gain": "end_gain_k_w",
    "depth_correction": "depth_correction_k_w",
    "end_loss_fraction": "end_loss_fraction",
    "mass": "mass_kg",
    "score": "score_k_kg_w",
    "fin_efficiency": "fin_efficiency",
    "radiative_fraction": "radiative_fraction",
    "view_factor_to_room": "view_factor_to_room",
    "h_convective": "h_convective_w_m2k",
}


def _profile_and_depth(
    geometry: Regions3D, params: "HeatSink3D.Params"
) -> tuple[heatsink.Profile, float]:
    """The cross-section from the parameters, the two lengths from the geometry.

    ``bounds`` is `[xmin, ymin, zmin, xmax, ymax, zmax]`, so the width the profile has to fill
    and the length it is cut to are both read off the envelope. The plane adapter could read
    only the first.
    """
    xmin, _ymin, zmin, xmax, _ymax, zmax = geometry.bounds
    profile = heatsink.Profile(
        base_width=float(xmax - xmin),
        base_thickness=params.base_thickness,
        fin_count=params.fin_count,
        fin_thickness=params.fin_thickness,
        fin_height=params.fin_height,
    )
    return profile, float(zmax - zmin)


def _section_cells(profile: heatsink.Profile, cell_size: float) -> int:
    """Metal cells in one station, without meshing.

    Cheap enough to run before a job is accepted, which is what
    :meth:`Solver.estimate_cells` requires: the grid is a tensor product of two known line
    sets, so counting it is building the lines and masking a few thousand booleans. And it is
    *exact* rather than a division — the line rule puts a line on every fin edge, so a naive
    `ceil(width / cell_size)` under-counts, and an under-estimate is the one direction a cell
    budget must not be wrong in.
    """
    x_edges, y_edges = heatsink.build_grid(profile, cell_size)
    return int(heatsink.solid_mask(profile, x_edges, y_edges).sum())


def _stations(depth: float, footprint_depth: float, cell_size: float) -> int:
    """Cells along the length, counted the same exact way and for the same reason."""
    return len(heatsink_solid.build_z_edges(depth, footprint_depth, cell_size)) - 1


def _conditions(params: "HeatSink3D.Params", depth: float) -> heatsink.Conditions:
    return heatsink.Conditions(
        power_w=params.power,
        depth=depth,
        ambient_c=params.t_ambient,
        emissivity=heatsink2d.FINISHES[params.finish],
        conductivity=params.conductivity,
        density=params.density,
        mode=params.cooling,
        face_velocity=params.face_velocity,
        footprint_width=params.footprint_width,
        base_mounted_flush=params.base_mounted_flush,
        radiation=params.radiation,
        h_override=params.h_override,
    )


def _as_mesh(lattice: heatsink_solid.Lattice) -> dict:
    """``mesh3d``: points, tetrahedra, one value per node.

    No mask, unlike the plane adapter's `grid2d`. A tetrahedral mesh carries only what exists,
    so the air between the fins is *absent* rather than present and flagged — which is the
    difference between the two kinds and the reason the fins read as fins in a slice.
    """
    return {
        "bounds": list(lattice.bounds),
        "points": [tuple(point) for point in np.round(lattice.points, 9).tolist()],
        "tets": [tuple(tet) for tet in lattice.tets.tolist()],
        "point_fields": {
            "T": np.round(lattice.temperature_c, 4).tolist(),
            "flux": np.round(lattice.flux, 2).tolist(),
        },
    }


def _warnings(
    solution: heatsink_solid.Solution, params: "HeatSink3D.Params", depth: float
) -> list[str]:
    """What the caller should know that did not fail the job."""
    notes: list[str] = []
    coefficient = solution.coefficient

    if coefficient is not None and not coefficient.valid and coefficient.note:
        notes.append(
            f"the {coefficient.correlation} correlation is out of range: {coefficient.note}. "
            "The coefficient is still reported, and it is an extrapolation."
        )
    if params.footprint_depth >= depth:
        notes.append(
            "the device covers the whole length, so there is no spreading along it to find: "
            "this is the plane model with a third dimension's worth of cells spent on it. "
            "Shorten footprint_depth, or run lab.heatsink2d, which solves the same problem "
            "faster and on a finer grid."
        )
    if not params.ends_open:
        notes.append(
            "the two cut ends are held adiabatic, which is an idealisation rather than a "
            "mounting: a sink in open air loses heat through them. It is the right setting "
            "for reproducing the plane model and the wrong one for a design answer."
        )
    if not params.radiation:
        notes.append(
            "radiation is switched off, which is a different physical model rather than a "
            "numerical setting. In still air this over-predicts the temperature rise."
        )
    if params.h_override is not None:
        notes.append(
            "the convection coefficient is pinned, so it no longer depends on the channel "
            "between the fins."
        )
    if not params.decompose and params.ends_open:
        notes.append(
            "the decomposition is off, so spreading_resistance and end_gain are absent and "
            "only their net, depth_correction, is reported. The two are of opposite sign and "
            "of similar size on a short extrusion, so the net alone can read as 'the third "
            "dimension does not matter here' when what is true is that two effects cancelled."
        )

    worst = max(
        (value for key, value in solution.residuals.items() if "summation" in key),
        default=0.0,
    )
    if worst > 1e-8:
        notes.append(
            f"view-factor rows sum to within {worst:.2e} of one rather than to machine "
            "precision, which means an enclosure is not closed or not convex"
        )
    return notes
