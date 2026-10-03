/** Top K settings must be integers in [1, 20]. Does not coerce the input. */
export function isValidTopK(value: unknown): boolean {
  return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 20;
}
