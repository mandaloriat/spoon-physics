"""Steady conduction in the *solid* heat sink: the same physics as :mod:`heatsink`, in 3-D.

``docs/exercises/heat-sink.md`` §13. Arrays in, arrays out, no Fenix Spoon import — the split
every lab adapter uses. The protocol-facing half is :mod:`physics_lab.solvers.heatsink3d`.

**What the third dimension is for, and it is one thing.** The 2-D solve is *exact* for an
extrusion, and its own assumption says so: a prismatic body has no third-dimension conduction to
neglect. What it assumes instead is that the device heats the base **uniformly along the
length** — and a 30 mm die on a 60 mm extrusion does not. The heat has to spread sideways along
the base to reach the far fins, and that spread costs a temperature drop the plane problem has
nowhere to put. That drop is the **spreading resistance**, and until protocol 1.17 there was no
way to send a body with a length, so no way to ask for it and no way to be told it was missing.
This module is what asks.

**What is solved.** ``div(k grad T) = 0`` over the whole body, by finite volumes on a
tensor-product grid: the cross-section grid :func:`heatsink.build_grid` already builds — lines
on every fin edge, so the metal/air interface is exact rather than a staircase — extruded along
``z`` with lines on the two edges of the device footprint for the same reason.

**What is reused, and why that is the interesting part.** Everything on the boundary:

* ``h`` comes from :mod:`physics_lab.solvers.correlations`, on the same channel width. The
  channel is unchanged by the third dimension — it is the *same* channel, longer.
* the radiative exchange inside a channel is the 2-D radiosity problem of
  :mod:`physics_lab.solvers.viewfactors`, solved at every station along the length with that
  station's wall temperatures. The enclosure geometry really is prismatic, so the view factors
  are the right ones; what is neglected is exchange *along* the channel, which is the
  ``prismatic_radiation`` assumption the adapter declares.

So the only thing this module adds to the 2-D model is conduction along ``z`` and the two cut
ends — which is exactly the claim "3-D buys the depth" and nothing more. That it adds nothing
else is testable, and it is tested: with the footprint spanning the whole length and the ends
held adiabatic, this solver reproduces :func:`heatsink.solve` on the same in-plane grid to
within the CG tolerance. The residual of that comparison is reported as
``extruded_limit`` rather than only asserted in a test, because a visitor is entitled to see it.

**Cost, and where it went.** A 3-D solve is the in-plane cell count times the number of
stations, so the in-plane grid is coarser here than the 2-D exercise runs by default and the
station count is its own knob. The reference solve the spreading resistance is measured against
is run **on the same in-plane grid**, so what the difference reports is the third dimension and
not the two discretisations disagreeing.
"""

from dataclasses import dataclass, field, replace

import numpy as np

from physics_lab.solvers import heatsink
from physics_lab.solvers.correlations import Coefficient, forced_convection, natural_convection
from physics_lab.solvers.heatsink import (
    KELVIN,
    MIN_EXCESS_K,
    SIGMA,
    Conditions,
    Enclosure,
    Numerics,
    Profile,
    build_grid,
    grid_lines,
    solid_mask,
)

#: Face kinds, as integer codes rather than strings. The 2-D solver carries one string per
#: :class:`heatsink.Face` because it has a few hundred of them; here a face is a *column* of
#: faces, one per station, and the classification is an array operation.
ADIABATIC, CHANNEL, OPEN, FOOTPRINT = 0, 1, 2, 3


@dataclass(frozen=True)
class Extrusion:
    """What the third dimension adds to :class:`heatsink.Conditions`.

    The length itself is not here: it is ``Conditions.depth``, which has carried it since the
    2-D solver needed it to turn a per-unit-depth answer into watts. What is here is what only
    a solved third dimension can use — where the device sits along that length, how finely the
    length is divided, and whether the two cut ends are exposed.
    """

    #: Contact length of the device along the extrusion, m. The device sits centred.
    footprint_depth: float = 0.030
    #: Target cell edge along the length, m. Coarser than the in-plane grid on purpose: there
    #: is no geometric feature along ``z`` except the two footprint edges, and the temperature
    #: variation this resolves is a smooth spread rather than a boundary layer.
    cell_size: float = 0.0025
    #: Do the two cut ends lose heat? True is a sink in open air. False is the idealisation the
    #: 2-D model makes, and setting it is what makes the extruded limit *exactly* reproducible
    #: rather than nearly so — see ``extruded_limit`` in :attr:`Solution.residuals`.
    ends_open: bool = True

    def __post_init__(self) -> None:
        if self.footprint_depth <= 0.0:
            raise ValueError("footprint_depth must be positive")
        if self.cell_size <= 0.0:
            raise ValueError("cell_size must be positive")


