# -*- coding: utf-8 -*-
from __future__ import unicode_literals

__title__ = "Importar de \nIFC"
__doc__ = """
VERSÃO: RV 13.1.0 29/09/2026
Lê luminárias de um vínculo IFC carregado e insere no projeto Revit.
"""
import math
import re
import unicodedata

import clr
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    FamilyPlacementType,
    StorageType,
    Transform,
    Solid,
    Mesh,
    PolyLine,
    Transaction,
    TransactionStatus,
    Element,
    ElementTransformUtils,
    FamilySymbol,
    FilteredElementCollector,
    ElementId,
    GeometryInstance,
    Options,
    Level,
    Line,
    LocationCurve,
    LocationPoint,
    RevitLinkInstance,
    Structure,
    XYZ
)
from pyrevit import revit, script, forms

from System.Windows import Thickness, VerticalAlignment, FontWeights, TextWrapping, SystemParameters
from System.Windows.Controls import Grid, ColumnDefinition, StackPanel, TextBlock, ComboBox, Border
from System.Windows import GridLength, GridUnitType
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Media import BrushConverter
from System.Windows.Automation import AutomationProperties


if revit.doc is None or revit.doc.IsFamilyDocument or revit.doc.IsReadOnly:
    forms.alert("Abra um projeto Revit editável para importar luminárias.", exitscript=True)

# ETAPA 1 - Permite ao usuario selecionar o vinculo IFC no Revit.
forms.alert(
    "Selecione o vinculo IFC no projeto Revit.",
    title="Selecionar vinculo"
)
vinculo_ifc = revit.pick_element()
if vinculo_ifc is None:
    script.exit()
if not isinstance(vinculo_ifc, RevitLinkInstance):
    forms.alert(
        "O elemento selecionado nao e um vinculo Revit/IFC.",
        title="Selecao invalida"
    )
    script.exit()

documento_ifc = vinculo_ifc.GetLinkDocument()
if not documento_ifc:
    forms.alert(
        "Nao foi possivel acessar o documento do vinculo. "
        "Verifique se ele esta carregado.",
        title="Vinculo indisponivel"
    )
    script.exit()

nome_vinculo = vinculo_ifc.Name
transformacao_vinculo = vinculo_ifc.GetTotalTransform()


# ETAPA 3 - Funcoes auxiliares para ler nomes e parametros dos elementos.
def nome_elemento(elemento):
    try:
        return Element.Name.__get__(elemento) or ""
    except Exception:
        return ""


def valor_parametro(elemento, nome_parametro):
    for parametro in elemento.Parameters:
        if (parametro.Definition and
                parametro.Definition.Name.lower() == nome_parametro.lower()):
            return ((parametro.AsString() if parametro.StorageType == StorageType.String
                     else parametro.AsValueString()) or "")
    return ""


def nome_tipo_elemento(elemento):
    try:
        tipo_id = elemento.GetTypeId()
        if not tipo_id or tipo_id == ElementId.InvalidElementId:
            return ""
        return nome_elemento(elemento.Document.GetElement(tipo_id))
    except Exception:
        return ""


def tipo_ifc_legivel(elemento):
    for nome_parametro in ("IfcType", "IfcObjectType", "ObjectType", "IfcName", "Name"):
        valor = valor_parametro(elemento, nome_parametro)
        if valor:
            valor_normalizado = normalizar(valor)
            if valor_normalizado and "vinculo" not in valor_normalizado and "link" not in valor_normalizado:
                return valor

    nome = nome_elemento(elemento)
    if nome:
        nome_normalizado = normalizar(nome)
        if nome_normalizado and "vinculo" not in nome_normalizado and "link" not in nome_normalizado:
            return nome

    nome_tipo = nome_tipo_elemento(elemento)
    if nome_tipo:
        nome_normalizado = normalizar(nome_tipo)
        if nome_normalizado and "vinculo" not in nome_normalizado and "link" not in nome_normalizado:
            return nome_tipo

    categoria = categoria_elemento(elemento)
    if categoria:
        categoria_normalizada = normalizar(categoria)
        if categoria_normalizada and "vinculo" not in categoria_normalizada and "link" not in categoria_normalizada:
            return categoria

    return "Luminaria IFC"


def definir_parametro(elemento, nomes_parametro, valor):
    for nome_parametro in nomes_parametro:
        parametro = elemento.LookupParameter(nome_parametro)
        if (parametro and not parametro.IsReadOnly and
                parametro.StorageType == StorageType.String):
            return parametro.Set(valor or "")
    return False


