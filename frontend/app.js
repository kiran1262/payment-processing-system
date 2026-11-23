const money = value => new Intl.NumberFormat("en-IN",{style:"currency",currency:"INR",maximumFractionDigits:2}).format(value || 0);
const el = id => document.getElementById(id);
const token = () => sessionStorage.getItem("payment_demo_token");
let currentUser = null;
function setAuthenticated(user){
  currentUser = user;
  document.body.classList.add("authenticated");
  el("authMessage").textContent = "";
  el("logoutBtn").hidden = false;
  const workspaceName = user.tenant_name || "Demo workspace";
  const initials = (user.full_name || "U").trim().split(/\s+/).slice(0,2).map(part=>part[0]).join("").toUpperCase();
  el("workspaceName").textContent = workspaceName;
  el("workspaceAvatar").textContent = workspaceName.slice(0,1).toUpperCase();
  el("profileName").textContent = user.full_name;
  el("profileRole").textContent = user.role === "owner" ? "Owner" : "Member";
  el("profileAvatar").textContent = initials;
  el("topbarAvatar").textContent = initials;
}
function clearAuthentication(message=""){
  currentUser = null;
  sessionStorage.removeItem("payment_demo_token");
  document.body.classList.remove("authenticated");
  el("logoutBtn").hidden = true;
  el("authMessage").textContent = message;
  el("authMessage").className = message ? "form-message error" : "form-message";
}
async function request(url, options = {}) {
  const headers = {"Content-Type":"application/json",...(options.headers || {})};
  if(token()) headers.Authorization = `Bearer ${token()}`;
  const response = await fetch(url,{...options,headers});
  const data = await response.json().catch(()=>({detail:"Unexpected server response"}));
  if(!response.ok){
    const detail=data.detail;
    let message=Array.isArray(detail)?detail.map(item=>item.msg||"Invalid value").join("; "):(detail||`Request failed (${response.status})`);
    if(response.status===429){
      const retryAfter=response.headers.get("Retry-After");
      if(retryAfter) message += ` Please retry in ${retryAfter} seconds.`;
    }
    if(response.status===401 && url!=="/api/auth/login" && url!=="/api/auth/register") clearAuthentication("Your session expired. Please sign in again.");
    throw new Error(message);
  }
  return data;
}
async function authenticate(path, values){
  const result=await request(path,{method:"POST",body:JSON.stringify(values)});
  sessionStorage.setItem("payment_demo_token",result.access_token);
  setAuthenticated(result.user);
  await loadDashboard();
}
el("loginForm").addEventListener("submit",async event=>{
  event.preventDefault();const form=event.currentTarget;
  try{await authenticate("/api/auth/login",Object.fromEntries(new FormData(form).entries()));form.reset();}
  catch(error){el("authMessage").textContent=error.message;el("authMessage").className="form-message error";}
});
el("registerForm").addEventListener("submit",async event=>{
  event.preventDefault();const form=event.currentTarget;
  try{await authenticate("/api/auth/register",Object.fromEntries(new FormData(form).entries()));form.reset();}
  catch(error){el("authMessage").textContent=error.message;el("authMessage").className="form-message error";}
});
el("logoutBtn").addEventListener("click",async()=>{
  try{if(token()) await request("/api/auth/logout",{method:"POST"});}
  catch(error){console.warn("Logout request failed",error);}
  clearAuthentication("You have signed out.");
});
async function loadDashboard(){
  try{
    const [stats,payments]=await Promise.all([request("/api/dashboard"),request("/api/payments")]);
    el("totalTransactions").textContent=stats.total_transactions;
    el("successfulPayments").textContent=stats.successful;
    el("paymentVolume").textContent=money(stats.revenue_paise/100);
    el("successRate").textContent=`${stats.success_rate}%`;
    el("methodCount").textContent=stats.total_transactions;
    el("cardCount").textContent=stats.methods.Card;
    el("upiCount").textContent=stats.methods.UPI;
    el("walletCount").textContent=stats.methods.Wallet;
    el("netCount").textContent=stats.methods["Net Banking"];
    renderPayments(payments);
  }catch(error){
    console.error(error);
    if(token()){el("formMessage").textContent=`Could not load data: ${error.message}`;el("formMessage").className="form-message error";}
  }
}
function renderPayments(payments){
  const body=el("transactionRows");
  if(!payments.length){body.innerHTML='<tr><td colspan="7" class="empty">No transactions yet. Create your first simulated payment.</td></tr>';return;}
  body.innerHTML=payments.map(p=>{
    const date=p.created_at?new Date(p.created_at).toLocaleString("en-IN",{day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit"}):"—";
    const canRefund=currentUser?.role==="owner" && p.status==="succeeded";
    return `<tr><td class="payment-ref">${escapeHtml(p.payment_id)}</td><td class="customer-cell"><b>${escapeHtml(p.customer_name)}</b><small>${escapeHtml(p.customer_email)}</small></td><td>${date}</td><td>${escapeHtml(p.method)}</td><td><b>${money(p.amount)}</b></td><td><span class="status ${p.status}">${p.status}</span></td><td>${canRefund?'<button class="refund-btn" data-refund="'+escapeHtml(p.payment_id)+'">Refund</button>':""}</td></tr>`;
  }).join("");
}
function escapeHtml(value){return String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
async function fingerprint(values){
  const bytes=new TextEncoder().encode(JSON.stringify(values));
  const digest=await crypto.subtle.digest("SHA-256",bytes);
  return Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,"0")).join("");
}
el("paymentForm").addEventListener("submit",async event=>{
  event.preventDefault();
  const form=event.currentTarget,button=el("payBtn"),message=el("formMessage");
  const values=Object.fromEntries(new FormData(form).entries());
  values.amount=Number(values.amount);
  button.disabled=true;button.textContent="Processing…";message.textContent="";message.className="form-message";
  try{
    const requestFingerprint=await fingerprint(values);
    let key=sessionStorage.getItem("pending_payment_key");
    const previousFingerprint=sessionStorage.getItem("pending_payment_fingerprint");
    if(!key || previousFingerprint!==requestFingerprint){
      key=crypto.randomUUID();
      sessionStorage.setItem("pending_payment_key",key);
      sessionStorage.setItem("pending_payment_fingerprint",requestFingerprint);
    }
    const result=await request("/api/payments",{method:"POST",headers:{"Idempotency-Key":key},body:JSON.stringify(values)});
    sessionStorage.removeItem("pending_payment_key");
    sessionStorage.removeItem("pending_payment_fingerprint");
    message.textContent=result.status==="succeeded"?`✓ Simulated payment ${result.payment_id} completed.`:`Simulated payment ${result.payment_id} was declined.`;
    if(result.status==="declined")message.className="form-message error";
    form.reset();await loadDashboard();
  }catch(error){
    console.error("Payment request failed:",error);
    message.textContent=`${error.message||"Payment request failed."} If the response was lost, retry without changing the form to safely reuse the same request key.`;
    message.className="form-message error";
  }finally{
    button.disabled=false;button.innerHTML='Process simulated payment <span>→</span>';
  }
});
el("transactionRows").addEventListener("click",async event=>{
  const button=event.target.closest("[data-refund]");if(!button)return;
  if(!confirm("Refund this simulated payment?"))return;
  button.disabled=true;
  try{await request(`/api/payments/${encodeURIComponent(button.dataset.refund)}/refund`,{method:"POST"});await loadDashboard();}
  catch(error){alert(error.message);button.disabled=false;}
});
el("refreshBtn").addEventListener("click",loadDashboard);
(async()=>{
  if(!token())return;
  try{const user=await request("/api/auth/me");setAuthenticated(user);await loadDashboard();}
  catch(error){clearAuthentication("Please sign in to access your demo workspace.");}
})();
