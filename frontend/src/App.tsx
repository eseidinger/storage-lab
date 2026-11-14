import { useEffect, useState } from 'react'
import { Alert, AppShell, Badge, Box, Button, Card, Code, Container, Divider, Group, Loader, Modal, Paper, Select, SimpleGrid, Stack, Text, TextInput, Title } from '@mantine/core'
import { useForm } from '@mantine/form'
import { notifications } from '@mantine/notifications'
import { IconArrowLeft, IconDatabase, IconFileText, IconLogout, IconPlus, IconServer, IconTrash } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BrowserRouter, Link, Route, Routes, useNavigate, useParams } from 'react-router'
import { api, type Capability, type Credential, type CurrentUser, type IssuedCredential, type Member, type Operation, type PlatformAdmin, type Project, type StoredObject } from './api'
import { AuthProvider, useAuth } from './auth'
import { Documents } from './Documents'
import './App.css'

const kinds = {
  postgresql: { label: 'PostgreSQL', description: 'A private application database.', icon: IconDatabase },
  'object-storage': { label: 'Object storage', description: 'A private S3 bucket for files and artifacts.', icon: IconServer },
  documents: { label: 'Documents', description: 'A private CouchDB database for JSON documents.', icon: IconFileText },
  'key-value': { label: 'Key-value', description: 'A private Valkey key namespace.', icon: IconDatabase },
  analytics: { label: 'Analytics', description: 'A private ClickHouse database.', icon: IconDatabase },
  vectors: { label: 'Vectors', description: 'A private Qdrant collection with 1536-dimensional vectors.', icon: IconDatabase },
  search: { label: 'Search', description: 'A private OpenSearch index and dashboard tenant.', icon: IconDatabase },
  graph: { label: 'Graph', description: 'A private HugeGraph graph with graph-scoped access.', icon: IconDatabase },
  events: { label: 'Events', description: 'A private NATS account with JetStream.', icon: IconServer },
} as const
type Kind = keyof typeof kinds
const notifyError = (error: unknown) => notifications.show({ color: 'red', title: 'Request failed', message: error instanceof Error ? error.message : String(error) })

function Shell({ children }: { children: React.ReactNode }) {
  const { user, token, logout } = useAuth()
  const queryClient = useQueryClient()
  const currentUser = useQuery({ queryKey: ['me'], queryFn: () => api<CurrentUser>('/me', token!), enabled: !!token })
  return <AppShell header={{ height: 70 }} padding="md">
    <AppShell.Header className="shell-header"><Container size="lg" h="100%"><Group h="100%" justify="space-between">
      <Group gap="sm"><Box className="brand-mark">S</Box><Text fw={800} size="lg">Storage Lab</Text><Badge variant="light" color="cyan">Development</Badge></Group>
      <Group gap="sm">{currentUser.data?.platform_admin && <Badge color="violet" variant="light">Platform Admin</Badge>}<Text size="sm" c="dimmed" visibleFrom="sm">{user?.profile.preferred_username ?? user?.profile.sub}</Text><Button size="xs" variant="subtle" leftSection={<IconLogout size={16} />} onClick={() => { queryClient.clear(); void logout() }}>Sign out</Button></Group>
    </Group></Container></AppShell.Header>
    <AppShell.Main><Container size="lg" py="xl">{children}</Container></AppShell.Main>
  </AppShell>
}