def categoria_elemento(elemento):
    try:
        return elemento.Category.Name if elemento.Category else ""
    except Exception:
        return ""



def documentos_ifc():
    return [(documento_ifc, nome_vinculo)]


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(caractere for caractere in texto
                     if not unicodedata.combining(caractere))
    return "".join(
        caractere for caractere in texto.lower()
        if caractere.isalnum()
    )


def camada_luminaria(nome):
    texto = nome or ""
    if not texto:
        return ""

    texto = texto.strip()
    texto = texto.replace("_", " ")
    texto = re.sub(r"\s+", " ", texto)

    padrao = r"\s*[-\/]\s*(?:\d+\s*[xX]\s*\d+\s*(?:W|WATTS|WATT)?|\d+\s*(?:W|L|LM)|\d+\s*[xX]\s*\d+\s*(?:L|LM)|[A-Z0-9]+\s*[-/]\s*\d+)$"
    texto = re.sub(padrao, "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\s*[-\/]\s*$", "", texto)
    texto = re.sub(r"\s{2,}", " ", texto).strip()
    return texto or "Luminaria"


def tipo_elemento(elemento):
    try:
        return elemento.Symbol.FamilyName + ": " + Element.Name.__get__(elemento.Symbol)
    except Exception:
        return elemento.GetType().Name


def nome_simbolo(simbolo):
    familia = getattr(simbolo, "FamilyName", "")
    tipo = nome_elemento(simbolo)
    return "{}: {}".format(familia, tipo).strip(": ")


def chave_exibicao(objeto):
    if objeto["guid_ifc"]:
        return ("guid", objeto["guid_ifc"].strip())
    if objeto.get("id_origem"):
        return ("elemento", objeto["origem"], objeto["id_origem"])
    ponto = objeto["ponto"]
    coordenadas = tuple(round(getattr(ponto, eixo), 3) for eixo in ("X", "Y", "Z")) if ponto else None
    return (
        "dados",
        normalizar(objeto["origem"]),
        normalizar(objeto["nome"]),
        normalizar(objeto["tipo"]),
        coordenadas
    )


def pontos_geometria(elemento):
    """Coleta pontos no documento, acumulando transformações de instâncias aninhadas."""
    pontos = []
    opcoes = Options()
    opcoes.ComputeReferences = False
    try:
        geometria = elemento.get_Geometry(opcoes)
        def coletar(geometria_atual, transformacao):
            if geometria_atual is None:
                return
            for item in geometria_atual:
                if isinstance(item, GeometryInstance):
                    coletar(item.GetSymbolGeometry(), transformacao.Multiply(item.Transform))
                elif isinstance(item, Solid):
                    for aresta in item.Edges:
                        pontos.extend(transformacao.OfPoint(p) for p in aresta.Tessellate())
                elif isinstance(item, Mesh):
                    pontos.extend(transformacao.OfPoint(p) for p in item.Vertices)
                elif isinstance(item, PolyLine):
                    pontos.extend(transformacao.OfPoint(p) for p in item.GetCoordinates())
        coletar(geometria, Transform.Identity)
    except Exception as erro:
        script.get_logger().warning("Geometria indisponível (%s): %s", elemento.Id, erro)
        return []  # Não calcular um centro a partir de geometria parcial.
    finally:
        opcoes.Dispose()
    return pontos


def eixo_principal_xy(pontos):
    """
    Calcula o eixo principal horizontal da geometria usando PCA 2D.

    Para uma luminária comprida:
        eixo principal = direção do comprimento.

    Para uma luminária quadrada/circular:
        não força uma direção artificial.
    """
    pontos_xy = [
        ponto for ponto in pontos
        if ponto is not None
    ]

    if len(pontos_xy) < 3:
        return None

    media_x = sum(ponto.X for ponto in pontos_xy) / float(len(pontos_xy))
    media_y = sum(ponto.Y for ponto in pontos_xy) / float(len(pontos_xy))

    sxx = 0.0
    syy = 0.0
    sxy = 0.0

    for ponto in pontos_xy:
        dx = ponto.X - media_x
        dy = ponto.Y - media_y
        sxx += dx * dx
        syy += dy * dy
        sxy += dx * dy

    if (sxx + syy) <= 0.000001:
        return None

    delta = math.sqrt(
        ((sxx - syy) * 0.5) ** 2 +
        sxy * sxy
    )

    maior = ((sxx + syy) * 0.5) + delta
    menor = ((sxx + syy) * 0.5) - delta

    # Se os dois eixos têm praticamente o mesmo tamanho,
    # a geometria não possui uma direção confiável.
    if menor > 0.000001 and maior / menor < 1.05:
        return None

    theta = 0.5 * math.atan2(
        2.0 * sxy,
        sxx - syy
    )

    vetor = XYZ(
        math.cos(theta),
        math.sin(theta),
        0.0
    )

    try:
        return vetor.Normalize()
    except Exception:
        return None


