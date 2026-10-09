<template>
  <div :class="graphClass">
    <div class="graph-toolbar">
      <div>
        <strong>Neo4j 关系图谱</strong>
        <span>{{ graph.nodes.length }} 个节点 / {{ validEdges.length }} 条边</span>
      </div>
      <div class="toolbar-actions">
        <button type="button" title="放大" @click="zoom = Math.min(2.4, zoom + 0.12)">
          <ArtSvgIcon icon="ri:zoom-in-line" />
        </button>
        <button type="button" title="缩小" @click="zoom = Math.max(0.35, zoom - 0.12)">
          <ArtSvgIcon icon="ri:zoom-out-line" />
        </button>
        <button type="button" title="重置视图" @click="resetView">
          <ArtSvgIcon icon="ri:refresh-line" />
        </button>
        <button
          type="button"
          :title="fullscreen ? '退出全屏' : '全屏'"
          @click="fullscreen = !fullscreen"
        >
          <ArtSvgIcon :icon="fullscreen ? 'ri:fullscreen-exit-line' : 'ri:fullscreen-line'" />
        </button>
      </div>
    </div>

    <div class="graph-body">
      <div class="graph-canvas">
        <svg
          v-if="graph.nodes.length"
          class="graph-svg"
          :viewBox="`0 0 ${layout.width} ${layout.height}`"
          @wheel="onWheel"
          @pointerdown="startPan"
          @pointermove="movePointer"
          @pointerup="stopPointer"
          @pointerleave="stopPointer"
        >
          <defs>
            <pattern id="sentinel-graph-grid" width="28" height="28" patternUnits="userSpaceOnUse">
              <path d="M 28 0 L 0 0 0 28" fill="none" stroke="#d7e0ea" stroke-width="0.7" />
            </pattern>
            <marker
              id="sentinel-graph-arrow"
              markerWidth="9"
              markerHeight="9"
              refX="10"
              refY="6"
              viewBox="0 0 12 12"
              orient="auto"
              markerUnits="userSpaceOnUse"
            >
              <path d="M2,2 L10,6 L2,10 z" fill="#778393" />
            </marker>
          </defs>

          <rect :width="layout.width" :height="layout.height" fill="url(#sentinel-graph-grid)" />
          <g :transform="viewTransform">
            <g
              v-for="edge in layout.edges"
              :key="edge.id || `${edge.source}-${edge.target}-${edge.label}`"
            >
              <path
                class="graph-edge"
                :d="edge.path"
                marker-end="url(#sentinel-graph-arrow)"
                @click.stop="selectItem('edge', edge)"
              />
              <text
                class="graph-edge-label"
                :x="edge.labelX"
                :y="edge.labelY"
                text-anchor="middle"
                @click.stop="selectItem('edge', edge)"
              >
                {{ short(edge.label || edge.type, 28) }}
              </text>
            </g>

            <g
              v-for="node in graph.nodes"
              :key="node.id"
              class="graph-node"
              @pointerdown.stop="startNodeDrag($event, node)"
              @click.stop="selectItem('node', node)"
            >
              <circle
                :cx="layout.positions[node.id]?.x"
                :cy="layout.positions[node.id]?.y"
                :r="nodeRadius(node)"
                :fill="nodeColor(node)"
              />
              <text
                class="graph-node-name"
                :x="layout.positions[node.id]?.x"
                :y="(layout.positions[node.id]?.y || 0) + nodeRadius(node) + 17"
                text-anchor="middle"
              >
                {{ short(displayName(node), 18) }}
              </text>
            </g>
          </g>
        </svg>
        <ElEmpty v-else description="暂无 Neo4j 图谱数据" />

        <div v-if="legend.length" class="graph-legend">
          <strong>节点类型</strong>
          <span v-for="item in legend" :key="item.type">
            <i :style="{ background: item.color }"></i>{{ item.label }}
          </span>
        </div>
      </div>

      <aside class="graph-detail">
        <template v-if="selected">
          <div class="detail-head">
            <h4>{{ selected.kind === 'node' ? '节点详情' : '关系详情' }}</h4>
            <button type="button" title="关闭详情" @click="selected = null">
              <ArtSvgIcon icon="ri:close-line" />
            </button>
          </div>
          <div class="detail-main">
            <span>{{ selected.kind === 'node' ? '名称' : '关系' }}</span>
            <strong>{{ detailName }}</strong>
          </div>
          <div class="detail-main">
            <span>{{ selected.kind === 'node' ? '标签' : '类型' }}</span>
            <strong>{{ detailLabel }}</strong>
          </div>
          <div class="detail-main">
            <span>Properties summary</span>
            <strong>{{ propertySummary }}</strong>
          </div>
        </template>
        <p v-else class="detail-empty">点击图中的节点或关系查看 Neo4j 属性。</p>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
  import { computed, ref, watch } from 'vue'
  import type { GraphEdge, GraphNode, PersonGraph } from '@/api/sentinel/types'

  type LayoutEdge = GraphEdge & { path: string; labelX: number; labelY: number }
  type SelectedItem = { kind: 'node'; data: GraphNode } | { kind: 'edge'; data: LayoutEdge }

  const props = defineProps<{ graph: PersonGraph }>()

  const selected = ref<SelectedItem | null>(null)
  const zoom = ref(1)
  const pan = ref({ x: 0, y: 0 })
  const fullscreen = ref(false)
  const dragging = ref(false)
  const dragStart = ref({ x: 0, y: 0, px: 0, py: 0 })
  const nodeDrag = ref<{ id: string; dx: number; dy: number } | null>(null)
  const manualPositions = ref<Record<string, { x: number; y: number }>>({})

  watch(
    () => props.graph,
    () => {
      selected.value = null
      dragging.value = false
      nodeDrag.value = null
      zoom.value = 1
      pan.value = { x: 0, y: 0 }
      manualPositions.value = {}
    }
  )

  const palette: Record<string, string> = {
    Customer: '#c9445a',
    Account: '#7b61b3',
    Merchant: '#2c9b72',
    Device: '#2f84c7',
    RiskSignal: '#d98a28',
    RiskEvent: '#2383d1',
    Episodic: '#2383d1',
    Entity: '#0f5f91'
  }

  const typeLabels: Record<string, string> = {
    Customer: '客户',
    Account: '账户',
    Merchant: '商户/机构',
    Device: '设备',
    RiskSignal: '风险信号',
    RiskEvent: '事件',
    Episodic: '事件',
    Entity: '实体'
  }

  const validEdges = computed(() => {
    const nodeIds = new Set(props.graph.nodes.map((node) => node.id))
    return props.graph.edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
  })

  const layout = computed(() => {
    const width = 1280
    const height = 700
    const center = { x: width / 2, y: height / 2 }
    const positions: Record<string, { x: number; y: number }> = {}
    const velocities: Record<string, { x: number; y: number }> = {}
    const typeOffsets: Record<string, { x: number; y: number }> = {
      Customer: { x: -210, y: -90 },
      Account: { x: -260, y: 140 },
      Merchant: { x: 240, y: 110 },
      Device: { x: 30, y: 220 },
      RiskSignal: { x: 260, y: -130 },
      RiskEvent: { x: 0, y: 0 },
      Episodic: { x: 0, y: 0 }
    }

    props.graph.nodes.forEach((node, index) => {
      const angle = (index * 2.3999632297) % (Math.PI * 2)
      const radius = 80 + 34 * Math.sqrt(index)
      const offset = typeOffsets[normalizedType(node)] || { x: 0, y: 0 }
      positions[node.id] = manualPositions.value[node.id] || {
        x: center.x + offset.x + Math.cos(angle) * radius,
        y: center.y + offset.y + Math.sin(angle) * radius
      }
      velocities[node.id] = { x: 0, y: 0 }
    })

    for (let tick = 0; tick < 120; tick += 1) {
      for (let i = 0; i < props.graph.nodes.length; i += 1) {
        for (let j = i + 1; j < props.graph.nodes.length; j += 1) {
          const a = props.graph.nodes[i]
          const b = props.graph.nodes[j]
          const pa = positions[a.id]
          const pb = positions[b.id]
          let dx = pa.x - pb.x
          let dy = pa.y - pb.y
          const distance = Math.max(24, Math.sqrt(dx * dx + dy * dy))
          const force = 1550 / (distance * distance)
          dx /= distance
          dy /= distance
          velocities[a.id].x += dx * force
          velocities[a.id].y += dy * force
          velocities[b.id].x -= dx * force
          velocities[b.id].y -= dy * force
        }
      }

      for (const edge of validEdges.value) {
        const source = positions[edge.source]
        const target = positions[edge.target]
        const dx = target.x - source.x
        const dy = target.y - source.y
        const distance = Math.max(1, Math.sqrt(dx * dx + dy * dy))
        const force = (distance - 155) * 0.008
        velocities[edge.source].x += (dx / distance) * force
        velocities[edge.source].y += (dy / distance) * force
        velocities[edge.target].x -= (dx / distance) * force
        velocities[edge.target].y -= (dy / distance) * force
      }

      for (const node of props.graph.nodes) {
        if (manualPositions.value[node.id]) continue
        const p = positions[node.id]
        const v = velocities[node.id]
        v.x += (center.x - p.x) * 0.002
        v.y += (center.y - p.y) * 0.002
        p.x = Math.max(45, Math.min(width - 45, p.x + v.x))
        p.y = Math.max(45, Math.min(height - 45, p.y + v.y))
        v.x *= 0.82
        v.y *= 0.82
      }
    }

    const edgeGroups = new Map<string, GraphEdge[]>()
    for (const edge of validEdges.value) {
      const endpoints = [edge.source, edge.target].sort()
      const key = `${endpoints[0]}::${endpoints[1]}`
      edgeGroups.set(key, [...(edgeGroups.get(key) || []), edge])
    }

    const edges: LayoutEdge[] = validEdges.value.map((edge) => {
      const source = positions[edge.source]
      const target = positions[edge.target]
      const endpoints = [edge.source, edge.target].sort()
      const siblings = edgeGroups.get(`${endpoints[0]}::${endpoints[1]}`) || [edge]
      const siblingIndex = siblings.indexOf(edge)
      const offset = (siblingIndex - (siblings.length - 1) / 2) * 34
      const dx = target.x - source.x
      const dy = target.y - source.y
      const distance = Math.max(1, Math.sqrt(dx * dx + dy * dy))
      const ux = dx / distance
      const uy = dy / distance
      const nx = -uy
      const ny = ux
      const sourceNode = props.graph.nodes.find((node) => node.id === edge.source)
      const targetNode = props.graph.nodes.find((node) => node.id === edge.target)
      const sourceRadius = sourceNode ? nodeRadius(sourceNode) + 7 : 25
      const targetRadius = targetNode ? nodeRadius(targetNode) + 11 : 29
      const x1 = source.x + ux * sourceRadius
      const y1 = source.y + uy * sourceRadius
      const x2 = target.x - ux * targetRadius
      const y2 = target.y - uy * targetRadius
      const cx = (x1 + x2) / 2 + nx * offset
      const cy = (y1 + y2) / 2 + ny * offset
      const path =
        Math.abs(offset) < 1
          ? `M ${x1} ${y1} L ${x2} ${y2}`
          : `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`
      return { ...edge, path, labelX: cx, labelY: cy - 7 }
    })

    return { width, height, positions, edges }
  })

  const graphClass = computed(() => ({
    'neo4j-graph': true,
    fullscreen: fullscreen.value
  }))

  const viewTransform = computed(
    () => `translate(${pan.value.x} ${pan.value.y}) scale(${zoom.value})`
  )

  const legend = computed(() => {
    const types = Array.from(new Set(props.graph.nodes.map((node) => normalizedType(node))))
    return types.map((type) => ({
      type,
      label: typeLabels[type] || type,
      color: colorForType(type)
    }))
  })

  const detailName = computed(() => {
    if (!selected.value) return ''
    return selected.value.kind === 'node'
      ? displayName(selected.value.data)
      : selected.value.data.label || selected.value.data.type || ''
  })

  const detailLabel = computed(() => {
    if (!selected.value) return ''
    if (selected.value.kind === 'node') {
      const labels = selected.value.data.labels || []
      return labels.length ? labels.join(', ') : normalizedType(selected.value.data)
    }
    return selected.value.data.type || selected.value.data.label || ''
  })

  const propertySummary = computed(() => {
    const data = selected.value?.data
    const summary = data?.properties?.summary
    if (summary === null || summary === undefined || summary === '') return '-'
    return formatValue(summary)
  })

  function normalizedType(node: GraphNode) {
    const labels = node.labels || []
    const type = node.type || labels.find((label) => label !== 'Entity') || labels[0] || 'Entity'
    if (/customer|person/i.test(type)) return 'Customer'
    if (/account/i.test(type)) return 'Account'
    if (/merchant|organization|counterparty/i.test(type)) return 'Merchant'
    if (/device/i.test(type)) return 'Device'
    if (/signal/i.test(type)) return 'RiskSignal'
    if (/event|episode|episodic/i.test(type)) return 'RiskEvent'
    return type
  }

  function colorForType(type: string) {
    return palette[type] || palette.Entity
  }

  function nodeColor(node: GraphNode) {
    return colorForType(normalizedType(node))
  }

  function connectedCount(nodeId: string) {
    return validEdges.value.filter((edge) => edge.source === nodeId || edge.target === nodeId)
      .length
  }

  function nodeRadius(node: GraphNode) {
    if (normalizedType(node) === 'RiskEvent') return 32
    return 20 + Math.min(11, connectedCount(node.id) * 2.2)
  }

  function displayName(node: GraphNode) {
    return String(node.label || node.properties?.name || node.properties?.id_number || node.id)
  }

  function short(text?: unknown, limit = 24) {
    const value = String(text || '')
    return value.length > limit ? `${value.slice(0, limit)}...` : value
  }

  function formatValue(value: unknown) {
    if (Array.isArray(value)) return value.join(', ')
    if (typeof value === 'object' && value !== null) return JSON.stringify(value, null, 2)
    return String(value)
  }

  function graphPoint(event: PointerEvent) {
    const svg =
      event.currentTarget instanceof SVGElement ? event.currentTarget.closest('svg') : null
    if (!svg) return { x: 0, y: 0 }
    const rect = svg.getBoundingClientRect()
    const x = ((event.clientX - rect.left) / rect.width) * layout.value.width
    const y = ((event.clientY - rect.top) / rect.height) * layout.value.height
    return {
      x: (x - pan.value.x) / zoom.value,
      y: (y - pan.value.y) / zoom.value
    }
  }

  function onWheel(event: WheelEvent) {
    event.preventDefault()
    zoom.value = Math.max(0.35, Math.min(2.4, zoom.value + (event.deltaY > 0 ? -0.08 : 0.08)))
  }

  function startPan(event: PointerEvent) {
    dragging.value = true
    dragStart.value = { x: event.clientX, y: event.clientY, px: pan.value.x, py: pan.value.y }
  }

  function movePointer(event: PointerEvent) {
    if (nodeDrag.value) {
      const point = graphPoint(event)
      manualPositions.value = {
        ...manualPositions.value,
        [nodeDrag.value.id]: {
          x: Math.max(45, Math.min(layout.value.width - 45, point.x - nodeDrag.value.dx)),
          y: Math.max(45, Math.min(layout.value.height - 45, point.y - nodeDrag.value.dy))
        }
      }
      return
    }
    if (!dragging.value) return
    pan.value = {
      x: dragStart.value.px + event.clientX - dragStart.value.x,
      y: dragStart.value.py + event.clientY - dragStart.value.y
    }
  }

  function stopPointer() {
    dragging.value = false
    nodeDrag.value = null
  }

  function startNodeDrag(event: PointerEvent, node: GraphNode) {
    selectItem('node', node)
    const point = graphPoint(event)
    const position = layout.value.positions[node.id]
    nodeDrag.value = {
      id: node.id,
      dx: point.x - position.x,
      dy: point.y - position.y
    }
  }

  function selectItem(kind: 'node' | 'edge', data: GraphNode | LayoutEdge) {
    selected.value =
      kind === 'node' ? { kind, data: data as GraphNode } : { kind, data: data as LayoutEdge }
  }

  function resetView() {
    zoom.value = 1
    pan.value = { x: 0, y: 0 }
    manualPositions.value = {}
  }
