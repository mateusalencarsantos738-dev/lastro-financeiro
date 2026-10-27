import {useEffect,useMemo,useState} from 'react'
import type {FormEvent,ReactNode} from 'react'
import {Activity,Archive,ArrowDownLeft,ArrowLeftRight,ArrowUpRight,CalendarDays,ChartNoAxesCombined,CreditCard,Download,LayoutDashboard,Moon,Plus,Search,ShieldCheck,Sun,Target,Trash2,Wallet} from 'lucide-react'
import {Cell,Pie,PieChart,ResponsiveContainer,Tooltip} from 'recharts'
import FinanceModal from './FinanceModal'
import ProfileModal from './ProfileModal'
import {loadProfile,loadProfilePhoto,saveProfile} from './profileStorage'
import type {LocalProfile} from './profileStorage'
import FinancialCalendar from './FinancialCalendar'
import {api,dateToday,fmt,normalizeMoney} from './shared'
import {CategoryIcon} from './categoryIcons'
import type {Account,Bill,BudgetStatus,Card,CardPurchase,Category,CategoryArchivePreview,DeletionPreview,Entertainment,Goal,GoalAllocation,GoalContribution,Investment,Invoice,MonthlyComparison,NetWorth,NetWorthSnapshot,Overview,RecurringPlan,Spending,Transaction} from './shared'

const pages=['Visão geral','Movimentações','Orçamentos','Contas e cartões','Patrimônio','Lixeira']
const icons=[LayoutDashboard,Activity,ChartNoAxesCombined,CreditCard,Wallet,Trash2]
const dateLabel=(value:string)=>new Date(value+'T12:00:00').toLocaleDateString('pt-BR')
const kindLabel:Record<string,string>={checking:'Conta corrente',savings:'Poupança',cash:'Dinheiro'}
const transactionKindLabel:Record<string,string>={income:'Receita',expense:'Despesa',refund:'Reembolso',transfer_in:'Transferência recebida',transfer_out:'Transferência enviada',investment:'Aporte'}

