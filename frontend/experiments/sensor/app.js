/**
 * The capacitive gap sensor — an annular electrode over a mirror, as an exercise.
 *
 * The sixth experiment, and the first whose **answer is a curve**. Every page before this one
 * asks a question a single solve answers: how much lift, which bar gives way, how hot does it
 * get. A position sensor is not characterised by a capacitance — what a controller runs on is
 * how much the reading moves per micron of gap, over what stroke that movement stays linear
 * enough to invert, and how much a tilt of the two plates corrupts it. So one press of
 * *Calibrate* is a sweep of gaps with a fit over it, and the three headline numbers are read
 * off the fit rather than off any one field.
 *
 * That is also why the lab wrote a solver at all when upstream has two adapters for this exact
 * geometry kind. None of the three headline numbers is a reduction of a field, so none can be
 * declared against a single solve. See ADR-026 — and the measurement in it, which is what
 * happened when the upstream mock was tried as the cross-check instead.
 *
 * **The picture is a meridian section, and the page says so in three places.** The horizontal
 * axis is a *radius*, not an x: this is half of a section through a body of revolution, and the
 * whole annulus is it turned through 360°. The workspace draws a plane domain and cannot know
 * the difference, so the page carries the note under the plate, the axis marks in the overlay,
 * and `sensor.sectionNote` in both languages. §6 of the exercise asks for exactly this, and the
 * failure it is guarding against is a visitor reading a slice.
 *
 * **There is no geometry widget**, for the reason ADR-012 gives on the solenoid and more
 * sharply: `<fs-geometry-2d>` edits an outline, and this solver refuses an outline it does not
 * recognise — a chamfer cut on one side only comes back as a refusal rather than as a shape.
 * Four lengths describe the electrode exactly, and a slider for each is both more honest and
 * easier to aim.
 */

import '@fenix-spoon/viewer';

import { solversFor } from '/shared/api.js';
import { describeError, el, health, mountChrome, revealPanel } from '/shared/components.js';
import { drawCurve } from '/shared/curve.js';
import {
  renderChallenge,
  renderCredibilityLights,
  renderKpis,
  renderMetrics,
  renderValidity,
  renderVerification,
  attemptState,
  renderAfterAttempt,
  renderTeacher,
} from '/shared/exercise.js';
import {
  changedTheDesign,
  mountPath,
  mountPrediction,
  renderPredictionRecall,
} from '/shared/journey.js';
import {
  applyFieldView,
  applyMaintenance,
  buildParamForm,
  buildShapeControls,
  renderLesson,
  runSolve,
  setStatusOn,
  showArtifacts,
  showStats,
  syncFieldOptions,
} from '/shared/experiment.js';
import { contentUrl, num, t } from '/shared/i18n.js';
import * as runs from '/shared/runs.js';
import { createWorkspace, marker, polyline, svgNode } from '/shared/workspace.js';

const EXERCISE = 'sensor';
const GEOMETRY_TYPE = 'axisymmetric2d';
/**
 * `capacitive_sensor`, and deliberately not `electrostatics`.
 *
 * Upstream's two electrostatics adapters declare that tag and answer one configuration each.
 * Filtering on it would offer this page a capability that cannot produce a single number in
 * the rail — not a coarser answer, a different question. The same trap the magnetics page fell
 * into with `mock.heat2d`, avoided the same way: the adapter carries its own tag.
 */
const PHYSICS = 'capacitive_sensor';

const dom = Object.fromEntries(
  [
    'lesson',
    'viewer',
    'workspace',
    'sectionNote',
    'status',
    'dot',
    'progress',
    'run',
    'cancel',
    'reset',
    'keep',
    'compareJump',
    'solver',
    'solverHint',
    'designControls',
    'designNote',
    'shapeControls',
    'dutyControls',
    'numerical',
    'derivedToggle',
    'derivedWrap',
    'derived',
    'field',
    'fieldHint',
    'challenge',
    'kpis',
    'metrics',
    'verification',
    'validity',
    'stats',
    'artifacts',
    'results',
    'calibrationCurve',
    'calibrationNote',
    'tiltCurve',
    'tiltMetrics',
    'runsPanel',
    'runsTable',
    'runsNote',
    'compare',
    'exportCsv',
    'exportJson',
    'clearRuns',
    'maintenance',
    'path',
    'prediction',
    'predictionRecall',
    'outcome',
    'hint',
    'credibility',
    'credibilityLights',
    'readingHint',
    'modelDetails',
    'explain',
    'teacher',
    'whyPanel',
    'predictPanel',
    'teacherCard',
    'missionWhy',
    'missionWhyToggle',
  ].map((key) => [
    key,
    document.getElementById(key.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)),
  ]),
);

/* ------------------------------------------------------------------ the sensor */

/**
 * The P45 unit as built, and it **misses one of the three targets**.
 *
 * 11 to 14.5 mm of annulus at 90 µm, which calibrates at −0.317 nF/mm over a linear
 * half-stroke of 9.6 µm — against a target of 10. Close enough that the exercise is a design
 * problem rather than a wall, and the lever that fixes it (open the gap) costs sensitivity,
 * which is the other target. That trade is the challenge.
 *
 * The two radii are the corrected ones. The thesis's table has them transposed — "raggio
 * interno 14.5 mm, raggio esterno 11 mm" — and the page says so in the lesson rather than
 * quietly disagreeing with its own source.
 */
