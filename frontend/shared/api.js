/**
 * The lab's thin layer over the Fenix Spoon SDK.
 *
 * Two things live here and nothing else: a client bound to this origin, and the
 * translation from "what capabilities does this server have" to "what can this page
 * offer". Job submission, progress streaming, reconnection and result fetching are the
 * SDK's job and are not re-implemented.
 */

import { FenixSpoonClient } from '@fenix-spoon/client';

import { t } from '/shared/i18n.js';

/**
 * Same-origin, always. The empty base URL makes every request relative, which is what
 * keeps the deployment free of CORS: Caddy serves the site and proxies `/api/v1` under
 * one hostname, so the browser never sees a cross-origin request. It also means no
 * build-time environment substitution and no hardcoded host to get wrong — this file is
 * identical on localhost and on the deployed hostname.
 */
export const client = new FenixSpoonClient('');

/**
 * The three ways a page can be told a solve was produced, keyed by the **declared**
 * `availability` of the capability rather than by its name.
 *
 * This used to match on the `mock.` and `dolfinx.` name prefixes, which was the only thing
 * `GET /api/v1/solvers` published. It has two failure modes that both actually bit:
 * `lab.airfoil_panel2d` is neither, so it fell through to a nameless "other" bucket — and
 * calling a panel method a "preview" would have been worse, because it is the most accurate
 * surface solution in the lab. Protocol 1.2 publishes `availability` through
 * `GET /api/v1/capabilities`, so the page reads what the adapter says about itself. This is
 * the change `docs/exercises/airfoil.md` §14.4 left open.
 *
 * An availability the lab has no entry for is not an error and not hidden: it gets the
 * capability's own title and description, which is how a solver added upstream tomorrow
 * shows up correctly without this file changing.
 */
export const MODES = {
  mock: mode('mock', 'mock'),
  fenicsx: mode('fenicsx', 'fenicsx'),
  'panel-method': mode('panel-method', 'panel'),
};

/**
 * One mode, worded in the language this page load resolved to.
 *
 * The `id` is the protocol's `availability` and never changes; the three sentences beside it
 * are the lab's own and live in `shared/strings/*.js`. Read once here rather than at every use,
 * because a mode is a constant and only its wording is not.
 */
function mode(id, key) {
  return {
    id,
    label: t(`solver.${key}.label`),
    summary: t(`solver.${key}.summary`),
    caveat: t(`solver.${key}.caveat`),
  };
}

/**
 * Every installed capability, with what it declares about itself.
 *
 * Two endpoints, because neither alone is enough. `GET /api/v1/solvers` carries the
 * `params_schema` the parameter form is generated from; `GET /api/v1/capabilities` carries
 * `physics` and `availability`, which is what lets a page choose by *what a solver solves*
 * instead of by what it is called. The second is protocol 1.2 and a server that predates it
 * simply answers 404 — in which case the declarations are absent, every page keeps working,
 * and `physics` filtering degrades to "accept anything", which is exactly the behaviour the
 * lab had before.
 *
 * @returns {Promise<object[]>} solver entries, each possibly carrying `physics` and
 *   `availability`
 */
async function catalogue() {
  const [solvers, declared] = await Promise.all([
    client.listSolvers(),
    fetch('/api/v1/capabilities', { headers: { Accept: 'application/json' } })
      .then((response) => (response.ok ? response.json() : []))
      .catch(() => []),
  ]);

  const byName = new Map((declared ?? []).map((entry) => [entry.name, entry]));
  return solvers.map((solver) => {
    const capability = byName.get(solver.name);
    return capability
      ? { ...solver, physics: capability.physics, availability: capability.availability }
      : solver;
  });
}

/**
 * The capabilities a page can actually use, grouped by mode.
 *
 * **`physics` is why this takes two filters and not one.** Geometry kind is a statement about
 * the payload, not about the problem: `mock.magnetostatics2d` and `mock.heat2d` both accept
 * `regions2d`, so a magnetics page filtering on geometry alone offered a heat-sink solver in
 * its own solver menu — and would have submitted a solenoid to it. Filtering on the physics
 * the capability declares is the fix, and it is the *server's* declaration rather than a list
 * of names kept here, which would go stale the first time a solver is renamed or added.
 *
 * A server too old to declare `physics` publishes none, and then the physics filter is
 * skipped rather than emptying the menu: a page that offers too much is recoverable, a page
 * that offers nothing is not.
 *
 * @param {string} geometryType protocol geometry kind the page produces, e.g. `domain2d`
 * @param {{physics?: string}} [want] the physics this page is about
 * @returns {Promise<{all: object[], byMode: Record<string, object[]>, declares: boolean}>}
 */
export async function solversFor(geometryType, want = {}) {
  const installed = await catalogue();
  const declares = installed.some((solver) => typeof solver.physics === 'string');

  const all = installed.filter((solver) => {
    if (!solver.geometry_types.includes(geometryType)) return false;
    if (!want.physics || !declares) return true;
    return solver.physics === want.physics;
  });

  const byMode = {};
  for (const mode of Object.values(MODES)) {
    byMode[mode.id] = all.filter((solver) => modeIdOf(solver) === mode.id);
  }
  return { all, byMode, declares };
}

/** The mode id a solver belongs to: its declared availability, or its name prefix. */
export function modeIdOf(solver) {
  if (solver?.availability && solver.availability !== 'unspecified') return solver.availability;
  // Pre-1.2 fallback only. Kept so the lab still groups a server that publishes no
  // declaration at all, and deliberately not consulted when one is published.
  if (solver?.name?.startsWith('mock.')) return 'mock';
  if (solver?.name?.startsWith('dolfinx.')) return 'fenicsx';
  return null;
}

