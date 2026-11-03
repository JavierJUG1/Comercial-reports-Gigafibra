"""Agrega un corte al Excel SIN reescribir el libro.

Un .xlsx es un zip de partes XML. Para dejar el archivo "tal cual" se copian todas las partes existentes byte a
byte y solo se tocan las mínimas necesarias:

- xl/worksheets/sheetN.xml       (nueva) hoja cruda con la respuesta de la consulta
- hoja del reporte               celda de encabezado + fórmula COUNTIFS (con su valor ya calculado) en cada fila
- tabla (Tabla2)                 rango y nueva columna calculada
- xl/workbook.xml, sus relaciones y [Content_Types].xml   registro de la hoja nueva
- docProps/app.xml               lista de hojas
- xl/calcChain.xml               se quita (Excel la regenera) y se marca recalcular al abrir

Así no se pierden estilos, anchos ni metadatos del archivo original y el tiempo no crece con el tamaño del libro
(las hojas existentes se copian en flujo, sin cargarlas en memoria).
"""
from __future__ import annotations

import os
import re
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from xml.sax.saxutils import escape, quoteattr

REL_WORKSHEET = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
CT_WORKSHEET = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
_INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_EPOCH = datetime(1899, 12, 30)


class XlsxError(Exception):
    pass


# ---------------------------------------------------------------------------- utilidades de celdas
def col_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def split_ref(ref: str) -> tuple[int, int]:
    m = re.fullmatch(r"\$?([A-Z]+)\$?(\d+)", ref)
    if not m:
        raise XlsxError(f"Referencia inválida: {ref}")
    return col_index(m.group(1)), int(m.group(2))


def range_bounds(ref: str) -> tuple[int, int, int, int]:
    a, b = ref.split(":")
    c1, r1 = split_ref(a)
    c2, r2 = split_ref(b)
    return c1, r1, c2, r2


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'\s{re.escape(name)}="([^"]*)"', tag)
    return m.group(1) if m else None


def _text(value: str) -> str:
    return escape(_INVALID_XML.sub("", value)[:32767])


def _cell_xml(ref: str, value: Any, style: str | None) -> str:
    s = f' s="{style}"' if style else ""
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return f'<c r="{ref}"{s} t="b"><v>{int(value)}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"{s}><v>{value!r}</v></c>'
    if isinstance(value, datetime):
        serial = (value.replace(tzinfo=None) - _EPOCH).total_seconds() / 86400
        return f'<c r="{ref}"{s}><v>{serial!r}</v></c>'
    if isinstance(value, date):
        return f'<c r="{ref}"{s}><v>{(value - _EPOCH.date()).days}</v></c>'
    text = str(value)
    space = ' xml:space="preserve"' if text != text.strip() else ""
    return f'<c r="{ref}"{s} t="inlineStr"><is><t{space}>{_text(text)}</t></is></c>'


# ---------------------------------------------------------------------------- estructura del libro
@dataclass
class Book:
    sheets: list[dict[str, str]]  # [{name, sheetId, rid, path}] en orden del libro
    rels: dict[str, str]  # rId → ruta de la parte
    main_path: str
    table_path: str


def _norm_target(target: str, base: str = "xl/") -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    parts = (base + target).split("/")
    out: list[str] = []
    for p in parts:
        if p == "..":
            out.pop()
        elif p and p != ".":
            out.append(p)
    return "/".join(out)


def inspect(z: zipfile.ZipFile, sheet_name: str, table_name: str) -> Book:
    wb = z.read("xl/workbook.xml").decode("utf-8")
    rels_xml = z.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    rels = {_attr(t, "Id"): _norm_target(_attr(t, "Target") or "") for t in re.findall(r"<Relationship\b[^>]*>", rels_xml)}
    sheets = []
    for t in re.findall(r"<sheet\b[^>]*/>", wb):
        rid = _attr(t, "r:id")
        name = _attr(t, "name") or ""
        sheets.append({"name": _unescape(name), "sheetId": _attr(t, "sheetId") or "0", "rid": rid or "",
                       "path": rels.get(rid, "")})
    main = next((s for s in sheets if s["name"] == sheet_name), None)
    if not main:
        raise XlsxError(f"El Excel no tiene la hoja '{sheet_name}'.")
    folder, fname = main["path"].rsplit("/", 1)
    srels_name = f"{folder}/_rels/{fname}.rels"
    table_path = ""
    if srels_name in z.namelist():
        srels = z.read(srels_name).decode("utf-8")
        for t in re.findall(r"<Relationship\b[^>]*>", srels):
            if (_attr(t, "Type") or "").endswith("/table"):
                p = _norm_target(_attr(t, "Target") or "", folder + "/")
                txml = z.read(p).decode("utf-8")
                root = re.search(r"<table\b[^>]*>", txml).group(0)
                if _attr(root, "displayName") == table_name or _attr(root, "name") == table_name:
                    table_path = p
    if not table_path:
        raise XlsxError(f"No se encontró la tabla '{table_name}' en la hoja '{sheet_name}'.")
    return Book(sheets=sheets, rels=rels, main_path=main["path"], table_path=table_path)


