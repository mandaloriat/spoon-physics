/**
 * The heat sink — an extruded profile, as an exercise.
 *
 * The fifth experiment, and the first whose answer depends on two heat paths that *fight each
 * other*. Conduction through the metal is ordinary. What makes the exercise is the boundary:
 *
 *   - convection, with `h` evaluated from the channel the fins leave between them rather than
 *     looked up once. Held constant, the model says more fins are always better for ever, which
 *     is the opposite of the answer;
 *   - radiation, exchanged inside each channel through exact two-dimensional view factors and
 *     with the room through the channel mouth. As the fins close up, a flank sees the facing
 *     fin instead of the room and the radiative loss collapses with the view factor.
 *
 * So thermal resistance has an interior minimum in fin count, and the page's headline is the
 * sweep that shows it — one solve cannot. See `docs/exercises/heat-sink.md`.
 *
 * There is no geometry widget, for the reason ADR-012 gives on the solenoid: `<fs-geometry-2d>`
 * edits a `domain2d` outline, and this profile is filled rectangles better described by the
 * quantities an engineer would name. The geometry payload carries the *envelope* the sink must
 * fit inside; the profile itself travels in `params`, because the correlation needs the channel
 * width and recovering that from a list of rectangles would be inferring a quantity from a
 * picture (ADR-019, and the adapter's own docstring).
 *
 * **The page asks the same question in two dimensions or three, and the choice is a real one.**
 * `lab.heatsink2d` solves the cross-section: exact for an extrusion, fast enough for the twenty
 * solves the fin-count sweep needs, and built on the assumption that the device heats the base
 * evenly along the whole length. `lab.heatsink3d` solves the body, so the device can be shorter
 * than the sink — which is what a real one is. The two are separate capabilities because their
 * *geometry kinds* differ, and that is what lets each refuse the other's payload instead of
 * answering a different problem confidently (ADR-023).
 *
 * A solid needs no new rendering here: the viewer draws `grid2d`, a `slice` through a `mesh3d`
 * is one, and the plane control below the field picker is the whole of the difference.
 */

import '@fenix-spoon/viewer';

import { sliceOf, solversFor } from '/shared/api.js';
import { describeError, el, health, mountChrome, revealPanel } from '/shared/components.js';
import { drawCurve } from '/shared/curve.js';
import {
  renderChallenge,
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
import { createGuide } from '/shared/guide.js';
import { contentUrl, num, t } from '/shared/i18n.js';
import * as runs from '/shared/runs.js';
import { createWorkspace } from '/shared/workspace.js';

const EXERCISE = 'heatsink';
/**
 * Both kinds, because the page offers both solvers.
 *
 * The catalogue is filtered by geometry kind *and* by physics — see `solversFor` on why the
 * second filter exists — so a page that produces two kinds asks twice and merges. What it must
 * not do is ask for neither and filter by name: the reason `physics` is a declaration is that a
 * list of names kept here goes stale the first time one is added.
 */
const GEOMETRY_TYPES = ['regions2d', 'regions3d'];
/**
 * `heatsink`, and deliberately not `heat`.
 *
 * Upstream's two conduction adapters declare `heat` and have no radiative boundary. Filtering
 * on that tag would offer this page a solver whose answer is a tenth high on the nominal
 * still-air case — not a different picture, a different number. It is the trap the magnetics
 * page fell into when `mock.heat2d` matched its geometry filter, and the adapter carries its
 * own tag so it cannot happen again.
 */
const PHYSICS = 'heatsink';
const SOLVER_PREFIX = 'lab.heatsink';

/** The extrusion is 60 mm wide and the profile has to fit inside it. Metres, on the wire. */
const ENVELOPE_WIDTH = 0.06;
const ENVELOPE_HEIGHT = 0.09;

const dom = Object.fromEntries(
  [
    'guide',
    'lesson',
    'viewer',
    'workspace',
    'schematic',
    'base',
    'fins',
    'footprint',
    'channel',
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
    'solidControls',
    'solidNote',
    'planePanel',
    'planeAxis',
    'planePosition',
    'planeNote',
    'numerical',
    'conditions',
    'derivedToggle',
    'derivedWrap',
    'derived',
    'shapeControls',
    'shapeNote',
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
    'sweep',
    'sweepCurve',
    'radiativeCurve',
    'sweepNote',
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
    'explain',
    'teacher',
    'whyPanel',
    'predictPanel',
    'teacherCard',
  ].map((key) => [
    key,
    document.getElementById(key.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)),
  ]),
);

/* ---------------------------------------------------------------- the profile */

/**
 * Ten fins, 25 mm tall, on a 5 mm base — and a sink that **misses the mission**.
 *
 * It is close to the best this fin height can do, which is the point: it lands at about 104 °C
 * against the 95 asked for, so the obvious move (add fins) makes it worse and the visitor has
 * to find the other lever. A default that already passed would leave nothing to do.
 */
const SHAPE_DEFAULTS = {
  baseThickness: 5,
  finCount: 10,
  finThickness: 1.5,
  finHeight: 25,
  power: 30,
  ambient: 25,
  footprint: 30,
  velocity: 0,
  // The extrusion length, in millimetres. It has always been part of this exercise — every
  // watt, gram and kelvin per watt on the page is per unit depth multiplied by it — and it
  // used to be a solver default nobody could see. Where it *travels* now depends on what is
  // being solved: a parameter for the section, the geometry's own z extent for the solid.
  depth: 60,
  // How much of that length the device actually touches. Meaningless to the section solver,
  // which has nowhere to put it, and the whole of what the solid one adds.
  footprintDepth: 30,
};

const shape = { ...SHAPE_DEFAULTS };
/** The choices that are not numbers, so they are not sliders. */
const choices = { finish: 'black_anodised', cooling: 'natural', flush: true };

const DESIGN_CONTROLS = [
  {
    key: 'finCount',
    label: t('heatsink.design.finCount'),
    min: 1,
    max: 30,
    step: 1,
    unit: '',
    title: t('heatsink.design.finCountTitle'),
  },
  {
    key: 'finHeight',
    label: t('heatsink.design.finHeight'),
    min: 5,
    max: 80,
    step: 1,
    unit: ' mm',
    title: t('heatsink.design.finHeightTitle'),
  },
  {
    key: 'finThickness',
    label: t('heatsink.design.finThickness'),
    min: 0.5,
    max: 5,
    step: 0.1,
    unit: ' mm',
    title: t('heatsink.design.finThicknessTitle'),
  },
  {
    key: 'baseThickness',
    label: t('heatsink.design.baseThickness'),
    min: 2,
    max: 15,
    step: 0.5,
    unit: ' mm',
    title: t('heatsink.design.baseThicknessTitle'),
  },
];