function Home() {
  const { token } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [opened, setOpened] = useState(false)
  const form = useForm({ initialValues: { name: '' }, validate: { name: value => value.trim() ? null : 'Enter a project name' } })
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects', token!) })
  const currentUser = useQuery({ queryKey: ['me'], queryFn: () => api<CurrentUser>('/me', token!) })
  const create = useMutation({ mutationFn: (name: string) => api<Project>('/projects', token!, { method: 'POST', body: JSON.stringify({ name }) }), onSuccess: project => { setOpened(false); form.reset(); void queryClient.invalidateQueries({ queryKey: ['projects'] }); navigate(`/projects/${project.id}`) }, onError: notifyError })
  return <Shell><Stack gap="xl">
    <Box className="hero-panel"><Text className="eyebrow">PROJECT STORAGE</Text><Title order={1}>Your data services, in one place.</Title><Text c="dimmed" mt="xs">Create a project, enable a service, and track provisioning from this portal.</Text><Button mt="xl" leftSection={<IconPlus size={18} />} onClick={() => setOpened(true)}>New project</Button></Box>
    <Group justify="space-between"><Title order={2}>Projects</Title><Text c="dimmed" size="sm">{projects.data?.length ?? 0} available</Text></Group>
    {projects.isLoading && <Loader />}{projects.isError && <Alert color="red">{String(projects.error)}</Alert>}
    {projects.data?.length === 0 && <Paper p="xl" withBorder><Text c="dimmed">No projects yet. Create one to get started.</Text></Paper>}
    <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>{projects.data?.map(project => <Card key={project.id} component={Link} to={`/projects/${project.id}`} className="project-card" withBorder padding="lg"><Group justify="space-between"><Box className="project-icon"><IconServer size={22} /></Box><Badge variant="light">{project.role}</Badge></Group><Title order={3} mt="lg">{project.name}</Title><Text size="xs" c="dimmed" mt="sm">ID {project.id.slice(0, 12)}</Text></Card>)}</SimpleGrid>
    {currentUser.data?.platform_admin && <PlatformAdmins />}
    <Modal opened={opened} onClose={() => setOpened(false)} title="Create project" centered><form onSubmit={form.onSubmit(values => create.mutate(values.name.trim()))}><Stack><TextInput label="Project name" placeholder="e.g. Analytics sandbox" required {...form.getInputProps('name')} /><Button type="submit" loading={create.isPending}>Create project</Button></Stack></form></Modal>
  </Stack></Shell>
}

function PlatformAdmins() {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  const [issuer, setIssuer] = useState(import.meta.env.VITE_OIDC_AUTHORITY ?? '')
  const [subject, setSubject] = useState('')
  const admins = useQuery({ queryKey: ['platform-admins'], queryFn: () => api<PlatformAdmin[]>('/platform-admins', token!) })
  const add = useMutation({ mutationFn: () => api<PlatformAdmin>('/platform-admins', token!, { method: 'POST', body: JSON.stringify({ issuer, subject }) }), onSuccess: () => { setSubject(''); void queryClient.invalidateQueries({ queryKey: ['platform-admins'] }) }, onError: notifyError })
  const remove = useMutation({ mutationFn: (admin: PlatformAdmin) => api<void>('/platform-admins', token!, { method: 'DELETE', body: JSON.stringify({ issuer: admin.issuer, subject: admin.subject }) }), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['platform-admins'] }); void queryClient.invalidateQueries({ queryKey: ['me'] }); void queryClient.invalidateQueries({ queryKey: ['projects'] }) }, onError: notifyError })
  return <Paper withBorder p="lg"><Title order={2} mb="md">Platform administrators</Title><Stack gap="xs">{admins.data?.map(admin => <Group key={`${admin.issuer}:${admin.subject}`} justify="space-between"><Box><Text size="sm">{admin.subject}</Text><Text size="xs" c="dimmed">{admin.issuer}</Text></Box><Button size="xs" color="red" variant="subtle" disabled={admins.data.length <= 1} loading={remove.isPending} onClick={() => remove.mutate(admin)}>Remove</Button></Group>)}</Stack><Divider my="lg" /><Text fw={700} size="sm" mb="sm">Add platform administrator</Text><SimpleGrid cols={{ base: 1, sm: 3 }}><TextInput label="Issuer" value={issuer} onChange={event => setIssuer(event.currentTarget.value)} /><TextInput label="Subject" value={subject} onChange={event => setSubject(event.currentTarget.value)} /><Button mt="xl" disabled={!issuer.trim() || !subject.trim()} loading={add.isPending} onClick={() => add.mutate()}>Add</Button></SimpleGrid></Paper>
}

