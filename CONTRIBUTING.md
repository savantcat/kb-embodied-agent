# 参与贡献（Contributing）

感谢关注本作品。本项目按开源项目常规协作流程维护，欢迎通过 Issue 与 Pull Request 参与。

## 提 Issue

请按模板提交（`.github/ISSUE_TEMPLATE/`）：

- **Bug 报告**：说明复现步骤、期望行为、实际行为，并附环境信息（操作系统、Docker 版本、浏览器版本）。
- **功能建议**：说明使用场景与要解决的问题，而不是只给结论。

> 涉及密钥、企业内部数据、客户信息的内容**不要**贴在 Issue 里；请脱敏后描述。

## 提 Pull Request

1. Fork 仓库并从 `main` 拉分支，分支名建议 `fix/xxx` 或 `feat/xxx`；
2. 保持改动聚焦（一个 PR 解决一件事），并在描述里说明**动机、改动范围、验证方式**；
3. 本地自检（提交前必跑）：

```bash
# 1) 语法与导入检查
cd backend && python -c "import app.main; print('import ok')"

# 2) 密钥扫描（CI 同款）
grep -rInE "sk-[A-Za-z0-9]{16,}" --exclude-dir=.git . && echo "发现疑似密钥" || echo "secret scan ok"

# 3) 一键部署验证（改动了后端或部署文件时必做）
docker compose up -d --build && curl -s http://127.0.0.1:8080/api/health
```

4. 提交信息使用 `feat:` / `fix:` / `docs:` / `chore:` 前缀，说明"做了什么、为什么"。

## 代码与数据边界（重要）

- **不得提交任何密钥**：`.env` 已被 `.gitignore` 忽略，只提交 `.env.example`；CI 会扫描并拒绝疑似密钥。
- **不得提交真实企业数据**：`kb/` 内只放可公开的自有语料；真实客户语料放在被忽略的 `kb/private/`。
- **新增语料**请遵循 `kb/*.md` 的问答格式（`### Q:` / `关键词:` / `A:` / `来源:`），便于数据驱动加载与整体替换。

## 行为准则

就事论事、尊重不同意见；不提交来源不明或版权不明的素材。
