import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useEffect, useState, type ReactNode } from 'react'
import {
  askIndexAssistant,
  groupFundRecommendations,
  loadWorkspace,
  recordIndexPurchase,
  saveManualIndexValuation,
  saveWorkspace,
  syncIndexData,
} from './api'
import {
  calculateAssetAllocation,
  calculateIndexAction,
  calculateMonthlySummary,
  formatMoney,
  formatPercent,
  type AssetPosition,
  type MonthlyRecord,
  type WealthWorkspace,
} from './domain'
import { initialWorkspace } from './productData'
import './styles.css'

type PrimaryTab = 'wealth' | 'index' | 'bond'
type Editor = 'month' | 'assets' | null

const tabs: Array<{ id: PrimaryTab; label: string }> = [
  { id: 'wealth', label: '个人财富' },
  { id: 'index', label: '宽基指数' },
  { id: 'bond', label: '债券基金' },
]

const indexSteps = [
  ['指数池', '列出 A 股与美股主要宽基'],
  ['查询 PE', '获取当前 PE 历史百分位'],
  ['筛选基金', '规模、跟踪误差与总费率'],
  ['购买后确认', '记录实际成交结果'],
  ['确定金额', '使用消费后结余的 70%'],
  ['安排闲钱', '剩余资金进入债券研究'],
  ['正三角定投', '下跌时增加当期份额'],
  ['3331 提醒', '高估时分批止盈复核'],
] as const

const providerNames: Record<string, string> = {
  ifind: '同花顺 iFinD',
  akshare: 'AKShare · 东方财富',
  bank_official: '银行官网',
}

function evidenceText(evidence: { provider: string | null; freshness: string; fallbackUsed: boolean; asOf: string | null } | null | undefined) {
  if (!evidence) return '数据源待配置'
  const source = evidence.provider ? (providerNames[evidence.provider] ?? evidence.provider) : '数据源待配置'
  const state = evidence.freshness === 'fresh' ? '已更新' : evidence.freshness === 'stale' ? '已过期' : '不可用于决策'
  return `${source}${evidence.fallbackUsed ? '（降级）' : ''} · ${state}${evidence.asOf ? ` · ${evidence.asOf}` : ''}`
}

