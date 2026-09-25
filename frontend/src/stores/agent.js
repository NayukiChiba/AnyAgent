/* Agent 运行信息的共享状态：侧边栏切换器与聊天页共用 */

import { ref } from 'vue'
import { request } from '../api.js'

export const agent = ref(null)

export async function loadAgent() {
  agent.value = await request('/api/v1/agent')
}