const CONDITION_CONTROLS = [
  {
    key: 'power',
    label: t('heatsink.design.power'),
    min: 5,
    max: 120,
    step: 1,
    unit: ' W',
    title: t('heatsink.design.powerTitle'),
  },
  {
    key: 'ambient',
    label: t('heatsink.design.ambient'),
    min: -10,
    max: 60,
    step: 1,
    unit: ' °C',
    title: t('heatsink.design.ambientTitle'),
  },
  {
    key: 'footprint',
    label: t('heatsink.design.footprint'),
    min: 5,
    max: 55,
    step: 1,
    unit: ' mm',
    title: t('heatsink.design.footprintTitle'),
  },
  {
    key: 'depth',
    label: t('heatsink.design.depth'),
    min: 20,
    max: 200,
    step: 5,
    unit: ' mm',
    title: t('heatsink.design.depthTitle'),
  },
];

/** The one control only the solid solver can use, so the page offers it only then. */
const SOLID_CONTROLS = [
  {
    key: 'footprintDepth',
    label: t('heatsink.design.footprintDepth'),
    min: 5,
    max: 200,
    step: 5,
    unit: ' mm',
    title: t('heatsink.design.footprintDepthTitle'),
  },
];

/**
 * The controls that are a choice rather than a magnitude.
 *
 * `buildShapeControls` makes range sliders, which is right for everything above and wrong for
 * these three: a finish is one of three coatings, cooling is a mode, and the mounting is a
 * yes-or-no. A slider over a set of names would be a lie about what lies between them.
 */
function buildChoiceControls(container) {
  const finish = el(
    'select',
    { id: 'choice-finish' },
    ...['mill', 'clear_anodised', 'black_anodised'].map(
      (value) => new Option(t(`heatsink.finish.${value}`), value, false, choices.finish === value),
    ),
  );
  finish.addEventListener('change', () => {
    choices.finish = finish.value;
    applyShape();
  });

  const cooling = el(
    'select',
    { id: 'choice-cooling' },
    ...['natural', 'forced'].map(
      (value) =>
        new Option(t(`heatsink.cooling.${value}`), value, false, choices.cooling === value),
    ),
  );
  cooling.addEventListener('change', () => {
    choices.cooling = cooling.value;
    // A fan with no speed is not a fan. Give it one the moment the mode is chosen, rather
    // than letting the solver refuse the job for a reason the visitor did not cause.
    if (choices.cooling === 'forced' && shape.velocity <= 0) shape.velocity = 2;
    applyShape();
    renderVelocity();
  });

  const flush = el('input', { type: 'checkbox', id: 'choice-flush' });
  flush.checked = choices.flush;
  flush.addEventListener('change', () => {
    choices.flush = flush.checked;
    applyShape();
  });

  container.append(
    el(
      'div',
      { class: 'field' },
      el(
        'label',
        { class: 'field__label', for: 'choice-finish' },
        el('span', { text: t('heatsink.design.finish') }),
      ),
      finish,
      el('span', { class: 'field__hint', text: t('heatsink.design.finishHint') }),
    ),
    el(
      'div',
      { class: 'field' },
      el(
        'label',
        { class: 'field__label', for: 'choice-cooling' },
        el('span', { text: t('heatsink.design.cooling') }),
      ),
      cooling,
      el('span', { class: 'field__hint', text: t('heatsink.design.coolingHint') }),
    ),
    el('div', { class: 'field', id: 'velocity-slot' }),
    el(
      'div',
      { class: 'field field--check' },
      el(
        'label',
        { class: 'field__label', for: 'choice-flush' },
        flush,
        el('span', { text: t('heatsink.design.flush') }),
      ),
      el('span', { class: 'field__hint', text: t('heatsink.design.flushHint') }),
    ),
  );
  renderVelocity();
}

/** The fan speed, shown only when there is a fan. */
function renderVelocity() {
  const slot = document.getElementById('velocity-slot');
  if (!slot) return;
  slot.replaceChildren();
  slot.hidden = choices.cooling !== 'forced';
  if (slot.hidden) return;
  buildShapeControls(
    slot,
    [
      {
        key: 'velocity',
        label: t('heatsink.design.velocity'),
        min: 0.5,
        max: 10,
        step: 0.5,
        unit: ' m/s',
        title: t('heatsink.design.velocityTitle'),
      },
    ],
    shape,
    applyShape,
  );
}

/* ------------------------------------------------------------------ the payloads */

/**
 * The envelope, in whichever kind the chosen solver takes.
 *
 * One region, and it is the space the sink may occupy rather than the sink itself — the same
 * "site" role the bridge's geometry plays. The vertices are inset by a micron because a region
 * must lie strictly inside the domain bounds.
 *
 * **The difference between the two is one coordinate, and it is the point of the whole
 * change.** A `regions2d` has no length, so the extrusion travelled as `params.depth` and every
 * number came back per unit depth multiplied by it — which a server can neither check nor
 * refuse. A `regions3d` has a `z` extent, so the same quantity is now part of the payload the
 * solver validates. Nothing else about the envelope moved.
 */
function buildGeometry() {
  const eps = 1e-6;
  const [w, h] = [ENVELOPE_WIDTH, ENVELOPE_HEIGHT];
  if (!isSolid()) {
    return {
      type: 'regions2d',
      bounds: [0, 0, w, h],
      background: {},
      regions: [
        {
          name: 'envelope',
          shape: {
            type: 'polygon2d',
            points: [
              [eps, eps],
              [w - eps, eps],
              [w - eps, h - eps],
              [eps, h - eps],
            ],
          },
          material: {},
        },
      ],
    };
  }

  const d = shape.depth / 1000;
  return {
    type: 'regions3d',
    bounds: [0, 0, 0, w, h, d],
    background: {},
    regions: [
      {
        name: 'envelope',
        // `box3d` and not a polygon: a solid region is a parametric primitive, which is what
        // keeps a face of it nameable by construction rather than by vertex index.
        shape: { type: 'box3d', min: [eps, eps, eps], max: [w - eps, h - eps, d - eps] },
        material: {},
      },
    ],
  };
}

