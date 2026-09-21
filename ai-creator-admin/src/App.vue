<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from './api/client'

type Row = Record<string, any>
const loggedIn = ref(false)
const loading = ref(false)
const active = ref('dashboard')
const loginForm = ref({ username: 'admin', password: '' })
const dashboard = ref<Row>({})
const users = ref<Row[]>([])
const orders = ref<Row[]>([])
const products = ref<Row[]>([])
const tasks = ref<Row[]>([])
const packages = ref<Row[]>([])
const chatSettings = ref({ system_prompt: '你是一个安全、准确、友好的 AI 助手。', max_context_rounds: 20 })
const packageDialog = ref(false)
const packageForm = ref({ name: '', amount_cents: 100, points: 100, bonus_points: 0, is_active: true, sort_order: 0 })

const labels: Record<string, string> = {
  dashboard: '运营概览', users: '用户与积分', orders: '充值订单', products: 'AI 服务配置',
  tasks: '生成任务', packages: '充值套餐', settings: '系统设置',
}

async function login() {
  loading.value = true
  try {
    await api.post('/admin/auth/login', loginForm.value)
    loggedIn.value = true
    await loadAll()
  } catch (error: any) { ElMessage.error(error.message) }
  finally { loading.value = false }
}

async function loadAll() {
  loading.value = true
  try {
    const [d, u, o, p, t, pk, s] = await Promise.all([
      api.get('/admin/dashboard'), api.get('/admin/users'), api.get('/admin/recharge-orders'),
      api.get('/admin/products'), api.get('/admin/tasks'), api.get('/admin/packages'), api.get('/admin/settings'),
    ])
    dashboard.value = d.data; users.value = u.data; orders.value = o.data
    products.value = p.data; tasks.value = t.data; packages.value = pk.data
    if (s.data.chat) chatSettings.value = { ...chatSettings.value, ...s.data.chat }
  } catch (error: any) {
    if (error.message.includes('登录')) loggedIn.value = false
    else ElMessage.error(error.message)
  } finally { loading.value = false }
}

async function editPoints(user: Row) {
  const result = await ElMessageBox.prompt('请输入增加的积分数量', '人工加分', { inputPattern: /^[1-9]\d*$/, inputErrorMessage: '请输入正整数' })
  try {
    await api.post(`/admin/users/${user.id}/points`, { amount: Number(result.value), note: '管理员人工发放', idempotency_key: crypto.randomUUID() })
    ElMessage.success('积分已发放'); await loadAll()
  } catch (error: any) { ElMessage.error(error.message) }
}

async function saveProduct(product: Row) {
  try {
    await api.patch(`/admin/products/${product.id}`, { name: product.name, model: product.model,
      points_cost: product.points_cost, is_active: product.is_active, config: product.config })
    ElMessage.success('配置已保存')
  } catch (error: any) { ElMessage.error(error.message) }
}

async function savePackage(row: Row) {
  try { await api.put(`/admin/packages/${row.id}`, row); ElMessage.success('套餐已保存') }
  catch (error: any) { ElMessage.error(error.message) }
}

async function createPackage() {
  try { await api.post('/admin/packages', packageForm.value); packageDialog.value = false; ElMessage.success('套餐已创建'); await loadAll() }
  catch (error: any) { ElMessage.error(error.message) }
}

async function saveSettings() {
  try { await api.put('/admin/settings/chat', { value: chatSettings.value }); ElMessage.success('系统设置已保存') }
  catch (error: any) { ElMessage.error(error.message) }
}

function fmt(date: string) { return date ? new Date(date + (date.endsWith('Z') ? '' : 'Z')).toLocaleString('zh-CN') : '-' }

onMounted(async () => {
  try { await api.get('/admin/me'); loggedIn.value = true; await loadAll() } catch { loggedIn.value = false }
})
</script>

