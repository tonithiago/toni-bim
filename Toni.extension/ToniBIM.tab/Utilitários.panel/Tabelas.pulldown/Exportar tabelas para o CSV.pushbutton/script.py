# -*- coding: utf-8 -*-
"""Exporta as tabelas selecionadas para arquivos CSV.

Shift + Clique:
Permite escolher entre locais padrão de exportação.
"""
#pylint: disable=C0103,E0401

import os.path as op

from pyrevit import forms
from pyrevit import coreutils
from pyrevit import revit, DB
from pyrevit import script

from pyrevit.userconfig import user_config


logger = script.get_logger()
output = script.get_output()

open_exported = False
incl_headers = False
basefolder = ''

# Se o usuário usar Shift + Clique, abrir opções automáticas
if __shiftclick__:  #pylint: disable=E0602
    destopt, switches = forms.CommandSwitchWindow.show(
        ["Área de Trabalho", "Pasta do Modelo Revit", "Meus Downloads", "Selecionar Pasta"],
        switches=["Abrir Arquivo CSV", "Incluir Cabeçalhos"],
        message="Selecione o destino da exportação:"
    )

    if destopt == "Área de Trabalho":
        basefolder = op.expandvars('%userprofile%\\desktop')
    elif destopt == "Meus Downloads":
        basefolder = op.expandvars('%userprofile%\\downloads')
    elif destopt == "Pasta do Modelo Revit":
        central_path = revit.query.get_central_path()
        if central_path:
            basefolder = op.dirname(central_path)
        else:
            basefolder = revit.query.get_project_info().location
            if not basefolder:
                forms.alert("O projeto ainda não foi salvo.", exitscript=True)
    elif destopt == "Selecionar Pasta":
        basefolder = forms.pick_folder()

    open_exported = switches["Abrir Arquivo CSV"]
    incl_headers = switches["Incluir Cabeçalhos"]
else:
    basefolder = forms.pick_folder()

if basefolder:
    logger.debug(basefolder)
    schedules_to_export = forms.select_schedules()

    if schedules_to_export:
        vseop = DB.ViewScheduleExportOptions()
        if incl_headers:
            vseop.ColumnHeaders = coreutils.get_enum_value(DB.ExportColumnHeaders, "OneRow")
        else:
            vseop.ColumnHeaders = coreutils.get_enum_none(DB.ExportColumnHeaders)

        vseop.TextQualifier = DB.ExportTextQualifier.DoubleQuote

        # Detectar o separador regional
        csv_sp = ','
        regional_sep = user_config.get_list_separator()
        if regional_sep != ',':
            if forms.alert(
                'O separador de listas da sua configuração regional é "{}"\n'
                'Deseja usar esse separador em vez de vírgula?'.format(regional_sep),
                yes=True,
                no=True
            ):
                csv_sp = regional_sep

        if csv_sp:
            vseop.FieldDelimiter = csv_sp
            vseop.Title = False
            vseop.HeadersFootersBlanks = False

            for sched in schedules_to_export:
                fname = coreutils.cleanup_filename(revit.query.get_name(sched)) + '.csv'
                sched.Export(basefolder, fname, vseop)
                exported = op.join(basefolder, fname)
                revit.files.correct_text_encoding(exported)
                output.print_md("**EXPORTADO:** {0}".format(revit.query.get_name(sched)))
                print(exported)
                if open_exported:
                    coreutils.run_process('"%s"' % exported)