const SHAPE_DEFAULTS = {
  gap: 90,
  innerRadius: 11,
  outerRadius: 14.5,
  thickness: 4,
  chamferWidth: 1.5,
  chamferHeight: 1.5,
  voltage: 1,
  stroke: 50,
  tilt: 0.1,
};

const shape = { ...SHAPE_DEFAULTS };

/** Micrometres on the page for the gap and the stroke, millimetres for everything with a radius. */
const um = (value) => value / 1e6;
const mm = (value) => value / 1e3;

/** The three that change the answer most, and the reason the exercise is a trade. */
const DESIGN_CONTROLS = [
  {
    key: 'gap',
    label: t('sensor.design.gap'),
    min: 40,
    max: 200,
    step: 1,
    unit: ' µm',
    title: t('sensor.design.gapTitle'),
  },
  {
    key: 'outerRadius',
    label: t('sensor.design.outerRadius'),
    min: 8,
    max: 25,
    step: 0.1,
    unit: ' mm',
    title: t('sensor.design.outerRadiusTitle'),
  },
  {
    key: 'chamferWidth',
    label: t('sensor.design.chamferWidth'),
    min: 0,
    max: 3,
    step: 0.1,
    unit: ' mm',
    title: t('sensor.design.chamferWidthTitle'),
  },
];

const SHAPE_CONTROLS = [
  {
    key: 'innerRadius',
    label: t('sensor.design.innerRadius'),
    min: 5,
    max: 20,
    step: 0.1,
    unit: ' mm',
    title: t('sensor.design.innerRadiusTitle'),
  },
  {
    key: 'thickness',
    label: t('sensor.design.thickness'),
    min: 1,
    max: 10,
    step: 0.5,
    unit: ' mm',
    title: t('sensor.design.thicknessTitle'),
  },
  {
    key: 'chamferHeight',
    label: t('sensor.design.chamferHeight'),
    min: 0,
    max: 3,
    step: 0.1,
    unit: ' mm',
    title: t('sensor.design.chamferHeightTitle'),
  },
];

const DUTY_CONTROLS = [
  {
    key: 'stroke',
    label: t('sensor.design.stroke'),
    min: 5,
    max: 150,
    step: 5,
    unit: ' µm',
    title: t('sensor.design.strokeTitle'),
  },
  {
    key: 'tilt',
    label: t('sensor.design.tilt'),
    min: 0.02,
    max: 1,
    step: 0.01,
    unit: '°',
    title: t('sensor.design.tiltTitle'),
  },
  {
    key: 'voltage',
    label: t('sensor.design.voltage'),
    min: 1,
    max: 20,
    step: 1,
    unit: ' V',
    title: t('sensor.design.voltageTitle'),
  },
];

/* ------------------------------------------------------------------ the geometry */

/**
 * Whether the four lengths describe an annulus at all.
 *
 * Two ways they can fail, and both are reachable by dragging one slider: the outer radius can
 * fall below the inner one, and two chamfers of 1.5 mm can meet in the middle of a 2 mm-wide
 * annulus. The solver refuses either — correctly — and the page would rather say so on the
 * control than spend a job learning it.
 */
function shapeProblem() {
  const width = shape.outerRadius - shape.innerRadius;
  if (width <= 0.2) return t('sensor.invalid.radii');
  if (2 * shape.chamferWidth >= width) return t('sensor.invalid.chamfers');
  if (shape.chamferHeight >= shape.thickness) return t('sensor.invalid.tooDeep');
  return null;
}

/**
 * The meridian section, as `axisymmetric2d`.
 *
 * Three things about this payload are worth knowing, and each is a decision rather than a
 * detail.
 *
 * **The floor of the window is the shell's coating.** It carries no region of its own: a gold
 * film a micron thick has no meridian section a grid could resolve, and the solver's convention
 * is that the bottom edge is the facing plate held at zero. (It *accepts* one drawn as a
 * grounded region, which is what lets the same payload go to upstream's adapters — see
 * ADR-026 — but the page has no reason to draw one.)
 *
 * **The window reaches well past the electrode**, because the answer is a fringe field and the
 * fringe does not stop at the metal. How far is a numerical setting (`truncation`), and the
 * geometry only has to be wide enough not to clip what that setting asks for.
 *
 * **A zero chamfer is a rectangle, not a hexagon with coincident corners.** `polygon2d` refuses
 * duplicate consecutive points, which is the right refusal — so the two cases are two outlines
 * rather than one with a parameter at zero.
 */
function buildGeometry() {
  const inner = mm(shape.innerRadius);
  const outer = mm(shape.outerRadius);
  const chamferW = mm(shape.chamferWidth);
  const chamferH = mm(shape.chamferHeight);
  const gap = um(shape.gap);
  const top = gap + mm(shape.thickness);

  const outline =
    chamferW <= 0 || chamferH <= 0
      ? [
          [inner, gap],
          [outer, gap],
          [outer, top],
          [inner, top],
        ]
      : [
          [inner, gap],
          [outer, gap],
          [outer, top - chamferH],
          [outer - chamferW, top],
          [inner + chamferW, top],
          [inner, top - chamferH],
        ];

  // Room for the far field on both sides, and never a negative radius: `axisymmetric2d`
  // refuses one, and it is right to — the first coordinate is a radius, and a payload with a
  // negative one is a plane section that has been mislabelled.
  const reach = 4 * (outer - inner);
  return {
    type: 'axisymmetric2d',
    bounds: [Math.max(0, inner - reach), 0, outer + reach, top + reach],
    background: { eps_r: 1.0 },
    regions: [
      {
        name: 'electrode',
        shape: { type: 'polygon2d', points: outline },
        material: { voltage: shape.voltage },
      },
    ],
  };
}

