import { test, expect } from '@playwright/test'

async function modelConnection(request) {
  const settings = await (await request.get('/api/v1/settings')).json()
  const group = settings.groups.find((item) => item.name === 'model_config')
  return { group, baseUrl: group.values.base_url }
}

test('runner profiles can be created, validated, activated, tested, edited and deleted', async ({
  page,
  request,
}) => {
  const { baseUrl } = await modelConnection(request)
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/')
  await page.getByRole('link', { name: 'Runner 管理', exact: true }).click()
  await expect(page).toHaveURL(/\/runners$/)
  await expect(page.getByRole('heading', { name: 'Runner 管理' })).toBeVisible()

  // 旧版模型连接自动迁移为档案并已启用
  const legacyCard = page.locator('.runner-card', { hasText: '默认连接（旧版迁移）' })
  await expect(legacyCard).toBeVisible()
  await expect(legacyCard.getByText('已启用', { exact: true })).toBeVisible()

  // 表单校验：缺少 API Key 时在弹窗内报错
  await page.getByRole('button', { name: '新建 Runner' }).click()
  const dialog = page.getByRole('dialog', { name: '新建 Runner' })
  await dialog.getByLabel('名称', { exact: true }).fill('不完整')
  await dialog.getByLabel('接口地址').fill(baseUrl)
  await dialog.getByLabel('模型名称', { exact: true }).fill('browser-fixture')
  await dialog.getByRole('button', { name: '创建 Runner' }).click()
  await expect(dialog.getByRole('alert')).toContainText('API Key')

  // 类型联动：Coze 需要 Bot ID，不展示模型名称
  await dialog.getByRole('combobox', { name: '类型' }).click()
  await page.getByRole('option', { name: 'Coze（远端平台）', exact: true }).click()
  await expect(dialog.getByLabel('Bot ID')).toBeVisible()
  await expect(dialog.getByLabel('模型名称', { exact: true })).toHaveCount(0)
  await expect(dialog.getByLabel('流式输出')).toHaveCSS('appearance', 'none')
  await expect(dialog.getByLabel('流式输出')).toHaveCSS('width', '40px')
  await dialog.getByRole('combobox', { name: '类型' }).click()
  await page.getByRole('option', { name: 'LangChain（官方封装）', exact: true }).click()
  await dialog.getByRole('button', { name: '取消' }).click()

  // 创建第二个档案
  await page.getByRole('button', { name: '新建 Runner' }).click()
  await dialog.getByLabel('名称', { exact: true }).fill('备用连接')
  await dialog.getByLabel('接口地址').fill(baseUrl)
  await dialog.getByLabel('模型名称', { exact: true }).fill('browser-fixture')
  await dialog.getByLabel('API Key', { exact: true }).fill('browser-local-key')
  await dialog.getByRole('button', { name: '创建 Runner' }).click()
  await expect(page.getByRole('status')).toContainText('已创建')
  const spareCard = page.locator('.runner-card', { hasText: '备用连接' })
  await expect(spareCard).toBeVisible()
  await expect(legacyCard.getByText('已启用', { exact: true })).toBeVisible()

  // 启用新档案并测试连接
  await spareCard.getByRole('button', { name: '启用', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('已切换')
  await expect(spareCard.getByText('已启用', { exact: true })).toBeVisible()
  await spareCard.getByRole('button', { name: '测试连接' }).click()
  await expect(page.getByRole('status')).toContainText('模型连接正常')

  // 热切换立即生效：回到对话页，新开一个会话发送消息（历史会话可能带有旧消息）
  await page.getByRole('link', { name: '对话', exact: true }).click()
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
  await page.getByRole('link', { name: 'Runner 管理', exact: true }).click()
  await spareCard.getByRole('button', { name: '编辑', exact: true }).click()
  const editDialog = page.getByRole('dialog', { name: '编辑 Runner' })
  await expect(editDialog.getByLabel('API Key', { exact: true })).toHaveAttribute(
    'placeholder',
    '已保存密钥，留空保持不变',
  )
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
  expect(errors).toEqual([])
})

test('first use creates and activates a runner from the empty state', async ({ page, request }) => {
  const { group, baseUrl } = await modelConnection(request)
  const originalValues = group.values
  // 清空档案并停用旧版模型连接，模拟首次使用
  const existing = await (await request.get('/api/v1/profiles')).json()
  for (const profile of existing.profiles) await request.delete(`/api/v1/profiles/${profile.id}`)
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
    await page.getByRole('button', { name: '创建第一个 Runner' }).click()
    const dialog = page.getByRole('dialog', { name: '新建 Runner' })
    await dialog.getByLabel('名称', { exact: true }).fill('我的模型')
    await dialog.getByLabel('接口地址').fill(baseUrl)
    await dialog.getByLabel('模型名称', { exact: true }).fill('browser-fixture')
    await dialog.getByLabel('API Key', { exact: true }).fill('browser-local-key')
    await dialog.getByRole('button', { name: '创建 Runner' }).click()
    // 首个档案自动启用，可直接测试连接
    await expect(page.locator('.runner-card .badge-success')).toHaveText('已启用')
    await page.getByRole('button', { name: '测试连接' }).click()
    await expect(page.getByRole('status')).toContainText('模型连接正常')
    await page.getByRole('link', { name: '对话', exact: true }).click()
    await expect(page.locator('.status-pill')).toContainText('我的模型')
    await page.getByRole('button', { name: '新建会话' }).click()
    await page.getByLabel('消息内容').fill('计算 2+3')
    await page.getByRole('button', { name: '发送 ↑' }).click()
    await expect(page.locator('.assistant .message-text')).toHaveText('结果是 5')
  } finally {
    // 清理档案并恢复模型连接配置（含夹具密钥），不影响其他用例
    const remaining = await (await request.get('/api/v1/profiles')).json()
    for (const profile of remaining.profiles) await request.delete(`/api/v1/profiles/${profile.id}`)
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
