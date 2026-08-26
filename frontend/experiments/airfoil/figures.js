/**
 * The diagrams the guided path's first three chapters are built around (ADR-021).
 *
 * Inline SVG, drawn with the same helpers the field overlay uses, for the same reason the
 * homepage thumbnails are real solves: a picture that was drawn by hand is a picture of what
 * somebody believed, and one generated from `naca.js` is a picture of the section the solver
 * is about to be handed. There is no illustration asset in this repository and this is how it
 * stays that way.
 *
 * The labels are translated like everything else a visitor reads (ADR-020) and live in the
 * string catalogue rather than here, so `scripts/check-i18n.mjs` can see them — hardcoded
 * English inside a drawing is exactly the kind of leak that checker exists to catch, and it
 * shipped in the first draft of this file.
 *
 * Every figure is `aria-hidden` at the call site, because each one illustrates a paragraph
 * sitting directly beside it — a screen reader that announced both would say the same thing
 * twice. Colours come from the stylesheet's tokens rather than being written in here, so dark
 * mode is handled by the same rules as everything else, and none of them encodes a magnitude:
 * they say which thing a line *is*, which is the rule the overlay palette already follows.
 */

import { t } from '/shared/i18n.js';
import { svgNode } from '/shared/workspace.js';
import { meanLine, outline, stations, surfacePoint } from './naca.js';

/** The section the diagrams describe. The page's own default, so the chapters and the bench
 *  open on the same shape and chapter 3 can name its digits. */
const SUBJECT = { m: 0.02, p: 0.4, t: 0.12 };

/**
 * A figure's frame: a `viewBox` in chord units, so every path below can be written in the
 * profile's own coordinates and never in pixels.
 */
function frame(host, viewBox, label) {
  const svg = svgNode('svg', {
    class: 'figure',
    viewBox,
    preserveAspectRatio: 'xMidYMid meet',
    role: 'img',
    'aria-label': label,
  });
  host.replaceChildren(svg);
  return svg;
}

function path(d, className) {
  return svgNode('path', { d, class: className });
}

/** A polyline through points already in figure coordinates. */
function line(points, className) {
  return path(
    points.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(4)},${y.toFixed(4)}`).join(' '),
    className,
  );
}

/**
 * The section itself, closed, in chord units with y already flipped for screen axes.
 *
 * `place` moves each point of the outline before it is drawn, which is how the flow figure
 * tilts its section without the drawing and the streamlines around it ever being computed in
 * different frames — the failure that put a streamline through the body once already.
 */
function sectionPath(shape, className = 'figure__section', place = (point) => point) {
  const points = outline(shape)
    .map(place)
    .map(([x, y]) => [x, -y]);
  return path(
    `${points.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(4)},${y.toFixed(4)}`).join(' ')} Z`,
    className,
  );
}

/**
 * A label, sized in the figure's own units.
 *
 * The size has to be passed rather than set in the stylesheet: these `viewBox`es are measured
 * in chord lengths and differ in width by more than two to one, so one CSS `font-size` renders
 * as a caption in the widest figure and as a headline in the narrowest. Anchoring is a
 * parameter for the same reason — a centred label is right above a symmetric thing and wrong
 * beside a leading edge.
 */
function text(x, y, content, className, size = 0.055, anchor = 'middle') {
  return svgNode(
    'text',
    { x, y, class: className, 'font-size': size, 'text-anchor': anchor },
    content,
  );
}

/* ------------------------------------------------------ 1. where the lift comes from */

