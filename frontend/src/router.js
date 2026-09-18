import { createRouter, createWebHistory } from 'vue-router'
import ChatView from './views/ChatView.vue'
import SettingsView from './views/SettingsView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: ChatView },
    { path: '/settings', component: SettingsView },
  ],
})