function CapabilityCard({ project, kind, capability }: { project: Project; kind: Kind; capability?: Capability }) {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  const [operationId, setOperationId] = useState<string | null>(null)
  const [issued, setIssued] = useState<IssuedCredential | null>(null)
  const [revealed, setRevealed] = useState<{ username: string; secret: string } | null>(null)
  const [issueOpen, setIssueOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [access, setAccess] = useState<'runtime' | 'migration'>('runtime')
  const [confirmation, setConfirmation] = useState('')
  const base = `/projects/${project.id}/capabilities/${kind}`
  const info = kinds[kind]
  const Icon = info.icon
  const admin = project.role === 'admin'
  const credentials = useQuery({ queryKey: ['credentials', project.id, kind], queryFn: () => api<Credential[]>(`${base}/credentials`, token!), enabled: admin && capability?.state === 'ready' })
  const operation = useQuery({ queryKey: ['operation', operationId], queryFn: () => api<Operation>(`/operations/${operationId}`, token!), enabled: !!operationId, refetchInterval: query => ['succeeded', 'failed'].includes(query.state.data?.state ?? '') ? false : 1500 })
  useEffect(() => { if (['succeeded', 'failed'].includes(operation.data?.state ?? '')) { void queryClient.invalidateQueries({ queryKey: ['capabilities', project.id] }); void queryClient.invalidateQueries({ queryKey: ['credentials', project.id, kind] }) } }, [operation.data?.state, project.id, kind, queryClient])
  const retry = useMutation({ mutationFn: () => api<Operation>(`/operations/${operationId}/retry`, token!, { method: 'POST' }), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['operation', operationId] }); void queryClient.invalidateQueries({ queryKey: ['capabilities', project.id] }) }, onError: notifyError })
  const enable = useMutation({ mutationFn: () => api<Operation>(base, token!, { method: 'PUT' }), onSuccess: result => { setOperationId(result.id); void queryClient.invalidateQueries({ queryKey: ['capabilities', project.id] }) }, onError: notifyError })
  const issue = useMutation({ mutationFn: () => api<IssuedCredential>(`${base}/credentials`, token!, { method: 'POST', body: JSON.stringify({ label, access }) }), onSuccess: result => { setIssued(result); setOperationId(result.operation.id); setLabel(''); setAccess('runtime'); void queryClient.invalidateQueries({ queryKey: ['credentials', project.id, kind] }) }, onError: notifyError })
  const claim = useMutation({ mutationFn: (id: string) => api<{ secret: string }>(`${base}/credentials/${id}/secret`, token!, { method: 'POST' }), onSuccess: (result, id) => { if (issued?.credential.id === id && issueOpen) setIssued({ ...issued, secret: result.secret }); else setRevealed({ username: credentials.data?.find(item => item.id === id)?.username ?? id, secret: result.secret }); void queryClient.invalidateQueries({ queryKey: ['credentials', project.id, kind] }) }, onError: notifyError })
  const revoke = useMutation({ mutationFn: (id: string) => api<Operation>(`${base}/credentials/${id}`, token!, { method: 'DELETE' }), onSuccess: result => { setOperationId(result.id); void queryClient.invalidateQueries({ queryKey: ['credentials', project.id, kind] }) }, onError: notifyError })
  const remove = useMutation({ mutationFn: () => api<Operation>(base, token!, { method: 'DELETE', body: JSON.stringify({ confirm_name: confirmation }) }), onSuccess: result => { setDeleteOpen(false); setConfirmation(''); setOperationId(result.id); void queryClient.invalidateQueries({ queryKey: ['capabilities', project.id] }) }, onError: notifyError })
  return <Card withBorder padding="lg" className="capability-card"><Group justify="space-between" align="flex-start"><Group><Box className="project-icon"><Icon size={22} /></Box><Box><Title order={3}>{info.label}</Title><Text size="sm" c="dimmed">{info.description}</Text></Box></Group><Badge color={capability?.state === 'ready' ? 'teal' : capability?.state === 'failed' ? 'red' : 'gray'}>{capability?.state ?? 'not enabled'}</Badge></Group>
    {capability?.error && <Alert mt="md" color="red">{capability.error}</Alert>}
    {capability?.endpoint && <Paper mt="lg" p="md" className="connection-panel"><Text fw={700} size="sm" mb="xs">Connection details</Text>{Object.entries(capability.endpoint).map(([key, value]) => <Group key={key} justify="space-between" gap="xs"><Text size="sm" c="dimmed">{key}</Text><Code>{String(value)}</Code></Group>)}{kind === 'postgresql' && <Text size="xs" c="dimmed" mt="sm">Use TLS with certificate verification. Migration credentials must run SET ROLE {String(capability.endpoint.migration_role)} before creating tables.</Text>}</Paper>}
    {operation.data && <Group mt="sm" gap="xs"><Text size="sm" c={operation.data.state === 'failed' ? 'red' : 'dimmed'}>Last operation: {operation.data.state}{operation.data.error ? ` · ${operation.data.error}` : ''}</Text>{admin && operation.data.state === 'failed' && operation.data.attempts < 5 && <Button size="xs" variant="subtle" loading={retry.isPending} onClick={() => retry.mutate()}>Retry operation</Button>}</Group>}
    {admin && <Group mt="lg"><Button size="sm" variant="light" onClick={() => enable.mutate()} loading={enable.isPending} disabled={['ready', 'pending', 'deleting'].includes(capability?.state ?? '')}>{capability?.state === 'failed' ? 'Retry provisioning' : 'Enable'}</Button>{capability?.state === 'ready' && <><Button size="sm" variant="subtle" onClick={() => setIssueOpen(true)}>Issue credential</Button><Button size="sm" variant="subtle" color="red" leftSection={<IconTrash size={15} />} onClick={() => setDeleteOpen(true)}>Delete</Button></>}</Group>}
    {admin && !!credentials.data?.length && <><Divider my="lg" /><Text fw={700} size="sm" mb="xs">Workload credentials</Text>{credentials.data.map(item => <Group key={item.id} justify="space-between" py={5}><Box><Text size="sm">{item.label}</Text><Text size="xs" c="dimmed">{item.username} · {item.access} · {item.state}</Text></Box><Group>{item.delivery_pending && <Button size="xs" variant="subtle" loading={claim.isPending} onClick={() => claim.mutate(item.id)}>Claim secret</Button>}<Button size="xs" variant="subtle" color="red" onClick={() => revoke.mutate(item.id)}>Revoke</Button></Group></Group>)}</>}
    <Modal opened={issueOpen} onClose={() => { setIssueOpen(false); setIssued(null) }} title="Issue workload credential" centered>{issued ? <Stack><Alert color="yellow">Copy this secret now. It will not be shown again.</Alert><Text size="sm">Username: <Code>{issued.credential.username}</Code></Text>{issued.secret === null ? <><Text size="sm">Provisioning: {operation.data?.state ?? 'pending'}</Text><Button disabled={operation.data?.state !== 'succeeded'} loading={claim.isPending} onClick={() => claim.mutate(issued.credential.id)}>Claim secret</Button></> : <><Code className="secret-value">{issued.secret}</Code><Button onClick={() => { void navigator.clipboard.writeText(issued.secret ?? ''); notifications.show({ message: 'Secret copied' }) }}>Copy secret</Button></>}</Stack> : <Stack><TextInput label="Workload label" placeholder="e.g. application" value={label} onChange={event => setLabel(event.currentTarget.value)} />{kind === 'postgresql' && <Select label="Access" data={[{ value: 'runtime', label: 'Runtime (data only)' }, { value: 'migration', label: 'Migration (schema changes)' }]} value={access} onChange={value => setAccess(value === 'migration' ? 'migration' : 'runtime')} />}<Button disabled={!label.trim()} loading={issue.isPending} onClick={() => issue.mutate()}>Issue credential</Button></Stack>}</Modal>
    <Modal opened={revealed !== null} onClose={() => setRevealed(null)} title="Workload secret" centered>{revealed && <Stack><Alert color="yellow">Copy this secret now. It will not be shown again.</Alert><Text size="sm">Username: <Code>{revealed.username}</Code></Text><Code className="secret-value">{revealed.secret}</Code><Button onClick={() => { void navigator.clipboard.writeText(revealed.secret); notifications.show({ message: 'Secret copied' }) }}>Copy secret</Button></Stack>}</Modal>
    <Modal opened={deleteOpen} onClose={() => setDeleteOpen(false)} title={`Delete ${info.label}`} centered><Stack><Alert color="red">This deletes the service resource and its data. Enter the project name to confirm.</Alert><TextInput label="Project name" value={confirmation} onChange={event => setConfirmation(event.currentTarget.value)} /><Button color="red" disabled={confirmation !== project.name} loading={remove.isPending} onClick={() => remove.mutate()}>Delete resource</Button></Stack></Modal>
  </Card>
}