/**
 * Streamlines parting around the section, crowding over its upper surface.
 *
 * **Schematic, and constructed rather than solved.** The real streamlines are one screen down,
 * integrated by the workspace from `vector_fields.velocity`; this figure exists to say what to
 * look for in them. But schematic is not the same as arbitrary, and the first draft of this
 * drawing ran its streamlines straight *through* the section, which is the precise opposite of
 * the thing the chapter beside it is explaining.
 *
 * So each line is displaced by the body instead of being drawn past it. A line whose
 * undisturbed height is `h` above the stream's own level is carried towards the surface at that
 * station, by less and less the further out it runs:
 *
 *     y(x) = ±h + surface(x) · exp(−h / REACH)
 *
 * Three things fall out of that, and all three are the chapter's content rather than
 * decoration. At `h = 0` the line *is* the surface, so nothing crosses the body. Neighbouring
 * lines are carried by slightly different amounts, so they **crowd** where the surface climbs
 * highest — which is the visual the words "the air speeds up over the top" refer to — and they
 * **spread** where it falls away, under a section that is holding its nose up. And ahead of the
 * nose and behind the tail, where there is no surface, the displacement relaxes back to the
 * stream's level over `TRAIL`, which is the upwash a lifting section pulls in front of itself
 * and the downwash it leaves behind.
 *
 * The picture shows level air and a nose-up section, which is the image the chapter's own
 * opening asks for — a hand tilted out of a car window. The *solver* does the opposite and
 * tilts the stream instead, keeping the section in its own axes (docs/exercises/airfoil.md
 * §5.1); the two differ by a rotation, and a rotation cannot change which side the air is
 * squeezed on. So the section is generated in the solver's convention and **the geometry** is
 * tilted into the picture, once, by `place` — the streamlines are then built from those same
 * tilted points and can no longer disagree with the shape they are drawn around. Tilting the
 * *frame* instead is what the version before this one did, and it left the two out of step: the
 * streamlines carried the stream's slope and the section, drawn flat inside the same rotated
 * group, did not, so the pair that should have hugged the surfaces ran an eighth of a chord above
 * the back of the section and straight through its tail.
 */
export function drawFlowFigure(host) {
  // Tall enough for the two notes to sit clear of the outermost streamline: the upwash lifts
  // the whole family a little, and a label with a line through it is a label that is read twice.
  const svg = frame(host, '-0.35 -0.51 1.85 1.02', t('airfoil.figures.flowAria'));
  const shape = { ...SUBJECT, m: 0.03 };
  /** Angle of attack for the picture, radians. */
  const ALPHA = 0.13;
  /** How far from the surface the body is still felt. */
  const REACH = 0.3;
  /** How far ahead of the nose and behind the tail the section is still felt. */
  const TRAIL = 0.45;
  /** The section turns about its mid-chord, so it stays in the middle of the frame and the
   *  surface it presents to the air above it is the taller of the two. */
  const PIVOT = 0.5;

  // A point of the section, in the solver's axes, put where the picture wants it: the stream
  // level and the section nose-up, which is the same scene the solver describes the other way
  // round. Physical axes here — y is flipped once, at the end, by whatever draws the point.
  const cos = Math.cos(ALPHA);
  const sin = Math.sin(ALPHA);
  const place = ([x, y]) => [(x - PIVOT) * cos + y * sin + PIVOT, -(x - PIVOT) * sin + y * cos];

  // Each surface, tilted, as a curve the streamlines can be read off. Sorted by station because
  // the tilt moves points along the chord as well as across it, by different amounts on the two
  // surfaces, and a table read by interpolation has to be in order.
  const surfaces = new Map(
    [+1, -1].map((sign) => [
      sign,
      stations(80)
        .map((x) => place(surfacePoint(x, shape, sign)))
        .sort((a, b) => a[0] - b[0]),
    ]),
  );

  /** Where the line that runs along one surface is, at station `x`. */
  const surfaceAt = (x, sign) => {
    const points = surfaces.get(sign);
    const nose = points[0];
    const tail = points[points.length - 1];
    if (x <= nose[0]) return nose[1] * Math.exp((x - nose[0]) / TRAIL);
    if (x >= tail[0]) return tail[1] * Math.exp(-(x - tail[0]) / TRAIL);
    let i = 1;
    while (i < points.length - 1 && points[i][0] < x) i += 1;
    const [x0, y0] = points[i - 1];
    const [x1, y1] = points[i];
    return x1 === x0 ? y1 : y0 + ((y1 - y0) * (x - x0)) / (x1 - x0);
  };

  // One family per side. Both start at h = 0, so the dividing streamline is drawn twice — once
  // along each surface — which is what the stagnation point at the nose actually looks like.
  for (const sign of [+1, -1]) {
    for (let k = 0; k <= 5; k += 1) {
      const h = k * 0.075;
      /** How much of the body this line still feels. One on the surface, nothing far out. */
      const felt = Math.exp(-h / REACH);
      const points = [];
      for (let i = 0; i <= 120; i += 1) {
        const x = -0.35 + (i / 120) * 1.85;
        points.push([x, -(sign * h + surfaceAt(x, sign) * felt)]);
      }
      svg.append(line(points, `figure__stream${k <= 1 ? ' figure__stream--near' : ''}`));
    }
  }

  svg.append(sectionPath(shape, 'figure__section', place));

  // Faster above, slower below — as words, because an arrow labelled "faster" is a claim the
  // reader can check against the streamline spacing right beside it.
  svg.append(text(0.42, -0.44, t('airfoil.figures.faster'), 'figure__note figure__note--low'));
  svg.append(text(0.42, 0.47, t('airfoil.figures.slower'), 'figure__note figure__note--high'));
  return svg;
}

