# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,too-many-lines
# pylint: disable=missing-function-docstring,missing-class-docstring
"""Exporta folhas em ordem a partir de um indice de folhas.

Note:
Ao usar a opcao `Combinar em um unico arquivo`
no Revit 2022 ou anterior, a ferramenta adiciona
o caractere nao imprimivel u'\u200e' no inicio dos
nomes das folhas para forcar a ordenacao correta.

Verifique se os indices de desenhos consideram isso
ao filtrar numeros de folhas.

Shift-Click:
Shift-clique na ferramenta remove todos os caracteres
nao imprimiveis dos numeros das folhas, caso algum erro
faca esses caracteres permanecerem.
"""
# pylint: disable=import-error,invalid-name,broad-except,superfluous-parens
import re
import os.path as op
import codecs
import os
import datetime
import locale
import time
import tempfile
from collections import namedtuple

from pyrevit import HOST_APP, EXEC_PARAMS
from pyrevit import framework
from pyrevit.framework import Windows, Drawing, ObjectModel, Forms, List
from pyrevit import coreutils
from pyrevit import forms
from pyrevit import revit, DB
from pyrevit import script
from pyrevit.compat import get_elementid_value_func


get_elementid_value = get_elementid_value_func()

logger = script.get_logger()
config = script.get_config()


# Non Printable Char
NPC = u'\u200e'
INDEX_FORMAT = '{{:0{digits}}}'
INTERNAL_PDF_PRINTER = "PDF nativo do Revit"
DWG_SESSION_SETUP = "<configuracao de exportacao na sessao>"


EXPORT_ENCODING = 'utf_16_le'
if HOST_APP.is_newer_than(2020):
    EXPORT_ENCODING = 'utf_8'

IS_REVIT_2022_OR_NEWER = HOST_APP.is_newer_than(2021)


AvailableDoc = namedtuple('AvailableDoc', ['name', 'hash', 'linked'])

NamingFormatter = namedtuple('NamingFormatter', ['template', 'desc'])

SheetRevision = namedtuple('SheetRevision', ['number', 'desc', 'date', 'is_set'])
UNSET_REVISION = SheetRevision(number=None, desc=None, date=None, is_set=False)

TitleBlockPrintSettings = \
    namedtuple('TitleBlockPrintSettings', ['psettings', 'set_by_param'])


class PrintUtils:
    """Utility functions for printing and exporting sheets."""

    @staticmethod
    def get_doc():
        return revit.doc

    @staticmethod
    def get_dir():
        return os.path.join(os.path.expanduser("~"), "Desktop", "Exportacoes pyRevit")

    @staticmethod
    def get_folder(task="_PDF"):
        date_stamp = datetime.datetime.today().strftime("%y%m%d")
        time_stamp = datetime.datetime.today().strftime("%H%M%S")
        return "{}_{}{}".format(date_stamp, time_stamp, task)

    @staticmethod
    def ensure_dir(dp):
        if not os.path.exists(dp):
            os.makedirs(dp)
        return dp

    @staticmethod
    def open_dir(dp):
        try:
            os.startfile(dp)
        except Exception:
            pass
        return dp

    @staticmethod
    def pdf_opts(hcb=True, hsb=True, hrp=True, hvt=True, mcl=True):
        if not IS_REVIT_2022_OR_NEWER:
            raise Exception("A exportacao nativa de PDF requer Revit 2022 ou mais recente.")
        opts = DB.PDFExportOptions()
        opts.HideCropBoundaries = hcb
        opts.HideScopeBoxes = hsb
        opts.HideReferencePlane = hrp
        opts.HideUnreferencedViewTags = hvt
        opts.MaskCoincidentLines = mcl
        opts.PaperFormat = DB.ExportPaperFormat.Default
        if hasattr(opts, 'SetExportInBackground'):
            opts.SetExportInBackground(False)
        return opts

    @staticmethod
    def dwg_opts(doc=None, setup_name=None, sc=False, mv=True):
        opts = None
        if doc and setup_name and setup_name != DWG_SESSION_SETUP:
            try:
                opts = DB.DWGExportOptions.GetPredefinedOptions(doc, setup_name)
            except Exception as setup_err:
                logger.warning(
                    'Nao foi possivel carregar a configuracao DWG "%s": %s',
                    setup_name,
                    setup_err
                    )
        if not opts:
            opts = DB.DWGExportOptions()
            opts.SharedCoords = sc
            opts.MergedViews = mv
        return opts

    @staticmethod
    def get_dwg_setup_names(doc):
        setup_names = []
        for class_name in ('BaseExportOptions', 'DWGExportOptions'):
            try:
                options_class = getattr(DB, class_name)
                get_names = getattr(options_class, 'GetPredefinedSetupNames')
                setup_names = list(get_names(doc))
                break
            except Exception:
                continue
        return [DWG_SESSION_SETUP] + sorted(setup_names)

    @staticmethod
    def export_sheet_pdf(dir_path, sheet, opt, doc, filename):
        opt.FileName = op.splitext(filename)[0]
        if hasattr(opt, 'Combine'):
            opt.Combine = False
        export_sheet = List[DB.ElementId]()
        export_sheet.Add(sheet.Id)
        if not doc.Export(dir_path, export_sheet, opt):
            raise Exception("A API do Revit retornou falha na exportacao PDF.")
        return True

    @staticmethod
    def export_sheets_pdf(dir_path, sheets, opt, doc, filename):
        opt.FileName = op.splitext(filename)[0]
        if hasattr(opt, 'Combine'):
            opt.Combine = True
        export_sheets = List[DB.ElementId]()
        for sheet in sheets:
            export_sheets.Add(sheet.Id)
        if not doc.Export(dir_path, export_sheets, opt):
            raise Exception("A API do Revit retornou falha na exportacao PDF combinada.")
        return True

    @staticmethod
    def export_sheet_dwg(dir_path, sheet, opt, doc, filename):
        dwg_doc_name = op.splitext(filename)[0] + ".dwg"
        export_sheet = List[DB.ElementId]()
        export_sheet.Add(sheet.Id)
        if not doc.Export(dir_path, dwg_doc_name, export_sheet, opt):
            raise Exception("A API do Revit retornou falha na exportacao DWG.")
        return True

    @staticmethod
    def get_pdf_path(dir_path, filename):
        return op.join(dir_path, NamingFormat.verify_template(filename))

    @staticmethod
    def get_pdf_files(dir_path):
        if not op.isdir(dir_path):
            return set()
        return set(
            op.join(dir_path, fname)
            for fname in os.listdir(dir_path)
            if op.splitext(fname)[1].lower() == '.pdf'
        )

    @staticmethod
    def normalize_exported_pdf_name(dir_path, expected_filename,
                                    pdfs_before, export_start_time):
        expected_path = PrintUtils.get_pdf_path(dir_path, expected_filename)
        if op.exists(expected_path):
            return expected_path

        expected_stem = op.splitext(op.basename(expected_path))[0].lower()
        new_pdfs = [
            pdf_path for pdf_path in PrintUtils.get_pdf_files(dir_path)
            if pdf_path not in pdfs_before
            and op.getmtime(pdf_path) >= export_start_time - 2
        ]
        if not new_pdfs:
            logger.warning(
                'PDF exportado nao encontrado para renomear: %s',
                expected_path
            )
            return expected_path

        def score(pdf_path):
            pdf_stem = op.splitext(op.basename(pdf_path))[0].lower()
            if pdf_stem == expected_stem:
                return 4
            if pdf_stem.endswith(expected_stem):
                return 3
            if expected_stem in pdf_stem:
                return 2
            return 1

        exported_path = sorted(
            new_pdfs,
            key=lambda x: (score(x), op.getmtime(x)),
            reverse=True
        )[0]

        if exported_path == expected_path:
            return expected_path
        if op.exists(expected_path):
            logger.warning(
                'Nao foi possivel renomear PDF. Arquivo ja existe: %s',
                expected_path
            )
            return exported_path

        try:
            os.rename(exported_path, expected_path)
            logger.debug(
                'PDF renomeado de "%s" para "%s"',
                exported_path,
                expected_path
            )
            return expected_path
        except Exception as rename_err:
            logger.warning(
                'Nao foi possivel renomear PDF "%s" para "%s": %s',
                exported_path,
                expected_path,
                rename_err
            )
            return exported_path

    @staticmethod
    def get_dwg_path(dir_path, filename):
        return op.join(dir_path, op.splitext(filename)[0] + ".dwg")


