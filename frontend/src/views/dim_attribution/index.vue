<template>
  <section class="page" data-module="dim_attribution">
    <header class="page-head">
      <div>
        <h2>维度归属校验</h2>
        <p class="page-desc">计算前按业务日校验维度归属（来源 + 业务键 + 允许层级一起确认），立方体只按已校验归属取数。</p>
      </div>
      <div class="page-actions">
        <button v-for="d in datePresets" :key="d.value" class="btn" :class="{ primary: bizDate === d.value }" type="button" @click="selectDate(d.value)">{{ d.label }}</button>
      </div>
    </header>

    <div class="card" style="margin-bottom:14px">
      <h3>维度归属数据集 · {{ dataset.业务日 }}</h3>
      <p v-if="dataset.summary" class="page-desc">
        ACTIVE {{ dataset.summary.active }} 条 · READ_ONLY {{ dataset.summary.read_only }} 条 ·
        INVALID {{ dataset.summary.invalid }} 条 · 冲突维度 {{ dataset.summary.冲突维度数 }} 个
      </p>
      <div v-for="c in dataset.conflicts" :key="c.维度编号" class="conflict-banner" data-testid="conflict-banner">
        ⚠️ {{ c.维度名称 }}（{{ c.维度编号 }}）在 {{ c.业务日 }} 存在归属冲突：{{ c.冲突归属.join(' vs ') }}
      </div>
      <table class="data-table" data-testid="attribution-table">
        <thead>
          <tr><th>归属ID（来源#业务键）</th><th>维度</th><th>允许层级</th><th>来源实际覆盖</th><th>确认</th><th>状态</th><th>说明 / 操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in dataset.records" :key="r.登记编号">
            <td>{{ r.归属ID }}</td>
            <td>{{ r.维度编号 }}</td>
            <td>{{ r.允许层级.join(', ') }}</td>
            <td>{{ r.来源实际覆盖层级.join(', ') || '—' }}</td>
            <td>{{ r.确认状态 }}</td>
            <td><span class="status-tag" :class="statusClass(r.status)">{{ r.status }}</span><span v-if="r.has_conflict" class="conflict-flag">冲突</span></td>
            <td>
              <div v-for="reason in r.reasons" :key="reason" class="reason-line">{{ reason }}</div>
              <button v-if="r.确认状态 !== 'confirmed' && r.维度编号 === 'DIM-REGION'" class="btn primary" type="button" :data-testid="`confirm-${r.登记编号}`" @click="confirmRegistration(r.登记编号)">确认归属</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="card">
      <h3>立方体按已校验归属取数（{{ bizDate }}）</h3>
      <div class="query-bar">
        <label>层级
          <select v-model="queryLevel" data-testid="level-select">
            <option value="province">省 province</option>
            <option value="city">市 city</option>
          </select>
        </label>
        <label>来源
          <select v-model="querySource" data-testid="source-select">
            <option :value="null">默认（按层级覆盖自动选择）</option>
            <option value="legacy_dim_region">legacy_dim_region（旧表·省/市）</option>
            <option value="province_dim_region">province_dim_region（新表·仅省）</option>
          </select>
        </label>
        <button class="btn primary" type="button" data-testid="run-query" @click="runQuery">请求取数</button>
      </div>

      <div v-if="!result" class="page-desc">选择层级与来源后点击「请求取数」。</div>
      <div v-else>
        <div v-if="!result.ok" class="conflict-banner" data-testid="query-blocked">🚫 {{ result.message }}</div>
        <div v-else class="result-meta" data-testid="query-meta">
          采纳来源 <b>{{ result.采纳来源 }}</b> · 实际粒度 <b>{{ result.实际粒度 }}</b> ·
          已聚合 {{ result.totals.已聚合金额 }} 元 / {{ result.totals.已聚合订单数 }} 笔 ·
          未覆盖 {{ result.totals.未覆盖金额 }} 元 / {{ result.totals.未覆盖订单数 }} 笔
        </div>
        <p class="page-desc">省/市小计可用层级：province → {{ result.level_availability?.province?.join(', ') || '无' }}；city → {{ result.level_availability?.city?.join(', ') || '无' }}</p>

        <table v-if="result.groups?.length" class="data-table" data-testid="group-table">
          <thead><tr><th>分组</th><th>层级</th><th>采纳来源</th><th>gmv</th><th>订单数</th><th>逐笔订单</th></tr></thead>
          <tbody>
            <tr v-for="g in result.groups" :key="g.分组键">
              <td>{{ g.分组名称 }}（{{ g.分组键 }}）</td><td>{{ g.层级 }}</td><td>{{ g.采纳来源 }}</td>
              <td>{{ g.gmv }}</td><td>{{ g.订单数 }}</td><td>{{ g.fact_order_ids.join(', ') }}</td>
            </tr>
          </tbody>
        </table>

        <h4>每笔金额落点核对</h4>
        <table class="data-table" data-testid="assignment-table">
          <thead><tr><th>订单</th><th>金额</th><th>事实键</th><th>采纳来源</th><th>层级</th><th>落点分组</th><th>是否计入</th><th>原因</th></tr></thead>
          <tbody>
            <tr v-for="a in result.fact_assignments" :key="a.order_id">
              <td>{{ a.order_id }}</td><td>{{ a.amount }}</td><td>{{ a.region_code }}</td>
              <td>{{ a.采纳来源 }}</td><td>{{ a.层级 }}</td>
              <td>{{ a.分组名称 || '—' }}</td>
              <td><span class="status-tag" :class="a.是否计入 ? 'st-active' : 'st-invalid'">{{ a.是否计入 ? '计入' : '未覆盖' }}</span></td>
              <td>{{ a.原因 }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <footer class="page-foot"><span>归属身份 = 来源 + 业务键；不同来源的同名维度不会被合并</span></footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { request } from '@/api/client'

const datePresets = [
  { label: '冲突前 09-14', value: '2026-09-14' },
  { label: '冲突日 09-15', value: '2026-09-15' },
  { label: '确认后 09-16', value: '2026-09-16' },
]
const bizDate = ref('2026-09-15')
const dataset = ref<any>({ records: [], conflicts: [], summary: null })
const queryLevel = ref('province')
const querySource = ref<string | null>(null)
const result = ref<any>(null)

function statusClass(status: string): string {
  if (status === 'ACTIVE') return 'st-active'
  if (status === 'READ_ONLY') return 'st-readonly'
  return 'st-invalid'
}

async function loadDataset() {
  const res = await request(`/api/dim_attribution/dataset?biz_date=${bizDate.value}`)
  dataset.value = await res.json()
}

async function selectDate(d: string) {
  bizDate.value = d
  result.value = null
  await loadDataset()
}

async function confirmRegistration(regId: string) {
  const res = await request(`/api/dim_attribution/${regId}/confirm`, { method: 'POST' })
  const body = await res.json()
  if (!body.ok) throw new Error(body.message)
  await loadDataset()
}

async function runQuery() {
  const params = new URLSearchParams({ dim_code: 'DIM-REGION', level: queryLevel.value, biz_date: bizDate.value })
  if (querySource.value) params.set('source', querySource.value)
  const res = await request(`/api/cube_dimension_query/aggregate?${params.toString()}`)
  result.value = await res.json()
}

onMounted(loadDataset)
</script>

<style scoped>
.card { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
.data-table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 8px; }
.data-table th, .data-table td { border: 1px solid var(--border); padding: 6px 8px; text-align: left; vertical-align: top; }
.data-table th { background: #f8fafc; }
.status-tag { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; }
.st-active { background: #d1fae5; color: #065f46; }
.st-readonly { background: #fef3c7; color: #92400e; }
.st-invalid { background: #fee2e2; color: #991b1b; }
.conflict-flag { margin-left: 6px; background: #ffedd5; color: #9a3412; border-radius: 8px; padding: 0 6px; font-size: 11px; }
.conflict-banner { background: #fff7ed; border: 1px solid #fdba74; color: #9a3412; border-radius: 8px; padding: 8px 12px; margin: 8px 0; font-size: 13px; }
.reason-line { color: var(--muted); font-size: 11px; }
.query-bar { display: flex; gap: 12px; align-items: center; margin: 10px 0; }
.query-bar select { padding: 4px 8px; border-radius: 6px; border: 1px solid var(--border); }
.result-meta { background: #f0f9ff; border: 1px solid #7dd3fc; border-radius: 8px; padding: 8px 12px; font-size: 13px; }
h4 { margin: 14px 0 4px; }
</style>
