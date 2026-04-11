import React, { useState } from 'react';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { useGenerateDocuments } from '../../hooks/useGrants';
import {
  Download,
  FileText,
  DollarSign,
  Calendar,
  CheckCircle,
  AlertTriangle,
  FileBarChart2,
} from 'lucide-react';
import { grantApi } from '../../services/api';

interface DocumentGeneratorProps {
  fileId: string;
}

// Human-readable labels for each doc type key
const DOC_LABELS: Record<string, string> = {
  summary: 'Grant Summary',
  workplan: 'Work Plan',
  budget: 'Budget Template',
  report: 'Report Template',
  agenda: 'Status Meeting Agenda',
  meeting_calendar: 'Status Meetings Calendar',
  disbursement_calendar: 'Disbursement Calendar',
  reporting_calendar: 'Reporting Calendar',
  calendar: 'Calendar', // legacy fallback
};

export const DocumentGenerator: React.FC<DocumentGeneratorProps> = ({ fileId }) => {
  const [options, setOptions] = useState({
    generate_summary: true,
    generate_workplan: true,
    generate_budget: true,
    generate_report_template: true,
    generate_agenda_template: true,
    generate_meeting_calendar: true,
    generate_disbursement_calendar: true,
    generate_reporting_calendar: true,
  });

  const [calendarOptions, setCalendarOptions] = useState({
    disbursement_interval_days: 30,
    disbursement_reminder_days: 7,
    meeting_interval_days: 14,
  });

  const [downloadingDoc, setDownloadingDoc] = useState<string | null>(null);
  const generateMutation = useGenerateDocuments();

  const anyCalendar =
    options.generate_meeting_calendar ||
    options.generate_disbursement_calendar ||
    options.generate_reporting_calendar;

  const handleGenerate = async () => {
    try {
      await generateMutation.mutateAsync({
        file_id: fileId,
        ...options,
        ...(anyCalendar ? calendarOptions : {}),
      });
    } catch (error) {
      console.error('Generation failed:', error);
    }
  };

  const handleDownload = async (type: string, filename: string) => {
    try {
      setDownloadingDoc(type);
      const url = grantApi.downloadDocument(fileId, type);
      const response = await fetch(url, { method: 'GET', headers: { Accept: 'application/octet-stream' } });
      if (!response.ok) throw new Error(response.statusText);
      const blob = await response.blob();
      const blobUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = blobUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(blobUrl);
    } catch (error) {
      console.error('Download failed:', error);
      alert(`Failed to download ${filename}. Please try again.`);
    } finally {
      setDownloadingDoc(null);
    }
  };

  // Four output categories
  const categories = [
    {
      heading: 'Category 1 — Grant Summary',
      icon: FileBarChart2,
      color: 'indigo',
      docs: [
        { key: 'generate_summary' as const, label: 'Grant Summary (Word)', description: 'Overview, milestones, financials, reporting obligations, and data gaps' },
      ],
    },
    {
      heading: 'Category 2 — Budget & Financials',
      icon: DollarSign,
      color: 'green',
      docs: [
        { key: 'generate_budget' as const, label: 'Budget Template (Excel)', description: 'Disbursement schedule, budget vs. actuals tracker' },
      ],
    },
    {
      heading: 'Category 3 — Report & Meeting Templates',
      icon: FileText,
      color: 'blue',
      docs: [
        { key: 'generate_report_template' as const, label: 'Report Template (Word)', description: 'Driven by extracted reporting requirements' },
        { key: 'generate_agenda_template' as const, label: 'Status Meeting Agenda (Word)', description: 'Recurring agenda template' },
      ],
    },
    {
      heading: 'Category 4 — Calendar Files (ICS)',
      icon: Calendar,
      color: 'amber',
      docs: [
        { key: 'generate_meeting_calendar' as const, label: 'Status Meetings (.ics)', description: 'Recurring meetings with built-in agenda notes' },
        { key: 'generate_disbursement_calendar' as const, label: 'Disbursement Deadlines (.ics)', description: 'Payment dates with submission checklist in description' },
        { key: 'generate_reporting_calendar' as const, label: 'Reporting Deadlines (.ics)', description: 'Report due dates with required elements in description' },
      ],
    },
  ];

  const colorClasses: Record<string, { border: string; bg: string; heading: string; check: string }> = {
    indigo: { border: 'border-indigo-200', bg: 'bg-indigo-50', heading: 'text-indigo-800', check: 'text-indigo-600' },
    green: { border: 'border-green-200', bg: 'bg-green-50', heading: 'text-green-800', check: 'text-green-600' },
    blue: { border: 'border-blue-200', bg: 'bg-blue-50', heading: 'text-blue-800', check: 'text-blue-600' },
    amber: { border: 'border-amber-200', bg: 'bg-amber-50', heading: 'text-amber-800', check: 'text-amber-600' },
  };

  const anySelected = Object.values(options).some((v) => v);

  return (
    <Card title="Generate Documents">
      <div className="space-y-5 mb-6">
        {categories.map((cat) => {
          const Icon = cat.icon;
          const c = colorClasses[cat.color];
          return (
            <div key={cat.heading} className={`border ${c.border} rounded-lg p-4 ${c.bg}`}>
              <div className="flex items-center mb-3">
                <Icon className={`h-4 w-4 ${c.check} mr-2`} />
                <h3 className={`text-sm font-semibold ${c.heading}`}>{cat.heading}</h3>
              </div>
              <div className="space-y-2">
                {cat.docs.map((doc) => (
                  <label
                    key={doc.key}
                    className="flex items-start p-2 rounded-md cursor-pointer hover:bg-white/60 transition-colors"
                  >
                    <input
                      type="checkbox"
                      checked={options[doc.key]}
                      onChange={(e) => setOptions({ ...options, [doc.key]: e.target.checked })}
                      className={`mt-1 mr-3 h-4 w-4 ${c.check} focus:ring-primary-500 border-gray-300 rounded`}
                    />
                    <div className="flex-1">
                      <p className="text-sm font-medium text-gray-900">{doc.label}</p>
                      <p className="text-xs text-gray-600">{doc.description}</p>
                    </div>
                  </label>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Calendar cadence options — shown when any calendar is checked */}
      {anyCalendar && (
        <div className="mb-6 p-4 border border-amber-200 rounded-lg bg-amber-50">
          <div className="flex items-center mb-3">
            <Calendar className="h-4 w-4 text-amber-600 mr-2" />
            <h3 className="text-sm font-semibold text-amber-800">Calendar Options</h3>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label className="block text-xs font-medium text-amber-700 mb-1">Meeting frequency</label>
              <select
                value={calendarOptions.meeting_interval_days}
                onChange={(e) => setCalendarOptions({ ...calendarOptions, meeting_interval_days: Number(e.target.value) })}
                className="w-full text-sm border border-amber-300 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-amber-500"
              >
                <option value={7}>Weekly</option>
                <option value={14}>Bi-weekly (default)</option>
                <option value={21}>Every 3 weeks</option>
                <option value={28}>Monthly</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-amber-700 mb-1">Disbursement frequency</label>
              <select
                value={calendarOptions.disbursement_interval_days}
                onChange={(e) => setCalendarOptions({ ...calendarOptions, disbursement_interval_days: Number(e.target.value) })}
                className="w-full text-sm border border-amber-300 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-amber-500"
              >
                <option value={14}>Every 2 weeks</option>
                <option value={30}>Monthly (30 days)</option>
                <option value={60}>Every 2 months</option>
                <option value={90}>Quarterly (90 days)</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-amber-700 mb-1">Reminder lead time</label>
              <select
                value={calendarOptions.disbursement_reminder_days}
                onChange={(e) => setCalendarOptions({ ...calendarOptions, disbursement_reminder_days: Number(e.target.value) })}
                className="w-full text-sm border border-amber-300 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-amber-500"
              >
                <option value={3}>3 days before</option>
                <option value={7}>7 days before</option>
                <option value={14}>14 days before</option>
              </select>
            </div>
          </div>
        </div>
      )}

      <Button
        onClick={handleGenerate}
        isLoading={generateMutation.isPending}
        className="w-full mb-4"
        disabled={!anySelected}
      >
        {generateMutation.isPending ? 'Generating Documents…' : 'Generate Selected Documents'}
      </Button>

      {generateMutation.isError && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-md mb-4">
          <p className="text-sm text-red-800">Failed to generate documents. Please try again.</p>
        </div>
      )}

      {generateMutation.isSuccess && generateMutation.data && (
        <div className="space-y-2">
          <div className="flex items-center mb-3">
            <CheckCircle className="h-5 w-5 text-green-600 mr-2" />
            <p className="text-sm font-medium text-green-700">Documents generated successfully!</p>
          </div>

          {Object.entries(generateMutation.data.files)
            .filter(([_, doc]) => doc && typeof doc === 'object' && 'filename' in doc)
            .map(([type, doc]) => {
              const typedDoc = doc as { filename: string; download_url: string };
              const isDownloading = downloadingDoc === type;
              const label = DOC_LABELS[type] || type;

              return (
                <button
                  key={type}
                  onClick={() => handleDownload(type, typedDoc.filename)}
                  disabled={isDownloading}
                  className="w-full flex items-center justify-between p-3 bg-green-50 border border-green-200 rounded-md hover:bg-green-100 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <div className="text-left">
                    <p className="text-sm font-medium text-green-900">{label}</p>
                    <p className="text-xs text-green-700">{typedDoc.filename}</p>
                  </div>
                  {isDownloading ? (
                    <svg className="animate-spin h-4 w-4 text-green-700 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                  ) : (
                    <Download className="h-4 w-4 text-green-700 flex-shrink-0" />
                  )}
                </button>
              );
            })}

          {generateMutation.data.calendar_discrepancy &&
            generateMutation.data.calendar_discrepancy.length > 0 && (
              <div className="mt-4 p-3 bg-amber-50 border border-amber-300 rounded-md">
                <div className="flex items-center mb-2">
                  <AlertTriangle className="h-4 w-4 text-amber-600 mr-2 flex-shrink-0" />
                  <p className="text-sm font-semibold text-amber-800">Calendar discrepancies detected</p>
                </div>
                <ul className="space-y-1">
                  {generateMutation.data.calendar_discrepancy.map((msg, idx) => (
                    <li key={idx} className="text-xs text-amber-700 leading-snug">{msg}</li>
                  ))}
                </ul>
              </div>
            )}
        </div>
      )}
    </Card>
  );
};
