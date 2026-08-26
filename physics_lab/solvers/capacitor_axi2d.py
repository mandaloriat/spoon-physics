"""``lab.capacitor_axi2d`` — the capacitive sensor as a Fenix Spoon capability.

Thin on purpose, like every adapter here. The discretisation is in
:mod:`~physics_lab.solvers.capacitor`, the exercise in :mod:`~physics_lab.solvers.sensor`, and
what is left in this file is the protocol: a params model, a result envelope, the declarations
a caller reads before submitting, and the cost estimate the server's cell budget checks.

Why the lab writes this one, with two upstream adapters for the same geometry kind
---------------------------------------------------------------------------------

This is the first lab solver whose reason is **not** missing physics. Upstream ships
``mock.electrostatics_axi2d`` and ``dolfinx.electrostatics_axi2d``; both solve the right
equation with the ``r`` weight in the right places, and the FEniCSx one meshes the chamfer
rather than staircasing it. Either would compute this section's capacitance perfectly well —
and ADR-018's rule says that where upstream has the physics a metric needs, the lab uses it.

The rule holds. What this exercise's metrics need is not physics; it is **that there are
several solves and that they are related to each other**. A position sensor is not
characterised by a capacitance:

* the sensitivity ``dC/dz`` is the *slope* of a curve;
* the linear half-stroke is how far a straight line stays inside a tolerance *of that curve*;
* the tilt cross-sensitivity is a quadrature *over that curve* — §2's hybrid method, which the
  thesis reached for after a full 3-D attempt failed to resolve the perturbation at a 90 µm
  gap.

Not one of the three is a reduction of a field, so not one of them can be declared as a
``MetricSpec`` against any single solve, upstream's or ours. A capability that sweeps is #48's
study abstraction and does not exist yet; until it does, the sweep and the fit over it are the
adapter's own work, and the adapter that does that work is the one that has to own the solve.

**The upstream pair was then meant to be the check rather than the replacement**, on the
ADR-018 principle: one configuration is what a single-solve adapter answers well, so comparing
one gap of our sweep against ``mock.electrostatics_axi2d`` on the same section would be two
independent discretisations of one problem. That is why :func:`_read` accepts a grounded region
it does not need — a cross-check between two *payloads* is a comparison of two geometries.

It does not survive contact with this configuration, and the measurement is in
``tests/test_capacitor_solver.py``. The mock rasterises onto a uniform grid over the whole
window, and this window is 10 mm tall around a 90 µm gap: at 512 — the ceiling its schema
allows — the cell is 59 µm, so the gap the entire answer depends on is one and a half of them.
The capacitance comes back **0.0137, 0.0159, 0.0125, 0.0140, 0.0171 and 0.0178 nF** at
resolutions 128, 160, 224, 256, 320 and 512, against a measured 0.0319. Not merely low: not
monotone, because what changes with the resolution is whether a grid line happens to fall
inside the gap. There is no refinement path along which this sensor stays the same sensor —
ADR-018's finding exactly, on a different mock and a sharper case — and the 512 run costs 66
seconds to be 44% wrong.

None of which is a fault the mock claims otherwise about: it says it is a development stand-in
and that a staircased electrode edge is its accuracy limit. It is worth recording because the
``axisymmetric2d`` docstring names *this sensor* as the case the geometry kind was added for,
so the gap between what the kind was added for and what the shipped mock can do with it is
worth an upstream issue rather than a silent local workaround. ``dolfinx.electrostatics_axi2d``
meshes the outline and would presumably not have this problem; it is not installed in this
deployment, which is its own kind of answer. See ADR-026.

The one thing this discretisation does differently, and it is not a refinement
-----------------------------------------------------------------------------

The electrode is **excluded from the domain**, and each face between the free cells and the
metal is a Dirichlet face at the electrode's potential. Upstream's mock pins the grid *points*
that fall inside the metal, which puts the conductor's surface half a cell inside the
electrode. On most sections that is a discretisation error that refines away. On this one it is
not: the metal is 4 mm thick, carries no field, and is therefore divided coarsely, while the
gap the answer depends on is 90 µm. The lab's own first attempt did exactly this and returned a
capacitance four times too small — with a consistent linear system, both capacitance routes
agreeing to five significant figures, and a machine-precision residual. See §8, and
``tests/test_capacitor_method.py``, whose benchmark is what caught it.
"""

from typing import Literal

import numpy as np
from fenixspoon.geometry import Axisymmetric2D
from fenixspoon.solvers.base import (
    Assumption,
    CapabilityExample,
    ConvergenceSpec,
    MetricSpec,
    ProgressEvent,
    Solver,
    SolverContext,
    SolverResult,
)
from fenixspoon.solvers.registry import register
from pydantic import BaseModel, Field

