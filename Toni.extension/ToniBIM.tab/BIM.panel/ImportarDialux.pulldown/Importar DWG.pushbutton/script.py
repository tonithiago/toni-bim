# -*- coding: utf-8 -*-
from __future__ import unicode_literals

__title__ = "Importar de DWG"
__doc__ = """
Versão: 5.16
Descrição: Usa recurso em SymbolGeometry para detectar blocos DWG
e insere famílias Revit dentro de um contexto de transação válido.
Autor: Thiago Toni
"""

import math
import re

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    ImportInstance,
    FilteredElementCollector,
    BuiltInCategory,
    BuiltInParameter,
    Options,
    ViewDetailLevel,
    XYZ,
    Line,
    Level,
    FamilySymbol,
    FamilyPlacementType,
    Transaction,
    TransactionStatus,
    Structure,
    Element,
    ElementId,
    GeometryInstance,
    ElementTransformUtils
)
from pyrevit import revit, forms, script

# Documentos e saída
doc    = revit.doc
output = script.get_output()
output.close_others()

if doc is None or doc.IsFamilyDocument or doc.IsReadOnly:
    forms.alert("Abra um projeto Revit editável para importar luminárias.", exitscript=True)

# 1) Seleção do vínculo CAD (DWG) ou de um bloco dentro dele
forms.alert(
    "Clique no vínculo CAD (DWG) ou em um de seus blocos.",
    title="Selecionar Vínculo"
)
picked = revit.pick_element()

if picked is None:
    script.exit()
if not isinstance(picked, ImportInstance):
    forms.alert("Selecione diretamente um vínculo ou uma importação CAD.", exitscript=True)
cad = picked

# 2) Lê o nome do DWG
try:
    raw = doc.GetElement(cad.GetTypeId()).get_Parameter(
        BuiltInParameter.SYMBOL_NAME_PARAM
    ).AsString()
    dwg_name = raw.strip() if raw else "Link DWG"
except Exception:
    dwg_name = "Link DWG"
output.print_md("**DWG selecionado:** {}".format(dwg_name))

# 3) Descobre as subcategorias DLX_FL…_LUMx
layer_map = {}
if cad.Category:
    for sub in cad.Category.SubCategories:
        match = re.match(r"^DLX_FL.*LUM\s*(\d+)\s*$", sub.Name, re.IGNORECASE)
        if match:
            # Vários pavimentos podem ter layers distintos com o mesmo LUM.
            layer_map[sub.Name] = int(match.group(1))

if not layer_map:
    forms.alert(
        "Nenhuma subcategoria DLX_FL…_LUMx encontrada no CAD.",
        title="Aviso"
    )
    script.exit()

types = sorted(set(layer_map.values()))
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
    .OfClass(FamilySymbol)
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

labels = sorted(label_map.keys())
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

# 5) Extrai as instâncias raiz do CAD
opts = Options()
opts.ComputeReferences        = False
opts.IncludeNonVisibleObjects = True
opts.DetailLevel              = ViewDetailLevel.Fine

geo = cad.get_Geometry(opts)
root_insts = [g for g in (geo or []) if isinstance(g, GeometryInstance)]
if not root_insts:
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
    gs_id = inst_obj.GraphicsStyleId
    gs = doc.GetElement(gs_id) if gs_id != ElementId.InvalidElementId else None
    layer = gs.GraphicsStyleCategory.Name if gs and gs.GraphicsStyleCategory else None
    if layer in layer_map:
        # O bloco correspondente já representa uma luminária; não duplicar seus filhos.
        return [(inst_obj, tr)]
    for sub in inst_obj.GetSymbolGeometry():
        if isinstance(sub, GeometryInstance):
            results += collect_blocks(sub, tr)
    return results

all_blocks = []
for root_inst in root_insts:
    all_blocks += collect_blocks(root_inst, None)