function currentParams(extra = {}) {
  return {
    voltage: shape.voltage,
    stroke: um(shape.stroke),
    tilt: shape.tilt,
    ...forms.numerical,
    ...extra,
  };
}

/* ------------------------------------------------------------------ derived values */

/** ε₀ π (r_o² − r_i²) / d, in farads: the sensor with no fringe field at all. */
function parallelPlate() {
  const EPS0 = 8.8541878128e-12;
  const area = Math.PI * (mm(shape.outerRadius) ** 2 - mm(shape.innerRadius) ** 2);
  return (EPS0 * area) / um(shape.gap);
}

/** How far the rim moves for the quoted tilt: the excursion the inference is read over. */
function tiltReach() {
  const meanRadius = mm(0.5 * (shape.innerRadius + shape.outerRadius));
  return ((shape.tilt * Math.PI) / 180) * meanRadius;
}

function entry(label, value) {
  return [el('dt', { text: label }), el('dd', { class: 'num', text: value })];
}

function renderDerived() {
  const width = shape.outerRadius - shape.innerRadius;
  dom.derived.replaceChildren(
    ...entry(t('sensor.derived.width'), `${num(width, { maximumFractionDigits: 2 })} mm`),
    ...entry(
      t('sensor.derived.area'),
      `${num(1e6 * Math.PI * (mm(shape.outerRadius) ** 2 - mm(shape.innerRadius) ** 2), {
        maximumFractionDigits: 1,
      })} mm²`,
    ),
    ...entry(
      t('sensor.derived.plate'),
      `${num(1e9 * parallelPlate(), { maximumFractionDigits: 5 })} nF`,
    ),
    ...entry(t('sensor.derived.aspect'), `${Math.round(mm(width) / um(shape.gap))} : 1`),
    ...entry(
      t('sensor.derived.tiltReach'),
      `${num(1e6 * tiltReach(), { maximumFractionDigits: 1 })} µm`,
    ),
  );
}

function applyShape() {
  const problem = shapeProblem();
  dom.designNote.textContent = problem ?? t('sensor.designNote');
  dom.designNote.classList.toggle('is-warning', Boolean(problem));
  dom.run.disabled = Boolean(problem) || running || !solver();
  renderDerived();
  workspace?.draw();
}

/* ------------------------------------------------------------------ what is reported */

const PARAM_UI = [
  { name: 'samples', label: t('sensor.params.samples'), group: 'numerical' },
  { name: 'cell_size', label: t('sensor.params.cellSize'), group: 'numerical' },
  { name: 'truncation', label: t('sensor.params.truncation'), group: 'numerical' },
  { name: 'linear_tolerance', label: t('sensor.params.linearTolerance'), group: 'numerical' },
  { name: 'convergence_check', label: t('sensor.params.convergenceCheck'), group: 'numerical' },
];

/**
 * Every declared metric, in the order §7 lists them, with the two units the tilt is quoted in
 * kept side by side.
 *
 * The four `_rel` checks are deliberately *not* here: they are verification, they have their
 * own panel, and a residual in the answers table reads as an answer.
 */
const METRICS = [
  {
    key: 'capacitance',
    label: t('sensor.metrics.c0'),
    unit: 'nF',
    digits: 5,
    from: (found) => scale(found, 'capacitance', 1e9),
    goal: t('sensor.goal.published'),
  },
  {
    key: 'dC_dz',
    label: t('sensor.metrics.sensitivity'),
    unit: 'nF/mm',
    digits: 4,
    from: (found) => scale(found, 'dC_dz', 1e6),
    goal: t('sensor.goal.sensitivity'),
  },
  {
    key: 'linear_halfstroke',
    label: t('sensor.metrics.halfstroke'),
    unit: 'µm',
    digits: 2,
    from: (found) => scale(found, 'linear_halfstroke', 1e6),
    goal: t('sensor.goal.halfstroke'),
  },
  {
    key: 'tilt_per_deg2',
    label: t('sensor.metrics.tiltDeg'),
    unit: 'nF/deg²',
    digits: 4,
    from: (found) => scale(found, 'tilt_per_deg2', 1e9),
    goal: t('sensor.goal.tilt'),
  },
  {
    key: 'tilt_per_rad2',
    label: t('sensor.metrics.tiltRad'),
    unit: 'nF/rad²',
    digits: 1,
    from: (found) => scale(found, 'tilt_per_rad2', 1e9),
  },
  {
    key: 'tilt_error',
    label: t('sensor.metrics.tiltError'),
    unit: 'µm',
    digits: 3,
    from: (found) => scale(found, 'tilt_error', 1e6),
  },
  {
    key: 'fringe_excess',
    label: t('sensor.metrics.fringe'),
    unit: '1',
    digits: 3,
    goal: t('sensor.goal.fringe'),
  },
  {
    key: 'parallel_plate',
    label: t('sensor.metrics.plate'),
    unit: 'nF',
    digits: 5,
    from: (found) => scale(found, 'parallel_plate', 1e9),
  },
  {
    key: 'capacitance_charge',
    label: t('sensor.metrics.charge'),
    unit: 'nF',
    digits: 5,
    from: (found) => scale(found, 'capacitance_charge', 1e9),
  },
  {
    key: 'energy',
    label: t('sensor.metrics.energy'),
    // Picojoules, because sixteen picojoules written in joules is `0.000000000016` and a
    // reader counts zeroes instead of reading a number. Farads get the same treatment above.
    unit: 'pJ',
    digits: 4,
    from: (found) => scale(found, 'energy', 1e12),
  },
  {
    key: 'e_max',
    label: t('sensor.metrics.eMax'),
    unit: 'V/m',
    digits: 0,
    // Not converged, and it never will be: it climbs with every refinement, because the
    // electrode's rim is a right angle and a right angle has an unbounded field in the
    // continuum. `hint` is the row's tooltip, which is where a caveat about a number belongs
    // — beside it, rather than only in the solver catalogue nobody reading this will open.
    hint: t('sensor.metrics.eMaxNote'),
  },
];

