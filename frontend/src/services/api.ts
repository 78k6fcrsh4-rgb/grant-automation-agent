import axios from 'axios';
import type {
  UploadResponse,
  PackageUploadResponse,
  GrantData,
  GenerateDocumentsRequest,
  GenerateDocumentsResponse,
  GrantListItem,
} from '../types';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const grantApi = {
  uploadGrantLetter: async (file: File): Promise<UploadResponse> => {
    const formData = new FormData();
    formData.append('files', file);
    const response = await api.post<UploadResponse[]>('/api/grants/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data[0];
  },

  uploadGrantLettersBatch: async (files: File[]): Promise<UploadResponse[]> => {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));
    const response = await api.post<UploadResponse[]>('/api/grants/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  },

  uploadGrantPackage: async (
    proposal?: File | null,
    awardLetter?: File | null,
    settings?: {
      redact_names: boolean;
      redact_salaries: boolean;
      redact_contact_details: boolean;
      enable_external_llm: boolean;
    }
  ): Promise<PackageUploadResponse> => {
    const formData = new FormData();
    if (proposal) formData.append('proposal', proposal);
    if (awardLetter) formData.append('award_letter', awardLetter);
    if (settings) {
      formData.append('redact_names', String(settings.redact_names));
      formData.append('redact_salaries', String(settings.redact_salaries));
      formData.append('redact_contact_details', String(settings.redact_contact_details));
      formData.append('enable_external_llm', String(settings.enable_external_llm));
    }
    const response = await api.post<PackageUploadResponse>('/api/grants/upload-package', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  },

  getGrantData: async (fileId: string): Promise<GrantData> => {
    const response = await api.get<GrantData>(`/api/grants/data/${fileId}`);
    return response.data;
  },

  listGrants: async (): Promise<{ grants: GrantListItem[] }> => {
    const response = await api.get<{ grants: GrantListItem[] }>('/api/grants/list');
    return response.data;
  },

  generateDocuments: async (request: GenerateDocumentsRequest): Promise<GenerateDocumentsResponse> => {
    const response = await api.post<GenerateDocumentsResponse>(`/api/grants/generate-documents/${request.file_id}`, request);
    return response.data;
  },
  deleteGrant: async (fileId: string): Promise<{ success: boolean; message: string }> => {
    const response = await api.delete<{ success: boolean; message: string }>(`/api/grants/${fileId}`);
    return response.data;
  },

  downloadDocument: (fileId: string, docType: string): string => `${API_URL}/api/grants/download/${fileId}/${docType}`,
};

export default api;