/**
 * Millimetres on the page, metres on the wire. Converted in exactly one place.
 *
 * The last two entries are where the two solvers part company, and neither is optional: the
 * section takes `depth` because it has nowhere else to learn the length, and the solid refuses
 * it — it read the length off the geometry — while taking the one thing that only exists once
 * there is a length to be shorter than.
 */
function profileParams() {
  const common = {
    base_thickness: shape.baseThickness / 1000,
    fin_count: Math.round(shape.finCount),
    fin_thickness: shape.finThickness / 1000,
    fin_height: shape.finHeight / 1000,
    finish: choices.finish,
    power: shape.power,
    t_ambient: shape.ambient,
    footprint_width: shape.footprint / 1000,
    cooling: choices.cooling,
    face_velocity: choices.cooling === 'forced' ? shape.velocity : 0,
    base_mounted_flush: choices.flush,
  };
  return isSolid()
    ? { ...common, footprint_depth: shape.footprintDepth / 1000 }
    : { ...common, depth: shape.depth / 1000 };
}

function currentParams(extra = {}) {
  return { ...profileParams(), ...forms.numerical, ...extra };
}

/* ------------------------------------------------------------------ the schematic */

/** Channel width in millimetres — the quantity the correlation is evaluated on. */
/**
 * The gap between two fins, in millimetres, and never a negative one.
 *
 * Ask for more fin than there is base and the arithmetic goes below zero, which is not a narrow
 * channel — it is a profile that does not exist. Returning the raw number let it reach the
 * derived readout and the schematic, so the page showed a channel of minus two millimetres and
 * drew the line backwards while correctly telling the visitor the fins overlap. Two answers to
 * the same question, one of them nonsense. `finsFit` is what callers ask when they need to know
 * *whether* there is a channel; this returns how wide it is when there is one.
 */
function channelWidth() {
  const n = Math.round(shape.finCount);
  if (n < 2) return 0;
  return Math.max(0, (60 - n * shape.finThickness) / (n - 1));
}

function finsFit() {
  return Math.round(shape.finCount) * shape.finThickness <= 60;
}

function applyShape() {
  const n = Math.round(shape.finCount);
  const pitch = n > 1 ? (60 - shape.finThickness) / (n - 1) : 0;

  setRect(dom.base, 0, 0, 60, shape.baseThickness);

  const fins = [];
  for (let i = 0; i < n; i += 1) {
    const x = n > 1 ? i * pitch : (60 - shape.finThickness) / 2;
    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    rect.setAttribute('class', 'region region--core');
    rect.setAttribute('x', x.toFixed(3));
    rect.setAttribute('y', shape.baseThickness.toFixed(3));
    rect.setAttribute('width', shape.finThickness.toFixed(3));
    rect.setAttribute('height', shape.finHeight.toFixed(3));
    fins.push(rect);
  }
  dom.fins.replaceChildren(...fins);

  const half = shape.footprint / 2;
  setLine(dom.footprint, 30 - half, 0, 30 + half, 0);
  // The channel, drawn once between the first pair as the gap the air has to fit through.
  // Only when there is one: an overlapping profile has no gap to annotate.
  if (n > 1 && finsFit()) {
    const left = shape.finThickness;
    setLine(
      dom.channel,
      left,
      shape.baseThickness + shape.finHeight / 2,
      left + channelWidth(),
      shape.baseThickness + shape.finHeight / 2,
    );
    dom.channel.removeAttribute('hidden');
  } else {
    dom.channel.setAttribute('hidden', '');
  }

  // The viewBox follows the profile, so a 5 mm fin and an 80 mm fin are both legible.
  const top = shape.baseThickness + shape.finHeight;
  dom.schematic.setAttribute('viewBox', `-4 ${(-top - 4).toFixed(1)} 68 ${(top + 8).toFixed(1)}`);
  dom.schematic
    .querySelector('g')
    .setAttribute('transform', `translate(0, ${(-top).toFixed(3)}) scale(1, -1)`);

  dom.shapeNote.textContent = finsFit()
    ? t('heatsink.shapeNote', {
        channel: num(channelWidth(), { maximumFractionDigits: 2 }),
        mass: num(estimatedMass() * 1000, { maximumFractionDigits: 0 }),
      })
    : t('heatsink.shapeOverlap', { count: n });
  dom.run.disabled = !finsFit() || !solver() || running;
  dom.sweep.disabled = isSolid();
  renderModelNote();
  renderDerived();
}

/**
 * The controls and the sentence that depend on which question is being asked.
 *
 * Rebuilt on every model change rather than hidden, because the solid's one extra control has
 * no meaning at all for the section — a disabled slider would suggest the section could take
 * the number and is declining to, which is the opposite of the situation.
 */
function renderModel() {
  const solidChosen = isSolid();
  if (solidChosen) buildShapeControls(dom.solidControls, SOLID_CONTROLS, shape, applyShape);
  else dom.solidControls.replaceChildren();

  dom.solverHint.textContent = solver()?.description ?? '';
  if (!solidChosen) {
    solid = null;
    dom.planePanel.hidden = true;
  }
  renderModelNote();
}

/**
 * The sentence under the model choice — text only, and separate from the controls above it.
 *
 * Split because `applyShape` runs on every pixel of a drag: rebuilding the slider from under
 * the pointer mid-gesture drops the drag, which is a bug that only appears with a mouse held
 * down and is therefore easy to ship.
 */
function renderModelNote() {
  dom.solidNote.hidden = false;
  dom.solidNote.textContent = isSolid()
    ? t('heatsink.model.solidNote', {
        covered: num(Math.min(100, (100 * shape.footprintDepth) / shape.depth), {
          maximumFractionDigits: 0,
        }),
      })
    : t('heatsink.model.sectionNote');
}

function setRect(node, x, y, width, height) {
  node.setAttribute('x', x.toFixed(3));
  node.setAttribute('y', y.toFixed(3));
  node.setAttribute('width', Math.max(0, width).toFixed(3));
  node.setAttribute('height', Math.max(0, height).toFixed(3));
}

