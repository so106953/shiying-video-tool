// Regression fixture only: verify that all TS bytes reach the output, including the tail.
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import { assembleHls } from '../src/hls.js';
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'shiying-hls-test-'));
const originalFetch = globalThis.fetch;
const originalLocation = globalThis.location;
try {
  const source = path.join(temporary, 'fixture.ts');
  execFileSync('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=160x90:rate=12', '-f', 'lavfi', '-i', 'sine=frequency=900:sample_rate=44100', '-t', '6', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-f', 'mpegts', source]);
  const data = fs.readFileSync(source);
  const cut = Math.floor(data.length / 188 / 2) * 188;
  const segments = [data.subarray(0, cut), data.subarray(cut)];
  const visited = [];
  globalThis.location = new URL('https://fixture.example/');
  globalThis.fetch = async (url, options) => {
    if (String(url).startsWith('/api/hls?')) return new Response('#EXTM3U\n#EXTINF:3,\n/api/media?ticket=0\n#EXTINF:3,\n/api/media?ticket=1\n#EXT-X-ENDLIST\n');
    const body = JSON.parse(options.body);
    assert.equal(body.offset, 0);
    visited.push(body.ticket);
    return new Response(segments[Number(body.ticket)], { headers: { 'X-Media-End': '1' } });
  };
  const blob = await assembleHls('fixture', new AbortController().signal, () => {});
  assert.deepEqual(visited, ['0', '1']);
  const output = path.join(temporary, 'result.mp4');
  fs.writeFileSync(output, new Uint8Array(await blob.arrayBuffer()));
  const info = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration:stream=codec_type', '-of', 'json', output]));
  assert(Number(info.format.duration) >= 5.9);
  assert(info.streams.some(track => track.codec_type === 'video'));
  assert(info.streams.some(track => track.codec_type === 'audio'));
  execFileSync('ffmpeg', ['-v', 'error', '-xerror', '-i', output, '-f', 'null', '-']);
  console.log('HLS fixture: both segments downloaded; complete video and audio decoded.');
} finally {
  globalThis.fetch = originalFetch;
  globalThis.location = originalLocation;
  fs.rmSync(temporary, { recursive: true, force: true });
}
