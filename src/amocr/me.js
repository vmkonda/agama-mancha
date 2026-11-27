// On a hosted server, the title band shows who is signed in, with Account and Sign out (all pages),
// and when someone has asked this person for help with a line, or answered their question.
(async () => {
  let me;
  try { me = await (await fetch("/api/me")).json(); } catch { return; }
  if (!me || !me.hosted || !me.name) return;
  const nav = document.querySelector(".brand nav");
  if (!nav) return;
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  nav.insertAdjacentHTML("beforeend", `<a href="#" id="helpbell" hidden></a><a href="/account" title="${esc(me.role)}: change password, listener token">${esc(me.name)}</a><a href="#" id="signout">Sign out</a>`);
  document.getElementById("signout").onclick = async (e) => {
    e.preventDefault();
    await fetch("/api/auth/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    location.replace("/login");
  };

  // Help with a line (Proofread → Ask someone): what's waiting for me, and answers to my questions.
  const bell = document.getElementById("helpbell");
  const box = document.createElement("div");
  box.id = "helpbox";
  box.hidden = true;
  box.style.cssText = "position:fixed;top:52px;right:16px;z-index:50;width:min(440px,calc(100vw - 32px));max-height:70vh;overflow:auto;" +
    "background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:10px 12px;box-shadow:0 8px 28px rgba(0,0,0,.18);font-size:14px";
  document.body.appendChild(box);
  const line = (r, what) => `<a href="/proofread#${encodeURIComponent(r.work)}/${r.page}/line=${r.n}" style="display:block;padding:6px 0;border-top:1px solid var(--line);color:inherit;text-decoration:none">
      <b>${esc(what)}</b> · ${esc(r.title)} · p${r.page} line ${r.n}<br><span style="color:var(--muted)">${esc(r.question)}</span></a>`;
  async function refresh() {
    let h;
    try { const r = await fetch("/api/help/mine"); if (!r.ok) return; h = await r.json(); } catch { return; }
    const n = h.asked.length, m = h.answered.length;
    bell.hidden = !(n || m);
    bell.textContent = [n && `Asked for help: ${n}`, m && `Answers: ${m}`].filter(Boolean).join(" · ");
    bell.title = "Questions about lines: open one to see it on its page";
    box.innerHTML = (n ? `<div style="font-weight:600;margin:2px 0 4px">Asked of you</div>` + h.asked.map((r) => line(r, `${r.by} asks`)).join("") : "")
      + (m ? `<div style="font-weight:600;margin:10px 0 4px">Answers to your questions</div>` + h.answered.map((r) => line(r, `${r.answers} answer${r.answers === 1 ? "" : "s"}`)).join("") : "")
      || `<span style="color:var(--muted)">Nothing waiting.</span>`;
  }
  bell.onclick = (e) => { e.preventDefault(); box.hidden = !box.hidden; };
  document.addEventListener("click", (e) => { if (!box.hidden && !box.contains(e.target) && e.target !== bell) box.hidden = true; });
  window.amHelpRefresh = refresh;   // Proofread calls it after asking, answering or closing
  refresh();
  setInterval(refresh, 60000);
})();
