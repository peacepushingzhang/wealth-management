export type EmploymentStage = 'student' | 'probation' | 'stable'

export type MonthlyRecord = {
  month: string
  city: string
  employmentStage: EmploymentStage
  salary: number
  housingFund: number
  allowance: number
  otherIncome: number
  housing: number
  food: number
  transport: number
  learning: number
  otherExpense: number
  confirmed: boolean
}

export type AssetStrategy =
  | 'liquidity'
  | 'deposit'
  | 'index'
  | 'bond'
  | 'stock'
  | 'housingFund'

export type AssetPosition = {
  id: string
  strategy: AssetStrategy
  label: string
  value: number
  cost?: number
  note: string
  tone: string
}

export type MarketEvidence = {
  provider: string | null
  sourceUrl: string | null
  asOf: string | null
  retrievedAt: string
  freshness: 'fresh' | 'stale' | 'missing' | 'invalid' | string
  fallbackUsed: boolean
  status: string
  message: string
}

export type DepositRate = {
  bank: string
  short: string
  threeMonth: number
  sixMonth: number
  oneYear: number
  twoYear: number
  threeYear: number
  fiveYear: number
  effectiveAt: string
  retrievedAt: string
  sourceUrl: string
  evidence?: MarketEvidence | null
}

export type IndexMarket = 'A股' | '美股'

export type IndexItem = {
  code: string
  name: string
  market: IndexMarket
  pe: number | null
  pePercentile: number | null
  pb: number | null
  pbPercentile: number | null
  asOf: string | null
  sourceUrl: string | null
  evidence?: MarketEvidence | null
}

export type FundProduct = {
  code: string
  name: string
  indexCode: string
  venue: '场内' | '场外'
  scaleBillion: number | null
  trackingError: number | null
  totalFee: number | null
  asOf: string | null
  sourceUrl: string | null
  evidence?: MarketEvidence | null
}

export type IndexPurchase = {
  id: number
  purchaseDate: string
  indexCode: string
  fundCode: string
  fundName: string
  venue: '场内' | '场外'
  shares: number
  amount: number | null
  createdAt: string
}

export type BondFundQuote = {
  code: string
  name: string
  issuer: string
  dailyChange: number | null
  oneYearReturn: number | null
  maxDrawdown: number | null
  nav: number | null
  asOf: string
  sourceUrl: string | null
  evidence?: MarketEvidence | null
}

export type SyncStatus = {
  depositsAt: string | null
  indicesAt: string | null
  fundsAt: string | null
  fundProductsAt: string | null
  nextRunAt: string | null
}

export type WealthWorkspace = {
  monthRecord: MonthlyRecord
  assets: AssetPosition[]
  depositRates: DepositRate[]
  indices: IndexItem[]
  fundProducts: FundProduct[]
  purchases: IndexPurchase[]
  bondFunds: BondFundQuote[]
  syncStatus: SyncStatus
}

export type IndexAction = '双份' | '一份' | '暂停买入' | '3331 复核' | '等待数据'

const safeRatio = (numerator: number, denominator: number) => denominator > 0 ? numerator / denominator : 0
const roundMoney = (value: number) => Math.max(0, Math.round(value))

export function calculateMonthlySummary(record: MonthlyRecord) {
  const income = record.salary + record.allowance + record.otherIncome
  const expenses = record.housing + record.food + record.transport + record.learning + record.otherExpense
  const saved = Math.max(0, income - expenses)
  const indexBudget = roundMoney(saved * 0.7)
  const bondBudget = Math.max(0, saved - indexBudget)

  return {
    income: roundMoney(income),
    totalCompensation: roundMoney(income + record.housingFund),
    expenses: roundMoney(expenses),
    saved: roundMoney(saved),
    savingsRate: safeRatio(saved, income),
    indexBudget,
    bondBudget,
  }
}

export function calculateAssetAllocation(positions: AssetPosition[]) {
  const total = positions.reduce((sum, position) => sum + position.value, 0)
  return positions.map((position) => ({
    ...position,
    share: safeRatio(position.value, total),
    gain: position.cost === undefined ? undefined : position.value - position.cost,
  }))
}

export function calculateIndexAction(pePercentile: number | null): IndexAction {
  if (pePercentile === null) return '等待数据'
  if (pePercentile < 20) return '双份'
  if (pePercentile < 40) return '一份'
  if (pePercentile < 80) return '暂停买入'
  return '3331 复核'
}

export function calculateTriangleUnits(pePercentile: number | null, drawdownFromLastBuy: number) {
  if (pePercentile === null || pePercentile >= 40) return 0
  if (pePercentile < 20 || drawdownFromLastBuy <= -30) return 2
  if (drawdownFromLastBuy <= -20) return 1.5
  if (drawdownFromLastBuy <= -10) return 1.25
  return 1
}

export function rankFunds(products: FundProduct[], indexCode: string) {
  return products
    .filter((product) => product.indexCode === indexCode)
    .sort((a, b) => {
      const completenessGap = [b.scaleBillion, b.trackingError, b.totalFee].filter((value) => value !== null).length
        - [a.scaleBillion, a.trackingError, a.totalFee].filter((value) => value !== null).length
      if (completenessGap) return completenessGap
      const errorGap = (a.trackingError ?? Infinity) - (b.trackingError ?? Infinity)
      if (Math.abs(errorGap) > 0.02) return errorGap
      const feeGap = (a.totalFee ?? Infinity) - (b.totalFee ?? Infinity)
      if (Math.abs(feeGap) > 0.02) return feeGap
      return (b.scaleBillion ?? 0) - (a.scaleBillion ?? 0)
    })
}

export const formatMoney = (value: number) =>
  new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: 'CNY',
    maximumFractionDigits: 0,
  }).format(value)

export const formatPercent = (value: number) =>
  new Intl.NumberFormat('zh-CN', {
    style: 'percent',
    maximumFractionDigits: 1,
  }).format(value)
