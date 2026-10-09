<template>
  <div class="blacklist-page art-full-height">
    <ElTabs v-model="activeTab" class="blacklist-tabs">
      <ElTabPane label="人员" name="persons">
        <ArtSearchBar
          v-model="personSearch"
          :items="searchItems"
          :default-expanded="true"
          :show-expand="false"
          :disabled="personBusy"
          :disabled-search="personBusy"
          @search="handlePersonSearch"
          @reset="resetPersonSearch"
        />

        <ElCard class="art-table-card" shadow="never">
          <div class="table-actions">
            <ElButton type="primary" :disabled="personBusy" @click="addPersonDraft"
              >新增人员</ElButton
            >
            <ElTag v-if="personDirty" type="warning" effect="plain">
              待保存 {{ personPendingCount }} 项
            </ElTag>
            <ElButton :disabled="!personDirty || personBusy" @click="discardPersonDrafts">
              放弃变更
            </ElButton>
            <ElButton
              type="primary"
              :loading="personSaving"
              :disabled="!personDirty || personBusy"
              @click="savePersonDrafts"
            >
              保存变更
            </ElButton>
          </div>

          <ElAlert
            v-if="personError"
            class="table-alert"
            :title="personError"
            type="error"
            show-icon
            :closable="false"
          />

          <ElTable
            v-loading="personLoading"
            :data="personRows"
            row-key="__row_key"
            border
            table-layout="fixed"
            empty-text="暂无人员黑名单"
          >
            <ElTableColumn label="人员 ID" min-width="160">
              <template #default="{ row }">
                <ElInput
                  v-model="row.person_id"
                  :disabled="personBusy"
                  @input="markPersonDirty(row)"
                />
              </template>
            </ElTableColumn>
            <ElTableColumn label="摘要" min-width="220">
              <template #default="{ row }">
                <ElInput
                  v-model="row.summary"
                  :disabled="personBusy"
                  @input="markPersonDirty(row)"
                />
              </template>
            </ElTableColumn>
            <ElTableColumn label="描述" min-width="260">
              <template #default="{ row }">
                <ElInput
                  v-model="row.description"
                  :disabled="personBusy"
                  @input="markPersonDirty(row)"
                />
              </template>
            </ElTableColumn>
            <ElTableColumn prop="hit_count" label="命中次数" width="100" />
            <ElTableColumn label="状态" width="90">
              <template #default="{ row }">
                <ElSwitch
                  v-model="row.enabled"
                  :disabled="personBusy"
                  @change="markPersonDirty(row)"
                />
              </template>
            </ElTableColumn>
            <ElTableColumn label="更新时间" min-width="170">
              <template #default="{ row }">
                {{ formatDate(row.updated_at) }}
              </template>
            </ElTableColumn>
            <ElTableColumn label="操作" width="90" fixed="right">
              <template #default="{ row }">
                <ElButton link type="danger" :disabled="personBusy" @click="markPersonDeleted(row)"
                  >删除</ElButton
                >
              </template>
            </ElTableColumn>
          </ElTable>

          <ElPagination
            :current-page="personSearch.current"
            :page-size="personSearch.size"
            class="table-pagination"
            layout="total, sizes, prev, pager, next"
            :page-sizes="[10, 20, 50, 100]"
            :total="personTotal"
            :disabled="personBusy"
            @size-change="handlePersonPageSizeChange"
            @current-change="handlePersonPageChange"
          />
        </ElCard>
      </ElTabPane>

      <ElTabPane label="关键词" name="keywords">
        <ArtSearchBar
          v-model="keywordSearch"
          :items="searchItems"
          :default-expanded="true"
          :show-expand="false"
          :disabled="keywordBusy"
          :disabled-search="keywordBusy"
          @search="handleKeywordSearch"
          @reset="resetKeywordSearch"
        />

        <ElCard class="art-table-card" shadow="never">
          <div class="table-actions">
            <ElButton type="primary" :disabled="keywordBusy" @click="addKeywordDraft"
              >新增关键词</ElButton
            >
            <ElTag v-if="keywordDirty" type="warning" effect="plain">
              待保存 {{ keywordPendingCount }} 项
            </ElTag>
            <ElButton :disabled="!keywordDirty || keywordBusy" @click="discardKeywordDrafts">
              放弃变更
            </ElButton>
            <ElButton
              type="primary"
              :loading="keywordSaving"
              :disabled="!keywordDirty || keywordBusy"
              @click="saveKeywordDrafts"
            >
              保存变更
            </ElButton>
          </div>

          <ElAlert
            v-if="keywordError"
            class="table-alert"
            :title="keywordError"
            type="error"
            show-icon
            :closable="false"
          />

          <ElTable
            v-loading="keywordLoading"
            :data="keywordRows"
            row-key="__row_key"
            border
            table-layout="fixed"
            empty-text="暂无关键词黑名单"
          >
            <ElTableColumn label="关键词" min-width="180">
              <template #default="{ row }">
                <ElInput
                  v-model="row.keyword"
                  :disabled="keywordBusy"
                  @input="markKeywordDirty(row)"
                />
              </template>
            </ElTableColumn>
            <ElTableColumn label="摘要" min-width="220">
              <template #default="{ row }">
                <ElInput
                  v-model="row.summary"
                  :disabled="keywordBusy"
                  @input="markKeywordDirty(row)"
                />
              </template>
            </ElTableColumn>
            <ElTableColumn label="描述" min-width="260">
              <template #default="{ row }">
                <ElInput
                  v-model="row.description"
                  :disabled="keywordBusy"
                  @input="markKeywordDirty(row)"
                />
              </template>
            </ElTableColumn>
            <ElTableColumn prop="hit_count" label="命中次数" width="100" />
            <ElTableColumn label="状态" width="90">
              <template #default="{ row }">
                <ElSwitch
                  v-model="row.enabled"
                  :disabled="keywordBusy"
                  @change="markKeywordDirty(row)"
                />
              </template>
            </ElTableColumn>
            <ElTableColumn label="更新时间" min-width="170">
              <template #default="{ row }">
                {{ formatDate(row.updated_at) }}
              </template>
            </ElTableColumn>
            <ElTableColumn label="操作" width="90" fixed="right">
              <template #default="{ row }">
                <ElButton
                  link
                  type="danger"
                  :disabled="keywordBusy"
                  @click="markKeywordDeleted(row)"
                  >删除</ElButton
                >
              </template>
            </ElTableColumn>
          </ElTable>

          <ElPagination
            :current-page="keywordSearch.current"
            :page-size="keywordSearch.size"
            class="table-pagination"
            layout="total, sizes, prev, pager, next"
            :page-sizes="[10, 20, 50, 100]"
            :total="keywordTotal"
            :disabled="keywordBusy"
            @size-change="handleKeywordPageSizeChange"
            @current-change="handleKeywordPageChange"
          />
        </ElCard>
      </ElTabPane>

      <ElTabPane label="典型事件" name="events">
        <ArtSearchBar
          v-model="eventSearch"
          :items="searchItems"
          :default-expanded="true"
          :show-expand="false"
          @search="handleEventSearch"
          @reset="resetEventSearch"
        />

        <ElCard class="art-table-card" shadow="never">
          <div class="table-actions">
            <ElButton type="primary" @click="openCreateEventDialog">新增典型事件</ElButton>
          </div>

          <ElAlert
            v-if="eventError"
            class="table-alert"
            :title="eventError"
            type="error"
            show-icon
            :closable="false"
          />

          <ElTable
            v-loading="eventLoading"
            :data="eventRows"
            row-key="sample_id"
            border
            table-layout="fixed"
            empty-text="暂无典型事件"
          >
            <ElTableColumn prop="sample_id" label="事件 ID" min-width="170" />
            <ElTableColumn prop="summary" label="摘要" min-width="300" show-overflow-tooltip />
            <ElTableColumn prop="description" label="描述" min-width="300" show-overflow-tooltip />
            <ElTableColumn label="状态" width="90">
              <template #default="{ row }">
                <ElSwitch
                  :model-value="row.enabled"
                  :loading="eventTogglingIds.has(row.sample_id)"
                  :disabled="eventTogglingIds.has(row.sample_id)"
                  @change="(enabled) => toggleEventEnabled(row, enabled)"
                />
              </template>
            </ElTableColumn>
            <ElTableColumn label="更新时间" min-width="170">
              <template #default="{ row }">
                {{ formatDate(row.updated_at) }}
              </template>
            </ElTableColumn>
            <ElTableColumn label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <ElButton
                  link
                  type="primary"
                  :disabled="eventTogglingIds.has(row.sample_id)"
                  @click="openEditEventDialog(row)"
                >
                  编辑
                </ElButton>
                <ElButton
                  link
                  type="danger"
                  :disabled="eventTogglingIds.has(row.sample_id)"
                  @click="confirmDeleteEvent(row)"
                >
                  删除
                </ElButton>
              </template>
            </ElTableColumn>
          </ElTable>

          <ElPagination
            v-model:current-page="eventSearch.current"
            v-model:page-size="eventSearch.size"
            class="table-pagination"
            layout="total, sizes, prev, pager, next"
            :page-sizes="[10, 20, 50, 100]"
            :total="eventTotal"
            @size-change="loadEvents"
            @current-change="loadEvents"
          />
        </ElCard>

        <ElDialog v-model="eventDialogVisible" title="典型事件" width="min(600px, 92vw)">
          <ElForm label-width="92px">
            <ElFormItem label="事件 ID" required>
              <ElInput v-model="eventForm.sample_id" maxlength="128" show-word-limit />
            </ElFormItem>
            <ElFormItem label="摘要" required>
              <ElInput
                v-model="eventForm.summary"
                type="textarea"
                :rows="4"
                maxlength="2048"
                show-word-limit
                resize="none"
              />
            </ElFormItem>
            <ElFormItem label="描述">
              <ElInput
                v-model="eventForm.description"
                type="textarea"
                :rows="4"
                maxlength="8192"
                show-word-limit
                resize="none"
              />
            </ElFormItem>
            <ElFormItem label="启用">
              <ElSwitch v-model="eventForm.enabled" />
            </ElFormItem>
          </ElForm>

          <template #footer>
            <ElButton @click="eventDialogVisible = false">取消</ElButton>
            <ElButton type="primary" :loading="eventSaving" @click="submitEventDialog">
              保存
            </ElButton>
          </template>
        </ElDialog>
      </ElTabPane>
    </ElTabs>
  </div>
