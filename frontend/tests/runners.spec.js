import { test, expect } from '@playwright/test'

async function modelConnection(request) {
  const settings = await (await request.get('/api/v1/settings')).json()
  const group = settings.groups.find((item) => item.name === 'model_config')
  return { group, baseUrl: group.values.base_url }
}

async function createModel(request, name, baseUrl) {
  const response = await request.post('/api/v1/models', {
    data: { name, base_url: baseUrl, model: 'browser-fixture', api_key: 'browser-local-key' },
  })
  return response.json()
}

test('runner profiles select a shared model connection instead of inline fields', async ({
  page,
  request,
}) => {
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/runners')
  await expect(page.getByRole('heading', { name: 'Runner 管理' })).toBeVisible()
  // 管理模式下侧栏展示管理导航
  const sidebar = page.locator('.sidebar')
  await expect(sidebar.getByRole('tab', { name: '管理' })).toHaveAttribute('aria-selected', 'true')

  // 旧版模型连接自动迁移为档案并已启用
  const legacyCard = page.locator('.runner-card', { hasText: '默认连接（旧版迁移）' })
  await expect(legacyCard).toBeVisible()
  await expect(legacyCard.getByText('已启用', { exact: true })).toBeVisible()

  // 类型联动：Coze 需要 Bot ID；编辑器不再出现连接字段，改为选择模型连接
  await page.getByRole('button', { name: '新建 Runner' }).click()
  const dialog = page.getByRole('dialog', { name: '新建 Runner' })
  await dialog.getByLabel('名称', { exact: true }).fill('不完整')
  await expect(dialog.getByLabel('接口地址')).toHaveCount(0)
  await expect(dialog.getByLabel('API Key', { exact: true })).toHaveCount(0)
  await expect(dialog.getByRole('combobox', { name: '模型连接' })).toContainText(
    '默认模型（旧版迁移）',
  )
  await dialog.getByRole('combobox', { name: '类型' }).click()
  await page.getByRole('option', { name: 'Coze（远端平台）', exact: true }).click()
  await expect(dialog.getByLabel('Bot ID')).toBeVisible()
  await dialog.getByRole('button', { name: '创建 Runner' }).click()
  await expect(dialog.getByRole('alert')).toContainText('Bot ID')
  await dialog.getByRole('combobox', { name: '类型' }).click()
  await page.getByRole('option', { name: 'LangChain（官方封装）', exact: true }).click()
  await dialog.getByRole('button', { name: '取消' }).click()

  // 新建一个模型连接，再创建引用它的档案
  const { baseUrl } = await modelConnection(request)
  await createModel(request, '备用模型', baseUrl)
  await page.getByRole('button', { name: '刷新' }).click()
  await page.getByRole('button', { name: '新建 Runner' }).click()
  await dialog.getByLabel('名称', { exact: true }).fill('备用连接')
  await dialog.getByRole('combobox', { name: '模型连接' }).click()
  await page.getByRole('option', { name: /备用模型/ }).click()
  await dialog.getByRole('button', { name: '创建 Runner' }).click()
  await expect(page.getByRole('status')).toContainText('已创建')
  const spareCard = page.locator('.runner-card', { hasText: '备用连接' })
  await expect(spareCard).toBeVisible()
  await expect(spareCard.getByText(/备用模型 · browser-fixture/)).toBeVisible()
  await expect(legacyCard.getByText('已启用', { exact: true })).toBeVisible()

  // 启用新档案并测试连接
  await spareCard.getByRole('button', { name: '启用', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('已切换')
  await expect(spareCard.getByText('已启用', { exact: true })).toBeVisible()
  await spareCard.getByRole('button', { name: '测试连接' }).click()
  await expect(page.getByRole('status')).toContainText('模型连接正常')

  // 热切换立即生效：回到对话页，新开一个会话发送消息（历史会话可能带有旧消息）
  await sidebar.getByRole('tab', { name: '会话' }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.locator('.status-pill')).toContainText('备用连接')
  await page.getByRole('button', { name: '新建会话' }).click()
  await page.getByLabel('消息内容').fill('计算 2+3')
  await page.getByRole('button', { name: '发送 ↑' }).click()
  await expect(page.locator('.assistant .message-text')).toHaveText('结果是 5')

  // 通过侧边栏切换器切回旧版档案
  await page.getByRole('button', { name: '切换 Runner' }).click()
  await page.getByRole('button', { name: /默认连接（旧版迁移）/ }).click()
  await expect(page.locator('.status-pill')).toContainText('默认连接（旧版迁移）')

  // 编辑与删除
  await page.goto('/runners')
  await spareCard.getByRole('button', { name: '编辑', exact: true }).click()
  const editDialog = page.getByRole('dialog', { name: '编辑 Runner' })
  await expect(editDialog.getByRole('combobox', { name: '模型连接' })).toContainText('备用模型')
  await editDialog.getByLabel('名称', { exact: true }).fill('备用连接 v2')
  await editDialog.getByRole('button', { name: '保存修改' }).click()
  await expect(page.getByRole('status')).toContainText('已保存')
  await expect(page.locator('.runner-card', { hasText: '备用连接 v2' })).toBeVisible()
  page.once('dialog', (confirm) => confirm.accept())
  await page
    .locator('.runner-card', { hasText: '备用连接 v2' })
    .getByRole('button', { name: '删除', exact: true })
    .click()
  await expect(page.getByRole('status')).toContainText('已删除')
  await expect(page.locator('.runner-card', { hasText: '备用连接 v2' })).toHaveCount(0)
  await expect(legacyCard.getByText('已启用', { exact: true })).toBeVisible()

  // 清理：删除备用模型连接，不影响其他用例
  const models = await (await request.get('/api/v1/models')).json()
  for (const model of models.models) {
    if (model.name === '备用模型') await request.delete(`/api/v1/models/${model.id}`)
  }
  expect(errors).toEqual([])
})

test('first use creates model then runner from the empty state', async ({ page, request }) => {
  const { group, baseUrl } = await modelConnection(request)
  const originalValues = group.values
  // 清空档案与模型连接并停用旧版模型配置，模拟首次使用
  const existing = await (await request.get('/api/v1/profiles')).json()
  for (const profile of existing.profiles) await request.delete(`/api/v1/profiles/${profile.id}`)
  const existingModels = await (await request.get('/api/v1/models')).json()
  for (const model of existingModels.models) await request.delete(`/api/v1/models/${model.id}`)
  const latest = await (await request.get('/api/v1/settings')).json()
  const current = latest.groups.find((item) => item.name === 'model_config')
  await request.put('/api/v1/settings/model_config', {
    data: {
      revision: current.revision,
      values: { ...current.values, enabled: false, model: '' },
      clear_api_key: true,
    },
  })
  try {
    await page.goto('/')
    await expect(page.getByText('还没有启用的 Runner')).toBeVisible()
    await expect(page.getByRole('button', { name: '发送 ↑' })).toBeDisabled()
    await page.getByRole('link', { name: '打开 Runner 管理' }).click()
    await expect(page).toHaveURL(/\/runners$/)
    await expect(page.getByText('还没有 Runner')).toBeVisible()

    // 没有模型连接时编辑器给出指引
    await page.getByRole('button', { name: '创建第一个 Runner' }).click()
    const runnerDialog = page.getByRole('dialog', { name: '新建 Runner' })
    await expect(runnerDialog.getByText('还没有模型连接')).toBeVisible()
    await runnerDialog.getByRole('button', { name: '取消' }).click()

    // 先在模型页面创建连接
    await page.locator('.sidebar').getByRole('link', { name: '模型', exact: true }).click()
    await expect(page).toHaveURL(/\/models$/)
    await page.getByRole('button', { name: '创建第一个模型连接' }).click()
    const modelDialog = page.getByRole('dialog', { name: '新建模型连接' })
    await modelDialog.getByLabel('名称', { exact: true }).fill('本地模型')
    await modelDialog.getByLabel('接口地址').fill(baseUrl)
    await modelDialog.getByLabel('模型名称', { exact: true }).fill('browser-fixture')
    await modelDialog.getByLabel('API Key', { exact: true }).fill('browser-local-key')
    await modelDialog.getByRole('button', { name: '创建模型连接' }).click()
    await expect(page.getByRole('status')).toContainText('已创建')

    // 回到 Runner 页面创建并自动启用首个档案
    await page.locator('.sidebar').getByRole('link', { name: 'Runner 管理', exact: true }).click()
    await page.getByRole('button', { name: '创建第一个 Runner' }).click()
    await runnerDialog.getByLabel('名称', { exact: true }).fill('我的模型')
    await expect(runnerDialog.getByRole('combobox', { name: '模型连接' })).toContainText(
      '本地模型',
    )
    await runnerDialog.getByRole('button', { name: '创建 Runner' }).click()
    await expect(page.locator('.runner-card .badge-success')).toHaveText('已启用')
    await page.getByRole('button', { name: '测试连接' }).click()
    await expect(page.getByRole('status')).toContainText('模型连接正常')
    await page.locator('.sidebar').getByRole('tab', { name: '会话' }).click()
    await expect(page.locator('.status-pill')).toContainText('我的模型')
    await page.getByRole('button', { name: '新建会话' }).click()
    await page.getByLabel('消息内容').fill('计算 2+3')
    await page.getByRole('button', { name: '发送 ↑' }).click()
    await expect(page.locator('.assistant .message-text')).toHaveText('结果是 5')
  } finally {
    // 清理档案与模型连接并恢复模型配置（含夹具密钥），不影响其他用例
    const remaining = await (await request.get('/api/v1/profiles')).json()
    for (const profile of remaining.profiles)
      await request.delete(`/api/v1/profiles/${profile.id}`)
    const remainingModels = await (await request.get('/api/v1/models')).json()
    for (const model of remainingModels.models)
      await request.delete(`/api/v1/models/${model.id}`)
    const refreshed = await (await request.get('/api/v1/settings')).json()
    const target = refreshed.groups.find((item) => item.name === 'model_config')
    await request.put('/api/v1/settings/model_config', {
      data: {
        revision: target.revision,
        values: { ...originalValues, api_key: 'browser-local-key' },
      },
    })
  }
})
