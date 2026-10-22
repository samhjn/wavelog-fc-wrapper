# Wavelog on Aliyun FC

把 Wavelog 部署到阿里云函数计算 FC 3.0：**自定义容器 + NAS + 外部 MySQL/MariaDB**。本仓库只维护运行封装，不 fork Wavelog 业务代码。默认应用版本为 **3.2.4**。

## 组成

- Apache 对 FC 监听 `9000`；`127.0.0.1:80` 专供 Wavelog Cron Manager 的内部回调。
- 从官方 Wavelog 镜像复制应用文件，PHP 从 `php:8.5-apache-trixie` 重新构建。用 `--pull` 拉取新的运行时补丁。
- 配置、上传文件、会话和可变数据存入 `/mnt/wavelog`；未挂载时拒绝启动。冷启动不下载应用，也不递归修改已有用户文件。
- FC Timer 每分钟调用带密钥的 `POST /invoke`，同步等待 Cron Manager 完成。没有常驻 cron 进程。
- 保留原生安装向导；安装入口默认关闭，开启后额外使用 HTTP Basic 密钥保护。
- `/healthz` 检查 Web/PHP 和存储可写性，不查询数据库，安装前也能通过健康检查。

不包含 MySQL、NAS、VPC、域名和证书的创建，也不部署可选的 Wavelog Worker（实时 WebSocket 功能）。

## 1. 准备资源

1. 同地域的 FC、ACR 容器镜像仓库、VPC、vSwitch、安全组和通用型 NAS NFS 挂载点。
2. 在 NAS 上创建专用 `/wavelog` 目录，确保 UID/GID **33:33** 可以读写和遍历。NAS 权限组允许 FC 所在 VPC 访问；数据库白名单/安全组允许该 VPC 访问 MySQL 端口。
3. 已有 **MySQL 8+ 或 MariaDB 10.11+**。新建空数据库和专用用户，授予该数据库的建表、改表及读写权限；安装和升级需要 DDL。Wavelog 数据库不能放到容器临时磁盘。
4. FC 执行角色信任 `fc.aliyuncs.com`，具备实际需要的 ACR 拉取、VPC/NAS 和 SLS 日志权限。部署者需要创建/更新 FC、绑定角色及相关资源的权限。企业版 ACR 如需额外镜像仓库配置，在 `customContainerConfig` 中按其访问方式补充。
5. 安装 Docker Buildx 和 Serverless Devs 3.x，执行 `s config add` 配置 `default` 凭据。AccessKey 不写入仓库。

## 2. 构建并推送镜像

```bash
git clone https://github.com/samhjn/wavelog-fc-wrapper.git
cd wavelog-fc-wrapper
cp .env.example .env
```

修改 `.env` 内的地域、资源 ID、镜像地址和最终根域名 URL。不要使用 URL 子路径。
分别运行两次 `openssl rand -hex 32`，填写 `WAVELOG_CRON_TOKEN` 和 `WAVELOG_INSTALL_TOKEN`。`.env` 已被 Git 和 Docker 构建上下文排除。

```bash
# 登录自己的 ACR；建议交互输入密码或使用 --password-stdin。
docker login registry.cn-hangzhou.aliyuncs.com

docker buildx build --pull --platform linux/amd64 \
  -t registry.cn-hangzhou.aliyuncs.com/YOUR_NAMESPACE/wavelog-fc:3.2.4-fc1 \
  --push .
```

将 `.env` 的 `FC_IMAGE` 设置为刚推送的镜像。生产推荐填 `仓库@sha256:...`，升级时换 digest，避免同名 tag 引起部署歧义。

## 3. 部署并安装

首次部署把 `.env` 中 `WAVELOG_INSTALL_ENABLED` 改成 `true`：

```bash
# Serverless Devs 从项目 .env 读取 ${env('NAME')}。
s deploy
```

在 FC 控制台为该函数的 `LATEST` 配置自定义域名、`/*` 路由及 HTTPS 证书，DNS 指向控制台给出的 CNAME。让 `WAVELOG_BASE_URL` 与最终访问地址一致，例如 `https://log.example.com/`。中国内地公网域名按阿里云要求完成备案；不要将测试域名当作生产地址。

打开 `https://log.example.com/install/`：

- HTTP Basic 用户名：`install`；密码：`WAVELOG_INSTALL_TOKEN`。
- 按原生向导填写数据库连接信息、管理员呼号/账号、定位网格等；数据库密码由向导写入 NAS 配置，不进入镜像或 Git。
- 数据库地址用 VPC 内网地址；非默认端口可填 `host:port`。最终 URL 填 `WAVELOG_BASE_URL`。
- 完成数据库建表、迁移与初始数据更新后登录。
- 将 `WAVELOG_INSTALL_ENABLED=false`，再次 `s deploy`。已有 NAS 文件不会被覆盖。

确认 `/healthz` 返回 `{"status":"ok"}`，并在 Admin → Cron Manager 查看最后执行时间。初次 DXCC/LoTW 等数据下载依赖 FC 的公网连通性；耗时也取决于上游服务。

> 安装中途若发生实例回收，已完成的配置文件仍在 NAS。不要反复清空生产数据。新实例发现两份配置后会锁住安装器；首次安装失败时，先备份并检查日志，再决定恢复安装或用新的空数据库、空 NAS 目录重试。

