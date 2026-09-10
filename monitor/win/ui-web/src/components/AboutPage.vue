<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { invoke } from '../bridge'

const props = defineProps({
  metadata: { type: Object, required: true },
  settings: { type: Object, required: true },
})

const savingPlan = ref(false)

/**
 * 保存开发者计划开关，成功后同步页面设置。
 */
async function saveDeveloperPlan(enabled) {
  savingPlan.value = true
  try {
    const result = await invoke('settings.developerPlan', { enabled })
    props.settings.developer_plan = result.enabled
    ElMessage.success(result.enabled ? '已加入开发者计划' : '已退出开发者计划')
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  } finally {
    savingPlan.value = false
  }
}

/**
 * 打开应用日志和数据目录。
 */
async function openDataDirectory() {
  try {
    await invoke('system.openDataDirectory')
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  }
}
</script>

<template>
  <div class="about-layout">
    <el-card shadow="never" class="about-card">
      <div class="about-heading">
        <div class="about-logo"><el-icon><Cpu /></el-icon></div>
        <div><h2>{{ metadata.applicationName }}</h2><p>控制中心</p></div>
      </div>
      <el-descriptions :column="1" border class="section-gap">
        <el-descriptions-item label="版本号">{{ metadata.version }}</el-descriptions-item>
        <el-descriptions-item label="作者">{{ metadata.about.author || 'tokyohost' }}</el-descriptions-item>
        <el-descriptions-item label="微信号">{{ metadata.about.wechat || 'hi2024FL' }}</el-descriptions-item>
        <el-descriptions-item label="发布仓库">{{ metadata.about.repository || '--' }}</el-descriptions-item>
        <el-descriptions-item label="数据目录">{{ metadata.dataDirectory || '--' }}</el-descriptions-item>
      </el-descriptions>
      <el-form label-position="top" class="section-gap">
        <el-form-item label="加入开发者计划">
          <el-switch :model-value="!!settings.developer_plan" :loading="savingPlan" :disabled="savingPlan" @change="saveDeveloperPlan" />
        </el-form-item>
        <el-alert title="加入后可更新 Preview 版本开发固件，但可能存在性能不稳定等问题。关闭后，检查更新将不显示标签含 -preview 的新版本。" type="warning" :closable="false" show-icon />
      </el-form>
      <el-button type="primary" @click="openDataDirectory">打开日志和数据目录</el-button>
    </el-card>
    <el-card shadow="never" class="qr-card">
      <h3>咸鱼店铺二维码</h3>
      <img v-if="metadata.about.qrDataUrl" :src="metadata.about.qrDataUrl" alt="咸鱼店铺二维码" />
      <el-empty v-else description="二维码资源未找到" />
      <p>微信号：{{ metadata.about.wechat || 'hi2024FL' }}</p>
    </el-card>
  </div>
</template>