const METRIC_LABELS = Object.fromEntries(METRICS.map((metric) => [metric.key, metric]));

/**
 * Farads and metres on the wire, nanofarads and microns on the page.
 *
 * Converted here and in exactly one place, because the alternative — a solver that reported
 * nanofarads — would make the envelope disagree with every other capability in the catalogue.
 * SI on the wire is not a preference; it is what lets two solvers be compared at all.
 */
function scale(found, key, factor) {
  const value = found.metrics?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? factor * value : null;
}

const KPIS = [
  {
    key: 'dC_dz',
    label: t('sensor.headline.sensitivity'),
    symbol: 'dC/dz',
    unit: 'nF/mm',
    plainUnit: 'nF/mm',
    digits: 3,
    from: (found) => scale(found, 'dC_dz', 1e6),
    goal: { value: 0.3, comparator: '>', absolute: true },
    hint: t('sensor.headline.sensitivityHint'),
  },
  {
    key: 'linear_halfstroke',
    label: t('sensor.headline.halfstroke'),
    symbol: 'w_lin',
    unit: 'µm',
    plainUnit: 'µm',
    digits: 1,
    from: (found) => scale(found, 'linear_halfstroke', 1e6),
    goal: { value: 10, comparator: '>' },
    hint: t('sensor.headline.halfstrokeHint'),
  },
  {
    key: 'tilt_error',
    label: t('sensor.headline.tiltError'),
    symbol: 'δz_γ',
    unit: 'µm',
    plainUnit: 'µm',
    digits: 2,
    from: (found) => scale(found, 'tilt_error', 1e6),
    // No goal, and shown beside two that have one. It is the number the exercise exists to
    // surprise with: a tenth of a degree reports microns of motion the mirror never made,
    // which is the same order as the stroke being measured.
    note: () => t('sensor.headline.tiltErrorNote'),
    hint: t('sensor.headline.tiltErrorHint'),
  },
];

/**
 * §8's four rows, each with the tolerance this *page* considers verified.
 *
 * All four arrive in the result envelope as declared metrics — this exercise writes no
 * `report.json` at all, which is the direction ADR-015 records. The tolerances are stated here
 * rather than by the solver, because what counts as verified is a claim about the exercise.
 */
const CHECKS = [
  {
    key: 'energy_charge_consistency_rel',
    tolerance: 'energy_charge_consistency_tol',
    label: t('sensor.checks.consistency'),
    describe: t('sensor.checks.consistencyTitle'),
  },
  {
    key: 'benchmark_rel',
    tolerance: 'benchmark_tol',
    label: t('sensor.checks.benchmark'),
    describe: t('sensor.checks.benchmarkTitle'),
  },
  {
    key: 'tilt_benchmark_rel',
    tolerance: 'tilt_benchmark_tol',
    label: t('sensor.checks.tiltBenchmark'),
    describe: t('sensor.checks.tiltBenchmarkTitle'),
  },
  {
    key: 'fit_residual_rel',
    tolerance: 'fit_residual_tol',
    label: t('sensor.checks.fit'),
    describe: t('sensor.checks.fitTitle'),
  },
];

const FIELD_VIEW = {
  V: {
    label: t('sensor.fields.potential'),
    units: 'V',
    colormap: 'viridis',
    hint: t('sensor.fields.potentialHint'),
  },
  E: {
    label: t('sensor.fields.field'),
    units: 'V/m',
    colormap: 'inferno',
    hint: t('sensor.fields.fieldHint'),
  },
};

/* --------------------------------------------------------------------- the state */

const forms = { numerical: {} };
let catalogue = { all: [], byMode: {} };
let report = null;
let running = false;
let currentJob = null;
let workspace = null;
let content = null;
/** The two curves the last calibration produced, by name. */
let curves = {};
let selected = new Set();

function solver() {
  return catalogue.all.find((entry) => entry.name.startsWith('lab.capacitor')) ?? null;
}

/**
 * The page's view over the result envelope.
 *
 * Nothing is fetched a second time: every number below arrived with the field. The benchmark's
 * expected size deserves a word — 6% rather than 1%, because the geometry on the page is the
 * visitor's and the measurement is of one particular sensor. Moving the chamfer *should* move
 * the run away from the benchmark, and a tolerance that called that a failure would be
 * punishing the exercise for working.
 */
