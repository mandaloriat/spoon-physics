"""The capacitive sensor as an *exercise*: a calibration, not a capacitance.

``docs/exercises/capacitive-sensor.md`` §7 and §8. Arrays in, arrays out — the physics is
:mod:`physics_lab.solvers.capacitor` and the protocol is
:mod:`physics_lab.solvers.capacitor_axi2d`; neither is imported here.

**What makes this an exercise rather than a solve.** One configuration gives one capacitance,
and a position sensor is not characterised by one capacitance. What the mirror's controller
runs on is a *curve*: how much the reading moves per micron of gap, over what stroke that
movement stays linear enough to invert, and how much a tilt of the two plates corrupts it. So
the answer here is a sweep with a fit over it, and that is the whole reason the lab writes a
solver where upstream ships an adapter pair that computes the capacitance perfectly well.

**The fit is the published family, on purpose.** The thesis reports

    C(z) = 1 / (-298.8 z^2 + 369.6 z + 0.5)   nF,  z the gap in mm

and that reciprocal-quadratic shape is not a curve-fitter's whim: a parallel plate is exactly
``1/z``, and the fringe field bends it. Fitting ``1/C`` as a quadratic in ``z`` is therefore a
*linear* least squares in the same family the measurement was reduced in, which is what makes
the benchmark a comparison of like with like rather than of two arbitrary interpolants. Every
derivative below is then analytic instead of a difference of noisy solves.

**The tilt is inferred from that curve, and this is §2's hybrid method rather than a shortcut.**
A tilt is not axisymmetric, so it has no meridian section of its own. What the thesis did — and
what failed when tried in full 3-D, at a 90 µm gap where the perturbation cannot be resolved
against discretisation error — was to treat each azimuth as locally axisymmetric with its own
gap ``z0 + gamma R cos(theta)`` and integrate the contribution around the annulus. That
integral is a quadrature over the *same* fitted curve, so a tilt costs no further solves. The
page says it is an inference; it is not presented as a second solve.

**One unit, stated because the source does not.** The thesis's tilt fit,
``C(gamma) = 0.09 gamma^2 + 0.0319 nF``, is in **degrees**: the coefficient recovered from its
own ``C(z)`` fit by the hybrid method is 288 nF/rad², which is 0.088 nF/deg² — 2.5% from the
printed 0.09, where the radian reading would be out by a factor of 3200. The two published
curves are consistent with each other only on the degree reading. Metrics here carry both, and
the one named in the challenge is the one the source used.
"""

from dataclasses import dataclass, field

import numpy as np

from physics_lab.solvers.capacitor import Electrode, Numerics, Solution, solve

#: The thesis's own reduction of its measurements: ``1/C`` in nF⁻¹ against the gap in mm.
PUBLISHED_FIT = (-298.8, 369.6, 0.5)
#: And its tilt fit, ``C = TILT_COEFFICIENT * gamma^2 + C0`` with **gamma in degrees**.
PUBLISHED_TILT_PER_DEG2 = 0.09e-9


@dataclass(frozen=True)
class Conditions:
    """What the sensor is asked to do, and over what range it is characterised."""

    #: Nominal gap, m. The P45 sensor sits at 90 µm.
    gap: float = 90e-6
    #: Excitation, V. The capacitance does not depend on it; the stored energy does.
    voltage: float = 1.0
    #: Half the working stroke, m — the actuator's excursion either side of nominal.
    stroke: float = 50e-6
    #: The tilt the cross-sensitivity is quoted at, in **degrees**.
    tilt_deg: float = 0.1
    #: How far from a straight line the reading may stray before the stroke stops counting as
    #: linear. §7's definition, and the challenge's second target.
    linear_tolerance: float = 0.01

    def __post_init__(self) -> None:
        if self.stroke >= self.gap:
            raise ValueError(
                f"a stroke of ±{self.stroke * 1e6:.0f} µm closes a {self.gap * 1e6:.0f} µm gap: "
                "the plates would touch, which is a collision rather than a measurement"
            )


