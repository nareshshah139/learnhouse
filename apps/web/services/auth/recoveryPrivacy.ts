let privateRecoveryDocument = false

export function markDocumentRecoverySensitive() { privateRecoveryDocument = true }
export function isRecoveryPrivate() { return privateRecoveryDocument }

export function isRecoveryPath(value?: string): boolean {
  return !!value && /(?:^|\/)recover(?:[/?#]|$)|\/api\/recovery(?:[/?#]|$)|\/recovery-links(?:[/?#]|$)/.test(value)
}

export function isRecoveryEvent(event: { request?: { url?: string }; transaction?: string }): boolean {
  return isRecoveryPrivate() || isRecoveryPath(event.request?.url) || isRecoveryPath(event.transaction)
}
