"""Axisymmetric electrostatics on a meridian (r, z) section — the physics only.

``docs/exercises/capacitive-sensor.md`` §2. Arrays in, arrays out, no Fenix Spoon import: the
split every lab adapter uses, so the capacitance can be checked against a published measurement
without a job, a server or an envelope.

**What is solved.** Laplace's equation for the potential in a linear dielectric with no free
charge,

    div( eps grad V ) = 0 ,

by finite volumes on a tensor-product grid over the meridian section. The one thing that makes
it axisymmetric is a factor of ``r``, and it is in both places it belongs: the radial face at
``r`` has area ``2 pi r dz``, and the axial face of the annulus between ``r_i`` and ``r_{i+1}``
has area ``pi (r_{i+1}^2 - r_i^2)`` — which is ``2 pi r_bar dr`` with ``r_bar`` the arithmetic
mean of the two radii, *exactly* rather than to first order. Drop the factor and this is a plane
slice of something else.

Because the volume element is the revolved one, the capacitance comes back in **farads** for the
whole body of revolution, not farads per metre.

**Two routes to the capacitance, and what their difference actually measures.** ``C = 2W/V^2``
from the stored energy, and ``C = Q/V`` from the charge on the electrode. For the *converged*
discrete solution these are the same number — discrete Green's identity, with one electrode at
``V`` and everything else at zero — so their gap is a measure of how well the linear system was
solved, not of how well the geometry was resolved. That is worth stating plainly because it is
easy to sell as more than it is: it is a convergence check, it is cheap, and the discretisation
error it does *not* see is what the mesh study in the exercise is for.

**Where the accuracy limit is.** The chamfer is a diagonal edge and the grid is a tensor
product, so the chamfer is staircased — the same limit upstream's ``mock.electrostatics_axi2d``
states about its own electrode edge. Since the chamfer is precisely the feature that lifts this
capacitance 15.7% above the parallel-plate value, the staircase is not a detail here, and the
exercise's convergence row is what measures it.
"""

from dataclasses import dataclass

import numpy as np

#: Vacuum permittivity, F/m.
EPS0 = 8.8541878128e-12


@dataclass(frozen=True)
class Electrode:
    """The annular electrode of one sensor unit, in metres.

    The *svaso* — the chamfer — is a bevel taken off the two lower corners of the annulus, so
    the face nearest the shell is narrower than the body behind it and the gap opens gradually
    at each rim instead of ending at a right angle. It is the reason this capacitance is not a
    parallel plate's, and the reason the exercise exists at all.
    """

    inner_radius: float = 0.011
    outer_radius: float = 0.0145
    #: How thick the annulus is. It is an equipotential and carries no field, so this changes
    #: no answer — it exists because a chamfer cannot be deeper than the part it is cut into,
    #: and §5 lets the chamfer reach 3 mm.
    thickness: float = 0.004
    chamfer_width: float = 0.0015
    chamfer_height: float = 0.0015

    def __post_init__(self) -> None:
        if self.outer_radius <= self.inner_radius:
            raise ValueError(
                f"outer_radius ({self.outer_radius}) must exceed inner_radius "
                f"({self.inner_radius}); the thesis table lists these transposed, and this is "
                "the check that catches a payload copied from it"
            )
        if self.chamfer_width * 2.0 >= self.width:
            raise ValueError(
                f"two chamfers of {self.chamfer_width * 1e3:.2f} mm do not fit across a "
                f"{self.width * 1e3:.2f} mm annulus: they would meet, and what is left is not "
                "a countersunk ring but a wedge"
            )
        if self.chamfer_height >= self.thickness:
            raise ValueError(
                f"a chamfer {self.chamfer_height * 1e3:.2f} mm high does not fit in an "
                f"electrode {self.thickness * 1e3:.2f} mm thick"
            )

    @property
    def width(self) -> float:
        """Radial width of the annulus, m."""
        return self.outer_radius - self.inner_radius

    @property
    def mean_radius(self) -> float:
        """The lever arm a tilt acts through — see :func:`tilted_capacitance`."""
        return 0.5 * (self.inner_radius + self.outer_radius)

    @property
    def facing_area(self) -> float:
        """Area of the flat part of the face, m^2 — what a parallel plate would count."""
        return np.pi * (self.outer_radius**2 - self.inner_radius**2)

    def parallel_plate(self, gap: float) -> float:
        """``eps0 A / d`` on the full annulus: the number the answer is measured against.

        Deliberately the *un*-chamfered area. The excess over this is the whole quantity the
        exercise reports as `fringe_excess`, and computing it against the chamfered area would
        quietly absorb half of what it is meant to expose.
        """
        return EPS0 * self.facing_area / gap


