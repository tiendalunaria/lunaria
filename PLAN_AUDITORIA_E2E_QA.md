# LUNARIA — Plan de Auditoría E2E y QA

**Versión:** 1.0 · **Fecha:** octubre 2026 · **Alcance:** todo el sistema publicado
(https://tiendalunaria.github.io/lunaria/) y su pipeline.

> Objetivo: garantizar que la tienda venda bien, cobre bien y no se caiga.
> Prioridad de riesgos: (1) cobrar mal, (2) catálogo roto, (3) pedido no llega
> por WhatsApp, (4) tienda caída, (5) daño de imagen legal/visual.

---

## 1. Alcance de la auditoría

| # | Componente | Archivo(s) | Riesgo principal |
|---|---|---|---|
| 1 | Tienda (catálogo, precios, carrito, checkout, WhatsApp) | `index.html` + `catalogo.js` | Cobrar mal / pedido incompleto |
| 2 | Panel de administración | `index.html` (sección admin) | Publicar configuración corrupta; fuga de token/clave |
| 3 | Publicación por API | fetch a Contents API (`data/configuracion.js`) | Sobreescribir el cron; claves en el repo |
| 4 | Cron de sincronización | `scripts/sync_catalogos.py` + workflow | Proveedor caído → tienda vacía; IDs cambiados → pedidos viejos rotos |
| 5 | Catálogo y datos | `catalogo.js`, `data/configuracion.js`, Excel | Precios con margen equivocado; imágenes rotas |
| 6 | Legales | `legal.html` | Datos legales desactualizados; config no absorbida |
| 7 | Marca y activos | logos, favicons, banner, QR | Recurso 404; logo viejo en cualquier superficie |
| 8 | No funcionales | móvil, a11y, performance, SEO, seguridad | Venta perdida en celular; penalización Google |

---

## 2. Niveles de prueba (L0 → L5)

### L0 — Estático (cada commit, ~1 min)
- HTML válido: sin atributos mal cerrados (lección del bug de comillas del héroe:
  `style="…" "Cormorant Garamond"…` rompía el atributo sin romper la página).
- `node --check` sobre JS inline extraído y sobre `catalogo.js`.
- Todos los recursos locales existen: `logo_120.png`, `logo_512*.png`,
  `favicon*`, `apple-touch-icon.png`, `banner_pijamas_1600x600.png`, `qr_lunaria.png`.
- Cero referencias a la marca vieja: grep `322D5B|B9A5F5|F7F4FC|E6DFF3|6A6480|Quicksand|Nunito|Noches suaves, sueños felices`
  debe dar 0 en `index.html`/`legal.html` (en MDs solo permitido como línea secundaria).
- Secretos: `git ls-files` NO contiene `GitHub.txt`, `Gmail.txt`, tokens `github_pat_…`.

### L1 — Pipeline del sync (cada cambio del script + 1 vez por semana)
Corrida local en seco antes de publicar cambios del pipeline:
```
python scripts/sync_catalogos.py          # compara contra el catalogo.js vigente
```
Verificaciones:
- [ ] Total de productos ≥ 90% del vigente (el guarda-red del script aborta < 50%; la auditoría es más estricta a propósito).
- [ ] IDs `mNN` y códigos `LUN-XXXX` de los 20 favoritos + 6 del héroe SIN CAMBIOS (diff del `catalogo.js` anterior).
- [ ] Ningún número `LUN-` reutilizado: nuevos códigos no existen en el histórico del repo.
- [ ] Precios: `venta == ceil(base×1.6 /1000)×1000` para los 99 (fuera de temporada).
- [ ] Sin precios placeholder ($3) en el catálogo final; familias expandidas con precio real por prenda.
- [ ] Excel regenerado: cabecera chocolate `#4B4141`, hojas "Catálogo" y "Resumen", fecha de extracción de hoy.
- [ ] Imágenes: toda `img/p/*.webp` referenciada existe; 0 URLs externas en `catalogo.js`.
- [ ] Prueba de fallo simulada: desconexión a mitad de descarga → el script debe abortar y conservar el catálogo vigente.

### L2 — Tienda E2E local (cada cambio funcional de `index.html`)
Suite existente: `node qa_aterrizaje_precios.js` (ajustar rutas del checkout local).
Cubre: 20 favoritos, carruseles por categoría, héroe, buscador (sin tildes/ñ,
`LUN-XXXX`, SKU), `?art=` de alistamiento, precios de los 99, matemática de
carrito, mensaje WhatsApp con total exacto, hoja de pedido PNG.
Complementos NUEVOS (a incorporar a la suite):
- [ ] **Checkout por fases completo**: pedido → datos → entrega → pago → notas;
  validación en vivo (teléfono colombiano, dirección, ciudad); consecutivo
  `PED-YYYYMMDD-NNN` secuencial en el mismo día.
- [ ] **Persistencia**: carrito y favoritos sobreviven recarga (localStorage).
- [ ] **Lightbox**: navegación prev/next, contador, cierre con Escape.
- [ ] **Móvil (viewport 360×740)**: menú móvil abre/cierra, subnav con snap,
  barra de pago visible con carrito lleno, botón WhatsApp flotante, héroe oculto.
- [ ] **Estados de error**: foto rota → cadena de respaldo (galería → placeholder);
  catálogo vacío de una categoría → mensaje, no pantalla en blanco.
- [ ] **Marquesina y badge**: sin saltos de layout; badge con rebote respeta `prefers-reduced-motion`.

### L3 — Panel E2E + publicación (cada cambio del panel)
Suite existente: `node qa_admin_e2e.js` (login A1–A7, identidad B1–B6, precios
C0–C6, héroe/favoritos D0–D6…). Complementos NUEVOS:
- [ ] **Publicar para TODOS** contra un **repositorio de pruebas** (fork/rama),
  nunca contra producción durante la auditoría: verificar `data/configuracion.js`
  resultante con `version` creciente y **sin `claveAdmin` ni token** (grep).
- [ ] Token guardado SOLO en localStorage del navegador de prueba; borrado con "Salir".
- [ ] Enlace de configuración de un toque: abre, carga y no filtra el token en la URL del historial.
- [ ] Absorción panel↔cron: publicar por API mientras un commit del cron entra → el
  `pull --rebase` del workflow absorbe sin conflicto (simular con 2 commits).

### L4 — Producción (smoke después de cada deploy + 1 vez/día)
Contra https://tiendalunaria.github.io/lunaria/ (solo lectura, sin comprar):
- [ ] HTTP 200 en `/`, `/catalogo.js`, `/data/configuracion.js`, `/legal.html` y los 7 activos de marca.
- [ ] `catalogo.js` parsea y conserva ≥ 90% del inventario elegible del proveedor (piso dinámico en vivo; el total fluctúa 88–101). Muestra de 10 precios correctos.
- [ ] Título y meta `og:` con el eslogan oficial; favicon carga (marca nueva).
- [ ] 20 imágenes de producto aleatorias: 0 rotas (HTTP 200).
- [ ] QR de la tarjeta apunta al dominio correcto.
- [ ] Deploy de Pages < 5 min después del push (Actions → pages-build-deployment success).

### L5 — No funcionales (1 vez por mes y antes de cada temporada)
- **Móvil real**: iPhone SE y Android gama media (Chrome): carrito, checkout, WhatsApp.
- **Accesibilidad**: contraste AA en rosa empolvado (`#3E3434` sobre `#C99BA6` = 5,0:1 ✓),
  foco visible, navegación por teclado del checkout completo, `aria-label` en iconos.
- **Performance Lighthouse (móvil)**: objetivo ≥ 85; imágenes webp ~46 KB ya optimizadas;
  fuentes con `display=swap`; héroe solo descarga en escritorio (lazy en móvil).
- **SEO**: `robots` en legal, schema.org OnlineStore, títulos únicos, sin dominios ajenos.
- **Seguridad**: token solo en navegador; `claveAdmin` nunca en `data/configuracion.js`
  ni en el HTML servido por encima del default; sin secretos en git (revisión L0).

---

## 3. Entornos y datos de prueba

| Entorno | URL / mecanismo | Uso |
|---|---|---|
| Local | `index.html` directo + `catalogo.js` vigente | L0–L3 |
| Staging | rama `qa/` con Pages de repositorio espejo | L3 (publicación real sin riesgo) |
| Producción | tiendalunaria.github.io/lunaria | L4 smoke (solo lectura) |
| Datos | WhatsApp de prueba `573001112222` (patrón de la suite A/B); clon del catálogo recortado a 10 ítems para iterar rápido | suites |

Reglas: nunca publicar a producción desde QA; nunca comprar real en pruebas;
el WhatsApp de pedidos real (573132434760) solo se valida leyendo el enlace
generado, no enviándolo.

---

## 4. Severidad y criterios de salida

| Sev | Definición | Ejemplo | Acción |
|---|---|---|---|
| S1 | Cobra mal o pierde pedidos | total del carrito errado; WhatsApp sin total; precio ≠ fórmula | Bloquea deploy |
| S2 | Catálogo/tienda rota para el usuario | catálogo < 95; imagen placeholder masiva; checkout no avanza | Bloquea deploy |
| S3 | Degradación visible sin pérdida | badge sin rebote; lightbox sin contador | Fix en 7 días |
| S4 | Cosmético | espaciado, tipografía menor | Backlog |

**Salida de la auditoría:** 0 × S1/S2 abiertos, ≥ 95% de checks PASS en L2/L3,
smoke L4 verde, y reporte firmado con fecha.

---

## 5. Calendario

| Momento | Qué corre |
|---|---|
| Cada push (pre-commit manual) | L0 completo |
| Cada cambio de `sync_catalogos.py` | L1 en seco |
| Cada cambio funcional de tienda/panel | L2 / L3 según corresponda |
| Diario (automatizable con workflow `qa-smoke.yml`) | L4 smoke de producción |
| Semanal (lunes) | L1 + revisión del run del cron de las 06:00 |
| Mensual | L5 no funcionales |
| **15-nov (antes de temporada)** | Auditoría completa L0–L5 + revisión de margen navidad 70% |

---

## 6. Reporte (plantilla por corrida)

```
Fecha / corrida:            Ejecutor:
L0 estático:        PASS/FAIL (detalle)
L1 pipeline:        productos ANTES=99 DESPUÉS=nn | IDs héroe/favoritos estables: SÍ/NO
L2 aterrizajes:     nn/nn PASS  | fallos:
L3 panel:           nn/nn PASS  | fallos:
L4 producción:      HTTP/precios/imágenes | deploy: min
L5 (si aplica):     Lighthouse móv=nn | a11y | contraste
Sev abiertas:       S1:[] S2:[] S3:[] S4:[]
Decisión:           PUBLICAR / NO PUBLICAR (motivo)
```

---

## 7. Backlog de automatización (orden sugerido)

1. ✅ **Hecho:** `qa_smoke_produccion.js` — L4 automático (23 checks: página,
   catálogo, configuración, imágenes, activos, deploy de Pages).
2. Ampliar `qa_aterrizaje_precios.js` con el bloque de checkout por fases y móvil (L2 nuevos).
3. Ampliar `qa_admin_e2e.js` con publicación a repositorio espejo (L3).
4. ✅ **Hecho:** workflow `qa-smoke.yml` diario (12:00 UTC) que corre L4 y
   abre/cierra issue automático con etiqueta `qa-smoke`.
5. Extracción del JS inline a `scripts/extraer_js.py` para `node --check` en L0.

---

## 8. Registro de corridas

| Fecha | Corrida | Resultado | Acción |
|---|---|---|---|
| 22-oct-2026 | **L4 smoke de producción** (`qa_smoke_produccion.js`, 23 checks) | **23/23 PASS** — producción sana | Automatizado con `qa-smoke.yml` (12:00 UTC) |
| 22-oct-2026 | **Auditoría de secretos** (tree + historial completo de git) | **0 fugas.** Tokens/credenciales ausentes en repo e historial; config publicada sin `claveAdmin` ni token; `.gitignore` cubre archivos locales. 2 hallazgos evaluados como aceptados: clave `sb_publishable_` del proveedor (pública por diseño) y clave de fábrica del panel en HTML (por diseño; publicar exige token, nunca en código) | Ninguna obligatoria; rotación de clave de fábrica opcional |
