const money = value => new Intl.NumberFormat("en-IN",{style:"currency",currency:"INR",maximumFractionDigits:2}).format(value || 0);
const el = id => document.getElementById(id);
async function request(url, options = {}) {
  // Keep JSON Content-Type while preserving custom headers such as Idempotency-Key.
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    }
  });

  const data = await response.json().catch(() => ({
    detail: "Unexpected server response"
  }));

  if (!response.ok) {
    const detail = data.detail;
    let message;

    if (Array.isArray(detail)) {
      message = detail.map(item => {
        const field = Array.isArray(item.loc)
          ? item.loc.filter(part => part !== "body").join(" → ")
          : "Validation error";
        return `${field || "Request"}: ${item.msg || "Invalid value"}`;
      }).join("; ");
    } else if (detail && typeof detail === "object") {
      message = JSON.stringify(detail);
    } else {
      message = detail || `Request failed (${response.status})`;
    }

    throw new Error(message);
  }

  return data;
}
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
  }catch(error){console.error(error);el("formMessage").textContent=`Could not load data: ${error.message}`;el("formMessage").className="form-message error";}
}
function renderPayments(payments){
  const body=el("transactionRows");
  if(!payments.length){body.innerHTML='<tr><td colspan="7" class="empty">No transactions yet. Create your first payment.</td></tr>';return;}
  body.innerHTML=payments.map(p=>{
    const date=p.created_at?new Date(p.created_at).toLocaleString("en-IN",{day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit"}):"—";
    const canRefund=p.status==="succeeded";
    return `<tr><td class="payment-ref">${escapeHtml(p.payment_id)}</td><td class="customer-cell"><b>${escapeHtml(p.customer_name)}</b><small>${escapeHtml(p.customer_email)}</small></td><td>${date}</td><td>${escapeHtml(p.method)}</td><td><b>${money(p.amount)}</b></td><td><span class="status ${p.status}">${p.status}</span></td><td>${canRefund?`<button class="refund-btn" data-refund="${escapeHtml(p.payment_id)}">Refund</button>`:""}</td></tr>`;
  }).join("");
}
function escapeHtml(value){return String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
el("paymentForm").addEventListener("submit",async event=>{
  event.preventDefault();
  const form=event.currentTarget,button=el("payBtn"),message=el("formMessage");
  const values=Object.fromEntries(new FormData(form).entries());
  values.amount=Number(values.amount);
  button.disabled=true;button.textContent="Processing…";message.textContent="";message.className="form-message";
  try{
    const result=await request("/api/payments",{method:"POST",headers:{"Idempotency-Key":crypto.randomUUID()},body:JSON.stringify(values)});
    message.textContent=result.status==="succeeded"?`✓ Payment ${result.payment_id} completed successfully.`:`Payment ${result.payment_id} was declined (demo scenario).`;
    if(result.status==="declined")message.className="form-message error";
    form.reset();await loadDashboard();
  } catch (error) {
    console.error("Payment request failed:", error);
    message.textContent = error.message || "Payment could not be processed. Please try again.";
    message.className = "form-message error";
  } finally {
    button.disabled = false;
    button.innerHTML = 'Process payment <span>→</span>';
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
loadDashboard();