function Members({ project }: { project: Project }) {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  const [issuer, setIssuer] = useState(import.meta.env.VITE_OIDC_AUTHORITY ?? '')
  const [subject, setSubject] = useState('')
  const [role, setRole] = useState<string | null>('viewer')
  const members = useQuery({ queryKey: ['members', project.id], queryFn: () => api<Member[]>(`/projects/${project.id}/members`, token!) })
  const add = useMutation({ mutationFn: () => api<Member>(`/projects/${project.id}/members`, token!, { method: 'POST', body: JSON.stringify({ issuer, subject, role }) }), onSuccess: () => { setSubject(''); void queryClient.invalidateQueries({ queryKey: ['members', project.id] }) }, onError: notifyError })
  return <Paper withBorder p="lg"><Title order={3} mb="md">Members</Title><Stack gap="xs">{members.data?.map(member => <Group key={`${member.issuer}:${member.subject}`} justify="space-between"><Text size="sm">{member.subject}</Text><Badge variant="light">{member.role}</Badge></Group>)}</Stack>{project.role === 'admin' && <><Divider my="lg" /><Text size="sm" fw={700} mb="sm">Add or update a member</Text><SimpleGrid cols={{ base: 1, sm: 3 }}><TextInput label="Issuer" value={issuer} onChange={event => setIssuer(event.currentTarget.value)} /><TextInput label="Subject" value={subject} onChange={event => setSubject(event.currentTarget.value)} /><Select label="Role" data={['viewer', 'admin']} value={role} onChange={setRole} /></SimpleGrid><Button mt="md" size="sm" disabled={!issuer || !subject || !role} loading={add.isPending} onClick={() => add.mutate()}>Save member</Button></>}</Paper>
}

