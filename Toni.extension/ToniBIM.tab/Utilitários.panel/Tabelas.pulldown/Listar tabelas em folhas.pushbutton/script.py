# -*- coding: utf-8 -*-
from pyrevit import revit, DB, script, forms

output = script.get_output()
output.close_others()

doc = revit.doc

schedules = DB.FilteredElementCollector(doc).OfClass(
    DB.ScheduleSheetInstance).ToElements()

sheets = DB.FilteredElementCollector(doc).OfCategory(
    DB.BuiltInCategory.OST_Sheets).WhereElementIsNotElementType().ToElements()

resultados = []
for schedule in schedules:
    if not schedule.IsTitleblockRevisionSchedule:
        sheet = doc.GetElement(schedule.OwnerViewId)
        resultados.append(
            (doc.GetElement(schedule.ScheduleId).Name, sheet.SheetNumber, sheet.Name)
        )

if len(resultados) != 0:
    resultados = sorted(resultados, key=lambda x: x[0])
    output.print_md("## Tabelas nas Pranchas")
    cabecalhos = ["Nome da Tabela", "Número da Prancha", "Nome da Prancha"]
    output.print_table(resultados, cabecalhos)
else:
    forms.alert("Nenhuma tabela encontrada nas pranchas.")
