# Notion 基金数据管道

这是一个自动化工具，用于同步基金数据到 Notion 数据库，包括基金行情、交易记录和持仓管理。

## 功能特性

- 🔗 **自动关联交易记录与持仓**
- 📊 **实时更新基金行情数据**
- 💰 **自动计算仓位权重**
- 🎯 **智能数据看板关联**
- ⚡ **支持增量更新（仅处理今日数据）**

## 环境变量配置

在 GitHub Secrets 中设置以下环境变量：

```bash
NOTION_TOKEN=your_notion_integration_token
HOLDINGS_DB_ID=your_holdings_database_id
TRADES_DB_ID=your_trades_database_id
DASHBOARD_DB_ID=your_dashboard_database_id  # 可选
```

## 使用方法

### 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 设置环境变量
export NOTION_TOKEN="your_token"
export HOLDINGS_DB_ID="your_db_id"
export TRADES_DB_ID="your_db_id"

# 运行脚本
python notion_fund_pipeline.py all          # 执行所有操作
python notion_fund_pipeline.py link         # 仅处理交易关联
python notion_fund_pipeline.py market       # 仅更新行情
python notion_fund_pipeline.py position     # 仅计算仓位
python notion_fund_pipeline.py all --today-only  # 仅处理今日数据
```

### GitHub Actions

项目已配置 GitHub Actions，支持：

- 每日自动同步基金数据
- 手动触发数据同步
- 自动测试和部署

## 数据库结构要求

### 持仓表 (Holdings)
- 基金名称 (Title)
- Code (Rich text)
- 单位净值 (Number)
- 估算净值 (Number)
- 估算涨跌幅 (Number)
- 估值时间 (Date)
- 来源 (Select)
- 更新于 (Date)
- 持仓成本 (Number/Formula/Rollup)
- 仓位 (Number)
- 数据看板 (Relation)

### 交易表 (Trades)
- Code (Rich text)
- 基金名称 (Title/Rich text)
- Fund 持仓 (Relation → 持仓表)

## 数据来源

- 天天基金网 (fundgz.1234567.com.cn)
- 东方财富网 (api.fund.eastmoney.com)

## 注意事项

- 请确保 Notion 集成有足够的权限访问相关数据库
- 建议在非交易时间运行，避免频繁请求
- 基金代码会自动补零到6位
- 支持增量更新，提高效率

## 许可证

MIT License

