import { useState } from 'react'
import { Alert, Button, Code, Group, Loader, Modal, Paper, Stack, Text, Textarea, TextInput, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type Project } from './api'
import { useAuth } from './auth'

type DocumentSummary = { id: string; rev: string }
type DocumentPage = { items: DocumentSummary[]; next_offset: number | null }

export function Documents({ project }: { project: Project }) {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  const base = `/projects/${project.id}/documents`
  const [opened, setOpened] = useState(false)
  const [documentId, setDocumentId] = useState('')
  const [documentJson, setDocumentJson] = useState('{}')
  const [loadingDocument, setLoadingDocument] = useState(false)
  const [isNew, setIsNew] = useState(false)
  const documents = useInfiniteQuery({
    queryKey: ['documents', project.id],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => api<DocumentPage>(`${base}?skip=${pageParam}`, token!),
    getNextPageParam: page => page.next_offset,
  })
  const items = documents.data?.pages.flatMap(page => page.items) ?? []
  const showError = (error: unknown) => notifications.show({ color: 'red', title: 'Document request failed', message: error instanceof Error ? error.message : String(error) })
  const save = useMutation({
    mutationFn: async () => {
      const parsed: unknown = JSON.parse(documentJson)
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('Enter a JSON object')
      if (!documentId.trim() || documentId.startsWith('_') || documentId.includes('/')) throw new Error('Enter a document ID without a leading underscore or slash')
      return api(`${base}/${encodeURIComponent(documentId)}`, token!, { method: 'PUT', body: JSON.stringify(parsed) })
    },
    onSuccess: () => { setOpened(false); void queryClient.invalidateQueries({ queryKey: ['documents', project.id] }) },
    onError: showError,
  })
  const remove = useMutation({
    mutationFn: (item: DocumentSummary) => api(`${base}/${encodeURIComponent(item.id)}?rev=${encodeURIComponent(item.rev)}`, token!, { method: 'DELETE' }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['documents', project.id] }),
    onError: showError,
  })
  const openNew = () => { setIsNew(true); setDocumentId(''); setDocumentJson('{}'); setOpened(true) }
  const openExisting = async (id: string) => {
    setLoadingDocument(true)
    try {
      const document = await api<Record<string, unknown>>(`${base}/${encodeURIComponent(id)}`, token!)
      setIsNew(false)
      setDocumentId(id)
      setDocumentJson(JSON.stringify(document, null, 2))
      setOpened(true)
    } catch (error) { showError(error) }
    finally { setLoadingDocument(false) }
  }
  return <Paper withBorder p="lg">
    <Group justify="space-between" mb="md"><div><Title order={3}>Documents</Title><Text size="sm" c="dimmed">JSON documents in this project's CouchDB database.</Text></div>{project.role === 'admin' && <Button size="sm" onClick={openNew}>New document</Button>}</Group>
    {documents.isLoading && <Loader size="sm" />}
    {documents.isError && <Alert color="red">Could not load documents.</Alert>}
    {items.length === 0 && !documents.isLoading && !documents.isError && <Text size="sm" c="dimmed">No documents yet.</Text>}
    <Stack gap="xs">{items.map(item => <Group key={item.id} justify="space-between"><div><Code>{item.id}</Code><Text size="xs" c="dimmed">Revision {item.rev}</Text></div><Group><Button size="xs" variant="subtle" loading={loadingDocument} onClick={() => void openExisting(item.id)}>{project.role === 'admin' ? 'Edit' : 'View'}</Button>{project.role === 'admin' && <Button size="xs" variant="subtle" color="red" onClick={() => { if (window.confirm(`Delete ${item.id}?`)) remove.mutate(item) }}>Delete</Button>}</Group></Group>)}</Stack>
    {documents.hasNextPage && <Button mt="md" size="sm" variant="subtle" loading={documents.isFetchingNextPage} onClick={() => void documents.fetchNextPage()}>Load more</Button>}
    <Modal opened={opened} onClose={() => setOpened(false)} title={isNew ? 'New document' : `Document ${documentId}`} size="lg" centered><Stack><TextInput label="Document ID" value={documentId} onChange={event => setDocumentId(event.currentTarget.value)} readOnly={!isNew || project.role !== 'admin'} /><Textarea label="JSON" value={documentJson} onChange={event => setDocumentJson(event.currentTarget.value)} readOnly={project.role !== 'admin'} minRows={12} autosize styles={{ input: { fontFamily: 'monospace' } }} />{project.role === 'admin' && <Button loading={save.isPending} onClick={() => save.mutate()}>Save document</Button>}</Stack></Modal>
  </Paper>
}
