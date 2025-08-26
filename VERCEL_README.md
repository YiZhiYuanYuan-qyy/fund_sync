# 🚀 Vercel 部署指南

这个项目包含一个 Vercel 函数，可以作为"遥控器"来触发 GitHub Actions 运行 Notion 基金同步管道。

## 📋 部署步骤

### 1. 准备 GitHub Token

首先，你需要在 GitHub 上创建一个 Personal Access Token：

1. 访问 [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens)
2. 点击 "Generate new token (classic)"
3. 选择以下权限：
   - `repo` - 完整的仓库访问权限
   - `workflow` - 管理 GitHub Actions 工作流
4. 复制生成的 token

### 2. 部署到 Vercel

#### 方法一：使用 Vercel CLI

```bash
# 安装 Vercel CLI
npm i -g vercel

# 登录 Vercel
vercel login

# 部署项目
vercel

# 设置环境变量
vercel env add GITHUB_TOKEN
# 输入你的 GitHub token
```

#### 方法二：使用 Vercel Dashboard

1. 访问 [vercel.com](https://vercel.com)
2. 点击 "New Project"
3. 导入你的 GitHub 仓库
4. 在项目设置中添加环境变量：
   - 名称：`GITHUB_TOKEN`
   - 值：你的 GitHub Personal Access Token

### 3. 配置环境变量

在 Vercel 项目设置中添加：

```
GITHUB_TOKEN=你的GitHub_Token
```

## 🔧 使用方法

### 通过 Web 界面

1. 访问你的 Vercel 域名（例如：`https://your-project.vercel.app`）
2. 选择运行模式：
   - `all`: 运行所有步骤
   - `link`: 仅同步链接
   - `market`: 仅更新市场数据
   - `position`: 仅更新持仓
3. 选择是否只处理今日交易
4. 点击"触发同步"按钮

### 通过 API 调用

```bash
curl -X POST https://your-project.vercel.app/api/trigger-pipeline \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "all",
    "today_only": false
  }'
```

## 📁 项目结构

```
├── api/
│   └── trigger-pipeline.js    # Vercel API 函数
├── public/
│   └── index.html             # Web 界面
├── vercel.json                # Vercel 配置
└── VERCEL_README.md           # 本文件
```

## 🔒 安全注意事项

1. **GitHub Token**: 确保你的 GitHub token 有足够的权限，但不要过度授权
2. **访问控制**: 考虑添加额外的认证机制（如 API key）
3. **监控**: 定期检查 Vercel 函数日志和 GitHub Actions 执行记录

## 🐛 故障排除

### 常见问题

1. **401 Unauthorized**: 检查 GitHub token 是否正确设置
2. **404 Not Found**: 确认仓库名称和工作流文件名正确
3. **500 Internal Server Error**: 检查 Vercel 函数日志

### 查看日志

```bash
# 使用 Vercel CLI 查看日志
vercel logs

# 或在 Vercel Dashboard 中查看
```

## 📞 支持

如果遇到问题，请检查：
1. GitHub token 权限
2. 仓库名称和工作流文件名
3. Vercel 环境变量设置
4. 网络连接和防火墙设置
