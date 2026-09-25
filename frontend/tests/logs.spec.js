import { test, expect } from '@playwright/test'

test('logs page replays recent entries and streams live logs', async ({ page, request }) => {
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/logs')
  await expect(page.getByRole('heading', { name: '运行日志' })).toBeVisible()
  // 管理模式下侧栏高亮日志导航
  const sidebar = page.locator('.sidebar')
  await expect(sidebar.getByRole('tab', { name: '管理' })).toHaveAttribute('aria-selected', 'true')
  await expect(
    sidebar.getByRole('link', { name: '日志', exact: true }),
  ).toHaveClass(/active/)

  // 启动日志经快照回放可见，连接状态展示为实时接收
  const console_ = page.locator('.log-console')
  await expect(console_.locator('.log-line').first()).toBeVisible()
  await expect(console_).toContainText('Application ready')
  await expect(page.locator('.status-pill')).toContainText('实时接收中')

  // 触发一条新日志：创建并删除一个 Runner 档案
  const models = await (await request.get('/api/v1/models')).json()
  const profile = await (
    await request.post('/api/v1/profiles', {
      data: { name: '日志探针', type: 'langchain', model_id: models.models[0].id },
    })
  ).json()
  await expect(console_).toContainText('Runner profile created')
  await request.delete(`/api/v1/profiles/${profile.id}`)

  // 暂停后新日志不再追加，继续后恢复
  await page.getByRole('button', { name: '暂停' }).click()
  const beforePause = await console_.locator('.log-line').count()
  const probe = await (
    await request.post('/api/v1/profiles', {
      data: { name: '暂停探针', type: 'langchain', model_id: models.models[0].id },
    })
  ).json()
  await page.waitForTimeout(500)
  expect(await console_.locator('.log-line').count()).toBe(beforePause)
  await page.getByRole('button', { name: '继续' }).click()
  const probe2 = await (
    await request.post('/api/v1/profiles', {
      data: { name: '恢复探针', type: 'langchain', model_id: models.models[0].id },
    })
  ).json()
  await expect
    .poll(async () => console_.locator('.log-line').count())
    .toBeGreaterThan(beforePause)
  await request.delete(`/api/v1/profiles/${probe.id}`)
  await request.delete(`/api/v1/profiles/${probe2.id}`)

  // 级别筛选与清空
  await page.getByLabel('级别').click()
  await page.getByRole('option', { name: '仅错误', exact: true }).click()
  await expect(console_.locator('.log-line')).toHaveCount(0)
  await page.getByLabel('级别').click()
  await page.getByRole('option', { name: '全部级别', exact: true }).click()
  await expect(console_.locator('.log-line').first()).toBeVisible()
  await page.getByRole('button', { name: '清空' }).click()
  await expect(page.getByText('暂无日志')).toBeVisible()
  expect(errors).toEqual([])
})