## 持久化目录

以下路径均相对于 NAS 的 `/wavelog` 导出目录：

| NAS 路径 | 内容 |
| --- | --- |
| `application/config/docker/` | 安装生成的 `config.php`、`database.php` 以及环境配置 |
| `uploads/`、`userdata/` | ADIF 导入、用户上传、QSL 图片 |
| `assets/qslcard/`、`images/eqsl_card_images/` | 旧版 QSL 图片目录 |
| `assets/resources/`、`updates/` | 更新下载的数据文件 |
| `backup/` | Wavelog 生成的备份文件 |
| `application/cache/`、`application/logs/` | 应用缓存与应用日志 |
| `sessions/` | Wavelog 和安装器的 PHP 会话 |
| `locks/` | Timer 的跨实例互斥锁 |

启动只初始化缺失目录；已有目录不会被镜像内容覆盖。静态 JS/CSS 随镜像升级，不能把整个 `assets/` 挂到旧 NAS 数据上。需要改 Wavelog 配置时编辑 `application/config/docker/` 内的文件；根 URL、session 路径及安全 Cookie 由封装统一覆盖。

备份必须同时包含数据库与 NAS。NAS 提供持久化，不等于已有备份。迁移时停止旧实例的写入和 cron，复制上述目录及数据库，保留原来的 `encryption_key`，修正文件所有权，再切换访问地址。不要直接拿 Cloudlog 数据库交给本封装；先按 Wavelog 官方迁移步骤转换。

## 定时任务、并发与费用

FC Timer 的事件格式为 `{"payload":"<WAVELOG_CRON_TOKEN>", ...}`，只触发固定的 Cron Manager 地址。公网直接访问 `/cron/run` 被拒绝，`/invoke` 必须验证密钥；密钥不要放在 URL 中。

- NAS `flock` 避免两个 Timer 调用同时执行；任务执行期间保持请求活跃。锁随进程退出自动释放。
- 超时预算：内部请求 840 秒，FC 900 秒，Apache 920 秒。失败返回 502；上游某些业务失败仍需在 Cron Manager 中检查。
- 异步自动重试设为 0，事件最大存活时间 60 秒，避免旧 tick 排队后反复执行。它不保证任务 exactly-once，也不补跑已错过的时间点；长任务可能跨过后续分钟任务。
- 默认 `instanceConcurrency: 1` 和 `reservedConcurrency: 1`，安装与数据库升级串行执行，**长 cron 会暂时占用唯一并发**。安装稳定后，可一起调大这两个值，例如 4，同时评估 PHP 内存、数据库连接和应用并发行为。升级数据库期间恢复串行，并先停 Timer。
- 不配置预留实例。但每分钟 Timer 会产生持续调用，可能阻止长时间缩容到零；这不是“无人访问时零费用”的配置。直接改成每 5 分钟会漏掉原生 Cron Manager 按分钟匹配的任务，必须同时调整其任务表达式。
- FC HTTP 请求体上限与 PHP 上传限制是两层限制；这里把上传限制设为 30 MiB、POST 31 MiB，为平台 32 MB 上限留空间。大 ADIF 应拆分导入。

## 本地验证

```bash
docker build --pull -t wavelog-fc:test .
python3 tests/smoke.py wavelog-fc:test
```

测试启动独立 MariaDB 和 Docker 数据卷，走真实安装器，检查 PHP/Apache、权限、Timer、上传目录禁止执行 PHP，以及销毁容器后配置/会话/上传数据仍可用。测试最后删除自己创建的容器、数据卷和网络，不使用云账号。

GitHub Actions 自动构建并运行同一测试；它不推送镜像或部署云资源。

## 升级与运行时补丁

1. 备份数据库和 NAS，停 Timer，确认没有导入或后台更新正在执行。
2. 升级 Wavelog 时修改 Dockerfile 中 `WAVELOG_IMAGE` 的固定版本，同时更新 `WAVELOG_GIT_DESCRIBE`，构建并通过测试。可将应用镜像固定到 digest。
3. 只更新 PHP 时保留 Wavelog 版本，重新 `docker buildx build --pull ... --push .`；可通过 `--build-arg PHP_IMAGE=...` 选择经过验证的兼容 PHP 镜像。
4. 修改 `FC_IMAGE` 到新 digest，`s deploy`，串行完成 Wavelog 的数据库迁移，检查登录、ADIF/API、QSL 和 cron 后恢复 Timer。

不要在容器里 `git pull` 或运行 Web 自更新；下次冷启动会恢复镜像版本。存在数据库迁移时，只回滚镜像未必能回滚应用，需要配套恢复数据库和 NAS 快照。

## 参考

- [Wavelog 官方 Docker 安装与要求](https://docs.wavelog.org/getting-started/installation/docker/)
- [本封装对应的 Wavelog 3.2.4 源码](https://github.com/wavelog/wavelog/tree/3.2.4)
- [Serverless Devs FC3 配置规范](https://docs.serverless-devs.com/user-guide/aliyun/fc3/spec/)
- [FC Web 函数调用协议](https://help.aliyun.com/zh/functioncompute/web-functions)
- [FC HTTP 触发器限制](https://help.aliyun.com/zh/functioncompute/http-triggers-overview)

Wavelog 及其依赖保留各自许可证；本仓库不改变上游许可。
