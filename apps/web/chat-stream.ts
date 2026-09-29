/** Decode SSE across arbitrary network/UTF-8 boundaries. A clean EOF is not a completed answer. */
export async function readChatStream(response: Response, onDelta: (text: string) => void) {
  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.detail || '回答请求未完成');
  }
  if (!response.headers.get('content-type')?.includes('text/event-stream')) {
    return (await response.json()).answer as string;
  }
  if (!response.body) throw new Error('回答连接未建立');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let boundary: RegExpExecArray | null;
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const lines = frame.split(/\r?\n/);
        const event = lines
          .find((line) => line.startsWith('event:'))
          ?.slice(6)
          .trim();
        const data = lines
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart())
          .join('\n');
        if (!data) continue;
        const payload = JSON.parse(data);
        if (event === 'delta' && typeof payload.text === 'string') onDelta(payload.text);
        if (event === 'error') throw new Error(payload.message || '回答中断');
        if (event === 'done' && typeof payload.answer === 'string') return payload.answer;
      }
      if (done) throw new Error('回答连接中断，已保留收到的内容，可重新发送问题。');
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