function buildReport(result) {
  const diagnostics = result.diagnostics ?? {};
  const metrics = result.metrics ?? {};
  return {
    metrics,
    verification: {
      energy_charge_consistency_rel: metrics.energy_charge_consistency_rel ?? null,
      energy_charge_consistency_tol: 0.01,
      benchmark_rel: metrics.benchmark_rel ?? null,
      benchmark_tol: 0.06,
      tilt_benchmark_rel: metrics.tilt_benchmark_rel ?? null,
      tilt_benchmark_tol: 0.1,
      fit_residual_rel: metrics.fit_residual_rel ?? null,
      fit_residual_tol: 0.02,
    },
    validity: { warnings: diagnostics.warnings ?? [] },
    stats: result.stats ?? {},
    converged: diagnostics.converged ?? null,
  };
}

async function run() {
  if (running) return;
  const chosen = solver();
  if (!chosen) {
    setStatusOn(dom, t('sensor.noSolver'), 'error');
    return;
  }

  running = true;
  dom.artifacts.replaceChildren();

  try {
    const result = await runSolve({
      dom,
      solver: chosen.name,
      geometry: buildGeometry(),
      params: currentParams(),
      onJob: (job) => {
        currentJob = job;
      },
    });
    if (!result) return;

    const first = report === null;
    report = buildReport(result);
    curves = Object.fromEntries((result.series ?? []).map((entry) => [entry.name, entry]));
    dom.results.hidden = false;
    workspace.setResult(result);
    if (first) workspace.fit();
    syncFieldOptions(dom.viewer, dom.field, FIELD_VIEW, dom.fieldHint);
    showStats(dom.stats, result);
    showArtifacts(dom.artifacts, result.artifacts);
    declareOverlays();
    present();
    setStatusOn(dom, t('experiment.done'), 'done');
  } finally {
    running = false;
    currentJob = null;
    dom.keep.disabled = report === null;
    applyShape();
  }
}

/* --------------------------------------------------------------- presenting a result */

function present() {
  renderChallenge(dom.challenge, content?.challenge, report, METRIC_LABELS);
  renderKpis(dom.kpis, KPIS, report);
  dom.readingHint.hidden = report !== null;
  renderCredibilityLights(dom.credibilityLights, content?.challenge, report, {
    checks: CHECKS,
    onOpen: () => openDrawer('checks-panel'),
  });
  renderMetrics(dom.metrics, METRICS, report);
  renderVerification(dom.verification, CHECKS, report);
  renderValidity(dom.validity, report);
  renderAfterAttempt(dom, {
    challenge: content?.challenge,
    explain: content?.explain,
    report,
    state: attemptState(content?.challenge, report),
    checks: CHECKS,
    hint: report ? suggestion() : null,
    facts: attemptFacts(),
  });
  renderPredictionRecall(dom.predictionRecall, prediction?.answer() ?? null);
  if (report) path.mark('attempt');

  drawCalibration();
  drawTilt();
}

/** The trace named `name` in the series named `series`, as [x, y] pairs. */
function pairs(series, name, xScale = 1, yScale = 1) {
  const curve = curves[series];
  const xs = curve?.x?.values ?? [];
  const ys = curve?.traces?.find((trace) => trace.name === name)?.values ?? [];
  if (!xs.length || xs.length !== ys.length) return [];
  return xs.map((x, index) => [xScale * x, yScale * ys[index]]);
}

/**
 * §8's benchmark row, drawn: the solve against the measurement, over the whole sweep.
 *
 * Three traces rather than two, and the third is the argument. The parallel plate is what the
 * sensor would be with no fringe field, and it sits visibly *below* the other two everywhere —
 * so the 16% excess the exercise is about is a gap on the page rather than a number in a table.
 *
 * The series carries a fourth — the fitted curve — and the page deliberately does not draw it.
 * It agrees with the solved points to two parts in a thousand, so it would be a line lying on
 * top of another line, and how far the two differ has a number of its own in the checks panel.
 * It stays in the envelope because a CSV export is a different reader with a different question.
 */
function drawCalibration() {
  if (!curves.calibration) {
    dom.calibrationNote.textContent = t('sensor.calibrationIdle');
    dom.calibrationCurve.replaceChildren();
    return;
  }

  drawCurve(dom.calibrationCurve, {
    traces: [
      { name: t('sensor.plots.solved'), points: pairs('calibration', 'solved', 1e6, 1e9) },
      { name: t('sensor.plots.published'), points: pairs('calibration', 'published', 1e6, 1e9) },
      { name: t('sensor.plots.plate'), points: pairs('calibration', 'parallel_plate', 1e6, 1e9) },
    ],
    xLabel: t('sensor.plots.gap'),
    yLabel: t('sensor.plots.capacitance'),
    marks: [{ x: shape.gap, label: t('sensor.plots.nominal') }],
  });

  const benchmark = report?.verification?.benchmark_rel;
  dom.calibrationNote.textContent = Number.isFinite(benchmark)
    ? t('sensor.calibrationNote', { percent: num(100 * benchmark, { maximumFractionDigits: 1 }) })
    : t('sensor.calibrationIdle');
}

