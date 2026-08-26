/**
 * A line plot, in SVG, in one file — with upstream's axis arithmetic underneath it.
 *
 * Four exercises need one: a surface pressure distribution, an incidence sweep, a fin-count
 * sweep, a member ladder. This file used to say the protocol had no result kind for a curve
 * and that the lab therefore drew its own. **The first half of that stopped being true**:
 * protocol 1.5 put `series1d` on the wire (fenix-spoon#69, closed), and upstream now ships
 * `<fs-plot>` to draw it.
 *
 * ## Why this file still exists, and what it gave up
 *
 * `<fs-plot>` draws curves and nothing on top of them. Every plot in this lab carries a
 * **reference mark** — the optimum fin count, the utilisation limit at 1, the edges of the flux
 * bundle, the zero line on a `C_p` — and on three of the four pages that mark is the didactic
 * point rather than a decoration. The widget has no annotation of any kind and no public
 * projection to place one with: it paints to a canvas and keeps its scales private, so drawing
 * a mark over it would mean reproducing its layout arithmetic from the outside and re-deriving
 * it on every upstream bump. See
 * [ADR-024](../../docs/architecture-decisions.md#adr-024--the-lab-takes-fenix-spoons-axis-arithmetic-and-keeps-its-own-renderer).
 *
 * What the lab does take is the half that is **pure, public and tested**:
 * `@fenix-spoon/plot/scale.js` — extents, padding, round ticks, and the data-to-pixel map. That
 * is the arithmetic where the interesting mistakes live, and it is now upstream's rather than
 * this file's second copy of it. What is left here is the renderer, the marks and the legend.
 *
 * This is still not a charting library and should not become one. The moment it wants to be,
 * the answer is the widget plus whatever it grew, not more code here.
 */

import { el } from '/shared/components.js';
import { t } from '/shared/i18n.js';

// The scale module, not the package index: the index registers `<fs-plot>` as a side effect,
// and a page that draws its own SVG has no use for a custom element it never mounts. `scale.js`
// imports nothing at all, which is what makes it safe to take on those terms.
import { extentOf, padDomain, scaleFor, ticksFor } from '@fenix-spoon/plot/scale.js';

const SVG = 'http://www.w3.org/2000/svg';
const PAD = { left: 46, right: 10, top: 10, bottom: 30 };

function node(name, attrs = {}) {
  const element = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== null && value !== undefined) element.setAttribute(key, String(value));
  }
  return element;
}

/**
 * Draw a plot into `container`, replacing whatever was there.
 *
 * @param {HTMLElement} container
 * @param {{traces: Array<{name: string, points: number[][], dashed?: boolean}>,
 *   xLabel: string, yLabel: string, invertY?: boolean, height?: number,
 *   marks?: Array<{y?: number, x?: number, label?: string}>}} spec
 */
export function drawCurve(container, spec) {
  const { traces = [], xLabel = '', yLabel = '', invertY = false, height = 260, marks = [] } = spec;
  const points = traces.flatMap((trace) => trace.points).filter((p) => Number.isFinite(p[1]));
  container.replaceChildren();
  if (!points.length) {
    container.append(el('p', { class: 'field__hint', text: t('curve.empty') }));
    return;
  }

  const width = Math.max(container.clientWidth || 520, 320);
  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;

  // A degenerate range is `usableDomain`'s problem, not this file's: it widens a constant
  // trace around its own value rather than dividing by a zero span. That guard used to live
  // here and is one of the things this import deletes.
  const xDomain = padDomain(extentOf(points.map((p) => p[0])) ?? { min: 0, max: 1 }, 'linear');
  const yDomain = padDomain(extentOf(points.map((p) => p[1])) ?? { min: 0, max: 1 }, 'linear');
  const xs = scaleFor(xDomain, PAD.left, width - PAD.right, 'linear');
  // Inverted means *up is more negative*, which is the aeronautical convention for `C_p` and
  // the reason this option exists: a `C_p` plot drawn the other way up reads as wrong to
  // anyone who has seen one before. Expressed as which pixel the domain minimum lands on,
  // which is how `<fs-plot>` expresses it too — same call, same two arguments swapped.
  const ys = invertY
    ? scaleFor(yDomain, PAD.top, height - PAD.bottom, 'linear')
    : scaleFor(yDomain, height - PAD.bottom, PAD.top, 'linear');
  const toX = (value) => xs.project(value);
  const toY = (value) => ys.project(value);

  const svg = node('svg', {
    viewBox: `0 0 ${width} ${height}`,
    class: 'curve',
    role: 'img',
    'aria-label': t('curve.aria', { y: yLabel, x: xLabel }),
  });

  for (const tick of ticksFor(ys)) {
    svg.append(
      node('line', {
        class: 'curve__grid',
        x1: PAD.left,
        x2: width - PAD.right,
        y1: toY(tick.value),
        y2: toY(tick.value),
      }),
    );
    const label = node('text', {
      class: 'curve__tick',
      x: PAD.left - 6,
      y: toY(tick.value) + 3.5,
      'text-anchor': 'end',
    });
    label.textContent = tick.label;
    svg.append(label);
  }
  for (const tick of ticksFor(xs)) {
    const label = node('text', {
      class: 'curve__tick',
      x: toX(tick.value),
      y: height - PAD.bottom + 16,
      'text-anchor': 'middle',
    });
    label.textContent = tick.label;
    svg.append(label);
  }

  for (const mark of marks) {
    if (mark.y !== undefined) {
      svg.append(
        node('line', {
          class: 'curve__mark',
          x1: PAD.left,
          x2: width - PAD.right,
          y1: toY(mark.y),
          y2: toY(mark.y),
        }),
      );
    }
    if (mark.x !== undefined) {
      svg.append(
        node('line', {
          class: 'curve__mark',
          x1: toX(mark.x),
          x2: toX(mark.x),
          y1: PAD.top,
          y2: height - PAD.bottom,
        }),
      );
    }
  }

  traces.forEach((trace, index) => {
    const usable = trace.points.filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));
    if (!usable.length) return;
    const path = usable.map(
      (p, i) => `${i ? 'L' : 'M'}${toX(p[0]).toFixed(2)},${toY(p[1]).toFixed(2)}`,
    );
    svg.append(
      node('path', {
        class: `curve__trace curve__trace--${index}`,
        d: path.join(' '),
        'stroke-dasharray': trace.dashed ? '4 3' : null,
      }),
    );
  });

  const xTitle = node('text', {
    class: 'curve__axis',
    x: PAD.left + plotW / 2,
    y: height - 2,
    'text-anchor': 'middle',
  });
  xTitle.textContent = xLabel;
  const yTitle = node('text', {
    class: 'curve__axis',
    x: 10,
    y: PAD.top + plotH / 2,
    'text-anchor': 'middle',
    transform: `rotate(-90 10 ${PAD.top + plotH / 2})`,
  });
  yTitle.textContent = yLabel;
  svg.append(xTitle, yTitle);

  container.append(svg);

  if (traces.length > 1) {
    container.append(
      el(
        'ul',
        { class: 'curve-legend' },
        ...traces.map((trace, index) =>
          el(
            'li',
            {},
            el('span', { class: `swatch swatch--trace-${index}` }),
            el('span', { text: trace.name }),
          ),
        ),
      ),
    );
  }
}
