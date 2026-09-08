import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { grantApi } from '../services/api';
import type { GenerateDocumentsRequest, GrantDataPatch } from '../types';

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

/** Correct a field on the working copy. The reply is the updated record, so
 *  the query cache is set from it rather than refetched. */
export const useEditGrantData = (fileId: string | undefined) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (patch: GrantDataPatch) => grantApi.patchGrantData(fileId!, patch),
    onSuccess: (data) => queryClient.setQueryData(['grant', fileId], data),
  });
};

export const useConfirmGrant = (fileId: string | undefined) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => grantApi.confirmGrant(fileId!),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['grants'] }),
  });
};

export const usePersistenceMode = () =>
  useQuery({
    queryKey: ['persistence-mode'],
    queryFn: () => grantApi.getPersistenceMode(),
    staleTime: Infinity,
  });