from . import sensor as exercise
from .capacitor import Electrode, Numerics, Solution, build_grid, solve

VERSION = "1.0.0"

#: §7, on the wire. Three keep upstream's names and meanings — ``capacitance``, ``energy`` and
#: ``e_max`` — because a caller swapping ``mock.electrostatics_axi2d`` for this one is asking
#: the same physics a sharper question and should not have to learn a second vocabulary to do
#: it. The rest are what a *sensor* is characterised by, and none of them is a reduction of a
#: field: each is a property of the swept curve.
SENSOR_METRICS = [
    MetricSpec(
        name="capacitance",
        unit="F",
        description=(
            "Capacitance at the nominal gap, from the field energy: C = 2W/V², for the whole "
            "body of revolution rather than per unit depth. Upstream's name and meaning. Read "
            "off the solve at the nominal gap, not off the fitted curve — the sweep always "
            "puts a sample exactly there so that it need not be interpolated."
        ),
    ),
    MetricSpec(
        name="capacitance_charge",
        unit="F",
        description=(
            "The same capacitance by the other route: the charge integrated over the "
            "electrode's surface, divided by the excitation. An identity for a converged "
            "discrete solution, so the gap between the two measures the linear solve."
        ),
    ),
    MetricSpec(
        name="energy",
        unit="J",
        description=(
            "Electrostatic field energy over the revolved volume, W = ½∫ε|∇V|² dV. Upstream's "
            "name; the quantity the capacitance is read off, beside it so a caller can see "
            "what it was divided by."
        ),
    ),
    MetricSpec(
        name="dC_dz",
        unit="F/m",
        description=(
            "Sensitivity: the tangent of C(z) at the nominal gap, and the number a controller "
            "inverts a reading with. Negative — closing the gap raises the capacitance. Taken "
            "analytically from the fitted curve rather than from a difference of two solves, "
            "so it carries no differencing noise."
        ),
    ),
    MetricSpec(
        name="linear_halfstroke",
        unit="m",
        description=(
            "How far either side of nominal a straight-line calibration stays within the "
            "declared tolerance of the true curve. The smaller of the two directions: a stroke "
            "is only as linear as its worse half."
        ),
    ),
    MetricSpec(
        name="tilt_per_deg2",
        unit="F/deg2",
        description=(
            "Cross-sensitivity to a relative tilt of the two plates: the quadratic coefficient "
            "of C(γ) at the nominal gap. **In degrees**, which is the unit the published fit "
            "used — see `tilt_per_rad2` for the same number the other way, and the exercise "
            "for how the two were told apart."
        ),
    ),
    MetricSpec(
        name="tilt_per_rad2",
        unit="F/rad2",
        description=(
            "The tilt coefficient in the SI unit, for a caller that would rather not think "
            "about degrees. The same number as `tilt_per_deg2` divided by (π/180)², which is a "
            "factor of 3283."
        ),
    ),
    MetricSpec(
        name="tilt_error",
        unit="m",
        description=(
            "The phantom displacement a tilt reports: the capacitance a tilt adds, read back "
            "through the sensitivity as though it had been a motion. Microns, for a tenth of a "
            "degree — this is the number that decides whether a tilt matters."
        ),
    ),
    MetricSpec(
        name="fringe_excess",
        unit="1",
        description=(
            "How far the capacitance sits above the parallel-plate value ε₀A/d on the annular "
            "area. The measured sensor is 15.7% above it, and that excess is the entire reason "
            "this is solved rather than evaluated."
        ),
    ),
    MetricSpec(
        name="parallel_plate",
        unit="F",
        description=(
            "ε₀π(r_o²−r_i²)/d — what the sensor would be with no fringe field at all. Exact, "
            "and it needs no solve; reported so the excess above it is checkable rather than "
            "merely stated."
        ),
    ),
    MetricSpec(
        name="e_max",
        unit="V/m",
        description=(
            "Peak field magnitude in the section, upstream's metric of the same name. Read it "
            "at the chamfer with suspicion: a corner has an unbounded field in the continuum, "
            "so this rises with refinement instead of converging."
        ),
        field="E",
        reduction="max",
    ),
]