/** The inference, drawn beside the curve it was inferred from — and labelled as one. */
function drawTilt() {
  if (!curves.tilt) {
    dom.tiltCurve.replaceChildren();
    dom.tiltMetrics.replaceChildren();
    return;
  }

  drawCurve(dom.tiltCurve, {
    traces: [
      { name: t('sensor.plots.inferred'), points: pairs('tilt', 'inferred', 1, 1e9) },
      { name: t('sensor.plots.published'), points: pairs('tilt', 'published', 1, 1e9) },
    ],
    xLabel: t('sensor.plots.tilt'),
    yLabel: t('sensor.plots.capacitance'),
    marks: [{ x: shape.tilt, label: t('sensor.plots.quoted') }],
  });

  const perDeg = scale(report ?? {}, 'tilt_per_deg2', 1e9);
  const error = scale(report ?? {}, 'tilt_error', 1e6);
  dom.tiltMetrics.replaceChildren(
    ...entry(
      t('sensor.metrics.tiltDeg'),
      perDeg === null ? '—' : `${num(perDeg, { maximumFractionDigits: 4 })} nF/deg²`,
    ),
    ...entry(t('sensor.derived.published'), '0.09 nF/deg²'),
    ...entry(
      t('sensor.metrics.tiltError'),
      error === null ? '—' : `${num(error, { maximumFractionDigits: 2 })} µm`,
    ),
    ...entry(
      t('sensor.derived.tiltReach'),
      `${num(1e6 * tiltReach(), { maximumFractionDigits: 1 })} µm`,
    ),
  );
}

/* --------------------------------------------------------------- the annotation layer */

/**
 * What the overlay is for here, and it is not decoration.
 *
 * §6 says the axis must be labelled *r* or the page teaches the wrong picture. The workspace
 * draws a plane domain and has no way to know this one is a meridian section, so the labels are
 * the page's to draw — the centreline the section is measured from, the electrode's outline,
 * and the gap that every number on the page depends on and that is far too thin to see at the
 * window's scale.
 */
function declareOverlays() {
  const noRun = t('workspace.noRun');
  workspace.setOverlays([
    { id: 'axes', label: t('sensor.overlays.axes'), colour: 'var(--overlay-chord)', on: true },
    {
      id: 'electrode',
      label: t('sensor.overlays.electrode'),
      colour: 'var(--core)',
      on: true,
      title: t('sensor.overlays.electrodeTitle'),
    },
    {
      id: 'gap',
      label: t('sensor.overlays.gap'),
      colour: 'var(--overlay-peak)',
      on: true,
      enabled: Boolean(report),
      why: noRun,
      title: t('sensor.overlays.gapTitle'),
    },
  ]);
}

function drawOverlay({ svg, project, layerOn, bounds }) {
  const [rmin, zmin, rmax, zmax] = bounds;

  if (layerOn('axes')) {
    const group = svgNode('g', { class: 'overlay__chord' });
    // The floor: the shell's coating, which is the other plate and carries no region.
    group.append(polyline([project([rmin, zmin]), project([rmax, zmin])], 'overlay__chordline'));
    group.append(marker(project([rmax, zmin]), t('sensor.overlays.shell'), 'overlay__cp'));
    // And the radius the horizontal axis actually is. The centreline is usually off-screen —
    // an annular electrode has no reason to model it — so the label goes on the axis itself.
    group.append(
      marker(
        project([rmin + 0.06 * (rmax - rmin), zmin + 0.9 * (zmax - zmin)]),
        'r →',
        'overlay__chord',
      ),
    );
    svg.append(group);
  }

  if (layerOn('electrode')) {
    const outline = buildGeometry().regions[0].shape.points;
    const ring = [...outline, outline[0]].map(project);
    svg.append(
      svgNode(
        'g',
        { class: 'overlay__regions' },
        polyline(ring, 'overlay__region overlay__region--core'),
      ),
    );
  }

  if (layerOn('gap') && report) {
    // Two ticks either side of the gap, because at this window's scale the gap is a hairline
    // and a visitor cannot otherwise see where the answer comes from.
    const inner = mm(shape.innerRadius);
    const outer = mm(shape.outerRadius);
    const gap = um(shape.gap);
    const group = svgNode('g', { class: 'overlay__plane' });
    group.append(polyline([project([inner, gap]), project([outer, gap])], 'overlay__planeline'));
    group.append(
      marker(
        project([outer, gap]),
        t('sensor.overlays.gapMark', { gap: shape.gap }),
        'overlay__peak',
      ),
    );
    svg.append(group);
  }
}

/* ------------------------------------------------------------------- the run table */

const COLUMNS = [
  { path: 'geometry.label', label: t('sensor.columns.sensor') },
  { path: 'metrics.capacitance', label: 'C₀ F' },
  { path: 'metrics.dC_dz', label: 'dC/dz F/m' },
  { path: 'metrics.linear_halfstroke', label: t('sensor.columns.halfstroke') },
  { path: 'metrics.tilt_per_deg2', label: 'c_γ F/deg²' },
  { path: 'metrics.tilt_error', label: t('sensor.columns.tiltError') },
  { path: 'metrics.fringe_excess', label: t('sensor.columns.fringe') },
  { path: 'verification.benchmark_rel', label: t('sensor.columns.benchmark') },
  { path: 'verification.energy_charge_consistency_rel', label: t('sensor.columns.consistency') },
];

