PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS monthly_records (
  user_id TEXT NOT NULL,
  month TEXT NOT NULL,
  city TEXT NOT NULL,
  employment_stage TEXT NOT NULL,
  salary REAL NOT NULL DEFAULT 0,
  housing_fund REAL NOT NULL DEFAULT 0,
  allowance REAL NOT NULL DEFAULT 0,
  other_income REAL NOT NULL DEFAULT 0,
  housing REAL NOT NULL DEFAULT 0,
  food REAL NOT NULL DEFAULT 0,
  transport REAL NOT NULL DEFAULT 0,
  learning REAL NOT NULL DEFAULT 0,
  other_expense REAL NOT NULL DEFAULT 0,
  confirmed INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, month)
);

CREATE TABLE IF NOT EXISTS asset_positions (
  user_id TEXT NOT NULL,
  id TEXT NOT NULL,
  strategy TEXT NOT NULL,
  label TEXT NOT NULL,
  value REAL NOT NULL DEFAULT 0,
  cost REAL,
  note TEXT NOT NULL DEFAULT '',
  tone TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, id)
);

CREATE TABLE IF NOT EXISTS deposit_rates (
  bank TEXT PRIMARY KEY,
  short TEXT NOT NULL,
  three_month REAL NOT NULL,
  six_month REAL NOT NULL,
  one_year REAL NOT NULL,
  two_year REAL NOT NULL,
  three_year REAL NOT NULL,
  five_year REAL NOT NULL,
  effective_at TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  source_url TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS index_catalog (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  market TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS index_valuations (
  code TEXT PRIMARY KEY REFERENCES index_catalog(code),
  pe REAL,
  pe_percentile REAL,
  pb REAL,
  pb_percentile REAL,
  as_of TEXT,
  source_url TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fund_products (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  index_code TEXT NOT NULL,
  venue TEXT NOT NULL,
  scale_billion REAL,
  tracking_error REAL,
  total_fee REAL,
  as_of TEXT,
  source_url TEXT
);

CREATE TABLE IF NOT EXISTS index_purchases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  purchase_date TEXT NOT NULL,
  index_code TEXT NOT NULL,
  fund_code TEXT NOT NULL,
  fund_name TEXT NOT NULL,
  venue TEXT NOT NULL,
  shares REAL NOT NULL,
  amount REAL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bond_fund_quotes (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  issuer TEXT NOT NULL,
  daily_change REAL,
  one_year_return REAL,
  max_drawdown REAL,
  nav REAL,
  as_of TEXT NOT NULL,
  source_url TEXT
);

CREATE TABLE IF NOT EXISTS dca_plans (
  user_id TEXT NOT NULL,
  index_code TEXT NOT NULL,
  base_amount REAL NOT NULL,
  last_buy_price REAL,
  enabled INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, index_code)
);

CREATE TABLE IF NOT EXISTS sell_reminders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  index_code TEXT NOT NULL,
  trigger_type TEXT NOT NULL,
  trigger_value REAL NOT NULL,
  allocation_share REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_runs (
  dataset TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  as_of TEXT,
  message TEXT
);

CREATE TABLE IF NOT EXISTS market_evidence (
  dataset TEXT NOT NULL,
  item_key TEXT NOT NULL,
  provider TEXT,
  source_url TEXT,
  as_of TEXT,
  retrieved_at TEXT NOT NULL,
  freshness TEXT NOT NULL,
  fallback_used INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  message TEXT NOT NULL DEFAULT '',
  content_hash TEXT,
  PRIMARY KEY (dataset, item_key)
);
