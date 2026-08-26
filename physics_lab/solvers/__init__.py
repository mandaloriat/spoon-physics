"""Lab-specific solver adapters.

Five adapters live here: the airfoil exercise's panel method, the magnetics exercise's
finite-volume magnetostatics, the bridge exercise's direct stiffness method for a pin-jointed
truss, and the heat-sink exercise twice — once on the cross-section and once on the solid body,
which is two capabilities rather than a switch because the *geometry kind* differs and that is
what lets each refuse the other's payload (ADR-023). Each is registered by importing it, and
importing this package is
wired into ``physics_lab.main`` before the app is created, so they appear in
``GET /api/v1/solvers``, in the capability catalogue and in the front-end's solver picker with
no further wiring. The worker needs the same import — see ``physics_lab.worker``, which is why
arq is pointed at that module rather than at ``fenixspoon.worker.WorkerSettings`` directly.

Why a solver of the lab's own, when the point of the first release was to write none
-------------------------------------------------------------------------------------

Because each exercise needs physics Fenix Spoon does not have, and in every case it is the
*metric* that needs it rather than the picture:

* Upstream's potential-flow adapters impose no Kutta condition, so their circulation is zero
  and their integrated lift is exactly zero at every incidence — fine for showing how a body
  deflects a stream, useless for an exercise whose target is a lift. See ADR-014, and the
  upstream issue that records the gap:
  https://github.com/mandaloriat/fenix-spoon/issues/68.
* Upstream's ``mock.magnetostatics2d`` rasterises the material onto a uniform grid, so an
  iron/air interface is a staircase whose steps move with the resolution: a 20.000 mm core
  comes out 20.339 mm wide at one resolution and 20.084 mm at another, and its fixed Jacobi
  sweep count reports no residual to say when it stopped short. Fine for a picture of where
  the flux goes, not for a number. See ADR-018.
* Upstream's elasticity adapters solve a **continuum** — a body filling a region, meshed, with
  a stress field through it. A truss is a graph: an axial force in each bar and nothing in
  between them, and the question a designer asks is *which member*. A continuum solve has no
  members to answer it with, and meshing 50 mm bars over a 24 m span would need cells finer
  than the bars across a thousand times the area. See ADR-019, which also records the geometry
  the protocol turned out not to have.
* Upstream's two conduction adapters declare `no_radiation`, and their own assumption text says
  radiation is "not negligible for a hot surface in still air" — which is the heat sink's
  nominal case. A radiative boundary with a radiosity enclosure and a ``T^4`` nonlinearity is
  physics upstream does not have and does not claim to. That is true of the solid body as well
  as the section, so the third dimension inherited the same reason rather than needing a new
  one. See ADR-023.

Every adapter is split the same way, so that only the last file in each list knows about the
protocol — which is what lets the physics be tested against a closed form, without a job, a
server or an envelope:

* ``panel.py`` — the Hess-Smith method. Arrays in, arrays out, no Fenix Spoon import.
* ``airfoil_geometry.py`` — NACA profiles, and reading chord, incidence and section out of an
  arbitrary outline.
* ``analytic.py`` — the closed-form solutions the answer is checked against.
* ``airfoil.py`` — the exercise: coefficients, sweeps, verification residuals, validity.
* ``airfoil_panel2d.py`` — the ``Solver`` adapter, and nothing else.

* ``magnetics.py`` — the finite-volume method on an interface-fitted grid. Arrays only.
* ``solenoid.py`` — the exercise: flux, leakage, saturation, residuals, validity.
* ``magnetics2d.py`` — the ``Solver`` adapter, and nothing else.

* ``truss.py`` — the direct stiffness method for a bar network. Arrays only.
* ``bridge.py`` — the exercise: utilisation, buckling, mass, residuals, validity.
* ``truss2d.py`` — the ``Solver`` adapter, the load case, and nothing else.

* ``correlations.py`` — convection coefficients from published relations. Arrays and air.
* ``viewfactors.py`` — exact two-dimensional view factors, and the checks on an enclosure.
* ``heatsink.py`` — conduction on the cross-section: the exercise, its metrics and residuals.
* ``heatsink2d.py`` — the ``Solver`` adapter for ``regions2d``, and nothing else.
* ``heatsink_solid.py`` — the same physics on the solid body, reusing the three files above
  unchanged. The only thing it adds is conduction along the extrusion, and the test that says
  so is the extruded limit: with the device covering the whole length and the ends shut it
  reproduces ``heatsink.solve`` to the solver tolerance.
* ``heatsink3d.py`` — the ``Solver`` adapter for ``regions3d``, and nothing else.

Adding another
--------------

An adapter is a class implementing Fenix Spoon's public ``Solver`` contract (see
``docs/start-write-a-solver.md`` in the pinned Fenix Spoon checkout). Nothing about it is
lab-specific — a solver written here could move upstream unchanged, and one written upstream
needs no adaptation to run here::

    # physics_lab/solvers/heat_sink.py
    from fenixspoon.solvers.base import Solver
    from fenixspoon.solvers.registry import register

    @register
    class HeatSink2D(Solver):
        name = "lab.heatsink2d"
        geometry_types = ["regions2d"]
        ...

then add ``from . import heat_sink  # noqa: F401`` below.

Guard a heavy dependency the way Fenix Spoon guards dolfinx — import it in a ``try`` block and
let the adapter be absent rather than the server be broken. The catalogue is what clients read,
so "not installed" is a complete and honest answer. The panel method needs nothing but NumPy,
which is why the airfoil exercise works on the slim image too.

Planned, in rough order: the heat sink, the lightweight bracket, acoustics — each an exercise
page plus, where Fenix Spoon has no solver for it, an adapter here. The bracket is the one that
probably needs none: it is a continuum problem, and upstream's elasticity adapters are what it
asks for.
"""

from . import (  # noqa: F401  - importing registers them
    airfoil_panel2d,
    capacitor_axi2d,
    heatsink2d,
    heatsink3d,
    magnetics2d,
    truss2d,
)

__all__: list[str] = [
    "airfoil_panel2d",
    "capacitor_axi2d",
    "heatsink2d",
    "heatsink3d",
    "magnetics2d",
    "truss2d",
]