function setLine(node, x1, y1, x2, y2) {
  node.setAttribute('x1', x1.toFixed(3));
  node.setAttribute('y1', y1.toFixed(3));
  node.setAttribute('x2', x2.toFixed(3));
  node.setAttribute('y2', y2.toFixed(3));
}

/** Aluminium 6063, the adapter's default. Shown before a run so the budget is visible while
 *  the sliders move, rather than only after the solve has spent it. */
function estimatedMass() {
  const area =
    (60 * shape.baseThickness + Math.round(shape.finCount) * shape.finThickness * shape.finHeight) /
    1e6;
  return 2700 * area * (shape.depth / 1000);
}

function renderDerived() {
  dom.derived.replaceChildren(
    // An em dash rather than a number wherever the profile does not exist: a quantity with no
    // value is said to have none, which is the same rule the run table follows for a metric the
    // solver withheld.
    ...entry(
      t('heatsink.derived.channel'),
      finsFit() ? `${num(channelWidth(), { maximumFractionDigits: 2 })} mm` : '—',
    ),
    ...entry(
      t('heatsink.derived.area'),
      `${num(exposedArea() * 1e4, { maximumFractionDigits: 0 })} cm²`,
    ),
    ...entry(
      t('heatsink.derived.mass'),
      `${num(estimatedMass() * 1000, { maximumFractionDigits: 0 })} g`,
    ),
    ...entry(
      t('heatsink.derived.flux'),
      `${num(shape.power / ((shape.footprint * 0.06) / 1000), { maximumFractionDigits: 0 })} W/m²`,
    ),
  );
}

/** Exposed surface over the whole extrusion, m². The number the coefficient multiplies. */
function exposedArea() {
  const n = Math.round(shape.finCount);
  const flanks = 2 * n * shape.finHeight;
  const tips = n * shape.finThickness;
  const between = Math.max(0, 60 - n * shape.finThickness);
  return ((flanks + tips + between) / 1000) * 0.06;
}

function entry(label, value) {
  return [el('dt', { text: label }), el('dd', { class: 'num', text: value })];
}

/* --------------------------------------------------------------- what is reported */

const PARAM_UI = [
  { name: 'cell_size', label: t('heatsink.params.cellSize'), group: 'numerical', scale: 1 },
  { name: 'radiation', label: t('heatsink.params.radiation'), group: 'numerical' },
  { name: 'h_override', label: t('heatsink.params.hOverride'), group: 'numerical' },
];

const METRICS = [
  {
    key: 't_max',
    goal: t('heatsink.goal.temperature'),
    label: t('heatsink.metrics.tMax'),
    unit: '°C',
    digits: 1,
  },
  { key: 't_rise', label: t('heatsink.metrics.tRise'), unit: 'K', digits: 1 },
  { key: 'thermal_resistance', label: t('heatsink.metrics.resistance'), unit: 'K/W', digits: 3 },
  {
    key: 'mass',
    goal: t('heatsink.goal.aluminium'),
    label: t('heatsink.metrics.mass'),
    unit: 'kg',
    digits: 3,
  },
  { key: 'score', label: t('heatsink.metrics.score'), unit: 'K·kg/W', digits: 4 },
  { key: 'fin_efficiency', label: t('heatsink.metrics.efficiency'), unit: '1', digits: 3 },
  { key: 'radiative_fraction', label: t('heatsink.metrics.radiative'), unit: '1', digits: 3 },
  { key: 'view_factor_to_room', label: t('heatsink.metrics.viewFactor'), unit: '1', digits: 3 },
  { key: 'h_convective', label: t('heatsink.metrics.h'), unit: 'W/m²·K', digits: 2 },
  { key: 'flux_max', label: t('heatsink.metrics.flux'), unit: 'W/m²', digits: 0 },
  // The four the section has no way to produce. `requires` is what makes them read as "this
  // run could not answer that" rather than as a missing number — the same mechanism the
  // aerofoil uses for a quantity that only a sweep has.
  {
    key: 'thermal_resistance_extruded',
    label: t('heatsink.metrics.extruded'),
    unit: 'K/W',
    digits: 4,
    requires: 'solid',
    absent: t('heatsink.metrics.needsSolid'),
  },
  {
    key: 'spreading_resistance',
    label: t('heatsink.metrics.spreading'),
    unit: 'K/W',
    digits: 4,
    requires: 'solid',
    absent: t('heatsink.metrics.needsSolid'),
  },
  {
    key: 'end_gain',
    label: t('heatsink.metrics.endGain'),
    unit: 'K/W',
    digits: 4,
    requires: 'solid',
    absent: t('heatsink.metrics.needsSolid'),
  },
  {
    key: 'end_loss_fraction',
    label: t('heatsink.metrics.endLoss'),
    unit: '1',
    digits: 3,
    requires: 'solid',
    absent: t('heatsink.metrics.needsSolid'),
  },
];

const METRIC_LABELS = Object.fromEntries(METRICS.map((metric) => [metric.key, metric]));

const KPIS = [
  {
    key: 't_max',
    label: t('heatsink.headline.temperature'),
    symbol: 'T_max',
    unit: '°C',
    plainUnit: '°C',
    digits: 1,
    goal: { value: 95, comparator: '<' },
    hint: t('heatsink.headline.temperatureHint'),
  },
  {
    key: 'mass',
    label: t('heatsink.headline.aluminium'),
    symbol: 'm',
    unit: 'g',
    plainUnit: 'g',
    digits: 0,
    from: (found) => (typeof found.metrics?.mass === 'number' ? 1000 * found.metrics.mass : null),
    goal: { value: 170, comparator: '<' },
    hint: t('heatsink.headline.aluminiumHint'),
  },
  {
    key: 'channel',
    label: t('heatsink.headline.channel'),
    symbol: 's',
    unit: 'mm',
    plainUnit: 'mm',
    digits: 1,
    // Not a target and deliberately shown beside two that are: it is the quantity that makes
    // the surprise legible. More fins raise the area and narrow this, and the exercise is
    // about which of the two wins.
    from: () => channelWidth(),
    note: () => t('heatsink.headline.channelNote'),
    hint: t('heatsink.headline.channelHint'),
  },
];

/**
 * The two checks that reach the page.
 *
 * Both come back in the result envelope rather than in an artifact: the energy balance as
 * `residual`, and the view-factor identities folded into it — radiation lost into a badly
 * formed enclosure leaves through the balance. The identities themselves are asserted at
 * machine precision in the test suite, where a number that small belongs.
 */
