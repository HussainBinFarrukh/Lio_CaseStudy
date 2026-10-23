'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import * as api from '@/lib/api';
import { useCommodityGroups } from '@/lib/hooks/useCommodityGroups';
import { Alert, Button, Input } from '@/components/base';
import { formatCurrency, formatDateTime } from '@/lib/utils';

const EMPTY: api.BookingRuleInput = {
  name: '',
  description: '',
  include_terms: [],
  exclude_terms: [],
  max_annual_amount: null,
  target_commodity_group_id: 0,
  active: true,
};

const splitTerms = (text: string) =>
  text
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean);

/** Admin management of the organization's booking rules (spec 003, US6/US7). */
export function BookingRulesPanel() {
  const queryClient = useQueryClient();
  const { data: groups } = useCommodityGroups();
  const rules = useQuery({ queryKey: ['booking-rules'], queryFn: () => api.bookingRules.list() });
  const events = useQuery({
    queryKey: ['booking-rule-events'],
    queryFn: () => api.bookingRules.events(),
  });
  const [editing, setEditing] = useState<{ id: string | null; input: api.BookingRuleInput } | null>(null);
  const [includeText, setIncludeText] = useState('');
  const [excludeText, setExcludeText] = useState('');
  const [message, setMessage] = useState<{ kind: 'success' | 'warning' | 'error'; text: string } | null>(null);
  const [checkResult, setCheckResult] = useState<api.MisbookedRequest[] | null>(null);
  const [selected, setSelected] = useState<string[]>([]);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['booking-rules'] });
    queryClient.invalidateQueries({ queryKey: ['booking-rule-events'] });
    // Rule changes apply to requests classified afterwards.
    queryClient.invalidateQueries({ queryKey: ['classification'] });
  };

  const save = useMutation({
    mutationFn: async () => {
      if (!editing) throw new Error('Nothing to save');
      const input = {
        ...editing.input,
        include_terms: splitTerms(includeText),
        exclude_terms: splitTerms(excludeText),
      };
      return editing.id
        ? api.bookingRules.update(editing.id, input)
        : api.bookingRules.create(input);
    },
    onSuccess: (result) => {
      setEditing(null);
      setMessage(
        result.warnings.length
          ? { kind: 'warning', text: `Saved. ${result.warnings.join(' ')}` }
          : { kind: 'success', text: `Rule '${result.rule.name}' saved.` }
      );
      refresh();
    },
    onError: (err) => setMessage({ kind: 'error', text: err instanceof Error ? err.message : 'Failed to save rule' }),
  });

  const remove = useMutation({
    mutationFn: (rule: api.BookingRule) => api.bookingRules.remove(rule.id),
    onSuccess: () => {
      setMessage({ kind: 'success', text: 'Rule deleted.' });
      refresh();
    },
    onError: (err) => setMessage({ kind: 'error', text: err instanceof Error ? err.message : 'Failed to delete rule' }),
  });

  const runCheck = async () => {
    setMessage(null);
    try {
      const found = await api.bookingRules.check();
      setCheckResult(found);
      setSelected(found.map((f) => f.request_id));
    } catch (err) {
      setMessage({ kind: 'error', text: err instanceof Error ? err.message : 'Check failed' });
    }
  };

  const rebook = useMutation({
    mutationFn: () => api.bookingRules.rebook(selected),
    onSuccess: (result) => {
      setMessage({ kind: 'success', text: `${result.rebooked} request(s) re-booked.` });
      setCheckResult(null);
      setSelected([]);
    },
    onError: (err) => setMessage({ kind: 'error', text: err instanceof Error ? err.message : 'Re-booking failed' }),
  });

  const startEdit = (rule: api.BookingRule | null) => {
    setMessage(null);
    const input = rule
      ? {
          name: rule.name,
          description: rule.description,
          include_terms: rule.include_terms,
          exclude_terms: rule.exclude_terms,
          max_annual_amount: rule.max_annual_amount,
          target_commodity_group_id: rule.target_commodity_group_id,
          active: rule.active,
        }
      : EMPTY;
    setEditing({ id: rule?.id ?? null, input });
    setIncludeText(input.include_terms.join(', '));
    setExcludeText(input.exclude_terms.join(', '));
  };

  const groupName = (id: number) => groups?.find((g) => g.id === id)?.name ?? `group ${id}`;

  return (
    <div className="space-y-6">
      {message && <Alert variant={message.kind}>{message.text}</Alert>}

      <div className="lio-card p-6">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
          <div>
            <h2 className="text-xl font-semibold tracking-tight text-ink">Booking rules</h2>
            <p className="text-sm text-ink/55 mt-1">
              Items matching a rule are always booked under its commodity group. Terms are matched
              as words; end a term with * to include word endings (e.g. &ldquo;cable tie*&rdquo;).
              Changes apply to requests classified afterwards.
            </p>
          </div>
          <Button size="sm" onClick={() => startEdit(null)}>+ Add rule</Button>
        </div>

        {editing && (
          <div className="rounded-xl border border-line p-4 mb-4 space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Input
                label="Name *"
                value={editing.input.name}
                onChange={(e) => setEditing({ ...editing, input: { ...editing.input, name: e.target.value } })}
              />
              <div>
                <label className="block text-sm font-medium text-ink/70 mb-1.5">Book under *</label>
                <select
                  value={editing.input.target_commodity_group_id || ''}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      input: { ...editing.input, target_commodity_group_id: Number(e.target.value) },
                    })
                  }
                  className="w-full h-11 px-3.5 border border-line rounded-xl text-sm text-ink bg-white"
                >
                  <option value="">Select a commodity group</option>
                  {groups?.map((g) => (
                    <option key={g.id} value={g.id}>{g.id} - {g.category} - {g.name}</option>
                  ))}
                </select>
              </div>
            </div>
            <Input
              label="Description"
              value={editing.input.description}
              onChange={(e) =>
                setEditing({ ...editing, input: { ...editing.input, description: e.target.value } })
              }
            />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Input
                label="Matches (comma-separated) *"
                value={includeText}
                onChange={(e) => setIncludeText(e.target.value)}
                placeholder="cable tie*, zip tie*"
              />
              <Input
                label="Never matches (comma-separated)"
                value={excludeText}
                onChange={(e) => setExcludeText(e.target.value)}
                placeholder="patch cable"
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 items-end">
              <Input
                label="Only below a yearly total of ($)"
                type="number"
                step="0.01"
                min="0"
                value={editing.input.max_annual_amount ?? ''}
                onChange={(e) =>
                  setEditing({
                    ...editing,
                    input: {
                      ...editing.input,
                      max_annual_amount: e.target.value ? Number(e.target.value) : null,
                    },
                  })
                }
              />
              <label className="flex items-center gap-2 text-sm text-ink h-11">
                <input
                  type="checkbox"
                  checked={editing.input.active}
                  onChange={(e) =>
                    setEditing({ ...editing, input: { ...editing.input, active: e.target.checked } })
                  }
                  className="h-4 w-4 accent-accent-deep"
                />
                Active
              </label>
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={() => save.mutate()} loading={save.isPending}>
                Save rule
              </Button>
              <Button size="sm" variant="outline" onClick={() => setEditing(null)}>Cancel</Button>
            </div>
          </div>
        )}

        <div className="divide-y divide-line rounded-xl border border-line">
          {(rules.data || []).length === 0 && (
            <p className="p-4 text-sm text-ink/50">No booking rules — commodity groups are proposed by the system.</p>
          )}
          {(rules.data || []).map((rule) => (
            <div key={rule.id} className="p-4 flex flex-col md:flex-row md:items-start gap-3">
              <div className="flex-1 min-w-0 text-sm">
                <p className="font-medium text-ink">
                  {rule.name} → {rule.target_commodity_group_name ?? groupName(rule.target_commodity_group_id)} (
                  {rule.target_commodity_group_id})
                  {!rule.active && <span className="ml-2 text-xs text-ink/45">inactive</span>}
                </p>
                {rule.description && <p className="text-ink/60">{rule.description}</p>}
                <p className="text-xs text-ink/55 mt-1">
                  Matches: {rule.include_terms.join(', ')}
                  {rule.exclude_terms.length > 0 && ` · never: ${rule.exclude_terms.join(', ')}`}
                  {rule.max_annual_amount !== null &&
                    ` · only below ${formatCurrency(rule.max_annual_amount)} a year`}
                </p>
              </div>
              <div className="flex gap-2 shrink-0">
                <Button size="sm" variant="outline" onClick={() => startEdit(rule)}>Edit</Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="text-red-600 border-red-300 hover:bg-red-50"
                  onClick={() => confirm(`Delete rule '${rule.name}'?`) && remove.mutate(rule)}
                >
                  Delete
                </Button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="lio-card p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold tracking-tight text-ink">Existing requests</h2>
            <p className="text-sm text-ink/55">
              Find requests booked differently from the current rules. Nothing changes until you re-book.
            </p>
          </div>
          <Button size="sm" variant="outline" onClick={runCheck}>Check requests</Button>
        </div>
        {checkResult && (
          <div className="mt-4">
            {checkResult.length === 0 ? (
              <p className="text-sm text-ink/55">All requests match the current rules.</p>
            ) : (
              <>
                <ul className="divide-y divide-line rounded-xl border border-line mb-3">
                  {checkResult.map((item) => (
                    <li key={item.request_id} className="p-3 flex items-start gap-3 text-sm">
                      <input
                        type="checkbox"
                        className="mt-1 h-4 w-4 accent-accent-deep"
                        checked={selected.includes(item.request_id)}
                        onChange={(e) =>
                          setSelected((s) =>
                            e.target.checked ? [...s, item.request_id] : s.filter((id) => id !== item.request_id)
                          )
                        }
                      />
                      <div>
                        <p className="text-ink">{item.title}</p>
                        <p className="text-xs text-ink/55">
                          Booked under {item.current_group_id ?? '—'}; rule &lsquo;{item.rule_name}&rsquo;
                          requires {groupName(item.mandated_group_id)} ({item.mandated_group_id}) — line
                          &ldquo;{item.deciding_line}&rdquo;
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
                <Button
                  size="sm"
                  onClick={() => rebook.mutate()}
                  disabled={selected.length === 0}
                  loading={rebook.isPending}
                >
                  Re-book {selected.length} selected
                </Button>
              </>
            )}
          </div>
        )}
      </div>

      <div className="lio-card p-6">
        <h2 className="text-lg font-semibold tracking-tight text-ink mb-3">Rule history</h2>
        <ul className="space-y-2 text-sm">
          {(events.data || []).slice(0, 20).map((event) => (
            <li key={event.id} className="flex justify-between gap-4">
              <span className="text-ink">{event.summary}</span>
              <span className="text-xs text-ink/45 shrink-0">{formatDateTime(event.created_at)}</span>
            </li>
          ))}
          {(events.data || []).length === 0 && <li className="text-ink/50">No changes yet.</li>}
        </ul>
      </div>
    </div>
  );
}