/* ------------------------------------------------------------- 2. a slice of a wing */

/**
 * A wing, the plane that cuts across it, and the outline that falls out.
 *
 * The wing is drawn in the crudest possible projection: the chord runs across the picture, the
 * span runs away from the reader up and to the right, and the planform tapers and sweeps
 * towards the tip the chapter says a real wing has. Nothing here is measured — it is a wing
 * because it reads as one — but the *cut* is not free, and the version before this one got it
 * wrong: it drew the plane along the span, a thin slab standing lengthwise down the wing, which
 * is a plane that has no section to leave. A slice is taken **across** the span, so the plane
 * that takes it is the one spanned by the chord and the thickness. In this projection that is a
 * plain upright rectangle, and where it crosses the wing it leaves a trace running nose to tail
 * — the outline drawn to the right of it.
 */
export function drawSliceFigure(host) {
  const svg = frame(host, '0 0 2.4 1.0', t('airfoil.figures.sliceAria'));

  // The wing: a tapered, swept plate with a little thickness, seen from in front and above.
  // The short chord at the top is the tip — one of the two things the chapter says a real wing
  // has and this page does not model, the other being everything that happens there.
  const rootNose = [0.08, 0.84];
  const rootTail = [0.86, 0.84];
  const tipNose = [0.66, 0.3];
  const tipTail = [1.04, 0.3];
  /** The plate's thickness, as this projection shows it: straight down the picture. */
  const DEEP = 0.06;
  const quad = (corners, className) =>
    path(`M${corners.map((point) => point.join(',')).join(' L')} Z`, className);
  const under = ([x, y]) => [x, y + DEEP];
  const wing = [
    // The two faces this viewpoint can see: the root end, and the trailing edge. The tip's own
    // face is on the far side of the plate and is not drawn, which is what makes it read as
    // depth rather than as a second wing.
    quad([rootNose, rootTail, under(rootTail), under(rootNose)], 'figure__wing'),
    quad([rootTail, tipTail, under(tipTail), under(rootTail)], 'figure__wing'),
    // The upper surface, last, so it sits over both.
    quad([rootNose, rootTail, tipTail, tipNose], 'figure__wing'),
  ];

  // Where the cut lands: the same fraction of the way out along both the leading and the
  // trailing edge, which is what "a station along the span" means and is why the trace it
  // leaves runs along the chord rather than along anything else in the picture.
  const STATION = 0.45;
  const along = (from, to) => [
    from[0] + (to[0] - from[0]) * STATION,
    from[1] + (to[1] - from[1]) * STATION,
  ];
  const cutNose = along(rootNose, tipNose);
  const cutTail = along(rootTail, tipTail);
  /** How far past the wing the plane reaches, so it reads as a plane and not as a patch. */
  const OVERHANG = 0.07;
  /** Half the plane's height. It is a plane, so where it stops is a matter of drawing. */
  const REACH = 0.14;
  const left = (cutNose[0] - OVERHANG).toFixed(4);
  const right = (cutTail[0] + OVERHANG).toFixed(4);
  const top = (cutNose[1] - REACH).toFixed(4);
  const bottom = (cutNose[1] + REACH).toFixed(4);

  // The plane goes down first and the wing over it, so the wing is never hidden by the thing
  // that cuts it; the trace goes on top of both, because it is what the section is.
  svg.append(
    path(
      `M${left},${top} L${right},${top} L${right},${bottom} L${left},${bottom} Z`,
      'figure__plane',
    ),
    ...wing,
    path(`M${cutNose.join(',')} L${cutTail.join(',')}`, 'figure__cut'),
    text(0.64, 0.98, t('airfoil.figures.oneSlice'), 'figure__note'),
  );

  // The section it leaves, drawn from the formula rather than sketched.
  const group = svgNode('g', { transform: 'translate(1.3 0.5) scale(1.0)' });
  group.append(sectionPath(SUBJECT));
  group.append(path('M0,0 L1,0', 'figure__chord'));
  svg.append(group);
  svg.append(text(1.8, 0.8, t('airfoil.figures.perMetre'), 'figure__note'));
  svg.append(
    svgNode('path', {
      d: 'M1.09,0.5 L1.24,0.5',
      class: 'figure__arrow',
      'marker-end': 'url(#figure-arrow)',
    }),
  );
  return svg;
}

