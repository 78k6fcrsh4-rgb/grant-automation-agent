import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useGrantData } from '../hooks/useGrants';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { DocumentGenerator } from '../components/features/DocumentGenerator';
import { Button } from '../components/ui/Button';
import { ArrowLeft, AlertCircle, CheckCircle2, AlertTriangle, HelpCircle, ChevronDown, ChevronRight } from 'lucide-react';
import type { ExtractionField } from '../types';

// ── Confidence badge ────────────────────────────────────────────────────────
type Confidence = 'CONFIRMED' | 'INFERRED' | 'MISSING';

function confidenceLabel(c?: Confidence): { label: string; dot: string; text: string } {
  switch (c) {
    case 'CONFIRMED':
      return { label: 'Confirmed', dot: 'bg-green-500', text: 'text-green-700' };
    case 'INFERRED':
      return { label: 'Inferred', dot: 'bg-amber-400', text: 'text-amber-700' };
    default:
      return { label: 'Not found', dot: 'bg-red-400', text: 'text-red-700' };
  }
}

interface FieldRowProps {
  label: string;
  field?: ExtractionField | null;
  value?: string | number | null;
  confidence?: Confidence;
}

const FieldRow: React.FC<FieldRowProps> = ({ label, field, value, confidence }) => {
  const displayValue = field?.value ?? (value != null ? String(value) : null);
  const conf: Confidence = (field?.confidence as Confidence) ?? confidence ?? (displayValue ? 'INFERRED' : 'MISSING');
  const { label: confLabel, dot, text } = confidenceLabel(conf);

  return (
    <div className="flex items-start py-3 border-b border-gray-100 last:border-0">
      <div className="w-44 flex-shrink-0">
        <span className="text-sm font-medium text-gray-600">{label}</span>
      </div>
      <div className="flex-1 min-w-0">
        {displayValue ? (
          <span className="text-sm text-gray-900">{displayValue}</span>
        ) : (
          <span className="text-sm text-gray-400 italic">Not extracted</span>
        )}
      </div>
      <div className="ml-3 flex items-center gap-1.5 flex-shrink-0">
        <span className={`inline-block h-2 w-2 rounded-full ${dot}`} />
        <span className={`text-xs font-medium ${text}`}>{confLabel}</span>
      </div>
    </div>
  );
};

