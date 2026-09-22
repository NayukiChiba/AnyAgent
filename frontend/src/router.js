import { createRouter, createWebHistory } from 'vue-router'
import ChatView from './views/ChatView.vue'
import RunnersView from './views/RunnersView.vue'
import SettingsView from './views/SettingsView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: ChatView },
    { path: '/runners', component: RunnersView },
    { path: '/settings', component: SettingsView },
  ],
})
