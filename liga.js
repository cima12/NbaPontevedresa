/* liga.js · NbaPontevedresa · Todo lo que usa datos de la liga de Yahoo.
 *
 * Lee data/liga/*.json (los guarda el Action "Actualizar liga"). Si no existen
 * (Yahoo aún no ha aprobado la app), no enseña nada y la web sigue como siempre.
 * Con ?prueba al final de la dirección usa data/liga_prueba/ (datos inventados).
 *
 * Usa de index.html: est, CATS, $, esc, color, cargar, hoyEEUU, leerLS, guardarLS.
 */
"use strict";

const LIGA = {
  base: new URLSearchParams(location.search).has("prueba") ? "data/liga_prueba/" : "data/liga/",
  liga: null, plantillas: null, enfr: null, clasif: null, cal: null,
  soy: null, nombre: {}, corto: {}, dueno: new Map(), jug: new Map(),
};
const FUERA = new Set(["O", "INJ", "NA", "SUSP", "IL", "IL+"]);     // estados que no juegan
const HUECOS_POS = ["PG", "SG", "SF", "PF", "C"];
const CAT_LIGA = [   // clave en Yahoo -> cómo se muestra y si es porcentaje
  { k: "fg_pct", n: "FG%", pct: true, m: "fgm", a: "fga" },
  { k: "ft_pct", n: "FT%", pct: true, m: "ftm", a: "fta" },
  { k: "tpm", n: "3PM", varf: 1.3 }, { k: "pts", n: "PTS", varf: 6 }, { k: "reb", n: "REB", varf: 2 },
  { k: "ast", n: "AST", varf: 2 }, { k: "stl", n: "STL", varf: 1.1 }, { k: "blk", n: "BLK", varf: 1.4 },
  { k: "to", n: "TO", varf: 1.3, menos: true },
];

/* ---------- utilidades ---------- */
const sumarDias = (iso, n) => { const f = new Date(iso + "T12:00:00Z"); f.setUTCDate(f.getUTCDate() + n); return f.toISOString().slice(0, 10); };
const diaCorto = iso => { const f = new Date(iso + "T12:00:00Z"); return ["D", "L", "M", "X", "J", "V", "S"][f.getUTCDay()] + " " + (+iso.slice(8)); };
function phi(x) {   // distribución normal acumulada
  const t = 1 / (1 + 0.2316419 * Math.abs(x));
  const d = 0.3989423 * Math.exp(-x * x / 2);
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
  return x > 0 ? 1 - p : p;
}

// Promedios por partido de un jugador NBA: últimos 30 días si hay muestra, si no la temporada
function promedios(nbaId) {
  const j = LIGA.jug.get(nbaId);
  if (!j) return null;
  const s = j.ult30 && j.ult30.pj >= 5 ? j.ult30 : j.temporada;
  if (!s || !s.pj) return null;
  return { ...s, fgm: s.fga * (s.fg_pct || 0), ftm: s.fta * (s.ft_pct || 0), valor: s.valor ?? 0 };
}

// Partidos que le quedan a un equipo NBA entre dos fechas (sin empezar)
function partidosPendientes(equipo, desde, hasta) {
  return LIGA.cal.filter(g => g.fecha >= desde && g.fecha <= hasta && g.estado === 1 &&
                              (g.local === equipo || g.visitante === equipo)).map(g => g.fecha);
}

// ¿Puede este grupo de jugadores ocupar los huecos? (emparejamiento con caminos de aumento)
function cabe(grupo, huecos) {
  const asig = new Array(huecos.length).fill(-1);
  const vale = (j, h) => h === "Util" || (j.pos || []).includes(h) ||
    (h === "G" && (j.pos || []).some(p => p === "PG" || p === "SG")) ||
    (h === "F" && (j.pos || []).some(p => p === "SF" || p === "PF"));
  function aumentar(i, vistos) {
    for (let h = 0; h < huecos.length; h++) {
      if (vistos[h] || !vale(grupo[i], huecos[h])) continue;
      vistos[h] = true;
      if (asig[h] < 0 || aumentar(asig[h], vistos)) { asig[h] = i; return true; }
    }
    return false;
  }
  for (let i = 0; i < grupo.length; i++) if (!aumentar(i, [])) return null;
  return asig;   // asig[hueco] = índice en grupo
}

