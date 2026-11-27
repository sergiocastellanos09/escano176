#!/usr/bin/env python3
"""Regenera todo lo derivado de los datos de Escaño 176.

Se ejecuta desde la raíz del repositorio después de editar el JSON de index.html
o datos/provincias.json:

    python3 herramientas/publicar.py

Hace lo siguiente:
  1. Valida el JSON de index.html y copia "results" a datos/resultados.json
     (lo leen el pactómetro y otras páginas).
  2. Genera provincias.html y una página por provincia con resultados
     (provincias/<slug>.html) a partir de datos/provincias.json.
  3. Dibuja og.png, la imagen que se ve al compartir la web.
  4. Reescribe sitemap.xml.
Si algo no cuadra, termina con error y no hay que publicar.
"""
import datetime as dt
import html
import json
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://escano176.es"
ADS = '<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-5829947072696022" crossorigin="anonymous"></script>'
MADRID = dt.timezone(dt.timedelta(hours=1))
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def p(*parts):
    return os.path.join(ROOT, *parts)


def fail(msg):
    print("ERROR:", msg)
    sys.exit(1)


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def color(c):
    return c if isinstance(c, str) and COLOR_RE.match(c) else "#888888"


def num(n):
    return f"{int(n):,}".replace(",", ".")


def pct(n):
    return "—" if n is None else f"{float(n):.1f}".replace(".", ",") + " %"


# ---------- 1. Datos de la portada ----------
def read_site_data():
    s = open(p("index.html"), encoding="utf-8").read()
    blocks = re.findall(r'<script type="application/json" id="site-data">\s*(.*?)\s*</script>', s, re.S)
    if len(blocks) != 1:
        fail("index.html debe tener exactamente un bloque site-data")
    try:
        d = json.loads(blocks[0])
    except json.JSONDecodeError as e:
        fail(f"JSON de index.html no válido: {e}")
    r = d.get("results") or {}
    seats = sum(int(x.get("seats") or 0) for x in r.get("parties", []))
    if seats > 350:
        fail(f"los escaños suman {seats}, más de 350")
    return d


def fix_prev(d):
    """Frente Amplio es el heredero del espacio de Sumar: si el escrutinio no trae su
    comparación con 2023, se usa la de Sumar (31 escaños) y se anota en index.html."""
    r = d.get("results") or {}
    changed = False
    for x in r.get("parties", []):
        if x.get("name") == "Frente Amplio" and x.get("prev") is None and r.get("status") != "pending":
            x["prev"] = 31
            changed = True
    if changed:
        path = p("index.html")
        s = open(path, encoding="utf-8").read()
        m = re.search(r'(<script type="application/json" id="site-data">\s*)(.*?)(\s*</script>)', s, re.S)
        s = s[:m.start(2)] + json.dumps(d, ensure_ascii=False, indent=2) + s[m.end(2):]
        open(path, "w", encoding="utf-8").write(s)


