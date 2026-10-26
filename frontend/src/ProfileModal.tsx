import {useState} from 'react'
import type {FormEvent} from 'react'
import {X} from 'lucide-react'
import {saveProfile} from './profileStorage'
import type {LocalProfile} from './profileStorage'

export default function ProfileModal({profile,onSave,onClose}:{profile:LocalProfile;onSave:(value:LocalProfile)=>void;onClose:()=>void}){
  const [draft,setDraft]=useState(profile)
  const [error,setError]=useState('')
  async function selectPhoto(file:File|undefined){
    if(!file)return
    if(!['image/png','image/jpeg','image/webp'].includes(file.type)){setError('Use uma imagem PNG, JPEG ou WebP.');return}
    if(file.size>10*1024*1024){setError('A foto deve ter até 10 MB.');return}
    try{const data=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(new Error());reader.readAsDataURL(file)});setDraft(current=>({...current,photo:data}));setError('')}
    catch{setError('Não foi possível ler a foto selecionada.')}
  }
  async function submit(event:FormEvent){
    event.preventDefault()
    try{await saveProfile(draft);onSave(draft);onClose()}
    catch{setError('Não foi possível salvar o perfil neste navegador. Verifique o espaço disponível.')}
  }
  return <div className="modal-backdrop" onMouseDown={event=>{if(event.target===event.currentTarget)onClose()}}><form className="modal" onSubmit={event=>void submit(event)} role="dialog" aria-modal="true" aria-label="Perfil local"><div className="modal-head"><div><p className="eyebrow">PREFERÊNCIAS LOCAIS</p><h2>Meu perfil</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label="Fechar"><X size={18}/></button></div><div className="profile-preview"><div className="avatar large">{draft.photo?<img src={draft.photo} alt="Foto de perfil"/>:draft.name.slice(0,1).toUpperCase()}</div><div><b>{draft.name||'Meu espaço'}</b><small>Guardado apenas neste navegador</small></div></div><label className="field"><span>Nome de exibição</span><input value={draft.name} maxLength={80} required onChange={event=>setDraft({...draft,name:event.target.value})}/></label><label className="field"><span>E-mail opcional</span><input type="email" maxLength={180} value={draft.email} onChange={event=>setDraft({...draft,email:event.target.value})}/></label><label className="field"><span>Foto de perfil, até 10 MB</span><input type="file" accept="image/png,image/jpeg,image/webp" onChange={event=>void selectPhoto(event.target.files?.[0])}/></label>{draft.photo&&<button type="button" className="text-button" onClick={()=>setDraft({...draft,photo:''})}>Remover foto</button>}<label className="field"><span>Aparência</span><select value={draft.theme} onChange={event=>setDraft({...draft,theme:event.target.value as LocalProfile['theme']})}><option value="system">Seguir o sistema</option><option value="light">Claro</option><option value="dark">Escuro</option></select></label>{error&&<p className="form-error" role="alert">{error}</p>}<div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Cancelar</button><button className="primary">Salvar perfil</button></div></form></div>
}