@dataclass
class Calibration:
    """A swept and fitted sensor: the curve, the numbers read off it, and the checks."""

    gaps: np.ndarray  #: m, the configurations actually solved
    capacitance: np.ndarray  #: F, one per gap, by the energy route
    charge_capacitance: np.ndarray  #: F, the second route
    fit: tuple[float, float, float]  #: 1/C = a z^2 + b z + c, z in mm, C in nF
    metrics: dict[str, float] = field(default_factory=dict)
    residuals: dict[str, float] = field(default_factory=dict)
    nominal: Solution | None = None
    solves: int = 0

    def curve(self, gap: float) -> float:
        """The fitted capacitance at any gap, in farads."""
        a, b, c = self.fit
        z = gap * 1e3
        return 1e-9 / (a * z * z + b * z + c)

    def slope(self, gap: float) -> float:
        """d*C*/d*z* in F/m, analytically from the fit."""
        a, b, c = self.fit
        z = gap * 1e3
        denominator = a * z * z + b * z + c
        return -1e-9 * (2.0 * a * z + b) / denominator**2 * 1e3

    def curvature(self, gap: float) -> float:
        """d²*C*/d*z*² in F/m², analytically. What the tilt coefficient is built from."""
        a, b, c = self.fit
        z = gap * 1e3
        denominator = a * z * z + b * z + c
        first = 2.0 * a * z + b
        return 1e-9 * (2.0 * first**2 / denominator**3 - 2.0 * a / denominator**2) * 1e6


# ────────────────────────────────────────────────────────────────────── the calibration


