// On a hosted server, the title band shows who is signed in, with Account and Sign out (all pages).
(async () => {
  let me;
  try { me = await (await fetch("/api/me")).json(); } catch { return; }
  if (!me || !me.hosted || !me.name) return;
  const nav = document.querySelector(".brand nav");
  if (!nav) return;
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  nav.insertAdjacentHTML("beforeend", `<a href="/account" title="${esc(me.role)}: change password, listener token">${esc(me.name)}</a><a href="#" id="signout">Sign out</a>`);
  document.getElementById("signout").onclick = async (e) => {
    e.preventDefault();
    await fetch("/api/auth/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    location.replace("/login");
  };
})();
