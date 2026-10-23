'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useMutation } from '@tanstack/react-query';
import * as api from '@/lib/api';
import { useCommodityGroups } from '@/lib/hooks/useCommodityGroups';
import { Button, Input, Alert, Loader } from '@/components/base';
import { cn, formatCurrency } from '@/lib/utils';

interface OrderLine {
  positionDescription: string;
  unitPrice: number;
  amount: number;
  unit: string;
  discountPercent: number;
  totalPrice: number;
}

// Document-level amounts that are not order lines (from the quote's totals block).
interface Extras {
  shipping: number;
  tax: number;
  fees: number;
}

const NO_EXTRAS: Extras = { shipping: 0, tax: 0, fees: 0 };
const PDF_TYPES = ['application/pdf', 'application/x-pdf'];

// Browsers report an empty/generic type for some PDFs and names may be ".Pdf";
// the server verifies the content either way.
const looksLikePdf = (file: File) =>
  PDF_TYPES.includes(file.type) || file.name.toLowerCase().endsWith('.pdf');

const round2 = (n: number) => Math.round(n * 100) / 100;
const lineTotal = (line: Pick<OrderLine, 'amount' | 'unitPrice' | 'discountPercent'>) =>
  round2(line.amount * line.unitPrice * (1 - (line.discountPercent || 0) / 100));
const grandTotal = (lines: OrderLine[], extras: Extras) =>
  round2(lines.reduce((sum, l) => sum + l.totalPrice, 0) + extras.shipping + extras.tax + extras.fees);

// Informational notes for data the quote simply doesn't contain (not errors).
const NOT_IN_DOCUMENT_NOTES: Record<string, string> = {
  vatId: 'No tax ID found in the quote.',
  vendorName: 'No vendor name found in the quote.',
  quoteNumber: 'No quote number printed on the quote.',
  quoteDate: 'No quote date printed on the quote.',
  validUntil: 'No validity date printed on the quote.',
  orderLines: 'No billable lines were identified in this quote.',
};

function extractionNotes(data: api.ExtractedVendorData): string[] {
  const notes = Object.entries(data.fieldStatus || {})
    .filter(([field, status]) => status === 'not_in_document' && NOT_IN_DOCUMENT_NOTES[field])
    .map(([field]) => NOT_IN_DOCUMENT_NOTES[field]);
  const alternatives = (data.excludedPositions || []).filter((p) => p.reason === 'alternative');
  if (alternatives.length > 0) {
    const names = alternatives.map((p) => p.itemNo || p.description).join(', ');
    notes.push(
      `${alternatives.length} alternative item${alternatives.length === 1 ? ' was' : 's were'} not added: ${names}.`
    );
  }
  return notes;
}