<template>
  <div v-if="!loggedIn" class="login-page">
    <el-card class="login-card">
      <div class="brand-mark">AI</div><h1>AI 创作管理台</h1><p>运营、积分与任务中心</p>
      <el-form label-position="top" @submit.prevent="login">
        <el-form-item label="管理员账号"><el-input v-model="loginForm.username" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="loginForm.password" type="password" show-password @keyup.enter="login" /></el-form-item>
        <el-button type="primary" size="large" :loading="loading" class="full" @click="login">安全登录</el-button>
      </el-form>
    </el-card>
  </div>
  <el-container v-else class="shell">
    <el-aside width="224px">
      <div class="logo"><span>AI</span><strong>创作管理台</strong></div>
      <el-menu :default-active="active" @select="active = $event">
        <el-menu-item v-for="(label, key) in labels" :key="key" :index="key">{{ label }}</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header><div><h2>{{ labels[active] }}</h2><small>所有时间按北京时间显示</small></div><el-button @click="loadAll">刷新数据</el-button></el-header>
      <el-main v-loading="loading">
        <template v-if="active === 'dashboard'">
          <div class="metric-grid">
            <el-card v-for="item in [{k:'users',n:'累计用户'},{k:'paid_orders',n:'充值订单'},{k:'tasks',n:'生成任务'},{k:'successful_tasks',n:'成功任务'},{k:'consumed_points',n:'已消耗积分'}]" :key="item.k">
              <span>{{ item.n }}</span><strong>{{ dashboard[item.k] || 0 }}</strong>
            </el-card>
          </div>
          <el-alert title="生产上线前请轮换所有已暴露密钥，并将默认管理员密码改为强密码。" type="warning" :closable="false" show-icon />
        </template>
        <el-table v-else-if="active === 'users'" :data="users" stripe>
          <el-table-column prop="id" label="用户 ID" min-width="220" />
          <el-table-column prop="username" label="账号" min-width="120" />
          <el-table-column prop="nickname" label="昵称" min-width="120" />
          <el-table-column label="微信" width="90">
            <template #default="s">{{ s.row.wechat_bound ? '已绑定' : '未绑定' }}</template>
          </el-table-column>
          <el-table-column prop="balance" label="可用积分" />
          <el-table-column prop="frozen" label="冻结" /><el-table-column prop="status" label="状态" />
          <el-table-column label="注册时间" min-width="180"><template #default="s">{{ fmt(s.row.created_at) }}</template></el-table-column>
          <el-table-column label="操作"><template #default="s"><el-button link type="primary" @click="editPoints(s.row)">加积分</el-button></template></el-table-column>
        </el-table>
        <el-table v-else-if="active === 'orders'" :data="orders" stripe>
          <el-table-column prop="order_no" label="订单号" min-width="210" />
          <el-table-column label="金额" width="100">
            <template #default="s">¥{{ (s.row.amount_cents / 100).toFixed(0) }}</template>
          </el-table-column>
          <el-table-column prop="points" label="积分" />
          <el-table-column label="状态" width="100">
            <template #default="s">{{ s.row.status === 'paid' ? '已到账' : s.row.status }}</template>
          </el-table-column>
          <el-table-column label="创建时间" min-width="180"><template #default="s">{{ fmt(s.row.created_at) }}</template></el-table-column>
        </el-table>
        <el-table v-else-if="active === 'products'" :data="products" stripe>
          <el-table-column prop="feature_type" label="类型" width="90" /><el-table-column label="名称"><template #default="s"><el-input v-model="s.row.name" /></template></el-table-column>
          <el-table-column label="模型" min-width="180"><template #default="s"><el-input v-model="s.row.model" /></template></el-table-column>
          <el-table-column label="积分"><template #default="s"><el-input-number v-model="s.row.points_cost" :min="1" /></template></el-table-column>
          <el-table-column label="供应商 credits 上限" min-width="180"><template #default="s"><el-input-number v-if="s.row.feature_type !== 'chat'" v-model="s.row.config.max_supplier_credits" :min="1" placeholder="上线前必填" /></template></el-table-column>
          <el-table-column label="启用"><template #default="s"><el-switch v-model="s.row.is_active" /></template></el-table-column>
          <el-table-column label="操作"><template #default="s"><el-button type="primary" link @click="saveProduct(s.row)">保存</el-button></template></el-table-column>
        </el-table>
        <el-table v-else-if="active === 'tasks'" :data="tasks" stripe>
          <el-table-column prop="id" label="任务 ID" min-width="250" /><el-table-column prop="feature_type" label="类型" />
          <el-table-column prop="status" label="状态" /><el-table-column prop="points" label="积分" />
          <el-table-column prop="prompt" label="提示词" min-width="260" show-overflow-tooltip />
          <el-table-column prop="error_message" label="错误" min-width="180" show-overflow-tooltip />
        </el-table>
        <template v-else-if="active === 'packages'">
          <div class="toolbar"><el-button type="primary" @click="packageDialog = true">新建套餐</el-button></div>
          <el-table :data="packages" stripe>
            <el-table-column label="套餐"><template #default="s"><el-input v-model="s.row.name" /></template></el-table-column>
            <el-table-column label="金额/分"><template #default="s"><el-input-number v-model="s.row.amount_cents" :min="1" /></template></el-table-column>
            <el-table-column label="基础积分"><template #default="s"><el-input-number v-model="s.row.points" :min="1" /></template></el-table-column>
            <el-table-column label="赠送"><template #default="s"><el-input-number v-model="s.row.bonus_points" :min="0" /></template></el-table-column>
            <el-table-column label="启用"><template #default="s"><el-switch v-model="s.row.is_active" /></template></el-table-column>
            <el-table-column label="操作"><template #default="s"><el-button link type="primary" @click="savePackage(s.row)">保存</el-button></template></el-table-column>
          </el-table>
        </template>
        <el-card v-else-if="active === 'settings'" class="settings-card">
          <el-form label-position="top"><el-form-item label="聊天系统提示词"><el-input v-model="chatSettings.system_prompt" type="textarea" :rows="8" maxlength="10000" show-word-limit /></el-form-item>
            <el-form-item label="最多携带历史轮数"><el-input-number v-model="chatSettings.max_context_rounds" :min="1" :max="100" /></el-form-item>
            <el-button type="primary" @click="saveSettings">保存设置</el-button></el-form>
        </el-card>
      </el-main>
    </el-container>
    <el-dialog v-model="packageDialog" title="新建充值套餐" width="480px">
      <el-form label-position="top"><el-form-item label="套餐名称"><el-input v-model="packageForm.name" /></el-form-item>
        <el-form-item label="金额（分）"><el-input-number v-model="packageForm.amount_cents" :min="1" /></el-form-item>
        <el-form-item label="基础积分"><el-input-number v-model="packageForm.points" :min="1" /></el-form-item>
        <el-form-item label="赠送积分"><el-input-number v-model="packageForm.bonus_points" :min="0" /></el-form-item></el-form>
      <template #footer><el-button @click="packageDialog = false">取消</el-button><el-button type="primary" @click="createPackage">创建</el-button></template>
    </el-dialog>
  </el-container>
</template>