#: What the model assumes. The first five follow upstream's electrostatics set closely, because
#: they are assumptions of the *equation* and this solves the same one. The last two are this
#: exercise's own, and both come from the thesis naming them as the next-order effects it did
#: not analyse.
SENSOR_ASSUMPTIONS = [
    Assumption(
        name="electrostatic",
        statement=(
            "No time derivative: charges are at rest and the field is the gradient of a "
            "potential. The real sensor is read by a carrier at tens of kilohertz, which this "
            "model says nothing about — no loss tangent, no dielectric relaxation, no "
            "demodulation noise. Those set the sensor's resolution; this sets its calibration."
        ),
        excludes=["loss_tangent", "displacement_current", "noise_floor"],
    ),
    Assumption(
        name="no_space_charge",
        statement=(
            "The gap carries no free charge: div(ε grad V) = 0. An ionised gap or a charged "
            "insulating film would shift the potential distribution rather than scale it."
        ),
        excludes=["space_charge", "charge_injection"],
    ),
    Assumption(
        name="ideal_conductors",
        statement=(
            "Both plates are perfect equipotentials. The capacitance is geometric, and the "
            "gold coating's 1 µm thickness and its resistance are outside the model — they "
            "matter to the read-out electronics and not to this number."
        ),
        excludes=["electrode_resistance", "contact_potential", "surface_roughness"],
    ),
    Assumption(
        name="rigid_plates",
        statement=(
            "Both plates stay flat. The shell deflects locally under the actuator that shares "
            "this unit's footprint, and the thesis names that curvature as the next-order "
            "effect it did not analyse. A curved plate is not a gap, and no setting here "
            "approximates one."
        ),
        excludes=["plate_curvature", "electrostatic_pull_in"],
    ),
    Assumption(
        name="isolated_unit",
        statement=(
            "One sensor, alone. The real reference body carries hundreds of these units, and "
            "the field of a neighbouring electrode is not in this section — the axisymmetric "
            "reduction cannot hold two of them. Good while the gap is far smaller than the "
            "spacing, which it is here by two orders of magnitude."
        ),
        excludes=["crosstalk", "neighbour_coupling"],
    ),
    Assumption(
        name="tilt_is_inferred",
        statement=(
            "A tilt is not axisymmetric and is not solved. It is inferred from the swept "
            "curve by treating each azimuth as locally axisymmetric with its own gap and "
            "integrating around the annulus — §2's hybrid method, and what the thesis did "
            "after a full 3-D attempt failed to resolve the perturbation at this gap. The "
            "inference is only as good as the curve is wide, which is why the sweep spans the "
            "tilt's reach at the rim and not merely the stroke."
        ),
        excludes=["three_dimensional_tilt", "azimuthal_field_variation"],
    ),
    Assumption(
        name="truncated_domain",
        statement=(
            "The far field is cut off at a stated distance with the potential held at zero "
            "there, rather than decaying to infinity. This is a numerical setting whose only "
            "correct effect is on the error — `truncation` moves it, and the convergence "
            "check measures what it was worth."
        ),
    ),
]

#: The linear solve, and what its residual is the size of. `on_failure` is `return`: a
#: conjugate-gradient solve stopped at its cap is still the iterate it reached, the result says
#: `converged: false`, and a caller can see the residual and decide. Refusing outright would
#: turn a coarse preview into an error.
SENSOR_CONVERGENCE = ConvergenceSpec(
    method="conjugate-gradient",
    measures="residual of the discrete Laplace system, relative to the load vector",
    unit=None,
    default_tolerance=1e-12,
    on_failure="return",
)


