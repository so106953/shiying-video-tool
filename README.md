# 拾影 · Shiying

支持手机和电脑的视频链接解析与本地下载工具。

- 项目名称：拾影
- 仓库名称：`shiying-video-tool`
- 在线网页：https://shiying-video-tool-rho.vercel.app
- 技术栈：React、Vite、FastAPI、yt-dlp、IndexedDB

## 功能

粘贴视频链接或完整分享文字，查看真实标题、封面与可用清晰度，下载到当前设备。支持单条和批量解析、下载队列、暂停与继续、播放预览、解析历史以及设置。电脑使用侧栏导航，手机使用底部导航。

Vercel 版本通过服务器解析媒体地址，再分块传输到浏览器；下载缓存保存在当前浏览器的 IndexedDB，历史和设置保存在本地。不同设备之间不自动同步。

## 平台验证情况

最新状态：**19 个平台的公开样例通过，11 个平台样例未通过，4 个平台尚未适配**。

- 通过：今日头条、哔哩哔哩、小红书、微博、快手、抖音、西瓜视频、Instagram、Streamable、TikTok、X / Twitter、Pinterest、皮皮虾、糖豆广场舞、好看视频、知乎、央视 CCTV、网易视频、AcFun。
- 未通过：Dailymotion、Facebook、Reddit、Vimeo、YouTube、新片场、搜狐视频、梨视频、美拍、斗鱼回放、虎牙回放。
- 尚未适配：QQ短视频、秒懂百科、音悦台、PP视频。

通过标准是线上解析、完整下载、媒体轨检查和开头/结尾解码；每个平台至少一个公开样例。首页仅展示通过的平台，验证页面展示时间与失败原因，更多平台目录只代表适配能力。基线失败记录仍保留；X 更换了一条有效公开视频做修复复验，不代表旧帖子已恢复。详见 [验证报告](docs/platform-verification.md)、[JSON 证据](docs/platform-verification.json)、[验证脚本](scripts/verify_platforms.py)。

小红书支持 `xhslink.cn` 和 `xhslink.com` 分享链接及手机分享页。西瓜视频支持相同视频编号的头条公开播放器回退；X 使用公开嵌入数据。已增加未加密、编码连续 MPEG-TS 分片合并能力（64 MB 内），暂停后重新开始；Dailymotion 本轮线上验证仍未通过，未列入可用平台。其他完整媒体的单文件上限仍为 256 MB。连接独立服务后可合并分离音视频和提取音频；不下载加密/DRM 内容；登录、验证、地区和隐私限制仍会影响部分链接。

## 本地运行当前云端版本

需要 Node.js 24 和 Python 3.12。

```bash
npm ci
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

设置一个随机签名密钥，然后启动 API：

```bash
export SHIYING_SIGNING_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
uvicorn api.index:app --host 127.0.0.1 --port 8787
```

在另一个终端启动网页：

```bash
npm run dev
```

打开 Vite 显示的本地地址。`vite.config.js` 会将 `/api` 请求转发到端口 8787。

## 部署到 Vercel

1. 在 Vercel 导入本仓库，选择 Vite，构建命令 `npm run build`，输出目录 `dist`。
2. 在 Production / Preview 配置加密环境变量 `SHIYING_SIGNING_SECRET`，使用独立随机值。
3. 部署；仓库中的 `vercel.json` 已配置 Python API 路由与网页回退路由。

当前线上项目已配置签名密钥，真实密钥不包含在仓库中。网页访问权限由 Vercel 的 Deployment Protection 设置决定。

## 目录

| 路径 | 用途 |
| --- | --- |
| `src/` | 响应式网页、解析、下载、历史与设置 |
| `src/cloud.js` | 浏览器分块下载、IndexedDB 缓存及任务恢复 |
| `api/index.py` | 当前 Vercel API、加密下载凭据与媒体分块代理 |
| `engine.py` | 公共分享页解析、平台名称及中文错误处理 |
| `public/` | 网站图标等静态资源 |
| `vercel.json` | Vercel 部署配置 |
| `server.py` / `worker.py` | 独立下载服务，使用 SQLite、本地文件和 FFmpeg |
| `worker_auth.py` / `worker_client.py` | 本机会话隔离与 Vercel 到独立服务的连接 |
| `DESIGN.md` | 设计说明 |

独立下载服务可通过 Docker Compose 运行，接收服务密钥认证，按平台加载本机会话并用 FFmpeg 准备文件。Vercel 通过加密票据转发文件；浏览器不接收服务密钥或平台 Cookie。见 [后端与登录配置](docs/worker-setup.md)。配置能力不代表剩余平台已经实测通过，当前已验证名单保持不变。

依赖目录、构建产物、下载视频、浏览器缓存、部署凭据与环境密钥不纳入 Git。网页源代码及部署配置完整保存在仓库中；在线地址对应已部署的网页。

## 验证

```bash
npm run build
python -m py_compile engine.py api/index.py server.py
python -m unittest discover -s tests -v
node tests/test_hls_remux.mjs
```

平台可用性需要对公开链接进行实际解析、下载和播放测试，构建成功不能替代平台测试。

## 免费格式与平台目录

解析后点击“更多格式 / 提取音频”，可使用已连接的独立后端生成 MP4、MKV 视频和 MP3、M4A 音频。只在主动展开时创建转换选项，不影响默认直链下载。MKV 通常需要下载后用本地播放器打开，单文件上限仍为 256 MB。网页没有新增收费接口；免费后端仍受休眠、流量、存储和平台访问限制。

“更多平台 → 平台目录”可搜索当前 yt-dlp 版本实际包含的适配器，提供常见平台中文索引。适配器数量不等于平台数量或下载通过数量，国内、国外实测标签仍单独显示既有验证记录。快手已增加独立适配并通过一个公开分享样例；图集下载和登录受限链接仍不保证可用。

格式流程实测命令：`python tests/integration_formats.py`，启动隔离的临时后端，用公开测试视频验证四种格式的完整传输、音视频轨道、时长、全片解码和任务删除，不使用平台账号。

## 本轮平台扩展

新增公开分享适配层：快手（短链、PC 详情页、手机分享页）、好看视频、皮皮虾、糖豆、网易视频；后端可重新获取地址并合并分片。另接入 Threads、微视、懂车帝、单视频公众号文章的公开元数据读取，但尚未通过线上下载验证，不作为已验证支持的平台。微视已知旧公开接口返回 404，公众号当前测试网络无法访问。

本轮新增真实通过：快手、好看视频、皮皮虾、糖豆、网易视频、知乎、央视、哔哩哔哩、AcFun。前述平台与历史通过项合计 19 个样例，完整记录见 `docs/platform-expansion-verification.json`。与 GreenVideo 页面清单仍有差距，QQ 短视频、秒懂百科、音悦台、PP 视频尚未实现专用适配；登录、权限、接口变更和失效样例仍需逐项处理。