</script>

<style scoped>
  .neo4j-graph {
    display: grid;
    min-height: 560px;
    overflow: hidden;
    background: var(--el-bg-color);
    border: 1px solid var(--el-border-color-lighter);
    border-radius: 8px;
  }

  .neo4j-graph.fullscreen {
    position: fixed;
    inset: 18px;
    z-index: 3000;
    min-height: auto;
    box-shadow: var(--el-box-shadow-dark);
  }

  .graph-toolbar {
    display: flex;
    gap: 12px;
    align-items: center;
    justify-content: space-between;
    padding: 12px 14px;
    background: var(--el-fill-color-lighter);
    border-bottom: 1px solid var(--el-border-color-lighter);
  }

  .graph-toolbar > div:first-child {
    display: grid;
    gap: 2px;
  }

  .graph-toolbar span,
  .detail-empty,
  .detail-main span {
    color: var(--el-text-color-secondary);
    font-size: 12px;
  }

  .toolbar-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  .toolbar-actions button,
  .detail-head button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 34px;
    height: 30px;
    color: var(--el-text-color-primary);
    cursor: pointer;
    background: var(--el-bg-color);
    border: 1px solid var(--el-border-color);
    border-radius: 6px;
  }

  .graph-body {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 280px;
    min-height: 520px;
  }

  .graph-canvas {
    position: relative;
    min-height: 520px;
    overflow: hidden;
    background: #f8fafc;
  }

  .graph-svg {
    width: 100%;
    height: 100%;
    min-height: 520px;
    cursor: grab;
    touch-action: none;
  }

  .graph-edge {
    fill: none;
    stroke: #778393;
    stroke-width: 1.8;
    cursor: pointer;
  }

  .graph-edge:hover {
    stroke: var(--el-color-primary);
    stroke-width: 2.4;
  }

  .graph-edge-label {
    font-size: 13px;
    cursor: pointer;
    fill: #4f5d6f;
    stroke: #fff;
    stroke-width: 4px;
    paint-order: stroke;
    user-select: none;
  }

  .graph-node {
    cursor: pointer;
  }

  .graph-node circle {
    filter: drop-shadow(0 8px 16px rgb(15 23 42 / 16%));
    stroke: #fff;
    stroke-width: 3;
  }

  .graph-node:hover circle {
    stroke: var(--el-color-primary-light-5);
    stroke-width: 5;
  }

  .graph-node-name {
    font-size: 13px;
    font-weight: 600;
    fill: #172033;
    stroke: #fff;
    stroke-width: 5px;
    paint-order: stroke;
    user-select: none;
  }

  .graph-legend {
    position: absolute;
    bottom: 12px;
    left: 12px;
    display: flex;
    flex-wrap: wrap;
    gap: 8px 12px;
    align-items: center;
    max-width: calc(100% - 24px);
    padding: 10px 12px;
    font-size: 12px;
    background: rgb(255 255 255 / 92%);
    border: 1px solid var(--el-border-color-lighter);
    border-radius: 8px;
    box-shadow: var(--el-box-shadow-light);
  }

  .graph-legend span {
    display: inline-flex;
    gap: 5px;
    align-items: center;
    color: var(--el-text-color-secondary);
  }

  .graph-legend i {
    width: 9px;
    height: 9px;
    border-radius: 50%;
  }

  .graph-detail {
    display: grid;
    gap: 14px;
    align-content: start;
    padding: 14px;
    overflow: auto;
    border-left: 1px solid var(--el-border-color-lighter);
  }

  .detail-head {
    display: flex;
    gap: 10px;
    align-items: center;
    justify-content: space-between;
  }

  .detail-head h4 {
    margin: 0;
  }

  .detail-main {
    display: grid;
    gap: 4px;
  }

  .detail-main strong {
    overflow-wrap: anywhere;
  }

  @media (max-width: 900px) {
    .graph-toolbar,
    .graph-body {
      grid-template-columns: 1fr;
    }

    .graph-toolbar {
      flex-direction: column;
      align-items: flex-start;
    }

    .graph-body {
      display: grid;
    }

    .graph-detail {
      border-top: 1px solid var(--el-border-color-lighter);
      border-left: 0;
    }
  }
</style>