@register
class CapacitorAxi2D(Solver):
    """The annular capacitive sensor: a calibration curve, not a capacitance."""

    name = "lab.capacitor_axi2d"
    title = "Capacitive gap sensor — axisymmetric electrostatics, swept and fitted"
    summary = (
        "Electrostatics on the meridian section of an annular gap sensor, solved at a series "
        "of gaps and reduced to the calibration a controller would be handed: sensitivity, "
        "the stroke over which a linear reading holds, and the phantom displacement a relative "
        "tilt of the plates reports. The electrode is excluded from the domain and its surface "
        "carried on the faces, so a 4 mm-thick conductor does not move a 90 µm gap. Benchmarked "
        "against a published measurement of the same sensor rather than against itself."
    )
    geometry_types = ["axisymmetric2d"]
    #: Its own tag rather than `electrostatics`, and for the same reason `lab.heatsink2d`
    #: does not declare `heat`: a page filtering on the upstream tag would be offered a
    #: capability that answers one configuration, which is not what any metric here is.
    physics = "capacitive_sensor"
    availability = "finite-volume"
    requires = ["numpy"]
    version = VERSION
    #: A fixed sequence of matrix-free CG solves and a linear least squares. No seeding, no
    #: thread-dependent reduction: an identical resubmission is worth answering from the cache.
    deterministic = True
    metrics = SENSOR_METRICS
    assumptions = SENSOR_ASSUMPTIONS
    convergence = SENSOR_CONVERGENCE
    examples = [
        CapabilityExample(
            title="the P45 sensor at its nominal gap",
            description=(
                "What the page submits: nine gaps spanning the actuator stroke, at a "
                "resolution where the benchmark against the 2015 measurement means something."
            ),
            params={"samples": 9, "stroke": 50e-6, "tilt": 0.1},
        ),
        CapabilityExample(
            title="fast look",
            description=(
                "Five gaps and coarse cells. Every metric is still reported and every one of "
                "them still stands: the capacitance moves by two parts in a thousand across "
                "this solver's whole resolution range, because the grid is fitted to the "
                "geometry rather than sized against it. What five gaps cost is the fit — "
                "three coefficients through five points follows them rather than their trend."
            ),
            params={"samples": 5, "cell_size": 5e-5, "truncation": 2.0},
        ),
        CapabilityExample(
            title="with the mesh study",
            description=(
                "§8's convergence row, with a number in it: a second solve at half the cell "
                "size and twice the truncation. The sweep is shortened to five gaps to make "
                "room for it — that one refined solve costs as much as four of the sweep's, "
                "and the public server's budget is spent either way."
            ),
            params={"samples": 5, "convergence_check": True},
        ),
    ]

    class Params(BaseModel):
        """Grouped by what each parameter *is* — ADR-013's split, and here it is unusually
        clean: the geometry carries every dimension, so the physical group holds only what the
        sensor is *asked to do*, and the rest is numerics.
        """

        # --- physical: the duty, not the shape. The shape is in the section.
        voltage: float = Field(
            default=1.0,
            gt=0.0,
            le=1000.0,
            description=(
                "Excitation, in volts. The capacitance does not depend on it and the stored "
                "energy goes as its square, so this scales one reported number and no other."
            ),
        )
        stroke: float = Field(
            default=50e-6,
            gt=0.0,
            le=1e-3,
            description=(
                "Half the working excursion, in metres — the ELT actuator's ±50 µm. The "
                "sweep spans it, and the linear half-stroke is searched inside it."
            ),
        )
        tilt: float = Field(
            default=0.1,
            gt=0.0,
            le=2.0,
            description=(
                "Relative tilt of the two plates the cross-sensitivity is quoted at, **in "
                "degrees**. A tenth of a degree is 1.7 mrad, which is the range the sensor "
                "actually sees. Degrees because the measurement this is benchmarked against "
                "was fitted in them; `tilt_per_rad2` reports the same coefficient in radians."
            ),
        )
        linear_tolerance: float = Field(
            default=0.01,
            gt=0.0,
            le=0.5,
            description=(
                "How far from a straight line the reading may stray before the stroke stops "
                "counting as linear. §7's definition uses 1%, and the metric's value is only "
                "comparable between two designs at the same tolerance."
            ),
        )
        # --- numerical: how well it is approximated, and nothing else
        samples: int = Field(
            default=9,
            ge=3,
            le=25,
            description=(
                "Gaps solved across the sweep. The fit has three coefficients, so three is the "
                "floor at which it is a fit rather than an interpolation; nine is where the "
                "residual stops moving. Each sample is a full solve — this is the parameter "
                "the run time is proportional to."
            ),
        )
        cell_size: float = Field(
            default=3e-5,
            gt=0.0,
            le=1e-4,
            description=(
                "Target cell size in the band that carries the field, in metres. A line lands "
                "on every edge the geometry has regardless, so this only ever divides "
                "intervals finer. Out past the electrode the cells grow, which is what makes "
                "a truncation many annulus-widths across affordable.\n\n"
                "The default is coarser than it looks because it does not need to be finer: "
                "with a grid line on every edge, the capacitance moves 0.2% across the whole "
                "range this parameter allows. What actually caps the sweep is the server's "
                "cell budget, and it is spent on gaps rather than on cells."
            ),
        )
        truncation: float = Field(
            default=2.5,
            ge=0.5,
            le=10.0,
            description=(
                "How far the modelled window reaches past the electrode, in multiples of the "
                "annulus width, with V = 0 at the far edge. A numerical setting whose only "
                "correct effect is on the error — §8 measures what it is worth."
            ),
        )
        thickness_cells: int = Field(
            default=4,
            ge=1,
            le=40,
            description=(
                "Cells across the electrode's thickness. Coarse on purpose: the metal carries "
                "no field, it is outside the solved domain, and its cells exist only to place "
                "the chamfer's staircase. Refining it buys the answer nothing."
            ),
        )
        growth: float = Field(
            default=1.15,
            ge=1.0,
            le=1.5,
            description=(
                "Cell-to-cell growth ratio out in the truncation region. 1.0 gives a uniform "
                "grid, and a window worth having with it."
            ),
        )
        tolerance: float = Field(
            default=1e-12,
            gt=0.0,
            le=1e-4,
            description="Relative residual the conjugate-gradient solve stops at.",
        )
        max_iterations: int = Field(
            default=20000,
            ge=50,
            le=200000,
            description="Iteration ceiling per solve.",
        )
        convergence_check: bool = Field(
            default=False,
            description=(
                "Also solve the nominal gap at half the cell size and twice the truncation, "
                "and report how far the capacitance moved. §8's fourth row, and about four "
                "times the work of the sweep it checks — off by default for that reason."
            ),
        )
        resolution: int = Field(
            default=192,
            ge=32,
            le=512,
            description=(
                "Sampling grid for the field picture, along the longer edge of the window. "
                "Affects the picture and no reported number."
            ),
        )
        # --- output
        output: Literal["grid2d", "mesh2d"] = Field(
            default="grid2d",
            description=(
                "A uniform raster of the nominal solve, or the graded cells the answer was "
                "actually computed on. The mesh is the discretisation; the grid is a "
                "resampling of it, and it is the one that shows the field rather than the "
                "grading."
            ),
        )

    @classmethod
    def estimate_cells(cls, geometry: Axisymmetric2D, params: "CapacitorAxi2D.Params") -> int:
        """The real count, not an estimate: these grids are cheap to build and dear to solve.

        Every solve in the sweep is counted, because the job pays for every one of them — the
        cost here is a multiple of one section's cells rather than one section's cells, and an
        estimate that quoted the latter would let a twenty-five sample run through a budget
        sized for one.
        """
        electrode, gap, _floor = _read(geometry)
        numerics = _numerics(params)
        conditions = _conditions(params, gap)
        total = 0
        for swept in exercise.sweep_gaps(electrode, conditions, params.samples):
            r_edges, z_edges = build_grid(electrode, float(swept), numerics)
            total += (len(r_edges) - 1) * (len(z_edges) - 1)
        if params.convergence_check:
            fine = Numerics(
                cell_size=0.5 * params.cell_size,
                truncation=2.0 * params.truncation,
                thickness_cells=params.thickness_cells,
                growth=params.growth,
            )
            r_edges, z_edges = build_grid(electrode, gap, fine)
            total += (len(r_edges) - 1) * (len(z_edges) - 1)
        if params.output == "grid2d":
            nz, nr = _raster_shape(geometry.bounds, params.resolution)
            total += nz * nr
        return total

    def solve(
        self, geometry: Axisymmetric2D, params: "CapacitorAxi2D.Params", ctx: SolverContext
    ) -> SolverResult:
        electrode, gap, floor = _read(geometry)
        numerics = _numerics(params)
        conditions = _conditions(params, gap)
        total = params.samples + (2 if params.convergence_check else 1)

        def tick(index: int, count: int, message: str) -> None:
            ctx.check_cancelled()
            ctx.progress(ProgressEvent(iteration=index, total=total, message=message))

        calibration = exercise.calibrate(
            electrode, conditions, numerics, samples=params.samples, progress=tick
        )
        nominal = calibration.nominal
        assert nominal is not None  # `calibrate` always solves at least three gaps

        refined: Solution | None = None
        if params.convergence_check:
            ctx.progress(
                ProgressEvent(
                    iteration=params.samples + 1,
                    total=total,
                    message="refining the nominal gap, for the mesh study",
                )
            )
            refined = solve(
                electrode,
                gap,
                params.voltage,
                Numerics(
                    cell_size=0.5 * params.cell_size,
                    truncation=2.0 * params.truncation,
                    thickness_cells=params.thickness_cells,
                    growth=params.growth,
                    tolerance=params.tolerance,
                    max_iterations=params.max_iterations,
                ),
            )

        ctx.progress(ProgressEvent(iteration=total, total=total, message="sampling the field"))
        data, cells = _emit(nominal, floor, params)

        metrics = {
            "capacitance": calibration.metrics["c0"],
            "capacitance_charge": calibration.metrics["c0_charge"],
            "energy": nominal.energy,
            "dC_dz": calibration.metrics["dc_dz"],
            "linear_halfstroke": calibration.metrics["linear_halfstroke"],
            "tilt_per_deg2": calibration.metrics["tilt_per_deg2"],
            "tilt_per_rad2": calibration.metrics["tilt_per_rad2"],
            "tilt_error": calibration.metrics["tilt_error"],
            "fringe_excess": calibration.metrics["fringe_excess"],
            "parallel_plate": calibration.metrics["parallel_plate"],
        }

        return SolverResult(
            kind=params.output,
            data=data,
            # Cost, never answer — the separation upstream's MetricSpec draws, and the reason
            # the sweep's length is here rather than among the metrics.
            stats={
                "cells": float(cells),
                "dofs": float(nominal.held.size - int(nominal.held.sum())),
                "solves": float(calibration.solves),
                "cg_iterations": float(nominal.iterations),
            },
            metrics={k: float(v) for k, v in metrics.items() if np.isfinite(v)},
            series=_series(calibration, electrode, conditions),
            converged=nominal.iterations < params.max_iterations,
            # The linear solve's own residual, at the worst gap of the sweep. §8's other three
            # rows are curves rather than scalars and travel in `series`, where a caller can
            # see them against the configurations that produced them.
            residual=calibration.residuals["cg_residual"],
            warnings=_warnings(calibration, conditions, params, refined),
        )