def _unescape(s: str) -> str:
    return s.replace("&quot;", '"').replace("&apos;", "'").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _template_sheet_parts(z: zipfile.ZipFile, path: str) -> tuple[str, dict[int, str]]:
    """<cols> y estilo por columna (fila 2) de una hoja cruda existente, leyendo solo su inicio."""
    with z.open(path) as fh:
        head = fh.read(400_000).decode("utf-8", "ignore")
    cols = re.search(r"<cols>.*?</cols>", head, re.S)
    styles: dict[int, str] = {}
    row2 = re.search(r'<row r="2"[^>]*>(.*?)</row>', head, re.S)
    if row2:
        for c in re.findall(r"<c\b[^>]*>", row2.group(1)):
            ref, s = _attr(c, "r"), _attr(c, "s")
            if ref and s:
                styles[split_ref(ref)[0]] = s
    return (cols.group(0) if cols else ""), styles


# ---------------------------------------------------------------------------- edición de la hoja del reporte
def _edit_main_sheet(xml: str, header: str, col: int, first_row: int, last_row: int,
                     formula: Callable[[int], str], cached: Callable[[int], int | None]) -> str:
    letter = col_letter(col)
    prev = col_letter(col - 1)

    def style_of(row_xml: str, ref: str) -> str | None:
        m = re.search(rf'<c r="{ref}"[^>]*>|<c r="{ref}"[^>]*/>', row_xml)
        return _attr(m.group(0), "s") if m else None

    def new_cell(r: int, row_xml: str) -> str:
        s = style_of(row_xml, f"{prev}{r}")
        sa = f' s="{s}"' if s else ""
        if r == first_row:
            return f'<c r="{letter}{r}"{sa} t="inlineStr"><is><t>{_text(header)}</t></is></c>'
        v = cached(r)
        cached_xml = f"<v>{v}</v>" if v is not None else ""
        return f'<c r="{letter}{r}"{sa}><f>{_text(formula(r))}</f>{cached_xml}</c>'

    def patch_row(tag: str, body: str, r: int) -> str:
        if tag.endswith("/>"):  # fila vacía <row .../>
            tag = tag[:-2].rstrip() + ">"
        if re.search(rf'<c r="{letter}{r}"', body):
            raise XlsxError(f"La celda {letter}{r} ya tiene datos; la columna siguiente a la tabla debe estar vacía.")
        spans = _attr(tag, "spans")
        if spans and ":" in spans:
            a, b = spans.split(":")
            if int(b) < col:
                tag = tag.replace(f'spans="{spans}"', f'spans="{a}:{col}"')
        pos = len(body)  # insertar en orden de columna
        for cm in re.finditer(r'<c r="([A-Z]+)\d+"', body):
            if col_index(cm.group(1)) > col:
                pos = cm.start()
                break
        return f"{tag}{body[:pos]}{new_cell(r, body)}{body[pos:]}</row>"

    out, idx, seen = [], 0, set()
    for m in re.finditer(r"<row(?=[\s/>])[^>]*>", xml):
        if m.start() < idx:
            continue
        tag = m.group(0)
        r = int(_attr(tag, "r") or 0)
        if tag.endswith("/>"):
            body, end = "", m.end()
        else:
            close = xml.index("</row>", m.end())
            body, end = xml[m.end():close], close + len("</row>")
        out.append(xml[idx:m.start()])
        out.append(patch_row(tag, body, r) if first_row <= r <= last_row else xml[m.start():end])
        seen.add(r)
        idx = end
    out.append(xml[idx:])
    result = "".join(out)
    missing = [r for r in range(first_row, last_row + 1) if r not in seen]
    if missing:
        raise XlsxError(f"Filas {missing} de la tabla no existen en la hoja.")

    dim = re.search(r'<dimension\s+ref="([^"]+)"\s*/>', result)
    if dim and ":" in dim.group(1):
        c1, r1, c2, r2 = range_bounds(dim.group(1))
        if c2 < col:  # el rango declarado de la hoja debe incluir la columna nueva (algunos lectores lo usan)
            result = result.replace(dim.group(0), f'<dimension ref="{col_letter(c1)}{r1}:{letter}{max(r2, last_row)}"/>', 1)
    elif dim:
        result = result.replace(dim.group(0), f'<dimension ref="A1:{letter}{last_row}"/>', 1)
    cols = re.search(r"<cols>.*?</cols>", result, re.S)
    if cols:
        new_cols = cols.group(0)
        covered = False
        for ct in re.findall(r"<col\b[^>]*/>", new_cols):
            lo, hi = int(_attr(ct, "min") or 0), int(_attr(ct, "max") or 0)
            if lo <= col <= hi:
                covered = True
            elif lo <= col - 1 == hi and not covered:
                new_cols = new_cols.replace(ct, ct.replace(f'max="{hi}"', f'max="{col}"'), 1)
                covered = True
        result = result.replace(cols.group(0), new_cols, 1)
    return result