function Objects({ project }: { project: Project }) {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  const path = `/projects/${project.id}/objects`
  const objects = useQuery({ queryKey: ['objects', project.id], queryFn: () => api<StoredObject[]>(path, token!) })
  const upload = useMutation({ mutationFn: async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    const response = await fetch(`${import.meta.env.VITE_API_URL ?? '/api'}${path}`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: form })
    if (!response.ok) throw new Error(`Upload failed: HTTP ${response.status}`)
  }, onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['objects', project.id] }), onError: notifyError })
  const remove = useMutation({ mutationFn: (key: string) => api(`${path}?key=${encodeURIComponent(key)}`, token!, { method: 'DELETE' }), onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['objects', project.id] }), onError: notifyError })
  const download = async (key: string) => {
    try {
      const response = await fetch(`${import.meta.env.VITE_API_URL ?? '/api'}${path}/download?key=${encodeURIComponent(key)}`, { headers: { Authorization: `Bearer ${token}` } })
      if (!response.ok) throw new Error(`Download failed: HTTP ${response.status}`)
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a')
      link.href = url
      link.download = key.split('/').pop() || key
      link.click()
      URL.revokeObjectURL(url)
    } catch (error) { notifyError(error) }
  }
  return <Paper withBorder p="lg"><Group justify="space-between" mb="md"><Box><Title order={3}>Objects</Title><Text size="sm" c="dimmed">Files in this project's private S3 bucket.</Text></Box>{project.role === 'admin' && <Button component="label" size="sm" loading={upload.isPending}>Upload<input type="file" hidden onChange={event => { const file = event.currentTarget.files?.[0]; if (file) upload.mutate(file); event.currentTarget.value = '' }} /></Button>}</Group>
    {objects.isLoading && <Loader size="sm" />}{objects.isError && <Alert color="red">Could not load objects.</Alert>}{objects.data?.length === 0 && <Text c="dimmed" size="sm">No objects yet.</Text>}
    <Stack gap="xs">{objects.data?.map(item => <Group key={item.key} justify="space-between"><Box><Text size="sm">{item.key}</Text><Text size="xs" c="dimmed">{item.size} bytes</Text></Box><Group><Button size="xs" variant="subtle" onClick={() => void download(item.key)}>Download</Button>{project.role === 'admin' && <Button size="xs" color="red" variant="subtle" onClick={() => { if (window.confirm(`Delete ${item.key}?`)) remove.mutate(item.key) }}>Delete</Button>}</Group></Group>)}</Stack>
  </Paper>
}