def centro_geometria_pontos(pontos):
    """
    Retorna o centro da caixa envolvente da geometria real.
    """
    if not pontos:
        return None

    min_x = min(ponto.X for ponto in pontos)
    min_y = min(ponto.Y for ponto in pontos)
    min_z = min(ponto.Z for ponto in pontos)

    max_x = max(ponto.X for ponto in pontos)
    max_y = max(ponto.Y for ponto in pontos)
    max_z = max(ponto.Z for ponto in pontos)

    return XYZ(
        (min_x + max_x) * 0.5,
        (min_y + max_y) * 0.5,
        (min_z + max_z) * 0.5
    )


def localizacao_elemento(elemento):
    """
    Retorna:
        ponto      = centro/posição da luminária no IFC
        angulo     = direção física horizontal em radianos
        vetor      = eixo físico horizontal da luminária

    A direção é determinada primeiro pela GEOMETRIA física.
    LocationPoint.Rotation é usada somente para definir o sentido
    (+/-) do eixo quando a geometria permite descobrir um eixo.

    Isso evita depender de uma orientação que pode estar invertida
    em determinados objetos IFC.
    """

    ponto = None
    angulo = 0.0
    vetor = None

    # ---------------------------------------------------------
    # 1. Centro/ponto de inserção IFC.
    # ---------------------------------------------------------
    try:
        localizacao = elemento.Location

        if isinstance(localizacao, LocationPoint):
            ponto = localizacao.Point

        elif isinstance(localizacao, LocationCurve):
            ponto_inicio = localizacao.Curve.GetEndPoint(0)
            ponto_fim = localizacao.Curve.GetEndPoint(1)
            ponto = (ponto_inicio + ponto_fim) * 0.5

    except Exception:
        pass

    # ---------------------------------------------------------
    # 2. Geometria física.
    # ---------------------------------------------------------
    pontos = pontos_geometria(elemento)

    centro = centro_geometria_pontos(pontos)
    if centro is not None:
        ponto = centro

    vetor_geometria = eixo_principal_xy(pontos)

    # ---------------------------------------------------------
    # 3. Define o sentido do eixo.
    #
    # O PCA sabe o eixo, mas não sabe se é:
    #     -----> ou <-----
    #
    # LocationPoint.Rotation fornece o sentido de referência
    # do objeto IFC.
    # ---------------------------------------------------------
    if vetor_geometria is not None:
        vetor = vetor_geometria

        try:
            localizacao = elemento.Location
            referencia = None

            if isinstance(localizacao, LocationPoint):
                rotacao = localizacao.Rotation
                referencia = XYZ(
                    math.cos(rotacao),
                    math.sin(rotacao),
                    0.0
                )

            elif isinstance(localizacao, LocationCurve):
                inicio = localizacao.Curve.GetEndPoint(0)
                fim = localizacao.Curve.GetEndPoint(1)
                referencia = fim - inicio
                referencia = XYZ(
                    referencia.X,
                    referencia.Y,
                    0.0
                )

            if referencia and referencia.GetLength() > 0.000001:
                referencia = referencia.Normalize()

                if vetor.DotProduct(referencia) < 0.0:
                    vetor = XYZ(
                        -vetor.X,
                        -vetor.Y,
                        -vetor.Z
                    )

        except Exception:
            pass

    # ---------------------------------------------------------
    # 4. Fallback para objetos sem geometria suficiente.
    # ---------------------------------------------------------
    if vetor is None:
        try:
            localizacao = elemento.Location

            if isinstance(localizacao, LocationPoint):
                rotacao = localizacao.Rotation
                vetor = XYZ(
                    math.cos(rotacao),
                    math.sin(rotacao),
                    0.0
                )

            elif isinstance(localizacao, LocationCurve):
                inicio = localizacao.Curve.GetEndPoint(0)
                fim = localizacao.Curve.GetEndPoint(1)
                delta = fim - inicio
                vetor = XYZ(delta.X, delta.Y, 0.0)

                if vetor.GetLength() > 0.000001:
                    vetor = vetor.Normalize()

        except Exception:
            pass

    if vetor is None:
        vetor = XYZ.BasisX

    try:
        vetor = vetor.Normalize()
    except Exception:
        vetor = XYZ.BasisX

    angulo = math.atan2(vetor.Y, vetor.X)

    return ponto, angulo, vetor


