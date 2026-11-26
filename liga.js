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
    html += tarjetaLibres(an);
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

  // Plantillas y traspasos
  html += tarjetaPlantillas();
  html += tarjetaTraspasos();

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
  activarPlantillas();
  activarTraspasos();
  const tl = $("tabla-libres");
  if (tl) tl.onclick = e => { const tr = e.target.closest("tr.clic"); if (tr) abrirFicha({ nbaId: +tr.dataset.id }); };
}

/* ---------- integración con el ranking ---------- */
// Filtro del selector "Dueño" del ranking
function ligaFiltro(j) { return ligaFiltroValor(j, est.dueno); }
function ligaFiltroValor(j, f) {
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
  $("dueno").innerHTML = `<option value="">Libres y con dueño</option><option value="libres">Solo libres</option>
    <option value="mio">Solo mi equipo</option>` + opts;
  $("dueno").hidden = false;
  $("semana-filtro").innerHTML = `<option value="">Todos</option><option value="libres">Solo libres</option><option value="mio">Mi equipo</option>`;
  if (est.semanas) pintarCalendario();
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

/* =====================================================================
 * PLANTILLAS Y FICHA DE JUGADOR (con su historia en la liga)
 * ===================================================================== */
const ORDEN_HUECO = ["PG", "SG", "G", "SF", "PF", "F", "C", "Util", "BN", "IL", "IL+", "NA"];
LIGA.verEquipo = null;
LIGA.hist = undefined;       // undefined = sin cargar · null = no hay histórico
LIGA.histBase = LIGA.base.includes("prueba") ? "data/historico_prueba/" : "data/historico/";

const norm = n => String(n || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
  .replace(/-/g, " ").replace(/[^a-z ]/g, "").split(" ").filter(p => p && !["jr", "sr", "ii", "iii", "iv", "v"].includes(p)).join(" ");
const etqTemporada = t => `${t}-${String((+t + 1) % 100).padStart(2, "0")}`;
const fechaCorta = iso => iso ? new Date(iso + "T12:00:00Z").toLocaleDateString("es-ES", { day: "numeric", month: "short" }) : "";

function tarjetaPlantillas() {
  const key = LIGA.verEquipo || LIGA.soy || LIGA.liga.equipos[0].key;
  const opts = LIGA.liga.equipos.map(e => `<option value="${esc(e.key)}"${e.key === key ? " selected" : ""}>${esc(e.nombre)}</option>`).join("");
  const plant = plantilla(key).sort((a, b) =>
    (ORDEN_HUECO.indexOf(a.hueco) - ORDEN_HUECO.indexOf(b.hueco)) || (b._v - a._v));
  const filas = plant.map(j => {
    const nba = LIGA.jug.get(j.nba_id);
    const e = nba ? edad(nba) : null;
    const est = j.estado ? `<span style="color:${FUERA.has(j.estado) ? "var(--rojo)" : "var(--ambar)"}">${esc(j.estado)}</span>` : "";
    return `<tr class="clic" data-yahoo="${esc(j.yahoo_id)}" data-nba="${j.nba_id ?? ""}">
      <td class="peq">${esc(j.hueco || "")}</td>
      <td style="text-align:left"><span class="nom">${esc(j.nombre)}</span> ${est}<span class="peq" style="display:block">${esc(j.equipo_nba)} · ${esc((j.pos || []).join(","))}</span></td>
      <td style="${j._p ? color(j._v / 3) : ""}">${j._p ? j._v.toFixed(1) : "–"}</td>
      <td>${e == null ? "–" : e.toFixed(1)}</td></tr>`;
  }).join("");
  return `<div class="tarjeta"><div class="controles"><span class="nom">Plantilla de</span>
      <select id="ver-equipo" style="flex:1">${opts}</select></div>
    <table class="liga" id="tabla-plantilla" style="margin-top:8px"><thead><tr><th></th><th style="text-align:left">Jugador</th><th>Valor</th><th>Edad</th></tr></thead>
    <tbody>${filas}</tbody></table>
    <p class="ayuda">Hueco de hoy en Yahoo. Valor de los últimos 30 días. Toca un jugador para ver su ficha y su historia en la liga.</p></div>`;
}

// Se engancha después de pintar "Mi semana"
function activarPlantillas() {
  const sel = $("ver-equipo");
  if (sel) sel.onchange = e => { LIGA.verEquipo = e.target.value; pintarLiga(); };
  const t = $("tabla-plantilla");
  if (t) t.onclick = e => {
    const tr = e.target.closest("tr.clic"); if (!tr) return;
    abrirFicha({ yahooId: tr.dataset.yahoo, nbaId: tr.dataset.nba ? +tr.dataset.nba : null });
  };
}

async function cargarHistorico() {
  if (LIGA.hist !== undefined) return LIGA.hist;
  try {
    LIGA.hist = await cargar(LIGA.histBase + "jugadores.json");
    LIGA.hist.porNombre = new Map();
    for (const [id, j] of Object.entries(LIGA.hist.jugadores)) LIGA.hist.porNombre.set(norm(j.nombre), id);
  } catch (e) { LIGA.hist = null; }
  return LIGA.hist;
}

function textoEvento(e, eq) {
  const n = k => {
    if (!k) return "?";
    if (k === "freeagents") return "agentes libres";
    if (k === "waivers") return "waivers";
    const x = eq[k]; return x ? `<b>${esc(x.nombre)}</b>` : esc(k);
  };
  switch (e.tipo) {
    case "draft": return `🎯 Elegido en el draft por ${n(e.a)} (ronda ${e.ronda}, pick ${e.pick})`;
    case "inicio": return `🏁 Empieza la temporada en ${n(e.a)}`;
    case "add": return `➕ ${fechaCorta(e.fecha)} · Fichado por ${n(e.a)}${e.de === "waivers" ? " (desde waivers)" : " (agente libre)"}`;
    case "drop": return `➖ ${fechaCorta(e.fecha)} · Cortado por ${n(e.de)}`;
    case "trade": return `🔁 ${fechaCorta(e.fecha)} · Traspasado de ${n(e.de)} a ${n(e.a)}`;
    default: return `${fechaCorta(e.fecha)} · ${esc(e.tipo || "movimiento")}: ${n(e.de)} → ${n(e.a)}`;
  }
}

function htmlHistorial(hist, hj) {
  if (!hist) return `<p class="ayuda">El historial de la liga aparecerá cuando se importe de Yahoo (Action "Importar histórico").</p>`;
  if (!hj) return `<p class="ayuda">No ha pasado nunca por ningún equipo de la liga (o no se ha encontrado en el histórico).</p>`;
  const porT = {};
  for (const e of hj.eventos) (porT[e.t] = porT[e.t] || []).push(e);
  // Resumen: temporadas en la liga y mánagers que lo han tenido
  const managers = new Map();
  for (const e of hj.eventos) for (const k of [e.a, e.de]) {
    const x = hist.temporadas[e.t]?.equipos[k];
    if (x && x.manager) managers.set(x.manager, (managers.get(x.manager) || new Set()).add(e.t));
  }
  const nT = Object.keys(porT).length;
  const resumen = `${nT} temporada${nT === 1 ? "" : "s"} en la liga · Mánagers que lo han tenido: ` +
    [...managers].sort((a, b) => b[1].size - a[1].size).map(([m, ts]) => `${esc(m)} (${ts.size} temp.)`).join(", ");
  return `<p class="ayuda" style="margin-top:2px">${resumen}</p>` +
    Object.keys(porT).sort().reverse().map(t => {
      const eq = hist.temporadas[t]?.equipos || {};
      return `<div class="temp"><div class="nom">${etqTemporada(t)}</div><ul class="avisos">` +
        porT[t].map(e => `<li>${textoEvento(e, eq)}</li>`).join("") + `</ul></div>`;
    }).join("");
}

async function abrirFicha({ nbaId = null, yahooId = null, nombre = null }) {
  // Datos NBA y de la liga actual
  let y = null;
  if (LIGA.liga) for (const lista of Object.values(LIGA.plantillas.equipos)) {
    y = lista.find(p => (yahooId && p.yahoo_id === String(yahooId)) || (nbaId && p.nba_id === nbaId)) || y;
    if (y) break;
  }
  nbaId = nbaId || (y && y.nba_id);
  const j = nbaId ? (LIGA.jug.get(nbaId) || est.datos.jugadores.find(x => x.id === nbaId)) : null;
  nombre = nombre || (j && j.nombre) || (y && y.nombre) || "Jugador";
  let caja = $("ficha");
  if (!caja) {
    caja = document.createElement("div"); caja.id = "ficha";
    caja.onclick = e => {
      if (e.target === caja || e.target.closest(".cerrar")) { caja.hidden = true; return; }
      const b = e.target.closest("#ficha-comparar");
      if (b) { alternarComparar(+caja.dataset.id); const on = LIGA.comp.includes(+caja.dataset.id);
        b.classList.toggle("on", on); b.textContent = on ? "✓ Comparando" : "Comparar"; }
    };
    document.body.appendChild(caja);
  }
  const dueno = y ? Object.entries(LIGA.plantillas.equipos).find(([, l]) => l.includes(y))?.[0] : null;
  const e = j ? edad(j) : null;
  const linea = (etq, s) => s && s.pj ? `<tr><td class="peq" style="text-align:left">${etq}</td><td>${s.pj}</td><td>${s.min.toFixed(0)}</td>` +
    CATS.map((c, i) => `<td style="${color(s.z?.[i])}">${c.v(s)}</td>`).join("") + `<td><b>${(s.valor ?? 0).toFixed(1)}</b></td></tr>` : "";
  const stats = j ? `<div class="tabla-wrap" style="background:var(--card2);margin-top:8px"><table class="liga"><thead><tr><th></th><th>PJ</th><th>MIN</th>` +
    CATS.map(c => `<th>${c.n}</th>`).join("") + `<th>Valor</th></tr></thead><tbody>` +
    linea("Temporada", j.temporada) + linea("30 días", j.ult30) + linea("7 días", j.ult7) + `</tbody></table></div>` : "";
  const pintar = hist => {
    const hid = hist && (yahooId && hist.jugadores[yahooId] ? String(yahooId)
      : y && hist.jugadores[y.yahoo_id] ? y.yahoo_id : hist.porNombre.get(norm(nombre)));
    caja.innerHTML = `<div class="panel"><button class="cerrar" aria-label="Cerrar">✕</button>
      <div class="nom" style="font-size:18px">${esc(nombre)}</div>
      ${j ? `<button class="chip${LIGA.comp.includes(j.id) ? " on" : ""}" id="ficha-comparar" style="margin:6px 0 4px">${LIGA.comp.includes(j.id) ? "✓ Comparando" : "Comparar"}</button>` : ""}
      <div class="peq">${esc(j?.equipo || y?.equipo_nba || "")}${j?.pos || y?.pos?.length ? " · " + esc(y?.pos?.join(",") || j.pos) : ""}${e != null ? ` · ${e.toFixed(1)} años` : ""}</div>
      ${LIGA.liga ? `<p style="margin:8px 0 0">${dueno ? `En <b style="color:${dueno === LIGA.soy ? "var(--ambar)" : "var(--txt)"}">${esc(LIGA.nombre[dueno])}</b>` +
        ` <span class="peq">(${esc(y.hueco === "BN" ? "banquillo" : y.hueco || "")}${y.estado ? " · " + esc(y.estado) : ""})</span>` : `<b style="color:var(--verde)">Libre</b>`}</p>` : ""}
      ${y?.lesion ? `<p class="peq" style="color:var(--rojo)">${esc(y.lesion)}</p>` : ""}
      ${stats}
      <div class="nom" style="margin-top:14px">Historia en la liga</div>
      ${hist === undefined ? `<p class="ayuda">Cargando…</p>` : htmlHistorial(hist, hid && hist.jugadores[hid])}
    </div>`;
  };
  caja.dataset.id = j ? j.id : "";
  pintar(LIGA.hist);
  caja.hidden = false;
  if (LIGA.hist === undefined) pintar(await cargarHistorico());
}

/* =====================================================================
 * TRASPASOS: evaluador y propuestas automáticas
 * ===================================================================== */
LIGA.tr = { otro: null, doy: new Set(), recibo: new Set(), propuestas: null };

// Totales por categoría con los 10 mejores sanos de una lista de jugadores
function totalesLista(lista) {
  const top = lista.filter(j => j._p && j.hueco !== "IL" && j.hueco !== "IL+").sort((a, b) => b._v - a._v).slice(0, 10);
  const t = { fgm: 0, fga: 0, ftm: 0, fta: 0, tpm: 0, pts: 0, reb: 0, ast: 0, stl: 0, blk: 0, to: 0 };
  for (const j of top) for (const k in t) t[k] += j._p[k] || 0;
  const v = {};
  for (const c of CAT_LIGA) v[c.k] = c.pct ? (t[c.a] ? t[c.m] / t[c.a] : 0) : t[c.k];
  return v;
}
function puestos(key, V) {
  const p = {};
  for (const c of CAT_LIGA) {
    let r = 1;
    for (const [k, v] of Object.entries(V)) if (k !== key && (c.menos ? v[c.k] < V[key][c.k] : v[c.k] > V[key][c.k])) r++;
    p[c.k] = r;
  }
  p.media = CAT_LIGA.reduce((s, c) => s + p[c.k], 0) / CAT_LIGA.length;
  return p;
}
function valoresBase() {
  const V = {}, P = {};
  for (const e of LIGA.liga.equipos) { P[e.key] = plantilla(e.key); V[e.key] = totalesLista(P[e.key]); }
  return { V, P };
}
function simular(base, yo, el, doy, recibo) {
  const V = { ...base.V };
  const fuera = (lista, quitar) => { const ids = new Set(quitar.map(j => j.yahoo_id)); return lista.filter(j => !ids.has(j.yahoo_id)); };
  const mio = fuera(base.P[yo], doy).concat(recibo);
  const suyo = fuera(base.P[el], recibo).concat(doy);
  V[yo] = totalesLista(mio); V[el] = totalesLista(suyo);
  return { yo: puestos(yo, V), el: puestos(el, V) };
}
const dinDe = j => { const n = LIGA.jug.get(j.nba_id); return n ? dinastia(n) : null; };
const edadDe = j => { const n = LIGA.jug.get(j.nba_id); return n ? edad(n) : null; };
const suma = (lista, f) => lista.reduce((s, j) => s + (f(j) ?? 0), 0);

function buscarPropuestas() {
  const base = valoresBase(), yo = LIGA.soy;
  const antesYo = puestos(yo, base.V).media;
  const res = [];
  for (const e of LIGA.liga.equipos) {
    if (e.key === yo) continue;
    const antesEl = puestos(e.key, base.V).media;
    for (const p of base.P[yo]) {
      if (!p._p) continue;
      for (const q of base.P[e.key]) {
        if (!q._p) continue;
        const r = simular(base, yo, e.key, [p], [q]);
        const gYo = antesYo - r.yo.media, gEl = antesEl - r.el.media;
        if (gYo > 0.05 && gEl > 0.05) res.push({ el: e.key, p, q, gYo, gEl, dDin: (dinDe(q) ?? 0) - (dinDe(p) ?? 0) });
      }
    }
  }
  // Se premia que mejore a los dos y se castiga que sea muy desigual en dinastía (el otro no lo aceptaría)
  const nota = r => r.gYo + r.gEl * 0.5 - 0.12 * Math.max(0, Math.abs(r.dDin) - 2);
  res.sort((a, b) => nota(b) - nota(a));
  // variedad: como mucho 2 propuestas por jugador que das y 1 por jugador que recibes
  const cuenta = new Map(), out = [];
  for (const r of res) {
    if ((cuenta.get(r.p) || 0) >= 2 || (cuenta.get(r.q) || 0) >= 1) continue;
    cuenta.set(r.p, (cuenta.get(r.p) || 0) + 1); cuenta.set(r.q, 1); out.push(r);
    if (out.length >= 10) break;
  }
  return out;
}

function tarjetaTraspasos() {
  const T = LIGA.tr, yo = LIGA.soy;
  const otros = LIGA.liga.equipos.filter(e => e.key !== yo);
  if (!T.otro || T.otro === yo) T.otro = otros[0].key;
  const mios = plantilla(yo).sort((a, b) => b._v - a._v), suyos = plantilla(T.otro).sort((a, b) => b._v - a._v);
  const chip = (j, lado) => {
    const on = (lado === "doy" ? T.doy : T.recibo).has(j.yahoo_id);
    const e = edadDe(j);
    return `<button class="chip${on ? " on" : ""}" data-lado="${lado}" data-y="${esc(j.yahoo_id)}">${esc(j.nombre)}<span class="peq" style="color:inherit;opacity:.75"> ${e != null ? Math.floor(e) : ""}</span></button>`;
  };
  let res = "";
  const doy = mios.filter(j => T.doy.has(j.yahoo_id)), recibo = suyos.filter(j => T.recibo.has(j.yahoo_id));
  if (doy.length && recibo.length) {
    const base = valoresBase();
    const aYo = puestos(yo, base.V), aEl = puestos(T.otro, base.V);
    const r = simular(base, yo, T.otro, doy, recibo);
    const flecha = (a, b) => `${a}→<b style="color:${b < a ? "var(--verde)" : b > a ? "var(--rojo)" : "var(--txt)"}">${b}</b>`;
    const gYo = aYo.media - r.yo.media, gEl = aEl.media - r.el.media;
    const veredicto = gYo > 0.05 && gEl > 0.05 ? "✅ Os mejora a los dos" : gYo > 0.05 ? "👍 Te mejora a ti, a él no" :
      gEl > 0.05 ? "👎 Le mejora a él, a ti no" : "➖ No mejora a ninguno";
    const paquete = l => `valor ${suma(l, j => j._v).toFixed(1)} · dinastía ${suma(l, dinDe).toFixed(1)} · edad media ${(suma(l, edadDe) / l.length).toFixed(1)}`;
    res = `<p style="margin:10px 0 4px"><b>${veredicto}</b></p>
      <p class="ayuda" style="margin:0">Das: ${paquete(doy)}<br>Recibes: ${paquete(recibo)}</p>
      <table class="liga" style="margin-top:6px"><thead><tr><th>Cat.</th><th>Tú (puesto)</th><th>Él (puesto)</th></tr></thead><tbody>` +
      CAT_LIGA.map(c => `<tr><td class="nom">${c.n}</td><td>${flecha(aYo[c.k], r.yo[c.k])}</td><td>${flecha(aEl[c.k], r.el[c.k])}</td></tr>`).join("") +
      `<tr><td class="nom">Media</td><td>${aYo.media.toFixed(1)}→<b>${r.yo.media.toFixed(1)}</b></td><td>${aEl.media.toFixed(1)}→<b>${r.el.media.toFixed(1)}</b></td></tr></tbody></table>`;
  }
  const props = T.propuestas;
  const htmlProps = props == null ? "" : !props.length ? `<p class="ayuda">No he encontrado traspasos 1 por 1 que mejoren a los dos.</p>` :
    `<ul class="avisos" id="lista-propuestas">` + props.map((r, i) => `<li class="clic" data-i="${i}">🔁 <b>${esc(r.p.nombre)}</b> por <b>${esc(r.q.nombre)}</b>
      <span class="peq" style="display:block">con ${esc(LIGA.nombre[r.el])} · tu media de puestos −${r.gYo.toFixed(2)}, la suya −${r.gEl.toFixed(2)} ·
      dinastía ${r.dDin >= 0 ? "+" : ""}${r.dDin.toFixed(1)}</span></li>`).join("") + `</ul>`;
  return `<div class="tarjeta" id="tarjeta-traspasos"><div class="nom">Traspasos</div>
    <div class="controles" style="margin-top:8px"><span class="peq">Con</span><select id="tr-otro" style="flex:1">` +
    otros.map(e => `<option value="${esc(e.key)}"${e.key === T.otro ? " selected" : ""}>${esc(e.nombre)}</option>`).join("") + `</select></div>
    <div class="peq" style="margin-top:10px">Das</div><div class="chips" style="margin-top:4px">${mios.map(j => chip(j, "doy")).join("")}</div>
    <div class="peq" style="margin-top:10px">Recibes</div><div class="chips" style="margin-top:4px">${suyos.map(j => chip(j, "recibo")).join("")}</div>
    ${res}
    <button class="mas" id="tr-buscar">Buscar traspasos que nos mejoren a los dos</button>${htmlProps}
    <p class="ayuda">Puestos (1 = mejor de 12) en cada categoría con los 10 mejores jugadores sanos de cada equipo, antes → después.
      Es una ayuda para pensar, no tiene en cuenta el calendario ni las lesiones futuras.</p></div>`;
}

function activarTraspasos() {
  const t = $("tarjeta-traspasos"); if (!t) return;
  const T = LIGA.tr;
  $("tr-otro").onchange = e => { T.otro = e.target.value; T.recibo.clear(); pintarLiga(); };
  t.onclick = e => {
    const b = e.target.closest("button.chip[data-lado]");
    if (b) {
      const set = b.dataset.lado === "doy" ? T.doy : T.recibo;
      set.has(b.dataset.y) ? set.delete(b.dataset.y) : set.add(b.dataset.y);
      pintarLiga(); $("tarjeta-traspasos")?.scrollIntoView({ block: "nearest" }); return;
    }
    if (e.target.closest("#tr-buscar")) { T.propuestas = buscarPropuestas(); pintarLiga(); $("tarjeta-traspasos")?.scrollIntoView({ block: "start" }); return; }
    const li = e.target.closest("#lista-propuestas li.clic");
    if (li) {
      const r = T.propuestas[+li.dataset.i];
      T.otro = r.el; T.doy = new Set([r.p.yahoo_id]); T.recibo = new Set([r.q.yahoo_id]);
      pintarLiga(); $("tarjeta-traspasos")?.scrollIntoView({ block: "start" });
    }
  };
}

/* =====================================================================
 * AGENTES LIBRES PARA ESTA SEMANA
 * ===================================================================== */
function libresSemana(an) {
  const peso = {};
  for (const f of an.filas) peso[f.c.k] = f.prob > 0.15 && f.prob < 0.85 ? 1 : 0.25;
  const fin = LIGA.enfr.fin, res = [];
  for (const j of est.datos.jugadores) {
    if (LIGA.dueno.has(j.id)) continue;
    const s = j.ult30;
    if (!s || !s.elegible || !s.z) continue;
    const quedan = partidosPendientes(j.equipo, an.desde, fin).length;
    if (!quedan) continue;
    let nota = 0;
    const ayuda = [];
    CAT_LIGA.forEach((c, i) => {
      nota += (peso[c.k] ?? 0.25) * s.z[i];
      if (peso[c.k] === 1 && s.z[i] > 0.4) ayuda.push([c.n, s.z[i]]);
    });
    res.push({ j, quedan, nota: nota * quedan, ayuda: ayuda.sort((a, b) => b[1] - a[1]).slice(0, 3).map(x => x[0]) });
  }
  return res.sort((a, b) => b.nota - a.nota).slice(0, 6);
}

function tarjetaLibres(an) {
  const aire = an.filas.filter(f => f.prob > 0.15 && f.prob < 0.85).map(f => f.c.n);
  const L = libresSemana(an);
  if (!L.length) return "";
  return `<div class="tarjeta"><div class="nom">Libres que te ayudan esta semana</div>
    <p class="ayuda" style="margin-top:2px">Categorías en el aire: <b style="color:var(--ambar)">${aire.join(", ") || "ninguna"}</b>.</p>
    <table class="liga" id="tabla-libres"><tbody>` +
    L.map(r => `<tr class="clic" data-id="${r.j.id}"><td style="text-align:left"><span class="nom">${esc(r.j.nombre)}</span>
      <span class="peq" style="display:block">${esc(r.j.equipo)}${r.j.pos ? " · " + esc(r.j.pos) : ""}${r.ayuda.length ? " · ayuda en " + r.ayuda.join(", ") : ""}</span></td>
      <td><b>${r.quedan}</b><span class="peq" style="display:block">partidos</span></td></tr>`).join("") +
    `</tbody></table><p class="ayuda">Ordenados por lo que aportan en las categorías en el aire (últimos 30 días) multiplicado por los partidos que les quedan esta semana.</p></div>`;
}

/* =====================================================================
 * COMPARADOR DE JUGADORES (hasta 3, desde la ficha)
 * ===================================================================== */
LIGA.comp = [];
LIGA.compVentana = "ult30";

function botonComparar() {
  let b = $("btn-comparar");
  if (!b) {
    b = document.createElement("button"); b.id = "btn-comparar";
    b.onclick = abrirComparador; document.body.appendChild(b);
  }
  b.hidden = !LIGA.comp.length;
  b.textContent = `Comparar (${LIGA.comp.length})`;
}

function alternarComparar(id) {
  const i = LIGA.comp.indexOf(id);
  if (i >= 0) LIGA.comp.splice(i, 1);
  else { if (LIGA.comp.length >= 3) LIGA.comp.shift(); LIGA.comp.push(id); }
  botonComparar();
}

function abrirComparador() {
  const caja = $("ficha") || (abrirFicha({ nbaId: LIGA.comp[0] }), $("ficha"));
  const v = LIGA.compVentana;
  const js = LIGA.comp.map(id => est.datos.jugadores.find(x => x.id === id)).filter(Boolean);
  const filas = [
    ["Edad", j => edad(j), x => x == null ? "–" : x.toFixed(1), "menos"],
    ["Dinastía", j => dinastia(j), x => x == null ? "–" : x.toFixed(1)],
    ["Tendencia", j => tendencia(j), x => x == null ? "–" : (x > 0 ? "▲" : "▼") + Math.abs(x).toFixed(1)],
    ["Valor", j => j[v]?.z ? valorJugador(j[v]) : null, x => x == null ? "–" : x.toFixed(1)],
    ["PJ", j => j[v]?.pj, x => x ?? "–", "nada"],
    ["MIN", j => j[v]?.min, x => x == null ? "–" : x.toFixed(1)],
    ...CATS.map((c, i) => [c.n, j => j[v]?.z ? j[v].z[i] : null, (x, j) => j[v] ? c.v(j[v]) : "–"]),
  ];
  let html = `<div class="panel"><button class="cerrar" aria-label="Cerrar">✕</button>
    <div class="nom" style="font-size:24px">Comparar jugadores</div>
    <div class="controles" style="margin-top:8px"><select id="comp-ventana">
      <option value="temporada">Temporada</option><option value="ult30">Últimos 30 días</option>
      <option value="ult14">Últimos 14 días</option><option value="ult7">Últimos 7 días</option></select>
      <button class="chip" id="comp-vaciar">Vaciar</button></div>
    <div class="tabla-wrap" style="background:var(--card2);margin-top:10px"><table class="liga"><thead><tr><th></th>` +
    js.map(j => `<th style="color:var(--txt)">${esc(j.nombre)}<span class="peq" style="display:block">${esc(j.equipo)}${j.pos ? " · " + esc(j.pos) : ""}</span>
      ${LIGA.liga ? `<span class="peq" style="display:block">${LIGA.dueno.get(j.id) ? esc(LIGA.corto[LIGA.dueno.get(j.id)]) : "Libre"}</span>` : ""}</th>`).join("") +
    `</tr></thead><tbody>`;
  for (const [n, f, fmtF, modo] of filas) {
    const vals = js.map(f);
    const ok = vals.filter(x => x != null);
    const mejor = modo === "nada" || ok.length < 2 ? null : modo === "menos" ? Math.min(...ok) : Math.max(...ok);
    html += `<tr><td class="nom" style="text-align:left">${n}</td>` + js.map((j, i) =>
      `<td style="${vals[i] != null && vals[i] === mejor ? "color:var(--verde);font-weight:700" : ""}">${fmtF(vals[i], j)}</td>`).join("") + `</tr>`;
  }
  html += `</tbody></table></div><p class="ayuda">En verde, el mejor de cada fila (en las categorías, según su puntuación respecto a la liga).
    Para añadir jugadores, abre su ficha y toca "Comparar".</p></div>`;
  caja.innerHTML = html; caja.hidden = false;
  $("comp-ventana").value = v;
  $("comp-ventana").onchange = e => { LIGA.compVentana = e.target.value; abrirComparador(); };
  $("comp-vaciar").onclick = () => { LIGA.comp = []; botonComparar(); caja.hidden = true; };
}