function AnimatedMoney({ value }: { value: number }) {
  const reducedMotion = useReducedMotion()
  const [display, setDisplay] = useState(value)

  useEffect(() => {
    if (reducedMotion) {
      setDisplay(value)
      return
    }
    const from = display
    const startedAt = performance.now()
    let frame = 0
    const tick = (now: number) => {
      const progress = Math.min(1, (now - startedAt) / 480)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(from + (value - from) * eased)
      if (progress < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [value, reducedMotion])

  return <>{formatMoney(display)}</>
}

function MonthLabel({ month }: { month: string }) {
  const [year, value] = month.split('-')
  return <>{year} 年 {Number(value)} 月</>
}

function HomeView({ workspace, openEditor, openTab }: {
  workspace: WealthWorkspace
  openEditor: (editor: Editor) => void
  openTab: (tab: PrimaryTab) => void
}) {
  const summary = calculateMonthlySummary(workspace.monthRecord)
  const allocation = calculateAssetAllocation(workspace.assets)
  const netWorth = workspace.assets.reduce((sum, item) => sum + item.value, 0)
  const tasks = [
    { label: '记录收入', value: formatMoney(summary.income), done: summary.income > 0, action: () => openEditor('month') },
    { label: '记录支出', value: formatMoney(summary.expenses), done: summary.expenses > 0, action: () => openEditor('month') },
    { label: '确认本月存款', value: formatMoney(summary.saved), done: workspace.monthRecord.confirmed, action: () => openEditor('month') },
    { label: '更新资金分布', value: formatMoney(netWorth), done: workspace.assets.some((item) => item.value > 0), action: () => openEditor('assets') },
  ]

  return (
    <motion.div className="wp-page wp-home" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}>
      <section className="wp-month-axis">
        <div className="wp-month-axis__intro">
          <p>MONTHLY SAVING</p>
          <span><MonthLabel month={workspace.monthRecord.month} /></span>
          <h1>开源节流，<br />长期复利；</h1>
          <button type="button" onClick={() => openEditor('month')}>记录本月 <span>→</span></button>
        </div>

        <div className="wp-task-axis" aria-label="本月财富任务轴">
          {tasks.map((task, index) => (
            <button type="button" key={task.label} className={task.done ? 'is-done' : index === 2 ? 'is-current' : ''} onClick={task.action}>
              <i>{task.done ? '✓' : index + 1}</i>
              <span>{task.label}<strong>{task.value}</strong></span>
              <em>{index === 2 && !task.done ? '待确认' : '查看'}</em>
            </button>
          ))}
        </div>

        <div className="wp-month-result">
          <span>本月新增存款</span>
          <strong><AnimatedMoney value={summary.saved} /></strong>
          <p>收入 {formatMoney(summary.income)} − 支出 {formatMoney(summary.expenses)}</p>
        </div>
      </section>

      <section className="wp-asset-map">
        <div className="wp-asset-total">
          <p>CURRENT ASSETS</p>
          <span>目前资金分布</span>
          <strong><AnimatedMoney value={netWorth} /></strong>
          <div className="wp-asset-bar" aria-label="资金策略占比">
            {allocation.map((item) => <i key={item.id} title={`${item.label} ${formatPercent(item.share)}`} style={{ width: `${item.share * 100}%`, background: item.tone }} />)}
          </div>
          <button type="button" onClick={() => openEditor('assets')}>更新余额</button>
        </div>

        <div className="wp-asset-list">
          {allocation.map((item) => {
            const linkedTab = item.strategy === 'index' ? 'index' : item.strategy === 'bond' || item.strategy === 'deposit' ? 'bond' : null
            return (
              <button type="button" key={item.id} className={linkedTab ? 'is-linked' : ''} onClick={() => linkedTab && openTab(linkedTab)} disabled={!linkedTab}>
                <i style={{ background: item.tone }} />
                <span><b>{item.label}</b><small>{item.note}</small></span>
                <strong>{formatMoney(item.value)}<small>{formatPercent(item.share)}</small></strong>
                {linkedTab && <em>→</em>}
              </button>
            )
          })}
        </div>
      </section>
    </motion.div>
  )
}

function EmptySync({ children }: { children: ReactNode }) {
  return <div className="wp-empty-sync"><i /> <span>{children}</span></div>
}

function IndexUniverse({ workspace, selectIndex, selectedCode, syncMarket, syncing, refreshWorkspace }: {
  workspace: WealthWorkspace
  selectIndex: (code: string) => void
  selectedCode: string
  syncMarket: () => Promise<void>
  syncing: boolean
  refreshWorkspace: () => Promise<void>
}) {
  const [manualCode, setManualCode] = useState<string | null>(null)
  const [manualPercentile, setManualPercentile] = useState('')
  const [manualDate, setManualDate] = useState(new Date().toISOString().slice(0, 10))
  const [manualSource, setManualSource] = useState('')
  const [manualState, setManualState] = useState('')

  const submitManual = async () => {
    if (!manualCode || manualPercentile === '') return
    setManualState('保存中')
    try {
      await saveManualIndexValuation(manualCode, {
        pePercentile: Number(manualPercentile),
        asOf: manualDate,
        sourceUrl: manualSource || null,
      })
      await refreshWorkspace()
      setManualState('已保存')
      setManualCode(null)
      setManualPercentile('')
    } catch {
      setManualState('保存失败，请检查浏览器存储权限')
    }
  }

  return (
    <div className="wp-index-universe-wrap">
      <div className="wp-sync-toolbar">
        <div><i /><span><b>每日自动同步</b><small>乐咕历史估值 + 中证官网校验 · 最近 {workspace.syncStatus.indicesAt ?? '尚未完成'}</small></span></div>
        <button type="button" onClick={syncMarket} disabled={syncing}>{syncing ? '同步中…' : '立即同步'}</button>
      </div>
      <div className="wp-index-universe">
        {(['A股', '美股'] as const).map((market) => (
          <section key={market}>
            <header><span>{market}</span><strong>{market === 'A股' ? '境内主要宽基' : '美国主要宽基'}</strong></header>
            {workspace.indices.filter((item) => item.market === market).map((item) => (
              <div className={`wp-index-row ${item.code === selectedCode ? 'is-selected' : ''}`} key={item.code}>
                <button type="button" className="wp-index-row__main" onClick={() => selectIndex(item.code)}>
                  <span><b>{item.name}</b><small>{item.code}</small></span>
                  <strong>{item.pePercentile === null ? '未覆盖' : `${item.pePercentile.toFixed(1)}%`}<small>{item.evidence?.provider === 'manual_entry' ? '手动录入' : 'PE 百分位'}</small></strong>
                </button>
                {item.pePercentile === null && <button className="wp-index-row__manual" type="button" onClick={() => { setManualCode(item.code); setManualState('') }}>手动录入</button>}
              </div>
            ))}
          </section>
        ))}
      </div>
      <p className="wp-coverage-note"><b>自动覆盖：</b>沪深300、中证500、中证1000。A500、创业板指、科创50和美股指数暂时缺少稳定的免费历史估值接口，可使用官方月报或可信估值工具手动录入百分位。</p>
      <AnimatePresence>
        {manualCode && <motion.div className="wp-manual-sync" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}>
          <div><span>手动补充</span><strong>{workspace.indices.find((item) => item.code === manualCode)?.name}</strong><small>系统会明确标记为“手动录入”，不会伪装成自动数据。</small></div>
          <label><span>PE 历史百分位</span><input type="number" min="0" max="100" value={manualPercentile} onChange={(event) => setManualPercentile(event.target.value)} placeholder="0–100" /></label>
          <label><span>数据日期</span><input type="date" value={manualDate} onChange={(event) => setManualDate(event.target.value)} /></label>
          <label className="is-wide"><span>来源链接（建议填写）</span><input type="url" value={manualSource} onChange={(event) => setManualSource(event.target.value)} placeholder="指数公司或可信估值页面" /></label>
          <div className="wp-manual-sync__actions"><button type="button" onClick={() => setManualCode(null)}>取消</button><button type="button" onClick={submitManual} disabled={!manualPercentile || !manualDate}>保存估值</button><small>{manualState}</small></div>
        </motion.div>}
      </AnimatePresence>
    </div>
  )
}

function PurchaseRecorder({ workspace, selectedCode, products, refreshWorkspace }: {
  workspace: WealthWorkspace
  selectedCode: string
  products: WealthWorkspace['fundProducts']
  refreshWorkspace: () => Promise<void>
}) {
  const first = products[0]
  const [purchaseDate, setPurchaseDate] = useState(new Date().toISOString().slice(0, 10))
  const [venue, setVenue] = useState<'场内' | '场外'>(first?.venue ?? '场内')
  const [fundCode, setFundCode] = useState(first?.code ?? '')
  const [fundName, setFundName] = useState(first?.name ?? '')
  const [shares, setShares] = useState('')
  const [amount, setAmount] = useState('')
  const [state, setState] = useState('')
  const recent = workspace.purchases.filter((item) => item.indexCode === selectedCode).slice(0, 3)

  const chooseFund = (code: string) => {
    const fund = products.find((item) => item.code === code)
    if (!fund) return
    setFundCode(fund.code)
    setFundName(fund.name)
    setVenue(fund.venue)
  }

  const submit = async () => {
    if (!purchaseDate || !fundCode.trim() || !fundName.trim() || Number(shares) <= 0) return
    setState('保存中')
    try {
      await recordIndexPurchase({
        purchaseDate,
        indexCode: selectedCode,
        fundCode: fundCode.trim(),
        fundName: fundName.trim(),
        venue,
        shares: Number(shares),
        amount: amount ? Number(amount) : null,
      })
      await refreshWorkspace()
      setShares('')
      setAmount('')
      setState('已记录，不会自动下单')
    } catch {
      setState('保存失败，请检查浏览器存储权限')
    }
  }

  return <section className="wp-purchase-recorder">
    <header><div><strong>购买后确认</strong></div><p>先在证券或基金软件完成交易，再把成交结果写回 WealthPilot。</p></header>
    {products.length > 0 && <label className="is-wide"><span>使用候选基金</span><select value={fundCode} onChange={(event) => chooseFund(event.target.value)}><option value="">手动填写</option>{products.map((item) => <option value={item.code} key={item.code}>{item.venue} · {item.name} · {item.code}</option>)}</select></label>}
    <label><span>购买日期</span><input type="date" value={purchaseDate} onChange={(event) => setPurchaseDate(event.target.value)} /></label>
    <label><span>渠道</span><select value={venue} onChange={(event) => setVenue(event.target.value as '场内' | '场外')}><option>场内</option><option>场外</option></select></label>
    <label><span>基金代码</span><input value={fundCode} onChange={(event) => setFundCode(event.target.value)} placeholder="例如 510300" /></label>
    <label><span>基金名称</span><input value={fundName} onChange={(event) => setFundName(event.target.value)} placeholder="例如 沪深300ETF" /></label>
    <label><span>确认份额</span><input type="number" min="0" step="0.01" value={shares} onChange={(event) => setShares(event.target.value)} placeholder="实际成交份额" /></label>
    <label><span>成交金额（可选）</span><input type="number" min="0" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="¥" /></label>
    <div className="wp-purchase-recorder__submit"><button type="button" onClick={submit} disabled={!fundCode || !fundName || Number(shares) <= 0}>确认记录</button><span>{state}</span></div>
    {recent.length > 0 && <div className="wp-purchase-history"><span>最近记录</span>{recent.map((item) => <p key={item.id}><b>{item.purchaseDate}</b>{item.fundName} · {item.fundCode}<strong>{item.shares} 份</strong></p>)}</div>}
  </section>
}

function IndexStepContent({ step, workspace, selectedCode, selectIndex, openBond, syncMarket, syncing, refreshWorkspace }: {
  step: number
  workspace: WealthWorkspace
  selectedCode: string
  selectIndex: (code: string) => void
  openBond: () => void
  syncMarket: () => Promise<void>
  syncing: boolean
  refreshWorkspace: () => Promise<void>
}) {
  const selected = workspace.indices.find((item) => item.code === selectedCode) ?? workspace.indices[0]
  const summary = calculateMonthlySummary(workspace.monthRecord)
  const oneShare = Math.round(summary.indexBudget / 2)
  const funds = groupFundRecommendations(workspace.fundProducts, selected.code)

  if (step === 0) return <IndexUniverse workspace={workspace} selectIndex={selectIndex} selectedCode={selectedCode} syncMarket={syncMarket} syncing={syncing} refreshWorkspace={refreshWorkspace} />

  if (step === 1) {
    return (
      <section className="wp-valuation-view">
        <div className="wp-valuation-focus"><span>{selected.name}</span><strong>{selected.pePercentile === null ? '—' : `${selected.pePercentile.toFixed(1)}%`}</strong><p>PE 历史百分位</p><em>{calculateIndexAction(selected.pePercentile)}</em><small>{evidenceText(selected.evidence)}</small></div>
        <div className="wp-valuation-list">
          {workspace.indices.map((item) => <button type="button" key={item.code} onClick={() => selectIndex(item.code)}><span>{item.name}</span><strong>{item.pePercentile === null ? '尚未同步' : `${item.pePercentile.toFixed(1)}%`}</strong><em>{calculateIndexAction(item.pePercentile)}</em></button>)}
        </div>
      </section>
    )
  }

  if (step === 2) {
    return (
      <section className="wp-fund-filter">
        <div className="wp-selected-index"><span>当前指数</span><strong>{selected.name}</strong><small>{selected.code}</small></div>
        {!funds.exchange && !funds.offExchange ? <div className="wp-fund-sync-callout"><span>该指数尚未发现匹配产品</span><p>可重新同步东方财富公开基金目录；没有真实代码时不生成占位推荐。</p><button type="button" onClick={syncMarket} disabled={syncing}>{syncing ? '同步中…' : '同步基金候选'}</button></div> : (
          <div className="wp-fund-results">
            {[funds.exchange, funds.offExchange].filter(Boolean).map((fund) => fund && <a href={fund.sourceUrl ?? '#'} target="_blank" rel="noreferrer" key={fund.code}><span>{fund.venue} · 真实候选</span><strong>{fund.name}</strong><b>{fund.code}</b><p>规模 {fund.scaleBillion === null ? '待核验' : `${fund.scaleBillion} 亿`} · 跟踪误差 {fund.trackingError === null ? '待核验' : `${fund.trackingError}%`} · 年度费率 {fund.totalFee === null ? '待核验' : `${fund.totalFee}%`}</p><small>{fund.evidence?.message ?? '来自东方财富公开目录，购买前回到基金公司公告核验。'}</small></a>)}
          </div>
        )}
        <blockquote>提问示例：我要买{selected.name}，请结合基金规模、跟踪准确度和最低费率，推荐对应的场内和场外基金。</blockquote>
      </section>
    )
  }

  if (step === 3) {
    return <PurchaseRecorder workspace={workspace} selectedCode={selected.code} products={workspace.fundProducts.filter((item) => item.indexCode === selected.code)} refreshWorkspace={refreshWorkspace} />
  }

  if (step === 4) {
    return <section className="wp-amount-decision"><span>本月指数预算</span><strong><AnimatedMoney value={summary.indexBudget} /></strong><p>本月存款 {formatMoney(summary.saved)} × 70%</p><div><span>消费后结余</span><b>{formatMoney(summary.saved)}</b><span>留给低波动资产</span><b>{formatMoney(summary.bondBudget)}</b></div></section>
  }

  if (step === 5) {
    return <section className="wp-idle-cash"><span>本月闲钱</span><strong>{formatMoney(summary.bondBudget)}</strong><p>这部分不承担权益波动，进入定存与债券基金比较。</p><button type="button" onClick={openBond}>查看债券基金 <span>→</span></button></section>
  }

  if (step === 6) {
    return <section className="wp-triangle"><header><span>{selected.name}</span><strong>一份 {formatMoney(oneShare)} · 36个月 / 72份</strong></header><div className="wp-strategy-reason"><b>正三角定投</b><p><span>把计划资金拆成固定份数：PE 低于40%买1份，低于20%买2份，回到40%以上停买。</span><span>估值越低投入越多，目的是用低价份额拉低平均成本；总投入仍受72份计划和月度预算限制。</span></p></div>{[['PE 20%–40%', '1.0 份', formatMoney(oneShare)], ['较上次买入下跌 10%', '1.25 份', formatMoney(oneShare * 1.25)], ['较上次买入下跌 20%', '1.5 份', formatMoney(oneShare * 1.5)], ['下跌 30% 或 PE<20%', '2.0 份', formatMoney(oneShare * 2)]].map(([condition, units, amount]) => <div className="wp-triangle-row" key={condition}><span>{condition}</span><strong>{units}</strong><em>{amount}</em></div>)}</section>
  }

  return <section className="wp-sell-plan"><header><span>3331</span><strong>只提醒，不自动卖出</strong></header><div className="wp-strategy-reason"><b>3331 分批止盈</b><p><span>PE 百分位到80%、90%和接近历史高点时，各人工复核并卖出30%，最后10%保留观察。</span><span>它不预测最高点，而是把高估区的账面收益分段落袋，同时保留少量仓位参与后续上涨。</span></p></div><div className="wp-sell-step"><i>30%</i><span>PE 百分位达到 80%</span></div><div className="wp-sell-step"><i>30%</i><span>PE 百分位达到 90%</span></div><div className="wp-sell-step"><i>30%</i><span>接近历史高点</span></div><div className="wp-sell-step"><i>10%</i><span>保留并人工复核</span></div></section>
}

function IndexView({ workspace, openBond, refreshWorkspace }: { workspace: WealthWorkspace; openBond: () => void; refreshWorkspace: () => Promise<void> }) {
  const [step, setStep] = useState(0)
  const [selectedCode, setSelectedCode] = useState(workspace.indices[0]?.code ?? '')
  const [question, setQuestion] = useState('沪深300的 PE 百分位是多少？')
  const [answer, setAnswer] = useState('选择一个指数，或直接向我提问。')
  const [asking, setAsking] = useState(false)
  const [syncing, setSyncing] = useState(false)

  const ask = async () => {
    if (!question.trim()) return
    setAsking(true)
    setAnswer(await askIndexAssistant(question, workspace))
    setAsking(false)
  }

  const syncMarket = async () => {
    setSyncing(true)
    try {
      await syncIndexData()
      await refreshWorkspace()
      setAnswer('指数估值与基金候选已刷新；未覆盖项目仍保留手动录入入口。')
    } catch {
      setAnswer('公开市场快照暂时无法获取，请稍后重试。')
    } finally {
      setSyncing(false)
    }
  }

  return (
    <motion.div className="wp-page wp-index-page" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}>
      <section className="wp-index-head">
        <div><p>INDEX WORKFLOW</p><h1>长期持有，按规则止盈；</h1></div>
        <div className="wp-question-api">
          <span>向 WealthPilot 提问</span>
          <div><input aria-label="指数问题" value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && ask()} /><button type="button" onClick={ask} disabled={asking}>{asking ? '查询中' : '提问'}</button></div>
          <p>{answer}</p>
        </div>
      </section>

      <section className="wp-index-flow">
        <nav aria-label="宽基指数定投工作流">
          {indexSteps.map(([title, detail], index) => <button type="button" key={title} className={index === step ? 'is-active' : index < step ? 'is-done' : ''} onClick={() => setStep(index)}><i>{index + 1}</i><span><b>{title}</b><small>{detail}</small></span></button>)}
        </nav>
        <div className="wp-flow-stage">
          <header><span>第 {step + 1} 步</span><h2>{indexSteps[step][0]}</h2><p>{indexSteps[step][1]}</p></header>
          <IndexStepContent step={step} workspace={workspace} selectedCode={selectedCode} selectIndex={setSelectedCode} openBond={openBond} syncMarket={syncMarket} syncing={syncing} refreshWorkspace={refreshWorkspace} />
          <footer><button type="button" disabled={step === 0} onClick={() => setStep((value) => Math.max(0, value - 1))}>上一步</button><span>{step + 1} / 8</span><button type="button" disabled={step === 7} onClick={() => setStep((value) => Math.min(7, value + 1))}>下一步</button></footer>
        </div>
      </section>
    </motion.div>
  )
}

