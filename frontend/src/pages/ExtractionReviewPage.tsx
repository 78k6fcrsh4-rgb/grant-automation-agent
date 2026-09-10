import React, { useMemo, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  useConfirmGrant, useEditGrantData, useGrantData, usePersistenceMode,
} from '../hooks/useGrants';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { DocumentGenerator } from '../components/features/DocumentGenerator';
import { Button } from '../components/ui/Button';
import {
  AlertCircle, AlertTriangle, ArrowLeft, Check, CheckCircle2, ChevronDown,
  ChevronRight, HelpCircle, Lock, Pencil, Save, Unlock, X,
} from 'lucide-react';
import type {
  ConfirmResponse, EditableScalar, ExtractionConfidence, GrantDataPatch,
  ReportingRequirement, Timeline,
} from '../types';

// ── Confidence badge ────────────────────────────────────────────────────────

function confidenceLabel(c?: ExtractionConfidence): { label: string; dot: string; text: string } {
  switch (c) {
    case 'confirmed':
      return { label: 'Confirmed', dot: 'bg-green-500', text: 'text-green-700' };
    case 'inferred':
      return { label: 'Inferred', dot: 'bg-amber-400', text: 'text-amber-700' };
    default:
      return { label: 'Not found', dot: 'bg-red-400', text: 'text-red-700' };
  }
}

// ── One editable field ──────────────────────────────────────────────────────

interface EditableFieldProps {
  label: string;
  field: EditableScalar;
  value?: string | number | null;
  display?: string | null;
  confidence?: ExtractionConfidence;
  numeric?: boolean;
  multiline?: boolean;
  edited: boolean;
  saving: boolean;
  onSave: (field: EditableScalar, value: string | number | null) => void;
}

const EditableField: React.FC<EditableFieldProps> = ({
  label, field, value, display, confidence, numeric, multiline, edited, saving, onSave,
}) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');

  const start = () => {
    setDraft(value == null ? '' : String(value));
    setEditing(true);
  };

  const commit = () => {
    const trimmed = draft.trim();
    const next = numeric
      ? (trimmed === '' ? null : Number(trimmed.replace(/[$,]/g, '')))
      : (trimmed === '' ? null : trimmed);
    if (numeric && next !== null && Number.isNaN(next as number)) return;
    if (String(next ?? '') !== String(value ?? '')) onSave(field, next);
    setEditing(false);
  };

  const { label: confLabel, dot, text } = confidenceLabel(confidence);
  const shown = display ?? (value != null ? String(value) : null);

  return (
    <div className="flex items-start py-3 border-b border-gray-100 last:border-0">
      <div className="w-44 flex-shrink-0">
        <span className="text-sm font-medium text-gray-600">{label}</span>
      </div>

      <div className="flex-1 min-w-0">
        {editing ? (
          <div className="flex items-start gap-2">
            {multiline ? (
              <textarea
                autoFocus
                rows={3}
                className="flex-1 text-sm border border-indigo-300 rounded px-2 py-1
                           focus:outline-none focus:ring-2 focus:ring-indigo-200"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
              />
            ) : (
              <input
                autoFocus
                className="flex-1 text-sm border border-indigo-300 rounded px-2 py-1
                           focus:outline-none focus:ring-2 focus:ring-indigo-200"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commit();
                  if (e.key === 'Escape') setEditing(false);
                }}
              />
            )}
            <button
              type="button"
              aria-label={`Save ${label}`}
              className="p-1 text-green-600 hover:bg-green-50 rounded"
              onClick={commit}
              disabled={saving}
            >
              <Save className="h-4 w-4" />
            </button>
            <button
              type="button"
              aria-label={`Cancel editing ${label}`}
              className="p-1 text-gray-400 hover:bg-gray-100 rounded"
              onClick={() => setEditing(false)}
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="group text-left w-full"
            onClick={start}
            aria-label={`Edit ${label}`}
          >
            {shown ? (
              <span className="text-sm text-gray-900">{shown}</span>
            ) : (
              <span className="text-sm text-gray-400 italic">Not extracted — click to add</span>
            )}
            <Pencil className="inline-block h-3 w-3 ml-2 text-gray-300 group-hover:text-indigo-500" />
          </button>
        )}
      </div>

      <div className="ml-3 flex items-center gap-1.5 flex-shrink-0">
        {edited ? (
          <>
            <Check className="h-3.5 w-3.5 text-indigo-600" />
            <span className="text-xs font-medium text-indigo-700">Corrected</span>
          </>
        ) : (
          <>
            <span className={`inline-block h-2 w-2 rounded-full ${dot}`} />
            <span className={`text-xs font-medium ${text}`}>{confLabel}</span>
          </>
        )}
      </div>
    </div>
  );
};

