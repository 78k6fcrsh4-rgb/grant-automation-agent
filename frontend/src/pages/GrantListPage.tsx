import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useGrantsList, useDeleteGrant } from '../hooks/useGrants';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { 
  FileText, 
  Trash2, 
  Eye, 
  Calendar,
  DollarSign,
  Building2,
  CheckCircle,
  Clock
} from 'lucide-react';

export const GrantListPage: React.FC = () => {
  const navigate = useNavigate();
  const { data, isLoading, isError } = useGrantsList();
  const deleteMutation = useDeleteGrant();

  const handleDelete = async (fileId: string, filename: string) => {
    if (window.confirm(`Are you sure you want to delete "${filename}"?`)) {
      try {
        await deleteMutation.mutateAsync(fileId);
      } catch (error) {
        console.error('Delete failed:', error);
        alert('Failed to delete grant. Please try again.');
      }
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingSpinner text="Loading grants..." />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <Card className="max-w-md w-full">
          <p className="text-red-600 text-center">Failed to load grants</p>
          <Button onClick={() => navigate('/')} className="w-full mt-4">
            Return to Home
          </Button>
        </Card>
      </div>
    );
  }

  const grants = data?.grants || [];

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">Your Grants</h1>
            <p className="text-gray-600 mt-2">
              {grants.length} {grants.length === 1 ? 'grant' : 'grants'} uploaded
            </p>
          </div>
          <Button onClick={() => navigate('/')}>
            Upload New Grant
          </Button>
        </div>

        {/* Grants List */}
        {grants.length === 0 ? (
          <Card className="text-center py-12">
            <FileText className="h-16 w-16 text-gray-400 mx-auto mb-4" />
            <h3 className="text-xl font-medium text-gray-900 mb-2">
              No grants yet
            </h3>
            <p className="text-gray-600 mb-6">
              Upload your first grant acceptance letter to get started
            </p>
            <Button onClick={() => navigate('/')}>Upload Grant</Button>
          </Card>
        ) : (
          <div className="grid grid-cols-1 gap-6">
            {grants.map((grant) => (
              <Card key={grant.file_id} className="hover:shadow-lg transition-shadow">
                <div className="flex items-start justify-between">
                  {/* Grant Info */}
                  <div className="flex-1">
                    <div className="flex items-center mb-3">
                      <FileText className="h-6 w-6 text-primary-600 mr-3" />
                      <div>
                        <h3 className="text-lg font-semibold text-gray-900">
                          {grant.grant_title || grant.filename}
                        </h3>
                        <p className="text-sm text-gray-500">{grant.filename}</p>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
                      {grant.organization && (
                        <div className="flex items-center text-sm">
                          <Building2 className="h-4 w-4 text-gray-400 mr-2" />
                          <span className="text-gray-700">{grant.organization}</span>
                        </div>
                      )}

                      {grant.grant_amount && (
                        <div className="flex items-center text-sm">
                          <DollarSign className="h-4 w-4 text-gray-400 mr-2" />
                          <span className="text-gray-700">
                            ${grant.grant_amount.toLocaleString()}
                          </span>
                        </div>
                      )}

                      {grant.created_at && (
                        <div className="flex items-center text-sm">
                          <Calendar className="h-4 w-4 text-gray-400 mr-2" />
                          <span className="text-gray-700">
                            {new Date(grant.created_at).toLocaleDateString()}
                          </span>
                        </div>
                      )}
                    </div>

                    {/* Processing Status */}
                    <div className="mt-4">
                      {grant.processed ? (
                        <div className="flex items-center text-sm text-green-700">
                          <CheckCircle className="h-4 w-4 mr-2" />
                          Processed and ready
                        </div>
                      ) : (
                        <div className="flex items-center text-sm text-yellow-700">
                          <Clock className="h-4 w-4 mr-2" />
                          Processing...
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex flex-col gap-2 ml-4">
                    <Button
                      onClick={() => navigate(`/grant/${grant.file_id}`)}
                      className="flex items-center"
                    >
                      <Eye className="h-4 w-4 mr-2" />
                      View
                    </Button>
                    <Button
                      variant="danger"
                      onClick={() => handleDelete(grant.file_id, grant.filename)}
                      disabled={deleteMutation.isPending}
                      className="flex items-center"
                    >
                      <Trash2 className="h-4 w-4 mr-2" />
                      {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
                    </Button>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};