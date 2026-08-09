/* Meridian — front-end renderer.
   Reads static JSON from ./data (written by scripts/pull.py locally,
   later by the Cloudflare Worker cron). */

const $ = (s) => document.querySelector(s);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function load(name) {
  try {
    const r = await fetch(`./data/${name}.json?t=${Date.now()}`);
    if (!r.ok) throw new Error(r.status);
    return await r.json();
  } catch {
    return null;
  }
}

/* ---------- clock ---------- */
function tick() {
  const d = new Date();
  const h = d.getHours(), m = d.getMinutes(), s = d.getSeconds();
  const h12 = h % 12 || 12, am = h < 12 ? "AM" : "PM";
  $("#digital").innerHTML = `${h12}:${String(m).padStart(2, "0")}<small>${am}</small>`;
  const rot = (id, deg) => document.getElementById(id).setAttribute("transform", `rotate(${deg} 50 50)`);
  rot("hh", (h % 12) * 30 + m * 0.5);
  rot("mh", m * 6 + s * 0.1);
  rot("sh", s * 6);
  setTimeout(tick, 1000);
}

function dateline(updatedISO) {
  const d = new Date();
  const day = d.toLocaleDateString("en-US", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  let s = day.replace(/, /g, " · ");
  if (updatedISO) {
    const u = new Date(updatedISO);
    s += ` · Updated ${u.getHours()}:${String(u.getMinutes()).padStart(2, "0")}`;
  }
  $("#dateline").textContent = s;
}

/* ---------- weather ---------- */
function renderWeather(w) {
  if (!w) { $("#weather-panel").innerHTML = `<div class="empty">Weather unavailable — run scripts/pull.py</div>`; return; }
  $("#weather-meta").textContent =
    `Raleigh–Durham · AQI ${w.aqi ?? "—"} ${w.aqiLabel ?? ""} · Sunrise ${w.sunrise} · Sunset ${w.sunset}`;
  $("#weather-panel").innerHTML = `
    <div class="weather-wrap">
      <div class="weather-main">
        <div class="weather-temp">${Math.round(w.temp)}°</div>
        <div class="weather-desc">${esc(w.desc)}</div>
      </div>
      <div class="weather-hours">
        ${w.hours.map((h) => `
          <div class="wh">
            <div class="h">${esc(h.h)}</div>
            <div class="g">${h.icon}</div>
            <div class="t">${Math.round(h.t)}°</div>
            <div class="p">${h.p}%</div>
          </div>`).join("")}
      </div>
    </div>`;
}

/* ---------- calendar & tasks ---------- */
function renderDay(cal, tasks) {
  if (cal) {
    $("#cal-tag").hidden = !cal.sample;
    $("#calendar-list").innerHTML = cal.events.length
      ? cal.events.map((e) => `
          <div class="event${e.now ? " now" : ""}">
            <div class="time">${esc(e.time)}</div>
            <div><div class="what">${esc(e.what)}${e.star ? " ★" : ""}</div>
            <div class="where">${esc(e.where ?? "")}</div></div>
          </div>`).join("")
      : `<div class="empty">Nothing scheduled — a clear day.</div>`;
  }
  if (tasks) {
    $("#task-tag").hidden = !tasks.sample;
    const done = tasks.items.filter((t) => t.done).length;
    $("#tasks-label").firstChild.textContent = `Tasks · ${done} of ${tasks.items.length} done`;
    $("#tasks-list").innerHTML = tasks.items.map((t) => `
      <div class="habit${t.done ? " done" : ""}">
        <div class="left"><span class="mark">${t.done ? "✓" : ""}</span>${esc(t.text)}</div>
        ${t.due ? `<span class="label" style="color:var(--down)">${esc(t.due)}</span>` : ""}
      </div>`).join("");
  }
  const n = cal ? cal.events.length : 0, m = tasks ? tasks.items.length : 0;
  $("#day-meta").textContent = `${n} event${n === 1 ? "" : "s"} · ${m} task${m === 1 ? "" : "s"}`;
}

/* ---------- health & habits ---------- */
function renderHealth(h, habits) {
  if (h) {
    $("#health-meta").innerHTML = h.sample
      ? `Awaiting Apple Health bridge<span class="sampletag">sample</span>`
      : `Synced from Apple Health · ${esc(h.synced)}`;
    $("#health-stats").innerHTML = h.stats.map((s) => `
      <div class="stat">
        <div class="v">${s.v}</div>
        <div class="k">${esc(s.k)}</div>
        <div class="trend ${s.dir === "up" ? "delta up" : s.dir === "down" ? "delta down" : ""}"
             ${!s.dir ? 'style="color:var(--faint)"' : ""}>${esc(s.trend)}</div>
      </div>`).join("");
  }
  if (habits) {
    $("#habits-list").innerHTML = habits.items.map((x) => `
      <div class="habit${x.done ? " done" : ""}">
        <div class="left"><span class="mark">${x.done ? "✓" : ""}</span>${esc(x.text)}</div>
        <span class="streak">${x.streak} days</span>
      </div>`).join("");
  }
}

/* ---------- briefing ---------- */
function renderBrief(b) {
  if (!b) return;
  $("#brief").innerHTML = `
    <div class="label label--gold">The Morning Brief${b.sample ? '<span class="sampletag">preview</span>' : ""}</div>
    <h1>${esc(b.headline)}</h1>
    ${b.paras.map((p) => `<p>${esc(p)}</p>`).join("")}
    <div class="signoff">${esc(b.signoff)}</div>`;
}

/* ---------- markets ---------- */
function fmtPrice(p) {
  if (p == null) return "—";
  const digits = p >= 1000 ? 2 : p >= 100 ? 2 : 3;
  return p.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: digits });
}
function renderMarkets(mk) {
  if (!mk) { $("#markets-grid").innerHTML = `<div class="col-12 empty">Markets unavailable — run scripts/pull.py</div>`; return; }
  $("#markets-meta").textContent = mk.meta ?? "";
  $("#markets-grid").innerHTML = mk.groups.map((g) => `
    <div class="col-4">
      <div class="label" style="margin-bottom:6px;color:${g.color}">${esc(g.label)}</div>
      ${g.rows.map((r) => {
        const pct = r.changePct;
        const cls = pct == null ? "flat" : pct >= 0.005 ? "up" : pct <= -0.005 ? "down" : "flat";
        const arrow = cls === "up" ? "▲" : cls === "down" ? "▼" : "–";
        const pctTxt = pct == null ? "" : `${arrow} ${Math.abs(pct).toFixed(2)}%`;
        return `
          <div class="row">
            <div><div class="name">${esc(r.name)}</div><div class="sub">${esc(r.sub)}</div></div>
            <div class="right"><span class="num">${fmtPrice(r.price)}</span><span class="delta ${cls}">${pctTxt}</span></div>
          </div>`;
      }).join("")}
    </div>`).join("");
}