export default function App(){
  const [profile,setProfile]=useState<LocalProfile>(loadProfile)
  const [profileOpen,setProfileOpen]=useState(false)
  const [systemDark,setSystemDark]=useState(()=>window.matchMedia('(prefers-color-scheme: dark)').matches)
  useEffect(()=>{let active=true;void loadProfilePhoto().then(photo=>{if(active)setProfile(current=>({...current,photo}))});return()=>{active=false}},[])
  const [calendarOpen,setCalendarOpen]=useState(false)
  const [calendarVersion,setCalendarVersion]=useState(0)
  useEffect(()=>{const media=window.matchMedia('(prefers-color-scheme: dark)');const apply=()=>setSystemDark(media.matches);media.addEventListener('change',apply);return()=>media.removeEventListener('change',apply)},[])
  const effectiveTheme=profile.theme==='system'?(systemDark?'dark':'light'):profile.theme
  useEffect(()=>{document.documentElement.dataset.theme=effectiveTheme},[effectiveTheme])
  async function toggleTheme(){
    const next:LocalProfile={...profile,theme:effectiveTheme==='dark'?'light':'dark'}
    setProfile(next)
    try{await saveProfile(next)}catch{setProfile(profile);setToast('Não foi possível salvar a preferência de tema.')}
  }
  const [month,setMonth]=useState(dateToday().slice(0,7)+'-01')
  const [budgetAsOf,setBudgetAsOf]=useState(dateToday())
  const [budgetRows,setBudgetRows]=useState<BudgetStatus[]>([])
  const monthEnd=`${month.slice(0,7)}-${String(new Date(Number(month.slice(0,4)),Number(month.slice(5,7)),0).getDate()).padStart(2,'0')}`
  const [page,setPage]=useState('Visão geral')
  const [overview,setOverview]=useState<Overview|null>(null)
  const [accounts,setAccounts]=useState<Account[]>([])
  const [categories,setCategories]=useState<Category[]>([])
  const [transactions,setTransactions]=useState<Transaction[]>([])
  const [trash,setTrash]=useState<Transaction[]>([])
  const [cards,setCards]=useState<Card[]>([])
  const [purchases,setPurchases]=useState<CardPurchase[]>([])
  const [invoices,setInvoices]=useState<Invoice[]>([])
  const [bills,setBills]=useState<Bill[]>([])
  const [recurring,setRecurring]=useState<RecurringPlan[]>([])
  const [investments,setInvestments]=useState<Investment[]>([])
  const [goals,setGoals]=useState<Goal[]>([])
  const [goalHistory,setGoalHistory]=useState<Record<string,GoalAllocation[]>>({})
  const [contributionHistory,setContributionHistory]=useState<Record<string,GoalContribution[]>>({})
  const [expandedGoal,setExpandedGoal]=useState('')
  const [worth,setWorth]=useState<NetWorth|null>(null)
  const [worthHistory,setWorthHistory]=useState<NetWorthSnapshot[]>([])
  const [spending,setSpending]=useState<Spending[]>([])
  const [entertainment,setEntertainment]=useState<Entertainment|null>(null)
  const [comparison,setComparison]=useState<MonthlyComparison[]>([])
  const [query,setQuery]=useState('')
  const [historyStart,setHistoryStart]=useState('')
  const [historyEnd,setHistoryEnd]=useState('')
  const [historyCategory,setHistoryCategory]=useState('')
  const [historyAccount,setHistoryAccount]=useState('')
  const [historyKind,setHistoryKind]=useState('')
  const [modal,setModal]=useState<{type:string;id:string;presetDate?:string}|null>(null)
  const [detailTx,setDetailTx]=useState<Transaction|null>(null)
  const [deletion,setDeletion]=useState<{tx:Transaction;preview:DeletionPreview}|null>(null)
  const [categoryArchive,setCategoryArchive]=useState<CategoryArchivePreview|null>(null)
  const [archivedSearch,setArchivedSearch]=useState('')
  const [undoId,setUndoId]=useState('')
  const [toast,setToast]=useState('')
  const [busy,setBusy]=useState(false)
  async function refresh(silent=false){
    try{
      const [o,a,c,t,ca,cp,inv,bi,i,g,w,wh,s,e,mc,rp,trashed,br]=await Promise.all([
        api<Overview>(`/overview?month=${month}`),api<Account[]>('/accounts'),api<Category[]>('/categories?scope=all'),
        api<Transaction[]>('/transactions?limit=500'),api<Card[]>('/cards'),api<CardPurchase[]>('/card-purchases'),api<Invoice[]>('/invoices'),
        api<Bill[]>(`/bills?through=${monthEnd}`),api<Investment[]>('/investments'),api<Goal[]>('/goals'),
        api<NetWorth>('/net-worth'),api<NetWorthSnapshot[]>('/net-worth/history'),
        api<Spending[]>(`/spending?start=${month}&end=${monthEnd}`),
        api<Entertainment>(`/entertainment?month=${budgetAsOf}`),
        api<MonthlyComparison[]>('/monthly-comparison?months=6'),
        api<RecurringPlan[]>(`/recurring-plans?month=${month}`),
        api<Transaction[]>('/transactions/trash'),
        api<BudgetStatus[]>(`/budgets?month=${budgetAsOf}`),
      ])
      setOverview(o);setAccounts(a);setCategories(c);setTransactions(t);setTrash(trashed);setCards(ca);setPurchases(cp);setInvoices(inv)
      setBills(bi);setRecurring(rp);setInvestments(i);setGoals(g);setWorth(w);setWorthHistory(wh);setSpending(s);setEntertainment(e);setComparison(mc);setBudgetRows(br)
      setCalendarVersion(value=>value+1)
    }catch(error){if(!silent)setToast(error instanceof Error?error.message:'Falha de conexão')}
  }
  useEffect(()=>{void refresh()},[month])
  useEffect(()=>{
    const onActive=()=>{if(document.visibilityState==='visible'&&!busy)void refresh(true)}
    window.addEventListener('focus',onActive)
    document.addEventListener('visibilitychange',onActive)
    const timer=window.setInterval(onActive,5000)
    return()=>{window.removeEventListener('focus',onActive);document.removeEventListener('visibilitychange',onActive);window.clearInterval(timer)}
  },[month,budgetAsOf,busy])
  useEffect(()=>{void Promise.all([api<BudgetStatus[]>(`/budgets?month=${budgetAsOf}`),api<Entertainment>(`/entertainment?month=${budgetAsOf}`)]).then(([rows,status])=>{setBudgetRows(rows);setEntertainment(status)}).catch(error=>setToast(error instanceof Error?error.message:'Falha ao carregar orçamentos'))},[budgetAsOf])
  useEffect(()=>{if(toast){const timer=setTimeout(()=>{setToast('');setUndoId('')},undoId?9000:4500);return()=>clearTimeout(timer)}},[toast,undoId])
  const filtered=useMemo(()=>transactions.filter(t=>
    t.description.toLocaleLowerCase('pt-BR').includes(query.toLocaleLowerCase('pt-BR')) &&
    (!historyStart||t.transaction_date>=historyStart) && (!historyEnd||t.transaction_date<=historyEnd) &&
    (!historyCategory||t.category_id===historyCategory) && (!historyAccount||t.account_id===historyAccount) &&
    (!historyKind||t.kind===historyKind)
  ),[transactions,query,historyStart,historyEnd,historyCategory,historyAccount,historyKind])
  const chart=spending.filter(s=>Number(s.spent)>0).map(s=>({id:s.category_id,name:s.category,value:Number(s.spent),color:s.color,icon:s.icon}))
  const chartTotal=chart.reduce((sum,row)=>sum+row.value,0)
  const show=(type:string,id='',presetDate?:string)=>setModal({type,id,presetDate})
  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault()
    if(!modal)return
    const data=Object.fromEntries(new FormData(event.currentTarget).entries()) as Record<string,string>
    const payload:Record<string,unknown>={...data}
    if(payload.color==='')delete payload.color
    if(modal.type==='Meta'||modal.type==='Atualizar meta')payload.account_ids=new FormData(event.currentTarget).getAll('account_ids')
    for(const field of ['amount','opening_balance','limit_amount','budget_limit','total_amount','current_value','target_amount','allocated_amount','value','opening_contribution'])if(field in payload&&data[field]!=='')payload[field]=normalizeMoney(data[field])
    for(const field of ['category_id','related_transaction_id','target_date','valuation_date','acquired_on','opening_contribution','quantity','budget_limit','budget_effective_start','effective_start'])if(payload[field]==='')payload[field]=null
    for(const field of ['interval_count','budget_interval_count','renewal_day','budget_renewal_day'])if(field in payload)payload[field]=data[field]?Number(data[field]):null
    if(payload.interval_count==null)delete payload.interval_count
    if(payload.budget_interval_count==null)delete payload.budget_interval_count
    if('amount_delta' in payload)payload.amount_delta=normalizeMoney(data.amount_delta)
    if(typeof payload.quantity==='string')payload.quantity=payload.quantity.replace(',','.')
    let path='';let method='POST'
    switch(modal.type){
      case 'Conta':path='/accounts';break
      case 'Transferência':path='/transfers';break
      case 'Categoria':path='/categories';payload.is_entertainment=data.is_entertainment==='on';break
      case 'Editar categoria':path=`/categories/${modal.id}`;method='PUT';payload.is_entertainment=data.is_entertainment==='on';break
      case 'Orçamento':path='/budgets';method='PUT';break
      case 'Cartão':path='/cards';payload.closing_day=Number(data.closing_day);payload.due_day=Number(data.due_day);break
      case 'Compra no cartão':path='/card-purchases';payload.installment_count=Number(data.installment_count);break
      case 'Editar compra no cartão':path=`/card-purchases/${modal.id}`;method='PATCH';payload.installment_count=Number(data.installment_count);payload.expected_version=Number(data.expected_version);break
      case 'Conta a pagar':path='/bills';break
      case 'Plano recorrente':path='/recurring-plans';break
      case 'Pagar fatura':path=`/invoices/${modal.id}/pay`;break
      case 'Pagar conta':path=`/bills/${modal.id}/pay`;break
      case 'Investimento':path='/investments';break
      case 'Avaliar investimento':path=`/investments/${modal.id}/valuations`;break
      case 'Evento de investimento':path='/investment-events';break
      case 'Meta':path='/goals';break
      case 'Atualizar meta':path=`/goals/${modal.id}`;method='PUT';break
      case 'Contribuição para meta':path=`/goals/${modal.id}/contributions`;break
      case 'Corrigir movimentação':path=`/transactions/${modal.id}`;method='PUT';payload.expected_version=Number(data.expected_version);payload.confirmed=data.confirmed==='on';break
      default:path='/transactions'
    }
    setBusy(true)
    try{
      await api(path,{method,headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify(payload)})
      setModal(null);await refresh();setToast('Registro salvo com sucesso.')
    }catch(error){setToast(error instanceof Error?error.message:'Falha ao salvar')}
    finally{setBusy(false)}
  }
  async function saveSnapshot(){
    try{await api('/net-worth/snapshots',{method:'POST'});await refresh();setToast('Posição patrimonial de hoje registrada.')}
    catch(error){setToast(error instanceof Error?error.message:'Falha ao registrar posição')}
  }
  async function settlePending(id:string){
    try{await api(`/transactions/${id}/settle`,{method:'POST'});await refresh();setToast('Movimentação marcada como realizada.')}
    catch(error){setToast(error instanceof Error?error.message:'Falha ao realizar movimentação')}
  }
  async function realizePlan(id:string){
    try{await api(`/recurring-plans/${id}/realize?month=${month}&realized_on=${dateToday()}`,{method:'POST'});await refresh();setToast('Ocorrência mensal registrada como realizada.')}
    catch(error){setToast(error instanceof Error?error.message:'Falha ao realizar plano')}
  }
  async function toggleGoalHistory(id:string){
    if(expandedGoal===id){setExpandedGoal('');return}
    try{const [allocations,contributions]=await Promise.all([api<GoalAllocation[]>(`/goals/${id}/allocations`),api<GoalContribution[]>(`/goals/${id}/contributions`)]);setGoalHistory(previous=>({...previous,[id]:allocations}));setContributionHistory(previous=>({...previous,[id]:contributions}));setExpandedGoal(id)}
    catch(error){setToast(error instanceof Error?error.message:'Falha ao consultar histórico da meta')}
  }
  async function showDeletion(tx:Transaction){
    try{const preview=await api<DeletionPreview>(`/transactions/${tx.id}/deletion-preview`);setDetailTx(null);setDeletion({tx,preview})}
    catch(error){setToast(error instanceof Error?error.message:'Falha ao consultar impacto da exclusão')}
  }
  function editTransaction(id:string){
    const purchase=purchases.find(item=>item.transaction_id===id)
    show(purchase?'Editar compra no cartão':'Corrigir movimentação',purchase?.id||id)
  }
  function deletePurchase(purchase:CardPurchase){
    const tx=transactions.find(item=>item.id===purchase.transaction_id)
    if(tx)void showDeletion(tx)
    else setToast('Movimentação da compra não encontrada. Recarregue os dados.')
  }
  async function confirmDeletion(){
    if(!deletion||!deletion.preview.can_delete)return
    try{await api(`/transactions/${deletion.tx.id}?expected_version=${deletion.tx.version}&confirmed=true`,{method:'DELETE'});const id=deletion.tx.id;setDeletion(null);await refresh();setUndoId(id);setToast('Movimentação enviada à lixeira.')}
    catch(error){setToast(error instanceof Error?error.message:'Falha ao excluir movimentação')}
  }
  async function restoreDeleted(id:string){
    try{await api(`/transactions/${id}/restore`,{method:'POST'});await refresh();setUndoId('');setToast('Movimentação restaurada sem duplicar valores.')}
    catch(error){setToast(error instanceof Error?error.message:'Falha ao restaurar movimentação')}
  }
  async function previewCategoryArchive(id:string){
    try{setCategoryArchive(await api<CategoryArchivePreview>(`/categories/${id}/archive-preview`))}
    catch(error){setToast(error instanceof Error?error.message:'Falha ao consultar a categoria')}
  }
  async function confirmCategoryArchive(){
    if(!categoryArchive)return
    try{await api(`/categories/${categoryArchive.category_id}/archive`,{method:'POST'});setCategoryArchive(null);await refresh();setToast('Categoria arquivada. Os gastos e o histórico foram preservados.')}
    catch(error){setToast(error instanceof Error?error.message:'Falha ao arquivar categoria')}
  }
  async function confirmCategoryRestore(category:Category){
    if(!window.confirm(`Restaurar ${category.name}? Ela voltará a aceitar novos lançamentos. Gastos, cor, ícone e orçamento existentes serão preservados.`))return
    try{await api(`/categories/${category.id}/restore`,{method:'POST'});await refresh();setToast('Categoria restaurada com o mesmo histórico.')}
    catch(error){setToast(error instanceof Error?error.message:'Falha ao restaurar categoria')}
  }
  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><div className="brand-mark"><Wallet size={19}/></div><div><strong>meu financeiro</strong><small>suas finanças, com clareza</small></div></div><div className="side-label">MENU PRINCIPAL</div><nav>{pages.map((label,index)=>{const Icon=icons[index];return <button key={label} className={page===label?'active':''} onClick={()=>setPage(label)}><Icon size={18}/><span>{label}</span>{label==='Movimentações'&&<span className="nav-count">{transactions.length}</span>}</button>})}</nav><div className="side-bottom"><div className="privacy-card"><ShieldCheck size={17}/><div><b>Seus dados ficam aqui</b><span>Armazenados localmente no seu computador.</span></div></div><button className="profile profile-button" onClick={()=>setProfileOpen(true)} aria-label="Abrir perfil e aparência"><div className="avatar">{profile.photo?<img src={profile.photo} alt=""/>:profile.name.slice(0,1).toUpperCase()}</div><div><b>{profile.name}</b><span>Perfil e aparência</span></div></button></div></aside>
    <main className="main-area"><header className="topbar"><div className="crumb">Financeiro <span>/</span> <b>{page}</b></div><div className="top-actions"><button className="icon-button" onClick={()=>void toggleTheme()} aria-label={effectiveTheme==='dark'?'Tema escuro ativo. Alternar para claro':'Tema claro ativo. Alternar para escuro'} title={effectiveTheme==='dark'?'Tema escuro ativo':'Tema claro ativo'}>{effectiveTheme==='dark'?<Moon size={17}/>:<Sun size={17}/>}</button><button className="icon-button" onClick={()=>setCalendarOpen(true)} aria-label="Abrir calendário financeiro"><CalendarDays size={18}/></button><label className="period"><span>Mês</span><input type="month" value={month.slice(0,7)} onChange={event=>{const selected=event.target.value+'-01';setMonth(selected);setBudgetAsOf(event.target.value===dateToday().slice(0,7)?dateToday():selected)}} aria-label="Mês de análise"/></label></div></header><div className="content">
      <div className="welcome-row"><div><p className="eyebrow">{new Date().toLocaleDateString('pt-BR',{day:'2-digit',month:'long'}).toUpperCase()}</p><h1>{page==='Visão geral'?'Bom dia, vamos cuidar do seu dinheiro.':page}</h1><p className="subhead">Uma visão simples para você decidir com tranquilidade.</p></div><button className="primary" onClick={()=>show('Movimentação')}><Plus size={17}/> Nova movimentação</button></div>
      {page==='Visão geral'&&<>
        {accounts.length===0&&<div className="setup-banner"><div className="setup-icon"><Wallet size={20}/></div><div><strong>Comece cadastrando uma conta</strong><p>Os saldos partem dos seus registros. Nenhum dado de exemplo foi incluído.</p></div><button className="text-button" onClick={()=>show('Conta')}>Adicionar conta →</button></div>}
        <section className="metrics"><Metric label="Saldo nas contas" value={fmt(overview?.cash_total)} detail="dinheiro registrado" icon={<Wallet/>} tone="green"/><Metric label="Receitas do mês" value={fmt(overview?.income)} detail="valores realizados" icon={<ArrowDownLeft/>} tone="blue"/><Metric label="Despesas do mês" value={fmt(overview?.expenses)} detail="consumo reconhecido" icon={<ArrowUpRight/>} tone="peach"/><Metric label="Resultado do mês" value={fmt(overview?.result)} detail="receitas menos despesas" icon={<Activity/>} tone="lavender"/></section>
        <section className="grid-main"><div className="panel budget-panel"><PanelTitle title="Orçamento por categoria" subtitle="Acompanhe o limite do ciclo de cada categoria." action="Ver todos →" onAction={()=>setPage('Orçamentos')}/><BudgetRows rows={overview?.budget_status||[]} onOpen={()=>setPage('Orçamentos')}/></div><div className="panel spending-panel"><PanelTitle title="Para onde vai seu dinheiro" subtitle="Despesas realizadas neste mês."/>{chart.length?<><div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={chart} dataKey="value" nameKey="name" innerRadius={63} outerRadius={90} paddingAngle={3}>{chart.map((x,index)=><Cell key={index} fill={x.color}/>)}</Pie><Tooltip formatter={value=>fmt(String(value))}/></PieChart></ResponsiveContainer><div className="chart-center"><strong>{fmt(chartTotal)}</strong><span>no mês</span></div></div><div className="legend">{chart.map(x=><div key={x.id}><i style={{background:x.color}}/><CategoryIcon icon={x.icon} name={x.name} size={14}/><span>{x.name}</span><b>{fmt(x.value)}</b></div>)}</div></>:<Empty label="Sem despesas por enquanto" detail="Registre uma movimentação para ver a distribuição dos gastos."/>}</div></section>
        <section className="metrics small-metrics"><Metric label="Contas futuras" value={fmt(overview?.open_bills)} detail="obrigações registradas" icon={<CalendarDays/>} tone="peach"/><Metric label="Parcelas pendentes" value={fmt(overview?.open_installments)} detail="faturas futuras" icon={<CreditCard/>} tone="lavender"/><Metric label="Reservado para metas" value={fmt(overview?.reserved)} detail="parte do saldo em conta" icon={<Target/>} tone="blue"/><Metric label="Após compromissos" value={fmt(overview?.cash_after_commitments)} detail="estimativa sem receitas futuras" icon={<Wallet/>} tone="green"/></section>
        <section className="panel section-gap"><PanelTitle title="Evolução mensal" subtitle="Receitas e despesas reconhecidas; transferências próprias ficam fora da comparação."/><div className="table-wrap"><table><thead><tr><th>MÊS</th><th className="right">RECEITAS</th><th className="right">DESPESAS</th><th className="right">RESULTADO</th></tr></thead><tbody>{comparison.map(row=><tr key={row.month}><td>{new Date(row.month+'T12:00:00').toLocaleDateString('pt-BR',{month:'long',year:'numeric'})}</td><td className="right">{fmt(row.income)}</td><td className="right">{fmt(row.expenses)}</td><td className="right"><strong>{fmt(row.result)}</strong></td></tr>)}</tbody></table></div></section>
        {overview?.budget_status.some(row=>Number(row.remaining)<0)&&<div className="setup-banner alert-banner"><div className="setup-icon"><Activity size={20}/></div><div><strong>Limite de orçamento ultrapassado</strong><p>Confira as categorias acima. As despesas reais continuam registradas normalmente.</p></div></div>}
        <section className="panel transactions-panel"><PanelTitle title="Movimentações recentes" subtitle="Seus últimos registros." action="Ver histórico →" onAction={()=>setPage('Movimentações')}/><Transactions rows={transactions.slice(0,5)} categories={categories} accounts={accounts}/></section>
      </>}
      {page==='Movimentações'&&<section className="panel transactions-panel"><div className="panel-head"><div><h2>Histórico de movimentações</h2><p>Consulte e pesquise seus registros.</p></div><div className="search-box"><Search size={16}/><input value={query} onChange={event=>setQuery(event.target.value)} placeholder="Buscar descrição" aria-label="Buscar descrição"/><a href="/api/export.csv" className="export"><Download size={15}/> Exportar CSV</a></div></div><div className="history-filters"><label>De<input type="date" value={historyStart} onChange={event=>setHistoryStart(event.target.value)}/></label><label>Até<input type="date" value={historyEnd} onChange={event=>setHistoryEnd(event.target.value)}/></label><label>Categoria<select value={historyCategory} onChange={event=>setHistoryCategory(event.target.value)}><option value="">Todas</option>{categories.map(c=><option value={c.id} key={c.id}>{c.name}</option>)}</select></label><label>Conta<select value={historyAccount} onChange={event=>setHistoryAccount(event.target.value)}><option value="">Todas</option>{accounts.map(a=><option value={a.id} key={a.id}>{a.name}</option>)}</select></label><label>Tipo<select value={historyKind} onChange={event=>setHistoryKind(event.target.value)}><option value="">Todos</option>{[['income','Receita'],['expense','Despesa'],['refund','Reembolso'],['transfer_out','Transferência enviada'],['transfer_in','Transferência recebida'],['investment','Aporte']].map(([kind,label])=><option value={kind} key={kind}>{label}</option>)}</select></label></div><p className="hint">{filtered.length} registro(s) nesta consulta. Exibimos até 500 movimentações recentes; o CSV contém o histórico completo.</p><Transactions rows={filtered} categories={categories} accounts={accounts} onCorrect={editTransaction} onSettle={id=>void settlePending(id)} onDetails={setDetailTx} onDelete={tx=>void showDeletion(tx)}/></section>}
      {page==='Lixeira'&&<section className="panel transactions-panel"><PanelTitle title="Lixeira de movimentações" subtitle="Os registros aqui não entram em saldos, orçamentos ou relatórios. Restaurar recupera o mesmo identificador."/>{trash.length?<div className="table-wrap"><table><thead><tr><th>DESCRIÇÃO</th><th>TIPO</th><th>DATA ORIGINAL</th><th>EXCLUÍDA EM</th><th className="right">VALOR</th><th className="right">AÇÃO</th></tr></thead><tbody>{trash.map(tx=><tr key={tx.id}><td><b>{tx.description}</b></td><td>{tx.kind}</td><td>{dateLabel(tx.transaction_date)}</td><td>{tx.deleted_at?new Date(tx.deleted_at).toLocaleString('pt-BR'):'—'}</td><td className="right">{fmt(tx.amount)}</td><td className="right"><button className="secondary" onClick={()=>void restoreDeleted(tx.id)}>Restaurar</button></td></tr>)}</tbody></table></div>:<Empty label="A lixeira está vazia" detail="Movimentações excluídas poderão ser restauradas aqui."/>}</section>}
      {page==='Orçamentos'&&<><section className="panel"><PanelTitle title="Limites por ciclo" subtitle="Os limites orientam escolhas e nunca impedem um registro real." action="Nova categoria" onAction={()=>show('Categoria')}/><label className="field"><span>Consultar ciclo na data</span><input type="date" value={budgetAsOf} onChange={event=>{if(event.target.value)setBudgetAsOf(event.target.value)}} aria-label="Data de consulta do orçamento"/></label>{categories.filter(c=>c.kind==='expense'&&(c.is_active||budgetRows.some(row=>row.category_id===c.id))).map(c=>{const b=budgetRows.find(x=>x.category_id===c.id);return <div className="budget-row" key={c.id}><div className="budget-title"><span className="cat-icon" style={{color:c.color}}><CategoryIcon icon={c.icon} name={c.name}/></span><div><b>{c.name}{c.is_entertainment?' · lazer':''}{!c.is_active?' · arquivada':''}</b><small>{b?`${fmt(b.spent)} gastos de ${fmt(b.limit)} · ${b.percent_used==null?'sem percentual':`${Number(b.percent_used).toFixed(1)}% usado`}`:c.budget_scheduled_start?`Limite programado para ${dateLabel(c.budget_scheduled_start)}`:'Sem limite definido'}{b&&<><br/>Ciclo: {dateLabel(b.period_start)} a {dateLabel(b.period_end)} · renova {dateLabel(b.next_renewal)}</>}</small></div><span className="trailing"/>{c.is_active?<><button className="text-button" onClick={()=>show('Movimentação',c.id)}>Lançar gasto</button><button className="text-button" onClick={()=>show('Editar categoria',c.id)}>Editar</button><button className="text-button" onClick={()=>show('Orçamento',c.id)}>Definir limite →</button><button className="category-archive-button" onClick={()=>void previewCategoryArchive(c.id)} aria-label={`Arquivar categoria ${c.name}`} title={`Arquivar ${c.name}`}><Archive size={16} aria-hidden="true"/></button></>:<span className="archived-label">Arquivada</span>}</div>{b&&<div className="progress"><span style={{width:`${Math.min(100,Math.max(0,Number(b.percent_used||0)))}%`,background:c.color}}/></div>}</div>})}{!categories.some(c=>c.kind==='expense'&&c.is_active)&&<Empty label="Nenhuma categoria ativa de despesa" detail="Cadastre uma categoria para novos lançamentos." action="Adicionar categoria" onAction={()=>show('Categoria')}/>}</section><section className="panel section-gap"><PanelTitle title="Categorias de receita" subtitle="Organize também as entradas com ícones próprios."/>{categories.filter(c=>c.kind==='income'&&c.is_active).map(c=><div className="budget-row" key={c.id}><div className="budget-title"><span className="cat-icon" style={{color:c.color}}><CategoryIcon icon={c.icon} name={c.name}/></span><div><b>{c.name}</b></div><button className="text-button trailing" onClick={()=>show('Editar categoria',c.id)}>Editar</button><button className="category-archive-button" onClick={()=>void previewCategoryArchive(c.id)} aria-label={`Arquivar categoria ${c.name}`} title={`Arquivar ${c.name}`}><Archive size={16} aria-hidden="true"/></button></div></div>)}{!categories.some(c=>c.kind==='income'&&c.is_active)&&<p className="hint">Nenhuma categoria de receita cadastrada.</p>}</section><section className="panel section-gap"><PanelTitle title="Categorias arquivadas" subtitle="Registros, cores, ícones e limites continuam guardados."/><label className="field"><span>Pesquisar categoria arquivada</span><input type="search" value={archivedSearch} onChange={event=>setArchivedSearch(event.target.value)} placeholder="Buscar pelo nome"/></label>{categories.filter(c=>!c.is_active&&c.name.toLocaleLowerCase('pt-BR').includes(archivedSearch.toLocaleLowerCase('pt-BR'))).map(c=><div className="budget-row" key={c.id}><div className="budget-title"><span className="cat-icon" style={{color:c.color}}><CategoryIcon icon={c.icon} name={c.name}/></span><div><b>{c.name}</b><small>{c.kind==='expense'?'Despesa':'Receita'} · arquivada em {c.archived_on?dateLabel(c.archived_on):'data não informada'}{c.visible_until?` · indicador corrente até ${dateLabel(c.visible_until)}`:''}{c.budget_limit?` · limite ${fmt(c.budget_limit)}`:''}</small></div><button className="text-button trailing" onClick={()=>void confirmCategoryRestore(c)}>Restaurar</button></div></div>)}{!categories.some(c=>!c.is_active&&c.name.toLocaleLowerCase('pt-BR').includes(archivedSearch.toLocaleLowerCase('pt-BR')))&&<p className="hint">Nenhuma categoria arquivada encontrada.</p>}</section><section className="panel section-gap"><PanelTitle title="Entretenimento" subtitle="Gastos marcados como lazer, sem misturar com outras categorias."/><div className="fact-grid"><Fact label="Gasto nos ciclos" value={fmt(entertainment?.cycle_spent)}/><Fact label="Limite" value={entertainment?.limit==null?'Não definido':fmt(entertainment.limit)}/><Fact label="Restante" value={entertainment?.remaining==null?'—':fmt(entertainment.remaining)}/><Fact label="Média de meses completos" value={entertainment?.average_completed_months==null?'Dados insuficientes':fmt(entertainment.average_completed_months)}/></div><p className="hint">{entertainment?.projection==null?'Projeção indisponível: são necessários registros em pelo menos três dias após o dia 7.':`Projeção do mês: ${fmt(entertainment.projection)}. Estimativa baseada no ritmo registrado.`}</p>{entertainment?.top_expenses.length? <p className="hint">Maiores gastos: {entertainment.top_expenses.map(x=>`${x.description} (${fmt(x.amount)})`).join(' · ')}</p>:null}<h3>Últimos meses</h3><div className="table-wrap"><table><thead><tr><th>MÊS</th><th className="right">GASTO</th><th className="right">REGISTROS</th></tr></thead><tbody>{entertainment?.history.map(item=><tr key={item.month}><td>{new Date(item.month+'T12:00:00').toLocaleDateString('pt-BR',{month:'long',year:'numeric'})}</td><td className="right">{fmt(item.spent)}</td><td className="right">{item.records}</td></tr>)}</tbody></table></div></section></>}
      {page==='Contas e cartões'&&<><section className="panel"><PanelTitle title="Contas e carteiras" subtitle="Saldos calculados pelos movimentos registrados." action="Adicionar conta" onAction={()=>show('Conta')}/>{accounts.filter(a=>a.kind!=='credit_card').map(a=><div className="account-item" key={a.id}><span className="cat-icon"><Wallet size={16}/></span><b>{a.name}</b><span>{kindLabel[a.kind]||a.kind}</span><strong>{fmt(overview?.balances.find(x=>x.account_id===a.id)?.balance)}</strong></div>)}{!accounts.some(a=>a.kind!=='credit_card')&&<Empty label="Nenhuma conta cadastrada" action="Adicionar conta" onAction={()=>show('Conta')}/>}<div className="panel-actions"><button className="secondary" onClick={()=>show('Transferência')}>Transferir entre contas</button></div></section><section className="panel section-gap"><PanelTitle title="Cartões de crédito" subtitle="A compra entra no consumo; a fatura apenas movimenta o dinheiro." action="Adicionar cartão" onAction={()=>show('Cartão')}/>{cards.map(c=><div className="account-item" key={c.id}><span className="cat-icon"><CreditCard size={16}/></span><b>{c.name}</b><span>Fecha dia {c.closing_day} · vence dia {c.due_day}</span><button className="text-button trailing" onClick={()=>show('Compra no cartão',c.id)}>Nova compra →</button></div>)}{!cards.length&&<Empty label="Nenhum cartão cadastrado" action="Adicionar cartão" onAction={()=>show('Cartão')}/>}</section><section className="panel section-gap"><PanelTitle title="Gastos do cartão" subtitle="Compras manuais, com edição e exclusão direta."/>
        <CardPurchaseList rows={purchases} categories={categories} onEdit={item=>show('Editar compra no cartão',item.id)} onDelete={deletePurchase} onDetails={item=>{const tx=transactions.find(t=>t.id===item.transaction_id);if(tx)setDetailTx(tx)}}/>
      </section><section className="panel section-gap"><PanelTitle title="Faturas" subtitle="Totais de todas as faturas, inclusive as já pagas."/>{invoices.map(i=><div className="invoice-card" key={i.id}><div className="account-item"><span className="cat-icon"><CalendarDays size={16}/></span><b>{i.card}</b><span>Vence {dateLabel(i.due_date)} · {i.installment_count} parcela(s){i.paid_date?' · paga':''}</span><strong>{fmt(i.total)}{Number(i.open_amount)>0&&<small>Aberto: {fmt(i.open_amount)}</small>}</strong>{Number(i.open_amount)>0&&<button className="secondary" onClick={()=>show('Pagar fatura',i.id)}>Pagar</button>}</div><CardPurchaseList rows={purchases.filter(item=>item.installments.some(part=>part.invoice_id===i.id))} categories={categories} onEdit={item=>show('Editar compra no cartão',item.id)} onDelete={deletePurchase} onDetails={item=>{const tx=transactions.find(t=>t.id===item.transaction_id);if(tx)setDetailTx(tx)}}/></div>)}{!invoices.length&&<Empty label="Nenhuma fatura registrada"/>}</section><section className="panel section-gap"><PanelTitle title="Contas a pagar" subtitle="Obrigações previstas, ainda não pagas." action="Adicionar conta a pagar" onAction={()=>show('Conta a pagar')}/>{bills.map(b=><div className="account-item" key={b.id}><span className="cat-icon"><CalendarDays size={16}/></span><b>{b.description}</b><span>Vence {dateLabel(b.due_date)}</span><strong>{fmt(b.amount)}</strong>{b.category_id&&!categories.find(c=>c.id===b.category_id)?.is_active?<span className="archived-label">Restaure a categoria para pagar</span>:<button className="secondary" onClick={()=>show('Pagar conta',b.id)}>Pagar</button>}</div>)}{!bills.length&&<Empty label="Nenhuma conta a pagar até o fim deste mês"/>}</section><section className="panel section-gap"><PanelTitle title="Receitas e despesas recorrentes" subtitle="Previsões mensais: só alteram caixa e resultado após a confirmação." action="Adicionar previsão" onAction={()=>show('Plano recorrente')}/>{recurring.map(plan=><div className="account-item" key={plan.id}><span className="cat-icon"><CalendarDays size={16}/></span><b>{plan.description}</b><span>{plan.kind==='income'?'Receita esperada':'Despesa prevista'} · {dateLabel(plan.due_date)}</span><strong>{fmt(plan.amount)}</strong>{plan.realized?<span className="tag">Realizada</span>:plan.in_trash?<span className="tag">Na lixeira — restaure a movimentação</span>:plan.category_id&&!categories.find(c=>c.id===plan.category_id)?.is_active?<span className="archived-label">Restaure a categoria para realizar</span>:<button className="secondary" onClick={()=>void realizePlan(plan.id)}>Registrar realização</button>}</div>)}{!recurring.length&&<Empty label="Nenhuma previsão recorrente neste mês" action="Adicionar previsão" onAction={()=>show('Plano recorrente')}/>}</section></>}
      {page==='Patrimônio'&&<>
        <section className="metrics"><Metric label="Patrimônio líquido" value={fmt(worth?.net_worth)} detail="ativos menos obrigações" icon={<Wallet/>} tone="green"/><Metric label="Investimentos" value={fmt(worth?.investments)} detail="avaliações informadas" icon={<ChartNoAxesCombined/>} tone="blue"/><Metric label="Cartões a pagar" value={fmt(worth?.card_liability)} detail="compras pendentes" icon={<CreditCard/>} tone="peach"/><Metric label="Contas a pagar" value={fmt(worth?.bill_liability)} detail="obrigações registradas" icon={<CalendarDays/>} tone="lavender"/></section>
        <section className="panel"><PanelTitle title="Investimentos" subtitle="Valores informados por você; não são cotações de mercado." action="Adicionar investimento" onAction={()=>show('Investimento')}/>
          {investments.map(i=><div className="investment-item" key={i.id}><div className="account-item"><span className="cat-icon"><ChartNoAxesCombined size={16}/></span><b>{i.name}</b><span>{i.institution?`${i.institution} · `:''}{i.valuation_date?`avaliação manual em ${dateLabel(i.valuation_date)}`:'sem data de avaliação'}</span><strong>{fmt(i.current_value)}</strong><button className="secondary" onClick={()=>show('Avaliar investimento',i.id)}>Avaliar</button><button className="secondary" onClick={()=>show('Evento de investimento',i.id)}>Aporte ou resgate</button></div><div className="investment-details"><span>Aportes novos: {fmt(i.contributions)}</span><span>Resgates: {fmt(i.withdrawals)}</span><span>Rendimentos registrados: {fmt(i.income_recorded)}</span><span>Taxas: {fmt(i.fees)}</span>{i.quantity&&<span>Quantidade: {i.quantity}</span>}{i.difference_vs_net_invested!=null&&<span>Diferença frente ao capital líquido: {fmt(i.difference_vs_net_invested)}</span>}</div></div>)}
          {!investments.length&&<Empty label="Nenhum investimento registrado" action="Adicionar investimento" onAction={()=>show('Investimento')}/>}
        </section>
        <section className="panel section-gap"><PanelTitle title="Evolução patrimonial" subtitle="Fotografias registradas por você; dias sem registro não são estimados." action="Registrar posição de hoje" onAction={()=>void saveSnapshot()}/>
          {worthHistory.length?worthHistory.map(row=><div className="account-item" key={row.id}><span className="cat-icon"><Wallet size={16}/></span><b>{dateLabel(row.as_of_date)}</b><span>Ativos: {fmt(row.cash)} em conta + {fmt(row.investments)} investidos · passivos: {fmt(row.liabilities)}</span><strong>{fmt(row.net_worth)}</strong></div>):<Empty label="Nenhuma posição histórica" detail="Registre a posição de hoje para acompanhar a evolução a partir desta data."/>}
        </section>
        <section className="panel section-gap"><PanelTitle title="Metas" subtitle="O valor reservado continua no saldo da conta e reduz o disponível estimado." action="Adicionar meta" onAction={()=>show('Meta')}/>
          {goals.map(g=><div className="goal-item" key={g.id}><div className="budget-title"><span className="cat-icon"><Target size={16}/></span><div><b>{g.name}</b><small>Objetivo: {fmt(g.target_amount)}{g.target_date?` · até ${dateLabel(g.target_date)}`:''}</small></div><strong className="trailing">Faltam {fmt(g.remaining)}</strong><button className="text-button" onClick={()=>show('Contribuição para meta',g.id)}>Registrar contribuição</button><button className="text-button" onClick={()=>void toggleGoalHistory(g.id)}>Histórico</button><button className="text-button" onClick={()=>show('Atualizar meta',g.id)}>Atualizar</button></div><div className="progress"><span style={{width:`${Math.min(100,100*Number(g.contributed_amount)/Number(g.target_amount))}%`}}/></div><div className="goal-facts"><span>Contribuído: <b>{fmt(g.contributed_amount)}</b></span><span>Reserva explícita: <b>{fmt(g.allocated_amount)}</b></span><span>Contas: <b>{g.tracking_mode==='none'?'Nenhuma':g.tracking_mode==='all'?'Todas':g.tracked_account_ids.length+' selecionada(s)'}</b></span>{g.tracking_mode!=='none'&&<><span>Saldo acompanhado: <b>{fmt(g.tracked_balance)}</b></span><span>Outras reservas: <b>{fmt(g.other_reserves)}</b></span><span>Obrigações abertas globais: <b>{fmt(g.open_obligations)}</b></span><span>Disponibilidade estimada: <b>{fmt(g.available_estimate)}</b></span></>}</div>{expandedGoal===g.id&&<div className="goal-history"><b>Contribuições</b>{contributionHistory[g.id]?.length?contributionHistory[g.id].map(item=><p key={item.id}>{dateLabel(item.contributed_on)} · {item.note}: {fmt(item.amount_delta)}</p>):<p>Nenhuma contribuição registrada.</p>}<b>Reservas</b>{goalHistory[g.id]?.length?goalHistory[g.id].map(item=><p key={item.id}>{dateLabel(item.allocated_on)} · {item.note}: {fmt(item.amount_delta)}</p>):<p>Nenhuma alteração de reserva registrada.</p>}</div>}</div>)}
          {!goals.length&&<Empty label="Nenhuma meta cadastrada" action="Adicionar meta" onAction={()=>show('Meta')}/>}
        </section>
      </>}
      <footer><span>Feito para decisões mais leves.</span><span><ShieldCheck size={14}/> Dados armazenados localmente</span></footer>
    </div></main>
    {profileOpen&&<ProfileModal profile={profile} onSave={setProfile} onClose={()=>setProfileOpen(false)}/>}
    {calendarOpen&&<FinancialCalendar categories={categories} revision={calendarVersion} onClose={()=>setCalendarOpen(false)} onNewTransaction={day=>{setCalendarOpen(false);show('Movimentação','',day)}}/>}
    {modal&&<FinanceModal type={modal.type} selectedId={modal.id} presetDate={modal.presetDate} accounts={accounts} cards={cards} purchases={purchases} categories={categories} goals={goals} investments={investments} transactions={transactions} busy={busy} onClose={()=>setModal(null)} onSubmit={submit}/>}
    {detailTx&&<div className="modal-backdrop" role="presentation" onMouseDown={event=>{if(event.target===event.currentTarget)setDetailTx(null)}}><div className="modal" role="dialog" aria-modal="true" aria-label="Detalhes da movimentação"><div className="modal-head"><h2>Detalhes da movimentação</h2><button className="icon-button" onClick={()=>setDetailTx(null)} aria-label="Fechar">×</button></div><dl className="transaction-details"><dt>Descrição</dt><dd>{detailTx.description}</dd><dt>Valor</dt><dd>{fmt(detailTx.amount)}</dd><dt>Tipo</dt><dd>{transactionKindLabel[detailTx.kind]||detailTx.kind}</dd><dt>Categoria</dt><dd>{categories.find(c=>c.id===detailTx.category_id)?.name||'—'}</dd><dt>Conta</dt><dd>{accounts.find(a=>a.id===detailTx.account_id)?.name||'—'}</dd><dt>Data</dt><dd>{dateLabel(detailTx.transaction_date)}</dd><dt>Situação</dt><dd>{detailTx.status==='settled'?'Realizada':'Pendente'}</dd>{purchases.find(p=>p.transaction_id===detailTx.id)?.installments.map(part=><div key={part.id}><dt>Parcela {part.sequence}</dt><dd>{fmt(part.amount)} · fatura {dateLabel(part.due_date)}</dd></div>)}{detailTx.notes&&<><dt>Observações</dt><dd>{detailTx.notes}</dd></>}</dl><div className="modal-actions"><button className="secondary" onClick={()=>setDetailTx(null)}>Fechar</button>{['income','expense','refund'].includes(detailTx.kind)&&detailTx.status==='settled'&&<button className="secondary" onClick={()=>{editTransaction(detailTx.id);setDetailTx(null)}}>Editar</button>}<button className="danger-outline" onClick={()=>void showDeletion(detailTx)}>Excluir…</button></div></div></div>}
    {categoryArchive&&<div className="modal-backdrop" onMouseDown={event=>{if(event.target===event.currentTarget)setCategoryArchive(null)}}><div className="modal" role="dialog" aria-modal="true" aria-label="Confirmar arquivamento da categoria"><div className="modal-head"><div><p className="eyebrow">CONFIRMAÇÃO</p><h2>Arquivar {categoryArchive.name}?</h2></div><button className="icon-button" onClick={()=>setCategoryArchive(null)} aria-label="Fechar">×</button></div><p className="modal-help">Ela deixará de aceitar novos lançamentos. {categoryArchive.transaction_count} movimentação(ões) associada(s) e seus valores serão preservados no histórico. {categoryArchive.current_spending_count>0?`Há ${fmt(categoryArchive.current_spent)} em gastos no ciclo atual. A categoria permanecerá nos indicadores desse ciclo até ${dateLabel(categoryArchive.visible_until!)}.`:'Sem gastos no ciclo atual, ela sairá dos indicadores correntes imediatamente.'}</p><div className="modal-actions"><button className="secondary" onClick={()=>setCategoryArchive(null)}>Cancelar</button><button className="danger" onClick={()=>void confirmCategoryArchive()}>Arquivar categoria</button></div></div></div>}
    {deletion&&<div className="modal-backdrop" role="presentation" onMouseDown={event=>{if(event.target===event.currentTarget)setDeletion(null)}}><div className="modal" role="dialog" aria-modal="true" aria-label="Confirmar exclusão"><div className="modal-head"><div><p className="eyebrow">CONFIRMAÇÃO</p><h2>Enviar movimentação à lixeira?</h2></div><button className="icon-button" onClick={()=>setDeletion(null)} aria-label="Fechar">×</button></div><p className="delete-summary"><b>{deletion.tx.description}</b><br/>{transactionKindLabel[deletion.tx.kind]||deletion.tx.kind} de {fmt(deletion.tx.amount)} · {dateLabel(deletion.tx.transaction_date)}<br/>{categories.find(c=>c.id===deletion.tx.category_id)?.name||'Sem categoria'} · {accounts.find(a=>a.id===deletion.tx.account_id)?.name||'Conta desconhecida'}</p><p className="modal-help">{deletion.preview.effect}</p><div className="modal-actions"><button className="secondary" onClick={()=>setDeletion(null)}>Cancelar</button>{deletion.preview.can_delete&&<button className="danger" onClick={()=>void confirmDeletion()}>Confirmar exclusão</button>}</div></div></div>}
    {toast&&<div className="toast" role="status">{toast}{undoId&&<button onClick={()=>void restoreDeleted(undoId)}>Desfazer</button>}</div>}
  </div>
}

