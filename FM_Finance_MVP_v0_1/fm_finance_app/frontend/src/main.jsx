import React, {useEffect, useMemo, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {LayoutDashboard, Landmark, ArrowLeftRight, ReceiptText, FileText, Building2, WandSparkles, ChartNoAxesCombined, Settings, Search, Check, Upload, Plus} from 'lucide-react';
import './styles.css';

const API='http://127.0.0.1:8000/api';
const money = n => new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(Number(n||0));

const nav=[
 ['Dashboard',LayoutDashboard],['Banking',Landmark],['Transactions',ArrowLeftRight],['Expenses',ReceiptText],['Receipts',FileText],['Vendors',Building2],['Rules',WandSparkles],['Reports',ChartNoAxesCombined],['Settings',Settings]
];

function App(){
 const [page,setPage]=useState('Dashboard'); const [dash,setDash]=useState(null); const [tx,setTx]=useState([]); const [accounts,setAccounts]=useState([]); const [cats,setCats]=useState([]); const [rules,setRules]=useState([]);
 const load=async()=>{const [d,t,a,c,r]=await Promise.all([fetch(`${API}/dashboard`).then(r=>r.json()),fetch(`${API}/transactions`).then(r=>r.json()),fetch(`${API}/accounts`).then(r=>r.json()),fetch(`${API}/categories`).then(r=>r.json()),fetch(`${API}/rules`).then(r=>r.json())]);setDash(d);setTx(t);setAccounts(a);setCats(c);setRules(r)};
 useEffect(()=>{load()},[]);
 const approve=async id=>{await fetch(`${API}/transactions/${id}/approve`,{method:'POST'});load()};
 const review=tx.filter(t=>t.status==='review');
 return <div className="app">
   <aside><div className="brand"><div className="logo">FM</div><div><b>FM Finance</b><span>Smart Books</span></div></div><nav>{nav.map(([n,I])=><button key={n} className={page===n?'active':''} onClick={()=>setPage(n)}><I size={19}/><span>{n}</span>{n==='Banking'&&review.length>0?<em>{review.length}</em>:null}</button>)}</nav><div className="sidefoot"><span>Demo company</span><b>FM Finance Demo</b></div></aside>
   <main><header><div><h1>{page}</h1><p>{subtitle(page)}</p></div><div className="header-actions"><div className="search"><Search size={17}/><input placeholder="Search transactions..."/></div><button className="primary"><Plus size={17}/>Add transaction</button></div></header>
   {page==='Dashboard'&&<Dashboard dash={dash} tx={tx} accounts={accounts} approve={approve}/>} 
   {page==='Banking'&&<Banking tx={review} approve={approve}/>} 
   {page==='Transactions'&&<Transactions tx={tx}/>} 
   {page==='Expenses'&&<Expenses tx={tx}/>} 
   {page==='Receipts'&&<Receipts onUploaded={load}/>} 
   {page==='Rules'&&<Rules rules={rules}/>} 
   {page==='Reports'&&<Reports/>}
   {['Vendors','Settings'].includes(page)&&<Empty page={page}/>} 
   </main>
 </div>
}

function subtitle(p){return {Dashboard:'Your financial position at a glance.',Banking:'Review imported bank and card activity.',Transactions:'Search and manage every transaction.',Expenses:'Track business spending and deductions.',Receipts:'Capture and organize supporting documents.',Vendors:'Manage merchants and payees.',Rules:'Automate transaction categorization.',Reports:'Understand business performance.',Settings:'Configure your company and integrations.'}[p]}

function Dashboard({dash,tx,accounts,approve}){if(!dash)return <div className="loading">Loading...</div>; const recent=tx.slice(0,5);return <>
 <section className="cards"><Metric label="Available cash" value={money(dash.cash)} note="Across cash accounts"/><Metric label="Income" value={money(dash.income)} note="Current dataset"/><Metric label="Expenses" value={money(dash.expenses)} note="Current dataset"/><Metric label="Net cash flow" value={money(dash.net_cash_flow)} note={dash.net_cash_flow>=0?'Positive cash flow':'Negative cash flow'}/></section>
 <section className="grid2"><div className="panel"><PanelTitle title="Needs attention" sub={`${dash.needs_review} transactions require review`}/><TxnTable rows={recent} approve={approve} compact/></div><div className="panel"><PanelTitle title="Connected accounts" sub="Balances from your financial accounts"/><div className="accountlist">{accounts.map(a=><div className="account" key={a.id}><div className="bankicon"><Landmark size={19}/></div><div><b>{a.name}</b><span>{a.institution} •••• {a.last4||'—'}</span></div><strong>{money(a.balance)}</strong></div>)}</div></div></section>
 <section className="panel"><PanelTitle title="Spending overview" sub="Where your money is going"/><SpendBars tx={tx}/></section>
 </>}
function Metric({label,value,note}){return <div className="metric"><span>{label}</span><strong>{value}</strong><small>{note}</small></div>}
function PanelTitle({title,sub}){return <div className="paneltitle"><div><h2>{title}</h2><p>{sub}</p></div></div>}
function Banking({tx,approve}){return <div className="panel"><div className="bankingtop"><div><h2>For review</h2><p>Approve the suggestions, or open a transaction to correct it.</p></div><span className="pill">{tx.length} pending</span></div><TxnTable rows={tx} approve={approve}/></div>}
function Transactions({tx}){return <div className="panel"><PanelTitle title="All transactions" sub={`${tx.length} transactions`}/><TxnTable rows={tx}/></div>}
function Expenses({tx}){const rows=tx.filter(t=>t.amount<0);return <div className="panel"><PanelTitle title="Business expenses" sub={`${rows.length} expense transactions`}/><TxnTable rows={rows}/></div>}
function TxnTable({rows,approve,compact}){return <div className="tablewrap"><table><thead><tr><th>Transaction</th><th>Category</th><th>Amount</th><th>Receipt</th><th>Confidence</th><th>Status</th></tr></thead><tbody>{rows.map(t=><tr key={t.id}><td><b>{t.description}</b><span>{new Date(t.date).toLocaleDateString()} · {t.account}</span></td><td>{t.category||'Uncategorized'}</td><td className={t.amount>=0?'income':'expense'}>{money(t.amount)}</td><td>{t.receipt_attached?'Matched':'Missing'}</td><td>{t.confidence?`${t.confidence}%`:'—'}</td><td>{t.status==='review'&&approve?<button className="approve" onClick={()=>approve(t.id)}><Check size={15}/>Approve</button>:<span className={`status ${t.status}`}>{t.status}</span>}</td></tr>)}</tbody></table>{rows.length===0?<div className="emptyrow">Nothing waiting for you.</div>:null}</div>}
function SpendBars({tx}){const m={};tx.filter(t=>t.amount<0).forEach(t=>m[t.category]=(m[t.category]||0)+Math.abs(t.amount));const rows=Object.entries(m).sort((a,b)=>b[1]-a[1]);const max=Math.max(...rows.map(r=>r[1]),1);return <div className="bars">{rows.map(([n,v])=><div className="barrow" key={n}><span>{n}</span><div><i style={{width:`${v/max*100}%`}}/></div><b>{money(v)}</b></div>)}</div>}
function Receipts({onUploaded}){const [name,setName]=useState('');const upload=async e=>{const f=e.target.files?.[0];if(!f)return;const fd=new FormData();fd.append('file',f);await fetch(`${API}/receipts/upload`,{method:'POST',body:fd});setName(f.name);onUploaded()};return <div className="panel"><PanelTitle title="Receipt inbox" sub="Upload receipts now; OCR and matching are the next integration layer."/><label className="drop"><Upload size={34}/><b>Drop or choose a receipt</b><span>PDF, JPG or PNG</span><input type="file" onChange={upload}/></label>{name&&<div className="success">Uploaded: {name}</div>}</div>}
function Rules({rules}){return <div className="panel"><PanelTitle title="Automation rules" sub="Rules classify repeat merchants automatically."/><div className="rulelist">{rules.map(r=><div className="rule" key={r.id}><div><b>{r.name}</b><span>If merchant contains “{r.merchant_contains}”</span></div><div><strong>{r.category}</strong><span>{r.auto_approve?'Auto-approve':'Review first'}</span></div></div>)}</div></div>}
function Reports(){const [rows,setRows]=useState([]);useEffect(()=>{fetch(`${API}/reports/expense-by-category`).then(r=>r.json()).then(setRows)},[]);return <div className="panel"><PanelTitle title="Expense by category" sub="Current dataset"/><div className="reportlist">{rows.map(r=><div><span>{r.category}</span><b>{money(r.amount)}</b></div>)}</div></div>}
function Empty({page}){return <div className="panel empty"><h2>{page}</h2><p>This module is scaffolded and ready for the next build pass.</p></div>}

createRoot(document.getElementById('root')).render(<App/>);