// Mejor alineación: voraz por valor (óptimo para este tipo de problema) respetando posiciones
function mejorAlineacion(candidatos, huecos) {
  const elegidos = [];
  for (const j of [...candidatos].sort((a, b) => b._v - a._v)) {
    if (elegidos.length >= huecos.length) break;
    if (cabe([...elegidos, j], huecos)) elegidos.push(j);
  }
  const asig = cabe(elegidos, huecos) || [];
  return { elegidos, porHueco: huecos.map((h, i) => ({ hueco: h, j: asig[i] >= 0 ? elegidos[asig[i]] : null })) };
}

function huecosTitulares() {
  const out = [];
  for (const p of LIGA.liga.posiciones || []) {
    if (["BN", "IL", "IL+", "NA"].includes(p.posicion)) continue;
    for (let i = 0; i < p.huecos; i++) out.push(p.posicion);
  }
  return out.length ? out : ["PG", "SG", "SF", "PF", "C", "Util", "Util", "Util"];
}

function plantilla(key) {
  return (LIGA.plantillas.equipos[key] || []).map(y => ({ ...y, _p: promedios(y.nba_id), _v: promedios(y.nba_id)?.valor ?? -9 }));
}

/* ---------- previsión del enfrentamiento ---------- */
// Suma de lo que harán los jugadores en los partidos que quedan, con 8 huecos por día como máximo
function prevision(key, desde, hasta) {
  const plant = plantilla(key).filter(j => j.hueco !== "IL" && j.hueco !== "IL+" && !FUERA.has(j.estado) && j._p);
  const huecos = huecosTitulares();
  const tot = { fgm: 0, fga: 0, ftm: 0, fta: 0, tpm: 0, pts: 0, reb: 0, ast: 0, stl: 0, blk: 0, to: 0 };
  const dias = {};
  let partidos = 0, perdidos = 0;
  for (let d = desde; d <= hasta; d = sumarDias(d, 1)) {
    const juegan = plant.filter(j => partidosPendientes(j.equipo_nba, d, d).length);
    const { elegidos } = mejorAlineacion(juegan, huecos);
    dias[d] = { juegan: juegan.length, titulares: elegidos.length, sinHueco: juegan.length - elegidos.length };
    perdidos += juegan.length - elegidos.length;
    for (const j of elegidos) {
      const w = j.estado === "GTD" || j.estado === "DTD" ? 0.75 : 1;
      partidos += w;
      for (const k in tot) tot[k] += w * (j._p[k] || 0);
    }
  }
  return { tot, dias, partidos, perdidos };
}