function BondView({ workspace }: { workspace: WealthWorkspace }) {
  const summary = calculateMonthlySummary(workspace.monthRecord)
  const oneYearHigh = Math.max(...workspace.depositRates.map((item) => item.oneYear))

  return (
    <motion.div className="wp-page wp-bond-page" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}>
      <header className="wp-bond-head"><div><p>DAILY FIXED INCOME</p><h1>先看银行利率，再看债券基金。</h1></div><span>每日 07:30 更新</span></header>

      <section className="wp-bond-section wp-deposits">
        <header><div><span>01</span><h2>主要银行定期存款</h2></div><p>一年期最高挂牌利率 <strong>{oneYearHigh.toFixed(2)}%</strong></p></header>
        <div className="wp-wide-table wp-deposit-grid">
          <div className="is-head"><span>银行</span><span>3月</span><span>6月</span><span>1年</span><span>2年</span><span>3年</span><span>5年</span></div>
          {workspace.depositRates.map((rate) => <a href={rate.sourceUrl} target="_blank" rel="noreferrer" title={rate.evidence?.message} key={rate.short}><span><b>{rate.bank}</b><small>{rate.short} · {rate.evidence?.status === 'review_required' ? '待复核' : '官网'}</small></span><span>{rate.threeMonth.toFixed(2)}</span><span>{rate.sixMonth.toFixed(2)}</span><span>{rate.oneYear.toFixed(2)}</span><span>{rate.twoYear.toFixed(2)}</span><span>{rate.threeYear.toFixed(2)}</span><span>{rate.fiveYear.toFixed(2)}</span></a>)}
        </div>
        <footer>挂牌利率数据日期 2025-05-20 · 最近核对 {workspace.syncStatus.depositsAt ?? '尚未同步'} · 实际办理利率以银行为准</footer>
      </section>

      <section className="wp-bond-section wp-bond-quotes">
        <header><div><span>02</span><h2>债券基金行情与代码</h2></div><p>债基没有固定利率，展示净值涨跌与历史收益。</p></header>
        {workspace.bondFunds.length ? <div className="wp-wide-table wp-bond-grid"><div className="is-head"><span>基金 / 代码</span><span>发行机构</span><span>单位净值</span><span>日涨跌</span><span>近1年</span><span>最大回撤</span></div>{workspace.bondFunds.map((fund) => <a href={fund.sourceUrl ?? '#'} title={fund.evidence?.message} key={fund.code}><span><b>{fund.name}</b><small>{fund.code} · {evidenceText(fund.evidence)}</small></span><span>{fund.issuer}</span><span>{fund.nav ?? '—'}</span><span>{fund.dailyChange === null ? '—' : `${fund.dailyChange.toFixed(2)}%`}</span><span>{fund.oneYearReturn === null ? '—' : `${fund.oneYearReturn.toFixed(2)}%`}</span><span>{fund.maxDrawdown === null ? '—' : `${fund.maxDrawdown.toFixed(2)}%`}</span></a>)}</div> : <EmptySync>债基数据供应商尚未配置。同步完成后，这里按基金代码展示日涨跌、近一年收益与最大回撤。</EmptySync>}
      </section>

      <section className="wp-bond-section wp-bond-amount">
        <header><div><span>03</span><h2>本月可以买多少钱</h2></div></header>
        <div><span>建议上限</span><strong><AnimatedMoney value={summary.bondBudget} /></strong><p>本月存款 {formatMoney(summary.saved)} − 指数预算 {formatMoney(summary.indexBudget)}</p></div>
      </section>
    </motion.div>
  )
}