# ----------------------------------------------------------------------------- the machinery


def _read(geometry: Axisymmetric2D) -> tuple[Electrode, float, float]:
    """The electrode, its gap, and where the facing plate is. Returns ``(electrode, gap, floor)``.

    Exactly one region may be *live*: this capability models one electrode over the shell, and
    a section with two driven conductors is a different problem — a guard ring, or two sensors
    — that this solver would answer by silently ignoring one of them.

    **A grounded region is read as the shell, and that is what makes this comparable with
    upstream.** Both upstream electrostatics adapters need the facing plate drawn: they pin
    what the section says is metal and nothing else, so a payload that leaves the shell out
    has one electrode and no capacitance. This solver's own convention is that the floor of
    the window *is* the coating, which needs no region at all — and if the two conventions
    disagreed about what a payload meant, no configuration could be sent to both, and §8's
    cross-check against ``mock.electrostatics_axi2d`` would be comparing two geometries rather
    than two discretisations. So a grounded region is accepted and its **top face** becomes
    the floor: one section, read the same way twice.

    A grounded region that does not reach the bottom of the window is refused. It would be a
    conductor floating in the gap, and this solver has nowhere to put one — it would be
    ignored, and the capacitance would come back as though it were not there.
    """
    live = [r for r in geometry.regions if float(r.material.get("voltage", 0.0)) != 0.0]
    grounded = [r for r in geometry.regions if "voltage" in r.material and r not in live]
    if len(live) != 1:
        raise ValueError(
            f"this capability models one electrode facing the shell, and the section holds "
            f"{len(live)} regions at a voltage other than zero. One region carries the "
            "electrode; the facing plate is either drawn as a region at zero volts or left "
            "out, in which case the floor of the window is the coating. A driven guard ring "
            "is a different problem, and this solver would answer it by ignoring a conductor "
            "rather than by failing"
        )

    floor = float(geometry.bounds[1])
    for region in grounded:
        points = np.asarray(region.shape.points, dtype=float)
        clearance = float(points[:, 1].min()) - floor
        if clearance > exercise.SAME_EDGE:
            raise ValueError(
                f"the grounded region {region.name!r} floats {clearance * 1e6:.1f} µm "
                "above the bottom of the window. This solver reads a grounded region as the "
                "shell's coating and grounds everything below its top face; one that does not "
                "reach the floor is a conductor in the gap, and it would be ignored rather "
                "than solved"
            )
        floor = max(floor, float(points[:, 1].max()))

    electrode, gap = exercise.read_electrode(
        np.asarray(live[0].shape.points, dtype=float), floor
    )
    return electrode, gap, floor


