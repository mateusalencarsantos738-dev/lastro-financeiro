import {BookOpen, BriefcaseBusiness, Car, CircleHelp, Clapperboard, Coffee, Dumbbell, Gift, GraduationCap, HeartPulse, Home, Landmark, Lightbulb, Music2, PawPrint, Plane, ReceiptText, ShoppingBag, ShoppingCart, Sparkles, UtensilsCrossed, Wallet} from 'lucide-react'
import type {LucideIcon} from 'lucide-react'

export const categoryIconChoices:Record<string,{label:string;Icon:LucideIcon}>={
  'utensils':{label:'Alimentação',Icon:UtensilsCrossed},'coffee':{label:'Café',Icon:Coffee},
  'home':{label:'Moradia',Icon:Home},'car':{label:'Transporte',Icon:Car},
  'heart':{label:'Saúde',Icon:HeartPulse},'book':{label:'Livros',Icon:BookOpen},
  'school':{label:'Educação',Icon:GraduationCap},'film':{label:'Cinema',Icon:Clapperboard},
  'music':{label:'Música',Icon:Music2},'bag':{label:'Compras',Icon:ShoppingBag},
  'cart':{label:'Mercado',Icon:ShoppingCart},'receipt':{label:'Contas',Icon:ReceiptText},
  'plane':{label:'Viagens',Icon:Plane},'bank':{label:'Investimentos',Icon:Landmark},
  'wallet':{label:'Dinheiro',Icon:Wallet},'work':{label:'Trabalho',Icon:BriefcaseBusiness},
  'gift':{label:'Presentes',Icon:Gift},'pet':{label:'Pets',Icon:PawPrint},
  'sport':{label:'Esporte',Icon:Dumbbell},'light':{label:'Energia',Icon:Lightbulb},
  'sparkles':{label:'Cuidados',Icon:Sparkles},'other':{label:'Outros',Icon:CircleHelp},
}

export function CategoryIcon({icon,name,size=16}:{icon:string|null|undefined;name:string;size?:number}){
  const Icon=icon?categoryIconChoices[icon]?.Icon:undefined
  return Icon?<Icon size={size} aria-label={categoryIconChoices[icon!].label}/>:<span aria-label={name}>{name.slice(0,1).toLocaleUpperCase('pt-BR')}</span>
}