/* ---------- news ---------- */
function renderNews(nw) {
  if (!nw) { $("#news-grid").innerHTML = `<div class="col-12 empty">News unavailable — run scripts/pull.py</div>`; return; }
  $("#news-meta").textContent = nw.meta ?? "";
  $("#news-grid").innerHTML = nw.columns.map((c) => `
    <div class="col-6">
      <div class="label" style="margin-bottom:4px;color:${c.color}">${esc(c.label)}</div>
      ${c.stories.map((s) => `
        <a class="story" href="${esc(s.link)}" target="_blank" rel="noopener">
          <div class="kicker" style="color:${c.color}">${esc(s.kicker)}</div>
          <h3>${esc(s.title)}</h3>
          <div class="src">${esc(s.source)}${s.time ? ` · ${esc(s.time)}` : ""}</div>
        </a>`).join("")}
    </div>`).join("");
}

/* ---------- events ---------- */
function renderEvents(ev) {
  if (!ev) return;
  $("#events-tag").hidden = !ev.sample;
  $("#events-list").innerHTML = ev.items.length
    ? ev.items.map((e) => `
        <div class="outing">
          <span class="badge">New</span>
          <div>
            <h4>${esc(e.title)}</h4>
            <div class="where">${esc(e.where)}</div>
            <div class="sale">${esc(e.line)}</div>
          </div>
        </div>`).join("")
    : `<div class="empty">Nothing newly announced — the agent checks daily.</div>`;
}

/* ---------- boot ---------- */
(async function main() {
  tick();
  const [meta, weather, cal, tasks, health, habits, brief, markets, news, events] =
    await Promise.all([
      load("meta"), load("weather"), load("calendar"), load("tasks"), load("health"),
      load("habits"), load("brief"), load("markets"), load("news"), load("events"),
    ]);
  dateline(meta?.generated);
  renderWeather(weather);
  renderDay(cal, tasks);
  renderHealth(health, habits);
  renderBrief(brief);
  renderMarkets(markets);
  renderNews(news);
  renderEvents(events);
})();
