// The attribute catalog shared by the hard constraints (C4) and the concept
// cards. The backend compares a concept's attribute to a constraint's value
// as an EXACT string, so both sides must use the same name and the same
// value string (the pickers below guarantee that).
export const ATTRIBUTE_NAMES = ["material", "price_band", "product_type"] as const;

export type AttributeName = (typeof ATTRIBUTE_NAMES)[number];

export const ATTRIBUTE_LABELS: Record<AttributeName, string> = {
  material: "Material",
  price_band: "Price band",
  product_type: "Product type",
};

/** Drop the empty entries: the backend treats a missing attribute as a failed
 *  hard-constraint check, so an untouched field must not be sent. */
export function cleanAttributes(
  attributes: Record<string, string>
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(attributes)) {
    const trimmed = value.trim();
    if (trimmed !== "") out[key] = trimmed;
  }
  return out;
}