const CHECKS = [
  {
    key: 'energy_balance_rel',
    tolerance: 'energy_balance_tol',
    label: t('heatsink.checks.energy'),
    describe: t('heatsink.checks.energyTitle'),
  },
];

const FIELD_VIEW = {
  T: {
    label: t('heatsink.fields.temperature'),
    units: '°C',
    colormap: 'inferno',
    hint: t('heatsink.fields.temperatureHint'),
  },
  flux: {
    label: t('heatsink.fields.flux'),
    units: 'W/m²',
    colormap: 'viridis',
    hint: t('heatsink.fields.fluxHint'),
  },
};

/* --------------------------------------------------------------------- the state */

const forms = { numerical: {} };
let catalogue = { all: [], byMode: {} };
let chosenSolver = null;
/** The last solid result and the plane currently cut through it. Null for a section. */
let solid = null;
let report = null;
let running = false;
let currentJob = null;
let workspace = null;
let content = null;
let lastSweep = null;
let selected = new Set();
let guide = null;

/**
 * The capability the page will submit to.
 *
 * It used to be "the first one whose name starts with `lab.heatsink`", which was right while
 * there was one. There are two now and they answer different questions, so the choice is the
 * visitor's and this reads it back. The fallback is deliberate and is the section: it is the
 * faster solve and the one the fin-count sweep needs, so a server that offers only one still
 * gets a working page.
 */
function solver() {
  const heatsinks = catalogue.all.filter((entry) => entry.name.startsWith(SOLVER_PREFIX));
  return heatsinks.find((entry) => entry.name === chosenSolver) ?? heatsinks[0] ?? null;
}

/** Is the chosen capability the one that solves a body? Read from what it *declares*. */
function isSolid() {
  return Boolean(solver()?.geometry_types?.includes('regions3d'));
}

/** The two capabilities, section first — which is the order the exercise is built in. */
function heatsinkSolvers() {
  return catalogue.all
    .filter((entry) => entry.name.startsWith(SOLVER_PREFIX))
    .sort(
      (a, b) =>
        Number(a.geometry_types.includes('regions3d')) -
        Number(b.geometry_types.includes('regions3d')),
    );
}

/** What to call each of them on the page. The server's own titles are English-only. */
function modelLabel(entry) {
  return entry.geometry_types.includes('regions3d')
    ? t('heatsink.model.solid')
    : t('heatsink.model.section');
}

/**
 * The report the exercise panels read, built here rather than fetched.
 *
 * The magnetics page carries its engineering answer in a `report.json` artifact, because when
 * it was written the envelope had nowhere to put a computed metric. It does now — protocol 1.3
 * gave it `metrics`, 1.5 gave it `series`, and this adapter also uses `residual` for the energy
 * balance and `warnings` for the model switches. So there is no artifact to fetch and no second
 * round trip: the report is a view over the result.
 */
function buildReport(result) {
  // `converged`, `residual` and `warnings` travel *inside* `diagnostics` on the wire — they
  // grew out of `stats` in protocol 1.3 and were grouped there rather than left loose at the
  // top level. Reading them off the envelope root returns undefined, which renders as a
  // verification row saying "not run" and a validity panel that silently swallows every
  // warning the solver wrote. Both failure modes look like a working page.
  const diagnostics = result.diagnostics ?? {};
  return {
    metrics: result.metrics ?? {},
    verification: {
      energy_balance_rel: diagnostics.residual ?? null,
      // The tolerance §8 declares. Stated here rather than by the solver, because it is a
      // claim about what this *page* considers verified.
      energy_balance_tol: 0.01,
    },
    validity: { warnings: diagnostics.warnings ?? [] },
    stats: result.stats ?? {},
    converged: diagnostics.converged ?? null,
    // Which of the two questions this run answered. Read from the *result*, not from the
    // control: a row kept before the visitor switched solvers must keep saying what produced
    // it, and the metric panel must not claim a section run was missing a number it was never
    // able to have.
    solid: result.kind === 'mesh3d',
  };
}

async function run() {
  if (running) return;
  const chosen = solver();
  if (!chosen) {
    setStatusOn(dom, t('heatsink.noSolver'), 'error');
    return;
  }

  running = true;
  dom.artifacts.replaceChildren();

  try {
    let jobId = null;
    const result = await runSolve({
      dom,
      solver: chosen.name,
      geometry: buildGeometry(),
      params: currentParams(),
      onJob: (job) => {
        currentJob = job;
        jobId = job.id;
      },
    });
    if (!result) return;

    const first = report === null;
    report = buildReport(result);
    dom.results.hidden = false;
    // A `mesh3d` is not something the canvas draws, and deliberately: a solid is seen by
    // cutting it. `showSolid` asks the server for a plane and hands the viewer the `grid2d`
    // that comes back, so the picture below is a real query against the real result rather
    // than a rendering of a mesh nobody downloaded to look at.
    if (result.kind === 'mesh3d') await showSolid(result, jobId);
    else {
      solid = null;
      dom.planePanel.hidden = true;
      workspace.setResult(result);
    }
    if (first) workspace.fit();
    syncFieldOptions(dom.viewer, dom.field, FIELD_VIEW, dom.fieldHint);
    showStats(dom.stats, result);
    showArtifacts(dom.artifacts, result.artifacts);
    present();
    setStatusOn(dom, t('experiment.done'), 'done');
  } finally {
    running = false;
    currentJob = null;
    dom.keep.disabled = report === null;
    dom.run.disabled = !finsFit();
  }
}

/**
 * §10: the same sink at every fin count, in one job.
 *
 * The sweep is a solver parameter rather than a loop over jobs here, which keeps it one cache
 * key and one progress stream. Counts that do not fit the base are dropped by the adapter
 * rather than clamped — a point silently moved is a point that lies about which design
 * produced it — so the curve can come back shorter than it was asked for.
 */