def _numerics(params: "CapacitorAxi2D.Params") -> Numerics:
    return Numerics(
        cell_size=params.cell_size,
        truncation=params.truncation,
        thickness_cells=params.thickness_cells,
        growth=params.growth,
        tolerance=params.tolerance,
        max_iterations=params.max_iterations,
    )


def _conditions(params: "CapacitorAxi2D.Params", gap: float) -> exercise.Conditions:
    """The duty, with the stroke clipped to something the geometry can hold.

    A ±50 µm stroke on a 40 µm gap is a collision, and :class:`sensor.Conditions` refuses one —
    correctly, since it is the caller declaring an excursion the sensor does not have. But the
    stroke arrives as a *parameter default* while the gap arrives in the *geometry*, so the two
    can disagree without anyone having asked for it: dragging the electrode down past 50 µm on
    the page would fail the job on a number the visitor never typed. Clipped here, and the
    clipping is a warning on the result.
    """
    return exercise.Conditions(
        gap=gap,
        voltage=params.voltage,
        stroke=min(params.stroke, 0.9 * gap),
        tilt_deg=params.tilt,
        linear_tolerance=params.linear_tolerance,
    )


def _raster_shape(bounds, resolution: int) -> tuple[int, int]:
    """Raster shape (nz, nr) for a resolution along the longer edge.

    The same rule as upstream's ``mock.laplace2d``, so a visitor comparing this solver's
    picture with the mock's is comparing two solves and not two rasters.
    """
    rmin, zmin, rmax, zmax = bounds
    lr, lz = rmax - rmin, zmax - zmin
    if lr >= lz:
        return max(8, round(resolution * lz / lr)), resolution
    return resolution, max(8, round(resolution * lr / lz))


