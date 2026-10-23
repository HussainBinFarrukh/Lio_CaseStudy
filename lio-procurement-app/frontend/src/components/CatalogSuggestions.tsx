'use client';

import type { ArticleSuggestion } from '@/lib/api';
import { formatCurrency } from '@/lib/utils';

interface CatalogSuggestionsProps {
  suggestions: ArticleSuggestion[];
  onApply: (suggestion: ArticleSuggestion) => void;
  onDismiss: (suggestion: ArticleSuggestion) => void;
}

// Saving vs. extra cost for the line's quantity — a pricier article is never a "saving".
function PriceEffect({ suggestion }: { suggestion: ArticleSuggestion }) {
  if (!suggestion.comparable || suggestion.lineEffect === null) {
    return <span className="text-ink/55">Per {suggestion.unit} — not comparable with this line</span>;
  }
  if (suggestion.lineEffect < 0) {
    return (
      <span className="font-semibold text-green-700">
        Save {formatCurrency(-suggestion.lineEffect)}
      </span>
    );
  }
  if (suggestion.lineEffect > 0) {
    return (
      <span className="text-ink/70">{formatCurrency(suggestion.lineEffect)} more expensive</span>
    );
  }
  return <span className="text-ink/70">Same price</span>;
}

/** Negotiated catalog articles matching one order line (spec 002, US1). */
export function CatalogSuggestions({ suggestions, onApply, onDismiss }: CatalogSuggestionsProps) {
  if (suggestions.length === 0) return null;
  return (
    <div className="mt-3 rounded-lg border border-accent/40 bg-accent-soft/10 p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-accent-deep mb-2">
        Catalog agreements
      </p>
      <ul className="space-y-2">
        {suggestions.map((s) => (
          <li
            key={s.articleId}
            className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="min-w-0 text-sm">
              <p className="text-ink truncate">
                <span className="font-mono text-xs text-ink/55 mr-2">{s.articleNumber}</span>
                {s.description}
              </p>
              <p className="text-xs text-ink/55">
                {s.supplierName}
                {s.fromVendor && ' · your vendor'} · {formatCurrency(s.unitPrice, s.currency)} /{' '}
                {s.unit} · <PriceEffect suggestion={s} />
                {s.belowMinQuantity && (
                  <span className="text-amber-700"> · minimum order {s.minQuantity}</span>
                )}
              </p>
            </div>
            <div className="flex shrink-0 gap-2">
              <button
                type="button"
                onClick={() => onApply(s)}
                className="rounded-full bg-ink px-3 py-1 text-xs font-medium text-white hover:bg-ink-700"
              >
                Use this
              </button>
              <button
                type="button"
                onClick={() => onDismiss(s)}
                className="rounded-full px-3 py-1 text-xs text-ink/60 hover:bg-ink-800/[0.06]"
              >
                Dismiss
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