# 7) Filtra por layer_map e agrupa instâncias únicas
seen = set()
items = []
blocos_nao_suportados = 0
for inst_obj, tr in all_blocks:
    gs_id = getattr(inst_obj, "GraphicsStyleId", None)
    if not gs_id or gs_id == ElementId.InvalidElementId:
        continue
    try:
        layer = doc.GetElement(gs_id).GraphicsStyleCategory.Name
    except Exception:
        continue
    num = layer_map.get(layer)
    if num is None:
        continue

    # Rotação em planta não reproduz espelhamento nem inclinação 3D.
    if tr.HasReflection or abs(tr.BasisZ.Normalize().Z - 1.0) > 0.000001:
        blocos_nao_suportados += 1
        continue
    pt = tr.Origin  # A geometria da Revit API já usa pés internos.
    ang = math.atan2(tr.BasisX.Y, tr.BasisX.X)

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
        "Nenhum bloco compatível encontrado. Blocos espelhados/inclinados: {}".format(
            blocos_nao_suportados),
        title="Aviso"
    )
    script.exit()

def inserir_luminaria(ponto, simbolo, niveis):
    tipo = simbolo.Family.FamilyPlacementType
    if tipo != FamilyPlacementType.OneLevelBased:
        raise ValueError(
            "Família '{}' usa {}. Selecione uma família de um nível, sem hospedeiro.".format(
                simbolo.FamilyName, tipo))
    if not niveis:
        raise ValueError("Nenhum nível encontrado no projeto.")
    abaixo = [nivel for nivel in niveis if nivel.ProjectElevation <= ponto.Z]
    nivel = (max(abaixo, key=lambda n: n.ProjectElevation) if abaixo else
             min(niveis, key=lambda n: abs(n.ProjectElevation - ponto.Z)))
    instancia = doc.Create.NewFamilyInstance(
        ponto, simbolo, nivel, Structure.StructuralType.NonStructural)
    if instancia is None:
        raise ValueError("O Revit não criou a instância.")
    return instancia


# 8) Uma falha desfaz todo o item, sem deixar instâncias parcialmente posicionadas.
count = 0
falhas = []
canceladas = 0
niveis = list(FilteredElementCollector(doc).OfClass(Level))
total_items = len(items)
with forms.ProgressBar(title="Importando DWG: {value}/{max_value}", cancellable=True) as progresso:
    for indice, (num, pt, ang) in enumerate(items, 1):
        progresso.update_progress(indice - 1, total_items)
        if progresso.cancelled:
            canceladas = total_items - indice + 1
            break
        transacao = Transaction(doc, "Inserir luminária DWG")
        try:
            transacao.Start()
            opcoes = transacao.GetFailureHandlingOptions()
            transacao.SetFailureHandlingOptions(
                opcoes.SetClearAfterRollback(True).SetForcedModalHandling(True))
            sym = lum_map[num]
            if not sym.IsActive:
                sym.Activate()
            doc.Regenerate()
            inst_rvt = inserir_luminaria(pt, sym, niveis)
            axis = Line.CreateBound(pt, pt + XYZ.BasisZ)
            if abs(ang) > 0.000001:
                ElementTransformUtils.RotateElement(doc, inst_rvt.Id, axis, ang)
            doc.Regenerate()
            if transacao.Commit() != TransactionStatus.Committed:
                raise ValueError("O Revit não confirmou a transação.")
            count += 1
        except Exception as erro:
            if transacao.GetStatus() == TransactionStatus.Started:
                transacao.RollBack()
            falhas.append("LUM{}: {}".format(num, erro))
        finally:
            transacao.Dispose()
        progresso.update_progress(indice, total_items)

# 9) Confirmação final com contagem somente das transações confirmadas.
forms.alert(
    "Foram inseridas {} luminária(s) do '{}'.\nFalhas: {}\nCanceladas: {}"
    "\nBlocos espelhados/inclinados não inseridos: {}".format(
        count, dwg_name, len(falhas), canceladas, blocos_nao_suportados),
    title="Resultado da importação DWG")
if falhas:
    output.print_md("**Falhas de inserção:**")
    for falha in falhas:
        output.print_md("- {}".format(falha))