def write_results(d):
    r = dict(d.get("results") or {})
    r["siteUpdated"] = d.get("updated")
    os.makedirs(p("datos"), exist_ok=True)
    with open(p("datos", "resultados.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    return r


# ---------- 1b. Contenido estático de la portada (para buscadores) ----------
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sept", "oct", "nov", "dic"]


def prerender_index(d):
    """Escribe titular, entradilla y noticias directamente en el HTML de index.html.
    El JavaScript de la página lo vuelve a dibujar igual al cargar; esto es para que
    Google y las vistas previas de enlaces vean el contenido sin ejecutar JavaScript."""
    path = p("index.html")
    s = open(path, encoding="utf-8").read()
    s2 = re.sub(r'(<h1 id="headline">).*?(</h1>)', lambda m: m.group(1) + esc(d.get("headline", "")) + m.group(2), s, count=1, flags=re.S)
    s2 = re.sub(r'(<p class="dek" id="dek">).*?(</p>)', lambda m: m.group(1) + esc(d.get("dek", "")) + m.group(2), s2, count=1, flags=re.S)
    items = []
    for n in sorted(d.get("news", []), key=lambda x: x.get("date", ""), reverse=True):
        try:
            y, mo, da = (int(x) for x in n["date"].split("-"))
            fecha = f"{da} {MESES[mo - 1]}"
        except Exception:
            fecha = esc(n.get("date", ""))
        url = n.get("url", "")
        src = (f'<a class="src" href="{esc(url)}">Fuente: {esc(n.get("source"))}</a>' if str(url).startswith("https://")
               else f'<span class="src">{esc(n.get("source"))}</span>')
        items.append(f'<article class="item"><time datetime="{esc(n.get("date"))}">{fecha}</time><div>'
                     + (f'<span class="tag">{esc(n.get("tag"))}</span>' if n.get("tag") else "")
                     + f'<h3>{esc(n.get("title"))}</h3><p>{esc(n.get("summary"))}</p>{src}</div></article>')
    s2 = re.sub(r'(<div class="news" id="news">).*?(</div>\s*</div>\s*<aside>)', lambda m: m.group(1) + "".join(items) + m.group(2), s2, count=1, flags=re.S)
    desc = d.get("dek", "")[:155]
    s2 = re.sub(r'(<meta name="description" content=")[^"]*(">)', lambda m: m.group(1) + esc(desc) + m.group(2), s2, count=1)
    if s2.count('id="site-data"') != 1:
        fail("prerender: index.html dañado")
    if s2 != s:
        open(path, "w", encoding="utf-8").write(s2)


# ---------- 2. Provincias ----------
HEAD = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{url}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="website">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{site}/og.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Cpath d='M3 26a13 13 0 0 1 26 0' fill='none' stroke='%2312141a' stroke-width='5'/%3E%3C/svg%3E">
{ads}
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,650&family=Public+Sans:wght@400;650&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/estilo.css">
<style>.bar2{{display:flex;height:22px;border-radius:6px;overflow:hidden;margin:16px 0;background:var(--soft)}}.bar2 i{{display:block;height:100%}}.stats{{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}}.stats div{{background:var(--soft);border-radius:8px;padding:10px 14px}}.stats b{{display:block;font-family:Newsreader,serif;font-size:26px;line-height:1.1}}.stats span{{font-size:13px;color:var(--mute)}}</style>
</head>
<body>
<header>
  <div class="wrap bar">
    <a class="brand" href="/">Escaño <b>176</b></a>
    <nav class="main-nav" id="main-nav" aria-label="Secciones">
      <a href="/">Portada</a>
      <a href="/#resultados">Resultados</a>
      <a href="/calculadora-dhondt.html">Calculadora d'Hondt</a>
      <a href="/provincias.html"{cur}>Provincias</a>
    </nav>
    <span class="spacer"></span>
    <a class="cta" href="/pactometro.html">Pactómetro</a>
    <button class="menu-btn" id="menu-btn" type="button" aria-expanded="false" aria-controls="main-nav">Menú</button>
  </div>
</header>
<main class="wrap">
"""

FOOT = """</main>
<footer><div class="wrap cols">
  <span>Escaño 176 · Información independiente y no partidista</span>
  <a href="/aviso-legal.html">Aviso legal</a><a href="/privacidad.html">Privacidad y cookies</a>
</div></footer>
<script>
{const b=document.getElementById('menu-btn'),n=document.getElementById('main-nav');
if(b&&n){const set=o=>{n.classList.toggle('open',o);b.setAttribute('aria-expanded',o);b.textContent=o?'Cerrar':'Menú'};
b.addEventListener('click',()=>set(!n.classList.contains('open')));
n.addEventListener('click',e=>{if(e.target.closest('a'))set(false)});
document.addEventListener('keydown',e=>{if(e.key==='Escape')set(false)});}}
</script>
</body>
</html>
"""


def page_head(title, desc, path, current=False):
    return HEAD.format(title=esc(title), desc=esc(desc), url=SITE + path, site=SITE, ads=ADS,
                       cur=' aria-current="page"' if current else "")


def winner(res):
    ps = sorted(res.get("parties", []), key=lambda x: (-(x.get("seats") or 0), -(x.get("votes") or 0)))
    return ps[0] if ps else None


def build_provinces():
    data = json.load(open(p("datos", "provincias.json"), encoding="utf-8"))
    provs = data["provinces"]
    if len(provs) != 52 or sum(x["seats"] for x in provs) != 350:
        fail("datos/provincias.json debe tener 52 circunscripciones que sumen 350 escaños")
    os.makedirs(p("provincias"), exist_ok=True)
    pages = []
    for pr in provs:
        res = pr.get("results")
        if not res or not res.get("parties"):
            continue
        ps = sorted(res["parties"], key=lambda x: (-(x.get("seats") or 0), -(x.get("votes") or 0)))
        given = sum(int(x.get("seats") or 0) for x in ps)
        if given > pr["seats"]:
            fail(f"{pr['name']}: {given} escaños asignados y solo reparte {pr['seats']}")
        title = f"Resultados elecciones generales 2026 en {pr['name']}"
        desc = f"Escaños y votos por partido en {pr['name']} en las elecciones generales del 29 de noviembre de 2026. Reparte {pr['seats']} diputados."
        rows = "".join(
            f'<tr><td><i class="sw" style="background:{color(x.get("color"))}"></i> {esc(x.get("name"))}</td>'
            f'<td class="r">{num(x["votes"]) if x.get("votes") is not None else "—"}</td><td class="r">{pct(x.get("pct"))}</td>'
            f'<td class="r"><b>{int(x.get("seats") or 0)}</b></td></tr>' for x in ps)
        bar = "".join(f'<i style="width:{(x.get("seats") or 0) / pr["seats"] * 100:.2f}%;background:{color(x.get("color"))}"></i>'
                      for x in ps if x.get("seats"))
        w = ps[0]
        status = "Escrutinio provisional" if res.get("status") != "final" else "Resultado definitivo"
        body = (f'<p class="small mute"><a href="/provincias.html">Provincias</a> · {esc(pr["ccaa"])}</p>'
                f'<h1>Elecciones generales 2026 en {esc(pr["name"])}</h1>'
                f'<p class="lead">{esc(pr["name"])} elige {pr["seats"]} diputados al Congreso'
                + (f' (en 2023 eligió {pr["seats2023"]})' if pr["seats2023"] != pr["seats"] else "")
                + f'. {esc(w.get("name"))} es la fuerza con más escaños en la provincia.</p>'
                f'<div class="stats"><div><b>{pct(res.get("counted"))}</b><span>escrutado</span></div>'
                f'<div><b>{pct(res.get("turnout"))}</b><span>participación</span></div>'
                f'<div><b>{pr["seats"]}</b><span>escaños en juego</span></div></div>'
                f'<div class="bar2">{bar}</div>'
                f'<div class="scroll-x"><table><thead><tr><th>Partido</th><th class="r">Votos</th><th class="r">%</th><th class="r">Escaños</th></tr></thead><tbody>{rows}</tbody></table></div>'
                f'<p class="small mute">{status}. Fuente: '
                + (f'<a href="{esc(res["sourceUrl"])}">{esc(res.get("source") or "Ministerio del Interior")}</a>' if str(res.get("sourceUrl", "")).startswith("https://") else esc(res.get("source") or "Ministerio del Interior"))
                + (f' · actualizado {esc(res.get("updated"))}' if res.get("updated") else "") + '.</p>'
                f'<p>¿Qué habría pasado con otros votos? Prueba la <a href="/calculadora-dhondt.html">calculadora d\'Hondt</a> o mira las sumas posibles en el <a href="/pactometro.html">pactómetro</a>.</p>')
        with open(p("provincias", pr["slug"] + ".html"), "w", encoding="utf-8") as f:
            f.write(page_head(title, desc, f"/provincias/{pr['slug']}.html") + body + FOOT)
        pages.append(f"/provincias/{pr['slug']}.html")

    any_res = bool(pages)
    rows = []
    for pr in sorted(provs, key=lambda x: x["name"]):
        res = pr.get("results")
        w = winner(res) if res else None
        name = f'<a href="/provincias/{pr["slug"]}.html">{esc(pr["name"])}</a>' if res and res.get("parties") else esc(pr["name"])
        diff = pr["seats"] - pr["seats2023"]
        dtxt = (("+" if diff > 0 else "") + str(diff)) if diff else "="
        wcell = ""
        if any_res:
            wcell = "<td>—</td>"
            if w:
                wcell = ('<td><i class="sw" style="background:' + color(w.get("color")) + '"></i> '
                         + esc(w.get("name")) + " (" + str(w.get("seats") or 0) + ")</td>")
        rows.append('<tr><td>' + name + '</td><td>' + esc(pr["ccaa"]) + '</td><td class="r"><b>' + str(pr["seats"])
                    + '</b></td><td class="r">' + dtxt + '</td>' + wcell + '</tr>')
    intro = ("Pulsa en cada provincia para ver sus resultados del 29N: escaños, votos y porcentaje por partido."
             if any_res else
             "Cuántos diputados elige cada circunscripción en las elecciones generales del 29 de noviembre de 2026, según el decreto de convocatoria. Tras el escrutinio, cada provincia tendrá aquí su página de resultados.")
    body = ('<h1>Escaños por provincia</h1>'
            f'<p class="lead">{intro}</p>'
            '<p class="small mute">Madrid gana un diputado respecto a 2023 y Cádiz pierde uno. Cada provincia elige al menos dos; Ceuta y Melilla, uno cada una.</p>'
            '<div class="scroll-x"><table><thead><tr><th>Circunscripción</th><th>Comunidad</th><th class="r">Escaños</th><th class="r">Vs. 2023</th>'
            + ('<th>Primera fuerza</th>' if any_res else '') + '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>'
            '<p>Con estos escaños puedes simular el reparto de cualquier provincia en la <a href="/calculadora-dhondt.html">calculadora d\'Hondt</a>.</p>')
    with open(p("provincias.html"), "w", encoding="utf-8") as f:
        f.write(page_head("Escaños por provincia: elecciones generales 2026", "Diputados que elige cada provincia en las elecciones generales del 29N y resultados por circunscripción.", "/provincias.html", True) + body + FOOT)
    return pages


# ---------- 3. Imagen para compartir ----------
def seat_layout(n=350, rows=12, r0=0.4):
    radii = [r0 + (1 - r0) * i / (rows - 1) for i in range(rows)]
    total = sum(radii)
    counts = [round(n * r / total) for r in radii]
    counts[-1] += n - sum(counts)
    pts = []
    for r, c in zip(radii, counts):
        for j in range(c):
            a = math.pi * (1 - (0.5 if c == 1 else j / (c - 1)))
            pts.append((a, math.cos(a) * r, math.sin(a) * r))
    pts.sort(key=lambda t: -t[0])
    return pts


def font(size, bold=False):
    from PIL import ImageFont
    for f in (["DejaVuSerif-Bold.ttf", "DejaVuSans-Bold.ttf"] if bold else ["DejaVuSans.ttf"]):
        for d in ("/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/dejavu/", ""):
            try:
                return ImageFont.truetype(d + f, size)
            except OSError:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def draw_og(d):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("AVISO: Pillow no está instalado; no se regenera og.png (pip install pillow)")
        return
    r = d.get("results") or {}
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), "#ffffff")
    g = ImageDraw.Draw(img)
    cx, cy, R = 850, 520, 300
    seats = []
    for x in r.get("parties", []):
        seats += [color(x.get("color"))] * int(x.get("seats") or 0)
    for i, (_, x, y) in enumerate(seat_layout()):
        px, py = cx + x * R, cy - y * R
        g.ellipse([px - 7, py - 7, px + 7, py + 7], fill=seats[i] if i < len(seats) else "#e3e5ea")
    g.line([cx, cy - R - 18, cx, cy - R - 2], fill="#12141a", width=2)
    g.text((60, 60), "Escaño 176", font=font(64, True), fill="#12141a")
    g.text((60, 150), "Elecciones generales 29N", font=font(34), fill="#12141a")
    label = r.get("label") or "Congreso de los Diputados"
    if r.get("status") != "pending" and r.get("counted") is not None:
        label += f" · {pct(r.get('counted'))} escrutado"
    g.text((60, 205), label[:60], font=font(24), fill="#5d6370")
    top = sorted(r.get("parties", []), key=lambda x: -(x.get("seats") or 0))[:6]
    y = 290
    for x in top:
        g.ellipse([60, y + 6, 80, y + 26], fill=color(x.get("color")))
        g.text((96, y), f"{str(x.get('name')).split(' (')[0]}  {int(x.get('seats') or 0)}", font=font(30, True), fill="#12141a")
        y += 48
    g.text((60, 580), "escano176.es", font=font(24), fill="#5d6370")
    img.save(p("og.png"), optimize=True)


# ---------- 4. Sitemap ----------
def write_sitemap(extra):
    today = dt.datetime.now(MADRID).date().isoformat()
    urls = [("/", "hourly", "1.0"), ("/pactometro.html", "daily", "0.9"), ("/calculadora-dhondt.html", "monthly", "0.8"),
            ("/provincias.html", "daily", "0.8")] + [(u, "daily", "0.7") for u in extra] + \
           [("/aviso-legal.html", "yearly", "0.2"), ("/privacidad.html", "yearly", "0.2")]
    body = "".join(f"  <url><loc>{SITE}{u}</loc><lastmod>{today}</lastmod><changefreq>{c}</changefreq><priority>{pr}</priority></url>\n" for u, c, pr in urls)
    with open(p("sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + body + "</urlset>\n")


if __name__ == "__main__":
    d = read_site_data()
    fix_prev(d)
    write_results(d)
    prerender_index(d)
    pages = build_provinces()
    draw_og(d)
    write_sitemap(pages)
    print(f"OK: resultados.json, provincias.html, {len(pages)} páginas de provincia, og.png y sitemap.xml")
