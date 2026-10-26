/** 验证实际国际化入口、资源占位符和内置详情键。 */
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { after, before, test } from 'node:test'
import { createServer } from 'vite'

let server
let translations

before(async () => {
  server = await createServer({ server: { middlewareMode: true }, appType: 'custom', optimizeDeps: { noDiscovery: true, include: [] } })
  translations = await server.ssrLoadModule('/src/i18n.js')
  globalThis.document = { documentElement: { lang: '' } }
})

after(async () => {
  await server?.close()
  delete globalThis.document
})

test('双语资源键和命名参数一致，主题详情保持原文', () => {
  const chinese = JSON.parse(readFileSync('src/locales/zh-CN.json', 'utf8'))
  const english = JSON.parse(readFileSync('src/locales/en-US.json', 'utf8'))
  assert.deepEqual(Object.keys(chinese).sort(), Object.keys(english).sort())
  for (const key of Object.keys(chinese)) {
    const parameters = text => [...text.matchAll(/\{([^{}]+)\}/g)].map(match => match[1]).sort()
    assert.deepEqual(parameters(chinese[key]), parameters(english[key]), key)
  }
  for (const file of readdirSync('assert/styleDetail')) {
    if (!file.endsWith('.html')) continue
    assert.ok(!readFileSync(`assert/styleDetail/${file}`, 'utf8').includes('data-i18n='))
  }
})

test('全局切换同时更新业务文案、组件库语言和页面语言', () => {
  const { setLocale, t, elementLocale } = translations
  setLocale('zh-CN')
  assert.equal(t('common.language'), '语言')
  assert.equal(elementLocale.value.name, 'zh-cn')
  setLocale('en-US')
  assert.equal(t('common.language'), 'Language')
  assert.equal(elementLocale.value.name, 'en')
  assert.equal(document.documentElement.lang, 'en-US')
  assert.equal(t('ui.operation_failed_value', { value0: 'Timeout' }), 'Operation failed: Timeout')
  setLocale('invalid')
  assert.equal(t('common.language'), '语言')
})

test('主题名称保持原文，采集任务跟随界面语言', () => {
  const { setLocale, styleLabel, taskLabel } = translations
  setLocale('en-US')
  assert.equal(styleLabel({ name: 'default', type: 'builtin', chinese_name: '经典概览' }), '经典概览')
  assert.equal(styleLabel({ name: 'default', type: 'custom', chinese_name: '作者自定义' }), '作者自定义')
  assert.equal(taskLabel('cpu_memory', 'CPU与内存采集'), 'CPU & memory')
  assert.equal(taskLabel('plugin_task', '插件标题'), '插件标题')
})


test('桥接保留稳定错误码，覆盖提示不匹配中文消息', async () => {
  const { invoke } = await server.ssrLoadModule('/src/bridge.js')
  globalThis.window = { pywebview: { api: { invoke: async () => ({ ok: false, message: 'Already exists', code: 'file_exists' }) } } }
  try {
    await assert.rejects(invoke('data.syncStyle'), error => error.code === 'file_exists')
    assert.ok(!readFileSync('src/components/CustomDataPage.vue', 'utf8').includes('/已存在/'))
  } finally {
    delete globalThis.window
  }
})