@dataclass
class Solution:
    """A converged 3-D solve, with the numbers the exercise reports and the checks it makes."""

    temperature_c: np.ndarray  #: (nz, ny, nx), NaN where the cell is not metal
    mask: np.ndarray  #: (ny, nx) bool — the cross-section, which is the same at every station
    flux_magnitude: np.ndarray  #: (nz, ny, nx) W/m^2, NaN outside the metal
    #: The grid lines, not the cell centres. Centres are a reading of these and are offered as
    #: properties: keeping both as data would be two places for one grid to be described, and
    #: reconstructing the edges from the centres afterwards is not exact on a graded grid.
    x_edges: np.ndarray
    y_edges: np.ndarray
    z_edges: np.ndarray
    metrics: dict[str, float] = field(default_factory=dict)
    residuals: dict[str, float] = field(default_factory=dict)
    coefficient: Coefficient | None = None
    passes: int = 0
    cg_iterations: int = 0
    #: The extruded reference this solve is measured against — :func:`heatsink.solve` on the
    #: same in-plane grid. ``None`` when the caller asked for no reference.
    reference: heatsink.Solution | None = None
    #: The same body with its two cut ends shut, when this solve had them open. It is what
    #: separates the two things the third dimension did — see :func:`solve`.
    shut: "Solution | None" = None

    @property
    def x_centres(self) -> np.ndarray:
        return 0.5 * (self.x_edges[:-1] + self.x_edges[1:])

    @property
    def y_centres(self) -> np.ndarray:
        return 0.5 * (self.y_edges[:-1] + self.y_edges[1:])

    @property
    def z_centres(self) -> np.ndarray:
        return 0.5 * (self.z_edges[:-1] + self.z_edges[1:])

    @property
    def cells(self) -> int:
        return int(self.mask.sum()) * (len(self.z_edges) - 1)


# ────────────────────────────────────────────────────────────────────────── the grid


def build_z_edges(depth: float, footprint_depth: float, cell_size: float) -> np.ndarray:
    """Stations along the length, with lines on both edges of the device footprint.

    The same rule as the cross-section grid, for the same reason: a boundary that falls between
    two cell centres is a boundary whose position moves with the resolution. Here the boundary
    is where the device stops touching the base, which is the discontinuity the whole exercise
    is about.
    """
    if footprint_depth >= depth:
        return grid_lines([0.0, depth], cell_size)
    margin = 0.5 * (depth - footprint_depth)
    return grid_lines([0.0, margin, depth - margin, depth], cell_size)


def _footprint_span(depth: float, footprint_depth: float) -> tuple[float, float]:
    """``(z_start, z_end)`` of the device contact, centred on the length."""
    reach = min(footprint_depth, depth)
    margin = 0.5 * (depth - reach)
    return margin, depth - margin


# ─────────────────────────────────────────────────────────────────── the face columns


@dataclass
class Lateral:
    """The 2-D exposed faces, lifted to arrays over ``(face, station)``.

    One :class:`heatsink.Face` becomes a column of faces, one per station, all with the same
    row, column and kind — except a footprint face, which is a footprint only where the device
    actually is. Keeping this as arrays rather than a list of a hundred thousand dataclasses is
    what makes the Picard loop a handful of array operations.
    """

    faces: list[heatsink.Face]
    rows: np.ndarray  #: (n,)
    cols: np.ndarray  #: (n,)
    length: np.ndarray  #: (n,) face length in the plane, m
    half_cell: np.ndarray  #: (n,)
    on_fin: np.ndarray  #: (n,) bool
    channel: np.ndarray  #: (n,) int, -1 when the face is not in a channel
    kind: np.ndarray  #: (n, nz) int code
    area: np.ndarray  #: (n, nz) m^2


def _lateral(
    faces: list[heatsink.Face],
    conditions: Conditions,
    extrusion: Extrusion,
    z_edges: np.ndarray,
) -> Lateral:
    codes = {"adiabatic": ADIABATIC, "channel": CHANNEL, "open": OPEN, "footprint": FOOTPRINT}
    hz = np.diff(z_edges)
    zc = 0.5 * (z_edges[:-1] + z_edges[1:])
    plane_kind = np.array([codes[f.kind] for f in faces], dtype=int)

    kind = np.repeat(plane_kind[:, None], len(zc), axis=1)
    # A face under the device is a footprint only for the stations the device covers. Away from
    # it the underside is whatever the mounting makes it, which is the same choice the 2-D
    # classifier makes for the base outside the contact width.
    start, end = _footprint_span(conditions.depth, extrusion.footprint_depth)
    under = (zc >= start) & (zc <= end)
    away = ADIABATIC if conditions.base_mounted_flush else OPEN
    kind[np.ix_(plane_kind == FOOTPRINT, ~under)] = away

    return Lateral(
        faces=faces,
        rows=np.array([f.row for f in faces], dtype=int),
        cols=np.array([f.col for f in faces], dtype=int),
        length=np.array([f.area for f in faces], dtype=float),
        half_cell=np.array([f.half_cell for f in faces], dtype=float),
        on_fin=np.array([f.on_fin for f in faces], dtype=bool),
        channel=np.array([f.channel for f in faces], dtype=int),
        kind=kind,
        area=np.array([f.area for f in faces], dtype=float)[:, None] * hz[None, :],
    )


@dataclass
class Ends:
    """The two cut ends — the faces that exist only because the body has a length.

    They are why an extrusion cut short runs cooler than the per-unit-depth model says, and
    they are the reason :class:`Extrusion` carries ``ends_open``: with them shut, this solver
    and the 2-D one are solving the same problem, and a claim that they agree becomes checkable
    rather than approximate.
    """

    layers: np.ndarray  #: (m,) station index — 0 or nz - 1
    rows: np.ndarray
    cols: np.ndarray
    area: np.ndarray
    half_cell: np.ndarray
    on_fin: np.ndarray


