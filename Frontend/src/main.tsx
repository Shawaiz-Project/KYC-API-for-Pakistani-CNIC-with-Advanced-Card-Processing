import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './i18n'
import './styles.css'
import { AuthProvider, useAuth } from './auth'
import { AppLayout, FullState, RequireAuth } from './components/Layout'
import { VerificationProvider } from './verification'
import { AuthPage, Landing, LegalPage } from './pages/PublicPages'
import { AdminOverview, ApplicantHome, ApplicationsPage } from './pages/Dashboards'
import { DocumentCapture, LivenessPage, ReviewCapture, SelfieCapture } from './pages/CapturePages'
import { PlaceholderPage, ResultsPage, ReviewQueue, ReviewerWorkspace } from './pages/ReviewPages'
import { APIAccessPage, WorkspaceSettingsPage } from './pages/AdminPages'

const queryClient=new QueryClient({defaultOptions:{queries:{staleTime:15_000,retry:1}}})

function RoleGate({admin=false,children}:{admin?:boolean;children:React.ReactNode}){const {user}=useAuth();const role=user?.memberships[0]?.role;const allowed=admin?role==='admin'||role==='reviewer':role==='applicant'||role==='admin';return allowed?<>{children}</>:<FullState title="Access denied" detail="Your organization role does not permit this page."/>}

function App(){return <Routes>
  <Route path="/" element={<Landing/>}/><Route path="/auth" element={<AuthPage/>}/><Route path="/privacy" element={<LegalPage title="Privacy policy"/>}/><Route path="/terms" element={<LegalPage title="Terms of service"/>}/><Route path="/support" element={<LegalPage title="Help and support"/>}/>
  <Route element={<RequireAuth/>}><Route element={<AppLayout/>}>
    <Route path="/app" element={<RoleGate><ApplicantHome/></RoleGate>}/><Route path="/app/new/document" element={<RoleGate><DocumentCapture/></RoleGate>}/><Route path="/app/new/selfie" element={<RoleGate><SelfieCapture/></RoleGate>}/><Route path="/app/new/liveness" element={<RoleGate><LivenessPage/></RoleGate>}/><Route path="/app/new/review" element={<RoleGate><ReviewCapture/></RoleGate>}/><Route path="/app/applications" element={<RoleGate><ApplicationsPage/></RoleGate>}/><Route path="/app/results/:id" element={<RoleGate><ResultsPage/></RoleGate>}/><Route path="/app/help" element={<PlaceholderPage title="Help"/>}/><Route path="/app/settings" element={<PlaceholderPage title="Settings"/>}/>
    <Route path="/admin" element={<RoleGate admin><AdminOverview/></RoleGate>}/><Route path="/admin/applications" element={<RoleGate admin><ApplicationsPage/></RoleGate>}/><Route path="/admin/review" element={<RoleGate admin><ReviewQueue/></RoleGate>}/><Route path="/admin/review/:id" element={<RoleGate admin><ReviewerWorkspace/></RoleGate>}/><Route path="/admin/analytics" element={<RoleGate admin><PlaceholderPage title="Analytics"/></RoleGate>}/><Route path="/admin/api" element={<RoleGate admin><APIAccessPage/></RoleGate>}/><Route path="/admin/settings" element={<RoleGate admin><WorkspaceSettingsPage/></RoleGate>}/>
  </Route></Route><Route path="*" element={<Navigate to="/" replace/>}/>
  </Routes>}

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><QueryClientProvider client={queryClient}><AuthProvider><VerificationProvider><BrowserRouter><App/></BrowserRouter></VerificationProvider></AuthProvider></QueryClientProvider></React.StrictMode>)