function analizarEnfrentamiento() {
  const E = LIGA.enfr, soy = LIGA.soy;
  const m = E && E.partidos.find(p => p.equipos.some(e => e.key === soy));
  if (!m) return null;
  const yo = m.equipos.find(e => e.key === soy), el = m.equipos.find(e => e.key !== soy);
  const hoy = hoyEEUU();
  const desde = hoy > E.inicio ? hoy : E.inicio;
  const pYo = prevision(yo.key, desde, E.fin), pEl = prevision(el.key, desde, E.fin);
  const filas = CAT_LIGA.map(c => {
    const act = e => c.pct ? { m: e.stats[c.m] || 0, a: e.stats[c.a] || 0 } : (e.stats[c.k] || 0);
    const aYo = act(yo), aEl = act(el);
    let vYo, vEl, actYo, actEl, sd;
    if (c.pct) {
      const fin = (a, p) => ({ m: a.m + p.tot[c.m], a: a.a + p.tot[c.a] });
      const fYo = fin(aYo, pYo), fEl = fin(aEl, pEl);
      vYo = fYo.a ? fYo.m / fYo.a : 0; vEl = fEl.a ? fEl.m / fEl.a : 0;
      actYo = aYo.a ? aYo.m / aYo.a : null; actEl = aEl.a ? aEl.m / aEl.a : null;
      // incertidumbre solo por los tiros que faltan por lanzar
      const varP = (f, p, v) => f.a ? (v * (1 - v) * p.tot[c.a]) / (f.a * f.a) : 0;
      sd = Math.sqrt(varP(fYo, pYo, vYo) + varP(fEl, pEl, vEl)) + 0.004;
    } else {
      vYo = aYo + pYo.tot[c.k]; vEl = aEl + pEl.tot[c.k];
      actYo = aYo; actEl = aEl;
      sd = Math.sqrt(c.varf * (pYo.tot[c.k] + pEl.tot[c.k])) + 0.5;
    }
    const dif = c.menos ? vEl - vYo : vYo - vEl;
    const prob = phi(dif / sd);
    return { c, actYo, actEl, vYo, vEl, prob, etq: prob >= 0.8 ? "segura" : prob <= 0.2 ? "perdida" : "en el aire" };
  });
  return { yo, el, pYo, pEl, filas, desde };
}

/* ---------- avisos de alineación de hoy ---------- */
function avisosHoy() {
  const hoy = hoyEEUU();
  const plant = plantilla(LIGA.soy);
  const huecos = huecosTitulares();
  const juegaHoy = j => partidosPendientes(j.equipo_nba, hoy, hoy).length > 0;
  const esTitular = j => j.hueco && !["BN", "IL", "IL+", "NA"].includes(j.hueco);
  const disponibles = plant.filter(j => juegaHoy(j) && !FUERA.has(j.estado) && j.hueco !== "IL" && j.hueco !== "IL+");
  const { porHueco, elegidos } = mejorAlineacion(disponibles, huecos);
  const avisos = [];
  const fechaPlant = LIGA.plantillas.fecha;
  if (fechaPlant !== hoy) avisos.push({ t: "info", m: `La alineación leída de Yahoo es del ${diaCorto(fechaPlant)}; puede haber cambios desde entonces.` });

  for (const j of plant.filter(j => esTitular(j) && FUERA.has(j.estado)))
    avisos.push({ t: "mal", m: `<b>${esc(j.nombre)}</b> es titular y está de baja (${esc(j.estado)}).` });
  const banqJuega = plant.filter(j => j.hueco === "BN" && elegidos.includes(j));
  const titNoJuega = plant.filter(j => esTitular(j) && !elegidos.includes(j) && !FUERA.has(j.estado));
  for (const j of banqJuega)
    avisos.push({ t: "mal", m: `<b>${esc(j.nombre)}</b> juega hoy y está en el banquillo.` });
  if (banqJuega.length && titNoJuega.length)
    avisos.push({ t: "info", m: `Titulares que no deberían serlo hoy: ${titNoJuega.map(j => esc(j.nombre) + (juegaHoy(j) ? "" : " (no juega)")).join(", ")}.` });
  const titulares = plant.filter(esTitular).length;
  if (titulares < huecos.length) avisos.push({ t: "mal", m: `Tienes ${huecos.length - titulares} hueco(s) de titular vacío(s).` });
  const sinHueco = disponibles.filter(j => !elegidos.includes(j));
  if (sinHueco.length)
    avisos.push({ t: "aviso", m: `Hoy juegan ${disponibles.length} de los tuyos: ${sinHueco.map(j => esc(j.nombre)).join(", ")} se queda(n) sin hueco.` });
  for (const j of plant.filter(j => (j.hueco === "IL" || j.hueco === "IL+") && !FUERA.has(j.estado) && j.estado !== "GTD" && j.estado !== "DTD"))
    avisos.push({ t: "aviso", m: `<b>${esc(j.nombre)}</b> está en IL pero Yahoo no lo marca lesionado: ¿puede volver?` });
  for (const j of plant.filter(j => j.estado === "GTD" || j.estado === "DTD").filter(juegaHoy))
    avisos.push({ t: "aviso", m: `<b>${esc(j.nombre)}</b> es duda (${esc(j.estado)}) para hoy.` });
  if (!avisos.some(a => a.t !== "info") && disponibles.length) avisos.push({ t: "bien", m: "Alineación de hoy sin problemas." });
  if (!disponibles.length) avisos.push({ t: "info", m: "Hoy no juega ninguno de tus jugadores." });
  return { avisos, porHueco, plant };
}

