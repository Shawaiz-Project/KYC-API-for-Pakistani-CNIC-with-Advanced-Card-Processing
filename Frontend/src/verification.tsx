import { createContext, useContext, useMemo, useState } from 'react'
import { applicationsApi } from './api'

type CaptureKind='front'|'back'|'selfie'
type VerificationValue={applicationId:string|null;files:Partial<Record<CaptureKind,File>>;previews:Partial<Record<CaptureKind,string>>;busy:boolean;error:string|null;detectedFields:Record<string,any>;capture:(kind:CaptureKind,file:File)=>Promise<void>;reset:()=>void}
const Context=createContext<VerificationValue|null>(null)

export function VerificationProvider({children}:{children:React.ReactNode}){
  const [applicationId,setApplicationId]=useState<string|null>(null); const [files,setFiles]=useState<Partial<Record<CaptureKind,File>>>({}); const [previews,setPreviews]=useState<Partial<Record<CaptureKind,string>>>({}); const [busy,setBusy]=useState(false); const [error,setError]=useState<string|null>(null); const [detectedFields,setDetectedFields]=useState<Record<string,any>>({})
  const capture=async(kind:CaptureKind,file:File)=>{setBusy(true);setError(null);try{let id=applicationId;if(!id){id=(await applicationsApi.create()).id;setApplicationId(id)}const resp=await applicationsApi.upload(id,kind,file);if(resp?.extracted_fields){setDetectedFields(old=>({...old,...resp.extracted_fields}))}setFiles(old=>({...old,[kind]:file}));setPreviews(old=>{if(old[kind])URL.revokeObjectURL(old[kind]!);return {...old,[kind]:URL.createObjectURL(file)}})}catch(reason){setError(reason instanceof Error?reason.message:'Upload failed');throw reason}finally{setBusy(false)}}
  const reset=()=>{Object.values(previews).forEach(url=>url&&URL.revokeObjectURL(url));setApplicationId(null);setFiles({});setPreviews({});setError(null);setDetectedFields({})}
  return <Context.Provider value={useMemo(()=>({applicationId,files,previews,busy,error,detectedFields,capture,reset}),[applicationId,files,previews,busy,error,detectedFields])}>{children}</Context.Provider>
}
export function useVerification(){const value=useContext(Context);if(!value)throw new Error('VerificationProvider missing');return value}
