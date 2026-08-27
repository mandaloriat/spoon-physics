"""Test fixtures.

Fenix Spoon's own suite already proves the protocol, the job lifecycle, the store and the
solvers — it is a dependency, and re-testing it here would be duplicated maintenance with
no extra coverage. What these tests cover is the seam: that the lab's app really is a
Fenix Spoon app, that the site is served from the same origin as the API, and that the
lab's own additions (``/health``, the maintenance switch) behave.
"""

import tempfile

import pytest


@pytest.fixture
def client(monkeypatch):
    """A TestClient over the lab app, with a throwaway data directory.

    The app is built inside the fixture rather than imported at module scope so each test
    gets a fresh job store, and so environment variables set by a test are read by the
    app that test uses. ``TestClient`` as a context manager runs the lifespan, which is
    what starts the retention sweep and reconciles the store — a solve submitted without
    it would never be reaped.
    """
    from starlette.testclient import TestClient

    with tempfile.TemporaryDirectory() as data_dir:
        monkeypatch.setenv("FENIXSPOON_DATA_DIR", data_dir)
        monkeypatch.setenv("FENIXSPOON_STORE", "sqlite")
        # Keep the suite honest about budgets without making it slow.
        monkeypatch.setenv("FENIXSPOON_MAX_CELLS", "200000")
        monkeypatch.setenv("FENIXSPOON_JOB_TIMEOUT", "90")
        # delenv, not os.environ.pop: pop mutates the real environment and is never
        # undone, so on a runner that sets FENIXSPOON_REDIS_URL the first test to use this
        # fixture would delete it for the rest of the session.
        monkeypatch.delenv("FENIXSPOON_REDIS_URL", raising=False)

        from physics_lab.main import create_app

        with TestClient(create_app()) as test_client:
            yield test_client


@pytest.fixture
def airfoil_geometry():
    """A small, valid ``domain2d`` payload: a blunt wedge in a rectangular domain.

    Deliberately not the page's NACA profile. A test that had to agree with the
    front-end's geometry generator would fail whenever the profile was retuned, which is
    not what any of these tests are about.
    """
    return {
        "type": "domain2d",
        "bounds": [-1.0, -1.0, 2.0, 1.0],
        "obstacle": {
            "type": "polygon2d",
            "points": [[0.0, 0.0], [0.6, 0.08], [1.0, 0.0], [0.6, -0.08]],
        },
    }


@pytest.fixture
def solenoid_geometry():
    """A small, valid ``regions2d`` payload: an iron core between two opposed windings.

    Like ``airfoil_geometry``, deliberately not the page's own cross-section — a test that had
    to agree with the front-end's geometry builder would fail whenever the defaults were
    retuned. What it does share with the page is the shape of the payload: named regions with
    ``mu_r`` and a signed ``current_density`` over an air background, which is the contract the
    magnetostatics solvers read.
    """

    def rect(x0, y0, x1, y1):
        return {
            "type": "polygon2d",
            "points": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
        }

    return {
        "type": "regions2d",
        "bounds": [-0.06, -0.06, 0.06, 0.06],
        "background": {"mu_r": 1.0},
        "regions": [
            {
                "name": "core",
                "shape": rect(-0.008, -0.025, 0.008, 0.025),
                "material": {"mu_r": 800.0},
            },
            {
                "name": "winding_left",
                "shape": rect(-0.024, -0.025, -0.014, 0.025),
                "material": {"current_density": -4.0e6},
            },
            {
                "name": "winding_right",
                "shape": rect(0.014, -0.025, 0.024, 0.025),
                "material": {"current_density": 4.0e6},
            },
        ],
    }


@pytest.fixture
def heatsink3d_geometry():
    """A small, valid ``regions3d`` payload: the space an extrusion may occupy.

    Like the two above, deliberately not the page's own envelope. What it does share with the
    page is the shape of the payload and the *role*: one `box3d` region standing for the site,
    with the profile itself in `params` — the split ADR-019 settled, one coordinate wider.

    The length of the extrusion is the `z` extent of these bounds and is not a parameter
    anywhere. That is protocol 1.17's whole point in one fixture: before it there was nowhere
    on the wire to put this number, so it travelled as a multiplier and no server could refuse
    a solve that ignored it.
    """
    eps = 1e-6
    return {
        "type": "regions3d",
        "bounds": [0.0, 0.0, 0.0, 0.060, 0.030, 0.060],
        "background": {},
        "regions": [
            {
                "name": "envelope",
                "shape": {
                    "type": "box3d",
                    "min": [eps, eps, eps],
                    "max": [0.060 - eps, 0.030 - eps, 0.060 - eps],
                },
                "material": {},
            }
        ],
    }


@pytest.fixture
def sensor_geometry():
    """A valid ``axisymmetric2d`` payload: one annular electrode over the shell's coating.

    The horizontal coordinate is a **radius**, and this section does not reach the axis —
    which is the case upstream's geometry docstring names as the one an adapter must not
    assume away, and it is this sensor that named it. The centreline is 11 mm inboard of
    anything modelled here.

    Deliberately smaller than the page's own envelope, and deliberately a plain chamfered
    hexagon: what it shares with the page is the *shape of the payload* — the electrode as a
    region carrying a `voltage`, the facing plate as the floor of the window — which is the
    only part a test at this level is about.
    """
    inner, outer, thickness = 0.011, 0.0145, 0.004
    chamfer, gap = 0.0015, 90e-6
    top = gap + thickness
    return {
        "type": "axisymmetric2d",
        "bounds": [0.0, 0.0, 0.030, 0.010],
        "background": {"eps_r": 1.0},
        "regions": [
            {
                "name": "electrode",
                "shape": {
                    "type": "polygon2d",
                    "points": [
                        [inner, gap],
                        [outer, gap],
                        [outer, top - chamfer],
                        [outer - chamfer, top],
                        [inner + chamfer, top],
                        [inner, top - chamfer],
                    ],
                },
                "material": {"voltage": 1.0},
            }
        ],
    }