export default function NewRequestPage() {
  const router = useRouter();
  const { data: commodityGroups } = useCommodityGroups();

  // Form state
  const [requestorName, setRequestorName] = useState('');
  const [title, setTitle] = useState('');
  const [vendorName, setVendorName] = useState('');
  const [vatId, setVatId] = useState('');
  const [department, setDepartment] = useState('');
  const [commodityGroupId, setCommodityGroupId] = useState<number | null>(null);
  const [orderLines, setOrderLines] = useState<OrderLine[]>([]);
  const [extras, setExtras] = useState<Extras>(NO_EXTRAS);
  // Grand total: the printed one after extraction, recalculated on every edit.
  const [totalCost, setTotalCost] = useState<number>(0);
  const [currency, setCurrency] = useState('USD');
  const [quoteNumber, setQuoteNumber] = useState('');
  const [quoteDate, setQuoteDate] = useState('');
  const [validUntil, setValidUntil] = useState('');

  // UI state
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [warning, setWarning] = useState('');
  const [notes, setNotes] = useState<string[]>([]);
  const [findings, setFindings] = useState<api.ReconciliationFinding[]>([]);
  const [extracting, setExtracting] = useState(false);

  // PDF parsing mutation
  const parsePDFMutation = useMutation({
    mutationFn: async (file: File) => {
      const result = await api.pdf.parse(file);
      if (!result.text.trim()) {
        throw new Error(
          "This PDF contains no readable text (it may be a scan). Please fill in the form manually."
        );
      }
      return result.text;
    },
  });

  const applyExtraction = (extracted: api.ExtractedVendorData) => {
    const lines: OrderLine[] = (extracted.orderLines || []).map((line) => ({
      ...line,
      discountPercent: line.discountPercent || 0,
    }));
    const totals = extracted.totals;
    setTitle(extracted.title || '');
    setVendorName(extracted.vendorName || '');
    setVatId(extracted.vatId || '');
    // Department comes from the requester's profile, never from the quote.
    if (extracted.department) setDepartment(extracted.department);
    setOrderLines(lines);
    setExtras({ shipping: totals?.shipping || 0, tax: totals?.tax || 0, fees: totals?.fees || 0 });
    setTotalCost(extracted.totalCost || 0);
    setCurrency(extracted.currency || 'USD');
    setQuoteNumber(extracted.quoteNumber || '');
    setQuoteDate(extracted.quoteDate || '');
    setValidUntil(extracted.validUntil || '');
    if (extracted.commodityGroupId) {
      setCommodityGroupId(extracted.commodityGroupId);
    }
    setFindings(extracted.reconciliation || []);
    setNotes(extractionNotes(extracted));
  };

  // Handle file upload and extraction
  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const uploadedFile = e.target.files?.[0];
    if (!uploadedFile) return;

    if (!looksLikePdf(uploadedFile)) {
      setError('Please upload a PDF file');
      return;
    }

    setFile(uploadedFile);
    setError('');
    setSuccess('');
    setWarning('');
    setNotes([]);
    setFindings([]);
    setExtracting(true);

    try {
      // Step 1: Parse PDF
      const pdfText = await parsePDFMutation.mutateAsync(uploadedFile);

      // Step 2: Extract structured data AND classify commodity group in one AI call
      const extractionResult = await api.extraction.extract(pdfText);

      if (!extractionResult.success || !extractionResult.data) {
        // The server already phrases this for the requester.
        throw new Error(
          extractionResult.error ||
            "We couldn't read this quote automatically. Please fill in the form manually."
        );
      }

      // Step 3: Auto-fill form (including commodity group from extraction)
      applyExtraction(extractionResult.data);

      // Warn only about fields that are in the quote but could not be read.
      if (extractionResult.missingFields && extractionResult.missingFields.length > 0) {
        setWarning(
          `Please fill in: ${extractionResult.missingFields.join(', ')} — these could not be read from the quote.`
        );
      }

      setSuccess('✓ PDF extracted successfully! Review and submit.');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      console.error('Extraction error:', err);
      setError(err instanceof Error ? err.message : 'Failed to extract data from PDF');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } finally {
      setExtracting(false);
    }
  };

  const applyLines = (updated: OrderLine[], nextExtras: Extras = extras) => {
    setOrderLines(updated);
    setTotalCost(grandTotal(updated, nextExtras));
  };

  // Add order line manually
  const addOrderLine = () => {
    applyLines([
      ...orderLines,
      {
        positionDescription: '',
        unitPrice: 0,
        amount: 1,
        unit: '',
        discountPercent: 0,
        totalPrice: 0,
      },
    ]);
  };

  // Update order line
  const updateOrderLine = (index: number, field: keyof OrderLine, value: string | number) => {
    const updated = [...orderLines];
    updated[index] = { ...updated[index], [field]: value };

    // Auto-calculate total price, keeping the line's discount.
    if (field === 'unitPrice' || field === 'amount' || field === 'discountPercent') {
      updated[index].totalPrice = lineTotal(updated[index]);
      // The requester has corrected this line; document totals no longer apply as printed.
      setFindings((current) =>
        current.filter((f) => f.scope !== 'net_total' && f.scope !== 'grand_total' && f.lineIndex !== index)
      );
    }

    applyLines(updated);
  };

  // Remove order line
  const removeOrderLine = (index: number) => {
    // Line positions shift, so drop line-level findings rather than mislabel them.
    setFindings([]);
    applyLines(orderLines.filter((_, i) => i !== index));
  };

  const updateExtra = (field: keyof Extras, value: number) => {
    const next = { ...extras, [field]: value };
    setExtras(next);
    applyLines(orderLines, next);
  };

  // Submit form
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setWarning('');

    // Validation with scroll to top on error
    if (!commodityGroupId) {
      setError('Please select a commodity group');
      window.scrollTo({ top: 0, behavior: 'smooth' });
      return;
    }

    if (orderLines.length === 0) {
      setError('Please add at least one order line');
      window.scrollTo({ top: 0, behavior: 'smooth' });
      return;
    }

    try {
      const created = await api.requests.create({
        requestorName,
        titleShortDescription: title,
        vendorName,
        vatId,
        commodityGroupId: commodityGroupId,
        totalCost,
        department,
        orderLines,
        quoteNumber: quoteNumber || null,
        quoteDate: quoteDate || null,
        validUntil: validUntil || null,
        currency,
        netTotal: round2(orderLines.reduce((sum, l) => sum + l.totalPrice, 0)),
        shippingAmount: extras.shipping || null,
        taxAmount: extras.tax || null,
        feesAmount: extras.fees || null,
      });

      // Attach the original PDF (if one was uploaded) so it shows on the detail page.
      if (file) {
        try {
          await api.requests.uploadDocument(created.id, file);
        } catch {
          // Non-fatal — the request itself was created.
        }
      }

      setSuccess('Request created successfully! Redirecting...');
      window.scrollTo({ top: 0, behavior: 'smooth' });
      setTimeout(() => {
        router.push('/dashboard/requests');
        router.refresh();
      }, 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create request');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  const money = (n: number) => formatCurrency(n, currency || 'USD');
  const linesSum = round2(orderLines.reduce((sum, l) => sum + l.totalPrice, 0));
  const lineFinding = (index: number) =>
    findings.find((f) => f.scope === 'line' && f.lineIndex === index);
  const documentFindings = findings.filter((f) => f.scope !== 'line');

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-semibold tracking-tight text-ink">New Procurement Request</h1>
        <p className="text-gray-600 mt-2">
          Upload a vendor offer PDF or fill in the details manually
        </p>
      </div>

      {error && <Alert variant="error" className="mb-6">{error}</Alert>}
      {warning && <Alert variant="warning" className="mb-6">{warning}</Alert>}
      {success && <Alert variant="success" className="mb-6">{success}</Alert>}
      {notes.length > 0 && (
        <Alert variant="info" className="mb-6">
          <ul className="space-y-1">
            {notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </Alert>
      )}

      <form onSubmit={handleSubmit} className="space-y-8">
        {/* PDF Upload Section */}
        <div className="lio-card p-6">
          <h2 className="text-xl font-semibold tracking-tight text-ink mb-4">Upload Vendor Offer (Optional)</h2>
          <p className="text-sm text-gray-600 mb-4">
            Upload a PDF to automatically extract vendor details and order items
          </p>

          <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center hover:border-accent-deep/50 transition-colors">
            <input
              type="file"
              accept=".pdf,application/pdf"
              onChange={handleFileChange}
              className="hidden"
              id="pdf-upload"
              disabled={extracting}
            />
            <label htmlFor="pdf-upload" className="cursor-pointer">
              {extracting ? (
                <div className="flex flex-col items-center">
                  <Loader size="lg" />
                  <p className="mt-4 text-sm text-gray-600">Extracting data from PDF...</p>
                </div>
              ) : file ? (
                <div>
                  <svg
                    className="mx-auto h-12 w-12 text-green-500"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                  <p className="mt-2 text-sm font-medium text-gray-900">{file.name}</p>
                  <p className="mt-1 text-xs text-gray-500">Click to upload a different file</p>
                </div>
              ) : (
                <div>
                  <svg
                    className="mx-auto h-12 w-12 text-gray-400"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                    />
                  </svg>
                  <p className="mt-2 text-sm text-gray-600">
                    Click to upload or drag and drop
                  </p>
                  <p className="mt-1 text-xs text-gray-500">PDF up to 10MB</p>
                </div>
              )}
            </label>
          </div>
        </div>

        {/* Request Details */}
        <div className="lio-card p-6 space-y-4">
          <h2 className="text-xl font-semibold tracking-tight text-ink mb-4">Request Details</h2>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Input
              label="Requestor Name *"
              value={requestorName}
              onChange={(e) => setRequestorName(e.target.value)}
              required
              placeholder="John Doe"
            />

            <Input
              label="Department"
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              placeholder="IT Department"
            />
          </div>

          <Input
            label="Title / Short Description *"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            placeholder="Adobe Creative Cloud Subscription"
          />
        </div>

        {/* Vendor Information */}
        <div className="lio-card p-6 space-y-4">
          <h2 className="text-xl font-semibold tracking-tight text-ink mb-4">Vendor Information</h2>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Input
              label="Vendor Name *"
              value={vendorName}
              onChange={(e) => setVendorName(e.target.value)}
              required
              placeholder="Adobe Systems"
            />

            <Input
              label="Tax ID"
              value={vatId}
              onChange={(e) => setVatId(e.target.value)}
              placeholder="12-3456789"
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Input
              label="Quote Number"
              value={quoteNumber}
              onChange={(e) => setQuoteNumber(e.target.value)}
              placeholder="Q-2026-001"
            />
            <Input
              label="Quote Date"
              type="date"
              value={quoteDate}
              onChange={(e) => setQuoteDate(e.target.value)}
            />
            <Input
              label="Valid Until"
              type="date"
              value={validUntil}
              onChange={(e) => setValidUntil(e.target.value)}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Commodity Group *
            </label>
            <select
              value={commodityGroupId || ''}
              onChange={(e) => setCommodityGroupId(Number(e.target.value))}
              required
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-gray-900 focus:ring-2 focus:ring-accent-deep/60 focus:border-accent-deep/40"
            >
              <option value="">
                {commodityGroups ? 'Select a commodity group' : 'Loading...'}
              </option>
              {commodityGroups?.map((group) => (
                <option key={group.id} value={group.id}>
                  {group.id} - {group.category} - {group.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Order Lines */}
        <div className="lio-card p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold tracking-tight text-ink">Order Lines *</h2>
            <Button type="button" onClick={addOrderLine} variant="outline" size="sm">
              + Add Line
            </Button>
          </div>

          {orderLines.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              No order lines yet. Add one to get started.
            </div>
          ) : (
            <div className="space-y-4">
              {orderLines.map((line, index) => {
                const finding = lineFinding(index);
                return (
                  <div
                    key={index}
                    className={cn(
                      'border rounded-lg p-4',
                      finding ? 'border-amber-300 bg-amber-50/40' : 'border-gray-200'
                    )}
                  >
                    <div className="flex items-start justify-between mb-4">
                      <h3 className="text-sm font-medium text-gray-700">Line {index + 1}</h3>
                      <button
                        type="button"
                        onClick={() => removeOrderLine(index)}
                        className="text-red-600 hover:text-red-700 text-sm"
                      >
                        Remove
                      </button>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-6 gap-4">
                      <div className="lg:col-span-2">
                        <Input
                          label="Description"
                          value={line.positionDescription}
                          onChange={(e) =>
                            updateOrderLine(index, 'positionDescription', e.target.value)
                          }
                          required
                          placeholder="Item description"
                        />
                      </div>

                      <Input
                        label="Unit Price ($)"
                        type="number"
                        step="0.01"
                        value={line.unitPrice}
                        onChange={(e) =>
                          updateOrderLine(index, 'unitPrice', parseFloat(e.target.value) || 0)
                        }
                        required
                      />

                      <Input
                        label="Amount"
                        type="number"
                        step="0.01"
                        value={line.amount}
                        onChange={(e) =>
                          updateOrderLine(index, 'amount', parseFloat(e.target.value) || 1)
                        }
                        required
                      />

                      <Input
                        label="Discount (%)"
                        type="number"
                        step="0.01"
                        min="0"
                        max="99.99"
                        value={line.discountPercent}
                        onChange={(e) =>
                          updateOrderLine(index, 'discountPercent', parseFloat(e.target.value) || 0)
                        }
                      />

                      <Input
                        label="Unit"
                        value={line.unit}
                        onChange={(e) => updateOrderLine(index, 'unit', e.target.value)}
                        required
                        placeholder="pcs, licenses, etc."
                      />
                    </div>

                    <div className="mt-2 flex items-center justify-between gap-4">
                      <p className="text-sm text-amber-800">
                        {finding &&
                          `Check this line: ${line.amount} × ${money(line.unitPrice)}` +
                            (line.discountPercent ? ` − ${line.discountPercent}%` : '') +
                            ` is ${money(finding.expected)}, but the quote shows ${money(finding.extracted)}.`}
                      </p>
                      <div className="text-right shrink-0">
                        <span className="text-sm text-gray-600">Total: </span>
                        <span className="text-lg font-semibold tracking-tight text-ink">
                          {money(line.totalPrice)}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Total Cost */}
        <div className="bg-accent-soft/20 border-2 border-accent/40 rounded-lg p-6 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div>
              <span className="block text-sm font-medium text-ink/70 mb-1.5">Net (order lines)</span>
              <span className="flex h-11 items-center text-sm font-semibold text-ink">{money(linesSum)}</span>
            </div>
            <Input
              label="Shipping ($)"
              type="number"
              step="0.01"
              min="0"
              value={extras.shipping}
              onChange={(e) => updateExtra('shipping', parseFloat(e.target.value) || 0)}
            />
            <Input
              label="Tax ($)"
              type="number"
              step="0.01"
              min="0"
              value={extras.tax}
              onChange={(e) => updateExtra('tax', parseFloat(e.target.value) || 0)}
            />
            <Input
              label="Fees ($)"
              type="number"
              step="0.01"
              min="0"
              value={extras.fees}
              onChange={(e) => updateExtra('fees', parseFloat(e.target.value) || 0)}
            />
          </div>

          {documentFindings.map((f) => (
            <p key={f.scope} className="text-sm text-amber-800">
              {f.scope === 'net_total'
                ? `The order lines add up to ${money(f.expected)}, but the quote's net total is ${money(f.extracted)}. Please check the lines.`
                : `Net + shipping + tax + fees is ${money(f.expected)}, but the quote's grand total is ${money(f.extracted)}. Please check the amounts.`}
            </p>
          ))}

          <div className="flex items-center justify-between border-t border-accent/30 pt-4">
            <span className="text-lg font-medium text-gray-900">Total Cost (incl. shipping, tax &amp; fees)</span>
            <span className="text-3xl font-bold text-accent-deep">
              {money(totalCost)}
            </span>
          </div>
        </div>

        {/* Submit */}
        <div className="flex items-center justify-end space-x-4">
          <Button
            type="button"
            variant="outline"
            onClick={() => router.back()}
          >
            Cancel
          </Button>
          <Button type="submit" size="lg">
            Create Request
          </Button>
        </div>
      </form>
    </div>
  );
}