# ETAPA 5 - Coleta elementos da categoria Luminárias no vínculo selecionado.
objetos_luminaria = []
chaves_ifc = set()

for documento, origem in documentos_ifc():
    for objeto in (
        FilteredElementCollector(documento)
        .OfCategory(BuiltInCategory.OST_LightingFixtures)
        .WhereElementIsNotElementType()
        .ToElements()
    ):
        nome = nome_elemento(objeto)
        nome_tipo = tipo_ifc_legivel(objeto)
        categoria = categoria_elemento(objeto)

        ponto, angulo, vetor_direcao = localizacao_elemento(objeto)

        if ponto:

            # -------------------------------------------------
            # IFC -> sistema de coordenadas do projeto Revit
            # -------------------------------------------------
            ponto = transformacao_vinculo.OfPoint(ponto)

            # -------------------------------------------------
            # Transforma a direção física da luminária.
            # OfVector NÃO altera a posição, apenas a direção.
            # -------------------------------------------------
            vetor_direcao = transformacao_vinculo.OfVector(
                vetor_direcao
            )

            if vetor_direcao.IsZeroLength():
                vetor_direcao = XYZ.BasisX

            vetor_direcao = vetor_direcao.Normalize()

            # Só queremos rotação no plano horizontal.
            vetor_xy = XYZ(
                vetor_direcao.X,
                vetor_direcao.Y,
                0.0
            )

            if vetor_xy.GetLength() > 0.000001:
                vetor_xy = vetor_xy.Normalize()
                angulo = math.atan2(
                    vetor_xy.Y,
                    vetor_xy.X
                )

        objeto_luminaria = {
            "id_origem": str(objeto.Id),
            "origem": origem,
            "nome": nome,
            "tipo": nome_tipo or tipo_elemento(objeto),
            "categoria": categoria,
            "guid_ifc": valor_parametro(objeto, "IfcGUID"),
            "entidade_ifc": valor_parametro(objeto, "IfcEntity"),
            "ponto": ponto,
            "angulo": angulo,
            "vetor_direcao": vetor_direcao
        }

        chave = chave_exibicao(objeto_luminaria)

        if chave not in chaves_ifc:
            chaves_ifc.add(chave)
            objetos_luminaria.append(objeto_luminaria)


# ETAPA 6 - Indexa familias e tipos de luminaria carregados no Revit.
def simbolos_de_luminaria():
    simbolos = (
        FilteredElementCollector(revit.doc)
        .OfClass(FamilySymbol)
        .OfCategory(BuiltInCategory.OST_LightingFixtures)
        .ToElements()
    )
    # A chave por ID preserva tipos com nomes que normalizam para a mesma grafia.
    return {str(simbolo.Id): simbolo for simbolo in simbolos}


