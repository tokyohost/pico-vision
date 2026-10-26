import { computed } from 'vue'
import { createI18n } from 'vue-i18n'
import zhCN from 'element-plus/es/locale/lang/zh-cn'
import enUS from 'element-plus/es/locale/lang/en'
import chinese from './locales/zh-CN.json'
import english from './locales/en-US.json'

export const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  fallbackLocale: 'zh-CN',
  flatJson: true,
  messages: { 'zh-CN': chinese, 'en-US': english },
})

export const elementLocale = computed(() => i18n.global.locale.value === 'en-US' ? enUS : zhCN)

/** 根据驱动持久化配置设置语言，不使用浏览器语言覆盖用户选择。 */
export function setLocale(locale) {
  i18n.global.locale.value = locale === 'en-US' ? 'en-US' : 'zh-CN'
  document.documentElement.lang = i18n.global.locale.value
  document.title = `OmniWatch ${t("ui.control_center")}`
}

/** 在组件和普通脚本中按需翻译，并跟踪全局响应式语言。 */
export function t(key, params = {}) {
  return i18n.global.t(key, params)
}

/** 主题名称保留作者元数据，不随界面语言切换。 */
export function styleLabel(item) {
  return item.chinese_name || item.name
}

/** 系统任务按稳定标识翻译，插件任务保留原有名称。 */
export function taskLabel(name, fallback) {
  const key = `tasks.${name}`
  return i18n.global.te(key, 'zh-CN') ? t(key) : (fallback || name)
}
