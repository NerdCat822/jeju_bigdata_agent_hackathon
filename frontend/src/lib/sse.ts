/** 서버가 보내는 SSE(text/event-stream) 조각을 이벤트로 풀어요. 조각이 이벤트 중간에서 끊겨 와도 돼요. */

export interface SseEvent {
  event: string
  data: unknown
}

export class SseParser {
  private buffer = ''

  push(chunk: string): SseEvent[] {
    this.buffer += chunk.replace(/\r\n/g, '\n')
    const out: SseEvent[] = []
    let cut: number
    while ((cut = this.buffer.indexOf('\n\n')) >= 0) {
      const block = this.buffer.slice(0, cut)
      this.buffer = this.buffer.slice(cut + 2)
      const parsed = parseBlock(block)
      if (parsed) out.push(parsed)
    }
    return out
  }
}

function parseBlock(block: string): SseEvent | null {
  let event = 'message'
  const data: string[] = []
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
  }
  if (!data.length) return null
  try {
    return { event, data: JSON.parse(data.join('\n')) }
  } catch {
    return null // 깨진 조각은 버려요. 나머지 흐름은 이어 가요.
  }
}
