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

test('settings save a model, preserve its key, test the SDK connection and open non-streaming chat', async ({
  page,
  request,
}) => {
  const original = await savedGroup(request, 'model_config')
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  try {
    await page.goto('/')
    await page.getByRole('link', { name: '设置', exact: true }).click()
    await expect(page).toHaveURL(/\/settings$/)
    await expect(page.getByRole('heading', { name: '模型连接' })).toBeVisible()
    await expect(page.getByLabel('API Key', { exact: true })).toHaveValue('')
    await expect(page.getByLabel('API Key', { exact: true })).toHaveAttribute(
      'placeholder',
      '密钥已保存，留空保留',
    )
    await page.getByLabel('流式输出', { exact: true }).uncheck()
    await expect(page.getByRole('button', { name: '测试已保存的连接' })).toBeDisabled()
    await page.getByRole('button', { name: '保存设置', exact: true }).click()
    await expect(page.getByRole('status')).toContainText('设置已保存')
    await page.reload()
    await expect(page.getByLabel('流式输出', { exact: true })).not.toBeChecked()
    await expect(page.getByLabel('API Key', { exact: true })).toHaveValue('')
    const before = await (await request.get('/api/v1/sessions')).json()
    await page.getByRole('button', { name: '测试已保存的连接' }).click()
    await expect(page.getByRole('status')).toContainText('模型连接正常')
    expect(await (await request.get('/api/v1/sessions')).json()).toEqual(before)
    await page.getByRole('link', { name: '返回聊天' }).click()
    await expect(page.getByText('非流式输出', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: '新建会话' }).click()
    await page.getByLabel('消息内容').fill('计算 2+3')
    await page.getByRole('button', { name: '发送 ↑' }).click()
    await expect(page.locator('.assistant .message-text')).toHaveText('结果是 5')
    await expect(page.getByText('结果：5.0', { exact: true })).toBeVisible()
    expect(errors).toEqual([])
  } finally {
    await restore(request, original)
  }
})

test('all configuration groups render with validation, dirty guards and restart feedback', async ({
  page,
  request,
}) => {
  const original = await savedGroup(request, 'cmd_config')
  try {
    await page.goto('/settings')
    await page.getByRole('button', { name: '服务', exact: true }).click()
    await page.getByLabel('服务端口').fill('0')
    await page.getByRole('button', { name: '保存设置', exact: true }).click()
    await expect(page.getByRole('alert').first()).toContainText('请检查标出的设置')
    await expect(page.getByLabel('服务端口')).toHaveAttribute('aria-invalid', 'true')
    expect((await savedGroup(request, 'cmd_config')).values.server.port).toBe(
      original.values.server.port,
    )
    page.once('dialog', (dialog) => dialog.dismiss())
    await page.getByRole('button', { name: '网页偏好', exact: true }).click()
    await expect(page.getByRole('heading', { name: '服务', exact: true })).toBeVisible()
    await page.getByRole('button', { name: '撤销修改' }).click()
    await page.getByLabel('服务端口').fill('9001')
    await page.getByRole('button', { name: '保存设置', exact: true }).click()
    await expect(page.getByRole('status')).toContainText('需要重启服务')
    for (const name of ['Agent 行为', '网页偏好', '会话存储', '日志', '模型连接']) {
      await page.getByRole('button', { name, exact: true }).click()
      await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
    }
    page.once('dialog', (dialog) => dialog.accept())
    await page.getByRole('button', { name: '恢复本组默认值' }).click()
    await expect(page.getByLabel('启用模型')).not.toBeChecked()
    await expect(page.getByLabel('模型名称', { exact: true })).toHaveValue('')
    await expect(page.getByLabel('API Key', { exact: true })).toHaveAttribute(
      'placeholder',
      '密钥已保存，留空保留',
    )
    await page.getByRole('button', { name: '撤销修改' }).click()
    await expect(page.getByLabel('启用模型')).toBeChecked()
    await page.setViewportSize({ width: 390, height: 844 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  } finally {
    await restore(request, original)
  }
})

test('first use configures a disabled model entirely in the web UI', async ({ page, request }) => {
  const original = await savedGroup(request, 'model_config')
  try {
    await request.put('/api/v1/settings/model_config', {
      data: {
        revision: original.revision,
        values: { enabled: false, model: '' },
        clear_api_key: true,
      },
    })
    await page.goto('/')
    await page.getByRole('link', { name: '打开设置' }).click()
    await expect(page.getByLabel('启用模型')).not.toBeChecked()
    await page.getByLabel('模型名称', { exact: true }).fill('browser-fixture')
    await page.getByLabel('API Key', { exact: true }).fill('browser-local-key')
    await page.getByLabel('启用模型').check()
    await page.getByRole('button', { name: '保存设置', exact: true }).click()
    await expect(page.getByRole('status')).toContainText('设置已保存')
    await expect(page.getByLabel('API Key', { exact: true })).toHaveValue('')
    await page.getByRole('button', { name: '测试已保存的连接' }).click()
    await expect(page.getByRole('status')).toContainText('模型连接正常')
    await page.getByRole('link', { name: '返回聊天' }).click()
    await expect(page.getByText('模型已配置', { exact: true })).toBeVisible()
  } finally {
    await restore(request, original)
  }
})

test('saving webpage preferences updates the next chat view', async ({ page, request }) => {
  const original = await savedGroup(request, 'frontend_config')
  try {
    await page.goto('/settings')
    await page.getByRole('button', { name: '网页偏好', exact: true }).click()
    await page.getByLabel('默认连接方式').click()
    await page.getByRole('option', { name: 'HTTP（SSE）', exact: true }).click()
    await page.getByRole('button', { name: '保存设置', exact: true }).click()
    await expect(page.getByRole('status')).toContainText('设置已保存')
    await page.getByRole('link', { name: '返回聊天' }).click()
    await expect(page.getByLabel('连接方式')).toHaveText('HTTP · SSE')
  } finally {
    await restore(request, original)
  }
})

test('sidebar settings and outlined controls support keyboard and mobile layout', async ({
  page,
}) => {
  await page.goto('/')
  const sidebar = page.locator('.sidebar-footer')
  await expect(sidebar.getByRole('link', { name: '设置', exact: true })).toBeVisible()
  await sidebar.getByRole('link', { name: '设置', exact: true }).click()
  const toggle = page.getByLabel('流式输出', { exact: true })
  await expect(toggle).toHaveCSS('appearance', 'none')
  await expect(toggle).toHaveCSS('width', '42px')
  await page.screenshot({ path: '/tmp/anyagent-settings-desktop.png', fullPage: true })
  await page.getByRole('button', { name: '网页偏好', exact: true }).click()
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
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: '/tmp/anyagent-settings-mobile.png', fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('link', { name: '返回聊天' }).click()
  await expect(
    page.locator('.sidebar-footer').getByRole('link', { name: '设置', exact: true }),
  ).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
