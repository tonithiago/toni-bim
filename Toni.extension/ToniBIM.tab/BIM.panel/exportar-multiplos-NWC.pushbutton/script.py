# -*- coding: utf-8 -*-
__title__ = "Exportar NWCs"


"""Exporta um arquivo .nwc por vista 3D selecionada.

Compatibilidade alvo: Revit 2025 (preparado para evolucao em 2026+).

Referencias API (Revit API Docs):
- Document.Export(String, String, NavisworksExportOptions)
  https://www.revitapidocs.com/2025/1b9538a9-a76b-0a40-2aed-e02f6974a43a.htm
- NavisworksExportOptions
  https://www.revitapidocs.com/2025/a58dbe71-1be7-dad6-51b6-5386c162cf87.htm
- OptionalFunctionalityUtils.IsNavisworksExporterAvailable()
  https://www.revitapidocs.com/2025/429a8247-5f73-a254-1377-f384a9360226.htm

Limitacao importante sobre "Navisworks settings...":
A API publica consultada para Revit 2025 nao expoe um metodo suportado para:
- ler o estado atual do dialogo "Navisworks settings..." da UI
- recuperar essas preferencias de exportacao ja persistidas pela UI
- clonar automaticamente essas preferencias para NavisworksExportOptions

Por isso, este script usa NavisworksExportOptions criado via API (fallback seguro).
A funcao build_export_options_for_view(view_id) foi centralizada para futura
expansao caso a Autodesk exponha leitura dessas preferencias em versoes futuras.
"""


import os
import re
import time

from pyrevit import revit, DB, forms, script
from System import Action
from System.Windows.Controls import CheckBox
from System.Windows import Thickness
from System.Windows.Threading import DispatcherPriority


doc = revit.doc
output = script.get_output()
logger = script.get_logger()


FIXED_FACETING_FACTOR = 40.0
NWC_EXTENSION = ".nwc"
MAX_BASENAME_LENGTH = 150
WRITE_TEST_FILENAME_PREFIX = ".toni_bim_write_test"

# Preset embutido no codigo, baseado na analise dos XMLs:
# - export_project_internal.xml
# - export_shared.xml
# A diferenca entre os dois presets e somente o campo Coordinates.
NWC_OPTION_PRESET = {
    "ExportElementIds": True,
    "FindMissingMaterials": False,
    "ConvertElementProperties": True,
    "ExportUrls": False,
    "ExportRoomAsAttribute": False,
    "ExportRoomGeometry": False,
    "ExportLinks": True,
    "ExportParts": True,
    "DivideFileIntoLevels": True,
    "ConvertLinkedCADFormats": False,
    "ConvertLights": True,
    "Parameters": "All",
    "FacetingFactor": FIXED_FACETING_FACTOR,
}


def _map_parameters_enum(param_value):
    normalized = str(param_value).strip().lower()
    if normalized == "none":
        return getattr(DB.NavisworksParameters, "None")
    if normalized == "elements":
        return getattr(DB.NavisworksParameters, "Elements")
    return getattr(DB.NavisworksParameters, "All")


def _map_coordinates_enum(coord_value):
    normalized = str(coord_value).strip().lower()
    if normalized == "project internal":
        return getattr(DB.NavisworksCoordinates, "Internal")
    if normalized == "shared":
        return getattr(DB.NavisworksCoordinates, "Shared")
    # fallback seguro
    return getattr(DB.NavisworksCoordinates, "Shared")


def apply_embedded_settings_to_options(options, coordinates_text):
    """Aplica preset embutido equivalente aos XMLs compartilhados pelo usuario."""
    options.ExportElementIds = bool(NWC_OPTION_PRESET["ExportElementIds"])
    options.FindMissingMaterials = bool(NWC_OPTION_PRESET["FindMissingMaterials"])
    options.ConvertElementProperties = bool(
        NWC_OPTION_PRESET["ConvertElementProperties"]
    )
    options.ExportUrls = bool(NWC_OPTION_PRESET["ExportUrls"])
    options.ExportRoomAsAttribute = bool(NWC_OPTION_PRESET["ExportRoomAsAttribute"])
    options.ExportRoomGeometry = bool(NWC_OPTION_PRESET["ExportRoomGeometry"])
    options.ExportLinks = bool(NWC_OPTION_PRESET["ExportLinks"])
    options.ExportParts = bool(NWC_OPTION_PRESET["ExportParts"])
    options.DivideFileIntoLevels = bool(NWC_OPTION_PRESET["DivideFileIntoLevels"])
    options.ConvertLinkedCADFormats = bool(
        NWC_OPTION_PRESET["ConvertLinkedCADFormats"]
    )
    options.ConvertLights = bool(NWC_OPTION_PRESET["ConvertLights"])
    options.Parameters = _map_parameters_enum(NWC_OPTION_PRESET["Parameters"])
    options.FacetingFactor = float(NWC_OPTION_PRESET["FacetingFactor"])
    options.Coordinates = _map_coordinates_enum(coordinates_text)

    # Mantidos fora por nao haver equivalente publico direto via Revit API:
    # embed_textures, with_type_props, separate_custom_props, strict_sectioning