def selecionar_mapping_ifc_revit(familias_ifc, familias_revit):
    """Janela de associação; o XAML concentra o tema e a estrutura visual."""
    familias_ifc = sorted(set(item for item in familias_ifc if item and item.strip()))
    familias_revit = sorted(set(item for item in familias_revit if item and item.strip()))
    if not familias_ifc or not familias_revit:
        return {}

    ignorar = "Ignorar esta família"
    mapeamento = {}
    janela = forms.WPFWindow(script.get_bundle_file("associar_luminarias.xaml"))
    WindowInteropHelper(janela).Owner = revit.uidoc.Application.MainWindowHandle
    # Ajusta o tamanho inicial à área útil, inclusive em monitores com escala alta.
    area = SystemParameters.WorkArea
    janela.MinWidth = min(janela.MinWidth, area.Width)
    janela.MinHeight = min(janela.MinHeight, area.Height)
    janela.Width = min(janela.Width, area.Width)
    janela.Height = min(760, max(520, 360 + len(familias_ifc) * 88), area.Height)
    linhas = janela.FindName("MappingRows")
    status = janela.FindName("StatusText")
    janela.FindName("SummaryText").Text = "{} tipos IFC  ·  {} tipos Revit disponíveis".format(
        len(familias_ifc), len(familias_revit))

    neutro = BrushConverter().ConvertFromString("#E8EDF2")
    texto = BrushConverter().ConvertFromString("#202B38")
    secundario = BrushConverter().ConvertFromString("#64748B")
    azul = BrushConverter().ConvertFromString("#2563EB")
    combos = []
    for indice, nome_ifc in enumerate(familias_ifc, 1):
        linha = Border()
        linha.BorderBrush = neutro
        linha.BorderThickness = Thickness(0, 1, 0, 0)
        linha.Padding = Thickness(14, 16, 14, 16)
        linha.MinHeight = 78
        grade = Grid()
        for largura in (2, 3):
            coluna = ColumnDefinition()
            coluna.Width = GridLength(largura, GridUnitType.Star)
            grade.ColumnDefinitions.Add(coluna)

        origem = StackPanel()
        origem.VerticalAlignment = VerticalAlignment.Center
        origem.Margin = Thickness(0, 0, 24, 0)
        numero = TextBlock()
        numero.Text = "{:02d}".format(indice)
        numero.FontSize = 11
        numero.Foreground = secundario
        numero.Margin = Thickness(0, 0, 0, 4)
        nome = TextBlock()
        nome.Text = nome_ifc
        nome.FontWeight = FontWeights.SemiBold
        nome.Foreground = texto
        nome.TextWrapping = TextWrapping.Wrap
        nome.ToolTip = nome_ifc
        origem.Children.Add(numero)
        origem.Children.Add(nome)

        combo = ComboBox()
        combo.Style = janela.FindResource("FamilyCombo")
        combo.VerticalAlignment = VerticalAlignment.Center
        combo.Margin = Thickness(12, 0, 0, 0)
        combo.IsTextSearchEnabled = True
        combo.Items.Add(ignorar)
        for familia in familias_revit:
            combo.Items.Add(familia)
        combo.SelectedIndex = 0
        AutomationProperties.SetName(combo, "Família Revit para " + nome_ifc)
        Grid.SetColumn(combo, 1)
        grade.Children.Add(origem)
        grade.Children.Add(combo)
        linha.Child = grade
        linhas.Children.Add(linha)
        combos.append((nome_ifc, combo))

    def atualizar_status(sender=None, args=None):
        associados = 0
        for _, combo in combos:
            selecionado = combo.SelectedItem and combo.SelectedItem != ignorar
            if selecionado:
                associados += 1
            combo.Foreground = texto if selecionado else secundario
            combo.ToolTip = combo.SelectedItem
        status.Text = "{} de {} tipos associados".format(associados, len(combos))
        status.Foreground = azul if associados else secundario

    def cancelar_click(sender, args):
        janela.DialogResult = False

    def confirmar_click(sender, args):
        resultado = {nome: combo.SelectedItem for nome, combo in combos
                     if combo.SelectedItem and combo.SelectedItem != ignorar}
        if not resultado:
            resposta = forms.alert(
                "Nenhum tipo IFC foi associado a uma família Revit.\n\nDeseja cancelar?",
                title="Sem associações", options=["Sim", "Não"])
            if resposta != "Sim":
                return
        mapeamento.update(resultado)
        janela.DialogResult = True

    for _, combo in combos:
        combo.SelectionChanged += atualizar_status
    janela.FindName("CancelButton").Click += cancelar_click
    janela.FindName("ConfirmButton").Click += confirmar_click
    atualizar_status()
    if janela.ShowDialog() != True:
        return {}
    return mapeamento

# ETAPA 8 - Mostra a quantidade e os dados encontrados no IFC.
output = script.get_output()
output.close_others()
quantidade_ifc = len(objetos_luminaria)
output.print_md("**Luminarias encontradas no IFC:** {}".format(quantidade_ifc))
categorias_ifc = sorted(set(
    objeto["categoria"] for objeto in objetos_luminaria
    if objeto.get("categoria")
))
if categorias_ifc:
    output.print_md("**Categorias IFC encontradas:** {}".format(
        ", ".join(categorias_ifc)
    ))

if not objetos_luminaria:
    forms.alert(
        "Nenhuma luminaria foi encontrada no arquivo IFC\nSelecione um vínculo IFC que contenha luminarias.",
        title="Resultado da busca"
    )
    script.exit()

objetos_filtrados = list(objetos_luminaria)
tipos_disponiveis = sorted(set(
    camada_luminaria(objeto["tipo"]) for objeto in objetos_filtrados
))
output.print_md("**Tipos IFC disponiveis:** {}".format(
    ", ".join(tipos_disponiveis)
))
if not tipos_disponiveis:
    forms.alert("Nenhum tipo de luminaria IFC foi encontrado.", title="Cancelado")
    script.exit()

tipos_selecionados = list(tipos_disponiveis)
if not tipos_selecionados:
    forms.alert("Nenhuma família IFC foi localizada.", title="Cancelado")
    script.exit()

familias_revit_disponiveis = sorted({nome_simbolo(simbolo) for simbolo in simbolos_de_luminaria().values()})
if not familias_revit_disponiveis:
    forms.alert(
        "Nenhuma família Revit de luminária foi encontrada no projeto.",
        title="Familias Revit indisponíveis"
    )
    script.exit()

