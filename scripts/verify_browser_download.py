"""Exercise the actual UI for browser-side HLS remux. Requires Playwright and Chromium."""
import os, pathlib, shutil, httpx
from playwright.sync_api import sync_playwright

def save_browser_download(base, url, height, destination):
 headers={}
 if os.environ.get('SHIYING_VERIFY_BYPASS'):headers['x-vercel-protection-bypass']=os.environ['SHIYING_VERIFY_BYPASS']
 with httpx.Client(timeout=180,verify=os.environ.get('SSL_CERT_FILE')or True)as http, sync_playwright()as playwright:
  executable=os.environ.get('CHROMIUM_PATH')or shutil.which('chromium')
  browser=playwright.chromium.launch(**({'executable_path':executable}if executable else{}),args=['--no-sandbox'])
  try:
   page=browser.new_page(viewport={'width':390,'height':844},accept_downloads=True)
   def forward(route):
    req=route.request
    request_headers={k:v for k,v in req.headers.items()if k.lower()not in('host','content-length','accept-encoding')}
    response=http.request(req.method,req.url,headers=request_headers|headers,content=req.post_data_buffer)
    route.fulfill(status=response.status_code,headers={k:v for k,v in response.headers.items()if k.lower()not in('content-encoding','transfer-encoding','content-length')},body=response.content)
   page.route(base.rstrip('/')+'/**',forward)
   page.goto(base,wait_until='networkidle')
   page.get_by_role('textbox',name='视频链接').fill(url)
   page.get_by_role('button',name='解析链接',exact=True).click()
   page.locator('.result-options select').first.wait_for(timeout=180000)
   if height:page.locator('.result-options select').first.select_option(str(height))
   page.get_by_role('button',name='下载到本地',exact=True).click()
   page.wait_for_function('''() => { const t=JSON.parse(localStorage.getItem('shiying.cloud.tasks.v1')||'[]')[0];return t&&['completed','failed'].includes(t.status); }''',timeout=300000)
   task=page.evaluate("JSON.parse(localStorage.getItem('shiying.cloud.tasks.v1'))[0]")
   if task['status']!='completed':raise RuntimeError(task.get('error','浏览器合并失败'))
   page.locator('.mobile-nav').get_by_role('button',name='下载管理').click()
   page.get_by_role('button',name='播放 '+task['title'],exact=True).click()
   page.locator('.preview-content video').evaluate('(video)=>video.play()')
   page.wait_for_function('document.querySelector(".preview-content video").currentTime>0',timeout=30000)
   with page.expect_download(timeout=30000)as event:page.get_by_role('button',name='保存到设备',exact=True).click()
   event.value.save_as(str(destination))
  finally:browser.close()
