// Download every unencrypted MPEG-TS segment before remuxing; never infer completion from metadata.
export async function assembleHls(ticket, signal, report) {
  const { Input, Output, BlobSource, MPEG_TS, Mp4OutputFormat, BufferTarget, Conversion } = await import('mediabunny');
  const limit = 64 * 1024 * 1024;
  const manifest = await fetch(`/api/hls?ticket=${encodeURIComponent(ticket)}`, { signal });
  if (!manifest.ok) { const error = await manifest.json(); throw new Error(error.detail || '播放列表获取失败。'); }
  const text = await manifest.text();
  if (/#EXT-X-(?:STREAM-INF|MAP|BYTERANGE|DISCONTINUITY)(?=[:\r\n]|$)/m.test(text)) throw new Error('当前仅支持编码连续的 MPEG-TS 分片视频。');
  const resources = text.split(/\r?\n/).map(line => line.trim()).filter(line => line && !line.startsWith('#'));
  if (!resources.length || resources.length > 2000) throw new Error('视频分片为空或数量超过当前处理上限。');
  const pieces = [];
  let transferred = 0;
  for (const [index, resource] of resources.entries()) {
    const url = new URL(resource, location.href);
    if (url.origin !== location.origin || url.pathname !== '/api/media' || !url.searchParams.get('ticket')) throw new Error('播放列表包含无效分片。');
    let offset = 0;
    let ended = false;
    while (!ended) {
      const response = await fetch('/api/chunk', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ticket: url.searchParams.get('ticket'), offset }), signal });
      if (!response.ok) { const error = await response.json(); throw new Error(error.detail || '视频分片下载失败。'); }
      const piece = await response.blob();
      ended = response.headers.get('X-Media-End') === '1';
      if (!piece.size && !ended) throw new Error('视频分片不完整。');
      transferred += piece.size;
      if (transferred > limit) throw new Error('分片视频超过 64 MB，请选择较低画质。');
      pieces.push(piece);
      offset += piece.size;
      report({ downloaded: transferred, progress: Math.floor((index + (ended ? 1 : 0)) / resources.length * 85) });
    }
  }
  if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
  const input = new Input({ source: new BlobSource(new Blob(pieces)), formats: [MPEG_TS] });
  let conversion;
  const stop = () => { input.dispose(); conversion?.cancel().catch(() => {}); };
  signal.addEventListener('abort', stop, { once: true });
  try {
    const output = new Output({ format: new Mp4OutputFormat({ fastStart: 'in-memory' }), target: new BufferTarget() });
    conversion = await Conversion.init({ input, output, tracks: 'primary' });
    if (!conversion.isValid || conversion.discardedTracks.length) throw new Error('当前分片编码无法完整保存为 MP4。');
    conversion.onProgress = progress => report({ progress: Math.min(99, 85 + Math.floor(progress * 14)) });
    await conversion.execute();
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
    const data = output.target.buffer;
    if (!data?.byteLength || data.byteLength > limit) throw new Error('合并文件为空或超过 64 MB，请选择较低画质。');
    return new Blob([data], { type: 'video/mp4' });
  } finally { signal.removeEventListener('abort', stop); input.dispose(); }
}
