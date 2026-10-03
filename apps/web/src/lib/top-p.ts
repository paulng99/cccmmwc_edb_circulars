/**
 * Top P 設定：空字串／null／undefined 視為有效（未設定）；
 * 數字必須在 0 至 1（含兩端）。不自動修正輸入內容。
 */
export function isValidTopP(raw: unknown): boolean {
  if (raw === "" || raw === null || raw === undefined) return true;
  if (typeof raw === "boolean") return false;
  if (typeof raw !== "number") return false;
  if (Number.isNaN(raw)) return false;
  return raw >= 0 && raw <= 1;
}
