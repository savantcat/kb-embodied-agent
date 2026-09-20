## 这个 PR 做了什么

（一句话说明；关联 Issue 请写 `Closes #123`）

## 动机

（为什么需要这个改动：解决什么问题、什么场景触发）

## 改动范围

- [ ] 后端（`backend/`）
- [ ] 前端（`web/`）
- [ ] 语料（`kb/`）
- [ ] 部署与配置（`docker-compose.yml` / `deploy/` / `.env.example`）
- [ ] 文档（`README.md` / `docs/`）

## 验证方式（必填）

（贴出你实际跑过的命令与结果，不要只写"本地测试通过"）

```bash
# 例：
# cd backend && python -c "import app.main; print('import ok')"
# docker compose up -d --build && curl -s http://127.0.0.1:8080/api/health
# curl -X POST -H "Content-Type: application/json" -d '{}' http://127.0.0.1:8080/api/selfcheck | head -c 200
```

## 自检清单

- [ ] 未提交任何密钥（`.env` 未入库，仅 `.env.example`）
- [ ] 未提交真实企业 / 客户数据（真实语料放 `kb/private/`，已被忽略）
- [ ] 新增语料遵循 `kb/*.md` 的问答格式
- [ ] 改动后端或部署文件时，已用 `docker compose up -d --build` 实跑验证
- [ ] 文档已同步更新（README / docs）
