const WALLET_CODE = "billing_wallet_not_activated";

function detailRecord(data: unknown): Record<string, unknown> | null {
  if (typeof data !== "object" || data === null) return null;
  const record = data as Record<string, unknown>;
  const detail = record.detail;
  if (typeof detail === "object" && detail !== null) {
    return detail as Record<string, unknown>;
  }
  return record;
}

/** Billing page for an inactive Vectoree wallet, or null for any other error. */
export function readWalletBillingUrl(data: unknown): string | null {
  const detail = detailRecord(data);
  if (!detail || detail.code !== WALLET_CODE) return null;
  if (typeof detail.billing_url !== "string") return null;
  try {
    const url = new URL(detail.billing_url);
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    return detail.billing_url;
  } catch {
    return null;
  }
}
