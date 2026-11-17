export const MAX_INTERACTIVE_HTML_BYTES = 10 * 1024 * 1024

export async function readInteractiveHtmlFile(file: File): Promise<string> {
  if (!/\.html?$/i.test(file.name)) throw new Error('Choose an .html or .htm file.')
  if (file.size === 0 || file.size > MAX_INTERACTIVE_HTML_BYTES) {
    throw new Error('Choose a non-empty HTML file no larger than 10 MiB.')
  }
  try {
    const html = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer())
    if (!html.trim() || html.includes('\0')) throw new Error()
    return html
  } catch {
    throw new Error('The HTML file must contain valid UTF-8 text without null bytes.')
  }
}

export function interactiveHtmlDocument(html: string): string {
  const policy = "default-src 'none'; script-src 'unsafe-inline' https://unpkg.com; style-src 'unsafe-inline' https://fonts.googleapis.com; img-src data: blob:; font-src data: https://fonts.gstatic.com; media-src data: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'; frame-src 'self'"
  return `<!doctype html><meta http-equiv="Content-Security-Policy" content="${policy}">${html}`
}
