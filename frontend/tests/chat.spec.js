import { test, expect } from '@playwright/test'

test('Vue chat uses WebSocket and HTTP, runs tools, persists and deletes sessions', async ({
  page,
}) => {
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/')
  await expect(page.getByText('browser-fixture', { exact: true })).toBeVisible()
  await expect(page.getByText('模型已配置', { exact: true })).toBeVisible()
  await page.getByLabel('消息内容').fill('计算 2+3')
  await page.getByRole('button', { name: '发送 ↑' }).click()
  await expect(page.locator('.assistant .message-text')).toHaveText('结果是 5')
  await expect(page.getByText('结果：5.0', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '停止生成' })).toHaveCount(0)
  await page.getByLabel('连接方式').selectOption('http')
  await page.getByLabel('消息内容').fill('再计算一次')
  await page.getByRole('button', { name: '发送 ↑' }).click()
  await expect(page.locator('.assistant .message-text')).toHaveCount(2)
  await expect(page.locator('.assistant .message-text').last()).toHaveText('结果是 5')
  await expect(page.getByRole('button', { name: '停止生成' })).toHaveCount(0)
  await page.reload()
  await expect(page.locator('.assistant .message-text')).toHaveCount(2)
  await page.getByRole('button', { name: '新建会话' }).click()
  await expect(page.getByRole('heading', { name: '从一个问题开始' })).toBeVisible()
  await page
    .getByRole('navigation', { name: '会话列表' })
    .getByRole('button')
    .filter({ hasText: '计算 2+3' })
    .click()
  await expect(page.locator('.assistant .message-text')).toHaveCount(2)
  await page.getByRole('button', { name: '删除当前会话' }).click()
  await expect(page.locator('.assistant .message-text')).toHaveCount(0)
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  expect(errors).toEqual([])
})

for (const transport of ['websocket', 'http']) {
  test(`cancel ${transport} leaves no partial conversation and allows retry`, async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: '新建会话' }).click()
    await page.getByLabel('连接方式').selectOption(transport)
    await page.getByLabel('消息内容').fill('慢请求')
    await page.getByRole('button', { name: '发送 ↑' }).click()
    await page.getByRole('button', { name: '停止生成' }).click()
    await expect(page.getByRole('alert')).toContainText('已停止生成')
    await expect(page.locator('.message')).toHaveCount(0)
    await page.getByLabel('消息内容').fill('重试 2+3')
    await page.getByRole('button', { name: '发送 ↑' }).click()
    await expect(page.locator('.assistant .message-text')).toHaveText('结果是 5')
  })
}

test('JSON preferences and non-streaming model mode reach the Vue workspace', async ({ page }) => {
  await page.route('**/api/v1/agent', async (route) => {
    const response = await route.fetch()
    const status = await response.json()
    status.streaming = false
    status.frontend.default_transport = 'http'
    status.frontend.cancel_timeout_ms = 2000
    status.limits.max_input_chars = 100
    await route.fulfill({ response, json: status })
  })
  await page.goto('/')
  await expect(page.getByText('非流式输出', { exact: true })).toBeVisible()
  await expect(page.getByLabel('连接方式')).toHaveValue('http')
  await expect(page.getByLabel('消息内容')).toHaveAttribute('maxlength', '100')
})