/** The mode entry a solver belongs to, or `undefined` for one the lab has no wording for. */
export function modeOf(solver) {
  const id = modeIdOf(solver);
  return id ? MODES[id] : undefined;
}

/**
 * Read a parameter's constraints out of the solver's published JSON Schema.
 *
 * Solvers do not agree on parameter names — `mock.magnetostatics2d` takes `resolution` and
 * `iterations`, `dolfinx.magnetostatics2d` takes `mesh_size` — so a form that hardcodes
 * either is wrong for the other. Every bound and every default therefore comes from
 * `params_schema`, and a parameter the schema does not describe is simply not offered.
 * Nothing here invents a value the server did not publish.
 *
 * @returns {null|{name: string, type: string, default: unknown, min?: number, max?: number,
 *   description?: string}}
 */
export function paramSpec(solver, name) {
  const declared = solver?.params_schema?.properties?.[name];
  if (!declared) return null;

  // An optional parameter is emitted by pydantic as `anyOf: [{...}, {type: 'null'}]`, which
  // hides the type and the bounds one level down. Unwrap it, and remember that null is
  // allowed — a form that lost the bounds of a nullable field would render a number box with
  // no limits and send values the server refuses.
  const branches = Array.isArray(declared.anyOf) ? declared.anyOf : null;
  const nullable = Boolean(branches?.some((branch) => branch.type === 'null'));
  const property = nullable
    ? { ...(branches.find((branch) => branch.type !== 'null') ?? {}), default: declared.default }
    : declared;

  const spec = {
    nullable,
    name,
    type: property.type ?? 'number',
    default: property.default,
    description: property.description,
  };
  // JSON Schema spells inclusive and exclusive bounds differently, and pydantic emits
  // whichever the Field used (`gt=0.0` becomes exclusiveMinimum). Both are read; neither
  // is assumed.
  if (property.minimum !== undefined) spec.min = property.minimum;
  else if (property.exclusiveMinimum !== undefined) spec.min = property.exclusiveMinimum;
  if (property.maximum !== undefined) spec.max = property.maximum;
  else if (property.exclusiveMaximum !== undefined) spec.max = property.exclusiveMaximum;
  if (property.enum) spec.enum = property.enum;
  return spec;
}

/**
 * Cut a plane through a three-dimensional result and get back something the viewer can draw.
 *
 * **Why this is here and not in the widget.** `<fs-viewer>` is a canvas renderer for `grid2d`
 * and `mesh2d` and upstream's ADR 0006 is explicit that it stays exactly that: a solid is
 * *seen* by cutting it, and the cut is a field query the server already runs. So the browser
 * story for three dimensions is this function — two POSTs and a merge — rather than a WebGL
 * backend, and the lab drew its first solid without a line of rendering code.
 *
 * **Why it asks for each field separately and merges them.** The `slice` operation answers for
 * one named field, which is right: its budget is per query and a caller usually wants one.
 * The page's field picker, though, switches between fields on a result that is already drawn,
 * and re-cutting on every switch would put a round trip behind a `<select>`. Both cuts are the
 * same plane through the same mesh, so their grids are identical and merging them is safe —
 * asserted here rather than assumed, and asserted over the *whole* grid definition rather than
 * its shape, because a server that agreed on 192x192 and disagreed on `bounds` would otherwise
 * have one field's values painted on the other's coordinates.
 *
 * @param {string} jobId the finished job
 * @param {{fields: string[], axis: 'x'|'y'|'z', value: number, samples?: number}} plane
 * @returns {Promise<{kind: 'grid2d', data: object, plane: object, missed: number}>}
 */
export async function sliceOf(jobId, { fields, axis, value, samples = 192 }) {
  const cuts = await Promise.all(
    fields.map(async (field) => {
      const response = await fetch(client.url(`/api/v1/jobs/${jobId}/query`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ field, op: 'slice', axis, value, samples }),
      });
      if (!response.ok) {
        throw new Error(t('experiment.sliceFailed', { status: response.status }));
      }
      return { field, answer: (await response.json()).result };
    }),
  );

  const [first] = cuts;
  const merged = {
    bounds: first.answer.data.bounds,
    shape: first.answer.data.shape,
    fields: {},
    ...(first.answer.data.mask ? { mask: first.answer.data.mask } : {}),
  };
  for (const { field, answer } of cuts) {
    if (!sameGrid(answer.data, merged)) throw new Error(t('experiment.sliceMismatch'));
    merged.fields[field] = answer.data.fields[field];
  }
  return { kind: 'grid2d', data: merged, plane: first.answer.plane, missed: first.answer.missed };
}

/**
 * Do two `grid2d` payloads describe the *same* grid — all of it, not the shape alone?
 *
 * A grid is its cell counts, the box they cover, and which of those cells hold nothing. Two
 * cuts of one plane through one stored mesh agree on all three, and checking only the first
 * would leave the failure this guard exists to catch: same 192x192 on different `bounds` merges
 * without complaint and paints one field onto the other's coordinates, which is a picture that
 * looks right and is not.
 *
 * The mask is compared element by element with an early exit, because it is the one part that
 * is an array of tens of thousands of entries and the one part a stringify would make expensive.
 */
function sameGrid(a, b) {
  if (String(a.shape) !== String(b.shape)) return false;
  if (String(a.bounds) !== String(b.bounds)) return false;
  if (Boolean(a.mask) !== Boolean(b.mask)) return false;
  if (!a.mask) return true;
  if (a.mask.length !== b.mask.length) return false;
  for (let index = 0; index < a.mask.length; index += 1) {
    if (a.mask[index] !== b.mask[index]) return false;
  }
  return true;
}