function MoneyField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return <label className="wp-money-field"><span>{label}</span><div><i>¥</i><input type="number" min="0" value={value} onChange={(event) => onChange(Math.max(0, Number(event.target.value) || 0))} /></div></label>
}

function EditorPanel({ editor, workspace, close, save }: {
  editor: Exclude<Editor, null>
  workspace: WealthWorkspace
  close: () => void
  save: (workspace: WealthWorkspace) => void
}) {
  const [month, setMonth] = useState<MonthlyRecord>(workspace.monthRecord)
  const [assets, setAssets] = useState<AssetPosition[]>(workspace.assets)
  const summary = calculateMonthlySummary(month)
  const updateMonth = <K extends keyof MonthlyRecord>(key: K, value: MonthlyRecord[K]) => setMonth((current) => ({ ...current, [key]: value }))
  const updateAsset = (id: string, value: number) => setAssets((current) => current.map((item) => item.id === id ? { ...item, value } : item))

  const commit = () => {
    save({ ...workspace, monthRecord: editor === 'month' ? { ...month, confirmed: true } : workspace.monthRecord, assets: editor === 'assets' ? assets : workspace.assets })
    close()
  }

  return (
    <motion.aside className="wp-editor" role="dialog" aria-modal="true" aria-labelledby="wp-editor-title" initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }} transition={{ duration: .35, ease: [0.22, 1, 0.36, 1] }}>
      <header><div><span><MonthLabel month={workspace.monthRecord.month} /></span><h2 id="wp-editor-title">{editor === 'month' ? '记录本月收支与存款' : '更新目前资金分布'}</h2></div><button type="button" aria-label="关闭" onClick={close}>×</button></header>
      {editor === 'month' ? <div className="wp-editor-body">
        <section><h3>城市</h3><label className="wp-text-field"><span>当前城市</span><input value={month.city} onChange={(event) => updateMonth('city', event.target.value)} placeholder="例如 北京" /></label></section>
        <section><h3>收入</h3><MoneyField label="工资" value={month.salary} onChange={(value) => updateMonth('salary', value)} /><MoneyField label="现金补贴" value={month.allowance} onChange={(value) => updateMonth('allowance', value)} /><MoneyField label="其他收入" value={month.otherIncome} onChange={(value) => updateMonth('otherIncome', value)} /><MoneyField label="公积金（非现金）" value={month.housingFund} onChange={(value) => updateMonth('housingFund', value)} /></section>
        <section><h3>支出</h3><MoneyField label="住房" value={month.housing} onChange={(value) => updateMonth('housing', value)} /><MoneyField label="餐饮" value={month.food} onChange={(value) => updateMonth('food', value)} /><MoneyField label="交通" value={month.transport} onChange={(value) => updateMonth('transport', value)} /><MoneyField label="学习" value={month.learning} onChange={(value) => updateMonth('learning', value)} /><MoneyField label="其他" value={month.otherExpense} onChange={(value) => updateMonth('otherExpense', value)} /></section>
        <div className="wp-editor-result"><span>本月新增存款</span><strong>{formatMoney(summary.saved)}</strong><p>公积金计入总财富，但不计入本月现金存款。</p></div>
      </div> : <div className="wp-editor-body"><section className="wp-assets-form"><h3>各策略当前余额</h3>{assets.map((asset) => <MoneyField key={asset.id} label={asset.label} value={asset.value} onChange={(value) => updateAsset(asset.id, value)} />)}</section></div>}
      <footer><button type="button" onClick={commit}>保存本月记录 <span>→</span></button></footer>
    </motion.aside>
  )
}

