export type LocalProfile={name:string;email:string;photo:string;theme:'light'|'dark'|'system'}
export const defaultProfile:LocalProfile={name:'Meu espaço',email:'',photo:'',theme:'system'}

const KEY='lastro.local.profile.v1'
const PHOTO_DB='lastro.local.profile.photos'
const PHOTO_KEY='avatar'

export function loadProfile():LocalProfile{
  try{
    const saved=JSON.parse(localStorage.getItem(KEY)||'{}')
    return {...defaultProfile,...saved}
  }catch{return defaultProfile}
}

function openPhotoDatabase():Promise<IDBDatabase>{
  return new Promise((resolve,reject)=>{
    const request=indexedDB.open(PHOTO_DB,1)
    request.onupgradeneeded=()=>request.result.createObjectStore('photos')
    request.onsuccess=()=>resolve(request.result)
    request.onerror=()=>reject(request.error)
  })
}

async function photoValue(value?:string):Promise<string|undefined>{
  const db=await openPhotoDatabase()
  try{
    return await new Promise<string|undefined>((resolve,reject)=>{
      const tx=db.transaction('photos',value===undefined?'readonly':'readwrite')
      const request=value===undefined?tx.objectStore('photos').get(PHOTO_KEY):tx.objectStore('photos').put(value,PHOTO_KEY)
      let result:string|undefined
      request.onsuccess=()=>{result=value===undefined?request.result:value}
      request.onerror=()=>reject(request.error)
      tx.oncomplete=()=>resolve(result)
      tx.onabort=()=>reject(tx.error)
    })
  }finally{db.close()}
}

export async function loadProfilePhoto():Promise<string>{
  const legacy=loadProfile().photo
  try{
    const stored=await photoValue()
    if(stored!==undefined)return stored
    if(legacy){
      await photoValue(legacy)
      const {photo:_,...preferences}=loadProfile()
      localStorage.setItem(KEY,JSON.stringify(preferences))
    }
    return legacy
  }catch{return legacy}
}

export async function saveProfile(profile:LocalProfile):Promise<void>{
  await photoValue(profile.photo)
  const {photo:_,...preferences}=profile
  localStorage.setItem(KEY,JSON.stringify(preferences))
}
