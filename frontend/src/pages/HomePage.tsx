import React from 'react';
import { useNavigate } from 'react-router-dom';
import { FileUpload } from '../components/features/FileUpload';
import { Card } from '../components/ui/Card';
import { FileText, TrendingUp, Calendar, BarChart } from 'lucide-react';

const APP_VERSION: string = (import.meta.env.VITE_APP_VERSION as string) ?? '2.3.0';

export const HomePage: React.FC = () => {
  const navigate = useNavigate();

  const handleUploadSuccess = (fileIds: string[]) => {
    // Single file → go to extraction review page
    // Multiple files → go to grants list
    if (fileIds.length === 1) {
      navigate(`/grant/${fileIds[0]}/review`);
    } else if (fileIds.length > 1) {
      navigate('/grants');
    }
  };

  const features = [
    {
      icon: BarChart,
      title: 'Grant Summary',
      description: 'High-level Word document: overview, milestones, financials, and reporting obligations',
    },
    {
      icon: TrendingUp,
      title: 'Budget & Disbursement',
      description: 'Excel spreadsheet with budget breakdown and disbursement schedule',
    },
    {
      icon: FileText,
      title: 'Word Templates',
      description: 'Reporting template driven by extracted requirements; status meeting agenda',
    },
    {
      icon: Calendar,
      title: 'Three Calendar Files',
      description: 'Separate ICS files for status meetings, disbursements (with checklist), and reporting deadlines',
    },
  ];

  return (
    <div className="min-h-screen bg-gradient-to-br from-primary-50 to-white">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        {/* Header */}
        <div className="text-center mb-12">
          <div className="flex items-center justify-center gap-3 mb-4">
            <h1 className="text-4xl font-bold text-gray-900">
              Grant Automation Platform
            </h1>
            <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold bg-primary-100 text-primary-700 border border-primary-200 self-center">
              v{APP_VERSION}
            </span>
          </div>
          <p className="text-xl text-gray-600 max-w-2xl mx-auto">
            Transform proposals and award letters into local-first work plans, privacy-reviewed extraction summaries, and downloadable grant operations templates
          </p>
          <p className="text-sm text-primary-600 mt-2">
            ✨ Local parsing + redaction now happens before any optional external AI call
          </p>
        </div>

        {/* Upload Section */}
        <div className="max-w-2xl mx-auto mb-16">
          <FileUpload onUploadSuccess={handleUploadSuccess} />
        </div>

        {/* Features Grid */}
        <div className="mb-12">
          <h2 className="text-2xl font-bold text-gray-900 text-center mb-8">
            Four Categories of Outputs
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {features.map((feature, index) => {
              const Icon = feature.icon;
              return (
                <Card key={index} className="text-center hover:shadow-lg transition-shadow">
                  <Icon className="h-12 w-12 text-primary-600 mx-auto mb-4" />
                  <h3 className="font-semibold text-gray-900 mb-2">
                    {feature.title}
                  </h3>
                  <p className="text-sm text-gray-600">{feature.description}</p>
                </Card>
              );
            })}
          </div>
        </div>

        {/* Recent Grants Link */}
        <div className="text-center">
          <button
            onClick={() => navigate('/grants')}
            className="text-primary-600 hover:text-primary-700 font-medium"
          >
            View All Grants →
          </button>
        </div>
      </div>
    </div>
  );
};
