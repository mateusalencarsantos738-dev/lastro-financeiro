export type Account = {id:string;name:string;kind:string}
export type Category = {id:string;name:string;kind:string;is_entertainment:boolean;icon:string|null;budget_limit:string|null;budget_period_type:string;budget_interval_count:number;budget_renewal_day:number|null;budget_effective_start:string|null;budget_scheduled_start:string|null;budget_period_start:string|null;budget_next_renewal:string|null}
export type BudgetStatus = {category_id:string;category:string;limit:string;spent:string;remaining:string;percent_used:number|null;state:'within'|'at_limit'|'exceeded';projection:string|null;period_start:string;period_end:string;next_renewal:string;period_type:string;interval_count:number;renewal_day:number|null}
export type MonthlyComparison = {month:string;income:string;expenses:string;result:string}
export type Overview = {month:string;cash_total:string;card_liability:string;open_bills:string;open_installments:string;reserved:string;cash_after_commitments:string;income:string;expenses:string;result:string;balances:{account_id:string;balance:string}[];budget_status:BudgetStatus[]}
export type Transaction = {id:string;version:number;kind:string;amount:string;account_id:string;category_id:string|null;description:string;transaction_date:string;settled_date?:string|null;status:string;notes?:string|null;deleted_at?:string|null}
export type DeletionPreview = {can_delete:boolean;effect:string;affected_ids:string[]}
export type Card = {id:string;name:string;account_id:string;closing_day:number;due_day:number}
export type CardPurchase = {id:string;transaction_id:string;version:number;card_id:string;card:string;category_id:string;total_amount:string;installment_count:number;purchase_date:string;merchant:string;deleted_at:string|null;installments:{id:string;sequence:number;amount:string;invoice_id:string;due_date:string;paid_date:string|null}[]}
export type Invoice = {id:string;card:string;due_date:string;total:string;open_amount:string;paid_date:string|null;installment_count:number}
export type Bill = {id:string;description:string;amount:string;due_date:string;category_id:string|null}
export type RecurringPlan = {id:string;description:string;kind:string;amount:string;account_id:string;category_id:string|null;due_date:string;realized:boolean;in_trash?:boolean;transaction_id:string|null}
export type Investment = {id:string;name:string;kind:string;institution:string|null;quantity:string|null;opening_contribution:string|null;acquired_on:string|null;current_value:string;valuation_date:string|null;contributions:string;withdrawals:string;income_recorded:string;fees:string;net_invested:string|null;difference_vs_net_invested:string|null}
export type Goal = {id:string;name:string;target_amount:string;contributed_amount:string;allocated_amount:string;remaining:string;target_date:string|null;tracking_mode:'none'|'selected'|'all';account_ids:string[];tracked_account_ids:string[];tracked_balance:string;other_reserves:string;open_obligations:string;available_estimate:string|null}
export type GoalAllocation = {id:string;amount_delta:string;allocated_on:string;note:string}
export type GoalContribution = {id:string;amount_delta:string;contributed_on:string;note:string}
export type CalendarDay = {date:string;income:string;expenses:string;result:string;transactions:{id:string;description:string;kind:string;amount:string;status:string;category_id:string|null}[];bills:{id:string;description:string;amount:string;paid:boolean}[];invoices:{id:string;card:string;amount:string;paid:boolean}[];recurring:{id:string;description:string;kind:string;amount:string;in_trash:boolean}[]}
export type NetWorth = {cash:string;investments:string;liabilities:string;card_liability:string;bill_liability:string;net_worth:string}
export type NetWorthSnapshot = {id:string;as_of_date:string;cash:string;investments:string;liabilities:string;net_worth:string}
export type Spending = {category_id:string;category:string;is_entertainment:boolean;spent:string}
export type Entertainment = {month:string;spent:string;cycle_spent:string;limit:string|null;remaining:string|null;average_completed_months:string|null;projection:string|null;history:{month:string;spent:string;records:number}[];top_expenses:{description:string;amount:string}[]}

export async function api<T>(path:string, init?:RequestInit):Promise<T>{
  const response=await fetch(`/api${path}`,{...init,headers:{'Content-Type':'application/json',...(init?.headers||{})}})
  if(!response.ok){const details=await response.json().catch(()=>({}));throw new Error(typeof details.detail==='string'?details.detail:'Não foi possível concluir a operação.')}
  return response.json()
}

export function fmt(value:string|number|null|undefined):string{
  const raw=String(value??'0').trim()
  const negative=raw.startsWith('-')
  const clean=(negative?raw.slice(1):raw).replace(/[^0-9.]/g,'')
  const [integer='0',fraction=''] = clean.split('.')
  const grouped=(integer.replace(/^0+(?=\d)/,'')||'0').replace(/\B(?=(\d{3})+(?!\d))/g,'.')
  return `${negative?'− ':''}R$ ${grouped},${fraction.padEnd(2,'0').slice(0,2)}`
}

export function normalizeMoney(value:FormDataEntryValue|undefined):string{
  const raw=String(value??'0').trim().replace(/\s/g,'')
  return raw.includes(',')?raw.replace(/\./g,'').replace(',','.'):raw
}

export function dateToday():string{
  const now=new Date()
  return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`
}