export default function WealthPilotApp() {
  const [tab, setTab] = useState<PrimaryTab>('wealth')
  const [workspace, setWorkspace] = useState<WealthWorkspace>(initialWorkspace)
  const [editor, setEditor] = useState<Editor>(null)

  const refreshWorkspace = async () => {
    setWorkspace(await loadWorkspace())
  }

  useEffect(() => {
    document.title = 'WealthPilot · 个人财富工作台'
    void refreshWorkspace()
  }, [])

  useEffect(() => {
    document.body.style.overflow = editor ? 'hidden' : ''
    return () => { document.body.style.overflow = '' }
  }, [editor])

  const persist = (next: WealthWorkspace) => {
    setWorkspace(next)
    void saveWorkspace(next)
  }

  return (
    <div className={`wealth-app is-${tab}`}>
      <div className="wp-night" aria-hidden="true" />
      <header className="wp-topbar">
        <div className="wp-brand-context"><a className="wp-wordmark" href="./"><b>WEALTHPILOT</b><span>个人财富工作台</span></a><button type="button" className="wp-city-beacon" onClick={() => setEditor('month')}><i /><span>{workspace.monthRecord.city || '设置城市'}</span><small>城市策略</small></button></div>
        <nav role="tablist" aria-label="财富管理领域">
          {tabs.map((item) => <button type="button" role="tab" aria-selected={tab === item.id} className={tab === item.id ? 'is-active' : ''} key={item.id} onClick={() => setTab(item.id)}>{item.label}</button>)}
        </nav>
        <button className="wp-month-button" type="button" onClick={() => setEditor('month')}><MonthLabel month={workspace.monthRecord.month} /> <span>记录</span></button>
      </header>

      <main>
        <AnimatePresence mode="wait">
          {tab === 'wealth' && <HomeView key="wealth" workspace={workspace} openEditor={setEditor} openTab={setTab} />}
          {tab === 'index' && <IndexView key="index" workspace={workspace} openBond={() => setTab('bond')} refreshWorkspace={refreshWorkspace} />}
          {tab === 'bond' && <BondView key="bond" workspace={workspace} />}
        </AnimatePresence>
      </main>

      <AnimatePresence>
        {editor && <><motion.button className="wp-editor-backdrop" aria-label="关闭编辑" type="button" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setEditor(null)} /><EditorPanel editor={editor} workspace={workspace} close={() => setEditor(null)} save={persist} /></>}
      </AnimatePresence>
    </div>
  )
}
