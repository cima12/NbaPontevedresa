/* historia.js · NbaPontevedresa · Pestaña "Historia" de la liga.
 *
 * Lee data/historico/partidos.json (lo genera scripts/historico.py con todos los
 * enfrentamientos de todas las temporadas). Con ?prueba usa data/historico_prueba/.
 * Si no existe, la pestaña no aparece.
 *
 * Usa de index.html / liga.js: $, esc, color, cargar, leerLS, guardarLS, LIGA, etqTemporada.
 */
"use strict";

const HIST = {
  base: new URLSearchParams(location.search).has("prueba") ? "data/historico_prueba/" : "data/historico/",
  d: null, vista: "palmares", yo: null, rival: null,
};
const VISTAS = [["palmares", "Palmarés"], ["managers", "Mánagers"], ["h2h", "Cara a cara"],
                ["rachas", "Rachas"], ["records", "Récords"], ["suerte", "Suerte"]];

/* ---------- preparación ---------- */
function prepararHistoria(d) {
  const T = d.temporadas;
  const man = (t, k) => T[t]?.equipos[k]?.manager || T[t]?.equipos[k]?.nombre || k;
  const eqN = (t, k) => T[t]?.equipos[k]?.nombre || k;
  const partidos = d.partidos.filter(p => !p.con).map(p => ({
    ...p, ma: man(p.t, p.a), mb: man(p.t, p.b),
    ra: p.ga > p.gb ? "G" : p.ga < p.gb ? "P" : "E",
  })).sort((x, y) => x.t.localeCompare(y.t) || x.s - y.s);
  const managers = [...new Set(Object.values(T).flatMap(t => Object.values(t.equipos).map(e => e.manager || e.nombre)))].sort((a, b) => a.localeCompare(b, "es", { numeric: true }));
  // Resultado desde el punto de vista de cada mánager, en orden cronológico
  const porManager = new Map(managers.map(m => [m, []]));
  for (const p of partidos) {
    porManager.get(p.ma)?.push({ p, yo: p.a, el: p.b, rival: p.mb, r: p.ra, g: p.ga, pe: p.gb, s: p.sa, so: p.sb });
    porManager.get(p.mb)?.push({ p, yo: p.b, el: p.a, rival: p.ma, r: p.ra === "G" ? "P" : p.ra === "P" ? "G" : "E", g: p.gb, pe: p.ga, s: p.sb, so: p.sa });
  }
  return { ...d, T, man, eqN, partidos, managers, porManager };
}

const pct = (g, p, e) => (g + p + e) ? ((g + e / 2) / (g + p + e)) : 0;
const fmtPct = x => (x * 100).toFixed(1);
const rec = (g, p, e) => `${g}-${p}${e ? "-" + e : ""}`;
const cuando = p => `${etqTemporada(p.t)} · sem. ${p.s}${p.po ? " · playoffs" : ""}`;

/* ---------- cálculos ---------- */
function calcManagers(H) {
  return H.managers.map(m => {
    const L = H.porManager.get(m) || [];
    const reg = L.filter(x => !x.p.po), po = L.filter(x => x.p.po);
    const cnt = (lista, r) => lista.filter(x => x.r === r).length;
    const temps = new Set(L.map(x => x.p.t));
    let titulos = 0, finales = 0, mejor = 99;
    const puestos = [];
    for (const [t, info] of Object.entries(H.T)) {
      for (const [k, e] of Object.entries(info.equipos)) {
        if ((e.manager || e.nombre) !== m) continue;
        temps.add(t);
        if (info.campeon) {           // temporada terminada
          if (info.campeon === k) titulos++;
          if (e.puesto && e.puesto <= 2) finales++;
          if (e.puesto) { mejor = Math.min(mejor, e.puesto); puestos.push(e.puesto); }
        }
      }
    }
    const cg = L.reduce((s, x) => s + x.g, 0), cp = L.reduce((s, x) => s + x.pe, 0), ce = L.reduce((s, x) => s + (x.p.e || 0), 0);
    return { m, temps: temps.size, g: cnt(reg, "G"), p: cnt(reg, "P"), e: cnt(reg, "E"),
             pg: cnt(po, "G"), pp: cnt(po, "P"), cg, cp, ce, titulos, finales,
             mejor: mejor < 99 ? mejor : null, media: puestos.length ? puestos.reduce((a, b) => a + b, 0) / puestos.length : null };
  }).sort((a, b) => b.titulos - a.titulos || pct(b.g, b.p, b.e) - pct(a.g, a.p, a.e));
}

