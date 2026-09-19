import { Bell, BarChart3, FileCheck2, Fingerprint, HelpCircle, Home, KeyRound, LogOut, Menu, Plus, Settings, Users, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { setLanguage } from '../i18n'

const applicantLinks = [
  ['/app','home',Home], ['/app/new/document','newVerification',Plus], ['/app/applications','applications',FileCheck2], ['/app/help','help',HelpCircle], ['/app/settings','settings',Settings],
] as const
const adminLinks = [
  ['/admin','home',Home], ['/admin/applications','applications',FileCheck2], ['/admin/review','reviewQueue',Users], ['/admin/analytics','analytics',BarChart3], ['/admin/api','apiAccess',KeyRound], ['/admin/settings','settings',Settings],
] as const

export function Brand({dark=false}:{dark?:boolean}) { return <Link to="/" className={`brand ${dark?'brand-dark':''}`} aria-label="Shanakht home"><span className="brand-mark"><Fingerprint/></span><span>Shanakht</span></Link> }

export function AppLayout() {
  const {user,signOut}=useAuth(); const navigate=useNavigate(); const {t,i18n}=useTranslation(); const [open,setOpen]=useState(false)
  const role=user?.memberships[0]?.role || 'applicant'; const isAdmin=role==='admin'||role==='reviewer'; const links=isAdmin?adminLinks:applicantLinks
  const toggleLanguage=()=>setLanguage(i18n.language==='ur'?'en':'ur')
  return <div className="app-shell">
    <aside className={`sidebar ${open?'sidebar-open':''}`}>
      <div className="sidebar-head"><Brand dark/><button className="icon-button mobile-only" onClick={()=>setOpen(false)} aria-label="Close menu"><X/></button></div>
      <nav>{links.map(([to,label,Icon])=><NavLink end={to==='/app'||to==='/admin'} key={to} to={to} onClick={()=>setOpen(false)}><Icon/><span>{t(label)}</span></NavLink>)}</nav>
      <div className="sidebar-art" aria-hidden="true"><Fingerprint/><span></span></div>
      <div className="sidebar-foot"><p>{user?.memberships[0]?.organization||'Workspace'}</p><button onClick={async()=>{await signOut();navigate('/auth')}}><LogOut/>{t('signOut')}</button><small>People <i/> Trust <i/> Clarity</small></div>
    </aside>
    <div className="workspace">
      <header className="topbar"><button className="icon-button mobile-only" onClick={()=>setOpen(true)} aria-label="Open menu"><Menu/></button><div/><button className="language" onClick={toggleLanguage}>EN <span/> اردو</button><button className="icon-button" aria-label="Notifications"><Bell/></button><span className="avatar">{user?.username?.slice(0,1).toUpperCase()||'A'}</span><strong>{user?.username}</strong></header>
      <main className="page"><Outlet/></main>
    </div>
  </div>
}

export function RequireAuth() { const {user,loading}=useAuth(); if(loading)return <FullState title="Loading workspace…"/>; if(!user)return <NavigateToAuth/>; return <Outlet/> }
function NavigateToAuth(){const navigate=useNavigate(); setTimeout(()=>navigate('/auth',{replace:true}),0); return <FullState title="Sign in required"/>}
export function FullState({title,detail}:{title:string;detail?:string}){return <div className="full-state"><Fingerprint/><h2>{title}</h2>{detail&&<p>{detail}</p>}</div>}

export function PageTitle({title,subtitle,action}:{title:string;subtitle?:string;action?:React.ReactNode}){return <div className="page-title"><div><h1>{title}</h1>{subtitle&&<p>{subtitle}</p>}</div>{action}</div>}
export function StatusBadge({value}:{value:string}){const clean=value.replaceAll('_',' ');return <span className={`status status-${value}`}>{clean}</span>}
export function Stepper({active}:{active:number}){return <ol className="stepper">{['Document','Selfie','Liveness','Review'].map((label,index)=><li className={index+1<=active?'active':''} key={label}><span>{index+1<active?'✓':index+1}</span><b>{label}</b></li>)}</ol>}
