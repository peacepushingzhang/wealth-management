import { initialWorkspace } from './productData'
import { calculateIndexAction, rankFunds, type FundProduct, type IndexPurchase, type WealthWorkspace } from './domain'

const CACHE_KEY = 'wealthpilot.public.workspace.v1'
const SNAPSHOT_URL = `${import.meta.env.BASE_URL}market-snapshot.json`

type MarketSnapshot = Pick<
  WealthWorkspace,
  'depositRates' | 'indices' | 'fundProducts' | 'bondFunds' | 'syncStatus'
> & {
  schemaVersion?: number
  generatedAt?: string
}

const cloneInitial = () => JSON.parse(JSON.stringify(initialWorkspace)) as WealthWorkspace

const normalizeWorkspace = (workspace: WealthWorkspace): WealthWorkspace => ({
  ...workspace,
  purchases: workspace.purchases ?? [],
  syncStatus: {
    ...initialWorkspace.syncStatus,
    ...workspace.syncStatus,
  },
})

function cachedWorkspace() {
  const cached = localStorage.getItem(CACHE_KEY)
  if (!cached) return cloneInitial()
  try {
    return normalizeWorkspace(JSON.parse(cached) as WealthWorkspace)
  } catch {
    localStorage.removeItem(CACHE_KEY)
    return cloneInitial()
  }
}

async function fetchSnapshot(): Promise<MarketSnapshot> {
  const response = await fetch(`${SNAPSHOT_URL}?v=${Date.now()}`, { cache: 'no-store' })
  if (!response.ok) throw new Error('公开市场快照暂不可用')
  return response.json() as Promise<MarketSnapshot>
}

function applySnapshot(workspace: WealthWorkspace, snapshot: MarketSnapshot): WealthWorkspace {
  const localIndices = new Map(workspace.indices.map((item) => [item.code, item]))
  const indices = snapshot.indices.map((item) => {
    const local = localIndices.get(item.code)
    return local?.evidence?.provider === 'manual_entry' ? local : item
  })

  return normalizeWorkspace({
    ...workspace,
    depositRates: snapshot.depositRates,
    indices,
    fundProducts: snapshot.fundProducts,
    bondFunds: snapshot.bondFunds,
    syncStatus: snapshot.syncStatus,
  })
}

export async function loadWorkspace(): Promise<WealthWorkspace> {
  const local = cachedWorkspace()
  try {
    const workspace = applySnapshot(local, await fetchSnapshot())
    localStorage.setItem(CACHE_KEY, JSON.stringify(workspace))
    return workspace
  } catch {
    return local
  }
}

export async function saveWorkspace(workspace: WealthWorkspace) {
  localStorage.setItem(CACHE_KEY, JSON.stringify(normalizeWorkspace(workspace)))
  return true
}

function localAnswer(question: string, workspace: WealthWorkspace) {
  const index = workspace.indices.find((item) => question.toLowerCase().includes(item.name.toLowerCase()) || question.toUpperCase().includes(item.code.toUpperCase()))
  if (index && question.includes('基金')) {
    const ranked = rankFunds(workspace.fundProducts, index.code)
    if (!ranked.length) return `${index.name}的基金规模、跟踪误差和费率数据尚未同步，暂不生成产品推荐。`
    const summary = ranked.slice(0, 2).map((item) => `${item.venue}${item.name}（${item.code}）`).join('；')
    return `${index.name}当前通过数据门槛的候选：${summary}。请分别在证券软件和基金平台复核后购买。`
  }
  if (index) {
    if (index.pePercentile === null) return `${index.name}的 PE 历史百分位尚未同步，不能判断是否低于 40%。`
    return `${index.name}当前 PE 历史百分位为 ${index.pePercentile.toFixed(1)}%，规则状态：${calculateIndexAction(index.pePercentile)}。数据截至 ${index.asOf ?? '未知'}。`
  }
  return '请在问题中写出指数名称，例如“沪深300的 PE 百分位是多少”或“我要买标普500，请推荐场内和场外基金”。'
}

export async function askIndexAssistant(question: string, workspace: WealthWorkspace) {
  return localAnswer(question, workspace)
}

export async function syncIndexData() {
  const workspace = applySnapshot(cachedWorkspace(), await fetchSnapshot())
  localStorage.setItem(CACHE_KEY, JSON.stringify(workspace))
  return { status: 'success', asOf: workspace.syncStatus.indicesAt }
}

export async function saveManualIndexValuation(code: string, payload: {
  pePercentile: number
  asOf: string
  pe?: number | null
  sourceUrl?: string | null
}) {
  const workspace = cachedWorkspace()
  const retrievedAt = new Date().toISOString()
  workspace.indices = workspace.indices.map((item) => item.code === code ? {
    ...item,
    pe: payload.pe ?? item.pe,
    pePercentile: payload.pePercentile,
    asOf: payload.asOf,
    sourceUrl: payload.sourceUrl ?? null,
    evidence: {
      provider: 'manual_entry',
      sourceUrl: payload.sourceUrl ?? null,
      asOf: payload.asOf,
      retrievedAt,
      freshness: 'manual',
      fallbackUsed: false,
      status: 'manual',
      message: '由当前浏览器的用户手动录入；请自行核验来源与口径。',
    },
  } : item)
  localStorage.setItem(CACHE_KEY, JSON.stringify(workspace))
  return { saved: true }
}

export async function recordIndexPurchase(payload: {
  purchaseDate: string
  indexCode: string
  fundCode: string
  fundName: string
  venue: '场内' | '场外'
  shares: number
  amount: number | null
}) {
  const workspace = cachedWorkspace()
  const purchase: IndexPurchase = {
    id: Date.now(),
    ...payload,
    createdAt: new Date().toISOString(),
  }
  workspace.purchases = [purchase, ...workspace.purchases]
  localStorage.setItem(CACHE_KEY, JSON.stringify(workspace))
  return purchase
}

export function groupFundRecommendations(products: FundProduct[], indexCode: string) {
  const ranked = rankFunds(products, indexCode)
  return {
    exchange: ranked.find((item) => item.venue === '场内') ?? null,
    offExchange: ranked.find((item) => item.venue === '场外') ?? null,
  }
}
