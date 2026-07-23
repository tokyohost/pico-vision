import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import './styles.css'

const application = createApp(App)

// 全量注册 Element Plus 图标，便于各导航和状态区域保持统一视觉语言。
for (const [name, component] of Object.entries(ElementPlusIconsVue)) {
  application.component(name, component)
}

application.use(ElementPlus)
application.mount('#app')
