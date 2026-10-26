<script setup>
import { t } from '../i18n'

import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { invoke, copyText } from '../bridge'

const props = defineProps({
  metadata: { type: Object, required: true },
  settings: { type: Object, required: true },
})

const savingPlan = ref(false)
const qqGroupNumber = '1109488330'

/**
 * 保存开发者计划开关，成功后同步页面设置。
 */
async function saveDeveloperPlan(enabled) {
  savingPlan.value = true
  try {
    const result = await invoke('settings.developerPlan', { enabled })
    props.settings.developer_plan = result.enabled
    ElMessage.success(result.enabled ? t('ui.joined_the_developer_program') : t('ui.left_the_developer_program'))
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

/**
 * 复制 QQ 群号并反馈操作结果。
 */
async function copyQqGroupNumber() {
  const groupNumber = props.metadata.about.qqGroup || qqGroupNumber
  try {
    await copyText(groupNumber)
    ElMessage.success(t('ui.qq_group_number_copied'))
  } catch (error) {
    ElMessage.error(error?.message || t('ui.failed_to_copy_qq_group_number'))
  }
}
</script>

<template>
  <div class="about-layout">
    <el-card shadow="never" class="about-card">
      <div class="about-heading">
        <div class="about-logo"><el-icon><Cpu /></el-icon></div>
        <div><h2>{{ metadata.applicationName }}</h2><p>{{ t('ui.control_center') }}</p></div>
      </div>
      <el-descriptions :column="1" border class="section-gap">
        <el-descriptions-item :label="t('ui.version_number')">{{ metadata.version }}</el-descriptions-item>
        <el-descriptions-item :label="t('ui.author')">{{ metadata.about.author || 'tokyohost' }}</el-descriptions-item>
        <el-descriptions-item :label="t('ui.wechat_id')">{{ metadata.about.wechat || 'hi2024FL' }}</el-descriptions-item>
        <el-descriptions-item :label="t('ui.release_repository')">{{ metadata.about.repository || '--' }}</el-descriptions-item>
        <el-descriptions-item :label="t('ui.data_directory')">{{ metadata.dataDirectory || '--' }}</el-descriptions-item>
      </el-descriptions>
      <el-form label-position="top" class="section-gap">
        <el-form-item :label="t('ui.join_the_developer_program')">
          <el-switch :model-value="!!settings.developer_plan" :loading="savingPlan" :disabled="savingPlan" @change="saveDeveloperPlan" />
        </el-form-item>
        <el-alert :title="t('ui.receive_preview_firmware_updates_which_may_have_performance_or')" type="warning" :closable="false" show-icon />
      </el-form>
      <el-button class="section-gap" type="primary" @click="openDataDirectory">{{ t('ui.open_log_and_data_directory') }}</el-button>
    </el-card>
    <el-card shadow="never" class="qr-card">
      <h3>{{ t('ui.xianyu_shop_qr_code') }}</h3>
      <img v-if="metadata.about.qrDataUrl" :src="metadata.about.qrDataUrl" :alt="t('ui.xianyu_shop_qr_code')" />
      <el-empty v-else :description="t('ui.qr_code_resource_not_found')" />
      <p>{{ t('ui.wechat_id_2') }}{{ metadata.about.wechat || 'hi2024FL' }}</p>
    </el-card>
    <el-card shadow="never" class="qr-card qq-group-card">
      <div class="qq-group-heading">
        <span class="qq-group-icon"><el-icon><ChatDotRound /></el-icon></span>
        <div>
          <h3>{{ t('ui.omniwatch_qq_group') }}</h3>
          <p>{{ t('ui.scan_to_join_the_user_group') }}</p>
        </div>
      </div>
      <img
        v-if="metadata.about.qqGroupQrDataUrl"
        :src="metadata.about.qqGroupQrDataUrl"
        :alt="t('ui.omniwatch_qq_group_qr_code')"
        class="qq-group-qr"
      />
      <el-empty v-else :description="t('ui.qq_group_qr_code_resource_not_found')" />
      <div class="qq-group-number">
        <span>
          <small>{{ t('ui.qq_group_number') }}</small>
          <strong>{{ metadata.about.qqGroup || qqGroupNumber }}</strong>
        </span>
        <el-button type="primary" plain size="small" @click="copyQqGroupNumber">
          <el-icon><CopyDocument /></el-icon>
          <span>{{ t('ui.copy_group_number') }}</span>
        </el-button>
      </div>
    </el-card>
  </div>
</template>