@dataclass(frozen=True)
class Numerics:
    """Everything whose only correct effect is on the error."""

    #: Target cell edge in the gap, m. The gap is 90 µm and the chamfer 1.5 mm, so this is the
    #: knob that has to resolve two lengths a factor of seventeen apart.
    cell_size: float = 1.5e-5
    #: How far past the electrode the window reaches before the potential is pinned to zero,
    #: as a multiple of the annulus width. A physical answer must not depend on it, and §8's
    #: convergence row is where that is demonstrated rather than asserted.
    truncation: float = 3.0
    #: Cells across the electrode's own thickness. It carries no field — it is an equipotential
    #: — so this is small on purpose.
    thickness_cells: int = 4
    #: Cell-to-cell growth out in the truncation region. 1.0 gives a uniform grid, and a window
    #: worth having with it: see :func:`_graded`.
    growth: float = 1.15
    tolerance: float = 1e-12
    max_iterations: int = 20000


@dataclass
class Solution:
    """A solved configuration, and the two readings of its capacitance."""

    potential: np.ndarray  #: (nz, nr) volts at cell centres
    field: np.ndarray  #: (nz, nr) |E| in V/m at cell centres
    held: np.ndarray  #: (nz, nr) bool, True where the potential was pinned
    r_edges: np.ndarray
    z_edges: np.ndarray
    capacitance_energy: float  #: F, from 2W/V^2
    capacitance_charge: float  #: F, from Q/V
    energy: float  #: J
    iterations: int = 0
    residual: float = 0.0

    @property
    def r_centres(self) -> np.ndarray:
        return 0.5 * (self.r_edges[:-1] + self.r_edges[1:])

    @property
    def z_centres(self) -> np.ndarray:
        return 0.5 * (self.z_edges[:-1] + self.z_edges[1:])

    @property
    def consistency(self) -> float:
        """Relative gap between the two routes — a convergence measure, not a mesh one."""
        scale = max(abs(self.capacitance_energy), 1e-30)
        return abs(self.capacitance_energy - self.capacitance_charge) / scale


# ────────────────────────────────────────────────────────────────────────── the grid


def _graded(start: float, stop: float, first: float, growth: float) -> np.ndarray:
    """Lines from ``start`` to ``stop``, the first cell ``first`` long and each one longer.

    The far field is where a truncation distance has to be large and a cell does not have to be
    small, and a uniform grid cannot have both: at the gap's cell size, three annulus widths of
    air past the electrode is more cells than the whole rest of the section. This is the same
    device — and the same argument — as the magnetics solver's `far_field_growth`.
    """
    lines = [start]
    step = first
    while lines[-1] + step < stop:
        lines.append(lines[-1] + step)
        step *= growth
    lines.append(stop)
    return np.array(lines, dtype=float)