mapeamento_familias_ifc_revit = selecionar_mapping_ifc_revit(
    tipos_selecionados,
    familias_revit_disponiveis
)
if not mapeamento_familias_ifc_revit:
    forms.alert(
        "Nenhuma família Revit foi relacionada para as famílias IFC selecionadas.",
        title="Mapeamento cancelado"
    )
    script.exit()

objetos_luminaria = [
    objeto for objeto in objetos_filtrados
    if camada_luminaria(objeto["tipo"]) in mapeamento_familias_ifc_revit
]
output.print_md("**Tipos IFC selecionados:** {}".format(
    ", ".join(tipos_selecionados)
))
output.print_md("**Mapeamento IFC x Revit (definido em uma única tela):**")
for nome_ifc, nome_revit in sorted(mapeamento_familias_ifc_revit.items()):
    output.print_md("- {} -> {}".format(nome_ifc, nome_revit))
output.print_md("**Luminarias selecionadas:** {}".format(
    len(objetos_luminaria)
))

# As coordenadas, a direção e a rotação permanecem em memória.
# Não é mais necessário salvar, localizar ou reler um arquivo CSV.
output.print_md("**Coordenadas e rotação mantidas em memória:** IFC -> Revit.")
output.print_md("**Rotação:** eixo físico da geometria IFC comparado ao eixo físico da família Revit.")

# ETAPA 9 - Resolve o mapeamento explícito de famílias para a inserção.
indice_simbolos = simbolos_de_luminaria()
output.print_md("**Tipos de luminaria encontrados no Revit:** {}".format(
    len(indice_simbolos)
))
simbolos_listados = {}
for simbolo in indice_simbolos.values():
    simbolos_listados[str(simbolo.Id)] = nome_simbolo(simbolo)
if simbolos_listados:
    output.print_md("**Familias/tipos disponiveis:**")
    for nome in sorted(simbolos_listados.values()):
        output.print_md("- {}".format(nome))

if not indice_simbolos:
    forms.alert(
        "Nenhuma familia ou tipo de luminaria foi encontrado no Revit.\n\n"
        "Carregue uma familia na categoria Luminarias e execute novamente.",
        title="Nada encontrado no Revit"
    )
    script.exit()

para_inserir = []
sem_familia = []
sem_posicao = []
erros_insercao = []

for objeto in objetos_luminaria:
    simbolo = None
    chave_objeto = camada_luminaria(objeto["tipo"] or objeto["nome"] or "")
    nome_revit_map = mapeamento_familias_ifc_revit.get(chave_objeto)
    if nome_revit_map:
        for simbolo_item in indice_simbolos.values():
            if nome_simbolo(simbolo_item) == nome_revit_map:
                simbolo = simbolo_item
                break
    if not simbolo:
        sem_familia.append(objeto["nome"])
        objeto["status"] = "NAO ALOCADA - familia nao encontrada"
    elif not objeto["ponto"]:
        sem_posicao.append(objeto["nome"])
        objeto["status"] = "NAO ALOCADA - coordenada nao encontrada"
    else:
        # Cada execução cria novas instâncias, inclusive em posições já ocupadas.
        para_inserir.append((objeto, simbolo))


def nivel_da_luminaria(ponto, niveis):
    niveis_abaixo = [nivel for nivel in niveis
                     if nivel.ProjectElevation <= ponto.Z]
    if niveis_abaixo:
        return max(niveis_abaixo, key=lambda nivel: nivel.ProjectElevation)
    return min(niveis, key=lambda nivel: abs(nivel.ProjectElevation - ponto.Z))


def inserir_luminaria(objeto, simbolo, niveis):
    tipo = simbolo.Family.FamilyPlacementType
    if tipo != FamilyPlacementType.OneLevelBased:
        raise ValueError(
            "Família '{}' usa {}. Este comando requer família de um nível, "
            "sem hospedeiro; face, teto ou plano de trabalho não são selecionados.".format(
                simbolo.FamilyName, tipo))
    if not niveis:
        raise ValueError("Nenhum nível encontrado no projeto.")
    ponto = objeto["ponto"]
    nivel = nivel_da_luminaria(ponto, niveis)
    instancia = revit.doc.Create.NewFamilyInstance(
        ponto, simbolo, nivel, Structure.StructuralType.NonStructural)
    if instancia is None:
        raise ValueError("O Revit não criou a instância.")
    return instancia


def pontos_geometria_instancia(instancia):
    return pontos_geometria(instancia)


