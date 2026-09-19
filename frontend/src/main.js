import { createApp } from 'vue'
import App from './App.vue'
import router from './router.js'
import './styles/style.css'
import './styles/controls.css'

createApp(App).use(router).mount('#app')
