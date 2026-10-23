'use client';

import { useEffect, useState } from 'react';
import * as api from '@/lib/api';
import type { ArticlePage } from '@/lib/api';
import { useQuery } from '@tanstack/react-query';
import { Input, Alert } from '@/components/base';
import { formatCurrency } from '@/lib/utils';

const PAGE_SIZE = 25;

function formatPrice(value: string, currency: string): string {
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  try {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(n);
  } catch {
    return `${currency} ${n.toFixed(2)}`;
  }
}

function formatQuantity(value: string): string {
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  // Drop trailing zeros: 1.000 -> "1", 1.500 -> "1.5"
  return String(Number(n.toFixed(3)));
}

const USAGE_PERIODS = [
  { days: 30, label: 'Last 30 days' },
  { days: 90, label: 'Last 90 days' },
  { days: 365, label: 'Last 12 months' },
];

const isoDaysAgo = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() - days + 1);
  return d.toISOString().slice(0, 10);
};

// How often requests use the negotiated catalog prices (spec 002, US6). Admins only.
function AgreementUsage() {
  const [days, setDays] = useState(30);
  const { data: org } = useQuery({
    queryKey: ['organization', 'me'],
    queryFn: () => api.organizations.getMine(),
    staleTime: 5 * 60 * 1000,
  });
  const isAdmin = org?.role === 'admin';
  const { data: usage } = useQuery({
    queryKey: ['catalog-usage', days],
    queryFn: () => api.catalog.usage({ from: isoDaysAgo(days) }),
    enabled: isAdmin,
  });
  if (!isAdmin || !usage) return null;

  const stats = [
    {
      label: 'Lines using agreements',
      value: `${usage.linkedLineCount} of ${usage.lineCount} (${Math.round(usage.linkedShare * 100)}%)`,
    },
    { label: 'Realised savings', value: formatCurrency(usage.realisedSavings) },
    { label: 'Missed savings', value: formatCurrency(usage.missedSavings) },
    { label: 'Requests', value: usage.requestCount.toLocaleString('en-US') },
  ];
  return (
    <div className="lio-card p-6 mb-6">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-ink">Agreement usage</h2>
          <p className="text-sm text-ink/55">
            Order lines that use negotiated catalog prices, and what unused agreements would have saved
          </p>
        </div>
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="h-9 px-3 border border-line rounded-xl text-sm text-ink bg-white"
        >
          {USAGE_PERIODS.map((p) => (
            <option key={p.days} value={p.days}>{p.label}</option>
          ))}
        </select>
      </div>
      <dl className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {stats.map((s) => (
          <div key={s.label}>
            <dt className="text-xs font-medium text-ink/45">{s.label}</dt>
            <dd className="text-xl font-semibold tracking-tight text-ink mt-1">{s.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export default function ArticlesPage() {
  const [page, setPage] = useState<ArticlePage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [offset, setOffset] = useState(0);

  // Debounce the search box, and reset to the first page whenever it changes.
  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedSearch(search);
      setOffset(0);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const result = await api.articles.list({
          search: debouncedSearch || undefined,
          limit: PAGE_SIZE,
          offset,
        });
        if (!cancelled) {
          setPage(result);
          setError('');
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load articles');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [debouncedSearch, offset]);

  const total = page?.total ?? 0;
  const items = page?.items ?? [];
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE_SIZE, total);
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;

  return (
    <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-semibold tracking-tight text-ink">Articles</h1>
        <p className="text-ink/55 mt-1.5">
          Your article catalog · {total.toLocaleString('en-US')} articles
        </p>
      </div>

      {error && <Alert variant="error" className="mb-6">{error}</Alert>}

      <AgreementUsage />

      {/* Filters */}
      <div className="lio-card p-4 mb-6">
        <div className="flex flex-col md:flex-row gap-4 md:items-center">
          <div className="flex-1">
            <Input
              placeholder="Search by description or article number…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <span className="text-sm text-ink/45 md:w-40 md:text-right">
            {total === 0 ? 'No results' : `${from}–${to} of ${total.toLocaleString('en-US')}`}
          </span>
        </div>
      </div>

      {/* Table */}
      <div className="lio-card overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center h-64">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-accent-deep"></div>
          </div>
        ) : items.length === 0 ? (
          <div className="p-12 text-center text-ink/50">No articles found</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-ink-800/[0.03] border-b border-line">
                <tr>
                  {['Article', 'Description', 'Supplier', 'Unit price', 'Unit', 'Qty'].map((h) => (
                    <th
                      key={h}
                      className="px-6 py-3 text-left text-xs font-medium text-ink/45 uppercase tracking-wider"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {items.map((a) => (
                  <tr key={a.id} className="hover:bg-ink-800/[0.02]">
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-mono text-ink/70">
                      {a.article_number}
                    </td>
                    <td className="px-6 py-4 text-sm text-ink max-w-md">{a.description}</td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="inline-flex px-2.5 py-1 text-xs font-medium rounded-full bg-accent-soft/30 text-accent-deep">
                        {a.supplier_name || '—'}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-ink/80 tabular-nums">
                      {formatPrice(a.unit_price, a.currency)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-ink/60">{a.unit}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-ink/60 tabular-nums">
                      {formatQuantity(a.quantity)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {items.length > 0 && (
          <div className="flex items-center justify-between px-6 py-4 border-t border-line">
            <span className="text-sm text-ink/45">
              Showing {from}–{to} of {total.toLocaleString('en-US')}
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                disabled={!hasPrev}
                className="px-3.5 py-2 rounded-full text-sm font-medium border border-line text-ink/70 hover:bg-ink-800/[0.03] disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Previous
              </button>
              <button
                onClick={() => setOffset(offset + PAGE_SIZE)}
                disabled={!hasNext}
                className="px-3.5 py-2 rounded-full text-sm font-medium border border-line text-ink/70 hover:bg-ink-800/[0.03] disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