def build_grid(
    electrode: Electrode, gap: float, numerics: Numerics
) -> tuple[np.ndarray, np.ndarray]:
    """Grid lines, with one on every edge the geometry has.

    The same rule the heat sink and the magnetics solver build their grids by, and here it
    matters more than on either: this section holds a 90 µm gap and a 1.5 mm chamfer at once,
    and a line that misses the electrode face moves the gap.

    The chamfer's *diagonal* cannot be fitted by a tensor product and is staircased; what the
    anchors buy is that its two ends — where it meets the face and where it meets full
    thickness — are exact.

    Fine where the answer is and graded where it is not. The band that carries the field is the
    gap and the two rims; everything outward of the chamfers is truncation, and it is spent at
    a growing cell size so that a window three annulus widths across costs tens of cells rather
    than thousands.
    """
    from physics_lab.solvers.heatsink import grid_lines

    reach = numerics.truncation * electrode.width
    inner = electrode.inner_radius - electrode.chamfer_width
    outer = electrode.outer_radius + electrode.chamfer_width

    r_edges = np.unique(
        np.concatenate(
            [
                # Grown from the electrode inwards and then read back, so the small cells sit
                # against the rim rather than out at the truncation edge where nothing happens.
                # Clamped at the axis: a negative radius is not a domain a body of revolution
                # has, and `axisymmetric2d` refuses one — correctly, since a payload with one
                # was authored as a plane section and mislabelled.
                np.maximum(
                    inner - _graded(0.0, min(reach, inner), numerics.cell_size, numerics.growth),
                    0.0,
                ),
                grid_lines(
                    [
                        inner,
                        electrode.inner_radius,
                        electrode.inner_radius + electrode.chamfer_width,
                        electrode.outer_radius - electrode.chamfer_width,
                        electrode.outer_radius,
                        outer,
                    ],
                    numerics.cell_size,
                ),
                _graded(outer, outer + reach, numerics.cell_size, numerics.growth),
            ]
        )
    )

    top = gap + electrode.thickness
    coarse = max(electrode.thickness / max(numerics.thickness_cells, 1), numerics.cell_size)
    z_edges = np.unique(
        np.concatenate(
            [
                grid_lines([0.0, gap, gap + electrode.chamfer_height], numerics.cell_size),
                grid_lines([gap + electrode.chamfer_height, top], coarse),
                _graded(top, top + reach, coarse, numerics.growth),
            ]
        )
    )
    return r_edges, z_edges


def electrode_mask(
    electrode: Electrode, gap: float, r_edges: np.ndarray, z_edges: np.ndarray
) -> np.ndarray:
    """True where a cell centre is inside the metal of the annulus.

    **The bevel is on the corners away from the gap, and that is a finding rather than a
    choice.** Modelled the other way — eating into the face — a 1.5 mm chamfer on each side of a
    3.5 mm annulus leaves half a millimetre of facing surface and the capacitance comes out 57%
    *below* the parallel-plate value. The published measurement is 15.7% **above** it, and a
    flat annulus reproduces that to a part in seven hundred with fringe alone. So whatever the
    *svaso* is, it is not something that removes facing area; it is a countersink in the body
    behind the face, and the face spans the full annulus. See §8 of the exercise.
    """
    r = 0.5 * (r_edges[:-1] + r_edges[1:])
    z = 0.5 * (z_edges[:-1] + z_edges[1:])
    rr, zz = np.meshgrid(r, z)

    body = (
        (rr >= electrode.inner_radius)
        & (rr <= electrode.outer_radius)
        & (zz >= gap)
        & (zz <= gap + electrode.thickness)
    )
    if electrode.chamfer_width <= 0.0 or electrode.chamfer_height <= 0.0:
        return body

    inboard_in = (rr - electrode.inner_radius) / electrode.chamfer_width
    inboard_out = (electrode.outer_radius - rr) / electrode.chamfer_width
    below_top = (gap + electrode.thickness) - zz
    cut_in = (inboard_in < 1.0) & (below_top < electrode.chamfer_height * (1.0 - inboard_in))
    cut_out = (inboard_out < 1.0) & (below_top < electrode.chamfer_height * (1.0 - inboard_out))
    return body & ~(cut_in | cut_out)


# ─────────────────────────────────────────────────────────────────── the linear solve