/* ---------- fuerza de las plantillas (mapa de la liga) ---------- */
function fuerzaEquipos() {
  const res = LIGA.liga.equipos.map(e => {
    const top = plantilla(e.key).filter(j => j._p && j.hueco !== "IL" && j.hueco !== "IL+")
      .sort((a, b) => b._v - a._v).slice(0, 10);
    const t = { fgm: 0, fga: 0, ftm: 0, fta: 0, tpm: 0, pts: 0, reb: 0, ast: 0, stl: 0, blk: 0, to: 0 };
    for (const j of top) for (const k in t) t[k] += j._p[k] || 0;
    const v = {};
    for (const c of CAT_LIGA) v[c.k] = c.pct ? (t[c.a] ? t[c.m] / t[c.a] : 0) : t[c.k];
    return { key: e.key, v };
  });
  for (const c of CAT_LIGA) {
    const orden = [...res].sort((a, b) => c.menos ? a.v[c.k] - b.v[c.k] : b.v[c.k] - a.v[c.k]);
    orden.forEach((r, i) => { (r.puesto = r.puesto || {})[c.k] = i + 1; });
  }
  res.forEach(r => r.media = CAT_LIGA.reduce((s, c) => s + r.puesto[c.k], 0) / CAT_LIGA.length);
  return res.sort((a, b) => a.media - b.media);
}

/* ---------- pintar ---------- */
const fmtCat = (c, x) => x == null ? "–" : c.pct ? (x * 100).toFixed(1) : (Math.round(x * 10) / 10).toString();
const colorProb = p => p >= 0.8 ? "var(--verde)" : p <= 0.2 ? "var(--rojo)" : "var(--ambar)";
const colorPuesto = (p, n) => color((n + 1 - 2 * p) / (n - 1) * 2);   // 1º verde, último rojo