</template>

<script setup lang="ts">
  import { ElMessageBox } from 'element-plus'
  import {
    createBlacklistEvent,
    deleteBlacklistEvent,
    fetchBlacklistEvents,
    fetchBlacklistKeywords,
    fetchBlacklistPersons,
    saveBlacklistKeywords,
    saveBlacklistPersons,
    setBlacklistEventEnabled,
    updateBlacklistEvent
  } from '@/api/sentinel/blacklist'
  import type {
    BlacklistEventSampleItem,
    BlacklistEventSavePayload,
    BlacklistKeywordBatchPayload,
    BlacklistKeywordItem,
    BlacklistPersonBatchPayload,
    BlacklistPersonItem,
    BlacklistSearchParams
  } from '@/api/sentinel/types'
  import type { SearchFormItem } from '@/components/core/forms/art-search-bar/index.vue'

  defineOptions({ name: 'SentinelBlacklist' })

  type TabName = 'persons' | 'keywords' | 'events'

  type PersonDraft = BlacklistPersonItem & {
    __row_key: string
    __new?: boolean
    __dirty?: boolean
    __old_key?: string
  }

  type KeywordDraft = BlacklistKeywordItem & {
    __row_key: string
    __new?: boolean
    __dirty?: boolean
    __old_key?: string
  }

  const activeTab = ref<TabName>('persons')

  const statusOptions = [
    { label: '启用', value: true },
    { label: '停用', value: false }
  ]

  const searchItems: SearchFormItem[] = [
    {
      key: 'keyword',
      label: '查找',
      type: 'input',
      props: { placeholder: 'ID / 关键词 / 摘要 / 描述', clearable: true }
    },
    {
      key: 'enabled',
      label: '状态',
      type: 'select',
      props: { placeholder: '全部状态', clearable: true, options: statusOptions }
    }
  ]

  const personSearch = ref<BlacklistSearchParams>({ current: 1, size: 20 })
  const keywordSearch = ref<BlacklistSearchParams>({ current: 1, size: 20 })
  const eventSearch = ref<BlacklistSearchParams>({ current: 1, size: 20 })

  const personRows = ref<PersonDraft[]>([])
  const keywordRows = ref<KeywordDraft[]>([])
  const eventRows = ref<BlacklistEventSampleItem[]>([])
  const personDeleted = ref<PersonDraft[]>([])
  const keywordDeleted = ref<KeywordDraft[]>([])

  const personTotal = ref(0)
  const keywordTotal = ref(0)
  const eventTotal = ref(0)

  const personLoading = ref(false)
  const keywordLoading = ref(false)
  const eventLoading = ref(false)
  const personSaving = ref(false)
  const keywordSaving = ref(false)
  const eventSaving = ref(false)
  const eventTogglingIds = ref(new Set<string>())
  const personError = ref('')
  const keywordError = ref('')
  const eventError = ref('')

  const eventDialogVisible = ref(false)
  const editingEventOriginalId = ref('')
  const eventForm = reactive<BlacklistEventSavePayload>({
    sample_id: '',
    summary: '',
    description: '',
    enabled: true,
    expected_updated_at: ''
  })

  const personDirty = computed(
    () => personRows.value.some((row) => row.__new || row.__dirty) || personDeleted.value.length > 0
  )
  const keywordDirty = computed(
    () =>
      keywordRows.value.some((row) => row.__new || row.__dirty) || keywordDeleted.value.length > 0
  )
  const personPendingCount = computed(
    () =>
      personRows.value.filter((row) => row.__new || row.__dirty).length + personDeleted.value.length
  )
  const keywordPendingCount = computed(
    () =>
      keywordRows.value.filter((row) => row.__new || row.__dirty).length +
      keywordDeleted.value.length
  )
  const personBusy = computed(() => personLoading.value || personSaving.value)
  const keywordBusy = computed(() => keywordLoading.value || keywordSaving.value)
  const hasUnsavedBatchDrafts = computed(() => personDirty.value || keywordDirty.value)

  const errorMessage = (error: unknown, fallback: string) =>
    error instanceof Error ? error.message : fallback

  const formatDate = (value?: string) => {
    if (!value) return '-'
    return new Date(value).toLocaleString('zh-CN', { hour12: false })
  }

  const hasDuplicateValues = (values: string[]) => new Set(values).size !== values.length
  const normalizePersonId = (value: string) => value.trim().toUpperCase()

  const personRowKey = (personId: string) => `person-${personId || Date.now()}`
  const keywordRowKey = (keywordId: string) => `keyword-${keywordId || Date.now()}`

  const toPersonDraft = (row: BlacklistPersonItem): PersonDraft => ({
    ...row,
    __row_key: personRowKey(row.person_id),
    __old_key: row.person_id
  })

  const toKeywordDraft = (row: BlacklistKeywordItem): KeywordDraft => ({
    ...row,
    __row_key: keywordRowKey(row.keyword_id),
    __old_key: row.keyword
  })

  const loadPersons = async () => {
    personLoading.value = true
    personError.value = ''
    try {
      const response = await fetchBlacklistPersons(personSearch.value)
      personRows.value = response.items.map(toPersonDraft)
      personDeleted.value = []
      personTotal.value = response.total
      personSearch.value.current = response.current
      personSearch.value.size = response.size
    } catch (error) {
      personError.value = errorMessage(error, '人员黑名单加载失败')
    } finally {
      personLoading.value = false
    }
  }

  const loadKeywords = async () => {
    keywordLoading.value = true
    keywordError.value = ''
    try {
      const response = await fetchBlacklistKeywords(keywordSearch.value)
      keywordRows.value = response.items.map(toKeywordDraft)
      keywordDeleted.value = []
      keywordTotal.value = response.total
      keywordSearch.value.current = response.current
      keywordSearch.value.size = response.size
    } catch (error) {
      keywordError.value = errorMessage(error, '关键词黑名单加载失败')
    } finally {
      keywordLoading.value = false
    }
  }

  const loadEvents = async () => {
    eventLoading.value = true
    eventError.value = ''
    try {
      const response = await fetchBlacklistEvents(eventSearch.value)
      eventRows.value = response.items
      eventTotal.value = response.total
      eventSearch.value.current = response.current
      eventSearch.value.size = response.size
    } catch (error) {
      eventError.value = errorMessage(error, '典型事件加载失败')
    } finally {
      eventLoading.value = false
    }
  }

  const confirmDiscardPending = async (dirty: boolean) => {
    if (!dirty) return true
    try {
      await ElMessageBox.confirm('当前有未保存变更，继续操作会丢弃这些变更。', '丢弃变更确认', {
        type: 'warning',
        confirmButtonText: '继续',
        cancelButtonText: '取消'
      })
      return true
    } catch {
      return false
    }
  }

  const handlePersonSearch = async (params: BlacklistSearchParams) => {
    if (personBusy.value) return
    if (!(await confirmDiscardPending(personDirty.value))) return
    personSearch.value = { ...personSearch.value, ...params, current: 1 }
    await loadPersons()
  }

  const resetPersonSearch = async () => {
    if (personBusy.value) return
    if (!(await confirmDiscardPending(personDirty.value))) return
    personSearch.value = { current: 1, size: 20 }
    await loadPersons()
  }

  const handleKeywordSearch = async (params: BlacklistSearchParams) => {
    if (keywordBusy.value) return
    if (!(await confirmDiscardPending(keywordDirty.value))) return
    keywordSearch.value = { ...keywordSearch.value, ...params, current: 1 }
    await loadKeywords()
  }

  const resetKeywordSearch = async () => {
    if (keywordBusy.value) return
    if (!(await confirmDiscardPending(keywordDirty.value))) return
    keywordSearch.value = { current: 1, size: 20 }
    await loadKeywords()
  }

  const handleEventSearch = async (params: BlacklistSearchParams) => {
    eventSearch.value = { ...eventSearch.value, ...params, current: 1 }
    await loadEvents()
  }

  const resetEventSearch = async () => {
    eventSearch.value = { current: 1, size: 20 }
    await loadEvents()
  }

  const handlePersonPageChange = async (current: number) => {
    if (personBusy.value) return
    if (!(await confirmDiscardPending(personDirty.value))) return
    personSearch.value.current = current
    await loadPersons()
  }

  const handlePersonPageSizeChange = async (size: number) => {
    if (personBusy.value) return
    if (!(await confirmDiscardPending(personDirty.value))) return
    personSearch.value = { ...personSearch.value, current: 1, size }
    await loadPersons()
  }

  const handleKeywordPageChange = async (current: number) => {
    if (keywordBusy.value) return
    if (!(await confirmDiscardPending(keywordDirty.value))) return
    keywordSearch.value.current = current
    await loadKeywords()
  }

  const handleKeywordPageSizeChange = async (size: number) => {
    if (keywordBusy.value) return
    if (!(await confirmDiscardPending(keywordDirty.value))) return
    keywordSearch.value = { ...keywordSearch.value, current: 1, size }
    await loadKeywords()
  }

  const addPersonDraft = () => {
    if (personBusy.value) return
    const draftKey = `draft-${Date.now()}`
    personRows.value.unshift({
      person_id: '',
      summary: '',
      description: '',
      hit_count: 0,
      enabled: true,
      created_at: '',
      updated_at: '',
      __row_key: `person-${draftKey}`,
      __new: true,
      __dirty: true,
      __old_key: ''
    })
  }

  const addKeywordDraft = () => {
    if (keywordBusy.value) return
    const draftKey = `draft-${Date.now()}`
    keywordRows.value.unshift({
      keyword_id: draftKey,
      keyword: '',
      summary: '',
      description: '',
      hit_count: 0,
      enabled: true,
      created_at: '',
      updated_at: '',
      __row_key: `keyword-${draftKey}`,
      __new: true,
      __dirty: true,
      __old_key: ''
    })
  }

  const markPersonDirty = (row: PersonDraft) => {
    if (personBusy.value) return
    row.__dirty = true
  }

  const markKeywordDirty = (row: KeywordDraft) => {
    if (keywordBusy.value) return
    row.__dirty = true
  }

  const stripPersonDraft = (row: PersonDraft) => ({
    person_id: normalizePersonId(row.person_id),
    summary: row.summary,
    description: row.description,
    enabled: row.enabled
  })

  const stripKeywordDraft = (row: KeywordDraft) => ({
    keyword: row.keyword.trim(),
    summary: row.summary,
    description: row.description,
    enabled: row.enabled
  })

  const buildPersonChangeset = (): BlacklistPersonBatchPayload => ({
    created: personRows.value.filter((row) => row.__new).map(stripPersonDraft),
    updated: personRows.value
      .filter((row) => row.__dirty && !row.__new)
      .map((row) => ({
        old_key: row.__old_key || row.person_id,
        expected_updated_at: row.updated_at,
        ...stripPersonDraft(row)
      })),
    deleted: personDeleted.value.map((row) => ({
      key: row.__old_key || row.person_id,
      expected_updated_at: row.updated_at
    }))
  })

  const buildKeywordChangeset = (): BlacklistKeywordBatchPayload => ({
    created: keywordRows.value.filter((row) => row.__new).map(stripKeywordDraft),
    updated: keywordRows.value
      .filter((row) => row.__dirty && !row.__new)
      .map((row) => ({
        old_key: row.__old_key || row.keyword,
        expected_updated_at: row.updated_at,
        ...stripKeywordDraft(row)
      })),
    deleted: keywordDeleted.value.map((row) => ({
      key: row.__old_key || row.keyword,
      expected_updated_at: row.updated_at
    }))
  })

  const validatePersonDrafts = () => {
    const ids = personRows.value.map((row) => normalizePersonId(row.person_id)).filter(Boolean)
    if (ids.length !== personRows.value.length) {
      ElMessage.warning('人员 ID 不能为空')
      return false
    }
    if (hasDuplicateValues(ids)) {
      ElMessage.warning('人员 ID 不能重复')
      return false
    }
    return true
  }

  const validateKeywordDrafts = () => {
    const keywords = keywordRows.value.map((row) => row.keyword.trim()).filter(Boolean)
    if (keywords.length !== keywordRows.value.length) {
      ElMessage.warning('关键词不能为空')
      return false
    }
    if (hasDuplicateValues(keywords)) {
      ElMessage.warning('关键词不能重复')
      return false
    }
    return true
  }

  const markPersonDeleted = async (row: PersonDraft) => {
    if (personBusy.value) return
    try {
      await ElMessageBox.confirm(
        `确定硬删除人员 ${row.person_id || '未命名'}？删除后将不再参与黑名单人员匹配。`,
        '硬删除确认',
        { type: 'warning', confirmButtonText: '硬删除', cancelButtonText: '取消' }
      )
      personRows.value = personRows.value.filter((item) => item !== row)
      if (!row.__new) {
        personDeleted.value.push(row)
      }
    } catch {
      // User cancelled.
    }
  }

  const markKeywordDeleted = async (row: KeywordDraft) => {
    if (keywordBusy.value) return
    try {
      await ElMessageBox.confirm(
        `确定硬删除关键词 ${row.keyword || '未命名'}？删除后将不再参与黑名单关键词匹配。`,
        '硬删除确认',
        { type: 'warning', confirmButtonText: '硬删除', cancelButtonText: '取消' }
      )
      keywordRows.value = keywordRows.value.filter((item) => item !== row)
      if (!row.__new) {
        keywordDeleted.value.push(row)
      }
    } catch {
      // User cancelled.
    }
  }

  const discardPersonDrafts = async () => {
    if (!(await confirmDiscardPending(personDirty.value))) return
    await loadPersons()
  }

  const discardKeywordDrafts = async () => {
    if (!(await confirmDiscardPending(keywordDirty.value))) return
    await loadKeywords()
  }

  const savePersonDrafts = async () => {
    if (personSaving.value) return
    if (!validatePersonDrafts()) return
    personSaving.value = true
    try {
      await saveBlacklistPersons(buildPersonChangeset())
      ElMessage.success('人员黑名单已保存')
      await loadPersons()
    } catch (error) {
      ElMessage.error(errorMessage(error, '人员黑名单保存失败'))
    } finally {
      personSaving.value = false
    }
  }

  const saveKeywordDrafts = async () => {
    if (keywordSaving.value) return
    if (!validateKeywordDrafts()) return
    keywordSaving.value = true
    try {
      await saveBlacklistKeywords(buildKeywordChangeset())
      ElMessage.success('关键词黑名单已保存')
      await loadKeywords()
    } catch (error) {
      ElMessage.error(errorMessage(error, '关键词黑名单保存失败'))
    } finally {
      keywordSaving.value = false
    }
  }

  const openCreateEventDialog = () => {
    editingEventOriginalId.value = ''
    Object.assign(eventForm, {
      sample_id: '',
      summary: '',
      description: '',
      enabled: true,
      expected_updated_at: ''
    })
    eventDialogVisible.value = true
  }

  const openEditEventDialog = (row: BlacklistEventSampleItem) => {
    editingEventOriginalId.value = row.sample_id
    Object.assign(eventForm, {
      sample_id: row.sample_id,
      summary: row.summary,
      description: row.description,
      enabled: row.enabled,
      expected_updated_at: row.updated_at
    })
    eventDialogVisible.value = true
  }

  const submitEventDialog = async () => {
    if (!eventForm.sample_id.trim()) {
      ElMessage.warning('典型事件 ID 不能为空')
      return
    }
    if (!eventForm.summary.trim()) {
      ElMessage.warning('典型事件摘要不能为空')
      return
    }
    eventSaving.value = true
    try {
      const payload = {
        sample_id: eventForm.sample_id.trim(),
        summary: eventForm.summary.trim(),
        description: eventForm.description,
        enabled: eventForm.enabled,
        expected_updated_at: eventForm.expected_updated_at
      }
      if (editingEventOriginalId.value) {
        await updateBlacklistEvent(editingEventOriginalId.value, payload)
      } else {
        await createBlacklistEvent(payload)
      }
      ElMessage.success('典型事件已保存')
      eventDialogVisible.value = false
      await loadEvents()
    } catch (error) {
      ElMessage.error(errorMessage(error, '典型事件保存失败'))
    } finally {
      eventSaving.value = false
    }
  }

  const toggleEventEnabled = async (
    row: BlacklistEventSampleItem,
    enabled: string | number | boolean
  ) => {
    if (typeof enabled !== 'boolean') return
    eventTogglingIds.value = new Set(eventTogglingIds.value).add(row.sample_id)
    try {
      await setBlacklistEventEnabled(row.sample_id, enabled, row.updated_at)
      ElMessage.success('典型事件状态已更新')
      await loadEvents()
    } catch (error) {
      ElMessage.error(errorMessage(error, '典型事件状态更新失败'))
    } finally {
      const next = new Set(eventTogglingIds.value)
      next.delete(row.sample_id)
      eventTogglingIds.value = next
    }
  }

  const confirmDeleteEvent = async (row: BlacklistEventSampleItem) => {
    try {
      await ElMessageBox.confirm(
        `确定硬删除典型事件 ${row.sample_id}？删除后将不再参与黑名单相似事件匹配。`,
        '硬删除确认',
        { type: 'warning', confirmButtonText: '硬删除', cancelButtonText: '取消' }
      )
      await deleteBlacklistEvent(row.sample_id, { expected_updated_at: row.updated_at })
      ElMessage.success('典型事件已删除')
      await loadEvents()
    } catch (error) {
      if (error instanceof Error) {
        ElMessage.error(errorMessage(error, '典型事件删除失败'))
      }
    }
  }

  const handleBeforeUnload = (event: BeforeUnloadEvent) => {
    if (!hasUnsavedBatchDrafts.value) return
    event.preventDefault()
    event.returnValue = ''
  }

  onMounted(() => {
    window.addEventListener('beforeunload', handleBeforeUnload)
    void loadPersons()
  })

  onBeforeUnmount(() => {
    window.removeEventListener('beforeunload', handleBeforeUnload)
  })

  onBeforeRouteLeave(async () => {
    if (!hasUnsavedBatchDrafts.value) return true
    return await confirmDiscardPending(true)
  })

  watch(activeTab, async (tab) => {
    if (tab === 'keywords' && keywordRows.value.length === 0) {
      await loadKeywords()
    }
    if (tab === 'events' && eventRows.value.length === 0) {
      await loadEvents()
    }
  })
</script>

<style scoped>
  .blacklist-page {
    display: grid;
    gap: 16px;
  }

  .blacklist-tabs {
    min-width: 0;
  }

  .blacklist-tabs :deep(.el-tabs__content) {
    overflow: visible;
  }

  .table-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    justify-content: flex-end;
    margin-bottom: 14px;
  }

  .table-alert {
    margin-bottom: 14px;
  }

  .table-pagination {
    justify-content: flex-end;
    margin-top: 16px;
  }

  @media (max-width: 768px) {
    .table-actions,
    .table-pagination {
      justify-content: flex-start;
    }
  }
</style>
