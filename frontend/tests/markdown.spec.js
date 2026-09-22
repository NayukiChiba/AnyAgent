import { test, expect } from '@playwright/test'

const sample = [
  '# Markdown 回复',
  '',
  '**粗体**、*斜体*、~~删除~~、`inline_code`',
  '',
  '> 引用内容',
  '',
  '- 列表第一项',
  '- 列表第二项',
  '',
  '1. 有序第一项',
  '2. 有序第二项',
  '',
  '| 名称 | 值 |',
  '| :--- | ---: |',
  `| 中文 | ${'very_long_cell_'.repeat(50)} |`,
  '',
  '```python',
  'def greet():',
  '    print("你好")',
  '```',
  '',
  '```unknown-language',
  '<script>window.markdownAttack = true</script>',
  '```',
  '',
  '[安全链接](https://example.com)',
  '[危险链接](javascript:alert(1))',
  '<img src=x onerror="window.markdownAttack=true">',
  '<script>window.markdownAttack=true</script>',
].join('\n')

test('assistant Markdown renders safely with highlighted code, copy and mobile overflow', async ({
  page,
  request,
  context,
}) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  const session = await (await request.post('/api/v1/sessions')).json()
  await page.route(`**/api/v1/sessions/${session.id}`, (route) =>
    route.fulfill({
      json: {
        ...session,
        messages: [
          { role: 'user', content: '**用户原文**' },
          { role: 'assistant', content: sample },
        ],
      },
    }),
  )
  await page.goto('/')
  const reply = page.locator('.assistant .message-text')
  await expect(reply.getByRole('heading', { name: 'Markdown 回复' })).toBeVisible()
  await expect(reply).toHaveCSS('white-space', 'normal')
  await expect(reply.locator('strong')).toHaveText('粗体')
  await expect(reply.locator('em')).toHaveText('斜体')
  await expect(reply.locator('s')).toHaveText('删除')
  await expect(reply.locator('blockquote')).toContainText('引用内容')
  await expect(reply.locator('ul li')).toHaveCount(2)
  await expect(reply.locator('ol li')).toHaveCount(2)
  await expect(reply.getByRole('table')).toHaveCount(1)
  await expect(reply.locator('th').nth(1)).toHaveCSS('text-align', 'right')
  await expect(reply.locator('.hljs-keyword').first()).toHaveText('def')
  await expect(reply.locator('pre code').nth(1)).toContainText('<script>')
  await expect(page.locator('.user .message-text')).toHaveText('**用户原文**')
  await expect(page.locator('.user strong')).toHaveCount(0)
  const link = reply.getByRole('link', { name: '安全链接' })
  await expect(link).toHaveAttribute('target', '_blank')
  await expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  await expect(reply.locator('script, img[onerror], a[href^="javascript:"]')).toHaveCount(0)
  expect(await page.evaluate(() => window.markdownAttack)).toBeUndefined()
  await reply.getByRole('button', { name: '复制代码' }).first().click()
  await expect(reply.getByRole('status')).toHaveText('代码已复制')
  // Windows 平台写入系统剪贴板时换行会被规范化为 CRLF
  const copied = await page.evaluate(() => navigator.clipboard.readText())
  expect(copied.replaceAll('\r\n', '\n')).toBe('def greet():\n    print("你好")\n')
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: '/tmp/anyagent-markdown-mobile.png', fullPage: true })
  await request.delete(`/api/v1/sessions/${session.id}`)
})

test('streaming Markdown handles an open code fence and the final reply', async ({
  page,
  request,
}) => {
  const session = await (await request.post('/api/v1/sessions')).json()
  let messages = []
  await page.route(`**/api/v1/sessions/${session.id}`, (route) =>
    route.fulfill({ json: { ...session, messages } }),
  )
  let socket
  let release
  const opened = new Promise((resolve) => {
    release = resolve
  })
  await page.routeWebSocket(`**/ws/sessions/${session.id}`, (ws) => {
    socket = ws
    ws.onMessage(() => {
      ws.send(
        JSON.stringify({
          type: 'delta',
          data: { content: '# 流式回复\n\n```python\nprint("逐步到达")' },
        }),
      )
      release()
    })
  })
  await page.goto('/')
  await page.getByLabel('消息内容').fill('请给出示例')
  await page.getByRole('button', { name: '发送 ↑' }).click()
  await opened
  await expect(page.getByRole('heading', { name: '流式回复' })).toBeVisible()
  await expect(page.locator('.assistant pre code')).toHaveText('print("逐步到达")')
  const complete = '# 流式回复\n\n```python\nprint("逐步到达")\n```\n\n**完成**'
  messages = [
    { role: 'user', content: '请给出示例' },
    { role: 'assistant', content: complete },
  ]
  socket.send(JSON.stringify({ type: 'result', data: { content: complete } }))
  await expect(page.locator('.assistant strong')).toHaveText('完成')
  await expect(page.getByRole('button', { name: '停止生成' })).toHaveCount(0)
  await page.reload()
  await expect(page.locator('.assistant strong')).toHaveText('完成')
  await request.delete(`/api/v1/sessions/${session.id}`)
})