def is_navisworks_exporter_available():
    """Retorna True quando o exporter Navisworks esta disponivel na sessao."""
    return DB.OptionalFunctionalityUtils.IsNavisworksExporterAvailable()


def get_folder_validation_error(folder):
    """Valida pasta de destino e retorna mensagem amigavel quando houver erro."""
    if not folder:
        return "Selecione a pasta de destino dos arquivos NWC."

    if not os.path.isdir(folder):
        return "A pasta de destino selecionada nao existe ou nao esta acessivel."

    test_filename = "{}_{}.tmp".format(
        WRITE_TEST_FILENAME_PREFIX,
        int(time.time() * 1000),
    )
    test_path = os.path.join(folder, test_filename)
    try:
        with open(test_path, "w") as test_file:
            test_file.write("ok")
        os.remove(test_path)
    except Exception as ex:
        return (
            "Nao foi possivel gravar na pasta selecionada.\n\n"
            "Verifique permissoes, sincronizacao do Dropbox ou bloqueios do Windows.\n\n"
            "Detalhes: {}".format(ex)
        )

    return None


def _is_exportable_3d_view(view):
    """Regras de filtro para vistas 3D exportaveis neste comando."""
    if not isinstance(view, DB.View3D):
        return False
    if view.IsTemplate:
        return False
    if view.IsPerspective:
        return False

    # Filtro conservador para evitar vistas sem suporte em exportacao em lote.
    return bool(view.CanBePrinted)


def collect_exportable_3d_views(document):
    """Coleta vistas 3D unicas, validas e ordenadas por nome."""
    unique_ids = set()
    exportable = []

    for view in DB.FilteredElementCollector(document).OfClass(DB.View3D):
        if view.Id.IntegerValue in unique_ids:
            continue
        if not _is_exportable_3d_view(view):
            continue

        unique_ids.add(view.Id.IntegerValue)
        exportable.append(view)

    exportable.sort(key=lambda v: v.Name.lower())
    return exportable


