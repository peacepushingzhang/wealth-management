# WealthPilot

一个本地优先的个人财富管理与投资决策支持产品，包含三条清晰主线：

- 个人财富：按月记录收入、支出、存款与资产分布。
- 宽基指数：查询估值、筛选基金、记录购买，并执行正三角定投与 3331 人工复核。
- 债券基金：比较银行定存、债基行情与本月可投入金额。

## 在线体验

GitHub Pages：<https://peacepushingzhang.github.io/wealth-management/>

公开站不会内置任何人的个人财务数据。收入、支出、资产和购买记录只保存在当前浏览器的 `localStorage`；清除浏览器数据会删除这些记录。

## 数据更新

`.github/workflows/refresh-market-data.yml` 每天北京时间 07:30 使用免费公开数据源更新 `public/market-snapshot.json`：

- 银行定存：主要银行官网挂牌利率与页面可用性核验。
- A 股宽基估值：AKShare 聚合的乐咕历史估值，并以中证指数官网数据交叉校验。
- 基金候选与债基净值：东方财富公开基金目录与净值数据。

免费源未覆盖、数据过期或交叉校验失败时，产品不生成金额结论，并保留手动录入入口。美股指数历史 PE 百分位目前没有稳定免费的自动数据源。

## 本地运行

```bash
pnpm install
pnpm dev
```

构建与检查：

```bash
pnpm typecheck
pnpm build
python3 -m unittest discover -s backend/tests
```

## 隐私与边界

- 不连接券商，不自动交易，不代替持牌投资顾问。
- 前端不会上传逐笔账单或个人资产数据。
- 仓库、Pages 构建产物与市场快照均不包含本地 SQLite、环境变量或密钥。
- 市场数据仅用于研究与决策支持；购买前应回到银行、基金公司或指数公司官网复核。

## 技术栈

React 19、TypeScript、Vite、Framer Motion、Python、SQLite、GitHub Actions、GitHub Pages。
