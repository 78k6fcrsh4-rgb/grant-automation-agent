import React, { useState } from 'react';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { useGenerateDocuments } from '../../hooks/useGrants';
import { Download, FileText, DollarSign, Calendar, ClipboardList, CheckCircle, AlertTriangle } from 'lucide-react';
import { grantApi } from '../../services/api';

interface DocumentGeneratorProps {
  fileId: string;
}

export const DocumentGenerator: React.FC<DocumentGeneratorProps> = ({ fileId }) => {
  const [options, setOptions] = useState({
    generate_workplan: true,
    generate_budget: true,
    generate_report_template: true,
    generate_calendar: true,
    generate_agenda_template: true,
  });

  const [calendarOptions, setCalendarOptions] = useState({
    disbursement_interval_days: 30,
    disbursement_reminder_days: 7,
    meeting_interval_days: 14,
  });

  const [downloadingDoc, setDownloadingDoc] = useState<string | null>(null);

  const generateMutation = useGenerateDocuments();

  const handleGenerate = async () => {
    try {
      await generateMutation.mutateAsync({
        file_id: fileId,
        ...options,
        ...(options.generate_calendar ? calendarOptions : {}),
      });
    } catch (error) {
      console.error('Generation failed:', error);
    }
  };

  const handleDownload = async (type: string, filename: string) => {
    try {
      setDownloadingDoc(type);
      const url = grantApi.downloadDocument(fileId, type);
      
      // Fetch the file as a blob
      const response = await fetch(url, {
        method: 'GET',
        headers: {
          'Accept': 'application/octet-stream',
        },
      });

      if (!response.ok) {
        throw new Error(`Download failed: ${response.statusText}`);
      }

      // Get the blob
      const blob = await response.blob();
      
      // Create blob URL
      const blobUrl = window.URL.createObjectURL(blob);
      
      // Create temporary link and trigger download
      const link = document.createElement('a');
      link.href = blobUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      
      // Cleanup
      document.body.removeChild(link);
      window.URL.revokeObjectURL(blobUrl);
      
      setDownloadingDoc(null);
    } catch (error) {
      console.error('Download failed:', error);
      alert(`Failed to download ${filename}. Please try again.`);
      setDownloadingDoc(null);
    }
  };

  const documentTypes = [
    {
      key: 'generate_workplan' as const,
      label: 'Work Plan (PDF)',
      icon: ClipboardList,
      description: 'Timeline and deliverables',
    },
    {
      key: 'generate_budget' as const,
      label: 'Budget Template (Excel)',
      icon: DollarSign,
      description: 'Budget breakdown and disbursement schedule',
    },
    {
      key: 'generate_report_template' as const,
      label: 'Report Template (Word)',
      icon: FileText,
      description: 'Progress report template',
    },
    {
      key: 'generate_calendar' as const,
      label: 'Calendar Events (ICS)',
      icon: Calendar,
      description: 'Important dates and deadlines',
    },
    {
      key: 'generate_agenda_template' as const,
      label: 'Status Agenda (Word)',
      icon: FileText,
      description: 'Reusable status meeting agenda',
    },
  ];

  return (
    <Card title="Generate Documents">
      <div className="space-y-4 mb-6">
        {documentTypes.map((doc) => {
          const Icon = doc.icon;
          return (
            <label
              key={doc.key}
              className="flex items-start p-3 border border-gray-200 rounded-md cursor-pointer hover:bg-gray-50 transition-colors"
            >
              <input
                type="checkbox"
                checked={options[doc.key]}
                onChange={(e) =>
                  setOptions({ ...options, [doc.key]: e.target.checked })
                }
                className="mt-1 mr-3 h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
              />
              <Icon className="h-5 w-5 text-primary-600 mt-0.5 mr-3" />
              <div className="flex-1">
                <p className="font-medium text-gray-900">{doc.label}</p>
                <p className="text-sm text-gray-600">{doc.description}</p>
              </div>
            </label>
          );
        })}
      </div>

      {options.generate_calendar && (
        <div className="mb-6 p-4 border border-blue-200 rounded-md bg-blue-50">
          <div className="flex items-center mb-3">
            <Calendar className="h-4 w-4 text-blue-600 mr-2" />
            <h3 className="text-sm font-semibold text-blue-800">Calendar Options</h3>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label className="block text-xs font-medium text-blue-700 mb-1">
                Disbursement frequency
              </label>
              <select
                value={calendarOptions.disbursement_interval_days}
                onChange={(e) =>
                  setCalendarOptions({
                    ...calendarOptions,
                    disbursement_interval_days: Number(e.target.value),
                  })
                }
                className="w-full text-sm border border-blue-300 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value={14}>Every 2 weeks</option>
                <option value={30}>Monthly (30 days)</option>
                <option value={60}>Every 2 months</option>
                <option value={90}>Quarterly (90 days)</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-blue-700 mb-1">
                Reminder window
              </label>
              <select
                value={calendarOptions.disbursement_reminder_days}
                onChange={(e) =>
                  setCalendarOptions({
                    ...calendarOptions,
                    disbursement_reminder_days: Number(e.target.value),
                  })
                }
                className="w-full text-sm border border-blue-300 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value={3}>3 days before</option>
                <option value={7}>7 days before</option>
                <option value={14}>14 days before</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-blue-700 mb-1">
                Meeting frequency
              </label>
              <select
                value={calendarOptions.meeting_interval_days}
                onChange={(e) =>
                  setCalendarOptions({
                    ...calendarOptions,
                    meeting_interval_days: Number(e.target.value),
                  })
                }
                className="w-full text-sm border border-blue-300 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value={7}>Weekly</option>
                <option value={14}>Biweekly (14 days)</option>
                <option value={21}>Every 3 weeks</option>
                <option value={28}>Monthly (28 days)</option>
              </select>
            </div>
          </div>
        </div>
      )}

      <Button
        onClick={handleGenerate}
        isLoading={generateMutation.isPending}
        className="w-full mb-4"
        disabled={!Object.values(options).some((v) => v)}
      >
        {generateMutation.isPending ? 'Generating Documents...' : 'Generate Selected Documents'}
      </Button>

      {generateMutation.isError && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-md mb-4">
          <p className="text-sm text-red-800">
            Failed to generate documents. Please try again.
          </p>
        </div>
      )}

      {generateMutation.isSuccess && generateMutation.data && (
        <div className="space-y-2">
          <div className="flex items-center mb-3">
            <CheckCircle className="h-5 w-5 text-green-600 mr-2" />
            <p className="text-sm font-medium text-green-700">
              Documents generated successfully!
            </p>
          </div>

          {Object.entries(generateMutation.data.files)
            .filter(([_, doc]) => doc && typeof doc === 'object' && 'filename' in doc)
            .map(([type, doc]) => {
              const typedDoc = doc as { filename: string; download_url: string };
              const isDownloading = downloadingDoc === type;

              return (
                <button
                  key={type}
                  onClick={() => handleDownload(type, typedDoc.filename)}
                  disabled={isDownloading}
                  className="w-full flex items-center justify-between p-3 bg-green-50 border border-green-200 rounded-md hover:bg-green-100 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <span className="text-sm font-medium text-green-900">
                    {typedDoc.filename}
                  </span>
                  {isDownloading ? (
                    <svg className="animate-spin h-4 w-4 text-green-700" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                  ) : (
                    <Download className="h-4 w-4 text-green-700" />
                  )}
                </button>
              );
            })}

          {generateMutation.data.calendar_discrepancy &&
            generateMutation.data.calendar_discrepancy.length > 0 && (
              <div className="mt-4 p-3 bg-amber-50 border border-amber-300 rounded-md">
                <div className="flex items-center mb-2">
                  <AlertTriangle className="h-4 w-4 text-amber-600 mr-2 flex-shrink-0" />
                  <p className="text-sm font-semibold text-amber-800">
                    Calendar discrepancies detected
                  </p>
                </div>
                <ul className="space-y-1">
                  {generateMutation.data.calendar_discrepancy.map((msg, idx) => (
                    <li key={idx} className="text-xs text-amber-700 leading-snug">
                      {msg}
                    </li>
                  ))}
                </ul>
              </div>
            )}
        </div>
      )}
    </Card>
  );
};
