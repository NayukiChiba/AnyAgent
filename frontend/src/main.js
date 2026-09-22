/* 全局样式需先于视图组件加载，视图内的局部样式才能覆盖基础布局 */
import './styles/tokens.css'
import './styles/controls.css'
import './styles/style.css'
import { createApp } from 'vue'
import App from './App.vue'
import router from './router.js'

createApp(App).use(router).mount('#app')
