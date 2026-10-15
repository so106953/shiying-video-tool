"""Publish only measured results from docs/platform-verification.json into the API and docs."""
import ast,json,pathlib,pprint
root=pathlib.Path(__file__).resolve().parents[1]
r=json.loads((root/'docs/platform-verification.json').read_text())
groups={'domestic':[],'international':[]};passed=[];failed=[];unsupported=[]
for row in r['results']:
 ok=row['status']=='passed'
 (passed if ok else unsupported if row['status']=='unsupported'else failed).append(row['name'])
 if ok:
  hint=f"完整下载 {row['bytes']/1000000:.2f} MB；开头、结尾解码通过"
  if row.get('delivery')=='hls':hint+='；分片在设备合并，上限 64 MB'
  if row['name']=='Instagram':hint+='；此样例无音轨'
 else:hint=row.get('diagnosis')or row['error']
 groups[row['group']].append({'name':row['name'],'hint':hint,'status':'样例已通过'if ok else'尚未适配'if row['status']=='unsupported'else'样例未通过','verified':ok,'sample_url':row.get('url'),'stage':row['stage']})
note=f"已核查 {len(r['results'])} 个平台：{len(passed)} 个样例完成线上解析、完整下载及开头/结尾解码，{len(failed)} 个样例未通过，{len(unsupported)} 个尚未适配。通过不代表任意链接均可下载；首页仅展示已通过的平台。"
p=root/'api/index.py';s=p.read_text();a=s.index('PLATFORM_GROUPS = ');b=s.index("\n\n@app.post('/api/parse')",a)
s=s[:a]+'PLATFORM_GROUPS = '+pprint.pformat(groups,sort_dicts=False,width=110)+'\nPLATFORM_CHECKED_AT = '+repr(r['checked_at'])+f'''\n\n@app.get('/api/platforms')
def platforms():
    return {{'groups': PLATFORM_GROUPS, 'checked_at': PLATFORM_CHECKED_AT,
            'passed': {len(passed)}, 'total': {len(r['results'])},
            'note': {note!r}}}
'''+s[b:];p.write_text(s)
lines=['# 平台验证报告','',f"最近更新（UTC）：{r['checked_at']}",'正式网页：https://shiying-video-tool-rho.vercel.app','',note,'','本报告合并基础验证和修复复验。通过要求：线上 API 解析、完整下载、ffprobe 媒体轨检查、ffmpeg 开头与结尾解码。分片视频还必须经过手机视口中的浏览器合并、保存和播放。JSON 中保留每项的检查时间与测试部署。','', '每个平台至少一个公开样例；结果仅代表检查时刻与样例。基线报告保留在 [原始报告](platform-verification-baseline.json)，没有用后续成功覆盖旧样例失败的历史证据。','', '| 平台 | 结果 | 阶段 / 证据 |','| --- | --- | --- |']
for row in r['results']:
 detail=f"{row['bytes']:,} 字节；开头、结尾解码通过"if row['status']=='passed'else row.get('diagnosis')or row['error']
 lines.append(f"| {row['name']} | {'通过'if row['status']=='passed'else'尚未适配'if row['status']=='unsupported'else'未通过'} | {detail} |")
lines+=['','## 修复与限制','','- 西瓜视频：读取相同视频编号的头条公开播放器，保留原始西瓜网页作为回退，并检查编号一致。','- X：改用公开嵌入数据；旧基线样例的历史媒体入口失效，修复后使用另一条公开含视频帖子验证，原始失败记录仍保留。','- Dailymotion：增加逐片下载和设备端 MP4 封装能力（未加密、编码连续 MPEG-TS，64 MB 内），固定媒体回归测试通过。但新部署仍无法稳定取得平台分片，线上验证未通过，未列入可用平台。暂停后重新下载合并。','- 哔哩哔哩仍对本轮云端请求返回 412；YouTube、Facebook、Reddit 要求账号或验证；Vimeo 的测试请求仍受登录/访问限制。未绕过验证，未把这些平台改为可用。','', '完整样例、SHA-256、编码和时长见 [JSON 证据](platform-verification.json)。Instagram 样例本身无音轨，其余通过样例均有音频。','', '## 重新验证','','```bash','pip install -r requirements-verify.txt','playwright install chromium','export SHIYING_VERIFY_URL=https://your-deployment.example','python scripts/verify_platforms.py','# 审阅报告后再发布平台状态：','python scripts/update_platform_catalog.py','```','','需要本机安装 ffmpeg / ffprobe。有部署保护时，通过环境变量 `SHIYING_VERIFY_BYPASS` 传入测试凭据；不要写进文件或提交。脚本不记录媒体票据、Cookie 或凭据，临时下载文件在检查后删除。']
(root/'docs/platform-verification.md').write_text('\n'.join(lines)+'\n')
p=root/'README.md';s=p.read_text();a=s.index('最近一轮');b=s.index('\n\n## 本地运行',a)
s=s[:a]+f'''最新状态：**{len(passed)} 个平台的公开样例通过，{len(failed)} 个平台样例未通过，{len(unsupported)} 个平台尚未适配**。

- 通过：{'、'.join(passed)}。
- 未通过：{'、'.join(failed)}。
- 尚未适配：{'、'.join(unsupported)}。

通过标准是线上解析、完整下载、媒体轨检查和开头/结尾解码；每个平台至少一个公开样例。首页仅展示通过的平台，平台目录展示时间与失败原因。基线失败记录仍保留；X 更换了一条有效公开视频做修复复验，不代表旧帖子已恢复。详见 [验证报告](docs/platform-verification.md)、[JSON 证据](docs/platform-verification.json)、[验证脚本](scripts/verify_platforms.py)。

小红书支持 `xhslink.cn` 和 `xhslink.com` 分享链接及手机分享页。西瓜视频支持相同视频编号的头条公开播放器回退；X 使用公开嵌入数据。已增加未加密、编码连续 MPEG-TS 分片合并能力（64 MB 内），暂停后重新开始；Dailymotion 本轮线上验证仍未通过，未列入可用平台。其他完整媒体的单文件上限仍为 256 MB。不合并分离音视频、不下载加密/DRM 内容；登录、验证、地区和隐私限制仍会影响部分链接。'''+s[b:];p.write_text(s)
print(note)