function describeSensor() {
  return t('sensor.shapeLabel', {
    inner: num(shape.innerRadius, { maximumFractionDigits: 1 }),
    outer: num(shape.outerRadius, { maximumFractionDigits: 1 }),
    gap: Math.round(shape.gap),
    chamfer: num(shape.chamferWidth, { maximumFractionDigits: 1 }),
  });
}

/**
 * One row: every input, the answer, the residuals, the warnings. The contract's §5.
 *
 * **SI throughout, and deliberately not the page's units.** The rail reads nanofarads and
 * microns because that is what a person compares; a row is compared by a spreadsheet, and a
 * column that changed unit when the page's wording did would be worthless. The conversions on
 * this page live in `scale` and nowhere else, and this function is on the other side of them.
 */
function row() {
  return {
    exercise: { id: EXERCISE, version: '1.0.0' },
    solver: { name: solver()?.name ?? null, version: solver()?.version ?? null },
    geometry: {
      source: 'parametric',
      label: describeSensor(),
      inner_radius_m: mm(shape.innerRadius),
      outer_radius_m: mm(shape.outerRadius),
      thickness_m: mm(shape.thickness),
      chamfer_width_m: mm(shape.chamferWidth),
      chamfer_height_m: mm(shape.chamferHeight),
      gap_m: um(shape.gap),
    },
    physical: {
      voltage_v: shape.voltage,
      stroke_m: um(shape.stroke),
      // Degrees, and named as such. The metric is reported in both units; a row that carried
      // a bare `tilt` would be the very ambiguity this exercise had to resolve in its source.
      tilt_deg: shape.tilt,
      tilt_rad: (shape.tilt * Math.PI) / 180,
      parallel_plate_f: parallelPlate(),
    },
    numerics: { ...forms.numerical },
    metrics: report?.metrics ?? {},
    verification: report?.verification ?? {},
    validity: report?.validity ?? {},
    cost: report?.stats ?? {},
  };
}

function refreshRuns(rows = runs.load(EXERCISE), evicted = 0) {
  selected = new Set([...selected].filter((key) => rows.some((entry) => entry.saved_at === key)));
  runs.renderTable(dom.runsTable, rows, {
    columns: COLUMNS,
    selected,
    onSelect: (savedAt, on) => {
      if (on) selected.add(savedAt);
      else selected.delete(savedAt);
      refreshRuns(rows);
    },
    onDelete: (savedAt) => refreshRuns(runs.remove(EXERCISE, savedAt)),
  });
  runs.renderComparison(
    dom.compare,
    rows.filter((entry) => selected.has(entry.saved_at)),
    { labels: METRIC_LABELS },
  );

  const parts = [t('experiment.kept', { count: rows.length, capacity: runs.CAPACITY })];
  if (evicted) parts.push(t('experiment.evicted', { count: evicted }));
  dom.runsNote.textContent = parts.join(' ');
  for (const button of [dom.exportCsv, dom.exportJson, dom.clearRuns])
    button.disabled = !rows.length;
  dom.compareJump.hidden = rows.length < 2;
  if (selected.size >= 2) path.mark('compare');
  if (!rows.length) dom.runsNote.textContent = t('runs.none');
  else if (rows.length === 1) dom.runsNote.textContent += ` ${t('runs.one')}`;
}

/* ------------------------------------------------------------------- after an attempt */

/**
 * One sentence about what to try next, and it names the trade rather than the fix.
 *
 * The order matters: sensitivity first, because a design that has lost it has lost the thing
 * the sensor is for, and the stroke is the target a visitor is most tempted to buy at its
 * expense.
 */
function suggestion() {
  const slope = Math.abs(scale(report, 'dC_dz', 1e6) ?? 0);
  const stroke = scale(report, 'linear_halfstroke', 1e6) ?? 0;
  const fringe = report?.metrics?.fringe_excess ?? 0;

  if (slope < 0.3) return t('sensor.hint.insensitive');
  if (stroke < 10)
    return t('sensor.hint.short', { short: num(10 - stroke, { maximumFractionDigits: 1 }) });
  if (fringe > 0.25) return t('sensor.hint.fringe');
  return null;
}

function attemptFacts() {
  if (!report) return {};
  return {
    sensitivity: num(Math.abs(scale(report, 'dC_dz', 1e6) ?? 0), { maximumFractionDigits: 3 }),
    stroke: num(scale(report, 'linear_halfstroke', 1e6) ?? 0, { maximumFractionDigits: 1 }),
    tiltError: num(scale(report, 'tilt_error', 1e6) ?? 0, { maximumFractionDigits: 2 }),
    gap: Math.round(shape.gap),
  };
}

/* ------------------------------------------------------------------------ wiring */

mountChrome(EXERCISE);
workspace = createWorkspace({
  root: dom.workspace,
  viewer: dom.viewer,
  editor: null,
  fitLabel: t('sensor.fitSection'),
  exportName: 'sensor-field',
  // The electrode and its gap, which is a small part of a window sized for the far field.
  // Framing the whole domain would frame mostly air — and the fringe field, which is the
  // answer, lives within an annulus width of the metal.
  subject: () => {
    const inner = mm(shape.innerRadius);
    const outer = mm(shape.outerRadius);
    const pad = 0.6 * (outer - inner);
    return [inner - pad, 0, outer + pad, mm(shape.thickness) + pad];
  },
  onDraw: drawOverlay,
});

const path = mountPath(dom.path, { exercise: EXERCISE });
let prediction = null;

