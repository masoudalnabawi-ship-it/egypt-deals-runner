export interface WatchTarget {
  targetPrice: number | null;
  targetDiscount: number | null;
}

export interface WatchPrice {
  current: number;
  original: number | null;
}

export function evaluateWatch(
  target: WatchTarget,
  price: WatchPrice
) {
  const current = Number(price.current);
  const original = Number(price.original);

  if (!Number.isFinite(current) || current <= 0) {
    return { matched: false, discount: null };
  }

  const discount =
    Number.isFinite(original) && original > current
      ? ((original - current) / original) * 100
      : null;

  const priceMatched =
    target.targetPrice !== null &&
    Number.isFinite(target.targetPrice) &&
    target.targetPrice > 0 &&
    current <= target.targetPrice;

  const discountMatched =
    target.targetDiscount !== null &&
    Number.isFinite(target.targetDiscount) &&
    target.targetDiscount > 0 &&
    target.targetDiscount <= 100 &&
    discount !== null &&
    discount >= target.targetDiscount;

  return {
    matched: priceMatched || discountMatched,
    discount,
    priceMatched,
    discountMatched
  };
}