class NamingFormat(forms.Reactive):
    """Print File Naming Format"""
    def __init__(self, name, template, builtin=False):
        self._name = name
        self._template = self.verify_template(template)
        self.builtin = builtin

    @staticmethod
    def verify_template(value):
        """Verify template is valid"""
        if not value.lower().endswith('.pdf'):
            value += '.pdf'
        return value

    @forms.reactive
    def name(self):
        """Format name"""
        return self._name

    @name.setter
    def name(self, value):
        self._name = value

    @forms.reactive
    def template(self):
        """Format template string"""
        return self._template

    @template.setter
    def template(self, value):
        self._template = self.verify_template(value)


class ViewSheetListItem(forms.Reactive):
    """Revit Sheet show in Print Window"""

    def __init__(self, view_sheet, view_tblock,
                 print_settings=None, rev_settings=None):
        self._sheet = view_sheet
        self._tblock = view_tblock
        if self._tblock:
            self._tblock_type = \
                view_sheet.Document.GetElement(view_tblock.GetTypeId())
        else:
            self._tblock_type = None
        self.name = self._sheet.Name
        self.number = self._sheet.SheetNumber if hasattr(self._sheet, 'SheetNumber') else ''
        self.issue_date = \
            self._sheet.Parameter[
                DB.BuiltInParameter.SHEET_ISSUE_DATE].AsString() if self._sheet.Parameter[
                DB.BuiltInParameter.SHEET_ISSUE_DATE] else ''
        self.printable = self._sheet.CanBePrinted
        self.revision_date_sortable = ""
        self._print_index = 0
        self._print_filename = ''

        self._tblock_psettings = print_settings or TitleBlockPrintSettings(
            psettings=[],
            set_by_param=False
        )
        self._print_settings = self._tblock_psettings.psettings
        self.all_print_settings = self._tblock_psettings.psettings
        if self.all_print_settings:
            self._print_settings = self.all_print_settings[0]
        self.read_only = self._tblock_psettings.set_by_param

        per_sheet_revisions = \
            rev_settings.RevisionNumbering == DB.RevisionNumbering.PerSheet \
            if rev_settings else False
        cur_rev = revit.query.get_current_sheet_revision(self._sheet) if hasattr(self._sheet, 'GetCurrentRevision') else ''
        self.revision = UNSET_REVISION
        if cur_rev:
            on_sheet = self._sheet if per_sheet_revisions else None
            self.revision = SheetRevision(
                number=revit.query.get_rev_number(cur_rev, sheet=on_sheet),
                desc=cur_rev.Description,
                date=cur_rev.RevisionDate,
                is_set=True
            )

    @property
    def revit_sheet(self):
        """Revit sheet instance"""
        return self._sheet

    @property
    def revit_tblock(self):
        """Revit titleblock instance"""
        return self._tblock

    @property
    def revit_tblock_type(self):
        """Revit titleblock type"""
        return self._tblock_type

    @forms.reactive
    def print_settings(self):
        """Sheet pring settings"""
        return self._print_settings

    @print_settings.setter
    def print_settings(self, value):
        self._print_settings = value

    @forms.reactive
    def print_index(self):
        """Sheet print index"""
        return self._print_index

    @print_index.setter
    def print_index(self, value):
        self._print_index = value

    @forms.reactive
    def print_filename(self):
        """Sheet print output filename"""
        return self._print_filename

    @print_filename.setter
    def print_filename(self, value):
        self._print_filename = \
            coreutils.cleanup_filename(value, windows_safe=True)


class PrintSettingListItem(forms.TemplateListItem):
    """Print Setting shown in Print Window"""

    def __init__(self, print_settings=None):
        super(PrintSettingListItem, self).__init__(print_settings)
        self.is_compatible = isinstance(self.item, DB.InSessionPrintSetting)

    @property
    def name(self):
        if isinstance(self.item, DB.InSessionPrintSetting):
            return "<Na sessao>"
        else:
            return self.item.Name

    @property
    def print_settings(self):
        return self.item

    @property
    def print_params(self):
        if self.print_settings:
            return self.print_settings.PrintParameters

    @property
    def paper_size(self):
        try:
            if self.print_params:
                return self.print_params.PaperSize
        except Exception:
            pass

    @property
    def allows_variable_paper(self):
        return False

    @property
    def is_user_defined(self):
        return not self.name.startswith('<')


class VariablePaperPrintSettingListItem(PrintSettingListItem):
    def __init__(self):
        PrintSettingListItem.__init__(self, None)
        # always compatible
        self.is_compatible = True

    @property
    def name(self):
        return "<Tamanho de papel variavel>"

    @property
    def allows_variable_paper(self):
        return True


