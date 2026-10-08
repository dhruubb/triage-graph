// Small API client. Triage runs stream Server-Sent Events over a POST, so we read the
// response body ourselves instead of using EventSource (which only supports GET).

async function errorMessage(res) {
  try {
    const body = await res.json()
    const d = body.detail
    if (typeof d === 'string') return d
    if (Array.isArray(d)) return d.map((e) => e.msg).join('; ')
    return JSON.stringify(d)
  } catch {
    return `${res.status} ${res.statusText}`
  }
}

export async function getJSON(url) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(await errorMessage(res))
  return res.json()
}

export async function streamSSE(url, body, onEvent, signal) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) throw new Error(await errorMessage(res))

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep
    while ((sep = buffer.indexOf('\n\n')) >= 0) {
      const raw = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      let event = 'message'
      let data = ''
      for (const line of raw.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7)
        else if (line.startsWith('data: ')) data += line.slice(6)
      }
      if (data) onEvent(event, JSON.parse(data))
    }
  }
}