class ExportNWCWindow(forms.WPFWindow):
    """Janela unica para configurar e iniciar a exportacao em lote."""

    def __init__(self, xaml_file, views):
        forms.WPFWindow.__init__(self, xaml_file)
        self._views = views
        self._view_checkboxes = []

        self.selected_views = []
        self.output_folder = None
        self.coordinates_text = "Project Internal"
        self.confirmed = False

        self._setup_views()
        self._setup_defaults()
        self._wire_events()
        self._update_selection_status()

    def _setup_views(self):
        duplicate_counter = {}
        for view in self._views:
            base_label = view.Name
            count = duplicate_counter.get(base_label, 0) + 1
            duplicate_counter[base_label] = count
            label = base_label if count == 1 else "{} ({})".format(base_label, count)
            checkbox = CheckBox()
            checkbox.Content = label
            checkbox.Margin = Thickness(0, 2, 0, 2)
            checkbox.IsChecked = False
            checkbox.ToolTip = view.Name
            checkbox.Checked += self._on_view_checked_changed
            checkbox.Unchecked += self._on_view_checked_changed
            self.viewsPanel.Children.Add(checkbox)
            self._view_checkboxes.append((checkbox, view))

        self.statusTextBlock.Text = "Pronto para exportar."

    def _setup_defaults(self):
        self.facetingTextBox.Text = str(int(FIXED_FACETING_FACTOR))
        self.coordinatesComboBox.SelectedIndex = 0

    def _wire_events(self):
        self.browseFolderButton.Click += self._on_browse_folder_click
        self.selectAllViewsButton.Click += self._on_select_all_views_click
        self.clearAllViewsButton.Click += self._on_clear_all_views_click
        self.cancelButton.Click += self._on_cancel_click
        self.exportButton.Click += self._on_export_click

    def _get_selected_views(self):
        return [
            view for checkbox, view in self._view_checkboxes if bool(checkbox.IsChecked)
        ]

    def _update_selection_status(self):
        selected_count = len(self._get_selected_views())
        total_count = len(self._view_checkboxes)
        self.selectedCountTextBlock.Text = "{} de {} vistas selecionadas".format(
            selected_count, total_count
        )
        self.exportButton.IsEnabled = bool(selected_count and self.output_folder)

    def _on_view_checked_changed(self, sender, args):
        self._update_selection_status()

    def _on_browse_folder_click(self, sender, args):
        folder = forms.pick_folder()
        if folder:
            folder_error = get_folder_validation_error(folder)
            if folder_error:
                self.output_folder = None
                self.outputFolderTextBox.Text = ""
                self._update_selection_status()
                forms.alert(folder_error, title="Pasta invalida")
                return

            self.output_folder = folder
            self.outputFolderTextBox.Text = folder
            self.statusTextBlock.Text = "Pasta selecionada."
            self._update_selection_status()

    def _on_cancel_click(self, sender, args):
        self.confirmed = False
        self.Close()

    def _on_select_all_views_click(self, sender, args):
        for checkbox, _ in self._view_checkboxes:
            checkbox.IsChecked = True
        self._update_selection_status()

    def _on_clear_all_views_click(self, sender, args):
        for checkbox, _ in self._view_checkboxes:
            checkbox.IsChecked = False
        self._update_selection_status()

    def _on_export_click(self, sender, args):
        selected_views = self._get_selected_views()
        if not selected_views:
            forms.alert(
                "Selecione ao menos uma vista 3D para exportar.",
                title="Selecao obrigatoria",
            )
            return

        folder_error = get_folder_validation_error(self.output_folder)
        if folder_error:
            forms.alert(folder_error, title="Pasta obrigatoria")
            return

        coord_item = self.coordinatesComboBox.SelectedItem
        coord_label = str(coord_item.Content) if coord_item else "Ponto base de projeto"
        if coord_label == "Ponto base de projeto":
            self.coordinates_text = "Project Internal"
        else:
            self.coordinates_text = "Shared"

        self.selected_views = selected_views
        self.confirmed = True
        self.Close()


class ExportProgressWindow(forms.WPFWindow):
    """Janela centralizada para acompanhar o progresso da exportacao."""

    def __init__(self, xaml_file):
        forms.WPFWindow.__init__(self, xaml_file)
        self.cancel_requested = False
        self._completed_count = 0
        self._total_count = 1
        self._percent = 0
        self._view_name = None
        self._estimated_total_text = "Calculando..."
        self._elapsed_time_text = "0 min 0.0 s"
        self._allow_close = False
        self.cancelButton.Click += self._on_cancel_click
        self.Closing += self._on_closing

    def _on_cancel_click(self, sender, args):
        self.request_cancel()

    def _on_closing(self, sender, args):
        if not self._allow_close:
            args.Cancel = True
            self.request_cancel()

    def request_cancel(self):
        self.cancel_requested = True
        self.cancelButton.Content = "Cancelando..."
        self.cancelButton.IsEnabled = False
        self.statusTextBlock.Text = (
            "Cancelamento solicitado. Aguardando finalizar o arquivo atual..."
        )

    def close_after_export(self):
        self._allow_close = True
        self.Close()

    def _apply_progress_values(self):
        self.exportProgressBar.Maximum = 100
        self.exportProgressBar.Value = self._percent
        self.percentTextBlock.Text = "{}%".format(self._percent)
        self.estimatedTimeTextBlock.Text = self._estimated_total_text
        self.elapsedTimeTextBlock.Text = self._elapsed_time_text

        if self._view_name:
            self.statusTextBlock.Text = "Exportando: {}".format(self._view_name)
        elif self._completed_count > 0:
            self.statusTextBlock.Text = "Concluidos: {} de {}".format(
                self._completed_count, self._total_count
            )
        else:
            self.statusTextBlock.Text = "Preparando exportacao..."

    def update_progress(self, completed_count, total_count, started_at, view_name=None):
        self._completed_count = completed_count
        self._total_count = max(total_count, 1)
        self._percent = int(round((completed_count / float(self._total_count)) * 100))
        self._view_name = view_name
        elapsed_seconds = time.time() - started_at
        self._elapsed_time_text = _format_elapsed_seconds(elapsed_seconds)

        if completed_count > 0:
            estimated_total_seconds = (
                elapsed_seconds / float(completed_count)
            ) * total_count
            self._estimated_total_text = _format_elapsed_seconds(estimated_total_seconds)
        else:
            self._estimated_total_text = "Calculando..."

        self.Dispatcher.Invoke(
            Action(self._apply_progress_values),
            DispatcherPriority.Background,
        )