def _edit_table(xml: str, header: str, col: int, formula_first: str) -> tuple[str, int, int, int]:
    root = re.search(r"<table\b[^>]*>", xml).group(0)
    ref = _attr(root, "ref")
    c1, r1, c2, r2 = range_bounds(ref)
    if col != c2 + 1:
        raise XlsxError("La columna nueva debe quedar inmediatamente a la derecha de la tabla.")
    new_ref = f"{col_letter(c1)}{r1}:{col_letter(col)}{r2}"
    xml = xml.replace(f'ref="{ref}"', f'ref="{new_ref}"')  # tabla y autofiltro
    ids = [int(x) for x in re.findall(r'<tableColumn\b[^>]*\bid="(\d+)"', xml)]
    names = [_unescape(x) for x in re.findall(r'<tableColumn\b[^>]*\bname="([^"]*)"', xml)]
    if header in names:
        raise XlsxError(f"La tabla ya tiene una columna '{header}'.")
    count = re.search(r'<tableColumns count="(\d+)"', xml)
    xml = xml.replace(count.group(0), f'<tableColumns count="{int(count.group(1)) + 1}"', 1)
    uid = f' xr3:uid="{{{str(uuid.uuid4()).upper()}}}"' if "xmlns:xr3=" in root else ""
    column = (f'<tableColumn id="{max(ids) + 1}"{uid} name={quoteattr(header)}>'
              f"<calculatedColumnFormula>{_text(formula_first)}</calculatedColumnFormula></tableColumn>")
    xml = xml.replace("</tableColumns>", column + "</tableColumns>", 1)
    return xml, r1, r2, c1


