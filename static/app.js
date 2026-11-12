/* Conciliador HOLALUKA — interfaz. Sin almacenamiento: los archivos viven solo en esta pestaña. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const ORDER = ["SINTESIS", "LUKA", "BANCO"];
  const LABEL = { SINTESIS: "Síntesis NETVALLE", LUKA: "Pagos LUKA", BANCO: "Extracto bancario", DECISIONES: "Decisiones anteriores" };
  const RULE_COLOR = { R1: "var(--r1)", R2: "var(--r2)", R3: "var(--r3)", R4: "var(--r4)", R5: "var(--r5)", M: "var(--m)" };
  const state = { files: {}, info: {}, decisiones: [], result: null, busy: false };
  const money = new Intl.NumberFormat("es-BO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtBs = (n) => (n === null || n === undefined || n === "" ? "" : money.format(n));
  const fmtD = (s) => (s ? s.slice(0, 10).split("-").reverse().join("/") : "");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ------------------------------------------------ red
  async function api(path, body) {
    const headers = {};
    const key = sessionStorage.getItem("accessKey");
    if (key) headers["X-Access-Key"] = key;
    const r = await fetch(path, { method: "POST", body, headers });
    if (r.status === 401) {
      const k = prompt("Ingresa la clave de acceso del conciliador:");
      if (k) { sessionStorage.setItem("accessKey", k.trim()); return api(path, body); }
      throw new Error("Se requiere la clave de acceso.");
    }
    let data;
    try { data = await r.json(); } catch { throw new Error(`Error del servidor (${r.status}).`); }
    if (!r.ok) throw new Error(data.error || data.detail || `Error ${r.status}`);
    return data;
  }

  fetch("/health").then((r) => r.json()).then((h) => { $("#ver").textContent = `Motor v${h.version}`; }).catch(() => {});

  // ------------------------------------------------ carga de archivos
  async function addFile(file, slotTipo) {
    const slot = slotTipo ? $(`.slot[data-tipo="${slotTipo}"]`) : null;
    if (slot) setStatus(slot, `<span class="spin"></span> Leyendo ${esc(file.name)}…`);
    const fd = new FormData();
    fd.append("archivo", file);
    let info;
    try {
      info = await api("/api/inspeccionar", fd);
    } catch (e) {
      if (slot) { slot.classList.add("err"); slot.classList.remove("ok"); setStatus(slot, `<span class="bad">${esc(e.message)}</span>`); }
      else flash(e.message);
      return;
    }
    const tipo = info.tipo;
    let note = "";
    if (slotTipo && slotTipo !== tipo) {
      note = `Este archivo es <b>${LABEL[tipo]}</b>; se colocó en su casilla.`;
      setStatus(slot, `<span class="warn">${note}</span>`);
      slot.classList.remove("ok", "err");
      if (state.files[slotTipo]) renderSlot(slotTipo);
    }
    state.files[tipo] = file;
    state.info[tipo] = info;
    renderSlot(tipo);
    refresh();
  }

  function setStatus(slot, html) { $(".status", slot).innerHTML = html; }

  function renderSlot(tipo) {
    const slot = $(`.slot[data-tipo="${tipo}"]`);
    const f = state.files[tipo], i = state.info[tipo];
    slot.classList.remove("err", "ok");
    if (!f) { setStatus(slot, ""); $(".drop-txt", slot).textContent = "Seleccionar o soltar archivo"; return; }
    slot.classList.add("ok");
    $(".drop-txt", slot).textContent = "Reemplazar archivo";
    const d = i.detalle || {};
    const lines = [];
    const rango = i.desde ? `${fmtD(i.desde)} – ${fmtD(i.hasta)}` : "";
    if (tipo === "SINTESIS") lines.push(`${i.filas} facturas válidas · ${rango}`, `Caja ${d.caja || "—"} · Bs ${fmtBs(d.total_neto)}`, d.anuladas_o_cero ? `${d.anuladas_o_cero} anuladas o en cero (excluidas)` : "");
    if (tipo === "LUKA") lines.push(`${i.filas} pagos · cumplimiento ${rango}`, `${d.qr} QR · ${d.tarjeta} tarjeta`, `Receptores: ${Object.entries(d.receptores || {}).map(([k, v]) => `${k} ${v}`).join(" · ")}`);
    if (tipo === "BANCO") lines.push(`${i.filas} créditos · ${rango}`, `${d.abonos_holaluka} HOLALUKA · ${d.abonos_linkser} LINKSER`, `Formato: ${d.formato}`);
    if (tipo === "DECISIONES") lines.push(`${i.filas} decisiones guardadas`);
    const warns = (i.advertencias || []).map((w) => `<li class="warn">${esc(w)}</li>`).join("");
    setStatus(slot, `<div class="file"><span class="ok">✓ ${esc(f.name)}</span><button type="button" data-remove="${tipo}">Quitar</button></div>
      <ul>${lines.filter(Boolean).map((l) => `<li>${esc(l)}</li>`).join("")}${warns}</ul>`);
  }

  function refresh() {
    const missing = ORDER.filter((t) => !state.files[t]);
    ORDER.forEach((t, i) => window.Scene3D.setLoaded(i, !!state.files[t]));
    const btn = $("#btnRun");
    btn.disabled = missing.length > 0 || state.busy;
    const msgs = [];
    if (missing.length) msgs.push(`Falta: ${missing.map((t) => LABEL[t]).join(", ")}.`);
    const s = state.info.SINTESIS, l = state.info.LUKA, b = state.info.BANCO;
    if (s && l && (l.desde > s.desde || l.hasta < s.hasta)) msgs.push("LUKA no cubre todo el período de la Síntesis.");
    if (s && b) {
      const fin = new Date(s.hasta); fin.setDate(fin.getDate() + 2);
      if (new Date(b.hasta) < fin) msgs.push("El extracto debería incluir los primeros días del mes siguiente.");
    }
    if (!missing.length && !msgs.length) msgs.push("Listo para conciliar.");
    $("#runMsg").textContent = msgs.join(" ");
  }

  $$(".slot").forEach((slot) => {
    const input = $("input[type=file]", slot);
    input.addEventListener("change", () => { if (input.files[0]) addFile(input.files[0], slot.dataset.tipo); input.value = ""; });
    slot.addEventListener("dragover", (e) => { e.preventDefault(); e.stopPropagation(); slot.classList.add("over"); hideVeil(); });
    slot.addEventListener("dragleave", () => slot.classList.remove("over"));
    slot.addEventListener("drop", (e) => {
      e.preventDefault(); e.stopPropagation(); slot.classList.remove("over"); hideVeil();
      const fs = [...e.dataTransfer.files];
      if (fs.length === 1) addFile(fs[0], slot.dataset.tipo); else fs.forEach((f) => addFile(f));
    });
  });
  $("#slots").addEventListener("click", (e) => {
    const t = e.target.closest("[data-remove]")?.dataset.remove;
    if (!t) return;
    e.preventDefault();
    delete state.files[t]; delete state.info[t];
    renderSlot(t); refresh();
  });

  // soltar varios archivos en cualquier parte
  const veil = $("#dropveil");
  let dragDepth = 0;
  const hideVeil = () => { dragDepth = 0; veil.hidden = true; };
  addEventListener("dragenter", (e) => { if (e.dataTransfer?.types?.includes("Files")) { dragDepth++; veil.hidden = false; } });
  addEventListener("dragleave", () => { if (--dragDepth <= 0) hideVeil(); });
  addEventListener("dragover", (e) => e.preventDefault());
  addEventListener("drop", (e) => { e.preventDefault(); hideVeil(); [...(e.dataTransfer?.files || [])].forEach((f) => addFile(f)); });

  function flash(msg) { $("#runMsg").innerHTML = `<span class="tag-bad">${esc(msg)}</span>`; }

  // ------------------------------------------------ conciliar
  function params() {
    const o = {};
    $$(".params input").forEach((i) => { o[i.name] = i.value.trim(); });
    return o;
  }

  async function run() {
    if (state.busy) return;
    state.busy = true; refresh();
    const btn = $("#btnRun"), btn2 = $("#btnReprocess");
    btn.textContent = "Conciliando…"; if (btn2) btn2.disabled = true;
    window.Scene3D.setStatus("running");
    const fd = new FormData();
    fd.append("sintesis", state.files.SINTESIS);
    fd.append("banco", state.files.BANCO);
    fd.append("luka", state.files.LUKA);
    if (state.files.DECISIONES) fd.append("decisiones_archivo", state.files.DECISIONES);
    fd.append("decisiones", JSON.stringify(state.decisiones));
    fd.append("parametros", JSON.stringify(params()));
    try {
      const t0 = performance.now();
      const res = await api("/api/conciliar", fd);
      await new Promise((r) => setTimeout(r, Math.max(0, 700 - (performance.now() - t0))));
      state.result = res;
      render(res);
      window.Scene3D.setStatus(res.asiento_liberable ? "done" : "warn");
      $("#resultado").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      window.Scene3D.setStatus("error");
      flash(e.message);
    } finally {
      state.busy = false; btn.textContent = "Conciliar"; if (btn2) btn2.disabled = false; refresh();
    }
  }
  $("#btnRun").addEventListener("click", run);
  $("#btnReprocess").addEventListener("click", run);

  $("#btnExcel").addEventListener("click", () => {
    const r = state.result; if (!r) return;
    const bin = atob(r.excel_b64), buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([buf], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: r.excel_nombre });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  });

  // ------------------------------------------------ render resultado
  function render(r) {
    $("#resultado").hidden = false;
    const s = r.resumen;
    $("#resPeriodo").textContent = `Período ${fmtD(r.periodo.desde)} – ${fmtD(r.periodo.hasta)} · Receptor LUKA de la sede: ${r.receptor || "—"}`;
    const b = $("#banner");
    b.className = "banner " + (r.asiento_liberable ? "ok" : "bad");
    b.textContent = r.asiento_liberable
      ? "✓ Asiento liberable: todas las facturas conciliadas y controles en cero."
      : `Asiento no liberado: ${r.bloqueos.join(" · ")}. El Excel incluye el asiento parcial marcado como no liberado.`;

    $("#kpis").innerHTML = [
      ["Facturas", s.facturas, `Bs ${fmtBs(s.total_neto)}`, ""],
      ["Conciliadas", s.conciliadas, `${s.porcentaje}% · Bs ${fmtBs(s.total_conciliado)}`, "accent"],
      ["Excepciones", s.pendientes, `Bs ${fmtBs(s.total_pendiente)}`, s.pendientes ? "alert" : ""],
      ["Comisión tarjetas", fmtBs(s.comision_tarjetas), `${s.por_regla.R4} tarjeta(s)`, ""],
      ["Sin factura", s.abonos_sin_factura_periodo + s.luka_sin_factura, "abonos / pagos LUKA a revisar", s.abonos_sin_factura_periodo + s.luka_sin_factura ? "alert" : ""],
    ].map(([k, v, sub, cls]) => `<div class="kpi ${cls}"><small>${k}</small><b>${esc(v)}</b><span>${esc(sub)}</span></div>`).join("");

    const tot = s.facturas || 1;
    const segs = Object.entries(s.por_regla).filter(([, n]) => n).map(([k, n]) => `<i style="width:${(100 * n) / tot}%;background:${RULE_COLOR[k]}" title="${k}: ${n}"></i>`);
    if (s.pendientes) segs.push(`<i style="width:${(100 * s.pendientes) / tot}%;background:var(--pend)" title="Pendientes: ${s.pendientes}"></i>`);
    $("#ruleBar").innerHTML = segs.join("");
    $("#ruleLegend").innerHTML = Object.entries(r.reglas).map(([k, name]) => `<li><i style="background:${RULE_COLOR[k]}"></i>${k} · ${esc(name)} <b>${s.por_regla[k]}</b></li>`).join("")
      + `<li><i style="background:var(--pend)"></i>Excepciones <b>${s.pendientes}</b></li>`;

    $("#warnings").innerHTML = r.advertencias.map((w) => `<li>${esc(w)}</li>`).join("");

    const counts = { exc: r.excepciones.length, conc: r.conciliadas.length, abonos: r.abonos_sin_factura.filter((a) => a.en_periodo).length, lukasin: r.luka_sin_factura.length };
    $$("#tabs button").forEach((t) => { const sp = $("span", t); if (sp) sp.textContent = counts[t.dataset.tab]; });

    renderExc(r);
    renderConc(r.conciliadas, "");
    renderAbonos(r.abonos_sin_factura);
    renderLuka(r.luka_sin_factura);
    renderCtrl(r.controles);
    renderDecisions();
  }

  function table(el, cols, rows, empty) {
    if (!rows.length) { el.innerHTML = `<tbody><tr><td class="empty" colspan="${cols.length}">${empty}</td></tr></tbody>`; return; }
    el.innerHTML = `<thead><tr>${cols.map((c) => `<th class="${c[2] || ""}">${c[0]}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${cols.map((c) => `<td class="${c[2] || ""}">${c[1](r)}</td>`).join("")}</tr>`).join("")}</tbody>`;
  }
  const chip = (k) => (k ? `<span class="chip" style="background:${RULE_COLOR[k]}">${k}</span>` : "");

  function renderConc(rows, q) {
    q = q.trim().toUpperCase();
    const f = q ? rows.filter((x) => [x.factura, x.alumno, x.asignacion, x.codigo_luka].join(" ").toUpperCase().includes(q)) : rows;
    table($("#tblConc"), [
      ["Factura", (x) => x.factura, "mono"], ["Fecha", (x) => fmtD(x.fecha), "mono"], ["Alumno", (x) => esc(x.alumno)],
      ["Neto", (x) => fmtBs(x.neto), "num"], ["Regla", (x) => chip(x.regla)], ["Cód. LUKA", (x) => esc(x.codigo_luka || ""), "mono"],
      ["Asignación", (x) => esc(x.asignacion), "mono"], ["Fecha banco", (x) => fmtD(x.fecha_banco), "mono"],
      ["Monto banco", (x) => fmtBs(x.monto_banco), "num"], ["Comisión", (x) => (x.comision ? fmtBs(x.comision) : ""), "num"],
      ["Evidencia", (x) => esc(x.evidencia), "ev"],
    ], f, "Sin resultados.");
  }
  $("#search").addEventListener("input", (e) => state.result && renderConc(state.result.conciliadas, e.target.value));

  function renderAbonos(rows) {
    const sorted = [...rows].sort((a, b) => (b.en_periodo - a.en_periodo) || a.fecha.localeCompare(b.fecha));
    table($("#tblAbonos"), [
      ["Fecha", (x) => fmtD(x.fecha), "mono"], ["Asignación", (x) => esc(x.asignacion), "mono"], ["Monto", (x) => fmtBs(x.monto), "num"],
      ["Cód. LUKA", (x) => esc(x.codigo_luka || ""), "mono"], ["Depositante", (x) => esc(x.depositante)],
      ["Clasificación", (x) => `<span class="${x.en_periodo ? "tag-bad" : ""}">${esc(x.clasificacion)}</span>`],
    ], sorted, "Todos los abonos HOLALUKA y LINKSER tienen factura.");
  }
  function renderLuka(rows) {
    table($("#tblLuka"), [
      ["Código", (x) => esc(x.codigo), "mono"], ["Alumno", (x) => esc(x.alumno)], ["Cód. estudiante", (x) => esc(x.codigo_estudiante), "mono"],
      ["Monto", (x) => fmtBs(x.monto), "num"], ["Método", (x) => esc(x.metodo)], ["Cumplimiento", (x) => esc(x.fecha_cumplimiento), "mono"],
      ["Receptor", (x) => esc(x.receptor || "—")], ["Abono en banco", (x) => esc(x.asignacion_banco || "—"), "mono"],
    ], rows, "Todos los pagos LUKA de la sede tienen factura.");
  }
  function renderCtrl(rows) {
    table($("#tblCtrl"), [
      ["Control", (x) => esc(x.control)], ["Valor", (x) => esc(x.valor), "num"],
      ["Resultado", (x) => (x.ok ? '<span class="tag-ok">OK</span>' : '<span class="tag-bad">REVISAR</span>')], ["Detalle", (x) => esc(x.detalle || ""), "ev"],
    ], rows, "");
  }

  function renderExc(r) {
    const pane = $("#paneExc");
    if (!r.excepciones.length) { pane.innerHTML = `<div class="empty">Sin excepciones: todas las facturas quedaron conciliadas.</div>`; return; }
    pane.innerHTML = r.excepciones.map((x) => {
      const dec = state.decisiones.find((d) => d.factura === x.factura);
      const props = x.propuestas.length
        ? `<div class="tablewrap"><table><thead><tr><th>Confianza</th><th>Asignación</th><th>Fecha</th><th class="num">Monto</th><th class="num">Diferencia</th><th>Depositante</th><th>Razón</th><th></th></tr></thead><tbody>
          ${x.propuestas.map((p, k) => `<tr><td><span class="conf ${p.confianza}">${p.confianza}</span></td><td class="mono">${esc(p.asignacion)}</td><td class="mono">${fmtD(p.fecha)}</td>
          <td class="num">${fmtBs(p.monto)}</td><td class="num ${p.diferencia ? "tag-bad" : ""}">${fmtBs(p.diferencia)}</td><td>${esc(p.depositante)}</td><td class="ev">${esc(p.motivo)}</td>
          <td><button class="btn sm" data-approve="${x.factura}" data-k="${k}">Aprobar</button></td></tr>`).join("")}</tbody></table></div>`
        : `<p class="muted">No hay candidatos en el extracto cargado. Si verificaste el depósito (incluso de otro mes), regístralo abajo.</p>`;
      return `<article class="exc ${dec ? "decided" : ""}">
        <div class="exc-head"><h3>F-${x.factura} · ${esc(x.alumno)}</h3><span class="amt">Bs ${fmtBs(x.neto)}</span></div>
        <div class="exc-meta">${fmtD(x.fecha)} · ${esc(x.metodo || "sin método")}${x.codigo_luka ? ` · LUKA ${esc(x.codigo_luka)}` : ""}${x.intento_luka ? ` · intento ${esc(x.intento_luka)}` : ""}${x.codigo_estudiante ? ` · ${esc(x.codigo_estudiante)}` : ""}</div>
        <div class="exc-why"><b>Motivo:</b> ${esc(x.motivo)}</div>
        ${dec ? `<p class="tag-ok">Decisión registrada: asignación ${esc(dec.asignacion)}. Pulsa «Reprocesar con decisiones».</p>` : ""}
        ${props}
        <div class="manual-title">Registrar manualmente</div>
        <form class="manual" data-manual="${x.factura}">
          <label>Asignación<input name="asignacion" required placeholder="3P…"></label>
          <label>Fecha banco<input name="fecha_banco" type="date"></label>
          <label>Monto banco<input name="monto_banco" inputmode="decimal" placeholder="${x.neto}"></label>
          <label>Nota<input name="nota" placeholder="Quién depositó, referencia…"></label>
          <button class="btn sm" type="submit">Registrar</button>
        </form>
      </article>`;
    }).join("");
  }

  $("#paneExc").addEventListener("click", (e) => {
    const b = e.target.closest("[data-approve]");
    if (!b) return;
    const x = state.result.excepciones.find((v) => v.factura === +b.dataset.approve);
    const p = x.propuestas[+b.dataset.k];
    if (p.diferencia && !confirm(`El abono es Bs ${fmtBs(p.monto)} y la factura Bs ${fmtBs(x.neto)}. Diferencia Bs ${fmtBs(p.diferencia)}.\nSe registrará la diferencia y el asiento no se liberará hasta su ajuste. ¿Aprobar?`)) return;
    addDecision({ factura: x.factura, asignacion: p.asignacion, fecha_banco: p.fecha, monto_banco: p.monto, nota: `Propuesta aprobada: ${p.motivo}` });
  });
  $("#paneExc").addEventListener("submit", (e) => {
    const f = e.target.closest("[data-manual]");
    if (!f) return;
    e.preventDefault();
    const d = Object.fromEntries(new FormData(f));
    const raw = String(d.monto_banco || "").trim();
    const monto = raw ? parseFloat(raw.includes(",") ? raw.replace(/\./g, "").replace(",", ".") : raw) : null;
    addDecision({ factura: +f.dataset.manual, asignacion: d.asignacion.trim(), fecha_banco: d.fecha_banco || null, monto_banco: Number.isFinite(monto) ? monto : null, nota: d.nota || "Confirmación manual" });
  });

  function addDecision(d) {
    if (state.decisiones.some((x) => x.asignacion.toUpperCase() === d.asignacion.toUpperCase() && x.factura !== d.factura)) {
      alert(`La asignación ${d.asignacion} ya está decidida para otra factura.`); return;
    }
    state.decisiones = state.decisiones.filter((x) => x.factura !== d.factura).concat(d);
    renderDecisions(); renderExc(state.result);
  }
  function renderDecisions() {
    const box = $("#decisionsBox");
    box.hidden = !state.decisiones.length;
    $("#decisionsList").innerHTML = state.decisiones.map((d) => `<li>F-${d.factura} → ${esc(d.asignacion)}<button title="Quitar" data-undo="${d.factura}">✕</button></li>`).join("");
  }
  $("#decisionsList").addEventListener("click", (e) => {
    const u = e.target.closest("[data-undo]");
    if (!u) return;
    state.decisiones = state.decisiones.filter((d) => d.factura !== +u.dataset.undo);
    renderDecisions(); if (state.result) renderExc(state.result);
  });

  // pestañas
  $("#tabs").addEventListener("click", (e) => {
    const t = e.target.closest("[data-tab]");
    if (!t) return;
    $$("#tabs button").forEach((b) => b.setAttribute("aria-selected", b === t));
    $$(".tabpanes [data-pane]").forEach((p) => { p.hidden = p.dataset.pane !== t.dataset.tab; });
  });

  refresh();
})();
