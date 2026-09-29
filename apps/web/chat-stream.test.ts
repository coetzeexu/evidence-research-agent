import { expect, it } from 'vitest';
import { readChatStream } from './chat-stream';
it('delivers Chinese deltas before completion across byte and SSE boundaries', async () => {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const response = new Response(
    new ReadableStream<Uint8Array>({
      start(c) {
        controller = c;
      },
    }),
    { headers: { 'content-type': 'text/event-stream' } },
  );
  const chunks: string[] = [];
  const result = readChatStream(response, (text) => chunks.push(text));
  const encode = new TextEncoder();
  const bytes = encode.encode('event: delta\r\ndata: {"text":"行情"}\r\n\r\n');
  for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(chunks).toEqual(['行情']);
  controller.enqueue(encode.encode('event: done\ndata: {"answer":"行情已完成"}\n\n'));
  controller.close();
  expect(await result).toBe('行情已完成');
});
it('does not call a truncated stream complete and retains earlier deltas on server failure', async () => {
  const texts: string[] = [];
  await expect(
    readChatStream(
      new Response(
        'event: delta\ndata: {"text":"已收到"}\n\nevent: error\ndata: {"message":"连接异常"}\n\n',
        { headers: { 'content-type': 'text/event-stream' } },
      ),
      (t) => texts.push(t),
    ),
  ).rejects.toThrow('连接异常');
  expect(texts).toEqual(['已收到']);
  await expect(
    readChatStream(
      new Response('event: delta\ndata: {"text":"半句"}\n\n', {
        headers: { 'content-type': 'text/event-stream' },
      }),
      () => {},
    ),
  ).rejects.toThrow('连接中断');
});