function rachas(L) {
  let act = { r: null, n: 0 }, mejorG = { n: 0 }, peorP = { n: 0 }, cur = { r: null, n: 0, desde: null };
  for (const x of L) {
    if (x.r === cur.r && x.r !== "E") cur.n++;
    else cur = { r: x.r, n: x.r === "E" ? 0 : 1, desde: x.p };
    cur.hasta = x.p;
    if (cur.r === "G" && cur.n > mejorG.n) mejorG = { ...cur };
    if (cur.r === "P" && cur.n > peorP.n) peorP = { ...cur };
  }
  act = cur;
  return { act, mejorG, peorP };
}

function calcRecords(H) {
  const cats = [];
  const vistos = new Map();
  for (const info of Object.values(H.T)) for (const c of info.categorias || []) if (!vistos.has(c.clave)) vistos.set(c.clave, c);
  const filas = H.partidos.flatMap(p => [{ p, k: p.a, s: p.sa }, { p, k: p.b, s: p.sb }]);
  for (const c of vistos.values()) {
    const con = filas.filter(f => f.s[c.clave] != null && (c.clave !== "fg_pct" || (f.s.fga || 0) > 50) && (c.clave !== "ft_pct" || (f.s.fta || 0) > 20));
    con.sort((a, b) => c.menos ? a.s[c.clave] - b.s[c.clave] : b.s[c.clave] - a.s[c.clave]);
    cats.push({ c, top: con.slice(0, 3) });
  }
  const palizas = [...H.partidos].sort((a, b) => Math.abs(b.ga - b.gb) - Math.abs(a.ga - a.gb)).slice(0, 5);
  const nueveCero = H.partidos.filter(p => (p.ga === 9 && p.gb === 0) || (p.gb === 9 && p.ga === 0)).length;
  return { cats, palizas, nueveCero };
}

// Récord "contra todos": cada semana, tu equipo contra los otros 11
function calcSuerte(H) {
  const res = [];
  const porSemana = new Map();
  for (const p of H.partidos) {
    if (p.po) continue;
    const k = p.t + "|" + p.s;
    if (!porSemana.has(k)) porSemana.set(k, []);
    porSemana.get(k).push({ key: p.a, s: p.sa, r: p.ra }, { key: p.b, s: p.sb, r: p.ra === "G" ? "P" : p.ra === "P" ? "G" : "E" });
  }
  const acc = new Map();
  for (const [k, lista] of porSemana) {
    const t = k.split("|")[0];
    const cats = H.T[t].categorias || [];
    for (const yo of lista) {
      const id = t + "|" + yo.key;
      const a = acc.get(id) || { t, key: yo.key, g: 0, p: 0, e: 0, ag: 0, ap: 0, ae: 0 };
      a[yo.r === "G" ? "g" : yo.r === "P" ? "p" : "e"]++;
      for (const otro of lista) {
        if (otro === yo) continue;
        let w = 0, l = 0;
        for (const c of cats) {
          const x = yo.s[c.clave], y = otro.s[c.clave];
          if (x == null || y == null || x === y) continue;
          if ((x < y) === !!c.menos) w++; else l++;
        }
        a[w > l ? "ag" : w < l ? "ap" : "ae"]++;
      }
      acc.set(id, a);
    }
  }
  for (const a of acc.values()) {
    const real = pct(a.g, a.p, a.e), todos = pct(a.ag, a.ap, a.ae);
    res.push({ ...a, real, todos, suerte: real - todos, m: H.man(a.t, a.key), eq: H.eqN(a.t, a.key) });
  }
  return res;
}