def sanitize_filename(name):
    """Converte nome de vista para nome de arquivo valido no Windows."""
    sanitized = re.sub(r"[<>:\"/\\|?*]", "_", name or "")
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    sanitized = sanitized.rstrip(".")
    sanitized = sanitized[:MAX_BASENAME_LENGTH].rstrip(" .")
    return sanitized or "vista_sem_nome"


def make_unique_export_basename(folder, raw_name, reserved_basenames):
    """Gera nome unico para evitar sobrescrever arquivos no lote ou na pasta."""
    base_name = sanitize_filename(raw_name)
    candidate = base_name
    counter = 2

    while (
        candidate.lower() in reserved_basenames
        or os.path.exists(os.path.join(folder, candidate + NWC_EXTENSION))
    ):
        suffix = " - {:02d}".format(counter)
        candidate = "{}{}".format(
            base_name[: MAX_BASENAME_LENGTH - len(suffix)].rstrip(" ."),
            suffix,
        )
        counter += 1

    reserved_basenames.add(candidate.lower())
    return candidate


def build_export_options_for_view(view_id, coordinates_text):
    """Monta opcoes de exportacao para uma vista.

    Fallback robusto: usa defaults da API e define somente escopo + ViewId.
    Isso evita suposicoes nao suportadas sobre o estado da UI "Navisworks settings...".
    """
    options = DB.NavisworksExportOptions()
    options.ExportScope = DB.NavisworksExportScope.View
    options.ViewId = view_id
    apply_embedded_settings_to_options(options, coordinates_text)

    return options


def export_view_to_nwc(document, folder, view, coordinates_text, reserved_basenames):
    """Exporta uma unica vista para NWC e retorna metadados do resultado."""
    base_name = make_unique_export_basename(folder, view.Name, reserved_basenames)
    target_path = os.path.join(folder, base_name + NWC_EXTENSION)

    options = build_export_options_for_view(view.Id, coordinates_text)
    document.Export(folder, base_name, options)

    return {
        "view_name": view.Name,
        "path": target_path,
    }


def get_export_error_message(ex):
    """Traduz excecoes comuns para mensagens mais uteis no relatorio."""
    err_text = str(ex)
    if "No suitable geometry found" in err_text:
        return (
            "{} | Dica: confirme se a vista possui elementos modelaveis "
            "visiveis (host ou links) e se os filtros/recortes nao "
            "estao ocultando a geometria."
        ).format(err_text)
    return err_text