function mountLoop() {
  if (content?.prediction) {
    prediction = mountPrediction(dom.prediction, {
      exercise: EXERCISE,
      prediction: content.prediction,
      hasSolved: () => Boolean(report),
      onAnswer: () => path.mark('predict'),
    });
  } else {
    dom.predictPanel?.remove();
  }
  renderTeacher(dom.teacher, content?.teacher);
  if (!content?.teacher) dom.teacherCard?.remove();
}

function buildControls() {
  buildShapeControls(dom.designControls, DESIGN_CONTROLS, shape, applyShape);
  buildShapeControls(dom.shapeControls, SHAPE_CONTROLS, shape, applyShape);
  buildShapeControls(dom.dutyControls, DUTY_CONTROLS, shape, applyShape);
}

function buildForms() {
  const chosen = solver();
  if (!chosen) return;
  forms.numerical = buildParamForm(dom.numerical, chosen, PARAM_UI, forms.numerical);
}

function setMissionDrawer(open) {
  dom.missionWhy.hidden = !open;
  dom.missionWhyToggle.setAttribute('aria-expanded', String(open));
}
dom.missionWhyToggle.addEventListener('click', () => setMissionDrawer(dom.missionWhy.hidden));

dom.run.addEventListener('click', run);
dom.cancel.addEventListener('click', () => currentJob?.cancel());
dom.reset.addEventListener('click', () => {
  Object.assign(shape, SHAPE_DEFAULTS);
  buildControls();
  applyShape();
});
dom.derivedToggle.addEventListener('click', () => {
  const open = dom.derivedWrap.hidden;
  dom.derivedWrap.hidden = !open;
  dom.derivedToggle.setAttribute('aria-expanded', String(open));
});
dom.field.addEventListener('change', () => {
  dom.viewer.field = dom.field.value;
  applyFieldView(dom.viewer, FIELD_VIEW, dom.field.value, dom.fieldHint);
  workspace.draw();
});
dom.keep.addEventListener('click', () => {
  if (!report) return;
  const entryRow = row();
  const { rows, evicted } = runs.save(EXERCISE, entryRow);
  if (changedTheDesign(EXERCISE, entryRow.geometry)) path.mark('improve');
  refreshRuns(rows, evicted);
  openDrawer('runs-panel');
});
dom.compareJump.addEventListener('click', () => openDrawer('runs-panel'));
dom.exportCsv.addEventListener('click', () =>
  runs.download('sensor-runs.csv', runs.toCsv(runs.load(EXERCISE)), 'text/csv'),
);
dom.exportJson.addEventListener('click', () =>
  runs.download('sensor-runs.json', runs.toJson(runs.load(EXERCISE)), 'application/json'),
);
dom.clearRuns.addEventListener('click', () => refreshRuns(runs.clear(EXERCISE)));

/**
 * The folded rows of the bench (ADR-025): each link in the model-details row opens one drawer
 * in the page flow, one at a time. The row is a set of tabs laid flat, and two open drawers
 * would rebuild the stacked page the redesign removed.
 */
function drawerToggles() {
  return [...dom.modelDetails.querySelectorAll('[data-drawer]')];
}

function setDrawer(id, open) {
  const drawer = document.getElementById(id);
  if (!drawer) return;
  drawer.hidden = !open;
  for (const button of drawerToggles()) {
    if (button.dataset.drawer === id) button.setAttribute('aria-expanded', String(open));
  }
}

function openDrawer(id, { reveal = true } = {}) {
  for (const button of drawerToggles()) {
    if (button.dataset.drawer !== id) setDrawer(button.dataset.drawer, false);
  }
  setDrawer(id, true);
  if (reveal) revealPanel(document.getElementById(id));
}

function toggleDrawer(id) {
  const drawer = document.getElementById(id);
  if (!drawer) return;
  if (drawer.hidden) openDrawer(id);
  else setDrawer(id, false);
}

for (const button of document.querySelectorAll('#model-details [data-drawer]')) {
  button.addEventListener('click', () => toggleDrawer(button.dataset.drawer));
}

try {
  const [loaded, info, solvers] = await Promise.all([
    fetch(contentUrl(EXERCISE)).then((response) => response.json()),
    health().catch(() => null),
    solversFor(GEOMETRY_TYPE, { physics: PHYSICS }),
  ]);

  content = loaded;
  catalogue = solvers;
  mountLoop();
  renderLesson({ content, intro: null, lesson: dom.lesson, open: ['problem'] });
  buildControls();
  declareOverlays();
  present();
  refreshRuns();

  const chosen = solver();
  if (chosen) {
    buildForms();
    dom.solverHint.textContent = chosen.description ?? '';
  }
  applyShape();

  const canSolve = applyMaintenance(
    dom,
    info,
    t('bench.maintenance', { alternative: t('sensor.maintenanceAlternative') }),
  );

  if (!chosen) {
    setStatusOn(dom, t('sensor.noSolverHere'), 'error');
    dom.run.disabled = true;
  } else if (!canSolve) {
    setStatusOn(dom, t('experiment.maintenanceStatus'));
    dom.run.disabled = true;
  } else {
    setStatusOn(dom, t('sensor.ready'));
  }
} catch (error) {
  setStatusOn(dom, t('experiment.unreachable', { detail: describeError(error) }), 'error');
  dom.run.disabled = true;
}
