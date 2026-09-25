import { test, expect } from '@playwright/test'

test('model connections can be created, tested, referenced and deleted', async ({
  page,
  request,
}) => {
  const settings = await (await request.get('/api/v1/settings')).json()
  const baseUrl = settings.groups.find((item) => item.name === 'model_config').values.base_url
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/models')
  await expect(page.getByRole('heading', { name: '模型连接' })).toBeVisible()

  // 旧版模型配置自动迁移为连接
  const legacyCard = page.locator('.runner-card', { hasText: '默认模型（旧版迁移）' })
  await expect(legacyCard).toBeVisible()
  await expect(legacyCard.getByText(/browser-fixture/)).toBeVisible()

  // 表单校验：缺少 API Key 时在弹窗内报错
  await page.getByRole('button', { name: '新建模型连接' }).click()
  const dialog = page.getByRole('dialog', { name: '新建模型连接' })
  await dialog.getByLabel('名称', { exact: true }).fill('不完整')
  await dialog.getByLabel('接口地址').fill(baseUrl)
  await dialog.getByLabel('模型名称', { exact: true }).fill('browser-fixture')
  await dialog.getByRole('button', { name: '创建模型连接' }).click()
  await expect(dialog.getByRole('alert')).toContainText('API Key')

  // 完整创建并测试连接
  await dialog.getByLabel('API Key', { exact: true }).fill('browser-local-key')
  await dialog.getByRole('button', { name: '创建模型连接' }).click()
  await expect(page.getByRole('status')).toContainText('已创建')
  const card = page.locator('.runner-card', { hasText: '不完整' })
  await expect(card).toBeVisible()
  await card.getByRole('button', { name: '测试连接' }).click()
  await expect(page.getByRole('status')).toContainText('模型连接正常')

  // 被 Runner 引用后禁止删除
  const models = await (await request.get('/api/v1/models')).json()
  const created = models.models.find((item) => item.name === '不完整')
  const profile = await (
    await request.post('/api/v1/profiles', {
      data: { name: '引用者', type: 'langchain', model_id: created.id },
    })
  ).json()
  await page.getByRole('button', { name: '刷新' }).click()
  await expect(card.getByText('被引用：引用者')).toBeVisible()
  await expect(card.getByRole('button', { name: '删除', exact: true })).toBeDisabled()
  await request.delete(`/api/v1/profiles/${profile.id}`)
  await page.getByRole('button', { name: '刷新' }).click()

  // 编辑：密钥留空保持不变
  await card.getByRole('button', { name: '编辑', exact: true }).click()
  const editDialog = page.getByRole('dialog', { name: '编辑模型连接' })
  await expect(editDialog.getByLabel('API Key', { exact: true })).toHaveAttribute(
    'placeholder',
    '已保存密钥，留空保持不变',
  )
  await editDialog.getByLabel('名称', { exact: true }).fill('不完整 v2')
  await editDialog.getByRole('button', { name: '保存修改' }).click()
  await expect(page.getByRole('status')).toContainText('已保存')
  const renamed = page.locator('.runner-card', { hasText: '不完整 v2' })
  await expect(renamed).toBeVisible()
  // 留空保存后密钥仍然可用
  await renamed.getByRole('button', { name: '测试连接' }).click()
  await expect(page.getByRole('status')).toContainText('模型连接正常')

  page.once('dialog', (confirm) => confirm.accept())
  await renamed.getByRole('button', { name: '删除', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('已删除')
  await expect(page.locator('.runner-card', { hasText: '不完整 v2' })).toHaveCount(0)
  expect(errors).toEqual([])
})