async function runSweep() {
  if (running) return;
  const chosen = solver();
  if (!chosen) return;
  // The sweep is twenty solves and the solid one is seconds each, so it is a parameter the
  // section adapter has and the solid one deliberately does not. The button is disabled rather
  // than hidden: a control that vanishes teaches nothing about why.
  if (isSolid()) return;

  const counts = [];
  for (let n = 2; n <= 26; n += 2) {
    if (n * shape.finThickness <= 60) counts.push(n);
  }

  running = true;
  try {
    const result = await runSolve({
      dom,
      solver: chosen.name,
      geometry: buildGeometry(),
      params: currentParams({ sweep_fin_counts: counts }),
      onJob: (job) => {
        currentJob = job;
      },
    });
    if (!result) return;
    lastSweep = (result.series ?? [])[0] ?? null;
    report = buildReport(result);
    dom.results.hidden = false;
    workspace.setResult(result);
    present();
    setStatusOn(dom, t('experiment.done'), 'done');
  } finally {
    running = false;
    currentJob = null;
    dom.run.disabled = !finsFit();
  }
}

/* --------------------------------------------------------------------- the cut plane */

/**
 * Which plane is currently cut through the solid, in metres along its normal.
 *
 * `z` by default, at mid-length — which is the cross-section, and therefore the picture the
 * section solver draws. Starting there is what makes the *other* two worth looking at: the
 * visitor recognises the first one, and then sees that a cut through the base is not uniform.
 */
const plane = { axis: 'z', value: null };

const PLANE_AXES = ['z', 'y', 'x'];

/** Where each axis may be cut, from the mesh's own bounds. */
function planeRange(axis) {
  const [xmin, ymin, zmin, xmax, ymax, zmax] = solid?.bounds ?? [0, 0, 0, 1, 1, 1];
  if (axis === 'x') return [xmin, xmax];
  if (axis === 'y') return [ymin, ymax];
  return [zmin, zmax];
}

/** A sensible first cut per axis: mid-length, mid-base, mid-width. */
function planeDefault(axis) {
  const [low, high] = planeRange(axis);
  if (axis === 'y') return Math.min(high, shape.baseThickness / 2000);
  return 0.5 * (low + high);
}

async function showSolid(result, jobId) {
  solid = { jobId, bounds: result.data.bounds, result };
  dom.planePanel.hidden = false;
  plane.value = planeDefault(plane.axis);
  renderPlaneControls();
  await drawPlane();
}

/** Fetch the plane and give it to the viewer. Failure says so rather than blanking the stage. */
async function drawPlane() {
  if (!solid) return;
  try {
    const cut = await sliceOf(solid.jobId, {
      fields: Object.keys(FIELD_VIEW),
      axis: plane.axis,
      value: plane.value,
    });
    workspace.setResult({ ...solid.result, kind: cut.kind, data: cut.data });
    syncFieldOptions(dom.viewer, dom.field, FIELD_VIEW, dom.fieldHint);
    workspace.draw();
    dom.planeNote.textContent = t(`heatsink.planeNote.${plane.axis}`, {
      position: num(plane.value * 1000, { maximumFractionDigits: 1 }),
      missed: cut.missed,
    });
  } catch (error) {
    dom.planeNote.textContent = describeError(error);
  }
}

function renderPlaneControls() {
  dom.planeAxis.replaceChildren(
    ...PLANE_AXES.map(
      (axis) => new Option(t(`heatsink.plane.${axis}`), axis, false, axis === plane.axis),
    ),
  );
  const [low, high] = planeRange(plane.axis);
  buildShapeControls(
    dom.planePosition,
    [
      {
        key: 'position',
        label: t('heatsink.planePosition'),
        min: Number((low * 1000).toFixed(1)),
        max: Number((high * 1000).toFixed(1)),
        step: 0.5,
        unit: ' mm',
        title: t('heatsink.planePositionTitle'),
      },
    ],
    // A view of `plane.value` in millimetres, so the slider and the wire never disagree about
    // units: the control writes here and this is the only place the conversion happens.
    {
      get position() {
        return plane.value * 1000;
      },
      set position(mm) {
        plane.value = mm / 1000;
      },
    },
    // Debounced, because the control fires on every pixel of travel and each fire is a POST.
    // A hundred and fifty milliseconds is below the threshold where a drag feels laggy and
    // above the rate a dragged slider emits, so the server sees one cut per gesture.
    () => {
      window.clearTimeout(planeTimer);
      planeTimer = window.setTimeout(drawPlane, 150);
    },
  );
}

let planeTimer = 0;

function present() {
  renderChallenge(dom.challenge, content?.challenge, report, METRIC_LABELS);
  renderAttemptModel();
  renderKpis(dom.kpis, KPIS, report);
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

  drawSweep();
}

/**
 * Which of the two models produced the numbers just judged against the targets.
 *
 * **This is not decoration, and it is the one thing the second solver made necessary.** The
 * challenge reads `t_max` against 95 °C and does not know, because nothing in the envelope
 * says, whether it is reading the cross-section's answer or the body's. Those differ by a few
 * per cent on the same sink — enough to move an attempt across the line — so an attempt that
 * did not say which model made it would be a pass or a fail with a hidden argument in it.
 *
 * On a solid run the sentence carries the comparison rather than an assertion, because the
 * solver publishes both numbers: what the body found, and what the cross-section would have
 * said about the same sink on the same in-plane grid. Neither is derived here — a page that
 * computed a headline from two published metrics would be making a claim of its own, which is
 * the line §8 of the contract draws.
 */
function renderAttemptModel() {
  const existing = document.getElementById('attempt-model');
  existing?.remove();
  if (!report) return;

  const extruded = report.metrics?.thermal_resistance_extruded;
  const solved = report.metrics?.thermal_resistance;
  const text = report.solid
    ? Number.isFinite(extruded) && Number.isFinite(solved)
      ? t('heatsink.model.attemptSolid', {
          extruded: num(extruded, { maximumFractionDigits: 3 }),
          solid: num(solved, { maximumFractionDigits: 3 }),
        })
      : t('heatsink.model.attemptSolidAlone')
    : t('heatsink.model.attemptSection');
  dom.challenge.append(el('p', { class: 'challenge__model', id: 'attempt-model', text }));
}

