# -*- coding: utf-8 -*-
"""Sincroniza el catalogo de LUNARIA (pijamas) desde su proveedor y actualiza:
  - catalogo.js  : productos curados (con galerias y variantes) para la tienda
  - 1 Excel      : catalogo completo del proveedor (Sublimados Majestic)

Fuente (publica):
  - Sublimados Majestic -> Supabase REST (publishable key del bundle publico)

LUNARIA es la tienda de pijamas del grupo (linea interna `l2`): un catalogo
por repositorio. Las demas lineas (joyas, juguetes, bebe, urbana) viven en
sus propios repositorios y NO se sincronizan aqui.

Ejecutar:  python scripts/sync_catalogos.py   (sin argumentos; escribe en la raiz del repo)
Cron:      .github/workflows/sync-catalogos.yml (cada 6 horas + manual)
"""
import hashlib
import io
import json
import os
import re
import sys
import time
import html as htmlmod
import urllib.request
import urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
PEQ = {"de", "del", "la", "el", "los", "las", "y", "con", "para", "en", "x", "por", "al", "un", "una"}

# ============================================================================
# Utilidades de red y texto
# ============================================================================

def get(url, headers=None, intentos=3):
    h = dict(UA)
    if headers:
        h.update(headers)
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            if i == intentos - 1:
                print("  ! fallo", url[:90], str(e)[:90])
                return ""
            time.sleep(2)

def get_json(url, headers=None):
    txt = get(url, headers)
    return json.loads(txt) if txt else {}

def get_bin(url, intentos=3):
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers=dict(UA))
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:
            if i == intentos - 1:
                print("  ! fallo bin", url[:80], str(e)[:80])
                return None
            time.sleep(1.5)

def limpiar_nombre(s):
    s = re.sub(r"\s+", " ", (s or "")).strip()
    s = re.split(r"\s*\|\s*", s)[0].strip()
    s = re.sub(r"\s*Ref\.?\s*[\w\-]+", "", s, flags=re.I).strip()
    return s

def titulo(s):
    s = limpiar_nombre(s)
    out = []
    for w in s.split(" "):
        if any(c.islower() for c in w):
            out.append(w)
        elif w.lower() in PEQ:
            out.append(w.lower())
        else:
            out.append(w[0] + w[1:].lower())
    return " ".join(out)

def plano(s):
    s = re.sub(r"<[^>]+>", " ", htmlmod.unescape(s or ""))
    return re.sub(r"\s+", " ", s).strip()

def js_str(s):
    return json.dumps(s, ensure_ascii=False)

# ============================================================================
# 1. DESCARGA
# ============================================================================

def descargar_majestic():
    """Sublimados Majestic (pijamasalmayor.com): Supabase REST con publishable key."""
    KEY = "sb_publishable_-6hv7O7DhudWC7NAW8izOw_PAc8hPre"
    SB = "https://dowbsbxvxjzjjhyqmyfr.supabase.co/rest/v1/productos"
    HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}
    out, desde = [], 0
    while True:
        d = get_json(SB + "?select=*&tenant_id=eq.sublimados_majestic&order=created_at.desc&limit=1000&offset=%d" % desde, HDR)
        if not isinstance(d, list) or not d:
            break
        out.extend(d)
        if len(d) < 1000:
            break
        desde += 1000
    return out

# ============================================================================
# 2. CURACION (seleccion para la tienda) + VARIANTES
# ============================================================================

def parse_tallas(s):
    if not s:
        return None
    s = str(s).strip()
    if s.lower() in ("unica", "única", "talla única", "unitalla"):
        return None
    partes = [x.strip() for x in s.split(",") if x.strip()]
    return partes if len(partes) > 1 else None

def parse_estampados(s):
    """'PIOLIN, GATO ROSA, MY MELODDY' -> ['Piolin', 'Gato Rosa', ...] (max 8, sin duplicados).
    Se descartan valores puramente numericos: en algunos productos el proveedor
    guarda referencias (ej. 1003558423) en lugar de nombres de estampado."""
    if not s:
        return None
    vistos, out = set(), []
    for x in str(s).split(","):
        x = titulo(x)
        if x and not x.isdigit() and any(c.isalpha() for c in x) and x.lower() not in vistos:
            vistos.add(x.lower())
            out.append(x)
    return out[:8] if len(out) > 1 else None

