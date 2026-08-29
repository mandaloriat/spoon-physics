/**
 * The gap sensor, in a browser — and the one flow here that no other test can stand in for.
 *
 * The Python suite proves the calibration and proves that the envelope carries a curve. What it
 * cannot prove is the claim this page rests on: that **one press is a sweep**, that what comes
 * back is a curve a visitor can look at beside the measurement it is checked against, and that
 * the three numbers in the rail are read off that curve rather than off any one field.
 *
 * If this file fails, the likely cause is not the physics. It is that `series` did not reach the
 * page — it is not in the default result level, so a page that forgot to ask for it by name gets
 * the metrics, no plot, and no sign that anything is missing.
 *
 *   BASE_URL=http://127.0.0.1:8000 npx playwright test sensor
 */

import { expect, test } from '@playwright/test';

/** A sweep is several solves, so the waits are generous on purpose. */
const SOLVE = { timeout: 120_000 };

async function calibrate(page) {
  await page.goto('/experiments/sensor/');
  await expect(page.locator('#run')).toBeEnabled();
  await page.click('#run');
  await expect(page.locator('#kpis .kpi').first()).toBeVisible(SOLVE);
}

test('one press sweeps the gap, and the curve comes back with the measurement beside it', async ({
  page,
}) => {
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await calibrate(page);

  // The three headline numbers, and the middle one is the design problem: the P45 sensor as
  // built lands just under its stroke target, so the bench opens with something to do.
  const kpis = page.locator('#kpis .kpi');
  await expect(kpis).toHaveCount(3);
  await expect(kpis.nth(0)).toHaveClass(/is-met/);
  await expect(kpis.nth(1)).toHaveClass(/is-missed/);
  await expect(page.locator('#hint')).toContainText(/short of a straight/);

  // The curve itself. Four traces: what was solved, the fit through it, the 2015 measurement,
  // and the parallel plate that the whole exercise is about being above.
  await page.click('#model-details [data-drawer="curve-panel"]');
  const calibration = page.locator('#calibration-curve svg');
  await expect(calibration).toBeVisible();
  // Three traces: what was solved, the 2015 measurement, and the parallel plate the whole
  // exercise is about being above. The envelope carries a fourth — the fit — which the page
  // does not draw because it lies on top of the solved points; see `drawCalibration`.
  await expect(calibration.locator('path.curve__trace')).toHaveCount(3);
  await expect(page.locator('#calibration-note')).toContainText(/2015/);

  // And the tilt, which is drawn beside it and is *inferred* rather than solved — the page
  // says so, and this is the assertion that the claim is on the page rather than only in the
  // commit that made it.
  await expect(page.locator('#tilt-curve svg')).toBeVisible();
  await expect(page.locator('#tilt-panel')).toContainText(/inferred, not solved/);
  await expect(page.locator('#tilt-metrics')).toContainText('0.09 nF/deg²');

  expect(errors, errors.join('\n')).toEqual([]);
});

test('the picture is labelled as a meridian section, not as a plane one', async ({ page }) => {
  // §6 of the exercise, and the one thing the workspace cannot know for itself: it draws a
  // plane domain, and here the horizontal axis is a radius. A page that let that pass would be
  // teaching a slice through a body of revolution as though it were a slab.
  await page.goto('/experiments/sensor/');
  await expect(page.locator('#section-note')).toBeVisible();
  await expect(page.locator('#section-note')).toContainText(/radius/);
  await expect(page.locator('#section-note')).toContainText(/360/);
});

test('the four checks arrive in the envelope, with no report artifact to fetch', async ({
  page,
}) => {
  // ADR-015's direction, asserted from the outside: this exercise writes no `report.json` at
  // all, so every number in the checks panel came back with the field. A page that had quietly
  // gone back to fetching an artifact would still show these rows — and would be one round
  // trip and one contract heavier for it.
  const artifacts = [];
  page.on('request', (request) => {
    if (/\/artifacts?\//.test(request.url())) artifacts.push(request.url());
  });

  await calibrate(page);
  await page.click('#model-details [data-drawer="checks-panel"]');
  await page.click('#checks summary');

  const rows = page.locator('#verification tr');
  await expect(rows).toHaveCount(4);
  for (let index = 0; index < 4; index += 1) {
    await expect(rows.nth(index)).toHaveClass(/is-met/);
  }
  // The external one, named: the benchmark is the only check here that is not the model
  // agreeing with itself.
  await expect(page.locator('#verification')).toContainText(/2015/);
  expect(artifacts).toEqual([]);
});

test('a sensor that cannot exist is refused on the control, not in a job', async ({ page }) => {
  // Two chamfers of 1.5 mm cannot both fit in a 2 mm annulus, and the solver says so. The page
  // would rather spend a sentence than a job learning it — and the button goes down with the
  // reason beside it rather than vanishing, which is ADR-017's rule.
  const submissions = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().includes('/jobs')) submissions.push(1);
  });

  await page.goto('/experiments/sensor/');
  await expect(page.locator('#run')).toBeEnabled();

  await page.locator('#advanced summary').click();
  // Bring the inner radius out until the annulus is too narrow for the chamfers it carries.
  const inner = page.locator('#shape-innerRadius');
  await inner.fill('14');
  await inner.dispatchEvent('input');

  await expect(page.locator('#run')).toBeDisabled();
  await expect(page.locator('#design-note')).toContainText(/chamfers/);
  expect(submissions).toEqual([]);
});
