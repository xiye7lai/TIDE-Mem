# TIDE-Mem 参赛起步说明

## 已经替你完成的部分

当前包已包含可公开提交的完整初始系统：FastAPI Add/Search/Health 接口、`gpt-4o-mini` 记忆抽取与证据重排、原始证据与结构化记忆双视图、时间状态账本、严格 `user_id` 隔离、幂等写入、30 天清理、Docker、测试、CI、公开仓库说明、Render 部署蓝图和申请文案生成器。

默认参赛路线仍是：

> **Textual Memory × Academic Methods × Self-hosted Add/Search API**

现在不需要先购买域名或配置 VPS。默认流程采用 GitHub 公开仓库加 Render 持久化部署；仓库同时保留自建服务器方案作为备选。

## 你只需要完成三次受保护操作

这些操作涉及你的账户或密钥，必须由你本人在官方页面或隐藏输入框完成：

1. 在 GitHub 官方浏览器页面授权 GitHub CLI。
2. 在 Render 页面确认付费 Starter 服务和 1 GB 持久化磁盘，并在受保护字段输入模型供应商 Key。
3. 从 Render 的 Environment 页面复制自动生成的 Memory System Key，粘贴到本地脚本的隐藏输入框以及赛事受控密钥字段。

**不要把 GitHub 密码、PAT、模型 Key、Memory System Key 或 Eval Key 发到聊天里。**

## 第一步：双击发布到 GitHub

解压完整参赛包后，进入带有 `.git` 的 `TIDE-Mem` 仓库，双击：

```text
PUBLISH_TO_GITHUB.cmd
```

也可在 PowerShell 中运行：

```powershell
.\scripts\publish_github.ps1
```

脚本会自动完成：

- 运行测试与秘密扫描；
- 缺少 Git、Python 3.11 或 GitHub CLI 时通过 `winget` 安装；
- 打开 GitHub 官方网页登录授权；
- 读取当前 GitHub 账户并询问联系人、邮箱、机构和团队；
- 将固定提交作者改为你的 GitHub 身份；
- 重建 `v0.1.0-amc2026` Tag；
- 创建新的公开仓库并推送 `main` 和 Tag；
- 创建 GitHub Release；
- 启动 GitHub Actions 测试和 GHCR 镜像构建；
- 在本地忽略目录 `submission-private/` 保存非密钥元数据；
- 自动打开该仓库对应的 Render Blueprint 页面。

默认仓库名是 `tide-mem`。若你的账户已经存在同名仓库，运行：

```powershell
.\scripts\publish_github.ps1 -RepoName tide-mem-amc2026
```

脚本不会覆盖已有 `main` 分支的仓库。

## 第二步：在 Render 页面批准部署

GitHub 步骤完成后，脚本会打开类似下面的页面：

```text
https://render.com/deploy?repo=https://github.com/你的账号/仓库名
```

在 Render 页面中：

1. 登录并允许 Render 读取刚创建的公开仓库。
2. 检查资源：一个付费 Starter Docker Web Service、Frankfurt 区域、一个 1 GB 持久化磁盘。
3. 只在 Render 的私密字段中填写 `TIDE_LLM_API_KEY`。
4. 不要修改 `TIDE_LLM_MODEL=gpt-4o-mini`、`TIDE_ENFORCE_GPT4O_MINI=true` 等固定配置。
5. 确认创建 Blueprint，直到 `/health` 显示健康。

`render.yaml` 已关闭自动重新部署，避免提交后因后续 Git Push 静默改变评测版本。

Render 会自动生成 `TIDE_MEMORY_API_KEY`。它位于服务的 Environment 设置中，不会进入公开仓库。

## 第三步：运行公网 Smoke 并生成申请材料

拿到 Render 的公网地址和自动生成的 Memory System Key 后，双击：

```text
VERIFY_AND_PREPARE_SUBMISSION.cmd
```

也可以在 PowerShell 中运行：

```powershell
.\scripts\verify_hosted.ps1 -BaseUrl https://你的服务.onrender.com
```

脚本会使用隐藏输入框读取 Memory System Key，不会把它写到命令历史或磁盘。随后自动验证：

- Health 公网可访问；
- 未鉴权 Add 被拒绝；
- Add 同步完成并能立即 Search；
- 返回 ID、Top K、幂等行为正确；
- 不同 `user_id` 严格隔离。

验证通过后，脚本会自动生成：

```text
submission-private/SUBMISSION_APPLICATION_READY.md
submission-private/SUBMISSION_NOTES_READY.txt
submission-private/hosted-verification.txt
submission-private/public-base-url.txt
```

这几个文件不会被 Git 跟踪。脚本还会把非密钥的公网地址写入 GitHub Actions 变量，并触发每 6 小时一次的公开 `/health` 检查。你只需把生成内容粘贴进赛事申请表，并将 Memory System Key 单独粘贴到赛事受控密钥字段。

需要附加小规模公网负载检查时再运行：

```powershell
.\scripts\verify_hosted.ps1 `
  -BaseUrl https://你的服务.onrender.com `
  -RunLoadTest
```

## 提交前核对

申请中应一致填写：

```text
Evaluation Type: Textual Memory
Division: Academic Methods
Route: Self-hosted Add/Search API
Authentication: X-Api-Key
Max Add Concurrency: 16
Search Concurrency: 16
Top K: 100
Tag: v0.1.0-amc2026
```

公开仓库、40 位 Commit SHA、三个 API URL 和镜像标识会由脚本写进私有申请文案。正式排行榜成绩只能在平台 Smoke/Full 后填写，当前版本不宣称任何官方成绩。

## 最重要的文件

- `docs/ACCOUNT_HANDOFF.md`：账户侧完整操作说明
- `docs/RULES_AND_DECISION.md`：规则与路线判断
- `docs/METHOD.md`：方法细节
- `docs/DEPLOYMENT.md`：Render 与自建服务器部署
- `docs/SMOKE_CHECKLIST.md`：正式 Full 前检查
- `docs/VALIDATION.md`：已经实际完成和仍需账户侧完成的验证
- `docs/SUBMISSION_APPLICATION_ZH.md`：公开申请模板
- `SUBMISSION_NOTES.txt`：公开短文案模板

## 不要做的事

- 不要把真实 Key 放到 Git、URL、截图、普通申请说明、邮件正文或群聊。
- 不要让 Search 直接生成最终答案或选项字母。
- 不要跨 `user_id` 检索或共享状态。
- 不要使用其他模型冒充 `gpt-4o-mini`。
- 不要在正式版本受理后静默修改代码、提示词、模型或数据库行为。
- 不要使用公开或私有评测题目做硬编码、训练或数据重建。
