import axios from 'axios';
import type {
  UploadResponse,
  PackageUploadResponse,
  GrantData,
  GenerateDocumentsRequest,
  GenerateDocumentsResponse,
  GrantListItem,
} from '../types';

const API_URL = import.meta.env.VITE_API_URL || 'https://ca-grants-backend.ambitioustree-e69e3f81.centralus.azurecontainerapps.io';

const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// ---- Auth token handling (portable: JWT in localStorage) ----
const TOKEN_KEY = 'gaa_token';
export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

// Attach the bearer token to every request.
api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers = config.headers ?? {};
    (config.headers as Record<string, string>).Authorization = `Bearer ${token}`;
  }
  return config;
});

// On 401, drop the token and bounce to login (unless we're already there).
api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error?.response?.status === 401) {
      clearToken();
      if (!window.location.pathname.startsWith('/login')) {
        window.location.assign('/login');
      }
    }
    return Promise.reject(error);
  }
);

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


// ---- Authentication API ----
export interface AuthUser {
  id: number;
  tenant_id: number;
  email: string;
  full_name?: string | null;
  role: string;
  is_active: boolean;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export const authApi = {
  login: async (email: string, password: string): Promise<LoginResponse> => {
    const res = await api.post<LoginResponse>('/api/auth/login', { email, password });
    return res.data;
  },
  me: async (): Promise<AuthUser> => {
    const res = await api.get<AuthUser>('/api/auth/me');
    return res.data;
  },
};
