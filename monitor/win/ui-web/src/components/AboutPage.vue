<script setup>
import { ElMessage } from 'element-plus'
import { invoke } from '../bridge'

defineProps({
  metadata: { type: Object, required: true },
})

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
        <div><h2>{{ metadata.applicationName }}</h2><p>Windows 桌面控制中心</p></div>
      </div>
      <el-descriptions :column="1" border class="section-gap">
        <el-descriptions-item label="版本号">{{ metadata.version }}</el-descriptions-item>
        <el-descriptions-item label="作者">{{ metadata.about.author || 'tokyohost' }}</el-descriptions-item>
        <el-descriptions-item label="微信号">{{ metadata.about.wechat || 'hi2024FL' }}</el-descriptions-item>
        <el-descriptions-item label="发布仓库">{{ metadata.about.repository || '--' }}</el-descriptions-item>
        <el-descriptions-item label="数据目录">{{ metadata.dataDirectory || '--' }}</el-descriptions-item>
      </el-descriptions>
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