// ── Page ────────────────────────────────────────────────────────────────────

export const ExtractionReviewPage: React.FC = () => {
  const { fileId } = useParams<{ fileId: string }>();
  const navigate = useNavigate();
  const { data, isLoading, isError, error } = useGrantData(fileId);
  const { data: mode } = usePersistenceMode();
  const edit = useEditGrantData(fileId);
  const confirm = useConfirmGrant(fileId);

  const [showDocGenerator, setShowDocGenerator] = useState(false);
  const [editedFields, setEditedFields] = useState<Set<string>>(new Set());
  const [confirmation, setConfirmation] = useState<ConfirmResponse | null>(null);

  const markEdited = (field: string) =>
    setEditedFields((prev) => new Set(prev).add(field));

  const saveScalar = (field: EditableScalar, value: string | number | null) => {
    edit.mutate({ [field]: value } as GrantDataPatch, {
      onSuccess: () => markEdited(field),
    });
  };

  const saveRequirements = (requirements: ReportingRequirement[]) => {
    edit.mutate({ reporting_requirements: requirements },
      { onSuccess: () => markEdited('reporting_requirements') });
  };

  const saveTimeline = (timeline: Timeline) => {
    edit.mutate({ timeline }, { onSuccess: () => markEdited('timeline') });
  };

  const gaps = data?.data_gaps ?? [];
  const flags = data?.validation_flags ?? [];

  const counts = useMemo(() => {
    const ec = data?.extraction_confidence ?? {};
    const values = Object.values(ec) as ExtractionConfidence[];
    return {
      confirmed: values.filter((c) => c === 'confirmed').length,
      inferred: values.filter((c) => c === 'inferred').length,
      missing: values.filter((c) => c === 'missing').length,
    };
  }, [data?.extraction_confidence]);

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

  const docFormat = (data.document_format ?? 'unknown').replace('_', ' ');
  const persists = mode?.persists ?? false;

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">

        <div className="mb-6">
          <Button variant="secondary" onClick={() => navigate('/')} className="mb-4">
            <ArrowLeft className="h-4 w-4 mr-2" />
            New Upload
          </Button>
          <h1 className="text-2xl font-bold text-gray-900">Review &amp; Correct</h1>
          <p className="text-gray-600 text-sm mt-1">
            Extraction is a proposal, not a fact. Click any field to correct it —
            what you save here is what goes into the calendars, the budget workbook
            and the report template.
          </p>
        </div>

        {/* What happens to this record. Nobody should be under a data-retention
            contract they cannot see. */}
        {mode && (
          <div
            className={`mb-6 p-4 rounded-lg border flex items-start gap-3 ${
              persists
                ? 'bg-indigo-50 border-indigo-200'
                : 'bg-gray-50 border-gray-200'
            }`}
          >
            {persists
              ? <Lock className="h-5 w-5 text-indigo-600 flex-shrink-0 mt-0.5" />
              : <Unlock className="h-5 w-5 text-gray-500 flex-shrink-0 mt-0.5" />}
            <div>
              <p className={`text-sm font-semibold ${persists ? 'text-indigo-900' : 'text-gray-800'}`}>
                {persists ? 'This grant will be kept' : 'This session is not retained'}
              </p>
              <p className={`text-sm ${persists ? 'text-indigo-700' : 'text-gray-600'}`}>
                {persists
                  ? 'When you confirm, this record becomes your organization’s record of the award and is visible in Perch. The source document itself is never stored.'
                  : `Nothing is written to a database. This extraction is held in memory and is discarded after ${mode.ttl_minutes} minutes of inactivity, or when the service restarts.`}
              </p>
            </div>
          </div>
        )}

        <div className="mb-6 p-4 bg-white rounded-lg border border-gray-200 shadow-sm">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-sm font-semibold text-gray-700">Extraction Summary</span>
            <span className="px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-600 capitalize">
              {docFormat}
            </span>
          </div>
          <div className="flex gap-6">
            <div className="flex items-center gap-1.5">
              <CheckCircle2 className="h-4 w-4 text-green-500" />
              <span className="text-sm text-gray-700">{counts.confirmed} confirmed</span>
            </div>
            <div className="flex items-center gap-1.5">
              <AlertTriangle className="h-4 w-4 text-amber-400" />
              <span className="text-sm text-gray-700">{counts.inferred} inferred</span>
            </div>
            <div className="flex items-center gap-1.5">
              <HelpCircle className="h-4 w-4 text-red-400" />
              <span className="text-sm text-gray-700">{counts.missing} not found</span>
            </div>
          </div>
        </div>

        {gaps.length > 0 && (
          <div className="mb-6 p-4 bg-amber-50 border border-amber-200 rounded-lg">
            <div className="flex items-center mb-2">
              <AlertTriangle className="h-5 w-5 text-amber-600 mr-2 flex-shrink-0" />
              <h2 className="text-sm font-semibold text-amber-800">
                {gaps.length} Data Gap{gaps.length > 1 ? 's' : ''} — fill these in below
              </h2>
            </div>
            <ul className="space-y-1 ml-7">
              {gaps.map((gap, i) => <li key={i} className="text-sm text-amber-700">{gap}</li>)}
            </ul>
          </div>
        )}

        {flags.length > 0 && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg">
            <div className="flex items-center mb-2">
              <AlertCircle className="h-5 w-5 text-red-600 mr-2 flex-shrink-0" />
              <h2 className="text-sm font-semibold text-red-800">
                {flags.length} Value{flags.length > 1 ? 's' : ''} need review — correct them below
              </h2>
            </div>
            <ul className="space-y-1 ml-7">
              {flags.map((flag, i) => <li key={i} className="text-sm text-red-700">{flag}</li>)}
            </ul>
          </div>
        )}

        <div className="bg-white rounded-lg border border-gray-200 shadow-sm mb-6">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-800">Extracted Fields</h2>
            {edit.isPending && <span className="text-xs text-gray-500">Saving…</span>}
            {edit.isError && (
              <span className="text-xs text-red-600">Could not save that change</span>
            )}
          </div>
          <div className="px-5">
            <EditableField
              label="Organization (Grantee)" field="organization_name"
              value={data.organization_name}
              confidence={data.extraction_confidence?.organization_name}
              edited={editedFields.has('organization_name')}
              saving={edit.isPending} onSave={saveScalar}
            />
            <EditableField
              label="Funder" field="funder_name" value={data.funder_name}
              confidence={data.extraction_confidence?.funder_name}
              edited={editedFields.has('funder_name')}
              saving={edit.isPending} onSave={saveScalar}
            />
            <EditableField
              label="Grant Title" field="grant_title" value={data.grant_title}
              confidence={data.extraction_confidence?.grant_title}
              edited={editedFields.has('grant_title')}
              saving={edit.isPending} onSave={saveScalar}
            />
            <EditableField
              label="Grant Amount" field="grant_amount" numeric
              value={data.grant_amount}
              display={data.grant_amount != null
                ? `$${Number(data.grant_amount).toLocaleString()}` : null}
              confidence={data.extraction_confidence?.grant_amount}
              edited={editedFields.has('grant_amount')}
              saving={edit.isPending} onSave={saveScalar}
            />
            <EditableField
              label="Grant Period" field="grant_period" value={data.grant_period}
              confidence={data.extraction_confidence?.grant_period}
              edited={editedFields.has('grant_period')}
              saving={edit.isPending} onSave={saveScalar}
            />
            <EditableField
              label="Purpose" field="purpose" multiline value={data.purpose}
              confidence={data.extraction_confidence?.purpose}
              edited={editedFields.has('purpose')}
              saving={edit.isPending} onSave={saveScalar}
            />
          </div>
        </div>

        {data.reporting_requirements && data.reporting_requirements.length > 0 && (
          <div className="bg-white rounded-lg border border-gray-200 shadow-sm mb-6">
            <div className="px-5 py-4 border-b border-gray-100">
              <h2 className="text-sm font-semibold text-gray-800">Reporting Requirements</h2>
              <p className="text-xs text-gray-500 mt-0.5">
                A due date the extractor could not read is stored as written and
                needs a real date before it can appear on a calendar.
              </p>
            </div>
            <ul className="divide-y divide-gray-100">
              {data.reporting_requirements.map((req, i) => (
                <li key={i} className="px-5 py-3 flex items-start gap-4">
                  <input
                    className="text-sm border border-gray-200 rounded px-2 py-1 flex-1
                               focus:outline-none focus:border-indigo-300"
                    defaultValue={req.description}
                    aria-label={`Requirement ${i + 1} description`}
                    onBlur={(e) => {
                      if (e.target.value === req.description) return;
                      const next = [...data.reporting_requirements!];
                      next[i] = { ...req, description: e.target.value };
                      saveRequirements(next);
                    }}
                  />
                  <input
                    className="text-sm border border-gray-200 rounded px-2 py-1 w-44
                               focus:outline-none focus:border-indigo-300"
                    defaultValue={req.due_date ?? ''}
                    placeholder="YYYY-MM-DD"
                    aria-label={`Requirement ${i + 1} due date`}
                    onBlur={(e) => {
                      if (e.target.value === (req.due_date ?? '')) return;
                      const next = [...data.reporting_requirements!];
                      next[i] = { ...req, due_date: e.target.value || undefined };
                      saveRequirements(next);
                    }}
                  />
                </li>
              ))}
            </ul>
          </div>
        )}

        {data.timeline?.items && data.timeline.items.length > 0 && (
          <div className="bg-white rounded-lg border border-gray-200 shadow-sm mb-6">
            <div className="px-5 py-4 border-b border-gray-100">
              <h2 className="text-sm font-semibold text-gray-800">Timeline Items</h2>
            </div>
            <ul className="divide-y divide-gray-100">
              {data.timeline.items.map((item, i) => (
                <li key={i} className="px-5 py-3 flex items-start gap-4">
                  <input
                    className="text-xs border border-gray-200 rounded px-2 py-1 w-36 flex-shrink-0
                               focus:outline-none focus:border-indigo-300"
                    defaultValue={item.date}
                    aria-label={`Timeline item ${i + 1} date`}
                    onBlur={(e) => {
                      if (e.target.value === item.date) return;
                      const items = [...data.timeline!.items];
                      items[i] = { ...item, date: e.target.value };
                      saveTimeline({ ...data.timeline!, items });
                    }}
                  />
                  <div>
                    <span className="text-xs font-medium text-indigo-600 capitalize">
                      {item.category ?? 'uncategorised'}
                    </span>
                    <p className="text-sm text-gray-800 mt-0.5">{item.description}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Confirm: machine output never becomes the record unattended. */}
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm mb-6 p-5">
          <h2 className="text-sm font-semibold text-gray-800 mb-1">
            {persists ? 'File this grant' : 'Mark as reviewed'}
          </h2>
          <p className="text-sm text-gray-600 mb-3">
            {persists
              ? 'Confirms that you have checked these values. The record is filed under your organization and attributed to you.'
              : 'Confirms that you have checked these values for this session. Nothing is stored.'}
          </p>
          {confirmation ? (
            <div className="flex items-start gap-2 text-sm text-green-800 bg-green-50
                            border border-green-200 rounded p-3">
              <CheckCircle2 className="h-4 w-4 mt-0.5 flex-shrink-0" />
              <span>{confirmation.message}</span>
            </div>
          ) : (
            <Button
              onClick={() => confirm.mutate(undefined, { onSuccess: setConfirmation })}
              disabled={confirm.isPending}
            >
              {confirm.isPending
                ? 'Working…'
                : persists ? 'Confirm & file' : 'Confirm reviewed'}
            </Button>
          )}
          {confirm.isError && (
            <div className="text-sm text-red-600 mt-2">
              <p>Could not confirm this grant. Your corrections are still held in this session.</p>
              {/* Show what the server actually said — a generic message with the
                  real reason hidden is not something anyone can act on. */}
              <p className="mt-1 font-mono text-xs break-words">
                {(confirm.error as { response?: { data?: { detail?: string } } })
                  ?.response?.data?.detail ?? String(confirm.error)}
              </p>
            </div>
          )}
        </div>

        <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
          <button
            className="w-full flex items-center justify-between px-5 py-4 text-left"
            onClick={() => setShowDocGenerator((v) => !v)}
          >
            <h2 className="text-sm font-semibold text-gray-800">Generate Documents</h2>
            {showDocGenerator
              ? <ChevronDown className="h-4 w-4 text-gray-500" />
              : <ChevronRight className="h-4 w-4 text-gray-500" />}
          </button>

          {showDocGenerator ? (
            <div className="px-5 pb-5">
              <p className="text-xs text-gray-500 mb-3">
                Documents are built from the values above as they stand now. If you
                correct something afterwards, generate them again.
              </p>
              <DocumentGenerator fileId={fileId!} />
            </div>
          ) : (
            <div className="px-5 pb-5">
              <p className="text-sm text-gray-600 mb-3">
                {gaps.length > 0
                  ? `${gaps.length} field(s) could not be extracted and will appear as placeholders unless you fill them in above.`
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