function drawSweep() {
  if (!lastSweep) {
    dom.sweepNote.textContent = t('heatsink.sweepIdle');
    return;
  }
  const counts = lastSweep.x?.values ?? [];
  const trace = (name) => lastSweep.traces?.find((entry) => entry.name === name)?.values ?? [];
  const resistance = trace('thermal_resistance');
  const radiative = trace('radiative_fraction');
  if (!counts.length || !resistance.length) return;

  let best = 0;
  resistance.forEach((value, index) => {
    if (value < resistance[best]) best = index;
  });

  drawCurve(dom.sweepCurve, {
    traces: [{ name: 'R_θ', points: counts.map((n, i) => [n, resistance[i]]) }],
    xLabel: t('heatsink.plots.finCount'),
    yLabel: t('heatsink.plots.resistance'),
    marks: [{ x: counts[best], label: t('heatsink.plots.best') }],
  });
  drawCurve(dom.radiativeCurve, {
    traces: [{ name: 'Q_rad/Q', points: counts.map((n, i) => [n, radiative[i]]) }],
    xLabel: t('heatsink.plots.finCount'),
    yLabel: t('heatsink.plots.radiative'),
    marks: [{ x: counts[best] }],
  });

  const interior = best > 0 && best < counts.length - 1;
  dom.sweepNote.textContent = interior
    ? t('heatsink.sweepNote', {
        best: counts[best],
        value: num(resistance[best], { maximumFractionDigits: 3 }),
        worst: num(resistance[resistance.length - 1], { maximumFractionDigits: 3 }),
      })
    : t('heatsink.sweepEdge');
}

/* ------------------------------------------------------------------- the run table */

const COLUMNS = [
  { path: 'geometry.label', label: t('heatsink.columns.profile') },
  { path: 'metrics.t_max', label: 'T_max °C' },
  { path: 'metrics.thermal_resistance', label: 'R_θ K/W' },
  { path: 'metrics.mass', label: t('heatsink.columns.mass') },
  { path: 'metrics.score', label: 'R_θ·m' },
  { path: 'metrics.radiative_fraction', label: t('heatsink.columns.radiative') },
  // Blank on a section run, which is the honest entry: it is the number that run could not
  // produce, not a zero.
  { path: 'metrics.depth_correction', label: t('heatsink.columns.depthCorrection') },
  { path: 'physical.emissivity', label: 'ε' },
  { path: 'verification.energy_balance_rel', label: t('heatsink.columns.energy') },
];

/** A profile deserves a name, and its four dimensions are one. */
function describeShape() {
  return t('heatsink.shapeLabel', {
    fins: Math.round(shape.finCount),
    height: shape.finHeight,
    thickness: num(shape.finThickness, { maximumFractionDigits: 1 }),
    base: num(shape.baseThickness, { maximumFractionDigits: 1 }),
  });
}