def eixo_fisico_familia(instancia):
    """
    Descobre a direção física principal da família pela geometria.

    O PCA identifica o eixo longitudinal da luminária.
    O HandOrientation/FacingOrientation serve apenas para decidir
    o sentido positivo desse eixo, pois PCA não diferencia
    esquerda/direita.
    """
    pontos = pontos_geometria_instancia(instancia)
    eixo = eixo_principal_xy(pontos)

    if eixo is None:
        # Família quadrada/circular ou geometria insuficiente.
        return None

    candidatos = []

    try:
        vetor = XYZ(
            instancia.HandOrientation.X,
            instancia.HandOrientation.Y,
            0.0
        )
        if vetor.GetLength() > 0.000001:
            candidatos.append(vetor.Normalize())
    except Exception:
        pass

    try:
        vetor = XYZ(
            instancia.FacingOrientation.X,
            instancia.FacingOrientation.Y,
            0.0
        )
        if vetor.GetLength() > 0.000001:
            candidatos.append(vetor.Normalize())
    except Exception:
        pass

    if candidatos:
        melhor = max(
            candidatos,
            key=lambda candidato: abs(eixo.DotProduct(candidato))
        )

        if eixo.DotProduct(melhor) < 0.0:
            eixo = XYZ(
                -eixo.X,
                -eixo.Y,
                0.0
            )

    return eixo.Normalize()


def angulo_normalizado(angulo):
    while angulo > math.pi:
        angulo -= 2.0 * math.pi
    while angulo < -math.pi:
        angulo += 2.0 * math.pi
    return angulo


def rotacionar_instancia(instancia, objeto):
    """
    Alinha a DIREÇÃO FÍSICA da família Revit com a DIREÇÃO FÍSICA
    da luminária IFC.

    Não usa +90, -90 ou +180 fixos.

    Se o IFC aponta para X e a família aponta para -X:
        delta = 180 graus.

    Se o IFC aponta para Y e a família aponta para X:
        delta = 90 graus.

    O eixo físico é obtido da geometria da família, o que corrige
    famílias criadas com origem/eixo interno diferentes.
    """

    ponto = objeto.get("ponto")

    if ponto is None:
        return

    alvo = objeto.get("vetor_direcao")

    if alvo is None:
        angulo = objeto.get("angulo", 0.0)
        alvo = XYZ(
            math.cos(angulo),
            math.sin(angulo),
            0.0
        )

    alvo = XYZ(alvo.X, alvo.Y, 0.0)

    if alvo.GetLength() <= 0.000001:
        return

    alvo = alvo.Normalize()

    atual = eixo_fisico_familia(instancia)

    # Se a geometria não permite descobrir um eixo físico,
    # usa a orientação da própria instância como fallback.
    if atual is None:
        try:
            atual = XYZ(
                instancia.HandOrientation.X,
                instancia.HandOrientation.Y,
                0.0
            )
            if atual.GetLength() > 0.000001:
                atual = atual.Normalize()
            else:
                atual = None
        except Exception:
            atual = None

    if atual is None:
        try:
            atual = XYZ(
                instancia.FacingOrientation.X,
                instancia.FacingOrientation.Y,
                0.0
            )
            if atual.GetLength() > 0.000001:
                atual = atual.Normalize()
            else:
                atual = None
        except Exception:
            atual = None

    if atual is None:
        return

    angulo_alvo = math.atan2(
        alvo.Y,
        alvo.X
    )

    angulo_atual = math.atan2(
        atual.Y,
        atual.X
    )

    delta = angulo_normalizado(
        angulo_alvo - angulo_atual
    )

    if abs(delta) <= 0.000001:
        return

    eixo_z = XYZ.BasisZ

    eixo = Line.CreateBound(
        ponto,
        ponto + eixo_z
    )

    try:
        localizacao = instancia.Location

        if isinstance(localizacao, LocationPoint):
            if localizacao.Rotate(eixo, delta):
                return
    except Exception:
        pass

    ElementTransformUtils.RotateElement(
        revit.doc,
        instancia.Id,
        eixo,
        delta
    )


def centralizar_instancia_no_ponto(instancia, ponto_alvo):
    """
    Depois da rotação, faz o centro geométrico real da família
    coincidir com o centro da luminária IFC.

    Não depende de a origem interna da família estar no centro.
    """

    pontos = pontos_geometria_instancia(instancia)

    centro_familia = centro_geometria_pontos(pontos)

    if centro_familia is None:
        try:
            caixa = instancia.get_BoundingBox(None)
            if caixa is not None:
                centro_familia = (
                    caixa.Transform.OfPoint(caixa.Min) + caixa.Transform.OfPoint(caixa.Max)
                ) * 0.5
        except Exception:
            pass

    if centro_familia is None:
        return False

    deslocamento = ponto_alvo - centro_familia

    if deslocamento.GetLength() <= 0.000001:
        return True

    ElementTransformUtils.MoveElement(
        revit.doc,
        instancia.Id,
        deslocamento
    )

    return True