def _format_elapsed_seconds(seconds):
    minutes = int(seconds // 60)
    remain = seconds - (minutes * 60)
    return "{} min {:.1f} s".format(minutes, remain)


def print_summary(selected_count, success, failures, elapsed_seconds):
    """Imprime relatorio final amigavel no output do pyRevit."""
    output.print_md("## Exportacao Multipla NWC - Relatorio")
    output.print_md("- Vistas selecionadas: **{}**".format(selected_count))
    output.print_md("- Exportadas com sucesso: **{}**".format(len(success)))
    output.print_md("- Falhas: **{}**".format(len(failures)))
    output.print_md("- Tempo total: **{}**".format(_format_elapsed_seconds(elapsed_seconds)))

    if success:
        output.print_md("### Arquivos Gerados")
        rows = [(item["view_name"], item["path"]) for item in success]
        output.print_table(rows, columns=["Vista", "Arquivo NWC"])

    if failures:
        output.print_md("### Falhas")
        rows = [(item["view_name"], item["error"]) for item in failures]
        output.print_table(rows, columns=["Vista", "Erro"])


def main():
    output.close_others()

    if doc.IsFamilyDocument:
        forms.alert(
            "Este comando deve ser executado em um projeto Revit, nao em uma familia.",
            title="Documento incompativel",
        )
        return

    if not is_navisworks_exporter_available():
        forms.alert(
            "Nao foi encontrado o exportador Navisworks nesta instalacao do Revit.\n\n"
            "Instale o plugin/exporter oficial da Autodesk para o Revit 2025 e tente novamente.",
            title="Exportador Navisworks indisponivel",
        )
        return

    views = collect_exportable_3d_views(doc)
    if not views:
        forms.alert(
            "Nenhuma vista 3D valida para exportacao foi encontrada.",
            title="Sem vistas exportaveis",
        )
        return

    xaml_file = os.path.join(
        os.path.dirname(__file__), "ExportarMultiplosNWCWindow.xaml"
    )
    window = ExportNWCWindow(xaml_file, views)
    window.ShowDialog()

    if not window.confirmed:
        forms.alert(
            "Operacao cancelada pelo usuario.",
            title="Operacao cancelada",
        )
        return

    selected_views = window.selected_views
    folder = window.output_folder
    coordinates_text = window.coordinates_text

    if not selected_views:
        forms.alert(
            "Nenhuma vista foi selecionada.",
            title="Operacao cancelada",
        )
        return

    if not folder:
        forms.alert(
            "Nenhuma pasta de destino foi selecionada.",
            title="Operacao cancelada",
        )
        return

    folder_error = get_folder_validation_error(folder)
    if folder_error:
        forms.alert(folder_error, title="Pasta invalida")
        return

    success = []
    failures = []
    cancelled = False
    reserved_basenames = set()
    started_at = time.time()
    total_views = len(selected_views)

    output.print_md(
        "Parametros do lote: Coordinates = **{}**, Faceting Factor = **{}**".format(
            coordinates_text, FIXED_FACETING_FACTOR
        )
    )

    progress_xaml_file = os.path.join(
        os.path.dirname(__file__), "ExportarMultiplosNWCProgressWindow.xaml"
    )
    progress_window = ExportProgressWindow(progress_xaml_file)
    progress_window.Show()
    progress_window.update_progress(0, total_views, started_at)

    try:
        for index, view in enumerate(selected_views, 1):
            if progress_window.cancel_requested:
                cancelled = True
                logger.info("Exportacao NWC cancelada pelo usuario.")
                break

            try:
                progress_window.update_progress(
                    index - 1,
                    total_views,
                    started_at,
                    view.Name,
                )
                result = export_view_to_nwc(
                    doc,
                    folder,
                    view,
                    coordinates_text,
                    reserved_basenames,
                )
                success.append(result)
                logger.info("NWC exportado: %s", result["path"])
            except Exception as ex:
                logger.exception("Falha ao exportar vista '%s'", view.Name)
                failures.append(
                    {
                        "view_name": view.Name,
                        "error": get_export_error_message(ex),
                    }
                )

            progress_window.update_progress(index, total_views, started_at)
    finally:
        progress_window.close_after_export()

    elapsed_seconds = time.time() - started_at
    elapsed_text = _format_elapsed_seconds(elapsed_seconds)
    print_summary(len(selected_views), success, failures, elapsed_seconds)

    if cancelled:
        forms.alert(
            "Exportacao cancelada pelo usuario.\n\n"
            "Arquivos gerados antes do cancelamento: {}\n"
            "Falhas antes do cancelamento: {}\n"
            "Tempo total: {}\n\n"
            "Consulte o relatorio no painel de saida.".format(
                len(success), len(failures), elapsed_text
            ),
            title="Exportacao cancelada",
        )
    elif success and not failures:
        forms.alert(
            "Exportacao concluida com sucesso.\n\n"
            "Arquivos gerados: {}\n"
            "Tempo total: {}".format(len(success), elapsed_text),
            title="Concluido",
        )
    elif success and failures:
        forms.alert(
            "Exportacao concluida com alertas.\n\n"
            "Sucessos: {}\nFalhas: {}\n\n"
            "Tempo total: {}\n\n"
            "Consulte o relatorio no painel de saida.".format(
                len(success), len(failures), elapsed_text
            ),
            title="Concluido com alertas",
        )
    else:
        forms.alert(
            "Nenhum arquivo foi exportado.\n\n"
            "Tempo total: {}\n\n"
            "Consulte o relatorio no painel de saida para detalhes.".format(
                elapsed_text
            ),
            title="Falha na exportacao",
        )


if __name__ == "__main__":
    main()