/** One row: every input, the answer, the residual, the warnings. The contract's §5. */
function row() {
  const mm = (value) => value / 1000;
  return {
    exercise: { id: EXERCISE, version: '1.0.0' },
    solver: { name: solver()?.name ?? null, version: solver()?.version ?? null },
    geometry: {
      source: 'parametric',
      label: describeShape(),
      base_width_m: ENVELOPE_WIDTH,
      base_thickness_m: mm(shape.baseThickness),
      fin_count: Math.round(shape.finCount),
      fin_thickness_m: mm(shape.finThickness),
      fin_height_m: mm(shape.finHeight),
      channel_width_m: mm(channelWidth()),
      depth_m: mm(shape.depth),
      // Always a number, and for the cross-section it is the whole length — which is not a
      // convenient fiction but exactly what that model assumes. `changedTheDesign` compares
      // this block to decide whether a kept attempt is a *second design*, and switching model
      // is not one: it is the same sink asked a different question. A field that went null
      // when the model changed would have marked the journey's "improve" step for a click
      // that improved nothing.
      //
      // Which model ran is recorded, and it is recorded under `solver` where it belongs —
      // the geometry kind is a property of the capability, not of the sink.
      footprint_depth_m: isSolid() ? mm(shape.footprintDepth) : mm(shape.depth),
    },
    physical: {
      power_w: shape.power,
      t_ambient_c: shape.ambient,
      footprint_m: mm(shape.footprint),
      finish: choices.finish,
      // The emissivity the finish resolved to, not only its name: a row that recorded the
      // label alone could not be recomputed if the table behind it ever moved.
      emissivity: { mill: 0.05, clear_anodised: 0.6, black_anodised: 0.8 }[choices.finish],
      cooling: choices.cooling,
      face_velocity_ms: choices.cooling === 'forced' ? shape.velocity : 0,
      base_mounted_flush: choices.flush,
    },
    // Radiation and the pinned coefficient sit here beside the mesh size, and they are not
    // numerics: a run with either one set answered a different physical question. §9 says the
    // row has to carry them for exactly that reason.
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

function buildForms() {
  const chosen = solver();
  if (!chosen) return;
  // Rebuilt from the chosen capability's own schema, which is why switching model swaps the
  // Advanced panel too: the section takes one `cell_size`, the solid takes three lengths and
  // a decomposition switch, and neither list is written down here.
  forms.numerical = buildParamForm(dom.numerical, chosen, PARAM_UI, forms.numerical);
}

/**
 * Populate the model menu, and say what a server that offers only one can do.
 *
 * A single-capability server is the normal case for anyone running the slim image, and the
 * page has to stay usable there rather than presenting a menu of one.
 */
function renderSolverChoice() {
  const available = heatsinkSolvers();
  dom.solver.replaceChildren(
    ...available.map(
      (entry) => new Option(modelLabel(entry), entry.name, false, entry.name === chosenSolver),
    ),
  );
  dom.solver.disabled = available.length < 2;
  renderModel();
}

/* ------------------------------------------------------------------------ wiring */

mountChrome(EXERCISE);
workspace = createWorkspace({
  root: dom.workspace,
  viewer: dom.viewer,
  editor: null,
  fitLabel: t('heatsink.fitProfile'),
  exportName: 'heatsink-field',
  // The profile fills its own domain, unlike the solenoid's magnet in an eight-times window,
  // so framing it is framing everything. Returning null lets the workspace fall back to the
  // whole domain rather than inventing a box that would be the same box.
  subject: () => null,
});

buildShapeControls(dom.shapeControls, DESIGN_CONTROLS, shape, applyShape);
buildShapeControls(dom.conditions, CONDITION_CONTROLS, shape, applyShape);
buildChoiceControls(dom.conditions);
applyShape();

dom.solver.addEventListener('change', () => {
  chosenSolver = dom.solver.value;
  // The numerical form belongs to the capability, so it is rebuilt rather than carried over:
  // `depth_cell_size` means nothing to the section solver and would be refused by it.
  forms.numerical = {};
  renderModel();
  buildForms();
  applyShape();
});
dom.planeAxis.addEventListener('change', () => {
  plane.axis = dom.planeAxis.value;
  plane.value = planeDefault(plane.axis);
  renderPlaneControls();
  drawPlane();
});
dom.run.addEventListener('click', run);
dom.sweep.addEventListener('click', runSweep);
dom.cancel.addEventListener('click', () => currentJob?.cancel?.());
dom.reset.addEventListener('click', () => {
  Object.assign(shape, SHAPE_DEFAULTS);
  choices.finish = 'black_anodised';
  choices.cooling = 'natural';
  choices.flush = true;
  buildShapeControls(dom.shapeControls, DESIGN_CONTROLS, shape, applyShape);
  buildShapeControls(dom.conditions, CONDITION_CONTROLS, shape, applyShape);
  buildChoiceControls(dom.conditions);
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
  // "Improve" is not "run it again". A second attempt at a finer grid is a numerical
  // experiment and a worthwhile one, but it is not a second design — `changedTheDesign`
  // compares the geometry and the physical conditions, and nothing else. See `journey.js`.
  const kept = runs.load(EXERCISE);
  const entry = row();
  if (kept.length && changedTheDesign(kept[0], entry)) path.mark('improve');
  const { rows, evicted } = runs.save(EXERCISE, entry);
  refreshRuns(rows, evicted);
  revealPanel(dom.runsPanel);
});
dom.compareJump.addEventListener('click', () => revealPanel(dom.runsPanel));
dom.exportCsv.addEventListener('click', () =>
  runs.download('heatsink-runs.csv', runs.toCsv(runs.load(EXERCISE)), 'text/csv'),
);
dom.exportJson.addEventListener('click', () =>
  runs.download('heatsink-runs.json', runs.toJson(runs.load(EXERCISE)), 'application/json'),
);
dom.clearRuns.addEventListener('click', () => {
  runs.clear(EXERCISE);
  refreshRuns();
});

/* ------------------------------------------------------------- one suggestion at a time */

/**
 * What to say after an attempt that did not pass.
 *
 * Editorial rules rather than generated prose (§13.7). "Hot with mass to spare" and "hot with
 * the channel already closing" are the two halves of the exercise's whole point, and they are
 * told apart here rather than merged into one sentence about adding fins.
 */
function suggestion() {
  if (!report) return null;
  const temperature = report.metrics?.t_max;
  const mass = 1000 * (report.metrics?.mass ?? 0);
  const channel = channelWidth();
  if ((report.validity?.warnings ?? []).length) return t('heatsink.hint.outside');
  if (typeof temperature === 'number' && temperature >= 95) {
    if (channel > 0 && channel < 3) {
      return t('heatsink.hint.choked', { channel: channel.toFixed(1) });
    }
    if (mass < 170) return t('heatsink.hint.room', { margin: Math.round(170 - mass) });
    return t('heatsink.hint.hot');
  }
  if (mass >= 170) return t('heatsink.hint.heavy', { excess: Math.round(mass - 170) });
  return null;
}

/** Numbers the post-attempt cards may quote, so an explanation can be about *this* attempt. */
function attemptFacts() {
  if (!report) return {};
  return {
    channel: channelWidth().toFixed(1),
    temperature: (report.metrics?.t_max ?? 0).toFixed(0),
    fins: Math.round(shape.finCount),
  };
}

/* ------------------------------------------------------------------- predict, try, compare */

/**
 * The loop the page is played in, mounted once.
 *
 * The prediction is asked before anything is computed and gates nothing; the path lights the
 * steps that have been taken. Both live in `shared/journey.js` — see the note there about why
 * neither is allowed to block a solve or to score an answer.
 */
const path = mountPath(dom.path, { exercise: EXERCISE });
let prediction = null;

/**
 * Build the guided path, if this exercise's content file carries one.
 *
 * `content.guide` being absent is not an error — it is an exercise that has not been given a
 * lesson yet, and the page is exactly what it was before. See `airfoil/app.js` for a version
 * with figures and interactive presets; this page's chapters are prose only.
 */
function mountGuide() {
  if (!content.guide?.length) return;
  guide = createGuide({
    root: dom.guide,
    chapters: content.guide,
    storageKey: `spoon-physics:guide:${EXERCISE}`,
    onSkip: () => {
      dom.workspace.scrollIntoView({ behavior: 'smooth', block: 'start' });
    },
  });
}

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

try {
  const [loaded, info, solvers] = await Promise.all([
    fetch(contentUrl(EXERCISE)).then((response) => response.json()),
    health().catch(() => null),
    Promise.all(GEOMETRY_TYPES.map((kind) => solversFor(kind, { physics: PHYSICS }))),
  ]);

  content = loaded;
  // Two catalogues, one menu. A capability answering both kinds would appear twice, so the
  // merge is by name rather than a concatenation — none does today, and a page that would
  // break when one did is a page waiting to break.
  catalogue = {
    all: [...new Map(solvers.flatMap((c) => c.all).map((entry) => [entry.name, entry])).values()],
    byMode: Object.assign({}, ...solvers.map((c) => c.byMode)),
    declares: solvers.some((c) => c.declares),
  };
  mountLoop();
  renderLesson({ content, intro: null, lesson: dom.lesson, open: ['problem'] });
  mountGuide();
  present();
  refreshRuns();

  const chosen = solver();
  if (chosen) {
    chosenSolver = chosen.name;
    renderSolverChoice();
    buildForms();
    workspace.draw();
  }

  const canSolve = applyMaintenance(
    dom,
    info,
    t('bench.maintenance', { alternative: t('heatsink.maintenanceAlternative') }),
  );

  if (!chosen) {
    setStatusOn(dom, t('heatsink.noSolverHere'), 'error');
  } else if (!canSolve) {
    setStatusOn(dom, t('experiment.maintenanceStatus'));
  } else {
    dom.run.disabled = !finsFit();
    setStatusOn(dom, t('heatsink.ready'));
  }
} catch (error) {
  setStatusOn(dom, t('experiment.unreachable', { detail: describeError(error) }), 'error');
  dom.run.disabled = true;
}
