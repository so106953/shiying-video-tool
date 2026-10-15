# 独立下载服务与登录会话

代码已支持独立下载服务、按平台读取本机会话以及 FFmpeg 合并。**接入能力不代表剩余平台已验证通过**：需要先提供真实运行机器，在该机器的网络上完成平台登录，再逐项实测。

网页仍部署在 Vercel。公开直链优先走原流程；解析失败、需要合并分离音视频或处理分片时，已配置的独立服务会接手。后端先准备文件，再通过现有的加密票据、分块下载和浏览器缓存保存到设备。单文件上限 256 MB。

## 运行位置

- 推荐自己的电脑或受自己控制的服务器。机器必须能正常访问目标平台。
- 平台 Cookie 只保存在该机器，不发送到网页、Vercel 环境变量或聊天中。
- Vercel 需要可访问的固定 HTTPS 服务地址。仅在本机启动 localhost 服务，并不能让 Vercel 连接到它。
- 账号下载服务是私人服务。保留 Vercel Deployment Protection，仅授权可信使用者访问；所有使用者都会使用后端配置的账号权限。本版本不提供多用户账号隔离。

## 启动服务

需要 Docker Compose；首次构建会安装 Python 依赖和 FFmpeg。

```bash
mkdir -p sessions
chmod 700 sessions
# Linux/macOS：让容器用户与本机用户一致，以读取权限为 600 的会话文件：
export SHIYING_UID="$(id -u)"
# 在自己的终端生成并保存，不提交到仓库：
export SHIYING_WORKER_TOKEN="$(python -c 'import secrets; print(secrets.token_hex(32))')"
docker compose -f compose.worker.yml up -d --build
```

若以 root 管理服务器，请保持容器 UID 为 1000，并将 `sessions` 目录及会话文件归属调整为该 UID；不要把 `SHIYING_UID` 设为 0。

端口默认只绑定 `127.0.0.1:8787`。使用你管理的 HTTPS 反向代理转发到该端口；后端每个接口都要求服务密钥，拒绝匿名调用。服务没有登录网页，也没有 Cookie 上传接口。

也可直接运行：

```bash
pip install -r requirements.txt
# 安装系统 FFmpeg 后：
export SHIYING_WORKER_TOKEN="你自己的至少32字符随机密钥"
export SHIYING_DATA_DIR="$(pwd)/worker-data"
export SHIYING_COOKIE_DIR="$(pwd)/sessions"
uvicorn worker:app --host 127.0.0.1 --port 8787 --workers 1
```

SQLite、任务和媒体在 `worker-data` 或 Docker 数据卷保存。删除网页中的独立服务任务时，会同时请求后端删除任务与媒体缓存。可设置 `SHIYING_CACHE_TTL_SECONDS=86400`，每分钟清理超过 24 小时未访问的已完成、暂停、失败和取消任务；正在下载及排队任务不会被清理，读取文件会刷新保留时间。默认不自动清理。

## 免费临时后端（Render）

如果只需要解析后保存到手机或电脑，可以使用临时磁盘，不需要购买持久磁盘。仓库的 `render.yaml` 提供免费 Docker Web Service 配置，包含 FFmpeg、随机生成的服务密钥和 24 小时缓存清理。免费方案是否可用以 Render 当前账户和官方限制为准。

在 Render 选择 New → Blueprint，连接本仓库并应用 `render.yaml`，确认方案为 Free。部署成功后，将服务的 HTTPS 根地址和 Environment 中生成的 `SHIYING_WORKER_TOKEN` 配置到下节的 Vercel 环境变量；不要把密钥发到聊天或提交到 GitHub。不要添加公开的免认证下载接口。

免费服务会休眠，唤醒后的首次请求可能超时，可等待后重试。重启或重新部署可能丢失全部临时任务，需要重新解析；已经保存到设备的文件不受影响。服务器不会立即删除刚传输的文件，以便分块重试和断点续传；过期自动清理，也可在网页中手动删除任务。不需要一直保存文件并不代表免费云 IP 能通过平台登录验证，剩余平台仍需要实际验证。

## 本机配置平台会话

在下载服务所在机器，以自己的浏览器登录平台并手动完成可能出现的验证码。仅配置有权使用的账号和内容。

显式运行以下命令会读取所选浏览器的 Cookie 存储，仅将所选平台相关域的会话写入 `sessions/<platform>.txt`，权限为 600；不会上传会话，也不会自动验证下载。

```bash
python scripts/import_session.py youtube --browser chrome
python scripts/import_session.py bilibili --browser chrome
python scripts/import_session.py facebook --browser firefox
python scripts/import_session.py reddit --browser firefox
python scripts/import_session.py vimeo --browser chrome
python scripts/import_session.py dailymotion --browser chrome
```

可用 `--profile` 指定自己的浏览器配置目录。浏览器锁定、操作系统密钥权限或浏览器加密机制可能使读取失败；请按 yt-dlp 的[官方会话说明](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp)在本机处理，勿把 Cookie 发到聊天或提交到 GitHub。也可直接把仅包含对应平台域的 Netscape 格式会话文件放到对应路径。

服务每次解析/下载都会重新读取会话文件，过期后在本机更新即可；不会修改原始会话文件。未配置的站点仍尝试普通公开访问，不会借用其他平台的 Cookie。

## 连接 Vercel

在 Vercel 的项目环境变量中设置并重新部署：

- `SHIYING_WORKER_URL`：最终 HTTPS 地址，如 `https://download.example.com`，不包含路径、用户名或查询参数。
- `SHIYING_WORKER_TOKEN`：与独立服务一致的随机密钥，设为加密变量。

平台 Cookie 不放在 Vercel 中。打开网页「设置 → 登录与独立下载服务 → 检查连接」。界面区分“服务已连接”“会话已配置”和真实下载验证，配置文件存在不代表登录有效。

服务地址和密钥变更后，原有独立下载票据失效，需要重新解析。下载暂停会请求后端暂停；FFmpeg 正在收尾时可能继续完成文件，浏览器不会继续传输，稍后可恢复保存。

## 当前验证记录

- 临时独立后端与网页 API 的真实测试视频：788,493 字节，完整传输并通过解码检查，准备与删除接口通过。
- 手机视口实测：连接检查、6 项会话状态、优先使用独立服务、保存与播放通过，无 JavaScript 错误。
- Docker 镜像构建与容器内健康检查通过，FFmpeg 可用，未认证请求返回 401。
- 这些测试没有读取或使用真实平台账号，不能替代剩余 6 个平台的登录下载实测。

## 开发验证

在仓库根目录，安装 Python 依赖和本机 FFmpeg 后运行 `python tests/integration_worker.py`。它启动临时后端和网页 API，用公开视频验证服务认证、准备、分块传输和删除；不读取任何平台会话。单元测试为 `python -m unittest discover -s tests -v`。

## 验证边界

连接、凭据隔离、下载准备、进度、文件传输等流程可以用测试媒体验证；YouTube、哔哩哔哩、Facebook、Reddit、Vimeo、Dailymotion 的真实登录下载仍需要上述实际环境。登录不能解决 DRM、账号无权限、地区限制或所有服务器 IP 限制；本工具不自动完成验证码。