def curar_moda_majestic(items):
    """Curacion de Sublimados Majestic: precios 18k-110k, con tallas y
    estampados, y CLASIFICACION por nombre en categorias de tienda (la
    'categoria' del proveedor viene muy sucia: 'shortiras', 'familiar',
    'shorts' vs 'Short Dama', 'Sin categoria'...)."""
    GENERICOS = {"conjunto", "body", "shorts", "pijama pink", "pijama"}
    # Typos visibles al cliente: se corrigen aqui y la preservacion de ids
    # es tolerante (norm_clave) para no romper enlaces de pedidos viejos.
    FIXES = [("CORSERT", "CORSET"), ("BODDY", "BODY")]
    # Pijamas de FAMILIA: nombres de tienda por articulo del proveedor
    NOMBRES_FAMILIAR = {
        "PIJAMAS FAMILIARES": "Pijama Familiar de Personajes",
        "PIJAMA FAMILIAR NAVIDEÑAS": "Pijama Familiar Navideña",
        "PIJAMA NAVIDAD FAMILIAR": "Pijama Familiar Grinch",
    }

    def nombre_limpio(nombre):
        n = re.sub(r"\s+", " ", (nombre or "")).strip().rstrip(".")
        for a, b in FIXES:
            n = n.replace(a, b)
        return n

    def clasificar_prenda(nombre):
        """Organiza el catalogo en 8 categorias de tienda a partir del
        nombre. Orden: temporada > ninos > pijamas/pareja > enterizos >
        conjuntos > interior > pantalones/trios > shorts > juanitas."""
        n = (nombre or "").upper()
        if re.search(r"NAVIDAD|NAVIDE|HALLOWEEN|GRINCH|SANTA\b", n):
            return "navidad"
        if re.search(r"NIÑO|NIÑA|NIÑOS|NIÑAS", n):
            return "ninos"
        if "PIJAMA" in n or "PAREJA" in n:
            return "pijamas"
        if "ENTERIZO" in n or "BATOLA" in n:
            return "enterizos"
        if re.search(r"CONJUNTO|CORSET|BODY|BLUSON|VESTIDO|CHAQUETA|EVILLA", n):
            return "conjuntos"
        if re.search(r"\bSET\b|LEVANTADORA", n):
            return "interior"
        if "PANTALON" in n or "CAPRI" in n or "TRIO" in n:
            return "pantalones"
        if "SHORT" in n or "BERMUDA" in n:
            return "shorts"
        if "JUANITA" in n:
            return "interior"
        return "moda"

    def candidato(p):
        if p.get("oculto"):
            return None
        precio = float(p.get("precio") or 0)
        if not (18000 <= precio <= 110000) or not p.get("imagen_url"):
            return None
        nombre = nombre_limpio(p.get("nombre"))
        if "(Copia)" in nombre or not nombre or limpiar_nombre(nombre).lower() in GENERICOS:
            return None
        return p

    def con_datos(p, nombre=None, precio=None, var_extra=None):
        # nombre explicito (prendas de familia): ya viene formateado, NO se
        # re-titula para no arruinar etiquetas como "2XL Unisex"
        nombre = (titulo(nombre_limpio(p.get("nombre"))) if nombre is None else nombre)
        tallas = parse_tallas(p.get("tallas"))
        var = {}
        if tallas:
            var["Talla"] = tallas
        est = parse_estampados(p.get("estampados"))
        if est:
            var["Estampado"] = est
        if var_extra:
            var.update(var_extra)
        extras = p.get("imagenes_extra")
        urls = []
        if isinstance(extras, list):
            urls = [x for x in extras if isinstance(x, str)]
        elif isinstance(extras, str) and extras.strip():
            try:
                j = json.loads(extras)
                urls = [x for x in j if isinstance(x, str)] if isinstance(j, list) else []
            except Exception:
                urls = []
        gal = []
        for u in urls:
            u = str(u).split("|")[0].strip()
            if u.startswith("http") and u != p["imagen_url"] and u not in gal:
                gal.append(u)
        ref = str(p.get("referencia") or "").strip()
        return {"nombre": nombre, "precio": int(float(precio if precio is not None else (p.get("precio") or 0))),
                "imgs": [p["imagen_url"]] + gal[:3],
                "cat": clasificar_prenda(nombre),
                "var": (var if var else None), "sku": (ref if ref else None)}

    def prendas_familiares(p):
        """Pijamas de FAMILIA: el proveedor las publica con precio placeholder
        ($3) pero la tarjeta trae el precio REAL POR PRENDA en precios_familia
        (dama, dama plus, caballero, 2XL unisex y nino con tallas 2/4 a 14/16).
        Se expande en un producto por prenda con su precio y sus tallas,
        respetando las opciones deshabilitadas de cada tarjeta."""
        pf = p.get("precios_familia") or {}
        if not isinstance(pf, dict):
            return []
        pt = pf.get("precios_tallas") or {}
        # opciones_deshabilitadas: llegaba como string y desde oct-2026 como
        # lista JSON; se normaliza a un solo texto en minusculas.
        des = pf.get("opciones_deshabilitadas")
        raw_des = (" ".join(str(v) for v in des) if isinstance(des, (list, tuple)) else str(des or "")).lower()
        # tallas de nino: las entradas de precios_tallas que NO son de adulto
        # ("Dama Unica", "Caballero Unica", "2XL Unisex"...). El proveedor
        # etiqueta las tallas de nino como "2/4".."14/16" y (oct-2026) "18".
        def _orden_talla(t):
            m = re.match(r"\s*(\d+)", str(t))
            return (int(m.group(1)) if m else 999, str(t))
        tallas_nino = sorted([t for t in pt
                              if not any(a in str(t).lower() for a in ("dama", "caballero", "2xl", "unisex", "plus"))],
                             key=_orden_talla)
        precio_nino = 0
        for t in tallas_nino:
            try:
                precio_nino = max(precio_nino, float(pt.get(t) or 0))
            except Exception:
                pass
        plan = [
            ("Dama", pf.get("dama_unica"), ["Única"]),
            ("Dama Plus", pf.get("dama_plus"), ["Plus"]),
            ("Caballero", pf.get("caballero_unica") if pf.get("caballero_unica") is not None else pf.get("hombre"), ["Única"]),
            ("2XL Unisex", pf.get("unisex_2xl"), ["2XL"]),
            ("Niño", precio_nino or None, tallas_nino),
        ]
        # Opciones deshabilitadas: match EXACTO por etiqueta de la tarjeta
        # ("dama" NO puede caer dentro de "dama plus" ni "18" dentro de nada)
        DES_HASTA = {"Dama": ["dama única"], "Dama Plus": ["dama plus"], "Caballero": ["caballero"],
                     "2XL Unisex": ["2xl unisex", "2xl"], "Niño": []}
        clave = nombre_limpio(p.get("nombre")).upper().strip()
        base = NOMBRES_FAMILIAR.get(clave) or titulo(nombre_limpio(p.get("nombre")))
        out = []
        for miembro, precio, tallas in plan:
            if not precio:
                continue
            if any(x in raw_des for x in DES_HASTA[miembro]):
                continue
            if miembro == "Niño" and tallas and all(t.lower() in raw_des for t in tallas):
                continue
            try:
                precio = int(float(precio))
            except Exception:
                continue
            if precio <= 0:
                continue
            var_extra = {"Talla": tallas} if tallas else {"Talla": ["Única"]}
            d = con_datos(p, nombre="%s · %s" % (base, miembro), precio=precio, var_extra=var_extra)
            if d:
                out.append(d)
        return out

    # TODOS los validos (sin tope por categoria). Las pijamas de familia se
    # PUBLICAN SIEMPRE expandidas por prenda con el precio real de cada una
    # (README 2.3): el proveedor las publico con precio placeholder y desde
    # oct-2026 tambien con precio real en el item padre (36k/59k); en ambos
    # esquemas el padre generico no sale: el precio correcto es el de cada
    # prenda. Excepcion: "PIJAMA NAVIDEÑA DE PAREJA" queda como conjunto de
    # 2 prendas (kit de pareja con su propio precio).
    elegidos = []
    for x in items:
        if x.get("oculto"):
            continue
        es_fam = (x.get("es_producto_familiar") and x.get("imagen_url") and (x.get("precios_familia") or {}))
        if es_fam and nombre_limpio(x.get("nombre")).upper().strip() in NOMBRES_FAMILIAR:
            elegidos.extend(prendas_familiares(x))
            continue
        c = candidato(x)
        if c:
            elegidos.append(con_datos(x))
        elif es_fam:
            elegidos.extend(prendas_familiares(x))
    elegidos = [p for p in elegidos if p and len(p.get("nombre") or "") >= 6]
    elegidos.sort(key=lambda x: -x["precio"])
    return elegidos

