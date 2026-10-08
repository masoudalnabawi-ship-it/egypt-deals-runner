import type { DealRow } from "./types";
import { titleSimilarity } from "./identity";

export interface DuplicateGuardResult {
  duplicate: boolean;
  similarity: number;
  matched_deal_key: string;
  reason: string;
}

export interface DealQualityBand {
  code: "elite" | "strong" | "good" | "verified";
  label: string;
}

function priceOf(row: DealRow): number {
  const effective =
    Number(row.effective_price || 0);

  if (effective > 0) {
    return effective;
  }

  return Math.max(
    0,
    Number(row.current_price || 0),
  );
}

export function nearDuplicateGuard(
  current: DealRow,
  recent: DealRow[],
): DuplicateGuardResult {
  let best: DuplicateGuardResult = {
    duplicate: false,
    similarity: 0,
    matched_deal_key: "",
    reason: "no_match",
  };

  for (const previous of recent) {
    if (
      !previous ||
      previous.deal_key === current.deal_key
    ) {
      continue;
    }

    const similarity =
      titleSimilarity(
        String(current.title || ""),
        String(previous.title || ""),
      );

    if (similarity < 0.90) {
      continue;
    }

    const currentPrice =
      priceOf(current);

    const previousPrice =
      priceOf(previous);

    const materiallyCheaper =
      previousPrice > 0 &&
      currentPrice > 0 &&
      currentPrice <=
        previousPrice * 0.97;

    const materiallyDeeper =
      Number(current.real_discount || 0) >=
      Number(previous.real_discount || 0) + 4;

    const materiallyStronger =
      Number(current.score || 0) >=
        Number(previous.score || 0) + 8 &&
      Number(current.confidence || 0) >=
        Number(previous.confidence || 0);

    const duplicate =
      !(
        materiallyCheaper ||
        materiallyDeeper ||
        materiallyStronger
      );

    if (similarity > best.similarity) {
      best = {
        duplicate,
        similarity:
          Math.round(similarity * 1000) / 1000,
        matched_deal_key:
          String(previous.deal_key || ""),
        reason:
          duplicate
            ? "recent_similar_not_better"
            : materiallyCheaper
              ? "allowed_materially_cheaper"
              : materiallyDeeper
                ? "allowed_deeper_discount"
                : "allowed_stronger_quality",
      };
    }
  }

  return best;
}

export function dealQualityBand(
  row: DealRow,
): DealQualityBand {
  const score =
    Number(row.score || 0);

  const confidence =
    Number(row.confidence || 0);

  const discount =
    Number(row.real_discount || 0);

  if (
    row.store === "amazon" &&
    row.lane === "ultra" &&
    discount >= 75 &&
    confidence >= 0.82 &&
    score >= 88
  ) {
    return {
      code: "elite",
      label: "ممتازة جدًا",
    };
  }

  if (
    score >= 82 &&
    confidence >= 0.76
  ) {
    return {
      code: "strong",
      label: "قوية",
    };
  }

  if (
    score >= 70 &&
    confidence >= 0.65
  ) {
    return {
      code: "good",
      label: "جيدة",
    };
  }

  return {
    code: "verified",
    label: "موثقة",
  };
}