# ETAPA 10 - Cada item é atômico: criação, rotação e alinhamento.
criadas = 0
niveis = list(FilteredElementCollector(revit.doc).OfClass(Level))
total_para_inserir = len(para_inserir)
canceladas = 0
with forms.ProgressBar(title="Importando IFC: {value}/{max_value}", cancellable=True) as progresso:
    for indice, (objeto, simbolo) in enumerate(para_inserir, 1):
        progresso.update_progress(indice - 1, total_para_inserir)
        if progresso.cancelled:
            canceladas = total_para_inserir - indice + 1
            for pendente, _ in para_inserir[indice - 1:]:
                pendente["status"] = "NAO ALOCADA - cancelada"
            break
        transacao = Transaction(revit.doc, "Inserir luminária IFC")
        try:
            transacao.Start()
            opcoes = transacao.GetFailureHandlingOptions()
            transacao.SetFailureHandlingOptions(
                opcoes.SetClearAfterRollback(True).SetForcedModalHandling(True))
            if not simbolo.IsActive:
                simbolo.Activate()
            revit.doc.Regenerate()
            instancia = inserir_luminaria(objeto, simbolo, niveis)
            revit.doc.Regenerate()
            rotacionar_instancia(instancia, objeto)
            revit.doc.Regenerate()
            if not centralizar_instancia_no_ponto(instancia, objeto["ponto"]):
                raise ValueError("Não foi possível obter o centro geométrico da família.")
            definir_parametro(instancia, ("IfcGUID",), objeto["guid_ifc"])
            if not definir_parametro(instancia, ("IfcName", "Nome IFC"), objeto["nome"]):
                comentarios = instancia.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                if comentarios and not comentarios.IsReadOnly:
                    comentarios.Set(objeto["nome"])
            definir_parametro(instancia, ("IfcSource", "Origem IFC"), objeto["origem"])
            revit.doc.Regenerate()
            if transacao.Commit() != TransactionStatus.Committed:
                raise ValueError("O Revit não confirmou a transação.")
            criadas += 1
            objeto["status"] = "ALOCADA"
        except Exception as erro:
            if transacao.GetStatus() == TransactionStatus.Started:
                transacao.RollBack()
            objeto["status"] = "NAO ALOCADA - {}".format(erro)
            erros_insercao.append("{}: {}".format(objeto["nome"], erro))
        finally:
            transacao.Dispose()
        progresso.update_progress(indice, total_para_inserir)

forms.alert(
    "Luminárias inseridas: {}\nFalhas: {}\nSem posição: {}\nSem família: {}\nCanceladas: {}".format(
        criadas, len(erros_insercao), len(sem_posicao), len(sem_familia), canceladas),
    title="Resultado da importação IFC")

# ETAPA 11 - Exibe o resultado individual da alocacao.
for objeto in objetos_luminaria:
    output.print_md(
        "- **{}** | {} | {} | Coordenada: {} | Familia Revit: {} | "
        "Status: **{}**".format(
            objeto["nome"],
            objeto["tipo"],
            objeto["origem"],
            "({}, {}, {})".format(
                round(objeto["ponto"].X, 3),
                round(objeto["ponto"].Y, 3),
                round(objeto["ponto"].Z, 3)
            ) if objeto["ponto"] else "nao encontrada",
            nome_simbolo(next(
                (simbolo for item, simbolo in para_inserir
                 if item is objeto),
                None
            )) if any(item is objeto for item, simbolo in para_inserir)
            else "nao encontrada",
            objeto.get("status", "NAO ALOCADA")
        )
    )

# ETAPA 12 - Exibe o resumo da comparacao e da insercao.
output.print_md("**Luminarias posicionadas:** {}".format(criadas))
if sem_familia:
    output.print_md("**Sem familia compativel:** {}".format(
        ", ".join(sem_familia)
    ))
if sem_posicao:
    output.print_md(
        "**COORDENADAS NAO ENCONTRADAS (nao alocadas):** {}".format(
            ", ".join(sem_posicao)
        )
    )
if erros_insercao:
    output.print_md("**Falhas de insercao:**")
    for erro in erros_insercao:
        output.print_md("- {}".format(erro))