# ---------------------------------------------------------------------------- operación principal
def append_cut(src: Path, dst: Path, *, sheet_name: str, table_name: str, new_sheet: str, header: str,
               raw_header: list[str], raw_rows: Iterable[list[Any]], formula: Callable[[str, int], str],
               cached: Callable[[int], int | None]) -> dict[str, Any]:
    """Escribe en `dst` una copia de `src` con la hoja cruda `new_sheet` y la columna `header` en la tabla."""
    with zipfile.ZipFile(src) as zin:
        book = inspect(zin, sheet_name, table_name)
        if any(s["name"] == new_sheet for s in book.sheets):
            raise XlsxError(f"El Excel ya tiene una hoja '{new_sheet}'.")
        names = zin.namelist()
        ct = zin.read("[Content_Types].xml").decode("utf-8")
        wb = zin.read("xl/workbook.xml").decode("utf-8")
        wbrels = zin.read("xl/_rels/workbook.xml.rels").decode("utf-8")
        main = zin.read(book.main_path).decode("utf-8")
        table = zin.read(book.table_path).decode("utf-8")
        app = zin.read("docProps/app.xml").decode("utf-8") if "docProps/app.xml" in names else None

        # Plantilla de formato: la última hoja cruda existente (anchos y estilo de fecha de Creation)
        raw_sheets = [s for s in book.sheets if s["path"] != book.main_path]
        tmpl_cols, tmpl_styles = _template_sheet_parts(zin, raw_sheets[-1]["path"]) if raw_sheets else ("", {})

        # Tabla y hoja del reporte
        c2 = range_bounds(_attr(re.search(r"<table\b[^>]*>", table).group(0), "ref"))[2]
        col = c2 + 1
        table, first_row, last_row, _ = _edit_table(table, header, col, formula(new_sheet, first_row_of(table) + 1))
        main = _edit_main_sheet(main, header, col, first_row, last_row, lambda r: formula(new_sheet, r), cached)

        # Registro de la hoja nueva
        nums = [int(m) for m in re.findall(r"worksheets/sheet(\d+)\.xml", wbrels)] or [0]
        part = f"xl/worksheets/sheet{max(nums) + 1}.xml"
        while part in names:
            part = f"xl/worksheets/sheet{int(re.search(r'(\d+)', part.rsplit('/', 1)[1]).group(1)) + 1}.xml"
        rid_nums = [int(m) for m in re.findall(r'Id="rId(\d+)"', wbrels)] or [0]
        rid = f"rId{max(rid_nums) + 1}"
        sheet_id = max(int(s["sheetId"]) for s in book.sheets) + 1
        wb = wb.replace("</sheets>", f'<sheet name={quoteattr(new_sheet)} sheetId="{sheet_id}" r:id="{rid}"/></sheets>', 1)
        calc = re.search(r"<calcPr\b[^>]*/>", wb)
        if calc and "fullCalcOnLoad" not in calc.group(0):
            wb = wb.replace(calc.group(0), calc.group(0)[:-2].rstrip() + ' fullCalcOnLoad="1"/>', 1)
        elif not calc:
            wb = wb.replace("</sheets>", '</sheets><calcPr fullCalcOnLoad="1"/>', 1) if "<definedNames" not in wb else \
                wb.replace("</definedNames>", '</definedNames><calcPr fullCalcOnLoad="1"/>', 1)
        target = part[len("xl/"):]
        wbrels = wbrels.replace("</Relationships>",
                                f'<Relationship Id="{rid}" Type="{REL_WORKSHEET}" Target="{target}"/></Relationships>', 1)
        calc_chain = None
        for t in re.findall(r"<Relationship\b[^>]*/>", wbrels):
            if (_attr(t, "Type") or "").endswith("/calcChain"):
                calc_chain = _norm_target(_attr(t, "Target") or "")
                wbrels = wbrels.replace(t, "", 1)
        ct = ct.replace("</Types>", f'<Override PartName="/{part}" ContentType="{CT_WORKSHEET}"/></Types>', 1)
        if calc_chain:
            ct = re.sub(rf'<Override PartName="/{re.escape(calc_chain)}"[^>]*/>', "", ct)
        if app:
            app = _edit_app(app, raw_sheets[-1]["name"] if raw_sheets else sheet_name, new_sheet)

        replaced = {"[Content_Types].xml": ct, "xl/workbook.xml": wb, "xl/_rels/workbook.xml.rels": wbrels,
                    book.main_path: main, book.table_path: table}
        if app:
            replaced["docProps/app.xml"] = app

        tmp = dst.with_name(f".{dst.stem}.{uuid.uuid4().hex[:8]}.tmp.xlsx")
        written = 0
        try:
            with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zout:
                last_ws = max((i for i, n in enumerate(names) if n.startswith("xl/worksheets/sheet")), default=len(names) - 1)
                for i, info in enumerate(zin.infolist()):
                    if info.filename == calc_chain:
                        continue
                    if info.filename in replaced:
                        zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                        zi.compress_type = zipfile.ZIP_DEFLATED
                        zout.writestr(zi, replaced[info.filename].encode("utf-8"))
                    else:
                        with zin.open(info) as fsrc, zout.open(_clone(info), "w", force_zip64=True) as fdst:
                            shutil.copyfileobj(fsrc, fdst, 1 << 20)
                    if i == last_ws:
                        written = _write_raw_sheet(zout, part, raw_header, raw_rows, tmpl_cols, tmpl_styles)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
    # Fuera del bloque de lectura: en Windows no se puede reemplazar un archivo que sigue abierto.
    try:
        _verify(tmp, sheet_name, table_name, new_sheet, header)
        os.replace(tmp, dst)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return {"hoja": new_sheet, "columna": col_letter(col), "encabezado": header, "parte": part, "filas": written}


