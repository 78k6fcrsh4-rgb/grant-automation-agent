import React, { useState } from 'react';
import { FileText, CheckCircle, AlertCircle, Shield } from 'lucide-react';
import { Button } from '../ui/Button';
import { useUploadGrantPackage } from '../../hooks/useGrants';

interface FileUploadProps {
  onUploadSuccess: (fileIds: string[]) => void;
}

export const FileUpload: React.FC<FileUploadProps> = ({ onUploadSuccess }) => {
  const [proposal, setProposal] = useState<File | null>(null);
  const [awardLetter, setAwardLetter] = useState<File | null>(null);
  const [settings, setSettings] = useState({
    redact_names: true,
    redact_salaries: true,
    redact_contact_details: true,
    enable_external_llm: false,
  });
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const uploadMutation = useUploadGrantPackage();

  const handleSubmit = async () => {
    if (!proposal && !awardLetter) return;
    const result = await uploadMutation.mutateAsync({ proposal, awardLetter, settings });
    setUploadMessage(`${result.message} Redactions detected: ${result.redaction_count}.`);
    onUploadSuccess([result.package_id]);
  };

  const fileCard = (
    label: string,
    description: string,
    file: File | null,
    onChange: (file: File | null) => void
  ) => (
    <label className="border-2 border-dashed border-gray-300 rounded-lg p-6 block cursor-pointer hover:border-primary-400 bg-white">
      <div className="flex items-start gap-3">
        <FileText className="h-6 w-6 text-primary-600 mt-0.5" />
        <div className="flex-1">
          <div className="font-semibold text-gray-900">{label}</div>
          <div className="text-sm text-gray-500 mb-3">{description}</div>
          <input
            type="file"
            accept=".pdf,.doc,.docx"
            className="hidden"
            onChange={(e) => onChange(e.target.files?.[0] || null)}
          />
          <div className="text-sm text-primary-700">
            {file ? file.name : 'Choose file'}
          </div>
        </div>
      </div>
    </label>
  );

  const checkbox = (key: keyof typeof settings, label: string, description: string) => (
    <label className="flex items-start gap-3 p-3 rounded-lg border border-gray-200 bg-white">
      <input
        type="checkbox"
        checked={settings[key]}
        onChange={(e) => setSettings({ ...settings, [key]: e.target.checked })}
        className="mt-1 h-4 w-4 rounded border-gray-300 text-primary-600"
      />
      <div>
        <div className="text-sm font-medium text-gray-900">{label}</div>
        <div className="text-xs text-gray-500">{description}</div>
      </div>
    </label>
  );

  return (
    <div className="border rounded-xl bg-gray-50 p-6 space-y-4">
      <div>
        <h3 className="text-lg font-semibold text-gray-900">Upload grant package</h3>
        <p className="text-sm text-gray-600 mt-1">
          Local V2 mode parses and redacts uploaded files before any optional external LLM call. You can keep analysis fully local by leaving external LLM disabled.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {fileCard('Proposal upload', 'Optional, but helpful for scope, work plan, and budget intent.', proposal, setProposal)}
        {fileCard('Award letter upload', 'Optional, but preferred for binding dates, disbursements, and reporting requirements.', awardLetter, setAwardLetter)}
      </div>

      <div className="rounded-xl border border-primary-100 bg-primary-50 p-4">
        <div className="flex items-center gap-2 mb-3">
          <Shield className="h-4 w-4 text-primary-700" />
          <h4 className="font-semibold text-primary-900">Privacy controls</h4>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {checkbox('redact_names', 'Redact names', 'Mask named personnel before downstream analysis.')}
          {checkbox('redact_salaries', 'Redact salaries and percentages', 'Mask salaries, fringe, and other compensation amounts.')}
          {checkbox('redact_contact_details', 'Redact contact details', 'Mask emails, phone numbers, EINs, and similar identifiers.')}
          {checkbox('enable_external_llm', 'Allow external LLM on sanitized text', 'Off by default. When enabled, only redacted text and structured facts are eligible to leave the local app.')}
        </div>
      </div>

      {uploadMutation.isError && (
        <div className="flex items-center gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-md p-3">
          <AlertCircle className="h-4 w-4" />
          Upload failed.
        </div>
      )}

      {uploadMutation.isSuccess && uploadMessage && (
        <div className="flex items-center gap-2 text-sm text-green-700 bg-green-50 border border-green-200 rounded-md p-3">
          <CheckCircle className="h-4 w-4" />
          {uploadMessage}
        </div>
      )}

      <Button
        onClick={handleSubmit}
        isLoading={uploadMutation.isPending}
        disabled={!proposal && !awardLetter}
        className="w-full"
      >
        {uploadMutation.isPending ? 'Processing package...' : 'Upload and process locally'}
      </Button>
    </div>
  );
};
