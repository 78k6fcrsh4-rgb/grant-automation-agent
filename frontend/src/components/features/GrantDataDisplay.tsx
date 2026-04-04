import React from 'react';
import { Card } from '../ui/Card';
import type { GrantData } from '../../types';
import { DollarSign, Calendar, Building2, Award, Shield, Eye, CircleAlert } from 'lucide-react';

interface GrantDataDisplayProps {
  data: GrantData;
}

export const GrantDataDisplay: React.FC<GrantDataDisplayProps> = ({ data }) => {
  return (
    <div className="space-y-6">
      <Card title="Privacy and processing summary">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="rounded-lg border border-gray-200 p-4 bg-white">
            <div className="flex items-center gap-2 mb-2 text-gray-900 font-medium">
              <Shield className="h-4 w-4 text-primary-600" />
              Privacy settings
            </div>
            <ul className="text-sm text-gray-700 space-y-1">
              <li>Names redacted: {data.privacy_settings?.redact_names ? 'Yes' : 'No'}</li>
              <li>Salaries redacted: {data.privacy_settings?.redact_salaries ? 'Yes' : 'No'}</li>
              <li>Contact details redacted: {data.privacy_settings?.redact_contact_details ? 'Yes' : 'No'}</li>
              <li>External LLM used: {data.used_external_llm ? 'Yes' : 'No'}</li>
            </ul>
          </div>
          <div className="rounded-lg border border-gray-200 p-4 bg-white">
            <div className="flex items-center gap-2 mb-2 text-gray-900 font-medium">
              <Eye className="h-4 w-4 text-primary-600" />
              Transmission preview
            </div>
            {data.transmission_preview ? (
              <div className="text-sm text-gray-700 space-y-1">
                <p>Raw characters: {data.transmission_preview.raw_characters.toLocaleString()}</p>
                <p>Redacted characters: {data.transmission_preview.redacted_characters.toLocaleString()}</p>
                <p>Structured fields sent: {data.transmission_preview.structured_fields_count}</p>
                {data.transmission_preview.notes.map((note, index) => (
                  <p key={index} className="text-gray-600">• {note}</p>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-600">No transmission preview available.</p>
            )}
          </div>
        </div>
      </Card>

      {data.redactions?.length > 0 && (
        <Card title="Detected redactions">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {data.redactions.map((item) => (
              <div key={`${item.entity_type}-${item.placeholder}`} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-gray-900">{item.entity_type.replace('_', ' ')}</span>
                  <span className="text-xs rounded bg-primary-100 px-2 py-1 text-primary-700">{item.placeholder}</span>
                </div>
                <p className="text-sm text-gray-600 mt-1">Preview: {item.original_preview}</p>
                <p className="text-xs text-gray-500 mt-1">Occurrences: {item.count}</p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {data.local_extraction_summary && (
        <Card title="Local extraction review">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 text-sm">
            <div>
              <h4 className="font-medium text-gray-900 mb-2">Clues identified locally</h4>
              <div className="space-y-2 text-gray-700">
                {data.local_extraction_summary.grant_amount_candidates.length > 0 && <p>Amounts: {data.local_extraction_summary.grant_amount_candidates.join(', ')}</p>}
                {data.local_extraction_summary.date_candidates.length > 0 && <p>Dates: {data.local_extraction_summary.date_candidates.join(', ')}</p>}
                {data.local_extraction_summary.reporting_clues.length > 0 && <p>Reporting clues: {data.local_extraction_summary.reporting_clues[0]}</p>}
                {data.local_extraction_summary.reimbursement_clues.length > 0 && <p>Reimbursement clues: {data.local_extraction_summary.reimbursement_clues[0]}</p>}
              </div>
            </div>
            <div>
              <div className="flex items-center gap-2 mb-2 text-gray-900 font-medium">
                <CircleAlert className="h-4 w-4 text-amber-600" />
                Unresolved questions
              </div>
              {data.local_extraction_summary.unresolved_questions.length > 0 ? (
                <ul className="space-y-1 text-gray-700">
                  {data.local_extraction_summary.unresolved_questions.map((question, index) => (
                    <li key={index}>• {question}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-gray-600">No major unresolved questions were flagged by local parsing.</p>
              )}
            </div>
          </div>
          {data.transmission_preview?.payload_excerpt && (
            <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
              <p className="text-sm font-medium text-gray-900 mb-2">Redacted payload excerpt</p>
              <pre className="whitespace-pre-wrap text-xs text-gray-700 font-mono">{data.transmission_preview.payload_excerpt}</pre>
            </div>
          )}
        </Card>
      )}

      <Card title="Grant information">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="flex items-start">
            <Building2 className="h-5 w-5 text-primary-600 mt-1 mr-3" />
            <div>
              <p className="text-sm text-gray-600">Organization</p>
              <p className="font-medium">{data.organization_name || 'N/A'}</p>
            </div>
          </div>

          <div className="flex items-start">
            <Award className="h-5 w-5 text-primary-600 mt-1 mr-3" />
            <div>
              <p className="text-sm text-gray-600">Funder</p>
              <p className="font-medium">{data.funder_name || 'N/A'}</p>
            </div>
          </div>

          <div className="flex items-start">
            <DollarSign className="h-5 w-5 text-primary-600 mt-1 mr-3" />
            <div>
              <p className="text-sm text-gray-600">Grant Amount</p>
              <p className="font-medium">{data.grant_amount ? `$${data.grant_amount.toLocaleString()}` : 'N/A'}</p>
            </div>
          </div>

          <div className="flex items-start">
            <Calendar className="h-5 w-5 text-primary-600 mt-1 mr-3" />
            <div>
              <p className="text-sm text-gray-600">Grant Period</p>
              <p className="font-medium">{data.grant_period || 'N/A'}</p>
            </div>
          </div>
        </div>

        <div className="mt-4 pt-4 border-t">
          <p className="text-sm text-gray-600 mb-2">Grant Title</p>
          <p className="font-medium text-lg">{data.grant_title || 'N/A'}</p>
        </div>
      </Card>

      {data.reporting_requirements && data.reporting_requirements.length > 0 && (
        <Card title="Reporting requirements">
          <div className="space-y-3">
            {data.reporting_requirements.map((item, index) => (
              <div key={index} className="rounded-lg border border-gray-200 p-3 bg-white">
                <p className="font-medium text-gray-900">{item.period || 'Reporting requirement'}</p>
                <p className="text-sm text-gray-700 mt-1">{item.description}</p>
                {item.due_date && <p className="text-sm text-primary-700 mt-1">Due: {item.due_date}</p>}
              </div>
            ))}
          </div>
        </Card>
      )}

      {data.submission_requirements && data.submission_requirements.length > 0 && (
        <Card title="Submission and reimbursement requirements">
          <div className="space-y-3">
            {data.submission_requirements.map((item, index) => (
              <div key={index} className="rounded-lg border border-gray-200 p-3 bg-white">
                <p className="font-medium text-gray-900 capitalize">{item.category}</p>
                {item.due_date && <p className="text-sm text-primary-700 mt-1">Due: {item.due_date}</p>}
                {item.instructions && <p className="text-sm text-gray-700 mt-1">{item.instructions}</p>}
              </div>
            ))}
          </div>
        </Card>
      )}

      {data.timeline && data.timeline.items.length > 0 && (
        <Card title="Timeline and milestones">
          <div className="space-y-3">
            {data.timeline.items.map((item, index) => (
              <div key={index} className="flex items-start p-3 bg-gray-50 rounded-md">
                <div className="flex-1">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-medium text-primary-600">{item.date}</span>
                    {item.amount && <span className="text-sm font-medium text-green-600">{item.amount}</span>}
                  </div>
                  <p className="text-sm text-gray-700">{item.description}</p>
                  {item.category && <span className="inline-block mt-1 px-2 py-1 text-xs bg-primary-100 text-primary-700 rounded">{item.category}</span>}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {data.budget && data.budget.items.length > 0 && (
        <Card title="Budget breakdown">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead>
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Category</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Description</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Amount</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {data.budget.items.map((item, index) => (
                  <tr key={index}>
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">{item.category}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{item.description || '-'}</td>
                    <td className="px-4 py-3 text-sm text-right font-medium text-gray-900">${item.amount.toLocaleString()}</td>
                  </tr>
                ))}
                <tr className="bg-gray-50">
                  <td colSpan={2} className="px-4 py-3 text-sm font-bold text-gray-900">Total</td>
                  <td className="px-4 py-3 text-sm text-right font-bold text-gray-900">${data.budget.total_grant_amount.toLocaleString()}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {data.workplan && data.workplan.tasks.length > 0 && (
        <Card title="Work plan">
          <div className="mb-4 pb-4 border-b">
            <p className="text-sm text-gray-600">Project Title</p>
            <p className="font-medium text-lg">{data.workplan.project_title}</p>
          </div>

          <div className="space-y-4">
            {data.workplan.tasks.map((task, index) => (
              <div key={index} className="p-4 bg-gray-50 rounded-md">
                <h4 className="font-medium text-gray-900 mb-2">{index + 1}. {task.task_name}</h4>
                <p className="text-sm text-gray-700 mb-2">{task.description}</p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
                  {task.start_date && <div><span className="text-gray-600">Start: </span><span className="font-medium">{task.start_date}</span></div>}
                  {task.end_date && <div><span className="text-gray-600">End: </span><span className="font-medium">{task.end_date}</span></div>}
                  {task.responsible_party && <div><span className="text-gray-600">Responsible: </span><span className="font-medium">{task.responsible_party}</span></div>}
                  {task.deliverables && <div className="md:col-span-2"><span className="text-gray-600">Deliverables: </span><span className="font-medium">{task.deliverables}</span></div>}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
};