def first_row_of(table_xml: str) -> int:
    ref = _attr(re.search(r"<table\b[^>]*>", table_xml).group(0), "ref")
    return range_bounds(ref)[1]


def _clone(info: zipfile.ZipInfo) -> zipfile.ZipInfo:
    zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
    zi.compress_type = info.compress_type
    zi.external_attr = info.external_attr
    return zi


def _edit_app(app: str, after_name: str, new_sheet: str) -> str:
    """Lista de hojas en docProps/app.xml (Excel la usa solo como metadato)."""
    try:
        hp = re.search(r"(<HeadingPairs>.*?<vt:i4>)(\d+)(</vt:i4>)", app, re.S)
        tp = re.search(r'(<TitlesOfParts><vt:vector size=")(\d+)(" baseType="lpstr">)(.*?)(</vt:vector>)', app, re.S)
        if not hp or not tp:
            return app
        app = app.replace(hp.group(0), f"{hp.group(1)}{int(hp.group(2)) + 1}{hp.group(3)}", 1)
        items = tp.group(4)
        marker = f"<vt:lpstr>{escape(after_name)}</vt:lpstr>"
        new_item = f"<vt:lpstr>{escape(new_sheet)}</vt:lpstr>"
        items = items.replace(marker, marker + new_item, 1) if marker in items else items + new_item
        return app.replace(tp.group(0), f"{tp.group(1)}{int(tp.group(2)) + 1}{tp.group(3)}{items}{tp.group(5)}", 1)
    except Exception:  # noqa: BLE001 - metadato no crítico
        return app


def _write_raw_sheet(zout: zipfile.ZipFile, part: str, header: list[str], rows: Iterable[list[Any]],
                     cols: str, styles: dict[int, str]) -> int:
    zi = zipfile.ZipInfo(part, date_time=datetime.now().timetuple()[:6])
    zi.compress_type = zipfile.ZIP_DEFLATED
    ncols = len(header)
    last = col_letter(ncols)
    rows = list(rows)
    with zout.open(zi, "w", force_zip64=True) as fh:
        w = lambda s: fh.write(s.encode("utf-8"))  # noqa: E731
        w('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
          '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">')
        w(f'<dimension ref="A1:{last}{len(rows) + 1}"/><sheetViews><sheetView workbookViewId="0"/></sheetViews>'
          f'<sheetFormatPr baseColWidth="10" defaultRowHeight="15"/>{cols}<sheetData>')
        w(f'<row r="1" spans="1:{ncols}">' + "".join(_cell_xml(f"{col_letter(i)}1", h, None)
                                                       for i, h in enumerate(header, start=1)) + "</row>")
        buf = []
        for n, row in enumerate(rows, start=2):
            cells = "".join(_cell_xml(f"{col_letter(i)}{n}", v, styles.get(i)) for i, v in enumerate(row, start=1))
            buf.append(f'<row r="{n}" spans="1:{ncols}">{cells}</row>')
            if len(buf) >= 2000:
                w("".join(buf))
                buf = []
        w("".join(buf))
        w('</sheetData><pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>'
          "</worksheet>")
    return len(rows)


def _verify(path: Path, sheet_name: str, table_name: str, new_sheet: str, header: str) -> None:
    """Comprobación de integridad antes de reemplazar el Excel: estructura legible y columna presente."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        if new_sheet not in wb.sheetnames or sheet_name not in wb.sheetnames:
            raise XlsxError("El Excel generado no tiene las hojas esperadas.")
        first = next(wb[sheet_name].iter_rows(min_row=1, max_row=1, values_only=True))
        if header not in [str(v) for v in first if v is not None]:
            raise XlsxError("El Excel generado no tiene la columna del corte.")
    finally:
        wb.close()
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad:
            raise XlsxError(f"Parte dañada en el Excel generado: {bad}")
