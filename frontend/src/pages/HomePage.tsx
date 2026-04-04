import React from 'react';
import { useNavigate } from 'react-router-dom';
import { FileUpload } from '../components/features/FileUpload';
import { Card } from '../components/ui/Card';
import { FileText, TrendingUp, Calendar, BarChart } from 'lucide-react';

export const HomePage: React.FC = () => {
  const navigate = useNavigate();

  const handleUploadSuccess = (fileIds: string[]) => {
    // If multiple files, go to grants list
    // If single file, go directly to grant details
    if (fileIds.length === 1) {
      navigate(`/grant/${fileIds[0]}`);
    } else if (fileIds.length > 1) {
      navigate('/grants');
    }
  };

  const features = [
    {
      icon: FileText,
      title: 'Work Plans',
      description: 'Generate professional work plan PDFs with timelines and deliverables',
    },
    {
      icon: BarChart,
      title: 'Budget Templates',
      description: 'Create detailed budget spreadsheets with disbursement schedules',
    },
    {
      icon: TrendingUp,
      title: 'Progress Reports',
      description: 'Build comprehensive report templates for tracking grant progress',
    },
    {
      icon: Calendar,
      title: 'Calendar Events',
      description: 'Export deadlines and milestones as .ics calendar files',
    },
  ];

  return (
    <div className="min-h-screen bg-gradient-to-br from-primary-50 to-white">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        {/* Header */}
        <div className="text-center mb-12">
          <h1 className="text-4xl font-bold text-gray-900 mb-4">
            Grant Automation Platform (Local V2)
          </h1>
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
            What We Generate For You
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