def _emit(solution: Solution, floor: float, params: "CapacitorAxi2D.Params"):
    """The envelope's ``data``, in whichever kind was asked for.

    Field names follow upstream's electrostatics adapters — ``V`` and ``E`` — so a page can
    show either solver without a translation table.

    **The window published is the solver's, not the payload's.** They differ: the section a
    caller sends is the part they care about, and the solve reaches further out because a
    truncation has to. Publishing the caller's bounds over the solver's array would stretch
    the picture onto a window it was not computed on, which is a wrong drawing rather than a
    cropped one.

    ``floor`` is where the shell's surface sits in the *payload's* frame. The solve works in
    its own, with the ground plane at zero, so it is added back on the way out — otherwise the
    picture is right and sitting in the wrong place, which is the harder mistake to see.
    """
    if params.output == "mesh2d":
        return _as_mesh(solution, floor), int(solution.potential.size)

    r_edges, z_edges = solution.r_edges, solution.z_edges + floor
    nz, nr = _raster_shape(
        (r_edges[0], z_edges[0], r_edges[-1], z_edges[-1]), params.resolution
    )
    r = np.linspace(r_edges[0], r_edges[-1], nr)
    z = np.linspace(z_edges[0], z_edges[-1], nz)

    def take(values: np.ndarray) -> np.ndarray:
        return _resample(values, solution.r_centres, solution.z_centres + floor, r, z)

    # The metal is a hole in the domain, and it travels as one. `mask` is the protocol's way
    # of saying "no value here"; filling it with the electrode's potential instead would draw
    # a solid block of colour and invite it to be read as field.
    inside = _resample(
        solution.held.astype(float), solution.r_centres, solution.z_centres + floor, r, z
    )
    return {
        "bounds": [float(r_edges[0]), float(z_edges[0]), float(r_edges[-1]), float(z_edges[-1])],
        "shape": [nz, nr],
        "fields": {
            "V": take(solution.potential).ravel().tolist(),
            "E": take(solution.field).ravel().tolist(),
        },
        "mask": (inside > 0.5).astype(np.uint8).ravel().tolist(),
    }, nz * nr


def _resample(
    values: np.ndarray, r: np.ndarray, z: np.ndarray, r_out: np.ndarray, z_out: np.ndarray
) -> np.ndarray:
    """Bilinear interpolation from the graded tensor grid onto a uniform one.

    Two one-dimensional interpolations, because the source grid is a tensor product: along the
    radius first, then along z. ``np.interp`` clamps outside the range, which is what is wanted
    at the four edges — the outermost cell centre is half a cell inside the window.
    """
    along_r = np.empty((values.shape[0], r_out.size))
    for row in range(values.shape[0]):
        along_r[row] = np.interp(r_out, r, values[row])
    out = np.empty((z_out.size, r_out.size))
    for column in range(r_out.size):
        out[:, column] = np.interp(z_out, z, along_r[:, column])
    return out


def _as_mesh(solution: Solution, floor: float) -> dict:
    """The cell centres, triangulated: the discretisation the answer was computed on.

    Not the cells as quadrilaterals — ``mesh2d`` carries triangles with one value per node, and
    these values live at cell centres, so the centres are the nodes. The picture is then the
    honest one: fine across the gap, coarse through the metal and out in the truncation.
    """
    r, z = solution.r_centres, solution.z_centres + floor
    rr, zz = np.meshgrid(r, z)
    ident = np.arange(rr.size).reshape(rr.shape)
    a, b = ident[:-1, :-1], ident[:-1, 1:]
    c, d = ident[1:, :-1], ident[1:, 1:]
    triangles = np.concatenate(
        [
            np.column_stack([a.ravel(), b.ravel(), d.ravel()]),
            np.column_stack([a.ravel(), d.ravel(), c.ravel()]),
        ]
    )
    return {
        "bounds": [float(r[0]), float(z[0]), float(r[-1]), float(z[-1])],
        "points": np.column_stack([rr.ravel(), zz.ravel()]).tolist(),
        "triangles": triangles.tolist(),
        "point_fields": {
            "V": solution.potential.ravel().tolist(),
            "E": solution.field.ravel().tolist(),
        },
    }