// ── Page ───────────────────────────────────────────────────────────────────
export const ExtractionReviewPage: React.FC = () => {
  const { fileId } = useParams<{ fileId: string }>();
  const navigate = useNavigate();
  const { data, isLoading, isError, error } = useGrantData(fileId);
  const [showDocGenerator, setShowDocGenerator] = useState(false);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingSpinner text="Loading extracted data…" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <div className="max-w-md w-full bg-red-50 border border-red-200 rounded-lg p-6">
          <div className="flex items-center mb-4">
            <AlertCircle className="h-6 w-6 text-red-600 mr-3" />
            <h2 className="text-lg font-semibold text-red-900">Error Loading Data</h2>
          </div>
          <p className="text-red-700 mb-4">
            {error instanceof Error ? error.message : 'Failed to load grant data'}
          </p>
          <Button onClick={() => navigate('/')}>Return to Home</Button>
        </div>
      </div>
    );
  }

  const ec = data.extraction_confidence as Record<string, ExtractionField> | undefined;
  const gaps = data.data_gaps ?? [];
  const docFormat = (data.document_format ?? 'unknown').replace('_', ' ');

  // Determine overall confidence summary
  const allFields = ec ? Object.values(ec) : [];
  const missingCount = allFields.filter((f) => f.confidence === 'MISSING').length;
  const inferredCount = allFields.filter((f) => f.confidence === 'INFERRED').length;
  const confirmedCount = allFields.filter((f) => f.confidence === 'CONFIRMED').length;

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">

        {/* ── Header ── */}
        <div className="mb-6">
          <Button variant="secondary" onClick={() => navigate('/')} className="mb-4">
            <ArrowLeft className="h-4 w-4 mr-2" />
            New Upload
          </Button>
          <h1 className="text-2xl font-bold text-gray-900">Extraction Review</h1>
          <p className="text-gray-600 text-sm mt-1">
            Review the data extracted from your grant documents before generating outputs.
            Fields marked <span className="font-medium text-amber-700">Inferred</span> or{' '}
            <span className="font-medium text-red-600">Not found</span> may need manual verification.
          </p>
        </div>

        {/* ── Confidence Summary Bar ── */}
        <div className="mb-6 p-4 bg-white rounded-lg border border-gray-200 shadow-sm">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-sm font-semibold text-gray-700">Extraction Summary</span>
            <span className="px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-600 capitalize">{docFormat}</span>
          </div>
          <div className="flex gap-6">
            <div className="flex items-center gap-1.5">
              <CheckCircle2 className="h-4 w-4 text-green-500" />
              <span className="text-sm text-gray-700">{confirmedCount} confirmed</span>
            </div>
            <div className="flex items-center gap-1.5">
              <AlertTriangle className="h-4 w-4 text-amber-400" />
              <span className="text-sm text-gray-700">{inferredCount} inferred</span>
            </div>
            <div className="flex items-center gap-1.5">
              <HelpCircle className="h-4 w-4 text-red-400" />
              <span className="text-sm text-gray-700">{missingCount} not found</span>
            </div>
          </div>
        </div>

        {/* ── Data Gaps (prominent) ── */}
        {gaps.length > 0 && (
          <div className="mb-6 p-4 bg-amber-50 border border-amber-200 rounded-lg">
            <div className="flex items-center mb-2">
              <AlertTriangle className="h-5 w-5 text-amber-600 mr-2 flex-shrink-0" />
              <h2 className="text-sm font-semibold text-amber-800">
                {gaps.length} Data Gap{gaps.length > 1 ? 's' : ''} — Review Before Generating
              </h2>
            </div>
            <ul className="space-y-1 ml-7">
              {gaps.map((gap, i) => (
                <li key={i} className="text-sm text-amber-700">{gap}</li>
              ))}
            </ul>
          </div>
        )}

        {/* ── Extracted Fields ── */}
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm mb-6">
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-800">Extracted Fields</h2>
          </div>
          <div className="px-5">
            <FieldRow
              label="Organization (Grantee)"
              value={data.organization_name}
              field={ec?.organization_name}
            />
            <FieldRow
              label="Funder"
              value={data.funder_name}
              field={ec?.funder_name}
            />
            <FieldRow
              label="Grant Title"
              value={data.grant_title}
              field={ec?.grant_title}
            />
            <FieldRow
              label="Grant Amount"
              value={data.grant_amount != null ? `$${Number(data.grant_amount).toLocaleString()}` : null}
              field={ec?.grant_amount}
            />
            <FieldRow
              label="Grant Period"
              value={data.grant_period}
              field={ec?.grant_period}
            />
            <FieldRow
              label="Purpose"
              value={data.purpose}
              field={ec?.purpose}
            />
          </div>
        </div>

        {/* ── Reporting Requirements ── */}
        {data.reporting_requirements && data.reporting_requirements.length > 0 && (
          <div className="bg-white rounded-lg border border-gray-200 shadow-sm mb-6">
            <div className="px-5 py-4 border-b border-gray-100">
              <h2 className="text-sm font-semibold text-gray-800">Reporting Requirements</h2>
            </div>
            <ul className="divide-y divide-gray-100">
              {data.reporting_requirements.map((req, i) => (
                <li key={i} className="px-5 py-3">
                  <div className="flex items-start justify-between gap-4">
                    <div className="text-sm text-gray-900">{req.description}</div>
                    {req.due_date && (
                      <span className="text-xs text-gray-500 whitespace-nowrap">Due: {req.due_date}</span>
                    )}
                  </div>
                  {req.period && (
                    <span className="text-xs text-indigo-600 mt-1 inline-block">{req.period}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* ── Timeline ── */}
        {data.timeline?.items && data.timeline.items.length > 0 && (
          <div className="bg-white rounded-lg border border-gray-200 shadow-sm mb-6">
            <div className="px-5 py-4 border-b border-gray-100">
              <h2 className="text-sm font-semibold text-gray-800">Timeline Items</h2>
            </div>
            <ul className="divide-y divide-gray-100">
              {data.timeline.items.map((item, i) => (
                <li key={i} className="px-5 py-3 flex items-start gap-4">
                  <span className="text-xs text-gray-500 w-28 flex-shrink-0 pt-0.5">{item.date}</span>
                  <div>
                    <span className="text-xs font-medium text-indigo-600 capitalize">{item.category}</span>
                    <p className="text-sm text-gray-800 mt-0.5">{item.description}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* ── Generate Documents ── */}
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
          <button
            className="w-full flex items-center justify-between px-5 py-4 text-left"
            onClick={() => setShowDocGenerator((v) => !v)}
          >
            <h2 className="text-sm font-semibold text-gray-800">Generate Documents</h2>
            {showDocGenerator ? (
              <ChevronDown className="h-4 w-4 text-gray-500" />
            ) : (
              <ChevronRight className="h-4 w-4 text-gray-500" />
            )}
          </button>

          {showDocGenerator ? (
            <div className="px-5 pb-5">
              <DocumentGenerator fileId={fileId!} />
            </div>
          ) : (
            <div className="px-5 pb-5">
              <p className="text-sm text-gray-600 mb-3">
                {gaps.length > 0
                  ? `${gaps.length} field(s) could not be extracted and will appear as placeholders in documents.`
                  : 'All key fields were extracted. Documents should generate with complete information.'}
              </p>
              <Button onClick={() => setShowDocGenerator(true)} className="w-full">
                Proceed to Document Generation
              </Button>
            </div>
          )}
        </div>

      </div>
    </div>
  );
};