function Metric({label,value,detail,icon,tone}:{label:string;value:string;detail:string;icon:ReactNode;tone:string}){return <div className="metric-card"><div className="metric-top"><span>{label}</span><i className={`metric-icon ${tone}`}>{icon}</i></div><strong>{value}</strong><small>{detail}</small></div>}
function PanelTitle({title,subtitle,action,onAction}:{title:string;subtitle:string;action?:string;onAction?:()=>void}){return <div className="panel-head"><div><h2>{title}</h2><p>{subtitle}</p></div>{action&&<button className="more-link" onClick={onAction}>{action}</button>}</div>}
function Empty({label,detail,action,onAction}:{label:string;detail?:string;action?:string;onAction?:()=>void}){return <div className="empty-state"><div className="empty-symbol"><Activity size={21}/></div><b>{label}</b>{detail&&<p>{detail}</p>}{action&&<button className="secondary" onClick={onAction}>{action}</button>}</div>}
function BudgetRows({rows,onOpen}:{rows:Overview['budget_status'];onOpen:()=>void}){return rows.length?rows.map(b=><div className="budget-row" key={b.category_id}><div className="budget-title"><span className="cat-icon" style={{color:b.color}}><CategoryIcon icon={b.icon} name={b.category}/></span><div><b>{b.category}</b><small>{fmt(b.spent)} de {fmt(b.limit)} · ciclo {dateLabel(b.period_start)} a {dateLabel(b.period_end)}{b.projection!=null?` · fechamento estimado ${fmt(b.projection)}`:''}</small></div><strong className={Number(b.remaining)<0?'over':''}>{fmt(b.remaining)} restantes</strong></div><div className="progress"><span style={{width:`${Math.min(100,Math.max(0,Number(b.percent_used||0)))}%`,background:b.color}}/></div></div>):<Empty label="Seu orçamento começa aqui" detail="Defina um limite para saber quanto ainda pode gastar em cada categoria." action="Montar orçamento" onAction={onOpen}/>}
function Fact({label,value}:{label:string;value:string}){return <div className="fact"><span>{label}</span><strong>{value}</strong></div>}
function CardPurchaseList({rows,categories,onEdit,onDelete,onDetails}:{rows:CardPurchase[];categories:Category[];onEdit:(row:CardPurchase)=>void;onDelete:(row:CardPurchase)=>void;onDetails:(row:CardPurchase)=>void}){
  return rows.length?<div className="card-purchase-list">{rows.map(row=><div className="card-purchase-item" key={row.id}><div><b>{row.merchant}</b><small>{row.card} · {categories.find(category=>category.id===row.category_id)?.name||'Categoria'} · {dateLabel(row.purchase_date)} · {row.installment_count} parcela(s)</small></div><strong>{fmt(row.total_amount)}</strong><button className="text-button" onClick={()=>onDetails(row)}>Detalhes</button><button className="text-button" onClick={()=>onEdit(row)}>Editar</button><button className="danger-link" onClick={()=>onDelete(row)}>Excluir…</button></div>)}</div>:<p className="hint">Nenhuma compra neste cartão ou fatura.</p>
}
function Transactions({rows,categories,accounts,onCorrect,onSettle,onDetails,onDelete}:{rows:Transaction[];categories:Category[];accounts:Account[];onCorrect?:(id:string)=>void;onSettle?:(id:string)=>void;onDetails?:(row:Transaction)=>void;onDelete?:(row:Transaction)=>void}){
  const actions=Boolean(onCorrect||onSettle||onDetails||onDelete)
  return <div className="table-wrap"><table><thead><tr><th>DESCRIÇÃO</th><th>CATEGORIA</th><th>DATA</th><th>CONTA</th><th className="right">VALOR</th>{actions&&<th className="right">AÇÃO</th>}</tr></thead><tbody>
    {rows.length?rows.map(t=><tr key={t.id}>
      <td><span className={`tx-icon ${t.kind}`}><ArrowLeftRight size={16}/></span><b>{t.description}</b>{t.status==='pending'&&<span className="pending-tag">Pendente</span>}{t.notes&&<small className="transaction-note">{t.notes}</small>}</td>
      <td><span className="tag category-tag" style={{borderLeft:t.category_id?`3px solid ${categories.find(c=>c.id===t.category_id)?.color||'#9BA39D'}`:undefined}}>{t.category_id&&<CategoryIcon icon={categories.find(c=>c.id===t.category_id)?.icon} name={categories.find(c=>c.id===t.category_id)?.name||'Categoria'} size={13}/>} {categories.find(c=>c.id===t.category_id)?.name||'—'}</span></td>
      <td>{dateLabel(t.transaction_date)}{t.settled_date&&t.settled_date!==t.transaction_date&&<small className="transaction-note">Realizada em {dateLabel(t.settled_date)}</small>}</td>
      <td>{accounts.find(a=>a.id===t.account_id)?.name||'—'}</td>
      <td className={`right amount ${['income','refund','transfer_in'].includes(t.kind)?'positive':''}`}>{['expense','investment','transfer_out'].includes(t.kind)?'−':'+'}{fmt(t.amount)}</td>
      {actions&&<td className="right table-actions">
        {t.status==='pending'&&onSettle&&<button className="text-button" onClick={()=>onSettle(t.id)}>Marcar realizada</button>}
        {onCorrect&&['income','expense','refund'].includes(t.kind)&&t.status==='settled'&&<button className="text-button" onClick={()=>onCorrect(t.id)}>Editar</button>}
        {onDetails&&<button className="text-button" onClick={()=>onDetails(t)}>Detalhes</button>}
        {onDelete&&<button className="danger-link" onClick={()=>onDelete(t)}>Excluir…</button>}
      </td>}
    </tr>):<tr><td colSpan={actions?6:5} className="empty-table">Nenhuma movimentação registrada ainda.</td></tr>}
  </tbody></table></div>
}