class EditNamingFormatsWindow(forms.WPFWindow):
    def __init__(self, xaml_file_name, start_with=None):
        forms.WPFWindow.__init__(self, xaml_file_name)

        self._drop_pos = 0
        self._starting_item = start_with
        self._saved = False

        self.reset_naming_formats()
        self.reset_formatters()

    @staticmethod
    def get_default_formatters():
        return [
            NamingFormatter(
                template='{index}',
                desc='Indice de exportacao. Ex.: "0001"'
            ),
            NamingFormatter(
                template='{number}',
                desc='Numero da folha. Ex.: "A1.00"'
            ),
            NamingFormatter(
                template='{name}',
                desc='Nome da folha. Ex.: "PLANTA DO 1 PAVIMENTO"'
            ),
            NamingFormatter(
                template='{name_dash}',
                desc='Nome da folha usando - nos espacos. Ex.: "PLANTA-DO-1-PAVIMENTO"'
            ),
            NamingFormatter(
                template='{name_underline}',
                desc='Nome da folha usando _ nos espacos. Ex.: "PLANTA_DO_1_PAVIMENTO"'
            ),
            NamingFormatter(
                template='{current_date}',
                desc='Data atual. Ex.: "2019-10-12"'
            ),
            NamingFormatter(
                template='{issue_date}',
                desc='Data de emissao da folha. Ex.: "2019-10-12"'
            ),
            NamingFormatter(
                template='{rev_number}',
                desc='Numero da revisao. Ex.: "01"'
            ),
            NamingFormatter(
                template='{rev_desc}',
                desc='Descricao da revisao. Ex.: "ASI01"'
            ),
            NamingFormatter(
                template='{rev_date}',
                desc='Data da revisao. Ex.: "2019-10-12"'
            ),
            NamingFormatter(
                template='{proj_name}',
                desc='Nome do projeto. Ex.: "MEU_PROJETO"'
            ),
            NamingFormatter(
                template='{proj_number}',
                desc='Numero do projeto. Ex.: "PR2019.12"'
            ),
            NamingFormatter(
                template='{proj_building_name}',
                desc='Nome do edificio. Ex.: "BLDG01"'
            ),
            NamingFormatter(
                template='{proj_issue_date}',
                desc='Data de emissao do projeto. Ex.: "2019-10-12"'
            ),
            NamingFormatter(
                template='{proj_org_name}',
                desc='Nome da organizacao. Ex.: "MINHAEMPRESA"'
            ),
            NamingFormatter(
                template='{proj_status}',
                desc='Status do projeto. Ex.: "EXECUTIVO"'
            ),
            NamingFormatter(
                template='{username}',
                desc='Usuario ativo. Ex.: "thiago"'
            ),
            NamingFormatter(
                template='{revit_version}',
                desc='Versao ativa do Revit. Ex.: "2024"'
            ),
            NamingFormatter(
                template='{sheet_param:PARAM_NAME}',
                desc='Valor de um parametro da folha. '
                     'Troque PARAM_NAME pelo nome do parametro'
            ),
            NamingFormatter(
                template='{tblock_param:PARAM_NAME}',
                desc='Valor de um parametro do carimbo. '
                     'Troque PARAM_NAME pelo nome do parametro'
            ),
            NamingFormatter(
                template='{proj_param:PARAM_NAME}',
                desc='Valor de um parametro das informacoes do projeto. '
                     'Troque PARAM_NAME pelo nome do parametro'
            ),
            NamingFormatter(
                template='{glob_param:PARAM_NAME}',
                desc='Valor de um parametro global. '
                     'Troque PARAM_NAME pelo nome do parametro'
            ),
        ]

    @staticmethod
    def get_default_naming_formats():
        return [
            NamingFormat(
                name='0001 A1.00 PLANTA DO 1 PAVIMENTO.pdf',
                template='{index} {number} {name}.pdf',
                builtin=True
            ),
            NamingFormat(
                name='0001_A1.00_PLANTA DO 1 PAVIMENTO.pdf',
                template='{index}_{number}_{name}.pdf',
                builtin=True
            ),
            NamingFormat(
                name='0001-A1.00-PLANTA DO 1 PAVIMENTO.pdf',
                template='{index}-{number}-{name}.pdf',
                builtin=True
            ),
        ]

    @staticmethod
    def get_naming_formats():
        naming_formats = EditNamingFormatsWindow.get_default_naming_formats()
        naming_formats_dict = config.get_option('namingformats', {})
        for name, template in naming_formats_dict.items():
            naming_formats.append(NamingFormat(name=name, template=template))
        return naming_formats

    @staticmethod
    def set_naming_formats(naming_formats):
        naming_formats_dict = {
            x.name: x.template for x in naming_formats if not x.builtin
        }
        config.namingformats = naming_formats_dict
        script.save_config()

    @property
    def naming_formats(self):
        return self.formats_lb.ItemsSource

    @property
    def selected_naming_format(self):
        return self.formats_lb.SelectedItem

    @selected_naming_format.setter
    def selected_naming_format(self, value):
        self.formats_lb.SelectedItem = value
        self.namingformat_edit.DataContext = value

    def reset_formatters(self):
        self.formatters_wp.ItemsSource = \
            EditNamingFormatsWindow.get_default_formatters()

    def reset_naming_formats(self):
        self.formats_lb.ItemsSource = \
                ObjectModel.ObservableCollection[object](
                    EditNamingFormatsWindow.get_naming_formats()
                )
        if isinstance(self._starting_item, NamingFormat):
            for item in self.formats_lb.ItemsSource:
                if item.name == self._starting_item.name:
                    self.selected_naming_format = item
                    break

    # https://www.wpftutorial.net/DragAndDrop.html
    def start_drag(self, sender, args):
        name_formatter = args.OriginalSource.DataContext
        Windows.DragDrop.DoDragDrop(
            self.formatters_wp,
            Windows.DataObject("name_formatter", name_formatter),
            Windows.DragDropEffects.Copy
            )

    # https://social.msdn.microsoft.com/Forums/vstudio/en-US/941f6bf2-a321-459e-85c9-501ec1e13204/how-do-you-get-a-drag-and-drop-event-for-a-wpf-textbox-hosted-in-a-windows-form
    def preview_drag(self, sender, args):
        mouse_pos = Forms.Cursor.Position
        mouse_po_pt = Windows.Point(mouse_pos.X, mouse_pos.Y)
        self._drop_pos = \
            self.template_tb.GetCharacterIndexFromPoint(
                point=self.template_tb.PointFromScreen(mouse_po_pt),
                snapToText=True
                )
        self.template_tb.SelectionStart = self._drop_pos
        self.template_tb.SelectionLength = 0
        self.template_tb.Focus()
        args.Effects = Windows.DragDropEffects.Copy
        args.Handled = True

    def stop_drag(self, sender, args):
        name_formatter = args.Data.GetData("name_formatter")
        if name_formatter:
            new_template = \
                str(self.template_tb.Text)[:self._drop_pos] \
                + name_formatter.template \
                + str(self.template_tb.Text)[self._drop_pos:]
            self.template_tb.Text = new_template
            self.template_tb.Focus()

    def namingformat_changed(self, sender, args):
        naming_format = self.selected_naming_format
        self.namingformat_edit.DataContext = naming_format

    def duplicate_namingformat(self, sender, args):
        naming_format = self.selected_naming_format
        new_naming_format = NamingFormat(
            name='<sem nome>',
            template=naming_format.template
            )
        self.naming_formats.Add(new_naming_format)
        self.selected_naming_format = new_naming_format

    def delete_namingformat(self, sender, args):
        naming_format = self.selected_naming_format
        if naming_format.builtin:
            return
        item_index = self.naming_formats.IndexOf(naming_format)
        self.naming_formats.Remove(naming_format)
        next_index = min([item_index, self.naming_formats.Count-1])
        self.selected_naming_format = self.naming_formats[next_index]

    def save_formats(self, sender, args):
        EditNamingFormatsWindow.set_naming_formats(self.naming_formats)
        self._saved = True
        self.Close()

    def cancelled(self, sender, args):
        if not self._saved:
            self.reset_naming_formats()

    def show_dialog(self):
        self.ShowDialog()


class SheetSetList(object):
    """List of sheets from a named Revit Sheet Set."""
    def __init__(self, view_sheetset):
        self.doc = view_sheetset.Document
        self.name = view_sheetset.Name
        self.sheetset = view_sheetset

    def get_sheets(self, doc):
        if doc == self.doc:
            return list(self.sheetset.Views)
        return []


class ScheduleSheetList(object):
    def __init__(self, view_shedule):
        self.doc = view_shedule.Document
        self.name = view_shedule.Name
        self.schedule = view_shedule

    def get_sheets(self, doc):
        return self._get_ordered_schedule_sheets(doc)

    def _get_schedule_text_data(self, view_shedule):
        schedule_data_file = \
            script.get_instance_data_file(str(get_elementid_value(view_shedule.Id)))
        vseop = DB.ViewScheduleExportOptions()
        vseop.TextQualifier = coreutils.get_enum_none(DB.ExportTextQualifier)
        view_shedule.Export(op.dirname(schedule_data_file),
                            op.basename(schedule_data_file),
                            vseop)

        sched_data = []
        try:
            with codecs.open(schedule_data_file, 'r', EXPORT_ENCODING) \
                    as sched_data_file:
                return [x.strip() for x in sched_data_file.readlines()]
        except Exception as open_err:
            logger.error('Erro ao abrir exportacao do indice de folhas: %s | %s',
                         schedule_data_file, open_err)
            return sched_data

    def _order_sheets_by_schedule_data(self, view_shedule, sheet_list):
        sched_data = self._get_schedule_text_data(view_shedule)

        if not sched_data:
            return sheet_list

        ordered_sheets_dict = {}
        for sheet in sheet_list:
            logger.debug('procurando indice para: %s', sheet.SheetNumber)
            for line_no, data_line in enumerate(sched_data):
                match_pattern = r'(^|.*\t){}(\t.*|$)'.format(
                    re.escape(sheet.SheetNumber)
                    )
                matches_sheet = re.match(match_pattern, data_line)
                logger.debug('correspondencia: %s', matches_sheet)
                try:
                    if matches_sheet:
                        ordered_sheets_dict[line_no] = sheet
                        break
                    if not sheet.CanBePrinted:
                        logger.debug('Folha %s nao pode ser impressa.',
                                     sheet.SheetNumber)
                except Exception:
                    continue

        sorted_keys = sorted(ordered_sheets_dict.keys())
        return [ordered_sheets_dict[x] for x in sorted_keys]

    def _get_ordered_schedule_sheets(self, doc):
        if doc == self.doc:
            sheets = DB.FilteredElementCollector(self.doc,
                                                 self.schedule.Id)\
                    .OfClass(framework.get_type(DB.ViewSheet))\
                    .WhereElementIsNotElementType()\
                    .ToElements()

            return self._order_sheets_by_schedule_data(
                self.schedule,
                sheets
                )
        return []


class AllSheetsList(object):
    @property
    def name(self):
        return "<Todas as folhas>"

    def get_sheets(self, doc):
        return DB.FilteredElementCollector(doc)\
                 .OfClass(framework.get_type(DB.ViewSheet))\
                 .WhereElementIsNotElementType()\
                 .ToElements()


