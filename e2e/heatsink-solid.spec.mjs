/**
 * The heat sink with a third dimension, in a browser.
 *
 * This is the one flow in the lab that no other test can stand in for. The Python suite proves
 * the solver and proves that a `slice` of a `mesh3d` is a `grid2d`; what it cannot prove is the
 * claim the whole design rests on — that a solid is therefore *drawable here*, with no new
 * rendering code, by asking the server for a plane and handing the answer to the same widget
 * that has drawn every other field on this site.
 *
 * If this file fails, the likely cause is not the physics. It is that a solid result reached the
 * canvas renderer directly, which draws nothing and says nothing.
 *
 *   BASE_URL=http://127.0.0.1:8000 npx playwright test heatsink-solid
 */

import { expect, test } from '@playwright/test';

/** The solve is seconds rather than milliseconds, so the waits are generous on purpose. */
const SOLVE = { timeout: 120_000 };

async function chooseTheSolid(page) {
  await page.goto('/experiments/heatsink/');
  await expect(page.locator('#solver')).toBeEnabled();
  // Two capabilities, and the page has to be offering both before this test means anything.
  await expect(page.locator('#solver option')).toHaveCount(2);
  await page.selectOption('#solver', 'lab.heatsink3d');
}

test('a solid is solved, cut, and drawn by the widget that draws planes', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await chooseTheSolid(page);

  // The control that only exists once there is a length to be shorter than.
  await expect(page.locator('#solid-controls input[type="range"]')).toHaveCount(1);
  // And the one that stops making sense: twenty solves of a body is not a sweep.
  await expect(page.locator('#sweep')).toBeDisabled();

  await page.click('#run');
  await expect(page.locator('#plane-note')).not.toBeEmpty(SOLVE);

  // What the solver returned, and what the viewer was actually given. The two differ on
  // purpose, and that difference is the whole browser story for three dimensions.
  const viewer = await page.evaluate(() => {
    const element = document.querySelector('#viewer');
    return { kind: element.result?.kind, fields: element.fields, field: element.field };
  });
  expect(viewer.kind).toBe('grid2d');
  expect(viewer.fields).toEqual(['T', 'flux']);

  // The four numbers the cross-section has no way to produce.
  const metrics = await page.locator('#metrics').textContent();
  expect(metrics).toContain('Spreading resistance');
  expect(metrics).toContain('Resistance, extruded model');
  expect(metrics).not.toContain('needs the whole body');

  expect(errors).toEqual([]);
});

test('cutting through the base shows the spread the section could not', async ({ page }) => {
  await chooseTheSolid(page);
  await page.click('#run');
  await expect(page.locator('#plane-note')).not.toBeEmpty(SOLVE);

  // The default cut is the cross-section, because that is the picture a visitor already knows.
  await expect(page.locator('#plane-axis')).toHaveValue('z');
  await expect(page.locator('#plane-note')).toContainText('cross-section');

  await page.selectOption('#plane-axis', 'y');
  await expect(page.locator('#plane-note')).toContainText('above the base', SOLVE);

  // A plane through the base is not isothermal, and that is the finding: the metal under the
  // device is hotter than the metal at the ends, and the difference is what a resistance
  // computed per unit depth left out.
  const spread = await page.evaluate(() => {
    const values = document.querySelector('#viewer').result.data.fields.T.filter(Number.isFinite);
    return Math.max(...values) - Math.min(...values);
  });
  expect(spread).toBeGreaterThan(0.2);
});

test('the section keeps its sweep, and says nothing about a spreading it cannot see', async ({
  page,
}) => {
  await page.goto('/experiments/heatsink/');
  await expect(page.locator('#solver')).toHaveValue('lab.heatsink2d');
  await expect(page.locator('#sweep')).toBeEnabled();
  await expect(page.locator('#plane-panel')).toBeHidden();

  await page.click('#run');
  await expect(page.locator('#status')).toContainText('Done', SOLVE);

  // Absent rather than zero. A section run did not measure a small spreading resistance; it
  // had no way to ask, and the panel says which of the two it is.
  await expect(page.locator('#metrics')).toContainText('needs the whole body');
});
