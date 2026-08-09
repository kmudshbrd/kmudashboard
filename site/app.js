/* Meridian — front-end renderer.
   Reads static JSON from ./data (written by scripts/pull.py, committed by the
   scheduled GitHub workflow). */

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
  if (!w) { $("#weather-panel").innerHTML = `<div class="empty">Weather unavailable</div>`; return; }
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

/* ---------- markets ---------- */
function fmtPrice(p) {
  if (p == null) return "—";
  const digits = p >= 100 ? 2 : 3;
  return p.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: digits });
}

function sparkline(series, pct) {
  if (!Array.isArray(series) || series.length < 3) return "";
  const w = 64, h = 20, pad = 2;
  const min = Math.min(...series), max = Math.max(...series);
  const span = max - min || 1;
  const pts = series.map((v, i) => {
    const x = pad + (i * (w - 2 * pad)) / (series.length - 1);
    const y = h - pad - ((v - min) * (h - 2 * pad)) / span;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const color = pct == null || Math.abs(pct) < 0.005 ? "var(--faint)" : pct > 0 ? "var(--up)" : "var(--down)";
  const [lastX, lastY] = pts.split(" ").at(-1).split(",");
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">
    <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.2" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${lastX}" cy="${lastY}" r="1.8" fill="${color}"/>
  </svg>`;
}

function renderMarkets(mk) {
  if (!mk) { $("#markets-grid").innerHTML = `<div class="col-12 empty">Markets unavailable</div>`; return; }
  $("#markets-meta").textContent = mk.meta ?? "";
  $("#markets-grid").innerHTML = mk.groups.map((g) => `
    <div class="col-4">
      <div class="mgroup" style="--gcolor:${g.color}">
        <div class="label">${esc(g.label)}</div>
        ${g.rows.map((r) => {
          const pct = r.changePct;
          const cls = pct == null ? "flat" : pct >= 0.005 ? "up" : pct <= -0.005 ? "down" : "flat";
          const arrow = cls === "up" ? "▲" : cls === "down" ? "▼" : "–";
          const pctTxt = pct == null ? "" : `${arrow} ${Math.abs(pct).toFixed(2)}%`;
          return `
            <div class="row">
              <div><div class="name">${esc(r.name)}</div><div class="sub">${esc(r.sub)}</div></div>
              <div class="spark">${sparkline(r.series, pct)}</div>
              <div class="right"><span class="num">${fmtPrice(r.price)}</span><span class="delta ${cls}">${pctTxt}</span></div>
            </div>`;
        }).join("")}
      </div>
    </div>`).join("");
}

/* ---------- news ---------- */
function renderNews(nw) {
  if (!nw) { $("#news-grid").innerHTML = `<div class="col-12 empty">News unavailable</div>`; return; }
  $("#news-meta").textContent = nw.meta ?? "";
  $("#news-grid").innerHTML = nw.columns.map((c) => `
    <div class="col-3 newscol">
      <div class="label" style="color:${c.color}">${esc(c.label)}</div>
      ${c.stories.map((s, i) => `
        <a class="story${i === 0 ? " featured" : ""}" href="${esc(s.link)}" target="_blank" rel="noopener">
          <h3>${esc(s.title)}</h3>
          <div class="src">${esc(s.source)}${s.time ? ` · ${esc(s.time)}` : ""}</div>
        </a>`).join("")}
    </div>`).join("");
}

/* ---------- events ---------- */
function renderEvents(ev) {
  if (!ev || !ev.groups) { $("#events-grid").innerHTML = `<div class="col-12 empty">Events unavailable</div>`; return; }
  $("#events-tag").hidden = !ev.sample;
  $("#events-grid").innerHTML = ev.groups.map((g) => `
    <div class="col-6">
      <div class="panel panel--events" style="--wash:var(--wash-blush);--dial:var(--dial-blush)">
        <div class="label">${esc(g.label)}</div>
        ${g.items.length ? g.items.map((e) => `
          <div class="ev-item">
            <div>
              <div class="ev-title">${esc(e.title)}</div>
              <div class="ev-where">${esc(e.where)}</div>
            </div>
            <div class="ev-when">${esc(e.line)}</div>
          </div>`).join("") : `<div class="empty">Nothing on the calendar yet.</div>`}
      </div>
    </div>`).join("");
}

/* ---------- boot ---------- */
(async function main() {
  tick();
  const [meta, weather, markets, news, events] = await Promise.all([
    load("meta"), load("weather"), load("markets"), load("news"), load("events"),
  ]);
  dateline(meta?.generated);
  renderWeather(weather);
  renderNews(news);
  renderEvents(events);
  renderMarkets(markets);
})();
