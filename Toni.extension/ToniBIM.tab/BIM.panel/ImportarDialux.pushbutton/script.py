# -*- coding: utf-8 -*-
__title__ = "Alocar Luminárias Dialux"
__doc__ = """
Versão: 5.15
Descrição: Usa recurso em SymbolGeometry para detectar blocos DWG
e insere famílias Revit dentro de um contexto de transação válido.
Autor: Thiago Toni
"""

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")

from Autodesk.Revit.DB import (
    ImportInstance,
    FilteredElementCollector,
    BuiltInCategory,
    BuiltInParameter,
    Options,
    ViewDetailLevel,
    XYZ,
    Line,
    Structure,
    Element,
    ElementId,
    GeometryInstance,
    ElementTransformUtils
)
from RevitServices.Transactions import TransactionManager
from pyrevit import revit, forms, script

# Documentos e saída
doc    = revit.doc
uidoc  = revit.uidoc
output = script.get_output()
output.close_others()

# 1) Seleção do vínculo CAD (DWG) ou de um bloco dentro dele
forms.alert(
    "Clique no vínculo CAD (DWG) ou em um de seus blocos.",
    title="Selecionar Vínculo"
)
picked = revit.pick_element()

if isinstance(picked, ImportInstance):
    cad = picked
else:
    try:
        pt = picked.Location.Point
    except:
        forms.alert(
            "Selecione o vínculo CAD ou um bloco dentro dele.",
            title="Erro"
        )
        script.exit()
    cad = None
    for link in FilteredElementCollector(doc).OfClass(ImportInstance):
        bb = link.get_BoundingBox(doc.ActiveView)
        if bb and bb.Min.X <= pt.X <= bb.Max.X and bb.Min.Y <= pt.Y <= bb.Max.Y:
            cad = link
            break
    if not cad:
        forms.alert(
            "Não encontrei o vínculo CAD. Clique diretamente nele, por favor.",
            title="Erro"
        )
        script.exit()

# 2) Lê o nome do DWG
try:
    raw = cad.Symbol.get_Parameter(
        BuiltInParameter.SYMBOL_NAME_PARAM
    ).AsString()
    dwg_name = raw.split(":")[0].strip()
except:
    dwg_name = "Link DWG"
output.print_md("**DWG selecionado:** {}".format(dwg_name))

# 3) Descobre as subcategorias DLX_FL…_LUMx
layer_map = {}
for sub in cad.Category.SubCategories:
    name = sub.Name
    if name.startswith("DLX_FL") and "LUM" in name:
        try:
            idx = int(name.split("LUM")[-1].strip())
            layer_map[idx] = name
        except:
            pass

if not layer_map:
    forms.alert(
        "Nenhuma subcategoria DLX_FL…_LUMx encontrada no CAD.",
        title="Aviso"
    )
    script.exit()

types = sorted(layer_map.keys())
forms.alert(
    "Detectados {} tipo(s) de luminária(s): {}".format(
        len(types),
        ", ".join("LUM{}".format(t) for t in types)
    ),
    title="Tipos Encontrados"
)

# 4) Mapeia famílias Revit para cada tipo
families = (
    FilteredElementCollector(doc)
    .OfCategory(BuiltInCategory.OST_LightingFixtures)
    .WhereElementIsElementType()
    .ToElements()
)
if not families:
    forms.alert(
        "Nenhuma família de luminária encontrada.",
        title="Erro"
    )
    script.exit()

label_map = {}
for sym in families:
    fam = sym.FamilyName
    typ = Element.Name.__get__(sym)
    label_map["{}: {}".format(fam, typ)] = sym

labels = list(label_map.keys())
lum_map = {}
for t in types:
    sel = forms.SelectFromList.show(
        labels,
        title="Selecionar família para LUMINÁRIA TIPO {}".format(t),
        button_name="Confirmar"
    )
    if not sel:
        forms.alert(
            "Família não selecionada para LUMINÁRIA {}".format(t),
            title="Erro"
        )
        script.exit()
    lum_map[t] = label_map[sel]

# 5) Extrai a instância raiz do CAD
opts = Options()
opts.ComputeReferences        = True
opts.IncludeNonVisibleObjects = True
opts.DetailLevel              = ViewDetailLevel.Fine

geo = cad.get_Geometry(opts)
root_inst = next(
    (g for g in geo if isinstance(g, GeometryInstance)),
    None
)
if not root_inst:
    forms.alert(
        "Falha ao extrair GeometryInstance do CAD.",
        title="Erro"
    )
    script.exit()

# 6) Recursão em SymbolGeometry para capturar cada bloco
def collect_blocks(inst_obj, parent_tr):
    results = []
    tr = (
        inst_obj.Transform
        if parent_tr is None
        else parent_tr.Multiply(inst_obj.Transform)
    )
    results.append((inst_obj, tr))
    for sub in inst_obj.SymbolGeometry:
        if isinstance(sub, GeometryInstance):
            results += collect_blocks(sub, tr)
    return results

all_blocks = collect_blocks(root_inst, None)

# 7) Filtra por layer_map e agrupa instâncias únicas
seen = set()
items = []
for inst_obj, tr in all_blocks:
    gs_id = getattr(inst_obj, "GraphicsStyleId", None)
    if not gs_id or gs_id == ElementId.InvalidElementId:
        continue
    try:
        layer = doc.GetElement(gs_id).GraphicsStyleCategory.Name
    except:
        continue
    num = next(
        (k for k, v in layer_map.items() if v == layer),
        None
    )
    if num is None:
        continue

    pt  = tr.Origin
    ang = XYZ.BasisX.AngleTo(tr.BasisX)
    if XYZ.BasisX.CrossProduct(tr.BasisX).Z < 0:
        ang = -ang

    key = (
        num,
        round(pt.X, 6),
        round(pt.Y, 6),
        round(pt.Z, 6),
        round(ang, 5)
    )
    if key in seen:
        continue
    seen.add(key)
    items.append((num, pt, ang))

if not items:
    forms.alert(
        "Nenhuma instância de bloco CAD encontrada após filtrar por layers.",
        title="Aviso"
    )
    script.exit()

# 8) Insere as instâncias dentro de um contexto de transação válido
count = 0
with revit.Transaction("Alocar Luminárias Dialux"):
    for num, pt, ang in items:
        sym = lum_map.get(num)
        if not sym:
            continue
        if not sym.IsActive:
            sym.Activate()
            doc.Regenerate()
        axis = Line.CreateBound(pt, pt + XYZ(0, 0, 1))
        inst_rvt = doc.Create.NewFamilyInstance(
            pt,
            sym,
            Structure.StructuralType.NonStructural
        )
        ElementTransformUtils.RotateElement(
            doc, inst_rvt.Id, axis, ang
        )
        count += 1

# 9) Confirmação final
forms.alert(
    "Foram inseridas {} luminária(s) do '{}'.".format(count, dwg_name),
    title="Concluído"
)
