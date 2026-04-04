import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useGrantData } from '../hooks/useGrants';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { GrantDataDisplay } from '../components/features/GrantDataDisplay';
import { DocumentGenerator } from '../components/features/DocumentGenerator';
import { Button } from '../components/ui/Button';
import { ArrowLeft, AlertCircle } from 'lucide-react';

export const GrantDetailsPage: React.FC = () => {
  const { fileId } = useParams<{ fileId: string }>();
  const navigate = useNavigate();
  const { data, isLoading, isError, error } = useGrantData(fileId);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingSpinner text="Loading grant data..." />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <div className="max-w-md w-full bg-red-50 border border-red-200 rounded-lg p-6">
          <div className="flex items-center mb-4">
            <AlertCircle className="h-6 w-6 text-red-600 mr-3" />
            <h2 className="text-lg font-semibold text-red-900">Error Loading Grant</h2>
          </div>
          <p className="text-red-700 mb-4">
            {error instanceof Error ? error.message : 'Failed to load grant data'}
          </p>
          <Button onClick={() => navigate('/')}>Return to Home</Button>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-gray-600">No data found</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <Button
            variant="secondary"
            onClick={() => navigate('/grants')}
            className="mb-4"
          >
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to Grants
          </Button>
          <h1 className="text-3xl font-bold text-gray-900">Grant Details</h1>
        </div>

        {/* Content Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Main Content - 2 columns */}
          <div className="lg:col-span-2">
            <GrantDataDisplay data={data} />
          </div>

          {/* Sidebar - 1 column */}
          <div className="lg:col-span-1">
            <div className="sticky top-8">
              <DocumentGenerator fileId={fileId!} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};