import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { grantApi } from '../services/api';
import type { GenerateDocumentsRequest } from '../types';

export const useUploadGrant = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => grantApi.uploadGrantLetter(file),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['grants'] }),
  });
};

export const useUploadGrantBatch = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (files: File[]) => grantApi.uploadGrantLettersBatch(files),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['grants'] }),
  });
};

export const useUploadGrantPackage = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: { proposal?: File | null; awardLetter?: File | null; settings: { redact_names: boolean; redact_salaries: boolean; redact_contact_details: boolean; enable_external_llm: boolean } }) =>
      grantApi.uploadGrantPackage(params.proposal, params.awardLetter, params.settings),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['grants'] }),
  });
};

export const useGrantData = (fileId: string | undefined) => {
  return useQuery({
    queryKey: ['grant', fileId],
    queryFn: () => grantApi.getGrantData(fileId!),
    enabled: !!fileId,
  });
};

export const useGrantsList = () => {
  return useQuery({
    queryKey: ['grants'],
    queryFn: () => grantApi.listGrants(),
  });
};

export const useGenerateDocuments = () => {
  return useMutation({
    mutationFn: (request: GenerateDocumentsRequest) => grantApi.generateDocuments(request),
  });
};


export const useDeleteGrant = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (fileId: string) => grantApi.deleteGrant(fileId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['grants'] });
    },
  });
};