/* ---------- pintar ---------- */
function pintarHistoria() {
  const H = HIST.d; if (!H) return;
  $("hist-vistas").innerHTML = VISTAS.map(([k, n]) => `<button class="chip${HIST.vista === k ? " on" : ""}" data-v="${k}">${n}</button>`).join("");
  const c = $("hist-contenido");
  const temps = Object.keys(H.T).sort();
  const sub = `<p class="ayuda">${temps.length} temporadas (${etqTemporada(temps[0])} a ${etqTemporada(temps.at(-1))}) · ${H.partidos.length} enfrentamientos.
    Los partidos de consolación no cuentan.</p>`;

  if (HIST.vista === "palmares") {
    const tabla = calcManagers(H).filter(x => x.titulos || x.finales);
    c.innerHTML = `<div class="tarjeta"><div class="nom">🏆 Campeones</div><table class="liga"><tbody>` +
      temps.slice().reverse().map(t => {
        const info = H.T[t];
        if (!info.campeon) return `<tr><td class="peq">${etqTemporada(t)}</td><td style="text-align:left" class="peq">En juego</td></tr>`;
        const sub = Object.entries(info.equipos).find(([, e]) => e.puesto === 2);
        return `<tr><td class="peq">${etqTemporada(t)}</td><td style="text-align:left"><span class="nom">${esc(info.equipos[info.campeon].nombre)}</span>
          <span class="peq" style="display:block">${esc(H.man(t, info.campeon))}${sub ? ` · finalista: ${esc(sub[1].nombre)}` : ""}</span></td></tr>`;
      }).join("") + `</tbody></table></div>
      <div class="tarjeta"><div class="nom">Títulos por mánager</div><div class="barras">` +
      tabla.map(x => `<div class="barra"><span>${esc(x.m)}</span><b>${"🏆".repeat(x.titulos) || "–"}</b><span class="peq">${x.finales} final${x.finales === 1 ? "" : "es"}</span></div>`).join("") +
      `</div></div>` + sub;
  }

  if (HIST.vista === "managers") {
    const tabla = calcManagers(H).sort((a, b) => pct(b.g, b.p, b.e) - pct(a.g, a.p, a.e));
    c.innerHTML = `<div class="tarjeta"><div class="nom">Clasificación histórica</div>
      <div class="tabla-wrap" style="background:var(--card2);margin-top:8px"><table class="liga"><thead><tr><th class="fijo">Mánager</th><th>Temp.</th>
      <th>Liga regular</th><th>%</th><th>Playoffs</th><th>Categorías</th><th>🏆</th><th>Finales</th><th>Mejor</th><th>Media</th></tr></thead><tbody>` +
      tabla.map(x => `<tr><td class="fijo nom">${esc(x.m)}</td><td>${x.temps}</td><td>${rec(x.g, x.p, x.e)}</td>
        <td style="${color((pct(x.g, x.p, x.e) - .5) * 8)}"><b>${fmtPct(pct(x.g, x.p, x.e))}</b></td><td>${x.pg}-${x.pp}</td>
        <td>${fmtPct(pct(x.cg, x.cp, x.ce))}%</td><td>${x.titulos || ""}</td><td>${x.finales || ""}</td>
        <td>${x.mejor ? x.mejor + "º" : "–"}</td><td>${x.media ? x.media.toFixed(1) : "–"}</td></tr>`).join("") +
      `</tbody></table></div><p class="ayuda">Liga regular: enfrentamientos semanales ganados-perdidos-empatados. Categorías: % de categorías ganadas en todos los enfrentamientos.
      Puestos solo de temporadas terminadas.</p></div>` + sub;
  }

  if (HIST.vista === "h2h") {
    const yo = HIST.yo && H.porManager.has(HIST.yo) ? HIST.yo : H.managers[0];
    const L = H.porManager.get(yo) || [];
    const rivales = [...new Set(L.map(x => x.rival))].map(r => {
      const g = L.filter(x => x.rival === r);
      const n = k => g.filter(x => x.r === k).length;
      return { r, g: n("G"), p: n("P"), e: n("E"), cg: g.reduce((s, x) => s + x.g, 0), cp: g.reduce((s, x) => s + x.pe, 0), lista: g };
    }).sort((a, b) => pct(b.g, b.p, b.e) - pct(a.g, a.p, a.e));
    const nem = rivales.at(-1), vic = rivales[0];
    const det = rivales.find(x => x.r === HIST.rival);
    c.innerHTML = `<div class="tarjeta"><div class="controles"><span class="peq">Mánager:</span><select id="h2h-yo" style="flex:1">` +
      H.managers.map(m => `<option${m === yo ? " selected" : ""}>${esc(m)}</option>`).join("") + `</select></div>
      ${rivales.length ? `<p class="ayuda">😈 Némesis: <b style="color:var(--rojo)">${esc(nem.r)}</b> (${rec(nem.g, nem.p, nem.e)}) · 🍖 Víctima favorita: <b style="color:var(--verde)">${esc(vic.r)}</b> (${rec(vic.g, vic.p, vic.e)})</p>` : ""}
      <table class="liga" id="h2h-tabla" style="margin-top:6px"><thead><tr><th style="text-align:left">Contra</th><th>G-P-E</th><th>%</th><th>Cat.</th><th>Último</th></tr></thead><tbody>` +
      rivales.map(x => {
        const u = x.lista.at(-1);
        return `<tr class="clic${x.r === HIST.rival ? " yo" : ""}" data-r="${esc(x.r)}"><td style="text-align:left">${esc(x.r)}</td><td>${rec(x.g, x.p, x.e)}</td>
          <td style="${color((pct(x.g, x.p, x.e) - .5) * 6)}">${fmtPct(pct(x.g, x.p, x.e))}</td><td>${x.cg}-${x.cp}</td>
          <td><span class="res ${u.r}">${u.r}</span> ${u.g}-${u.pe}</td></tr>`;
      }).join("") + `</tbody></table><p class="ayuda">Toca un rival para ver todos vuestros enfrentamientos.</p></div>` +
      (det ? `<div class="tarjeta"><div class="nom">${esc(yo)} contra ${esc(det.r)}</div><ul class="avisos">` +
        det.lista.slice().reverse().map(x => `<li><span class="res ${x.r}">${x.r}</span> <b>${x.g}-${x.pe}</b>
          <span class="peq">${cuando(x.p)} · ${esc(H.eqN(x.p.t, x.yo))} vs ${esc(H.eqN(x.p.t, x.el))}</span></li>`).join("") + `</ul></div>` : "");
    $("h2h-yo").onchange = e => { HIST.yo = e.target.value; HIST.rival = null; guardarLS("hist-yo", HIST.yo); pintarHistoria(); };
    $("h2h-tabla").onclick = e => { const tr = e.target.closest("tr.clic"); if (!tr) return; HIST.rival = HIST.rival === tr.dataset.r ? null : tr.dataset.r; pintarHistoria(); };
  }

  if (HIST.vista === "rachas") {
    const R = H.managers.map(m => ({ m, ...rachas(H.porManager.get(m) || []) }));
    const act = [...R].filter(x => x.act.n).sort((a, b) => (b.act.r === "G" ? b.act.n : -b.act.n) - (a.act.r === "G" ? a.act.n : -a.act.n));
    const mejores = [...R].sort((a, b) => b.mejorG.n - a.mejorG.n).slice(0, 5);
    const peores = [...R].sort((a, b) => b.peorP.n - a.peorP.n).slice(0, 5);
    const desdeHasta = x => x.desde ? `${cuando(x.desde)} → ${cuando(x.hasta)}` : "";
    c.innerHTML = `<div class="tarjeta"><div class="nom">🔥 Rachas actuales</div><table class="liga"><tbody>` +
      act.map(x => `<tr><td style="text-align:left">${esc(x.m)}</td><td><span class="res ${x.act.r}">${x.act.r}${x.act.n}</span></td>
        <td class="peq">desde ${cuando(x.act.desde)}</td></tr>`).join("") + `</tbody></table></div>
      <div class="tarjeta"><div class="nom">Mejores rachas de victorias de la historia</div><ul class="avisos">` +
      mejores.map(x => `<li><b style="color:var(--verde)">${x.mejorG.n} seguidas</b> · ${esc(x.m)} <span class="peq" style="display:block">${desdeHasta(x.mejorG)}</span></li>`).join("") + `</ul></div>
      <div class="tarjeta"><div class="nom">Peores rachas de derrotas</div><ul class="avisos">` +
      peores.map(x => `<li><b style="color:var(--rojo)">${x.peorP.n} seguidas</b> · ${esc(x.m)} <span class="peq" style="display:block">${desdeHasta(x.peorP)}</span></li>`).join("") +
      `</ul></div><p class="ayuda">Rachas de enfrentamientos semanales (liga regular y playoffs, seguidas entre temporadas). Un empate corta la racha.</p>`;
  }

  if (HIST.vista === "records") {
    const R = calcRecords(H);
    const val = (c, x) => c.clave.endsWith("pct") ? (x * 100).toFixed(1) + "%" : x;
    c.innerHTML = `<div class="tarjeta"><div class="nom">Récords de una semana</div>` +
      R.cats.map(({ c: cat, top }) => `<div class="record"><div class="peq">${esc(cat.nombre)}${cat.menos ? " (menos)" : ""}</div>` +
        top.map((f, i) => `<div class="fila-rec"><span class="medalla">${["🥇", "🥈", "🥉"][i]}</span><b>${val(cat, f.s[cat.clave])}</b>
          <span>${esc(H.eqN(f.p.t, f.k))} <span class="peq">· ${esc(H.man(f.p.t, f.k))} · ${cuando(f.p)}</span></span></div>`).join("") + `</div>`).join("") +
      `</div><div class="tarjeta"><div class="nom">Mayores palizas</div><p class="ayuda" style="margin-top:2px">${R.nueveCero} victorias por 9-0 en la historia.</p><ul class="avisos">` +
      R.palizas.map(p => { const ganaA = p.ga > p.gb;
        return `<li><b>${Math.max(p.ga, p.gb)}-${Math.min(p.ga, p.gb)}</b> · ${esc(H.eqN(p.t, ganaA ? p.a : p.b))} a ${esc(H.eqN(p.t, ganaA ? p.b : p.a))}
          <span class="peq" style="display:block">${esc(ganaA ? p.ma : p.mb)} sobre ${esc(ganaA ? p.mb : p.ma)} · ${cuando(p)}</span></li>`; }).join("") + `</ul></div>`;
  }

  if (HIST.vista === "suerte") {
    const S = calcSuerte(H);
    const ult = temps.at(-1);
    const actual = S.filter(x => x.t === ult).sort((a, b) => b.suerte - a.suerte);
    const top = (lista) => lista.map(x => `<li><b style="color:${x.suerte >= 0 ? "var(--verde)" : "var(--rojo)"}">${x.suerte >= 0 ? "+" : ""}${fmtPct(x.suerte)}</b> · ${esc(x.eq)}
      <span class="peq" style="display:block">${esc(x.m)} · ${etqTemporada(x.t)} · real ${rec(x.g, x.p, x.e)} (${fmtPct(x.real)}%) · contra todos ${fmtPct(x.todos)}%</span></li>`).join("");
    const orden = [...S].sort((a, b) => b.suerte - a.suerte);
    c.innerHTML = `<div class="tarjeta"><div class="nom">🍀 Suerte esta temporada (${etqTemporada(ult)})</div><table class="liga"><thead><tr><th style="text-align:left">Equipo</th><th>Real</th><th>Contra todos</th><th>Suerte</th></tr></thead><tbody>` +
      actual.map(x => `<tr${LIGA.soy && x.key === LIGA.soy ? ' class="yo"' : ""}><td style="text-align:left">${esc(x.eq)}</td><td>${rec(x.g, x.p, x.e)}</td><td>${fmtPct(x.todos)}%</td>
        <td style="color:${x.suerte >= 0 ? "var(--verde)" : "var(--rojo)"};font-weight:700">${x.suerte >= 0 ? "+" : ""}${fmtPct(x.suerte)}</td></tr>`).join("") +
      `</tbody></table><p class="ayuda">"Contra todos": el % que tendrías si cada semana jugaras contra los 11 rivales a la vez. Si tu % real es mayor, has tenido suerte con los cruces.</p></div>
      <div class="tarjeta"><div class="nom">Temporadas con más suerte</div><ul class="avisos">${top(orden.slice(0, 5))}</ul></div>
      <div class="tarjeta"><div class="nom">Temporadas más gafadas</div><ul class="avisos">${top(orden.slice(-5).reverse())}</ul></div>`;
  }
}

async function iniciarHistoria() {
  try { HIST.d = prepararHistoria(await cargar(HIST.base + "partidos.json")); } catch (e) { return; }
  if (!HIST.d.partidos.length) return;
  // Mánager por defecto: el del equipo elegido en "Soy", si lo hay
  const soyMan = LIGA.soy && LIGA.liga ? LIGA.liga.equipos.find(e => e.key === LIGA.soy)?.manager : null;
  HIST.yo = leerLS("hist-yo", null) || soyMan || null;
  document.querySelector('nav button[data-sec="historia"]').hidden = false;
  $("hist-vistas").onclick = e => { const b = e.target.closest("button[data-v]"); if (!b) return; HIST.vista = b.dataset.v; pintarHistoria(); };
  pintarHistoria();
  if (leerLS("seccion", "") === "historia") document.querySelector('nav button[data-sec="historia"]').click();
}