/* ------------------------------------------------------------ 3. the four digits */

/**
 * The anatomy of a four-digit section: the chord, the mean line, and the two measurements the
 * digits are.
 *
 * A section is only about 12 % as tall as it is long, so a figure drawn to scale is a sliver
 * with no room for a label. The `viewBox` is therefore much taller than the shape, and every
 * label is tied to the thing it names by a leader — the alternative, floating captions near
 * the right area, is what the first version of this drawing did, and it left "12 % thick"
 * sitting under the nose pointing at nothing.
 */
export function drawNacaFigure(host) {
  const svg = frame(host, '-0.16 -0.4 1.36 0.86', t('airfoil.figures.nacaAria'));
  const shape = SUBJECT;
  const SIZE = 0.052;
  /** Where the four-digit thickness distribution peaks — always 30 % of the chord. */
  const THICKEST = 0.3;

  svg.append(sectionPath(shape, 'figure__section figure__section--open'));

  // The chord: nose to tail in a straight line, and what every percentage is a fraction of.
  svg.append(path('M0,0 L1,0', 'figure__chord'));
  svg.append(text(0.68, 0.075, t('airfoil.figures.chord'), 'figure__note', SIZE * 0.92));

  // The mean line, from the same function the solver's geometry reader recovers from an outline.
  svg.append(
    line(
      stations(60).map((x) => [x, -meanLine(x, shape.m, shape.p).y]),
      'figure__mean',
    ),
  );

  // First digit: how high the mean line climbs. Second: where it does it. The leader turns
  // right and the label runs from there, so it clears the thickness label above rather than
  // being stacked on top of it — the two used to collide.
  const peakY = -meanLine(shape.p, shape.m, shape.p).y;
  svg.append(
    path(`M${shape.p},0.115 L${shape.p},${(peakY + 0.012).toFixed(4)}`, 'figure__tick'),
    text(shape.p, 0.175, t('airfoil.figures.secondDigit'), 'figure__note', SIZE * 0.92),
    path(
      `M${shape.p},${peakY.toFixed(4)} L${shape.p},-0.17 L${shape.p + 0.09},-0.17`,
      'figure__tick figure__tick--mean',
    ),
    text(
      shape.p + 0.11,
      -0.152,
      t('airfoil.figures.firstDigit'),
      'figure__note figure__note--mean',
      SIZE,
      'start',
    ),
  );

  // Last two digits: the greatest thickness, measured across the section where it is thickest.
  const upper = surfacePoint(THICKEST, shape, +1);
  const lower = surfacePoint(THICKEST, shape, -1);
  svg.append(
    path(
      `M${upper[0].toFixed(4)},${(-upper[1]).toFixed(4)} L${lower[0].toFixed(4)},${(-lower[1]).toFixed(4)}`,
      'figure__tick figure__tick--thick',
    ),
    path(`M${THICKEST},${(-upper[1]).toFixed(4)} L${THICKEST - 0.03},-0.29`, 'figure__tick'),
    text(
      THICKEST + 0.02,
      -0.315,
      t('airfoil.figures.lastTwo'),
      'figure__note figure__note--thick',
      SIZE,
      'middle',
    ),
  );

  svg.append(
    text(-0.02, 0.02, t('airfoil.figures.nose'), 'figure__note', SIZE * 0.92, 'end'),
    text(1.03, 0.02, t('airfoil.figures.tail'), 'figure__note', SIZE * 0.92, 'start'),
  );
  return svg;
}

/**
 * The one shared SVG definition the figures need: an arrowhead.
 *
 * `marker-end` refers to it by id, so it has to exist in the document once. Kept here rather
 * than in the markup so a page gains it by importing the figures, and a page that never draws
 * one never carries it.
 */
export function mountFigureDefs(root) {
  if (root.querySelector('#figure-defs')) return;
  const svg = svgNode('svg', { id: 'figure-defs', width: '0', height: '0', 'aria-hidden': 'true' });
  const marker = svgNode('marker', {
    id: 'figure-arrow',
    viewBox: '0 0 10 10',
    refX: '9',
    refY: '5',
    markerWidth: '5',
    markerHeight: '5',
    orient: 'auto-start-reverse',
  });
  marker.append(svgNode('path', { d: 'M0,0 L10,5 L0,10 Z', class: 'figure__arrowhead' }));
  svg.append(svgNode('defs', {}, marker));
  root.prepend(svg);
}
