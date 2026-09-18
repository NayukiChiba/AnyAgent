import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/common'

const markdown = new MarkdownIt({ html: false, linkify: true, breaks: true })
const escape = markdown.utils.escapeHtml
markdown.renderer.rules.fence = (tokens, index) => {
  const token = tokens[index]
  const language = token.info.trim().split(/\s+/)[0]
  let code = escape(token.content)
  if (language && hljs.getLanguage(language)) {
    try {
      code = hljs.highlight(token.content, { language, ignoreIllegals: true }).value
    } catch {
      // Incomplete or unsupported snippets remain readable as plain text.
    }
  }
  return `<div class="markdown-code"><div class="markdown-code-header"><span>${escape(language || '代码')}</span><button type="button" class="markdown-copy" aria-label="复制代码">复制代码</button></div><pre><code class="hljs">${code}</code></pre></div>`
}
markdown.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
  tokens[index].attrSet('target', '_blank')
  tokens[index].attrSet('rel', 'noopener noreferrer')
  return renderer.renderToken(tokens, index, options)
}
const image = markdown.renderer.rules.image
markdown.renderer.rules.image = (tokens, index, options, env, renderer) => {
  tokens[index].attrSet('loading', 'lazy')
  return image(tokens, index, options, env, renderer)
}
for (const tag of ['th_open', 'td_open']) {
  markdown.renderer.rules[tag] = (tokens, index, options, env, renderer) => {
    const alignment = tokens[index].attrGet('style')?.match(/^text-align:(left|center|right)$/)?.[1]
    if (alignment) {
      tokens[index].attrSet('data-align', alignment)
      tokens[index].attrs = tokens[index].attrs.filter(([name]) => name !== 'style')
    }
    return renderer.renderToken(tokens, index, options)
  }
}
const tableOpen = markdown.renderer.rules.table_open
markdown.renderer.rules.table_open = (tokens, index, options, env, renderer) =>
  '<div class="markdown-table" tabindex="0" role="region" aria-label="Markdown 表格">' +
  (tableOpen
    ? tableOpen(tokens, index, options, env, renderer)
    : renderer.renderToken(tokens, index, options))
markdown.renderer.rules.table_close = () => '</table></div>'

export function renderMarkdown(content) {
  return DOMPurify.sanitize(markdown.render(content || ''), {
    USE_PROFILES: { html: true },
    ADD_ATTR: ['target'],
    FORBID_TAGS: ['style', 'form', 'input', 'iframe'],
    FORBID_ATTR: ['style'],
  })
}