function ProjectDetail() {
  const { projectId } = useParams()
  const { token } = useAuth()
  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => api<Project>(`/projects/${projectId}`, token!), enabled: !!projectId })
  const capabilities = useQuery({ queryKey: ['capabilities', projectId], queryFn: () => api<Capability[]>(`/projects/${projectId}/capabilities`, token!), enabled: !!projectId, refetchInterval: query => query.state.data?.some(item => ['pending', 'deleting'].includes(item.state)) ? 2000 : false })
  if (project.isLoading) return <Shell><Loader /></Shell>
  if (project.isError || !project.data) return <Shell><Alert color="red">Project could not be loaded.</Alert></Shell>
  return <Shell><Stack gap="xl"><Box><Button component={Link} to="/" variant="subtle" leftSection={<IconArrowLeft size={16} />} px={0}>All projects</Button><Group justify="space-between" mt="md"><Box><Text className="eyebrow">PROJECT</Text><Title order={1}>{project.data.name}</Title><Text c="dimmed" size="sm">{project.data.id}</Text></Box><Badge size="lg" variant="light">{project.data.role}</Badge></Group></Box><Box><Title order={2} mb="md">Capabilities</Title><SimpleGrid cols={{ base: 1, md: 2 }}>{(Object.keys(kinds) as Kind[]).map(kind => <CapabilityCard key={kind} project={project.data!} kind={kind} capability={capabilities.data?.find(item => item.kind === kind)} />)}</SimpleGrid></Box>{capabilities.data?.some(item => item.kind === 'object-storage' && item.state === 'ready') && <Objects project={project.data} />}{capabilities.data?.some(item => item.kind === 'documents' && item.state === 'ready') && <Documents project={project.data} />}<Members project={project.data} /></Stack></Shell>
}

function AuthCallback() {
  const { finishLogin } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState('')
  useEffect(() => { void finishLogin().then(() => navigate('/', { replace: true })).catch(err => setError(String(err))) }, [finishLogin, navigate])
  return <Container py="xl">{error ? <Alert color="red">{error}</Alert> : <Loader />}</Container>
}

function PortalRoutes() {
  const { user, loading, configured, login } = useAuth()
  const [loginError, setLoginError] = useState('')
  const [signingIn, setSigningIn] = useState(false)
  const signIn = async () => {
    setLoginError('')
    setSigningIn(true)
    try {
      await login()
    } catch (error) {
      setLoginError(error instanceof TypeError
        ? `Could not load the identity provider at ${import.meta.env.VITE_OIDC_AUTHORITY}. Check that it is reachable, then try again.`
        : error instanceof Error ? error.message : String(error))
      setSigningIn(false)
    }
  }
  if (!configured) return <Container py="xl"><Alert color="yellow" title="OIDC is not configured">Set VITE_OIDC_AUTHORITY, VITE_OIDC_CLIENT_ID, and VITE_API_URL before starting the portal.</Alert></Container>
  if (loading) return <Container py="xl"><Loader /></Container>
  return <Routes><Route path="/auth/callback" element={<AuthCallback />} />{!user ? <Route path="*" element={<Container py="xl"><Paper p="xl" withBorder><Title order={1}>Storage Lab</Title><Text c="dimmed" my="md">Sign in to manage your project data services.</Text>{loginError && <Alert color="red" title="Sign-in could not start" mb="md">{loginError}</Alert>}<Button loading={signingIn} onClick={() => void signIn()}>Sign in</Button></Paper></Container>} /> : <><Route path="/" element={<Home />} /><Route path="/projects/:projectId" element={<ProjectDetail />} /></>}</Routes>
}

export default function App() { return <BrowserRouter><AuthProvider><PortalRoutes /></AuthProvider></BrowserRouter> }