def _series(
    calibration: exercise.Calibration, electrode: Electrode, conditions: exercise.Conditions
) -> list[dict]:
    """The two curves the metrics are read off, so a caller can see them and not just the
    numbers reduced from them.

    The first is the calibration itself, with the published measurement beside it: §8's
    benchmark row is a *curve* against a *curve*, and reducing it to one worst-case percentage
    would hide where along the stroke the two part company. The second is the tilt inference —
    the thing §2 says is inferred rather than solved, drawn so that the claim is inspectable.
    """
    gaps = calibration.gaps
    tilts = np.linspace(0.0, conditions.tilt_deg * 2.0, 21)
    return [
        {
            "name": "calibration",
            "title": "Capacitance against gap, solved and as published",
            "x": {"name": "gap", "unit": "m", "values": [float(g) for g in gaps]},
            "traces": [
                {
                    "name": "solved",
                    "unit": "F",
                    "values": [float(c) for c in calibration.capacitance],
                },
                {
                    "name": "fitted",
                    "unit": "F",
                    "values": [float(calibration.curve(float(g))) for g in gaps],
                },
                {
                    "name": "published",
                    "unit": "F",
                    "values": [float(exercise._published(float(g))) for g in gaps],
                },
                {
                    "name": "parallel_plate",
                    "unit": "F",
                    "values": [float(electrode.parallel_plate(float(g))) for g in gaps],
                },
            ],
        },
        {
            "name": "tilt",
            "title": "Capacitance against relative tilt, inferred from the calibration",
            "x": {"name": "tilt", "unit": "deg", "values": [float(t) for t in tilts]},
            "traces": [
                {
                    "name": "inferred",
                    "unit": "F",
                    "values": [
                        float(
                            exercise.tilted_capacitance(
                                calibration, electrode, conditions.gap, float(t)
                            )
                        )
                        for t in tilts
                    ],
                },
                {
                    "name": "published",
                    "unit": "F",
                    "values": [
                        float(
                            exercise.PUBLISHED_TILT_PER_DEG2 * t * t
                            + exercise._published(conditions.gap)
                        )
                        for t in tilts
                    ],
                },
            ],
        },
    ]


def _warnings(
    calibration: exercise.Calibration,
    conditions: exercise.Conditions,
    params: "CapacitorAxi2D.Params",
    refined: Solution | None,
) -> list[str]:
    """What the caller should know that did not fail the job.

    §8's rows, as sentences, and each one only when it has something to say. A verification
    that passed is not news; a verification that did not is the whole reason it is run.
    """
    notes: list[str] = []
    residuals = calibration.residuals

    if conditions.stroke < params.stroke:
        notes.append(
            f"the ±{params.stroke * 1e6:.0f} µm stroke was clipped to "
            f"±{conditions.stroke * 1e6:.0f} µm, which is as far as a "
            f"{conditions.gap * 1e6:.0f} µm gap can travel before the plates touch. The linear "
            "half-stroke is searched inside the clipped range and can be no larger than it."
        )
    if residuals["energy_charge_consistency"] > 0.01:
        notes.append(
            f"the two routes to the capacitance differ by "
            f"{residuals['energy_charge_consistency'] * 100:.2f}%, over §8's 1% gate. They are "
            "the same number for a converged discrete solution, so this is the linear solve "
            "rather than the mesh: raise `max_iterations` or loosen nothing."
        )
    if residuals["fit_residual"] > 0.02:
        notes.append(
            f"the fitted curve misses the solved points by up to "
            f"{residuals['fit_residual'] * 100:.1f}%. The fit is the reciprocal quadratic the "
            "measurement was reduced in, so a large residual means this geometry is not in "
            "that family — every derivative reported here is taken from the fit, and would be "
            "describing the fit rather than the sensor."
        )
    if residuals["benchmark"] > 0.10:
        notes.append(
            f"the sweep sits up to {residuals['benchmark'] * 100:.1f}% from the published "
            "measurement. That is expected of a geometry that is not the measured one — a "
            "different chamfer or a different annulus is a different sensor — and it means "
            "the benchmark is no longer checking this run."
        )
    if params.samples < 5:
        notes.append(
            f"{params.samples} gaps for a three-coefficient fit. The curve passes through the "
            "points rather than through their trend, so the sensitivity and the stroke carry "
            "whatever each solve's discretisation error happened to be."
        )
    if refined is not None:
        moved = abs(refined.capacitance_energy / calibration.metrics["c0"] - 1.0)
        notes.append(
            f"§8's mesh and truncation study: halving the cell size and doubling the "
            f"truncation moves the nominal capacitance by {moved * 100:.2f}%."
            + (
                " That is above the 1% the page declares, so the resolution is the largest "
                "error in every number here."
                if moved > 0.01
                else ""
            )
        )
    return notes
