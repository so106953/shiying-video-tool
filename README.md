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

最新状态：**9 个平台的公开样例通过，6 个平台样例未通过，1 个平台尚未适配**。

- 通过：今日头条、小红书、微博、抖音、西瓜视频、Instagram、Streamable、TikTok、X / Twitter。
- 未通过：哔哩哔哩、Dailymotion、Facebook、Reddit、Vimeo、YouTube。
- 尚未适配：快手。

通过标准是线上解析、完整下载、媒体轨检查和开头/结尾解码；每个平台至少一个公开样例。首页仅展示通过的平台，平台目录展示时间与失败原因。基线失败记录仍保留；X 更换了一条有效公开视频做修复复验，不代表旧帖子已恢复。详见 [验证报告](docs/platform-verification.md)、[JSON 证据](docs/platform-verification.json)、[验证脚本](scripts/verify_platforms.py)。

小红书支持 `xhslink.cn` 和 `xhslink.com` 分享链接及手机分享页。西瓜视频支持相同视频编号的头条公开播放器回退；X 使用公开嵌入数据。已增加未加密、编码连续 MPEG-TS 分片合并能力（64 MB 内），暂停后重新开始；Dailymotion 本轮线上验证仍未通过，未列入可用平台。其他完整媒体的单文件上限仍为 256 MB。不合并分离音视频、不下载加密/DRM 内容；登录、验证、地区和隐私限制仍会影响部分链接。

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
| `server.py` | 早期本地服务实现，使用 SQLite / 本地文件，不是当前线上 API |
| `DESIGN.md` | 设计说明 |

`server.py` 保留作本地服务参考；其解析实现与当前 `engine.py` 并不完全一致。开发和验证线上功能请运行 `api.index:app`。

依赖目录、构建产物、下载视频、浏览器缓存、部署凭据与环境密钥不纳入 Git。网页源代码及部署配置完整保存在仓库中；在线地址对应已部署的网页。

## 验证

```bash
npm run build
python -m py_compile engine.py api/index.py server.py
python -m unittest discover -s tests -v
node tests/test_hls_remux.mjs
```

平台可用性需要对公开链接进行实际解析、下载和播放测试，构建成功不能替代平台测试。
