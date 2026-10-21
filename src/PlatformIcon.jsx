import { useState } from 'react';
import { Globe2 } from 'lucide-react';

// Aliases identify the same service; unmatched engine adapters use a neutral icon.
const platforms = {
  douyin: ['抖音', 'Douyin'], bilibili: ['哔哩哔哩', 'Bilibili'],
  xiaohongshu: ['小红书', 'XiaoHongShu'], toutiao: ['今日头条', 'Toutiao'],
  weibo: ['微博', 'Weibo'], kuaishou: ['快手', 'Kuaishou'], ixigua: ['西瓜视频', 'Ixigua'],
  instagram: ['Instagram'], streamable: ['Streamable'], tiktok: ['TikTok'],
  x: ['X / Twitter', 'Twitter', 'X'], pinterest: ['Pinterest'], pipixia: ['皮皮虾', 'Pipixia'],
  tangdou: ['糖豆广场舞', 'Tangdou'], haokan: ['好看视频', 'Haokan'], zhihu: ['知乎', 'Zhihu'],
  cctv: ['央视 CCTV', 'CCTV'], netease: ['网易视频', '网易视频163', 'NetEaseVideo', 'NetEase'],
  acfun: ['AcFun', 'AcFunVideo'], youtube: ['YouTube', 'Youtube'], facebook: ['Facebook'],
  vimeo: ['Vimeo'], dailymotion: ['Dailymotion'], reddit: ['Reddit'], threads: ['Threads'],
  weverse: ['Weverse'], xinpianchang: ['新片场', 'Xinpianchang'], sohu: ['搜狐视频', 'Sohu'],
  huya: ['虎牙回放', 'Huya'], douyu: ['斗鱼回放', 'Douyu'], pearvideo: ['梨视频', 'PearVideo'],
  meipai: ['美拍', 'Meipai'], dongchedi: ['懂车帝', 'Dongchedi'], weishi: ['微视', 'Weishi'],
  wechat: ['微信公众号', 'WechatArticle'], tencentvideo: ['腾讯视频', 'TencentVideo'],
  qq: ['QQ短视频', 'QQ'], baike: ['秒懂百科'], yinyuetai: ['音悦台', 'YinYueTai'], pptv: ['PP视频', 'PPTV'],
};
const aliases = new Map(Object.entries(platforms).flatMap(([key, names]) => names.map(name => [name.toLowerCase(), key])));

export function platformIconPath(name = '') {
  const normalized = name.trim().toLowerCase();
  const key = aliases.get(normalized) || aliases.get(normalized.split(':')[0]);
  return key ? `/platforms/${key}.png` : null;
}

export default function PlatformIcon({ name }) {
  const src = platformIconPath(name);
  const [failedSource, setFailedSource] = useState(null);
  return src && failedSource !== src
    ? <img className="platform-icon" src={src} width="24" height="24" alt="" aria-hidden="true" decoding="async" onError={() => setFailedSource(src)}/>
    : <Globe2 className="platform-icon platform-icon-fallback" aria-hidden="true"/>;
}
