(() => {
  const $ = (s) => document.querySelector(s);
  const thread = $("#thread"), form = $("#composer"), input = $("#q"), send = $("#send");
  let sessionId = null, dept = "", lastQuestion = "";

  const token = () => localStorage.getItem("sop_token") || "";

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  // Safe mini-renderer: paragraphs, numbered/bulleted lists, **bold**, [n] citations. Never uses innerHTML.
  function inline(parent, text, onCite) {
    const re = /(\*\*[^*]+\*\*|\[\d+\])/g;
    text.split(re).forEach((part) => {
      if (/^\*\*[^*]+\*\*$/.test(part)) parent.appendChild(el("strong", null, part.slice(2, -2)));
      else if (/^\[\d+\]$/.test(part)) {
        const b = el("button", "cite", part.slice(1, -1));
        b.type = "button"; b.setAttribute("aria-label", "Show source " + part);
        b.addEventListener("click", () => onCite(Number(part.slice(1, -1))));
        parent.appendChild(b);
      } else if (part) parent.appendChild(document.createTextNode(part));
    });
  }

  function renderAnswer(text, onCite) {
    const box = el("div", "answer");
    let list = null;
    text.split("\n").forEach((line) => {
      const ol = line.match(/^\s*\d+[.)]\s+(.*)/), ul = line.match(/^\s*[-*•]\s+(.*)/);
      if (ol || ul) {
        const want = ol ? "ol" : "ul";
        if (!list || list.tagName.toLowerCase() !== want) { list = el(want); box.appendChild(list); }
        const li = el("li"); inline(li, (ol || ul)[1], onCite); list.appendChild(li);
      } else if (line.trim()) {
        list = null; const p = el("p"); inline(p, line, onCite); box.appendChild(p);
      }
    });
    return box;
  }

  function addUser(text) {
    $("#empty")?.remove();
    thread.appendChild(el("div", "msg you", text));
    thread.scrollTop = thread.scrollHeight;
  }

  function addThinking() {
    const m = el("div", "msg bot"); const d = el("div", "answer dots");
    d.append(el("span"), el("span"), el("span")); d.setAttribute("aria-label", "Looking up the SOPs");
    m.appendChild(d); thread.appendChild(m); thread.scrollTop = thread.scrollHeight; return m;
  }

  function addBot(holder, data) {
    holder.replaceChildren();
    const cards = {};
    const answer = renderAnswer(data.answer, (n) => {
      const c = cards[n]; if (!c) return;
      c.classList.add("flash"); c.scrollIntoView({ block: "nearest", behavior: "smooth" });
      setTimeout(() => c.classList.remove("flash"), 1200);
    });
    if (/fire|injur|unwell|emergency|first aid|evacuat/i.test(data.answer)) answer.classList.add("safety");
    holder.appendChild(answer);

    const cited = data.sources.filter((s) => s.cited);
    if (cited.length) {
      const wrap = el("div", "sources");
      cited.forEach((s) => {
        const c = el("div", "sop"); c.dataset.dept = s.department; cards[s.ref] = c;
        c.appendChild(el("div", "sop-head", `[${s.ref}] ${s.sop_id} · ${s.title}`));
        c.appendChild(el("div", "sop-meta", `Version ${s.version} · ${s.section}${s.page ? " · page " + s.page : ""}`));
        c.appendChild(el("p", "sop-snippet", s.snippet + (s.snippet.length >= 240 ? "…" : "")));
        wrap.appendChild(c);
      });
      holder.appendChild(wrap);
    }

    const fb = el("div", "fb"); fb.appendChild(el("span", null, "Was this helpful?"));
    ["up", "down"].forEach((r) => {
      const b = el("button", null, r === "up" ? "Yes" : "No"); b.type = "button"; b.setAttribute("aria-pressed", "false");
      b.addEventListener("click", async () => {
        fb.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", "false"));
        b.setAttribute("aria-pressed", "true");
        await api("/v1/feedback", { session_id: data.session_id, message_id: data.message_id, rating: r }).catch(() => {});
      });
      fb.appendChild(b);
    });
    holder.appendChild(fb);
    thread.scrollTop = thread.scrollHeight;
  }

  async function api(path, body) {
    const headers = { "content-type": "application/json" };
    if (token()) headers.authorization = "Bearer " + token();
    const res = await fetch(path, { method: "POST", headers, body: JSON.stringify(body) });
    if (res.status === 401) { const e = new Error("auth"); e.code = 401; throw e; }
    if (!res.ok) { const j = await res.json().catch(() => ({})); throw new Error(j.detail || "Request failed"); }
    return res.status === 204 ? null : res.json();
  }

  async function ask(question) {
    lastQuestion = question; addUser(question);
    const holder = addThinking(); send.disabled = true;
    try {
      const data = await api("/v1/chat", { question, session_id: sessionId, department: dept || null });
      sessionId = data.session_id; addBot(holder, data);
    } catch (e) {
      holder.replaceChildren();
      if (e.code === 401) { holder.appendChild(el("div", "answer err", "You're not signed in. Add a token, then ask again.")); $("#token-dialog").showModal(); }
      else holder.appendChild(el("div", "answer err", e.message + " Try again in a moment."));
    } finally { send.disabled = false; input.focus(); }
  }

  form.addEventListener("submit", (ev) => {
    ev.preventDefault(); const q = input.value.trim(); if (!q) return;
    input.value = ""; input.style.height = "auto"; ask(q);
  });
  input.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); form.requestSubmit(); } });
  input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 140) + "px"; });
  document.querySelectorAll(".starter").forEach((b) => b.addEventListener("click", () => ask(b.textContent)));
  document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
    document.querySelectorAll(".chip").forEach((x) => x.classList.remove("on")); c.classList.add("on"); dept = c.dataset.dept;
  }));
  $("#new-chat").addEventListener("click", () => location.reload());
  $("#token-save").addEventListener("click", () => { localStorage.setItem("sop_token", $("#token-input").value.trim()); if (lastQuestion) setTimeout(() => ask(lastQuestion), 0); });
})();
