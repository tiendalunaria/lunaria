/* QA EXHAUSTIVO: aterrizaje de tarjetas por cada via de entrada + matematica
   de precios (todos los productos vs catalogo) + matematica del carrito.
   Ejecutar:  node qa_aterrizaje_precios.js
   51 verificaciones: los 20 favoritos, primero y ultimo de cada carrusel de
   categoria, las 6 prendas del heroe, buscador y enlace ?art= aterrizan en
   SU tarjeta con el panel de cantidad abierto; todos los precios = base x 1.6
   redondeado a 100; carrito con lineas, unidades, totales, mensaje de
   WhatsApp y hoja de pedido exactos. */
const { chromium } = require("C:/Users/User/IKI/dropi-analytics/node_modules/playwright");

(async () => {
  const res = [];
  let grupo = "";
  const check = (n, c, e) => res.push(grupo + " | " + n + ": " + (c ? "PASS" : "FAIL" + (e !== undefined ? " -> " + JSON.stringify(e).slice(0, 220) : "")));
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await page.route("**/data/configuracion.js", r => { const u = new global.URL(r.request().url()); u.searchParams.set("cb", String(Date.now())); r.continue({ url: u.toString() }); });
  await page.goto("https://tiendalunaria.github.io/lunaria/?cb=" + Date.now(), { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForFunction(() => (window.PRODUCTOS || []).length > 0, { timeout: 60000 });
  await page.waitForTimeout(1500);

  /* ============ helper: activa una via de entrada y verifica el aterrizaje ============ */
  const aterriza = async (via, id, extra) => {
    const card = await page.evaluate(async (id) => {
      const p = prod(id);
      if (!p) return { error: "sin producto" };
      // dispara exactamente lo que la via de entrada dispara
      scrollToProduct(id);
      await new Promise(r => setTimeout(r, 2600));
      const c = document.getElementById("product-" + id);
      if (!c) return { error: "sin tarjeta en DOM" };
      const r = c.getBoundingClientRect();
      const vh = window.innerHeight;
      return {
        nombre: p.n,
        visible: r.top < vh - 60 && r.bottom > 70,
        panelAbierto: !!document.getElementById("q-" + id) && document.getElementById("q-" + id).classList.contains("open"),
        rectTop: Math.round(r.top), rectBottom: Math.round(r.bottom), vh,
      };
    }, id);
    check(via + " → " + (extra || id) + (card.nombre ? " (" + card.nombre.slice(0, 28) + ")" : ""), !card.error && card.visible && card.panelAbierto, card);
    return card;
  };

  /* ============ 1. FAVORITOS: los 20 items del carrusel ============ */
  grupo = "1-Favoritos";
  const favs = await page.evaluate(() => CONFIG.favoritosIds.filter(id => prod(id) && prodVisible(prod(id))));
  check("1.0 carrusel con " + favs.length + " favoritos visibles", favs.length === 20, favs.length);
  for (const id of favs) await aterriza("Fav", id);

  /* ============ 2. CARRUSELES DE CATEGORIA: primero y ultimo de cada fila ============ */
  grupo = "2-Carruseles";
  const filas = await page.evaluate(() => {
    const out = [];
    for (let i = 1; i <= 5; i++) {
      const label = document.getElementById("row" + i + "Label").textContent;
      const items = [...document.getElementById("row" + i).style.display !== "none" ? document.querySelectorAll("#car" + i + " .cari") : []];
      const ids = items.length ? [items[0], items[items.length - 1]].map(b => {
        const lbl = b.getAttribute("aria-label") || "";
        const p = PRODUCTOS.find(x => "Ver " + x.n === lbl);
        return p ? p.id : null;
      }) : [];
      out.push({ fila: label, ids });
    }
    return out;
  });
  for (const fila of filas) {
    check("2.x fila '" + fila.fila + "' con items", fila.ids.length > 0 && !fila.ids.includes(null), fila);
    for (const id of fila.ids) if (id) await aterriza("Carrusel " + fila.fila, id);
  }

  /* ============ 3. HEROE: las 6 prendas de temporada ============ */
  grupo = "3-Héroe";
  const heroIds = await page.evaluate(() => TIENDA.heroIds.split(",").map(s => s.trim()).filter(Boolean));
  check("3.0 heroe con 6 prendas", heroIds.length === 6, heroIds);
  for (const id of heroIds) await aterriza("Héroe", id);

  /* ============ 4. BUSCADOR ============ */
  grupo = "4-Buscador";
  await page.evaluate(() => { document.getElementById("searchInput").value = "grinch"; searchProducts(); });
  await page.waitForTimeout(400);
  const busca = await page.evaluate(() => {
    const b = document.querySelector("#searchResults .sri");
    const m = /scrollToProduct\('(.+?)'\)/.exec(b ? b.getAttribute("onclick") || "" : "");
    return m ? m[1] : null;
  });
  if (busca) {
    await page.click("#searchResults .sri");
    await aterriza("Buscador 'grinch'", busca);
  }

  /* ============ 5. ?art=LUN-XXXX (enlace de alistamiento) ============ */
  grupo = "5-?art";
  {
    const art = await page.evaluate(() => { const p = prod("m66"); return p ? p.cid : null; });
    const page2 = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    await page2.route("**/data/configuracion.js", r => { const u = new global.URL(r.request().url()); u.searchParams.set("cb", String(Date.now())); r.continue({ url: u.toString() }); });
    await page2.goto("https://tiendalunaria.github.io/lunaria/?cb=" + Date.now() + "&art=" + art, { waitUntil: "domcontentloaded", timeout: 90000 });
    await page2.waitForFunction(() => (window.PRODUCTOS || []).length > 0, { timeout: 60000 });
    await page2.waitForTimeout(3500);
    const c = await page2.evaluate((id) => {
      const el = document.getElementById("product-" + id);
      if (!el) return { error: "sin tarjeta" };
      const r = el.getBoundingClientRect();
      return { visible: r.top < innerHeight - 60 && r.bottom > 70, panel: document.getElementById("q-" + id).classList.contains("open"), top: Math.round(r.top) };
    }, "m66");
    check("5.1 ?art=" + art + " aterriza en Juanita 4 Piezas con panel abierto", c.visible && c.panel, c);
    await page2.close();
  }

  /* ============ 6. PRECIOS: los 99 visibles = round100(base × 1.6) ============ */
  grupo = "6-Precios";
  const precios = await page.evaluate(() => {
    const malos = [];
    let n = 0;
    const base = {};
    CATALOGO_BASE_LUNARIA.forEach(p => { base[p.id] = p.p; });
    PRODUCTOS.forEach(p => {
      if (!prodVisible(p)) return;
      n++;
      const esperado = Math.round(base[p.id] * 1.6 / 100) * 100;
      if (p.p !== esperado) malos.push({ id: p.id, n: p.n, esperado, real: p.p });
    });
    return { n, malos };
  });
  check("6.1 los " + precios.n + " productos visibles a base×1.6 redondeado a 100 (margen 60% fuera de temporada)", precios.n === 99 && precios.malos.length === 0, precios.malos.slice(0, 5));

  /* ============ 7. CARRITO: matematica completa ============ */
  grupo = "7-Carrito";
  const carrito = await page.evaluate(() => new Promise(done => {
    const r = {};
    vaciarCarrito();
    // 2x m44 (54400) + 1x m01 (161600) + 3x m98 Grinch Niño (45600)
    addToCart("m44", 2, null);
    addToCart("m01", 1, null);
    addToCart("m98", 3, null);
    const s = cartResumen();
    r.esperado = { items: 3, unidades: 6, total: 2 * 54400 + 161600 + 3 * 45600 };
    r.real = { items: cart.length, unidades: s.count, total: s.total };
    r.subtotalDrawer = document.getElementById("cartSubtotal").textContent;
    r.payTotal = document.getElementById("payTotal").textContent;
    r.payCount = document.getElementById("payCount").textContent;
    // stepper en tarjeta: cambiar cantidad de m44 a 4
    selQty["m44"] = 2; changeQty("m44", 2);
    r.stepper = document.getElementById("qs-m44").textContent;
    // pedido por WhatsApp: verificar el mensaje
    window.open = u => { r.waUrl = u; return {}; };
    const set = (id, v) => { const el = document.getElementById(id); el.value = v; el.dispatchEvent(new Event("input", { bubbles: true })); };
    set("customerName", "QA Matematica");
    set("customerPhone", "3001112222");
    const dep = document.getElementById("customerDept"); if (dep && dep.options.length > 1) dep.selectedIndex = 1;
    set("customerCity", "Bogota");
    set("customerAddress", "Calle QA 123");
    sendOrder();
    setTimeout(() => done(r), 700);
  }));
  const esperadoTotal = 2 * 54400 + 161600 + 3 * 45600;
  check("7.1 carrito: 3 lineas, 6 unidades, total $" + esperadoTotal.toLocaleString("es-CO"),
    carrito.real.items === 3 && carrito.real.unidades === 6 && carrito.real.total === esperadoTotal, carrito);
  check("7.2 stepper de tarjeta: 4x $54.400 = $217.600", carrito.stepper === "$217.600", carrito.stepper);
  const dec = decodeURIComponent(carrito.waUrl || "");
  const totalFmt = "$" + esperadoTotal.toLocaleString("es-CO").replace(/\u00a0/g, ".");
  check("7.3 mensaje WhatsApp con el TOTAL exacto (" + totalFmt + ")", dec.includes("TOTAL PRODUCTOS: " + totalFmt), dec.slice(-260));
  check("7.4 mensaje con lineas y c/u correctas", dec.includes("2 x Pijama en Satin") && dec.includes("3 x Pijama Familiar Grinch") && dec.includes("$54.400 c/u"), "");
  const hoja = await page.evaluate(() => new Promise(d => { crearHojaPedido("PED-QA").then(f => d({ size: f ? f.size : 0 })); }));
  check("7.5 hoja de pedido PNG generada con el resumen", hoja.size > 20000, hoja);

  await browser.close();
  const ok = res.filter(x => x.includes("PASS")).length;
  console.log(res.join("\n"));
  console.log("\n===== " + ok + "/" + res.length + " PASS =====");
  process.exit(ok === res.length ? 0 : 1);
})();