class UnlistedSheetsList(object):
    @property
    def name(self):
        return "<Folhas fora do indice>"

    def get_sheets(self, doc):
        scheduled_param_id = DB.ElementId(DB.BuiltInParameter.SHEET_SCHEDULED)
        param_prov = DB.ParameterValueProvider(scheduled_param_id)
        param_equality = DB.FilterNumericEquals()
        value_rule = DB.FilterIntegerRule(param_prov, param_equality, 0)
        param_filter = DB.ElementParameterFilter(value_rule)
        return DB.FilteredElementCollector(doc)\
                 .OfClass(framework.get_type(DB.ViewSheet))\
                 .WherePasses(param_filter) \
                 .WhereElementIsNotElementType()\
                 .ToElements()


class PrintSheetsWindow(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)

        self._output_dir = None
        self._init_psettings = None
        self._scheduled_sheets = []
        self._all_sheets_list = []

        self.project_info = revit.query.get_project_info(doc=revit.doc)
        self.sheet_cat_id = \
            revit.query.get_category(DB.BuiltInCategory.OST_Sheets).Id

        self._setup_docs_list()
        self._setup_naming_formats()
        self._setup_dwg_settings()

        self._apply_projectinfo_naming_format_default()

        self._all_sheets_list = list(self.sheets_lb.ItemsSource) \
            if self.sheets_lb.ItemsSource else []

    def copy_naming_format(self, sender, args):
        try:
            naming_format = sender.DataContext
            if not naming_format:
                return

            script.clipboard_copy(naming_format.name)

        except Exception as e:
            logger.error("Falha ao copiar formato de nomenclatura: %s", e)

    def _apply_projectinfo_naming_format_default(self):
        pi = self.selected_doc.ProjectInformation
        param = pi.LookupParameter("Formato de Nomenclatura") if pi else None
        if not param and pi:
            param = pi.LookupParameter("Naming Format")
        param_value = param.AsString() if param else None

        selected_item = next(
            (nf for nf in self.namingformat_cb.ItemsSource if nf.name == param_value),
            None
        )

        if not selected_item and self.namingformat_cb.ItemsSource:
            selected_item = self.namingformat_cb.ItemsSource[0]

        self.namingformat_cb.SelectedItem = selected_item

    def sheet_search_changed(self, sender, args):
        search_text = self.sheetsearch_tb.Text.strip().lower() \
            if self.sheetsearch_tb.Text else ''
        sheets = self._all_sheets_list or []
        filtered = [sheet for sheet in sheets
                    if not search_text
                    or search_text in (sheet.number or '').lower()
                    or search_text in (sheet.name or '').lower()]
        self.sheets_lb.ItemsSource = filtered
        self._update_sheet_summary()

    def cancel_export(self, sender, args):
        self.Close()

    def _update_sheet_summary(self):
        visible = len(list(self.sheets_lb.ItemsSource or []))
        selected = len(list(self.sheets_lb.SelectedItems))
        self.sheet_count_tb.Text = u'{} de {} folhas | {} selecionadas'.format(
            visible, len(self._all_sheets_list or []), selected)
        if visible:
            self.hide_element(self.empty_state_tb)
        else:
            self.show_element(self.empty_state_tb)

    # doc and schedule
    @property
    def selected_doc(self):
        selected_doc = self.documents_cb.SelectedItem
        if not selected_doc:
            return None
        for opened_doc in revit.docs:
            if opened_doc.GetHashCode() == selected_doc.hash:
                return opened_doc
        return revit.doc

    @property
    def selected_sheetlist(self):
        return self.schedules_cb.SelectedItem

    # misc
    @property
    def has_errors(self):
        return self.errormsg_tb.Text != ''

    @property
    def combine_print(self):
        return self.combine_cb.IsChecked

    @property
    def index_digits(self):
        scheduled_count = len(self._scheduled_sheets or [])
        return max(coreutils.get_integer_length(max(scheduled_count, 1)), 2)

    @property
    def index_start(self):
        return 1

    # print settings
    @property
    def selected_naming_format(self):
        return self.namingformat_cb.SelectedItem

    @property
    def selected_printer(self):
        return self.printers_cb.SelectedItem

    @property
    def selected_print_setting(self):
        return self.printsettings_cb.SelectedItem

    @property
    def selected_dwg_export_setup(self):
        return self.dwgsettings_cb.SelectedItem or DWG_SESSION_SETUP

    @property
    def has_print_settings(self):
        # self.selected_print_setting implements __nonzero__
        # manually check None-ness
        return self.selected_print_setting is not None

    @property
    def print_settings(self):
        return self.printsettings_cb.ItemsSource

    # sheet list
    @property
    def sheet_list(self):
        return self.sheets_lb.ItemsSource

    @sheet_list.setter
    def sheet_list(self, value):
        self.sheets_lb.ItemsSource = value

    @property
    def selected_sheets(self):
        return self.sheets_lb.SelectedItems

    @property
    def printable_sheets(self):
        return [x for x in self.sheet_list if x.printable]

    @property
    def selected_printable_sheets(self):
        return [x for x in self.selected_sheets if x.printable]

    # private utils
    def _is_sheet_index(self, schedule_view):
        return self.sheet_cat_id == schedule_view.Definition.CategoryId \
               and not schedule_view.IsTemplate

    def _get_sheet_index_list(self):
        schedules = DB.FilteredElementCollector(self.selected_doc)\
                      .OfClass(framework.get_type(DB.ViewSchedule))\
                      .WhereElementIsNotElementType()\
                      .ToElements()

        return [
            ScheduleSheetList(s) for s in schedules
            if self._is_sheet_index(s)
            ]

    def _get_printmanager(self):
        try:
            return self.selected_doc.PrintManager
        except Exception as printerr:
            logger.critical('Erro ao acessar o gerenciador de impressao. '
                            'Provavelmente nao existe uma impressora '
                            'configurada no sistema. | %s', printerr)
            script.exit()

    def _setup_docs_list(self):
        if not revit.doc.IsFamilyDocument:
            docs = [AvailableDoc(name=revit.doc.Title,
                                 hash=revit.doc.GetHashCode(),
                                 linked=False)]
            docs.extend([
                AvailableDoc(name=x.Title, hash=x.GetHashCode(), linked=True)
                for x in revit.query.get_all_linkeddocs(doc=revit.doc)
            ])
            self.documents_cb.ItemsSource = docs
            self.documents_cb.SelectedIndex = 0

    def _setup_naming_formats(self):
        self.namingformat_cb.ItemsSource = \
            EditNamingFormatsWindow.get_naming_formats()
        self.namingformat_cb.SelectedIndex = 0

    def _setup_printers(self):
        printers = list(Drawing.Printing.PrinterSettings.InstalledPrinters)

        if IS_REVIT_2022_OR_NEWER:
            printers.insert(0, INTERNAL_PDF_PRINTER)

        self.printers_cb.ItemsSource = printers
        if IS_REVIT_2022_OR_NEWER and INTERNAL_PDF_PRINTER in printers:
            self.printers_cb.SelectedItem = INTERNAL_PDF_PRINTER
        elif printers:
            print_mgr = self._get_printmanager()
            self.printers_cb.SelectedItem = print_mgr.PrinterName
        else:
            forms.alert("Nenhuma impressora esta instalada neste sistema.",
                        exitscript=True)

    def _setup_dwg_settings(self):
        setup_names = PrintUtils.get_dwg_setup_names(self.selected_doc)
        self.dwgsettings_cb.ItemsSource = setup_names
        self.dwgsettings_cb.SelectedIndex = 0

    def _get_psetting_items(self, doc,
                            psettings=None, include_varsettings=False):
        if include_varsettings:
            psetting_items = [VariablePaperPrintSettingListItem()]
        else:
            psetting_items = []

        psettings = psettings or revit.query.get_all_print_settings(doc=doc)
        psetting_items.extend([PrintSettingListItem(x) for x in psettings])

        print_mgr = self._get_printmanager()
        compatible_sizes = {x.Name for x in print_mgr.PaperSizes}
        for psetting_item in psetting_items:
            if isinstance(psetting_item, PrintSettingListItem):
                if psetting_item.paper_size \
                        and psetting_item.paper_size.Name in compatible_sizes:
                    psetting_item.is_compatible = True
        return psetting_items

    def _setup_print_settings(self):
        psetting_items = \
            self._get_psetting_items(
                doc=self.selected_doc,
                include_varsettings=not self.selected_doc.IsLinked
                )
        self.printsettings_cb.ItemsSource = psetting_items

        print_mgr = self._get_printmanager()
        if isinstance(print_mgr.PrintSetup.CurrentPrintSetting,
                      DB.InSessionPrintSetting):
            in_session = PrintSettingListItem(
                print_mgr.PrintSetup.CurrentPrintSetting
                )
            psetting_items.append(in_session)
            self.printsettings_cb.SelectedItem = in_session
        else:
            self._init_psettings = print_mgr.PrintSetup.CurrentPrintSetting
            cur_psetting_name = print_mgr.PrintSetup.CurrentPrintSetting.Name
            for psetting_item in psetting_items:
                if psetting_item.name == cur_psetting_name:
                    self.printsettings_cb.SelectedItem = psetting_item

        if self.selected_doc.IsLinked:
            self.disable_element(self.printsettings_cb)
        else:
            self.enable_element(self.printsettings_cb)

        self._update_combine_option()

    def _update_combine_option(self):
        if self._export_pdf_selected():
            self.enable_element(self.combine_cb)
        else:
            self.disable_element(self.combine_cb)
            self.combine_cb.IsChecked = False
            return

        if self.selected_doc.IsLinked \
                or ((self.selected_sheetlist and self.has_print_settings)
                    and self.selected_print_setting.allows_variable_paper):
            self.disable_element(self.combine_cb)
            self.combine_cb.IsChecked = False

    def _setup_sheet_list(self):
        sheet_indices = self._get_sheet_index_list()
        try:
            cl = DB.FilteredElementCollector(self.selected_doc)
            sheetsets = cl.OfClass(framework.get_type(DB.ViewSheetSet)).WhereElementIsNotElementType().ToElements()
            for ss in sheetsets:
                sheet_indices.append(SheetSetList(ss))
        except Exception as e:
            logger.warning("Nao foi possivel carregar os conjuntos de folhas: {}".format(e))
        sheet_indices.append(AllSheetsList())
        sheet_indices.append(UnlistedSheetsList())

        self.schedules_cb.ItemsSource = sheet_indices
        self.schedules_cb.SelectedIndex = 0
        if self.schedules_cb.ItemsSource:
            self.enable_element(self.schedules_cb)
        else:
            self.disable_element(self.schedules_cb)

    def _verify_print_filename(self, sheet_name, sheet_print_filepath):
        if op.exists(sheet_print_filepath):
            logger.warning(
                "Folha \"%s\" ignorada. "
                "O arquivo ja existe em %s.",
                sheet_name, sheet_print_filepath
                )
            return False
        return True

    def choose_output_folder(self, sender, args):
        dialog = Forms.FolderBrowserDialog()
        try:
            dialog.Description = 'Escolha onde salvar os arquivos PDF e DWG'
            dialog.ShowNewFolderButton = True
            if self._output_dir:
                dialog.SelectedPath = self._output_dir
            if dialog.ShowDialog() == Forms.DialogResult.OK:
                self._output_dir = dialog.SelectedPath
                self.output_folder_tb.Text = self._output_dir
        finally:
            dialog.Dispose()

    def _validate_output_dir(self):
        if not self._output_dir:
            self.choose_output_folder(None, None)
        if not self._output_dir:
            return False
        try:
            if not op.isdir(self._output_dir):
                raise IOError('A pasta selecionada nao esta disponivel.')
            # Verify actual write access, including network folders.
            with tempfile.TemporaryFile(dir=self._output_dir) as probe:
                probe.write(b'export')
                probe.flush()
        except (IOError, OSError) as folder_err:
            forms.alert('Nao foi possivel gravar na pasta selecionada. '
                        'Escolha outra pasta de destino.',
                        expanded=str(folder_err))
            return False
        return True

    def _get_output_dir(self):
        return self._output_dir

    def _use_native_pdf_export(self):
        return IS_REVIT_2022_OR_NEWER \
            and self.selected_printer == INTERNAL_PDF_PRINTER

    def _export_pdf_selected(self):
        return bool(self.export_pdf.IsChecked)

    def _export_dwg_selected(self):
        return bool(self.export_dwg.IsChecked)

    def _iter_printable_named_sheets(self, target_sheets, step_count=1):
        for sheet in target_sheets:
            if not sheet.printable:
                logger.debug('Folha %s nao pode ser impressa. Ignorando.',
                             sheet.number)
                yield sheet, False, step_count
            elif not sheet.print_filename:
                logger.debug('Folha %s nao possui um nome de arquivo valido.',
                             sheet.number)
                yield sheet, False, step_count
            else:
                yield sheet, True, 0

    def _export_pdf_sheet(self, print_mgr, doc, dir_path, sheet):
        print_filepath = PrintUtils.get_pdf_path(dir_path, sheet.print_filename)
        print_mgr.PrintToFileName = print_filepath
        if not self._verify_print_filename(sheet.name, print_filepath):
            return False

        pdfs_before = PrintUtils.get_pdf_files(dir_path)
        export_start_time = time.time()
        if self._use_native_pdf_export():
            PrintUtils.export_sheet_pdf(
                dir_path,
                sheet.revit_sheet,
                PrintUtils.pdf_opts(),
                doc,
                sheet.print_filename
                )
        else:
            print_mgr.SubmitPrint(sheet.revit_sheet)
        PrintUtils.normalize_exported_pdf_name(
            dir_path,
            sheet.print_filename,
            pdfs_before,
            export_start_time
        )
        return True

    def _export_dwg_sheet(self, doc, dir_path, sheet):
        dwg_filepath = PrintUtils.get_dwg_path(dir_path, sheet.print_filename)
        if not self._verify_print_filename(sheet.name, dwg_filepath):
            return False

        PrintUtils.export_sheet_dwg(
            dir_path,
            sheet.revit_sheet,
            PrintUtils.dwg_opts(
                doc=doc,
                setup_name=self.selected_dwg_export_setup
                ),
            doc,
            sheet.print_filename
            )
        return True

    def _export_individual_sheets(self, target_sheets, print_mgr, doc,
                                  dir_path, per_sheet_psettings,
                                  export_pdf=True, export_dwg=False,
                                  title='Exportando PDFs... '):
        steps_per_sheet = int(bool(export_pdf)) + int(bool(export_dwg))
        if not steps_per_sheet:
            return
        pb_total = len(target_sheets) * steps_per_sheet
        pb_count = 1

        with forms.ProgressBar(
                step=1,
                title=title + '{value} of {max_value}',
                cancellable=True) as progress:
            for sheet, _, skip_steps in self._iter_printable_named_sheets(
                    target_sheets, steps_per_sheet):
                if progress.cancelled:
                    break
                if skip_steps:
                    pb_count += skip_steps
                    continue
                if per_sheet_psettings:
                    print_mgr.PrintSetup.CurrentPrintSetting = sheet.print_settings

                if export_pdf:
                    try:
                        progress.update_progress(pb_count, pb_total)
                        self._export_pdf_sheet(print_mgr, doc, dir_path, sheet)
                    except Exception as export_err:
                        logger.error('Falha ao exportar PDF da folha %s: %s',
                                     sheet.number, export_err)
                    finally:
                        pb_count += 1

                if export_dwg:
                    try:
                        progress.update_progress(pb_count, pb_total)
                        self._export_dwg_sheet(doc, dir_path, sheet)
                    except Exception as export_err:
                        logger.error('Falha ao exportar DWG da folha %s: %s',
                                     sheet.number, export_err)
                    finally:
                        pb_count += 1

    def _print_combined_sheets_in_order(self, target_sheets):
        if self._use_native_pdf_export():
            dir_path = self._get_output_dir()
            output_name = 'Conjunto de Folhas Ordenado.pdf'
            output_path = PrintUtils.get_pdf_path(dir_path, output_name)
            if not self._verify_print_filename('Conjunto de Folhas Ordenado', output_path):
                return

            printable_sheets = [
                sheet.revit_sheet for sheet in target_sheets if sheet.printable
            ]
            if not printable_sheets:
                forms.alert('Nao ha folhas imprimiveis para exportar.')
                return

            try:
                PrintUtils.export_sheets_pdf(
                    dir_path,
                    printable_sheets,
                    PrintUtils.pdf_opts(),
                    self.selected_doc,
                    output_name
                    )
                PrintUtils.open_dir(dir_path)
            except Exception as export_err:
                logger.error('Falha ao exportar PDF combinado: %s', export_err)
                forms.alert('Falha ao exportar PDF combinado.',
                            expanded=str(export_err))
            return

        # make sure we can access the print config
        print_mgr = self._get_printmanager()
        if not print_mgr:
            forms.alert(
                "Erro ao acessar o gerenciador de impressao deste documento",
                exitscript=True
                )
        with revit.TransactionGroup('Exportar Folhas em Ordem',
                                    doc=self.selected_doc):
            with revit.Transaction('Definir Configuracoes de Impressao',
                                   doc=self.selected_doc,
                                   log_errors=False):
                try:
                    print_mgr.PrintSetup.CurrentPrintSetting = \
                        self.selected_print_setting.print_settings
                    print_mgr.SelectNewPrintDriver(self.selected_printer)
                    print_mgr.PrintRange = DB.PrintRange.Select
                except Exception as cpSetEx:
                    forms.alert(
                        "A configuracao de impressao e incompativel com a impressora.",
                        expanded=str(cpSetEx)
                        )
                    return
            # The OrderedViewList property was added to the IViewSheetSet
            # interface in Revit 2023 and makes the non-printable char
            # technique unnecessary.
            supports_OrderedViewList = HOST_APP.is_newer_than(2022)
            original_sheetnums = []

            def restore_legacy_sheet_numbers():
                if supports_OrderedViewList or not original_sheetnums:
                    return
                with revit.Transaction('Restaurar Numeros das Folhas',
                                       doc=self.selected_doc):
                    for sheet, sheetnum in zip(target_sheets,
                                               original_sheetnums):
                        sheet.revit_sheet.SheetNumber = sheetnum

            if supports_OrderedViewList:
                sheet_list = List[DB.View]()
                for sheet in target_sheets:
                    if sheet.printable:
                        sheet_list.Add(sheet.revit_sheet)
            else:
                # add non-printable char in front of sheet Numbers
                # to push revit to sort them per user
                sheet_set = DB.ViewSet()
                with revit.Transaction('Ajustar Numeros das Folhas',
                                       doc=self.selected_doc):
                    for idx, sheet in enumerate(target_sheets):
                        rvtsheet = sheet.revit_sheet
                        # removing any NPC from previous failed prints
                        if NPC in rvtsheet.SheetNumber:
                            rvtsheet.SheetNumber = \
                                rvtsheet.SheetNumber.replace(NPC, '')
                        # create a list of the existing sheet numbers
                        original_sheetnums.append(rvtsheet.SheetNumber)
                        # add a prefix (NPC) for sorting purposes
                        rvtsheet.SheetNumber = \
                            NPC * (idx + 1) + rvtsheet.SheetNumber
                        if sheet.printable:
                            sheet_set.Insert(rvtsheet)

            # Collect existing sheet sets
            cl = DB.FilteredElementCollector(self.selected_doc)
            viewsheetsets = cl.OfClass(framework.get_type(DB.ViewSheetSet))\
                              .WhereElementIsNotElementType()\
                              .ToElements()
            all_viewsheetsets = {vss.Name: vss for vss in viewsheetsets}

            sheetsetname = 'OrderedPrintSet'

            with revit.Transaction('Remover Conjunto de Impressao Anterior',
                                   doc=self.selected_doc):
                # Delete existing matching sheet set
                if sheetsetname in all_viewsheetsets:
                    print_mgr.ViewSheetSetting.CurrentViewSheetSet = \
                        all_viewsheetsets[sheetsetname]
                    print_mgr.ViewSheetSetting.Delete()

            with revit.Transaction('Atualizar Conjunto de Impressao Ordenado',
                                   doc=self.selected_doc):
                try:
                    viewsheet_settings = print_mgr.ViewSheetSetting
                    if supports_OrderedViewList:
                        viewsheet_settings.CurrentViewSheetSet.IsAutomatic = False
                        viewsheet_settings.CurrentViewSheetSet.OrderedViewList = \
                            sheet_list
                    else:
                        viewsheet_settings.CurrentViewSheetSet.Views = \
                            sheet_set
                    viewsheet_settings.SaveAs(sheetsetname)
                except Exception as viewset_err:
                    sheet_report = ''
                    report_sheets = sheet_set if not supports_OrderedViewList \
                        else [x.revit_sheet for x in target_sheets]
                    for sheet in report_sheets:
                        sheet_report += '{} {}\n'.format(
                            sheet.SheetNumber if isinstance(sheet,
                                                            DB.ViewSheet)
                            else '---',
                            type(sheet)
                            )
                    logger.critical(
                        'Erro ao definir o conjunto de folhas no mecanismo '
                        'de impressao. Estes itens estao no objeto viewset:\n%s',
                        sheet_report
                        )
                    restore_legacy_sheet_numbers()
                    raise viewset_err

            # set print job configurations
            print_mgr.PrintOrderReverse = False
            try:
                print_mgr.CombinedFile = True
            except Exception as e:
                forms.alert(str(e) +
                            '\nConfigure a impressora corretamente nas configuracoes de impressao.')
                script.exit()
            dir_path = self._get_output_dir()
            print_filepath = PrintUtils.get_pdf_path(
                dir_path,
                'Conjunto de Folhas Ordenado.pdf'
                )
            PrintUtils.open_dir(dir_path)
            print_mgr.PrintToFile = True
            print_mgr.PrintToFileName = print_filepath
            if not self._verify_print_filename('Conjunto de Folhas Ordenado',
                                               print_filepath):
                restore_legacy_sheet_numbers()
                return

            with revit.Transaction('Recarregar Arquivo de Keynote',
                                   doc=self.selected_doc):
                DB.KeynoteTable.GetKeynoteTable(revit.doc).Reload(None)
            try:
                print_mgr.Apply()
                print_mgr.SubmitPrint()
            finally:
                restore_legacy_sheet_numbers()

            self._reset_psettings()

    def _print_sheets_in_order(self, target_sheets):
        # make sure we can access the print config
        print_mgr = self._get_printmanager()
        print_mgr.PrintToFile = True
        per_sheet_psettings = self.selected_print_setting.allows_variable_paper

        # make sure you can print, construct print path and make directory
        dir_path = self._get_output_dir()
        doc = self.selected_doc

        if self.selected_printer == INTERNAL_PDF_PRINTER or self._export_dwg_selected():
            PrintUtils.open_dir(dir_path)
        with revit.Transaction('Recarregar Arquivo de Keynote',
                               doc=self.selected_doc):
            DB.KeynoteTable.GetKeynoteTable(self.selected_doc).Reload(None)

        with revit.DryTransaction('Definir Configuracoes de Impressao',
                                  doc=self.selected_doc):
            try:
                if not per_sheet_psettings:
                    print_mgr.PrintSetup.CurrentPrintSetting = \
                        self.selected_print_setting.print_settings
                if not self._use_native_pdf_export():
                    print_mgr.SelectNewPrintDriver(self.selected_printer)
                print_mgr.PrintRange = DB.PrintRange.Current
            except Exception as cpSetEx:
                forms.alert(
                    "A configuracao de impressao e incompativel com a impressora.",
                    expanded=str(cpSetEx)
                    )
                return
            if target_sheets:
                export_pdf = self._export_pdf_selected()
                export_dwg = self._export_dwg_selected()
                if export_pdf and export_dwg:
                    progress_title = 'Exportando PDF e DWGs... '
                elif export_dwg:
                    progress_title = 'Exportando DWGs... '
                else:
                    progress_title = 'Exportando PDFs... '
                self._export_individual_sheets(
                    target_sheets,
                    print_mgr,
                    doc,
                    dir_path,
                    per_sheet_psettings,
                    export_pdf=export_pdf,
                    export_dwg=export_dwg,
                    title=progress_title
                    )

    def _print_linked_sheets_in_order(self, target_sheets, target_doc):
        # make sure we can access the print config
        print_mgr = self._get_printmanager()
        print_mgr.PrintToFile = True
        if not self._use_native_pdf_export():
            print_mgr.SelectNewPrintDriver(self.selected_printer)
        print_mgr.PrintRange = DB.PrintRange.Current

        dir_path = self._get_output_dir()
        doc = target_doc

        if self.selected_printer == INTERNAL_PDF_PRINTER:
            PrintUtils.open_dir(dir_path)

        if target_sheets:
            self._export_individual_sheets(
                target_sheets,
                print_mgr,
                doc,
                dir_path,
                per_sheet_psettings=False,
                export_dwg=False,
                title='Exportando PDFs vinculados... '
                )

    def _reset_error(self):
        self.enable_element(self.print_b)
        self.hide_element(self.errormsg_block)
        self.errormsg_tb.Text = ''

    def _set_error(self, err_msg):
        if self.errormsg_tb.Text != err_msg:
            self.disable_element(self.print_b)
            self.show_element(self.errormsg_block)
            self.errormsg_tb.Text = err_msg

    def _update_print_indices(self, sheet_list):
        start_idx = self.index_start
        for idx, sheet in enumerate(sheet_list):
            sheet.print_index = INDEX_FORMAT\
                .format(digits=self.index_digits)\
                .format(idx + start_idx)

    def _update_filename_template(self, template, value_type, value_getter):
        finder_pattern = r'{' + value_type + r':(.*?)}'
        for param_name in re.findall(finder_pattern, template):
            try:
                param_value = value_getter(param_name)
            except Exception as param_err:
                logger.debug(
                    'Nao foi possivel resolver o parametro %s "%s": %s',
                    value_type,
                    param_name,
                    param_err
                    )
                param_value = None
            repl_pattern = '{' + value_type + ':' + param_name + '}'
            if param_value:
                template = template.replace(repl_pattern, str(param_value))
            template = template.replace(repl_pattern, '')
        return template

    @staticmethod
    def _get_param_value(element, param_name):
        if not element:
            return None
        return revit.query.get_param_value(
            revit.query.get_param(element, param_name)
            )

    def _update_print_filename(self, template, sheet):
        # resolve sheet-level custom param values
        # get titleblock param values
        template = self._update_filename_template(
            template=template,
            value_type='tblock_param',
            value_getter=lambda x: self._get_param_value(
                sheet.revit_tblock, x
                ) or self._get_param_value(sheet.revit_tblock_type, x)
        )

        # get sheet param values
        template = self._update_filename_template(
            template=template,
            value_type='sheet_param',
            value_getter=lambda x: self._get_param_value(sheet.revit_sheet, x)
        )

        # get date for sortable list
        rev_date_str = sheet.revision.date or ""
        sortable_date = ""

        # Try to detect user's locale
        locale_tuple = locale.getdefaultlocale()
        user_locale = (locale_tuple[0] if locale_tuple and locale_tuple[0] else "en_GB")
        dayfirst = not user_locale.startswith("en_US")

        # Try several common patterns
        date_formats = ["%d.%m.%y", "%m.%d.%y", "%d/%m/%y", "%m/%d/%y"]
        if not dayfirst:
            date_formats = ["%m.%d.%y", "%m/%d/%y", "%d.%m.%y", "%d/%m/%y"]

        for fmt in date_formats:
            try:
                parsed = datetime.datetime.strptime(rev_date_str, fmt)
                sortable_date = parsed.strftime("%Y%m%d")
                break
            except (ValueError, TypeError):
                continue

        sheet.revision_date_sortable = sortable_date
        # resolved the fixed formatters
        try:
            output_fname = \
                template.format(
                    index=sheet.print_index,
                    number=sheet.number,
                    name=sheet.name,
                    name_dash=sheet.name.replace(' ', '-'),
                    name_underline=sheet.name.replace(' ', '_'),
                    current_date=coreutils.current_date(),
                    issue_date=sheet.issue_date,
                    rev_number=sheet.revision.number if sheet.revision else '',
                    rev_desc=sheet.revision.desc if sheet.revision else '',
                    rev_date=sheet.revision.date if sheet.revision else '',
                    proj_name=self.project_info.name,
                    proj_number=self.project_info.number,
                    proj_building_name=self.project_info.building_name,
                    proj_issue_date=self.project_info.issue_date,
                    proj_org_name=self.project_info.org_name,
                    proj_status=self.project_info.status,
                    username=HOST_APP.username,
                    revit_version=HOST_APP.version,
                )
        except Exception as ferr:
            output_fname = ''
            if isinstance(ferr, KeyError):
                self._set_error('Chave desconhecida no formato de nomenclatura selecionado')
        # and set the sheet file name
        sheet.print_filename = output_fname

    def _update_print_filenames(self, sheet_list):
        doc = self.selected_doc
        naming_fmt = self.selected_naming_format
        if naming_fmt:
            template = naming_fmt.template
            # resolve project-level custom param values
            # project info param values
            template = self._update_filename_template(
                template=template,
                value_type='proj_param',
                value_getter=lambda x: revit.query.get_param_value(
                    doc.ProjectInformation.LookupParameter(x)
                    )
            )

            # global param values
            template = self._update_filename_template(
                template=template,
                value_type='glob_param',
                value_getter=lambda x: revit.query.get_param_value(
                    revit.query.get_global_parameter(x, doc=doc)
                    )
            )

            for sheet in sheet_list:
                self._update_print_filename(template, sheet)

    def _find_sheet_tblock(self, revit_sheet, tblocks):
        for tblock in tblocks:
            view_sheet = revit_sheet.Document.GetElement(tblock.OwnerViewId)
            if view_sheet.Id == revit_sheet.Id:
                return tblock

    def _get_sheet_printsettings(self, tblocks, psettings):
        tblock_printsettings = {}
        sheet_printsettings = {}
        for tblock in tblocks:
            tblock_psetting = None
            sheet = self.selected_doc.GetElement(tblock.OwnerViewId)
            # build a unique id for this tblock
            tblock_tform = tblock.GetTotalTransform()
            tblock_tid = get_elementid_value(tblock.GetTypeId())
            tblock_tid = tblock_tid * 100 + tblock_tform.BasisX.X * 10 + tblock_tform.BasisX.Y
            # can not use None as default. see notes below
            tblock_psetting = tblock_printsettings.get(tblock_tid, None)
            # if found a tblock print settings, assign that to sheet
            if tblock_psetting:
                sheet_printsettings[sheet.SheetNumber] = tblock_psetting
            # otherwise, analyse the tblock and determine print settings
            else:
                # try the type parameter "Print Setting"
                tblock_type = tblock.Document.GetElement(tblock.GetTypeId())
                if tblock_type:
                    psparam = tblock_type.LookupParameter("Configuracao de Impressao")
                    if not psparam:
                        psparam = tblock_type.LookupParameter("Print Setting")
                    if psparam:
                        psetting_name = psparam.AsString()
                        psparam_psetting = \
                            next(
                                (x for x in psettings
                                    if x.Name == psetting_name),
                                None
                            )
                        if psparam_psetting:
                            tblock_psetting = \
                                TitleBlockPrintSettings(
                                    psettings=[psparam_psetting],
                                    set_by_param=True
                                )
                # otherwise, try to detect applicable print settings
                # based on title block geometric properties
                if not tblock_psetting:
                    tblock_psetting = \
                        TitleBlockPrintSettings(
                            psettings=revit.query.get_titleblock_print_settings(
                                tblock,
                                self.selected_printer,
                                psettings
                                ),
                            set_by_param=False
                        )
                # the analysis result might be None
                tblock_printsettings[tblock_tid] = tblock_psetting
                sheet_printsettings[sheet.SheetNumber] = tblock_psetting
        return sheet_printsettings

    def _reset_psettings(self):
        if self._init_psettings:
            print_mgr = self._get_printmanager()
            with revit.Transaction("Restaurar Configuracoes de Impressao Originais"):
                print_mgr.PrintSetup.CurrentPrintSetting = self._init_psettings

    # event handlers
    def doclist_changed(self, sender, args):
        self.project_info = revit.query.get_project_info(doc=self.selected_doc)
        self._setup_printers()
        self._setup_print_settings()
        self._setup_dwg_settings()
        self._setup_sheet_list()

    def sheetlist_changed(self, sender, args):
        print_settings = None
        tblocks = revit.query.get_elements_by_categories(
            [DB.BuiltInCategory.OST_TitleBlocks],
            doc=self.selected_doc
        )
        if self.selected_sheetlist and self.has_print_settings:
            rev_cfg = DB.RevisionSettings.GetRevisionSettings(self.selected_doc)
            if self.selected_print_setting.allows_variable_paper:
                sheet_printsettings = \
                    self._get_sheet_printsettings(
                        tblocks,
                        revit.query.get_all_print_settings(
                            doc=self.selected_doc
                            )
                        )
                self.show_element(self.varsizeguide)
                self.show_element(self.psettingcol)
                self._scheduled_sheets = [
                    ViewSheetListItem(
                        view_sheet=x,
                        view_tblock=self._find_sheet_tblock(x, tblocks),
                        print_settings=sheet_printsettings.get(
                            x.SheetNumber,
                            None),
                        rev_settings=rev_cfg)
                    for x in self.selected_sheetlist.get_sheets(
                        doc=self.selected_doc
                        )
                    ]
            else:
                print_settings = self.selected_print_setting.print_settings
                self.hide_element(self.varsizeguide)
                self.hide_element(self.psettingcol)
                self._scheduled_sheets = [
                    ViewSheetListItem(
                        view_sheet=x,
                        view_tblock=self._find_sheet_tblock(x, tblocks),
                        print_settings=TitleBlockPrintSettings(
                            psettings=[print_settings],
                            set_by_param=False
                        ),
                        rev_settings=rev_cfg)
                    for x in self.selected_sheetlist.get_sheets(
                        doc=self.selected_doc
                        )
                    ]
        self._update_combine_option()
        self.options_changed(None, None)

    def printers_changed(self, sender, args):
        print_mgr = self._get_printmanager()

        if self.selected_printer == INTERNAL_PDF_PRINTER:
            return
        print_mgr.SelectNewPrintDriver(self.selected_printer)
        self._setup_print_settings()

    def options_changed(self, sender, args):
        self._reset_error()
        self._update_combine_option()

        sheet_list = [x for x in self._scheduled_sheets if x.printable]
        self._update_print_indices(sheet_list)

        if self.combine_cb.IsChecked:
            self.hide_element(self.namingformat_dp)
            self.hide_element(self.pfilename)
            self.export_dwg.IsChecked = False
            self.export_dwg.IsEnabled = False
            self.disable_element(self.dwgsettings_dp)
        else:
            self.show_element(self.namingformat_dp)
            self.show_element(self.pfilename)
            self.export_dwg.IsEnabled = True
            if self.export_dwg.IsChecked:
                self.enable_element(self.dwgsettings_dp)
            else:
                self.disable_element(self.dwgsettings_dp)

        if self.selected_doc.IsLinked:
            self.export_dwg.IsChecked = False
            self.export_dwg.IsEnabled = False
            self.disable_element(self.dwgsettings_dp)

        if not self._export_pdf_selected() and not self._export_dwg_selected():
            self._set_error('Selecione PDF, DWG ou ambos para exportar.')

        self.sheet_list = sheet_list

        self._all_sheets_list = list(self.sheet_list or [])
        self.sheet_search_changed(None, None)

        # update sheet naming formats
        self._update_print_filenames(sheet_list)

    def set_sheet_printsettings(self, sender, args):
        if self.selected_printable_sheets:
            # make sure none of the sheets has readonly print setting
            if any(x.read_only for x in self.selected_printable_sheets):
                forms.alert("A configuracao de impressao foi definida pelo "
                            "carimbo em uma ou mais folhas e so pode ser "
                            "alterada no parametro do tipo de carimbo.")
                return

            all_psettings = \
                [x for x in self.print_settings if x.is_user_defined]
            sheet_psettings = \
                self.selected_printable_sheets[0].all_print_settings
            if sheet_psettings:
                options = {
                    'Configuracoes compativeis':
                        self._get_psetting_items(
                            doc=self.selected_doc,
                            psettings=sheet_psettings
                            ),
                    'Todas as configuracoes':
                        all_psettings
                }
            else:
                options = all_psettings or []

            if options:
                psetting_item = forms.SelectFromList.show(
                    options,
                    name_attr='name',
                    group_selector_title='Configuracoes de impressao:',
                    default_group='Configuracoes compativeis',
                    title='Selecionar configuracao de impressao',
                    item_container_template=self.Resources["printSettingsItem"],
                    width=450, height=400
                    )
                if psetting_item:
                    for sheet in self.selected_printable_sheets:
                        sheet.print_settings = psetting_item
            else:
                forms.alert('Nao ha configuracoes de impressao neste modelo.')

    def sheet_selection_changed(self, sender, args):
        self._update_sheet_summary()
        if self.selected_printable_sheets:
            return self.enable_element(self.sheetopts_wp)
        self.disable_element(self.sheetopts_wp)

    def edit_formats(self, sender, args):
        editfmt_wnd = \
            EditNamingFormatsWindow(
                'EditNamingFormats.xaml',
                start_with=self.selected_naming_format
                )
        editfmt_wnd.show_dialog()
        self.namingformat_cb.ItemsSource = editfmt_wnd.naming_formats
        self.namingformat_cb.SelectedItem = editfmt_wnd.selected_naming_format

    def copy_filenames(self, sender, args):
        if self.selected_sheets:
            filenames = [x.print_filename for x in self.selected_sheets]
            script.clipboard_copy('\n'.join(filenames))

    def print_sheets(self, sender, args):
        if self.sheet_list:
            if not self._export_pdf_selected() and not self._export_dwg_selected():
                forms.alert('Selecione PDF, DWG ou ambos para exportar.')
                return

            if not self.has_print_settings:
                forms.alert('Nenhuma configuracao de impressao foi selecionada.')
                return

            selected_only = False
            if self.selected_sheets:
                opts = forms.alert(
                    "Ha folhas selecionadas. Deseja exportar somente as "
                    "folhas selecionadas ou todas as folhas da lista?",
                    options=["Somente selecionadas", "Todas da lista"]
                    )
                selected_only = opts == "Somente selecionadas"

            target_sheets = \
                self.selected_sheets if selected_only else self.sheet_list

            if not self.combine_print:
                # verify all sheets have print settings
                if (self.selected_print_setting.allows_variable_paper
                        and not all(x.print_settings for x in target_sheets)):
                    forms.alert(
                        'Nem todas as folhas possuem configuracao de impressao. '
                        'Selecione as folhas e atribua uma configuracao.')
                    return
                # confirm print if a lot of sheets are going to be printed
                printable_count = len([x for x in target_sheets if x.printable])
                if printable_count > 5:
                    # prepare warning message
                    sheet_count = len(target_sheets)
                    message = str(printable_count)
                    if printable_count != sheet_count:
                        message += ' (de {} no total)'.format(sheet_count)

                    if not forms.alert('Deseja exportar {} folhas '
                                       'individualmente? O processo nao pode '
                                       'ser cancelado.'.format(message),
                                       ok=False, yes=True, no=True):
                        return
            if not self._validate_output_dir():
                return

            # close window and submit print
            self.Close()
            if self.combine_print:
                self._print_combined_sheets_in_order(target_sheets)
            else:
                if self.selected_doc.IsLinked:
                    self._print_linked_sheets_in_order(target_sheets, self.selected_doc)
                else:
                    self._print_sheets_in_order(target_sheets)


def cleanup_sheetnumbers(doc):
    sheets = revit.query.get_sheets(doc=doc)
    with revit.Transaction('Limpar Numeros das Folhas', doc=doc):
        for sheet in sheets:
            sheet.SheetNumber = sheet.SheetNumber.replace(NPC, '')


# verify model is printable
forms.check_modeldoc(exitscript=True)
# ensure there is nothing selected
revit.selection.get_selection().clear()

# TODO: add copy filenames to sheet list
if EXEC_PARAMS.config_mode:
    open_docs = forms.select_open_docs(check_more_than_one=False)
    if open_docs:
        for open_doc in open_docs:
            cleanup_sheetnumbers(open_doc)
else:
    PrintSheetsWindow('PrintSheets.xaml').ShowDialog()