@dataclass
class _Operator:
    """Face conductances of the r-weighted five-point stencil.

    **The electrode is not in the domain, and that is the whole of why this class looks the way
    it does.** A cell-centred method that pins the electrode's *cells* puts the conductor's
    surface at those cells' centres, half a cell inside the metal — and with a 90 µm gap and an
    electrode divided coarsely because it carries no field, that half-cell is an order of
    magnitude larger than the gap itself. The capacitance comes back several times too small and
    nothing in the solve complains: the linear system is consistent, both capacitance routes
    agree, the residual is machine-precision. It is a wrong number, not an error.

    So the metal is *excluded*, and every face between the domain and the electrode is a
    Dirichlet face at `voltage`, with the distance from the free cell's centre to the face —
    exactly the treatment the outer truncation and the shell coating already get. The
    conductor's surface is then where the geometry says it is.
    """

    gr: np.ndarray  #: (nz, nr-1) radial faces, free cell to free cell
    gz: np.ndarray  #: (nz-1, nr) axial faces, free cell to free cell
    walls: list[tuple[np.ndarray, np.ndarray, float]]
    """Dirichlet faces, as (conductance, index mask over cells, held potential).

    One entry per family — the shell, the truncation edges, and the four ways a free cell can
    touch the electrode — each carrying the conductance seen by the free cell beside it.
    """
    diag: np.ndarray  #: (nz, nr)
    held: np.ndarray  #: (nz, nr) bool, the metal


def _operator(
    r_edges: np.ndarray,
    z_edges: np.ndarray,
    held: np.ndarray,
    epsilon: float,
    voltage: float,
) -> _Operator:
    """Assemble the conductances. **Both `r` weights live here and nowhere else.**

    A radial face at radius `r` has area `2 pi r dz`. An axial face is the annulus between two
    radii, `pi (r_out^2 - r_in^2)` — which is `2 pi r_bar dr` with `r_bar` the arithmetic mean,
    exactly rather than to first order, because that is what the difference of two squares is.

    **The axis needs no special case, and this is where that shows.** At `r = 0` the radial face
    area is `2 pi * 0 * dz = 0`, so its conductance vanishes and the natural symmetry condition
    is what the arithmetic produces by itself. A branch for the axis would be a branch that
    could disagree with the weak form.
    """
    dr, dz = np.diff(r_edges), np.diff(z_edges)
    rc, zc = 0.5 * (r_edges[:-1] + r_edges[1:]), 0.5 * (z_edges[:-1] + z_edges[1:])
    annulus = np.pi * (r_edges[1:] ** 2 - r_edges[:-1] ** 2)
    free = ~held

    radial_area = 2.0 * np.pi * r_edges[1:-1][None, :] * dz[:, None]
    axial_area = annulus[None, :] * np.ones((len(zc) - 1, 1))
    both_r = free[:, :-1] & free[:, 1:]
    both_z = free[:-1, :] & free[1:, :]
    gr = np.where(both_r, epsilon * radial_area / np.diff(rc)[None, :], 0.0)
    gz = np.where(both_z, epsilon * axial_area / np.diff(zc)[:, None], 0.0)

    walls: list[tuple[np.ndarray, np.ndarray, float]] = []

    def wall(conductance: np.ndarray, cells: np.ndarray, potential: float) -> None:
        if np.any(cells):
            walls.append((np.where(cells, conductance, 0.0), cells, potential))

    # The shell coating below, and the three truncation edges: all held at zero.
    edge = np.zeros_like(held, dtype=float)
    cells = np.zeros_like(held, dtype=bool)
    edge[0, :], cells[0, :] = epsilon * annulus / (0.5 * dz[0]), free[0, :]
    wall(edge.copy(), cells.copy(), 0.0)
    edge[:], cells[:] = 0.0, False
    edge[-1, :], cells[-1, :] = epsilon * annulus / (0.5 * dz[-1]), free[-1, :]
    wall(edge.copy(), cells.copy(), 0.0)
    edge[:], cells[:] = 0.0, False
    edge[:, 0], cells[:, 0] = epsilon * (2.0 * np.pi * r_edges[0] * dz) / (0.5 * dr[0]), free[:, 0]
    wall(edge.copy(), cells.copy(), 0.0)
    edge[:], cells[:] = 0.0, False
    edge[:, -1] = epsilon * (2.0 * np.pi * r_edges[-1] * dz) / (0.5 * dr[-1])
    cells[:, -1] = free[:, -1]
    wall(edge.copy(), cells.copy(), 0.0)

    # The four ways a free cell can face the metal. The distance is always the free cell's own
    # half-width, so the electrode surface sits on the grid line the geometry put there.
    for facing, distance, area, axis in (
        (held[:, 1:], 0.5 * dr[:-1][None, :], radial_area, 1),
        (held[:, :-1], 0.5 * dr[1:][None, :], radial_area, -1),
        (held[1:, :], 0.5 * dz[:-1][:, None], axial_area, 2),
        (held[:-1, :], 0.5 * dz[1:][:, None], axial_area, -2),
    ):
        touching = np.zeros_like(held, dtype=bool)
        conductance = np.zeros_like(held, dtype=float)
        value = epsilon * area / distance
        if axis == 1:
            touching[:, :-1] = free[:, :-1] & facing
            conductance[:, :-1] = value
        elif axis == -1:
            touching[:, 1:] = free[:, 1:] & facing
            conductance[:, 1:] = value
        elif axis == 2:
            touching[:-1, :] = free[:-1, :] & facing
            conductance[:-1, :] = value
        else:
            touching[1:, :] = free[1:, :] & facing
            conductance[1:, :] = value
        wall(conductance, touching, voltage)

    diag = np.zeros_like(held, dtype=float)
    diag[:, :-1] += gr
    diag[:, 1:] += gr
    diag[:-1, :] += gz
    diag[1:, :] += gz
    for conductance, _cells, _potential in walls:
        diag += conductance
    return _Operator(gr, gz, walls, diag, held)


