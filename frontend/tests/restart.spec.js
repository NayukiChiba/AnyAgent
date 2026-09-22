import { test, expect } from '@playwright/test'

test('web restart waits for a new ready instance before reopening settings', async ({ page }) => {
  let polling = false
  let checks = 0
  await page.route('**/api/v1/system', (route) => {
    if (polling) checks++
    return route.fulfill({
      json: {
        ready: true,
        restart_available: true,
        restarting: polling && checks < 2,
        instance_id: checks >= 2 ? 'new-instance' : 'old-instance',
      },
    })
  })
  await page.route('**/api/v1/system/restart', (route) => {
    polling = true
    return route.fulfill({ status: 202, json: { instance_id: 'old-instance', port: 18765 } })
  })
  await page.goto('/settings')
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: '重启服务', exact: true }).click()
  await expect(page.locator('.restart-feedback')).toContainText('正在重启')
  await expect(page.getByRole('button', { name: '正在重启…' })).toBeDisabled()
  await page.waitForEvent('load')
  expect(checks).toBeGreaterThanOrEqual(2)
  await expect(page.getByRole('heading', { name: '网页偏好' })).toBeVisible()
})