def _ends(
    profile: Profile,
    extrusion: Extrusion,
    mask: np.ndarray,
    x_edges: np.ndarray,
    y_edges: np.ndarray,
    z_edges: np.ndarray,
) -> Ends:
    hx, hy, hz = np.diff(x_edges), np.diff(y_edges), np.diff(z_edges)
    yc = 0.5 * (y_edges[:-1] + y_edges[1:])
    rows, cols = np.nonzero(mask)
    nz = len(hz)

    layers = np.concatenate([np.zeros(len(rows), dtype=int), np.full(len(rows), nz - 1)])
    rows2 = np.concatenate([rows, rows])
    cols2 = np.concatenate([cols, cols])
    area = hx[cols2] * hy[rows2]
    half = 0.5 * hz[layers]
    return Ends(
        layers=layers,
        rows=rows2,
        cols=cols2,
        area=area,
        half_cell=half,
        on_fin=yc[rows2] > profile.base_thickness,
    )


# ─────────────────────────────────────────────────────────────────── the linear solve


def _conductances(
    conductivity: float,
    x_edges: np.ndarray,
    y_edges: np.ndarray,
    z_edges: np.ndarray,
    mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Face conductances on the seven-point stencil.

    The in-plane pair is the 2-D solver's, times the thickness of the station — which is what
    "per unit depth" meant all along, written out. The third is new and is the only conductance
    the plane problem could not have: metal to metal along the extrusion. A prismatic body is
    solid at every station wherever it is solid in the section, so the ``z`` link exists exactly
    where the section is metal and no mask product is needed for it.
    """
    hx, hy, hz = np.diff(x_edges), np.diff(y_edges), np.diff(z_edges)
    both_x = mask[:, :-1] & mask[:, 1:]
    both_y = mask[:-1, :] & mask[1:, :]
    dx = 0.5 * (hx[:-1] + hx[1:])
    dy = 0.5 * (hy[:-1] + hy[1:])
    dz = 0.5 * (hz[:-1] + hz[1:])

    plane_x = np.where(both_x, conductivity * hy[:, None] / dx[None, :], 0.0)
    plane_y = np.where(both_y, conductivity * hx[None, :] / dy[:, None], 0.0)
    cx = plane_x[None, :, :] * hz[:, None, None]
    cy = plane_y[None, :, :] * hz[:, None, None]

    cell_face = np.where(mask, conductivity * (hx[None, :] * hy[:, None]), 0.0)
    cz = cell_face[None, :, :] / dz[:, None, None]
    return cx, cy, cz


def _apply(
    t: np.ndarray, diag: np.ndarray, cx: np.ndarray, cy: np.ndarray, cz: np.ndarray
) -> np.ndarray:
    out = diag * t
    out[:, :, :-1] -= cx * t[:, :, 1:]
    out[:, :, 1:] -= cx * t[:, :, :-1]
    out[:, :-1, :] -= cy * t[:, 1:, :]
    out[:, 1:, :] -= cy * t[:, :-1, :]
    out[:-1, :, :] -= cz * t[1:, :, :]
    out[1:, :, :] -= cz * t[:-1, :, :]
    return out


def _solve_cg(
    diag: np.ndarray,
    cx: np.ndarray,
    cy: np.ndarray,
    cz: np.ndarray,
    rhs: np.ndarray,
    mask: np.ndarray,
    guess: np.ndarray,
    tolerance: float,
    max_iterations: int,
) -> tuple[np.ndarray, int]:
    """Jacobi-preconditioned conjugate gradients on the seven-point stencil.

    :func:`heatsink._solve_cg` with one more pair of shifted multiplies. Matrix-free for the
    reason it is there: assembling a 100.000-cell operator would be a large sparse matrix to
    build for an operator that is six shifts and a scale.
    """
    t = np.where(mask, guess, 0.0)
    residual = np.where(mask, rhs - _apply(t, diag, cx, cy, cz), 0.0)
    inverse_diagonal = np.where(mask & (diag > 0.0), 1.0 / np.where(diag > 0.0, diag, 1.0), 0.0)
    z = residual * inverse_diagonal
    direction = z.copy()
    rz = float(np.sum(residual * z))
    scale = max(float(np.sum(np.abs(rhs))), 1e-30)

    for iteration in range(1, max_iterations + 1):
        if float(np.max(np.abs(residual))) / scale < tolerance:
            return t, iteration
        a_direction = np.where(mask, _apply(direction, diag, cx, cy, cz), 0.0)
        denominator = float(np.sum(direction * a_direction))
        if abs(denominator) < 1e-300:
            break
        step = rz / denominator
        t += step * direction
        residual -= step * a_direction
        z = residual * inverse_diagonal
        rz_next = float(np.sum(residual * z))
        direction = z + (rz_next / rz) * direction
        rz = rz_next
    return t, max_iterations


# ────────────────────────────────────────────────────────────────────────── the solve


def solve(
    profile: Profile,
    conditions: Conditions,
    extrusion: Extrusion,
    numerics: Numerics | None = None,
    reference: bool = True,
    decompose: bool = True,
) -> Solution:
    """Run the coupled 3-D solve, and separate the two things the third dimension did.

    The number this exercise exists to produce is a *difference* — a resistance on its own does
    not say what the plane model was missing — and the difference turns out to be **two**
    effects pulling opposite ways:

    * the device heats only part of the length, so heat spreads sideways along the base to reach
      the far fins and pays a temperature drop doing it. This **raises** the resistance, and it
      is what "spreading resistance" means;
    * the extrusion has two cut ends, and they are surface. This **lowers** it.

    On a 60 mm extrusion in aluminium they nearly cancel, which is why the plane model has been
    getting away with it; on a 200 mm one the spreading wins by fourteen percent. Reporting only
    the net would leave a visitor to conclude that three dimensions do not matter here, when
    what is true is that two effects of a few percent happen to be about the same size.

    So the run is up to three solves, and each is a term in
    ``R = R_extruded + spreading - end_gain``:

    ``reference``
        :func:`heatsink.solve` on the same in-plane grid and the same conditions — the plane
        model, exactly as ``lab.heatsink2d`` would report it. Same grid on purpose: what the
        difference should show is the third dimension, not two discretisations disagreeing.
    ``decompose``
        the same body with its cut ends shut, which isolates the spreading. Skipped when the
        ends are already shut, since the solve would be this one again.
    """
    numerics = numerics or Numerics(cell_size=0.0015)
    x_edges, y_edges = build_grid(profile, numerics.cell_size)
    z_edges = build_z_edges(conditions.depth, extrusion.footprint_depth, extrusion.cell_size)
    mask = solid_mask(profile, x_edges, y_edges)
    nz = len(z_edges) - 1

    plane_faces = heatsink.exposed_faces(profile, conditions, x_edges, y_edges, mask)
    lateral = _lateral(plane_faces, conditions, extrusion, z_edges)
    ends = _ends(profile, extrusion, mask, x_edges, y_edges, z_edges)
    cx, cy, cz = _conductances(conditions.conductivity, x_edges, y_edges, z_edges, mask)

    ambient_k = conditions.ambient_k
    temperature_k = np.where(mask, ambient_k + 20.0, 0.0)[None, :, :] * np.ones((nz, 1, 1))

    enclosures: dict[int, tuple[Enclosure, np.ndarray]] = {}
    if conditions.radiation:
        for index, (left, right) in enumerate(profile.channel_spans):
            members = np.nonzero((lateral.kind[:, 0] == CHANNEL) & (lateral.channel == index))[0]
            if not len(members):
                continue
            enclosures[index] = (
                Enclosure(
                    [plane_faces[i] for i in members],
                    heatsink.mouth_surfaces(profile, x_edges, left, right),
                    conditions.emissivity,
                ),
                members,
            )

    convective = (lateral.kind == CHANNEL) | (lateral.kind == OPEN)
    lat_i, lat_k = np.nonzero(convective)
    foot_i, foot_k = np.nonzero(lateral.kind == FOOTPRINT)
    footprint_area = float(lateral.area[foot_i, foot_k].sum())
    if footprint_area <= 0.0:
        raise ValueError("the device footprint does not touch the base")

    coefficient = Coefficient(0.0, "none", True, "")
    passes = 0
    cg_iterations = 0

    for pass_index in range(1, numerics.max_passes + 1):
        passes = pass_index
        wall_k = _at_faces(temperature_k, lateral)
        walls = [wall_k[convective]]
        if extrusion.ends_open:
            walls.append(temperature_k[ends.layers, ends.rows, ends.cols])
        excess = float(np.mean(np.concatenate(walls))) - ambient_k

        coefficient = _coefficient(profile, conditions, excess, ambient_k)
        radiative_h = _radiative_h(
            temperature_k, lateral, ends, enclosures, conditions, extrusion, ambient_k
        )

        diag = np.zeros((nz,) + mask.shape, dtype=float)
        rhs = np.zeros_like(diag)
        diag[:, :, :-1] += cx
        diag[:, :, 1:] += cx
        diag[:, :-1, :] += cy
        diag[:, 1:, :] += cy
        diag[:-1, :, :] += cz
        diag[1:, :, :] += cz

        # The device: its power, spread over the contact patch it actually has. This is the
        # whole difference from the plane problem — there the patch is a line and the power per
        # unit depth is uniform along a length nobody solved.
        np.add.at(
            rhs,
            (foot_k, lateral.rows[foot_i], lateral.cols[foot_i]),
            (conditions.power_w / footprint_area) * lateral.area[foot_i, foot_k],
        )

        _add_film(
            diag,
            rhs,
            (lat_k, lateral.rows[lat_i], lateral.cols[lat_i]),
            coefficient.value + radiative_h.lateral[convective],
            lateral.area[convective],
            lateral.half_cell[lat_i],
            conditions.conductivity,
            ambient_k,
        )
        if extrusion.ends_open:
            _add_film(
                diag,
                rhs,
                (ends.layers, ends.rows, ends.cols),
                coefficient.value + radiative_h.ends,
                ends.area,
                ends.half_cell,
                conditions.conductivity,
                ambient_k,
            )

        updated, iterations = _solve_cg(
            diag,
            cx,
            cy,
            cz,
            rhs,
            mask,
            temperature_k,
            numerics.cg_tolerance,
            numerics.cg_max_iterations,
        )
        cg_iterations += iterations
        relaxed = temperature_k + numerics.relaxation * (updated - temperature_k)
        broadcast = np.broadcast_to(mask, relaxed.shape)
        change = float(np.max(np.abs(relaxed - temperature_k)[broadcast]))
        temperature_k = np.where(mask, relaxed, 0.0)
        if change < numerics.tolerance_k:
            break

    extruded = heatsink.solve(profile, conditions, numerics) if reference else None
    shut = (
        solve(
            profile,
            conditions,
            replace(extrusion, ends_open=False),
            numerics,
            reference=False,
            decompose=False,
        )
        if decompose and extrusion.ends_open
        else None
    )
    return _assemble(
        profile,
        conditions,
        extrusion,
        x_edges,
        y_edges,
        z_edges,
        mask,
        lateral,
        ends,
        enclosures,
        temperature_k,
        coefficient,
        passes,
        cg_iterations,
        extruded,
        shut,
    )


def _at_faces(temperature_k: np.ndarray, lateral: Lateral) -> np.ndarray:
    """Cell temperature behind each lateral face, as ``(face, station)``."""
    return temperature_k[:, lateral.rows, lateral.cols].T


def _coefficient(
    profile: Profile, conditions: Conditions, excess: float, ambient_k: float
) -> Coefficient:
    """``h``, from the same correlations and on the same channel as the plane problem.

    The third dimension changes neither: a channel between two fins is the same channel however
    long the extrusion is, and its width is what the correlation is a function of. What *is*
    different is that the surface excess feeding the film properties is now averaged over a
    surface that varies along the length as well as up it — one coefficient over the whole
    body, as in 2-D, which is the ``correlated_convection_coefficient`` assumption unchanged.
    """
    if conditions.h_override is not None:
        return Coefficient(conditions.h_override, "override", True, "pinned by the visitor")
    if conditions.mode == "forced":
        return forced_convection(
            profile.channel_width,
            conditions.depth,
            conditions.face_velocity,
            excess,
            ambient_k,
        )
    return natural_convection(profile.channel_width, profile.fin_height, excess, ambient_k)


@dataclass
class Radiative:
    """Equivalent radiative coefficients, ``q / (T_wall - T_inf)``, for one Picard pass."""

    lateral: np.ndarray  #: (n, nz)
    ends: np.ndarray  #: (m,)


def _radiative_h(
    temperature_k: np.ndarray,
    lateral: Lateral,
    ends: Ends,
    enclosures: dict[int, tuple[Enclosure, np.ndarray]],
    conditions: Conditions,
    extrusion: Extrusion,
    ambient_k: float,
) -> Radiative:
    """The radiative half of the boundary, linearised the way the 2-D solver linearises it.

    Two populations, and the difference between them is what they can see. A face inside a
    channel exchanges with the facing fin, the strip of base between them and the fictitious
    black window at the mouth — its own enclosure, solved here at every station at once. A face
    on the outside, and both cut ends, look straight at the room.
    """
    out = Radiative(np.zeros_like(lateral.kind, dtype=float), np.zeros(len(ends.area)))
    if not conditions.radiation:
        return out

    wall_k = _at_faces(temperature_k, lateral)
    for enclosure, members in enclosures.values():
        walls = wall_k[members]
        flux = enclosure.net_flux_columns(walls, ambient_k)
        out.lateral[members] = flux / np.maximum(walls - ambient_k, MIN_EXCESS_K)

    to_room = lateral.kind == OPEN
    q = conditions.emissivity * SIGMA * (wall_k**4 - ambient_k**4)
    out.lateral = np.where(
        to_room, q / np.maximum(wall_k - ambient_k, MIN_EXCESS_K), out.lateral
    )

    if extrusion.ends_open:
        end_k = temperature_k[ends.layers, ends.rows, ends.cols]
        q_ends = conditions.emissivity * SIGMA * (end_k**4 - ambient_k**4)
        out.ends = q_ends / np.maximum(end_k - ambient_k, MIN_EXCESS_K)
    return out


def _add_film(
    diag: np.ndarray,
    rhs: np.ndarray,
    index: tuple[np.ndarray, np.ndarray, np.ndarray],
    total_h: np.ndarray,
    area: np.ndarray,
    half_cell: np.ndarray,
    conductivity: float,
    ambient_k: float,
) -> None:
    """Put one population of exposed faces into the operator.

    The half-cell of conduction between the cell centre and the surface sits in series with the
    film, exactly as in the plane problem — negligible for aluminium, not for a poor conductor,
    and one division either way.
    """
    positive = total_h > 0.0
    if not np.any(positive):
        return
    effective = 1.0 / (
        1.0 / np.where(positive, total_h, 1.0) + half_cell / conductivity
    )
    contribution = np.where(positive, effective * area, 0.0)
    np.add.at(diag, index, contribution)
    np.add.at(rhs, index, contribution * ambient_k)


# ──────────────────────────────────────────────────────────────────────── the answer


def _assemble(
    profile: Profile,
    conditions: Conditions,
    extrusion: Extrusion,
    x_edges: np.ndarray,
    y_edges: np.ndarray,
    z_edges: np.ndarray,
    mask: np.ndarray,
    lateral: Lateral,
    ends: Ends,
    enclosures: dict[int, tuple[Enclosure, np.ndarray]],
    temperature_k: np.ndarray,
    coefficient: Coefficient,
    passes: int,
    cg_iterations: int,
    extruded: heatsink.Solution | None,
    shut: Solution | None,
) -> Solution:
    ambient_k = conditions.ambient_k
    radiative = _radiative_h(
        temperature_k, lateral, ends, enclosures, conditions, extrusion, ambient_k
    )

    wall_k = _at_faces(temperature_k, lateral)
    convective = (lateral.kind == CHANNEL) | (lateral.kind == OPEN)
    excess = wall_k - ambient_k
    lat_conv = np.where(convective, coefficient.value * excess * lateral.area, 0.0)
    lat_rad = np.where(
        convective,
        radiative.lateral * np.maximum(excess, MIN_EXCESS_K) * lateral.area,
        0.0,
    )

    end_k = temperature_k[ends.layers, ends.rows, ends.cols]
    end_excess = end_k - ambient_k
    if extrusion.ends_open:
        end_conv = coefficient.value * end_excess * ends.area
        end_rad = radiative.ends * np.maximum(end_excess, MIN_EXCESS_K) * ends.area
    else:
        end_conv = np.zeros_like(ends.area)
        end_rad = np.zeros_like(ends.area)

    convective_out = float(lat_conv.sum() + end_conv.sum())
    radiative_out = float(lat_rad.sum() + end_rad.sum())
    total_out = convective_out + radiative_out
    end_out = float(end_conv.sum() + end_rad.sum())

    peak_k = float(np.max(temperature_k[np.broadcast_to(mask, temperature_k.shape)]))
    rise = peak_k - ambient_k
    resistance = rise / conditions.power_w

    view_weighted = 0.0
    view_area = 0.0
    for enclosure, members in enclosures.values():
        views = enclosure.view_to_room()
        area = lateral.area[members].sum(axis=1)
        view_weighted += float(np.sum(views * area))
        view_area += float(area.sum())

    metrics = {
        "t_max_c": peak_k - KELVIN,
        "t_rise_k": rise,
        "flux_max_w_m2": conditions.conductivity
        * float(np.nanmax(_flux_magnitude(temperature_k, mask, x_edges, y_edges, z_edges))),
        "thermal_resistance_k_w": resistance,
        "mass_kg": conditions.density * profile.solid_area * conditions.depth,
        "fin_efficiency": _fin_efficiency(
            profile,
            conditions,
            extrusion,
            y_edges,
            lateral,
            ends,
            temperature_k,
            lat_conv + lat_rad,
            end_conv + end_rad,
            coefficient,
            radiative,
            rise,
        ),
        "radiative_fraction": float(radiative_out / total_out) if total_out > 0 else 0.0,
        "view_factor_to_room": float(view_weighted / view_area) if view_area > 0 else 1.0,
        "channel_width_mm": profile.channel_width * 1e3,
        "h_convective_w_m2k": coefficient.value,
        # The two numbers a plane solve has nowhere to put. `end_loss_fraction` is not a
        # curiosity: it is the *other* thing the third dimension changed, and reporting it is
        # what stops the spreading resistance below being read as one effect when it is a net.
        "end_loss_fraction": float(end_out / total_out) if total_out > 0 else 0.0,
        "footprint_coverage": float(
            min(extrusion.footprint_depth, conditions.depth) / conditions.depth
        ),
    }
    metrics["score_k_kg_w"] = metrics["thermal_resistance_k_w"] * metrics["mass_kg"]

    residuals = {
        "energy_balance": abs(total_out - conditions.power_w) / max(conditions.power_w, 1e-30),
        "picard_passes": float(passes),
    }
    for index, (enclosure, _members) in enclosures.items():
        from physics_lab.solvers.viewfactors import enclosure_residuals

        worst = enclosure_residuals(enclosure.surfaces, enclosure.matrix)
        residuals[f"view_factor_summation_channel_{index}"] = worst["summation"]
        residuals[f"view_factor_reciprocity_channel_{index}"] = worst["reciprocity"]

    if extruded is not None:
        plane = extruded.metrics["thermal_resistance_k_w"]
        # `R = R_extruded + spreading - end_gain`, and every term is a solve rather than an
        # apportionment of one. With the ends already shut this solve *is* the shut one, so
        # the spreading is the whole difference and the end gain is zero by construction.
        shut_resistance = shut.metrics["thermal_resistance_k_w"] if shut else resistance
        metrics["thermal_resistance_extruded_k_w"] = plane
        metrics["depth_correction_k_w"] = resistance - plane
        metrics["spreading_resistance_k_w"] = shut_resistance - plane
        metrics["end_gain_k_w"] = shut_resistance - resistance
        # A residual only where the two solvers are solving the same problem. Everywhere else
        # the difference is the answer, and calling the answer a residual would be the
        # arithmetic saying what it wants to hear.
        if _is_extruded_limit(conditions, extrusion):
            residuals["extruded_limit"] = abs(resistance - plane) / max(abs(plane), 1e-30)

    return Solution(
        temperature_c=np.where(mask, temperature_k - KELVIN, np.nan),
        mask=mask,
        flux_magnitude=conditions.conductivity
        * _flux_magnitude(temperature_k, mask, x_edges, y_edges, z_edges),
        x_edges=x_edges,
        y_edges=y_edges,
        z_edges=z_edges,
        metrics=metrics,
        residuals=residuals,
        coefficient=coefficient,
        passes=passes,
        cg_iterations=cg_iterations,
        reference=extruded,
        shut=shut,
    )


def _is_extruded_limit(conditions: Conditions, extrusion: Extrusion) -> bool:
    """Is this configuration the one the plane solver models exactly?

    Two conditions, and both are needed: the device has to heat the base along the whole
    length, and the cut ends have to be shut. Either one alone leaves a real difference between
    the two solvers, and a residual computed over a real difference is not a residual.
    """
    return extrusion.footprint_depth >= conditions.depth and not extrusion.ends_open


def _fin_efficiency(
    profile: Profile,
    conditions: Conditions,
    extrusion: Extrusion,
    y_edges: np.ndarray,
    lateral: Lateral,
    ends: Ends,
    temperature_k: np.ndarray,
    lat_heat: np.ndarray,
    end_heat: np.ndarray,
    coefficient: Coefficient,
    radiative: Radiative,
    rise: float,
) -> float:
    """What the fins move, against what they would move at their own root temperature.

    The 2-D reading with the fin roots now varying along the length as well as across the base,
    which is the point: under a small device the outer fins are rooted in cooler metal, and an
    efficiency read against one root temperature would hide exactly that.
    """
    root = heatsink.root_row(y_edges, profile)
    convective = (lateral.kind == CHANNEL) | (lateral.kind == OPEN)
    on_fin = convective & lateral.on_fin[:, None]

    fin_heat = float(lat_heat[on_fin].sum())
    fin_area = float(lateral.area[on_fin].sum())
    roots = temperature_k[:, root, lateral.cols].T
    root_excess = float(np.mean(roots[on_fin])) - conditions.ambient_k if fin_area else 0.0

    if extrusion.ends_open:
        end_fin = ends.on_fin
        fin_heat += float(end_heat[end_fin].sum())
        fin_area += float(ends.area[end_fin].sum())

    # One coefficient for the ideal fin, as in the plane problem: the convective one plus the
    # area-weighted radiative one, because a fin at its root temperature would shed heat by both.
    exposed = float(lateral.area[convective].sum()) + (
        float(ends.area.sum()) if extrusion.ends_open else 0.0
    )
    total_h = coefficient.value
    if conditions.radiation and exposed > 0.0:
        mean_radiative = float(
            (lateral.area[convective] * radiative.lateral[convective]).sum()
        )
        if extrusion.ends_open:
            mean_radiative += float((ends.area * radiative.ends).sum())
        total_h += mean_radiative / exposed

    ideal = total_h * fin_area * root_excess
    return float(fin_heat / ideal) if ideal > 0.0 and rise > 0.0 else float("nan")


def _flux_magnitude(
    temperature_k: np.ndarray,
    mask: np.ndarray,
    x_edges: np.ndarray,
    y_edges: np.ndarray,
    z_edges: np.ndarray,
) -> np.ndarray:
    """``|grad T|`` at cell centres, by central differences on all three axes."""
    hx, hy, hz = np.diff(x_edges), np.diff(y_edges), np.diff(z_edges)
    t = np.where(mask, temperature_k, np.nan)
    gx = np.full(t.shape, np.nan)
    gy = np.full(t.shape, np.nan)
    gz = np.full(t.shape, np.nan)
    gx[:, :, 1:-1] = (t[:, :, 2:] - t[:, :, :-2]) / (
        hx[1:-1] + 0.5 * (hx[:-2] + hx[2:])
    )[None, None, :]
    gy[:, 1:-1, :] = (t[:, 2:, :] - t[:, :-2, :]) / (
        hy[1:-1] + 0.5 * (hy[:-2] + hy[2:])
    )[None, :, None]
    if len(hz) >= 3:
        gz[1:-1, :, :] = (t[2:, :, :] - t[:-2, :, :]) / (
            hz[1:-1] + 0.5 * (hz[:-2] + hz[2:])
        )[:, None, None]
    magnitude = np.sqrt(
        np.nan_to_num(gx) ** 2 + np.nan_to_num(gy) ** 2 + np.nan_to_num(gz) ** 2
    )
    return np.where(mask, magnitude, np.nan)


# ─────────────────────────────────────────────────────────────────────── the picture


#: The six tetrahedra of a cube, as the corner offsets ``(dz, dy, dx)`` they are built from.
#: One per permutation of the three axes: start at the low corner, take a unit step along each
#: axis in that order, and the four points reached are a tetrahedron. The six of them fill the
#: cube exactly and — this is the part that matters — the four they induce on a shared face are
#: the same four whichever cube you look from, so the mesh is conforming with no orientation
#: bookkeeping.
_KUHN = [
    [(0, 0, 0), (0, 0, 1), (0, 1, 1), (1, 1, 1)],
    [(0, 0, 0), (0, 1, 0), (0, 1, 1), (1, 1, 1)],
    [(0, 0, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1)],
    [(0, 0, 0), (1, 0, 0), (1, 0, 1), (1, 1, 1)],
    [(0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 1, 1)],
    [(0, 0, 0), (1, 0, 0), (1, 1, 0), (1, 1, 1)],
]


@dataclass
class Lattice:
    """A tetrahedral mesh of the body, with one value per node — a ``mesh3d``, in arrays.

    **Why this is not the grid the solve ran on.** A `mesh3d` is the first payload whose inline
    size is a design problem, and six tetrahedra per cell of a hundred-thousand-cell solve is
    tens of megabytes of JSON for a picture nobody can see that finely. So the body is retiled
    on a coarser lattice — built by the *same* rule, with lines on every fin edge, so no fin
    disappears and no interface moves — and the solution is read onto it. What travels is
    therefore a faithful shape at a coarse sampling, rather than a fine sampling of a shape that
    has been rounded off, which is the trade the other way round and the wrong one.

    The values are the finite-volume solution of the containing cell, averaged over the cells
    meeting at each node. No interpolation: a cell-centred method knows a cell's value and
    nothing finer, and inventing a gradient inside one for the picture would be inventing data.
    """

    points: np.ndarray  #: (n, 3)
    tets: np.ndarray  #: (m, 4) int
    temperature_c: np.ndarray  #: (n,)
    flux: np.ndarray  #: (n,)
    bounds: tuple[float, float, float, float, float, float]

    @property
    def cells(self) -> int:
        return len(self.tets)


def display_lattice(
    profile: Profile,
    conditions: Conditions,
    extrusion: Extrusion,
    solution: Solution,
    cell_size: float,
) -> Lattice:
    """Retile the body at ``cell_size`` and read the solution onto it."""
    x_edges, y_edges = build_grid(profile, cell_size)
    z_edges = build_z_edges(conditions.depth, extrusion.footprint_depth, cell_size)
    mask = solid_mask(profile, x_edges, y_edges)
    nz, ny, nx = len(z_edges) - 1, len(y_edges) - 1, len(x_edges) - 1

    rows, cols = np.nonzero(mask)
    layers = np.repeat(np.arange(nz), len(rows))
    rows = np.tile(rows, nz)
    cols = np.tile(cols, nz)

    values = _read_onto(solution, x_edges, y_edges, z_edges, layers, rows, cols)

    used = np.zeros((nz + 1, ny + 1, nx + 1), dtype=bool)
    for dk in (0, 1):
        for dj in (0, 1):
            for di in (0, 1):
                used[layers + dk, rows + dj, cols + di] = True
    ids = np.full(used.shape, -1, dtype=np.int64)
    ids[used] = np.arange(int(used.sum()))

    total = np.zeros(used.shape)
    total_flux = np.zeros(used.shape)
    count = np.zeros(used.shape)
    for dk in (0, 1):
        for dj in (0, 1):
            for di in (0, 1):
                index = (layers + dk, rows + dj, cols + di)
                np.add.at(total, index, values[0])
                np.add.at(total_flux, index, values[1])
                np.add.at(count, index, 1.0)
    divisor = np.where(count > 0, count, 1.0)

    zz, yy, xx = np.meshgrid(z_edges, y_edges, x_edges, indexing="ij")
    points = np.column_stack(
        [xx[used].ravel(), yy[used].ravel(), zz[used].ravel()]
    ).astype(float)

    tets = np.empty((len(layers) * 6, 4), dtype=np.int64)
    for which, corners in enumerate(_KUHN):
        for corner, (dk, dj, di) in enumerate(corners):
            tets[which :: len(_KUHN), corner] = ids[layers + dk, rows + dj, cols + di]

    return Lattice(
        points=points,
        tets=tets,
        temperature_c=(total / divisor)[used].ravel(),
        flux=(total_flux / divisor)[used].ravel(),
        bounds=(
            float(x_edges[0]),
            float(y_edges[0]),
            float(z_edges[0]),
            float(x_edges[-1]),
            float(y_edges[-1]),
            float(z_edges[-1]),
        ),
    )


def _read_onto(
    solution: Solution,
    x_edges: np.ndarray,
    y_edges: np.ndarray,
    z_edges: np.ndarray,
    layers: np.ndarray,
    rows: np.ndarray,
    cols: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """The solved cell containing each display cell, by the interval its centre falls in.

    Containment rather than nearest: both grids put a line on every fin edge, so a display
    cell's centre is strictly inside one solved cell and that cell is metal. Nearest-centre
    lookup would have no such guarantee at an interface, and the failure would be a picture with
    a NaN — air — painted on the surface of the metal.
    """
    def locate(display: np.ndarray, solved: np.ndarray) -> np.ndarray:
        centres = 0.5 * (display[:-1] + display[1:])
        return np.clip(
            np.searchsorted(solved, centres, side="right") - 1, 0, len(solved) - 2
        )

    ix = locate(x_edges, solution.x_edges)[cols]
    jy = locate(y_edges, solution.y_edges)[rows]
    kz = locate(z_edges, solution.z_edges)[layers]
    temperature = np.nan_to_num(solution.temperature_c[kz, jy, ix], nan=0.0)
    flux = np.nan_to_num(solution.flux_magnitude[kz, jy, ix], nan=0.0)
    return temperature, flux