def _apply(op: _Operator, x: np.ndarray) -> np.ndarray:
    out = op.diag * x
    out[:, :-1] -= op.gr * x[:, 1:]
    out[:, 1:] -= op.gr * x[:, :-1]
    out[:-1, :] -= op.gz * x[1:, :]
    out[1:, :] -= op.gz * x[:-1, :]
    return np.where(op.held, 0.0, out)


def _load(op: _Operator) -> np.ndarray:
    """What the Dirichlet faces put on the right-hand side."""
    b = np.zeros_like(op.diag)
    for conductance, _cells, potential in op.walls:
        if potential:
            b += conductance * potential
    return np.where(op.held, 0.0, b)


def _solve_cg(
    op: _Operator, rhs: np.ndarray, tolerance: float, max_iterations: int
) -> tuple[np.ndarray, int, float]:
    """Jacobi-preconditioned conjugate gradients, matrix-free — as everywhere else in the lab."""
    free = ~op.held
    x = np.zeros_like(rhs)
    residual = np.where(free, rhs - _apply(op, x), 0.0)
    inverse = np.where(free & (op.diag > 0.0), 1.0 / np.where(op.diag > 0.0, op.diag, 1.0), 0.0)
    z = residual * inverse
    direction = z.copy()
    rz = float(np.sum(residual * z))
    scale = max(float(np.sum(np.abs(rhs))), 1e-300)

    for iteration in range(1, max_iterations + 1):
        worst = float(np.max(np.abs(residual))) / scale
        if worst < tolerance:
            return x, iteration, worst
        a_direction = _apply(op, direction)
        denominator = float(np.sum(direction * a_direction))
        if abs(denominator) < 1e-300:
            break
        step = rz / denominator
        x += step * direction
        residual -= step * a_direction
        z = residual * inverse
        rz_next = float(np.sum(residual * z))
        direction = z + (rz_next / rz) * direction
        rz = rz_next
    return x, max_iterations, float(np.max(np.abs(residual))) / scale


