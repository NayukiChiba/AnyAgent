import { defineConfig } from 'vitepress'

export default defineConfig({
  lang: 'zh-CN',
  title: 'AnyAgent',
  description: '通过统一 API 接入多个 Agent Runner 的应用平台',
  base: process.env.DOCS_BASE || '/',
  lastUpdated: true,
  themeConfig: {
    nav: [
      { text: '使用指南', link: '/guide/getting-started' },
      { text: '开发指南', link: '/development' }
    ],
    sidebar: [
      {
        text: '使用指南',
        items: [
          { text: '快速开始', link: '/guide/getting-started' },
          { text: '配置管理', link: '/guide/configuration' },
          { text: 'LangChain Agent', link: '/guide/agent' },
          { text: '日志', link: '/guide/logging' },
          { text: '健康检查', link: '/guide/health' }
        ]
      },
      { text: '开发指南', link: '/development' }
    ],
    socialLinks: [{ icon: 'github', link: 'https://github.com/NayukiChiba/AnyAgent' }],
    search: { provider: 'local' },
    outline: { label: '本页目录' },
    docFooter: { prev: '上一页', next: '下一页' },
    lastUpdated: { text: '最后更新' }
  }
})
