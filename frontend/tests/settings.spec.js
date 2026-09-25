import { test, expect } from '@playwright/test'

async function savedGroup(request, name) {
  const response = await request.get('/api/v1/settings')
  return (await response.json()).groups.find((group) => group.name === name)
}
async function restore(request, original) {
  const latest = await savedGroup(request, original.name)
  await request.put(`/api/v1/settings/${original.name}`, {
    data: { revision: latest.revision, values: original.values },
  })
}

test('configuration groups render with validation, dirty guards and restart feedback', async ({
  page,
  request,
}) => {
  const original = await savedGroup(request, 'cmd_config')
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  try {
    await page.goto('/settings')
    // 默认展示网页偏好；模型连接与执行引擎已由 Runner 管理接管
    await expect(page.getByRole('heading', { name: '网页偏好' })).toBeVisible()
    await expect(page.getByRole('button', { name: '模型连接' })).toHaveCount(0)
    // 统一侧栏在管理页展示管理导航，分类导航为主区内的 pill 按钮
    const sidebar = page.locator('.sidebar')
    await expect(sidebar).toHaveCSS('background-color', 'rgb(16, 16, 20)')
    await expect(sidebar.getByRole('tab', { name: '管理' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    await expect(sidebar.getByRole('link', { name: '设置', exact: true })).toHaveClass(/active/)
    await expect(page.locator('.settings-pills')).toBeVisible()
    await expect(page.locator('.hot-reload-notice')).toHaveCSS(
      'background-color',
      'rgb(255, 251, 235)',
    )
    await page.getByRole('button', { name: '系统设置', exact: true }).click()
    await expect(page.locator('.restart-required-notice')).toHaveCSS(
      'background-color',
      'rgb(254, 242, 242)',
    )
    for (const name of ['Agent 行为', '会话存储', '日志', '服务'])
      await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
    await expect(page.getByText('高级设置')).toHaveCount(0)
    await expect(page.getByLabel('执行引擎')).toHaveCount(0)
    await page.getByLabel('服务端口').fill('0')
    await expect(page.getByText('已修改配置，请点击保存')).toBeVisible()
    await expect(page.locator('.settings-action-dock')).toHaveCSS('position', 'fixed')
    await expect(page.locator('.settings-action-dock')).toHaveCSS('flex-direction', 'column')
    await page.getByRole('button', { name: '保存设置', exact: true }).click()
    await expect(page.getByRole('alert').first()).toContainText('请检查标出的设置')
    await expect(page.getByLabel('服务端口')).toHaveAttribute('aria-invalid', 'true')
    expect((await savedGroup(request, 'cmd_config')).values.server.port).toBe(
      original.values.server.port,
    )
    page.once('dialog', (dialog) => dialog.dismiss())
    await page.getByRole('button', { name: '网页偏好', exact: true }).click()
    await expect(page.getByRole('heading', { name: '系统设置', exact: true })).toBeVisible()
    await page.getByRole('button', { name: '撤销修改' }).click()
    await page.getByLabel('服务端口').fill('9001')
    await page.getByRole('button', { name: '保存设置', exact: true }).click()
    await expect(page.getByRole('status')).toContainText('需要重启服务')
    // 恢复默认值：先把网页偏好改为非默认值并保存，恢复默认后才产生可撤销的修改
    await page.getByRole('button', { name: '网页偏好', exact: true }).click()
    await expect(page.getByRole('heading', { name: '网页偏好', exact: true })).toBeVisible()
    await page.getByRole('combobox', { name: '默认连接方式' }).click()
    await page.getByRole('option', { name: 'HTTP（SSE）', exact: true }).click()
    await page.getByRole('button', { name: '保存设置', exact: true }).click()
    await expect(page.getByRole('status')).toContainText('设置已保存')
    page.once('dialog', (dialog) => dialog.accept())
    await page.getByRole('button', { name: '恢复网页偏好默认值' }).click()
    await expect(page.getByRole('combobox', { name: '默认连接方式' })).toHaveText('WebSocket')
    await expect(page.getByText('已修改配置，请点击保存')).toBeVisible()
    await page.getByRole('button', { name: '撤销修改' }).click()
    await expect(page.getByRole('combobox', { name: '默认连接方式' })).toHaveText('HTTP（SSE）')
    await page.setViewportSize({ width: 390, height: 844 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    expect(errors).toEqual([])
  } finally {
    await restore(request, original)
    const frontend = await savedGroup(request, 'frontend_config')
    await request.put('/api/v1/settings/frontend_config', {
      data: { revision: frontend.revision, values: { default_transport: 'websocket' } },
    })
  }
})

test('saving webpage preferences hot reloads an open chat view', async ({
  page,
  context,
  request,
}) => {
  const original = await savedGroup(request, 'frontend_config')
  const nextTransport = original.values.default_transport === 'websocket' ? 'http' : 'websocket'
  const nextLabel = nextTransport === 'http' ? 'HTTP（SSE）' : 'WebSocket'
  const expectedChatLabel = nextTransport === 'http' ? 'HTTP · SSE' : 'WebSocket'
  const settingsPage = await context.newPage()
  try {
    await page.goto('/')
    await settingsPage.goto('/settings')
    await settingsPage.getByRole('button', { name: '网页偏好', exact: true }).click()
    await expect(settingsPage.locator('.hot-reload-notice')).toContainText('不需要重启服务')
    await settingsPage.getByLabel('默认连接方式').click()
    await settingsPage.getByRole('option', { name: nextLabel, exact: true }).click()
    await settingsPage.getByRole('button', { name: '保存设置', exact: true }).click()
    await expect(settingsPage.getByRole('status')).toContainText('设置已保存')
    await expect(page.getByLabel('连接方式')).toHaveText(expectedChatLabel)
  } finally {
    await settingsPage.close()
    await restore(request, original)
  }
})

test('unified sidebar switches between session and management modes', async ({ page }) => {
  await page.goto('/')
  const sidebar = page.locator('.sidebar')
  // 对话页默认会话模式：会话列表与新建按钮可见
  await expect(sidebar.getByRole('tab', { name: '会话' })).toHaveAttribute('aria-selected', 'true')
  await expect(sidebar.getByRole('button', { name: '新建会话' })).toBeVisible()
  // 切到管理模式：跳转 Runner 页并展示管理导航
  await sidebar.getByRole('tab', { name: '管理' }).click()
  await expect(page).toHaveURL(/\/runners$/)
  for (const name of ['Runner 管理', '模型', '日志', '设置'])
    await expect(sidebar.getByRole('link', { name, exact: true })).toBeVisible()
  await sidebar.getByRole('link', { name: '设置', exact: true }).click()
  await expect(page).toHaveURL(/\/settings$/)
  await page.screenshot({ path: '/tmp/anyagent-settings-desktop.png', fullPage: true })
  // 下拉控件键盘操作
  const select = page.getByRole('combobox', { name: '默认连接方式', exact: true })
  await select.focus()
  await select.press('ArrowDown')
  await expect(select).toHaveAttribute('aria-expanded', 'true')
  await page.screenshot({ path: '/tmp/anyagent-settings-dropdown.png', fullPage: true })
  await select.press('ArrowDown')
  await select.press('Escape')
  await expect(select).toHaveText('WebSocket')
  await select.press('ArrowDown')
  await select.press('End')
  await select.press('Enter')
  await expect(select).toHaveText('HTTP（SSE）')
  await page.getByRole('button', { name: '撤销修改' }).click()
  // 移动端布局
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: '/tmp/anyagent-settings-mobile.png', fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  // 切回会话模式返回对话页
  await sidebar.getByRole('tab', { name: '会话' }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(sidebar.getByRole('button', { name: '新建会话' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