def sweep_gaps(electrode: Electrode, conditions: Conditions, samples: int) -> np.ndarray:
    """The configurations to solve, spanning everything the answer will be read over.

    Wide enough for both questions at once: the working stroke, and the excursion a tilt
    produces at the rim, ``gamma R``. Reading the tilt off a curve that was only sampled over
    the stroke would be extrapolation dressed as a quadrature — cheap to avoid, since the extra
    span costs a couple of solves.

    The nominal gap is always a sample, exactly. It is where *C*₀ is read, and reading it off
    the fit instead would report a fitted number as a measured one.
    """
    tilt = np.radians(conditions.tilt_deg) * electrode.mean_radius
    reach = max(conditions.stroke, 1.5 * tilt)
    reach = min(reach, 0.9 * conditions.gap)
    half = max(samples // 2, 2)
    below = np.linspace(conditions.gap - reach, conditions.gap, half, endpoint=False)
    above = np.linspace(conditions.gap, conditions.gap + reach, half + 1)
    return np.unique(np.concatenate([below, above]))


def fit_reciprocal(gaps: np.ndarray, capacitance: np.ndarray) -> tuple[float, float, float]:
    """Least squares of ``1/C`` as a quadratic in the gap — the published family.

    Linear in its coefficients, so there is no iteration to converge and no starting guess to
    get wrong. Units are the source's: the gap in millimetres, *C* in nanofarads, which is what
    lets the coefficients be compared with the printed ones digit for digit.
    """
    z = gaps * 1e3
    inverse = 1.0 / (capacitance * 1e9)
    matrix = np.column_stack([z**2, z, np.ones_like(z)])
    coefficients, *_ = np.linalg.lstsq(matrix, inverse, rcond=None)
    return tuple(float(c) for c in coefficients)  # type: ignore[return-value]


def calibrate(
    electrode: Electrode,
    conditions: Conditions | None = None,
    numerics: Numerics | None = None,
    samples: int = 9,
    progress=None,
) -> Calibration:
    """Sweep the gap, fit the curve, and read the seven numbers §7 asks for off it."""
    conditions = conditions or Conditions()
    numerics = numerics or Numerics()
    gaps = sweep_gaps(electrode, conditions, samples)

    solutions = []
    for index, gap in enumerate(gaps, start=1):
        solutions.append(solve(electrode, float(gap), conditions.voltage, numerics))
        if progress is not None:
            progress(index, len(gaps), f"gap {gap * 1e6:.0f} µm")

    capacitance = np.array([s.capacitance_energy for s in solutions])
    charge = np.array([s.capacitance_charge for s in solutions])
    fit = fit_reciprocal(gaps, capacitance)
    nominal = solutions[int(np.argmin(np.abs(gaps - conditions.gap)))]

    calibration = Calibration(
        gaps=gaps,
        capacitance=capacitance,
        charge_capacitance=charge,
        fit=fit,
        nominal=nominal,
        solves=len(gaps),
    )
    calibration.metrics = _metrics(electrode, conditions, calibration, nominal)
    calibration.residuals = _residuals(conditions, calibration, solutions)
    return calibration


def tilted_capacitance(
    calibration: Calibration, electrode: Electrode, gap: float, tilt_deg: float, samples: int = 721
) -> float:
    """§2's hybrid method: each azimuth is locally axisymmetric, and the annulus is integrated.

    A tilt has no meridian section — that is the whole difficulty, and it is why the thesis's
    3-D attempt was abandoned at this gap. What it did instead is this: at azimuth ``theta`` the
    local gap is ``z0 + gamma R cos(theta)``, the contribution there is the axisymmetric answer
    at that gap, and the sensor sees their mean around the ring.

    So a tilt costs no solve of its own. It is an **inference from the swept curve**, and the
    page says so — an inference that is only as good as the curve is wide, which is what
    :func:`sweep_gaps` is careful about.
    """
    theta = np.linspace(0.0, 2.0 * np.pi, samples)
    local = gap + np.radians(tilt_deg) * electrode.mean_radius * np.cos(theta)
    return float(np.trapezoid(np.array([calibration.curve(z) for z in local]), theta) / (2 * np.pi))


def _metrics(
    electrode: Electrode,
    conditions: Conditions,
    calibration: Calibration,
    nominal: Solution,
) -> dict[str, float]:
    gap = conditions.gap
    slope = calibration.slope(gap)
    flat = electrode.parallel_plate(gap)

    tilted = tilted_capacitance(calibration, electrode, gap, conditions.tilt_deg)
    per_deg2 = (tilted - calibration.curve(gap)) / conditions.tilt_deg**2
    per_rad2 = per_deg2 / np.radians(1.0) ** 2

    return {
        "c0": nominal.capacitance_energy,
        "c0_charge": nominal.capacitance_charge,
        "dc_dz": slope,
        "linear_halfstroke": _linear_halfstroke(conditions, calibration),
        "tilt_per_deg2": per_deg2,
        "tilt_per_rad2": per_rad2,
        # The phantom motion a tilt reports: the capacitance it adds, read as a displacement
        # through the sensitivity the controller inverts with. This is the number that decides
        # whether a tilt matters, and it is in metres because that is what it pretends to be.
        "tilt_error": abs(per_deg2 * conditions.tilt_deg**2 / slope) if slope else float("nan"),
        "fringe_excess": nominal.capacitance_energy / flat - 1.0,
        "parallel_plate": flat,
    }


def _linear_halfstroke(conditions: Conditions, calibration: Calibration) -> float:
    """The largest excursion over which a straight line still describes the curve.

    §7's definition, walked outward from the nominal gap rather than solved for: the tangent at
    nominal is the calibration a controller would actually use, and the question is how far it
    can be trusted before the error passes the declared tolerance. Both directions are walked
    and the smaller wins — a stroke is only linear as far as its worse half.
    """
    gap = conditions.gap
    at_nominal = calibration.curve(gap)
    slope = calibration.slope(gap)
    limit = min(conditions.stroke, 0.9 * gap)

    best = limit
    for direction in (-1.0, 1.0):
        for excursion in np.linspace(0.0, limit, 400)[1:]:
            z = gap + direction * excursion
            straight = at_nominal + direction * excursion * slope
            if abs(calibration.curve(z) - straight) / abs(calibration.curve(z)) > (
                conditions.linear_tolerance
            ):
                best = min(best, float(excursion))
                break
    return best


def _residuals(
    conditions: Conditions, calibration: Calibration, solutions: list[Solution]
) -> dict[str, float]:
    """§8, as numbers. Each one says what it measures — see the exercise for what each is worth."""
    published = np.array([_published(gap) for gap in calibration.gaps])
    fitted = np.array([calibration.curve(gap) for gap in calibration.gaps])
    consistency = max(
        abs(a - b) / max(abs(a), 1e-30)
        for a, b in zip(calibration.capacitance, calibration.charge_capacitance, strict=True)
    )
    tilt = calibration.metrics.get("tilt_per_deg2", float("nan"))
    return {
        # The two routes to C. An identity for the converged discrete solution, so this tracks
        # the linear solve rather than the mesh.
        "energy_charge_consistency": float(consistency),
        # How far the fitted family sits from the solved points it was fitted to. Large here
        # means the reciprocal-quadratic shape is the wrong family for this geometry, which
        # would be a finding rather than a bug.
        "fit_residual": float(np.max(np.abs(fitted / calibration.capacitance - 1.0))),
        # The external check: solved points against the published measurement, over the sweep.
        "benchmark": float(np.max(np.abs(calibration.capacitance / published - 1.0))),
        # And the second published curve, which the first one implies through the hybrid method.
        "tilt_benchmark": float(abs(tilt / PUBLISHED_TILT_PER_DEG2 - 1.0)),
        "cg_residual": float(max(s.residual for s in solutions)),
    }


def _published(gap: float) -> float:
    """The thesis's fitted curve, in farads, for a gap in metres."""
    a, b, c = PUBLISHED_FIT
    z = gap * 1e3
    return 1e-9 / (a * z * z + b * z + c)