function pintarLiga() {
  const cont = $("liga-contenido");
  if (!LIGA.soy) { cont.innerHTML = `<div class="estado">Elige tu equipo arriba.</div>`; return; }
  let html = "";

  // Enfrentamiento
  const an = analizarEnfrentamiento();
  if (an) {
    const ganadas = an.filas.filter(f => f.prob >= 0.5).length;
    const n = c => an.filas.filter(f => f.etq === c).length;
    html += `<div class="tarjeta"><div class="nom">Semana ${esc(LIGA.enfr.semana)} · contra ${esc(LIGA.nombre[an.el.key] || "?")}</div>
      <p class="ayuda" style="margin-top:2px">Previsión al acabar la semana: <b style="color:var(--txt)">${ganadas}-${CAT_LIGA.length - ganadas}</b>
       · ${n("segura")} seguras · ${n("en el aire")} en el aire · ${n("perdida")} perdidas.
       Te quedan ${Math.round(an.pYo.partidos)} partidos de titulares, a él ${Math.round(an.pEl.partidos)}.</p>
      <div class="tabla-wrap" style="background:var(--card2)"><table class="liga"><thead><tr><th>Cat.</th><th>Tú</th><th>Él</th>
      <th>Prev. tú</th><th>Prev. él</th><th>Prob.</th></tr></thead><tbody>` +
      an.filas.map(f => `<tr><td class="nom">${f.c.n}</td><td>${fmtCat(f.c, f.actYo)}</td><td>${fmtCat(f.c, f.actEl)}</td>
        <td><b>${fmtCat(f.c, f.vYo)}</b></td><td><b>${fmtCat(f.c, f.vEl)}</b></td>
        <td style="color:${colorProb(f.prob)};font-weight:700">${Math.round(f.prob * 100)}%<span class="peq" style="display:block">${f.etq}</span></td></tr>`).join("") +
      `</tbody></table></div>`;
    // partidos por día lo que queda de semana
    const dias = Object.keys(an.pYo.dias);
    if (dias.length) {
      html += `<div class="dias" style="grid-template-columns:repeat(${Math.min(dias.length, 7)},1fr)">` + dias.map(d => {
        const a = an.pYo.dias[d], b = an.pEl.dias[d];
        return `<div class="dia"><span class="peq">${diaCorto(d)}</span><b>${a.titulares}<span class="peq"> vs ${b.titulares}</span></b>
          ${a.sinHueco ? `<span class="peq" style="color:var(--ambar)">${a.sinHueco} sin hueco</span>` : `<span class="peq">&nbsp;</span>`}</div>`;
      }).join("") + `</div><p class="ayuda">Partidos de titulares por día que quedan (tú vs él), con 8 huecos como máximo.
        Previsión con los promedios de los últimos 30 días; las dudas cuentan al 75 % y los lesionados no cuentan. Orientativa: no sabe de descansos ni lesiones nuevas.</p>`;
    }
    html += `</div>`;
  }

  // Alineación de hoy
  const ah = avisosHoy();
  const icono = { mal: "⛔", aviso: "⚠️", info: "ℹ️", bien: "✅" };
  html += `<div class="tarjeta"><div class="nom">Alineación de hoy (${diaCorto(hoyEEUU())}, hora EE. UU.)</div>
    <ul class="avisos">${ah.avisos.map(a => `<li>${icono[a.t]} ${a.m}</li>`).join("")}</ul>
    <details><summary>Alineación ideal de hoy</summary><table class="liga">` +
    ah.porHueco.map(h => `<tr><td class="peq">${h.hueco}</td><td style="text-align:left">${h.j ? esc(h.j.nombre) +
      (h.j.hueco === "BN" ? ' <span class="peq" style="color:var(--ambar)">(ahora en banquillo)</span>' : "") : '<span class="peq">— nadie disponible —</span>'}</td></tr>`).join("") +
    `</table><p class="ayuda">Los que juegan hoy, ordenados por valor (últimos 30 días) y respetando las posiciones de Yahoo.</p></details></div>`;

  // Clasificación
  if (LIGA.clasif && LIGA.clasif.equipos.length) {
    html += `<div class="tarjeta"><div class="nom">Clasificación</div><table class="liga"><thead><tr><th></th><th style="text-align:left">Equipo</th><th>G-P-E</th><th>%</th></tr></thead><tbody>` +
      LIGA.clasif.equipos.map(e => `<tr${e.key === LIGA.soy ? ' class="yo"' : ""}><td>${e.puesto}</td><td style="text-align:left">${esc(LIGA.nombre[e.key] || e.key)}</td>
        <td>${e.g}-${e.p}-${e.e}</td><td>${e.pct ?? ""}</td></tr>`).join("") + `</tbody></table></div>`;
  }

  // Fuerza de las plantillas
  const fz = fuerzaEquipos(), N = fz.length;
  const mio = fz.find(r => r.key === LIGA.soy);
  if (mio) {
    const ord = [...CAT_LIGA].sort((a, b) => mio.puesto[a.k] - mio.puesto[b.k]);
    html += `<div class="tarjeta"><div class="nom">Fuerza de las plantillas</div>
      <p class="ayuda" style="margin-top:2px">Tus puntos fuertes: <b style="color:var(--verde)">${ord.slice(0, 3).map(c => c.n).join(", ")}</b> ·
        flojos: <b style="color:var(--rojo)">${ord.slice(-3).map(c => c.n).join(", ")}</b>.</p>
      <div class="tabla-wrap" style="background:var(--card2)"><table class="liga"><thead><tr><th class="fijo">Equipo</th>${CAT_LIGA.map(c => `<th>${c.n}</th>`).join("")}<th>Media</th></tr></thead><tbody>` +
      fz.map(r => `<tr${r.key === LIGA.soy ? ' class="yo"' : ""}><td class="fijo">${esc(LIGA.corto[r.key])}</td>` +
        CAT_LIGA.map(c => `<td style="${colorPuesto(r.puesto[c.k], N)}">${r.puesto[c.k]}</td>`).join("") +
        `<td><b>${r.media.toFixed(1)}</b></td></tr>`).join("") +
      `</tbody></table></div><p class="ayuda">Puesto de cada equipo (1 = mejor) sumando los promedios de sus 10 mejores jugadores sanos. Sirve para ver qué te sobra y qué le falta a cada uno de cara a traspasos.</p></div>`;
  }
  cont.innerHTML = html;
}