# ============================================================================
# 3. ESCRITURA: catalogo.js y Excel
# ============================================================================

def norm_clave(nombre):
    """Clave de preservacion de ids/cids TOLERANTE a correcciones de
    nombre: los typos corregidos (Corsert->Corset, Boddy->Body) y el
    punto final suelto mantienen su id y su Cat permanente, asi los
    enlaces de pedidos viejos (?art=) y la curacion del heroe/favoritos
    no se rompen."""
    n = (nombre or "").lower().strip().rstrip(".")
    for a, b in (("corsert", "corset"), ("boddy", "body")):
        n = n.replace(a, b)
    return n


def escribir_catalogo_js(secciones):
    """secciones: [(prefijo, categoria, proveedor, [productos])] -> catalogo.js con ids ESTABLES.
    Los ids se reutilizan del catalogo.js anterior (clave: prefijo + nombre
    normalizado en minusculas), asi el heroe, los favoritos y los precios
    fijos del admin no se rompen cuando cambian precios, el orden o se
    corrigen typos del proveedor. Respeta la categoria POR PRODUCTO cuando
    la curacion la trae (clasificacion de Majestic)."""
    # RESTAURACION: al corregirle el punto final del nombre, el Pantalon
    # Bolero Tanga perdio su id m30 y su Cat LUN-0030 (la clave de nombre
    # dejo de coincidir). Se restauran para que los favoritos, los precios
    # fijos del admin y los enlaces de pedidos viejos (?art=LUN-0030)
    # sigan apuntando al mismo producto. m87/LUN-0103 fueron suyos durante
    # unas horas y quedan QUEMADOS: ningun producto nuevo puede heredar
    # enlaces o favoritos ajenos.
    ID_FIJOS = {("m", "pantalon bolero tanga"): 30}
    CID_FIJOS = {("m", "pantalon bolero tanga"): 30}
    QUEMADOS_ID = {("m", 87)}
    QUEMADOS_CID = {103}
    previos = {}
    usados = {}
    previos_cid = {}
    usados_cid = set(QUEMADOS_CID)
    # numeros que ID_FIJOS devuelve a su dueno original: nadie mas puede
    # heredarlos por nombre desde el catalogo previo (el m30 vuelve al
    # Pantalon: la prenda que lo heredo por error debe soltarlo y recibir
    # numero fresco, pues no tiene historial propio)
    FIJOS_NUM = set(ID_FIJOS.values())
    FIJOS_CID_NUM = set(CID_FIJOS.values())
    # numeros restaurados y quemados jamas se reemiten
    for (pre, _), num in ID_FIJOS.items():
        usados.setdefault(pre, set()).add(num)
    for pre, num in QUEMADOS_ID:
        usados.setdefault(pre, set()).add(num)
    try:
        with open(os.path.join(RAIZ, "catalogo.js"), encoding="utf-8") as f:
            texto_previo = f.read()
            for mm in re.finditer(r'\{id:"([a-z]+)(\d+)",n:"((?:[^"\\]|\\.)*)"', texto_previo):
                previos[(mm.group(1), norm_clave(mm.group(3)))] = int(mm.group(2))
                usados.setdefault(mm.group(1), set()).add(int(mm.group(2)))
            for mm in re.finditer(r'cid:"LUN-(\d+)"', texto_previo):
                usados_cid.add(int(mm.group(1)))
            for mm in re.finditer(r'\{id:"([a-z]+)\d+",n:"((?:[^"\\]|\\.)*)"[^}]*?cid:"LUN-(\d+)"', texto_previo):
                previos_cid[(mm.group(1), norm_clave(mm.group(2)))] = int(mm.group(3))
    except Exception:
        pass

    def num_libre(prefijo):
        s = usados.setdefault(prefijo, set())
        n = 1
        while n in s:
            n += 1
        s.add(n)
        return n

    def cid_libre():
        n = 1
        while n in usados_cid:
            n += 1
        usados_cid.add(n)
        return n

    lineas = []
    lineas.append("// ======================================================================")
    lineas.append("// catalogo.js de LUNARIA - generado automaticamente por scripts/sync_catalogos.py")
    lineas.append("// (%s). NO editar a mano: el cron de GitHub Actions lo regenera." % time.strftime("%Y-%m-%d %H:%M"))
    lineas.append("// Fuentes: inventario propio de la marca (gestión interna de LUNARIA)")
    lineas.append("// ======================================================================")
    lineas.append("const CATALOGO_LUNARIA=[")
    total = 0
    for prefijo, cat, prov, items in secciones:
        lineas.append("/* %s: %d productos */" % (cat, len(items)))
        claves = set()
        claves_cid = set()
        for p in items:
            clave = (prefijo, norm_clave(p["nombre"]))
            if clave in ID_FIJOS:
                num = ID_FIJOS[clave]
                usados.setdefault(prefijo, set()).add(num)
            elif clave in previos and clave not in claves and previos[clave] not in FIJOS_NUM:
                num = previos[clave]
            else:
                num = num_libre(prefijo)
            claves.add(clave)
            if clave in CID_FIJOS:
                cid_num = CID_FIJOS[clave]
                usados_cid.add(cid_num)
            elif clave in previos_cid and clave not in claves_cid and previos_cid[clave] not in FIJOS_CID_NUM:
                cid_num = previos_cid[clave]
                usados_cid.add(cid_num)
            else:
                cid_num = cid_libre()
            claves_cid.add(clave)
            partes = ['{id:"%s%02d"' % (prefijo, num), "n:%s" % js_str(p["nombre"]), "p:%d" % p["precio"], 'cat:"%s"' % (p.get("cat") or cat), 'prov:"%s"' % prov, 'cid:"LUN-%04d"' % cid_num]
            imgs = p.get("imgs") or []
            if imgs:
                partes.append("img:%s" % js_str(imgs[0]))
                if len(imgs) > 1:
                    partes.append("imgs:[%s]" % ",".join(js_str(x) for x in imgs[1:4]))
            if p.get("var"):
                var = p["var"]
                partes.append("var:{%s}" % ",".join("%s:[%s]" % (js_str(g), ",".join(js_str(v) for v in vals)) for g, vals in var.items()))
            if p.get("sku"):
                partes.append("sku:%s" % js_str(p["sku"]))
            if p.get("antes") and p["antes"] > p["precio"]:
                partes.append("antes:%d" % p["antes"])
            lineas.append(",".join(partes) + "},")
            total += 1
    lineas.append("];")
    # Guarda-red: si el proveedor cayo o la conexion fallo a medias, NO
    # destruir el catalogo vigente (protege ids/cids estables y la tienda).
    if previos and total < len(previos) * 0.5:
        print("  ! ABORTADO: %d productos vs %d previos (descarga parcial): se conserva el catalogo vigente." % (total, len(previos)))
        return 0
    with open(os.path.join(RAIZ, "catalogo.js"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lineas) + "\n")
    print("catalogo.js: %d productos" % total)
    return total