# ────────────────────────────────────────────────────────────────────────── the solve


def solve(
    electrode: Electrode,
    gap: float,
    voltage: float = 1.0,
    numerics: Numerics | None = None,
) -> Solution:
    """One configuration: the potential in the gap, and the capacitance by two routes.

    ``voltage`` scales the potential and the stored energy and leaves the capacitance alone,
    which is the check the exercise's §5 note is about — it is there so a page can say so.
    """
    numerics = numerics or Numerics()
    if gap <= 0.0:
        raise ValueError("the gap must be positive; a closed sensor is a short circuit")

    r_edges, z_edges = build_grid(electrode, gap, numerics)
    held = electrode_mask(electrode, gap, r_edges, z_edges)
    if not held.any():
        raise ValueError(
            "no cell falls inside the electrode: the grid is too coarse for this annulus"
        )

    op = _operator(r_edges, z_edges, held, EPS0, voltage)
    free, iterations, residual = _solve_cg(
        op, _load(op), numerics.tolerance, numerics.max_iterations
    )
    potential = np.where(held, voltage, free)

    energy = _stored_energy(op, potential)
    charge = _electrode_charge(op, potential)
    return Solution(
        potential=potential,
        field=_field_magnitude(potential, r_edges, z_edges),
        held=held,
        r_edges=r_edges,
        z_edges=z_edges,
        capacitance_energy=2.0 * energy / voltage**2,
        capacitance_charge=charge / voltage,
        energy=energy,
        iterations=iterations,
        residual=residual,
    )


def _stored_energy(op: _Operator, potential: np.ndarray) -> float:
    """``W = 1/2 sum G dV^2`` over every face, the boundary ones included.

    The face sum rather than a quadrature of ``|grad V|^2`` over cells, because this one is the
    energy *of the discrete operator*: it is the quadratic form whose stationary point the solve
    found, so it inherits the solve's accuracy instead of adding a second approximation on top.
    """
    inside = np.where(op.held, 0.0, potential)
    total = 0.5 * float(np.sum(op.gr * np.diff(inside, axis=1) ** 2))
    total += 0.5 * float(np.sum(op.gz * np.diff(inside, axis=0) ** 2))
    for conductance, cells, held_potential in op.walls:
        drop = np.where(cells, held_potential - inside, 0.0)
        total += 0.5 * float(np.sum(conductance * drop**2))
    return total


def _electrode_charge(op: _Operator, potential: np.ndarray) -> float:
    """The charge on the electrode, as the flux leaving it across every face it owns.

    The second route to the capacitance, and the exercise's consistency check. For the converged
    discrete solution it is the *same number* as the energy route — discrete Green's identity,
    with one electrode at ``V`` and everything else at zero — so what their gap measures is how
    far the linear solve got, not how well the chamfer was resolved. Cheap, worth having, and
    worth not overselling: the mesh study is the check on the geometry.
    """
    inside = np.where(op.held, 0.0, potential)
    total = 0.0
    for conductance, cells, held_potential in op.walls:
        if not held_potential:
            continue
        total += float(np.sum(np.where(cells, conductance * (held_potential - inside), 0.0)))
    return total


def _field_magnitude(
    potential: np.ndarray, r_edges: np.ndarray, z_edges: np.ndarray
) -> np.ndarray:
    """``|E| = |grad V|`` at cell centres, by central differences. Volts per metre."""
    rc = 0.5 * (r_edges[:-1] + r_edges[1:])
    zc = 0.5 * (z_edges[:-1] + z_edges[1:])
    er = np.zeros_like(potential)
    ez = np.zeros_like(potential)
    er[:, 1:-1] = (potential[:, 2:] - potential[:, :-2]) / (rc[2:] - rc[:-2])[None, :]
    ez[1:-1, :] = (potential[2:, :] - potential[:-2, :]) / (zc[2:] - zc[:-2])[:, None]
    return np.hypot(er, ez)