/* ---------- integración con el ranking ---------- */
// Filtro del selector "Dueño" del ranking
function ligaFiltro(j) {
  const f = est.dueno;
  if (!f || !LIGA.liga) return true;
  const d = LIGA.dueno.get(j.id);
  if (f === "libres") return !d;
  if (f === "mio") return d === LIGA.soy;
  return d === f;
}
function ligaEtiqueta(j) {
  if (!LIGA.liga) return "";
  const d = LIGA.dueno.get(j.id);
  if (!d) return ' · <span style="color:var(--verde)">Libre</span>';
  return ` · <span style="color:${d === LIGA.soy ? "var(--ambar)" : "var(--sub)"}">${esc(LIGA.corto[d])}</span>`;
}

function prepararSelectores() {
  const opts = LIGA.liga.equipos.map(e => `<option value="${esc(e.key)}">${esc(e.nombre)}</option>`).join("");
  $("soy").innerHTML = `<option value="">Elige tu equipo…</option>` + opts;
  $("soy").value = LIGA.soy || "";
  $("soy").onchange = e => { LIGA.soy = e.target.value || null; guardarLS("soy", LIGA.soy); pintarLiga(); pintarRanking(); };
  $("dueno").innerHTML = `<option value="">Todos (libres y con dueño)</option><option value="libres">Solo libres</option>
    <option value="mio">Solo mi equipo</option>` + opts;
  $("dueno").hidden = false;
  $("dueno").onchange = e => { est.dueno = e.target.value; est.limite = PASO; pintarRanking(); };
}

async function iniciarLiga() {
  try {
    [LIGA.liga, LIGA.plantillas, LIGA.enfr, LIGA.clasif, LIGA.cal] = await Promise.all([
      cargar(LIGA.base + "liga.json"), cargar(LIGA.base + "plantillas.json"),
      cargar(LIGA.base + "enfrentamientos.json").catch(() => null),
      cargar(LIGA.base + "clasificacion.json").catch(() => null),
      cargar("data/nba/calendario.json").then(d => d.partidos)]);
  } catch (e) {
    LIGA.liga = null;          // sin datos de Yahoo: la web sigue como antes
    return;
  }
  for (const j of est.datos.jugadores) LIGA.jug.set(j.id, j);
  for (const e of LIGA.liga.equipos) {
    LIGA.nombre[e.key] = e.nombre;
    LIGA.corto[e.key] = e.nombre.length > 16 ? e.nombre.slice(0, 15) + "…" : e.nombre;
  }
  for (const [key, lista] of Object.entries(LIGA.plantillas.equipos))
    for (const y of lista) if (y.nba_id) LIGA.dueno.set(y.nba_id, key);
  const guardado = leerLS("soy", null);
  LIGA.soy = LIGA.nombre[guardado] ? guardado : null;

  document.querySelector('nav button[data-sec="liga"]').hidden = false;
  $("aviso-yahoo").hidden = false;
  if (LIGA.base.includes("prueba")) $("liga-prueba").hidden = false;
  prepararSelectores();
  pintarLiga();
  pintarRanking();
  if (leerLS("seccion", "") === "liga") document.querySelector('nav button[data-sec="liga"]').click();
}