def escribir_excel(archivo, hojas):
    """hojas: [(titulo, headers, filas, anchos, cols_cop, resumen)]"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter
    thin = Border(bottom=Side(style="thin", color="E9D9C8"))
    for titulo, headers, filas, anchos, cols_cop, resumen in hojas:
        wb = Workbook()
        ws = wb.active
        ws.title = titulo
        ws.append(headers)
        for c in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=c)
            cell.font = Font(name="Montserrat", bold=True, color="FFF9F2", size=11)
            cell.fill = PatternFill("solid", fgColor="4B4141")
            cell.border = thin
        for f in filas:
            ws.append(f)
        last = ws.max_row
        for row in ws.iter_rows(min_row=2, max_row=last):
            for cell in row:
                cell.border = thin
                cell.font = Font(name="Calibri", size=10)
        for col in cols_cop:
            for r in range(2, last + 1):
                ws.cell(row=r, column=col).number_format = '"$"#,##0'
        for i, w in enumerate(anchos, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = "A1:%s%d" % (get_column_letter(len(headers)), last)
        if resumen:
            rs = wb.create_sheet("Resumen")
            rs.append(["Resumen — " + titulo])
            rs["A1"].font = Font(name="Montserrat", bold=True, size=13)
            for linea in resumen:
                rs.append(linea)
            for c in range(1, 5):
                cel = rs.cell(row=3, column=c)
                cel.font = Font(bold=True, color="FFF9F2")
                cel.fill = PatternFill("solid", fgColor="4B4141")
            for r in range(4, rs.max_row + 1):
                if "COP" in str(rs.cell(row=r, column=1).value or ""):
                    rs.cell(row=r, column=2).number_format = '"$"#,##0'
            for i, w in enumerate([40, 16, 16, 16], 1):
                rs.column_dimensions[get_column_letter(i)].width = w
        wb.save(os.path.join(RAIZ, archivo))
        print("%s: %d filas" % (archivo, len(filas)))

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("== Descargando proveedor (pijamas) ==")
    majestic = descargar_majestic()
    print("  majestic:", len(majestic))

    print("== Curando seleccion de la tienda ==")
    moda = curar_moda_majestic(majestic)
    print("  pijamas=%d" % len(moda))

    # --- Marca unica: rehostear imagenes cuyo dominio delata al proveedor.
    #     Incremental: solo descarga las que falten en img/p/ (hash del URL).
    #     Las fotos de Majestic (Supabase) son ORIGINALES del proveedor
    #     (100-200 KB para casillas de 235px): se rehospedan REDIMENSIONADAS
    #     a webp (~600px, 40-80 KB). Pillow la genera; el hash del URL
    #     original mantiene todo incremental.
    carpeta = os.path.join(RAIZ, "img", "p")
    os.makedirs(carpeta, exist_ok=True)

    def rehost_una(original, redimensionar):
        h = hashlib.md5(original.encode()).hexdigest()[:16]
        dest = os.path.join(carpeta, h + ".webp")
        if not os.path.exists(dest):
            data = get_bin(original)
            if not data:
                return None
            if redimensionar:
                try:
                    from io import BytesIO
                    from PIL import Image
                    im = Image.open(BytesIO(data))
                    im = im.convert("RGB") if im.mode != "RGB" else im
                    im.thumbnail((640, 800))
                    im.save(dest, "WEBP", quality=78, method=6)
                except Exception:
                    with open(dest, "wb") as f:
                        f.write(data)
            else:
                with open(dest, "wb") as f:
                    f.write(data)
        return "img/p/" + h + ".webp"

    def rehost_imgs(items, redimensionar=False):
        n = 0
        for x in items:
            nuevas = []
            for u in x.get("imgs") or []:
                if not u:
                    continue
                if redimensionar and "supabase" in u:
                    original, red = u, True
                else:
                    nuevas.append(u)
                    continue
                nueva = rehost_una(original, red)
                if not nueva:
                    nuevas.append(u)
                    continue
                nuevas.append(nueva)
                n += 1
            x["imgs"] = nuevas
        if n:
            print("  rehost: %d imagenes locales%s" % (n, " (redimensionadas a webp)" if redimensionar else ""))
        return items

    moda = rehost_imgs(moda, redimensionar=True)

    print("== catalogo.js ==")
    escribir_catalogo_js([
        ("m", "moda", "l2", moda),
    ])

    print("== Excel del proveedor ==")
    # --- Majestic ---
    def extra_n(v):
        if isinstance(v, list):
            return len(v)
        if isinstance(v, str) and v.strip():
            try:
                return len(json.loads(v))
            except Exception:
                return 1
        return 0
    filas = []
    for p in sorted(majestic, key=lambda x: (x.get("categoria") or "Sin categoría", -(x.get("precio") or 0))):
        filas.append([p.get("id", ""), p.get("referencia") or "", re.sub(r"\s+", " ", p.get("nombre") or "").strip(),
                      p.get("categoria") or "Sin categoría", p.get("subcategoria") or "", p.get("tallas") or "",
                      p.get("precio"), p.get("precio_por_mayor"), p.get("precio_50_unidades"), p.get("costo"),
                      p.get("stock"), "Sí" if p.get("oculto") else "No", p.get("estampados") or "",
                      plano(p.get("descripcion"))[:400], p.get("imagen_url") or "", extra_n(p.get("imagenes_extra"))])
    escribir_excel("Sublimados_Majestic_Catalogo.xlsx", [(
        "Catálogo",
        ["ID", "Referencia", "Nombre", "Categoría", "Subcategoría", "Tallas", "Precio (COP)", "Precio por mayor",
         "Precio 50 und.", "Costo", "Stock", "Oculto", "Estampados", "Descripción", "URL imagen", "N.º imágenes extra"],
        filas, [38, 12, 44, 22, 14, 18, 13, 15, 14, 11, 8, 8, 30, 46, 70, 12], (7, 8, 9, 10),
        [["Métrica", "Valor"], ["Total de productos", len(filas)],
         ["Ocultos", sum(1 for f in filas if f[11] == "Sí")],
         ["Fecha de extracción", time.strftime("%Y-%m-%d %H:%M")]])])

    print("== Sincronización completa ==")
