# PostgreSQL 备份与恢复

## 备份

`scripts/backup-database.ps1` 在 PostgreSQL 容器内执行 `pg_dump -Fc`，再复制到宿主机。备份目录已加入 `.gitignore`。

```powershell
.\scripts\backup-database.ps1 -Output backups\tingting-$(Get-Date -Format yyyyMMdd).dump
```

备份文件应加密保存到访问受控的介质，并定期校验可恢复性。Docker Volume 不是备份；删除 Volume、磁盘损坏或错误迁移都会影响其中数据。

**范围说明：`scripts/backup-database.ps1` 只备份 PostgreSQL（含工单、知识库元数据与向量），不包含 MinIO 对象存储中的附件与原文文件。附件灾备需另行备份 MinIO bucket / volume。**

## MinIO 备份与恢复顺序

1. **先停写**：暂停 Backend/Worker（或进入只读维护），避免备份窗口内新对象写入。
2. **PostgreSQL**：执行 `backup-database.ps1`（或 `pg_dump -Fc`）。
3. **MinIO buckets**：备份 `tingting-attachments` 与 `tingting-kb`（`mc mirror` / volume snapshot）。
4. **恢复顺序**：先恢复 PostgreSQL 并确认 `alembic current`，再恢复 MinIO buckets；最后启动 Backend 做附件下载与 KB 原文抽检。
5. **校验**：抽检 ticket attachment 下载、KB `storage_key` 对象存在、市民/部门关键路径。

## 恢复

```powershell
$env:VERIFY_TICKET_ID = 'QT...'
.\scripts\restore-database.ps1 -InputFile backups\tingting.dump -Force
```

脚本使用 `pg_restore --clean --if-exists --no-owner --no-privileges`，随后等待 Backend、检查 Alembic 当前版本，并验证工单、用户、部门、处理记录和审计日志的引用完整性。若设置 `VERIFY_TICKET_ID`，还会强制验证该工单、处理记录和关联审计记录。

## 第六轮实测

在独立项目中创建并受理工单 `QT2026071400000001`，执行自定义格式备份，停止 Backend，删除并重建 `public` schema，确认 `tickets` 表不存在后恢复。结果：Alembic `0003 (head)`；工单 1、用户 4、部门 7、处理记录 2、审计日志 4；指定工单关联处理记录 2、审计记录 2。测试 Volume 和临时 dump 已清理。

## 异机恢复注意事项

- 目标 PostgreSQL 主版本应不低于源端，优先保持同为 PostgreSQL 16。
- 恢复前确认字符集、时区、可用磁盘空间和秘密配置。
- 先在隔离项目恢复并运行 `python -m app.verify_restore`，再安排业务切换。
- 恢复后重新 Seed 会重置四个演示账号密码；正式账号不要使用演示 Seed 管理。
