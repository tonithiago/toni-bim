# -*- coding: utf-8 -*-
"""Importar um arquivo CSV existente como uma Tabela-Chave.

- A primeira linha do CSV deve conter os nomes dos campos
- O primeiro campo do CSV deve ser "Key Name"

Exemplo de CSV:
Key Name,NomeParâmetro1,NomeParâmetro2
A,Valor11,Valor12
B,Valor21,Valor22
C,Valor32,Valor32
"""
# pylint: disable=C0103,E0401,W0703

import csv
import codecs
import os.path as op
from collections import defaultdict

from pyrevit import PyRevitException
from pyrevit import forms
from pyrevit import coreutils
from pyrevit import revit, DB, HOST_APP
from pyrevit import script


logger = script.get_logger()


def safe_delete_keysched(doc, keysched):
    try:
        doc.Delete(keysched.Id)
        return True
    except Exception as ex:
        forms.alert("Falha ao excluir a Tabela-Chave existente", expanded=str(ex))
    return False


def create_schedule_record(schedule, count=1):
    table_data = schedule.GetTableData()
    section_data = table_data.GetSectionData(DB.SectionType.Body)
    for _ in range(count):
        section_data.InsertRow(section_data.LastRowNumber + 1)


def create_schedule_records(schedule, fields, records):
    create_schedule_record(schedule, count=len(records))
    for keysched_el, record_data in zip(
        revit.query.get_all_elements_in_view(schedule), records
    ):
        logger.debug("Processando registro: %s", record_data)
        for idx, field_name in enumerate(fields):
            if record_data[idx]:
                p = keysched_el.LookupParameter(field_name)
                if p and not p.SetValueString(record_data[idx]):
                    if p.StorageType == DB.StorageType.Integer:
                        p.Set(int(record_data[idx]))
                    elif p.StorageType == DB.StorageType.Double:
                        p.Set(float(record_data[idx]))
                    elif p.StorageType == DB.StorageType.String:
                        p.Set(record_data[idx])
                    elif p.StorageType == DB.StorageType.ElementId:
                        p.Set(DB.ElementId(int(record_data[idx])))


def has_matching_fields(keysched_def, fields):
    exist_ksch_fields = set()
    for idx in range(keysched_def.GetFieldCount()):
        sched_field = keysched_def.GetField(idx)
        exist_ksch_fields.add(sched_field.GetName())
    other_fields = exist_ksch_fields.difference(set(fields))
    return len(other_fields) == 0


def has_field_conflicts(keysched_def, fields):
    for idx in range(keysched_def.GetFieldCount()):
        sched_field = keysched_def.GetField(idx)
        if sched_field.GetName() in fields:
            return sched_field.GetName()


def resolve_naming_conflicts(category, sched_name, fields, doc=None):
    doc = doc or revit.doc

    all_schedules = revit.query.get_all_views(
        doc=doc, view_types=[DB.ViewType.Schedule]
    )
    matching_keysched = next(
        (
            x
            for x in all_schedules
            if x.Definition.IsKeySchedule
            and x.Definition.CategoryId == category.Id
        ),
        None,
    )
    if matching_keysched:
        cfield = has_field_conflicts(matching_keysched.Definition, fields)
        if cfield:
            if forms.alert(
                'O campo "{}" já está sendo utilizado por outra tabela-chave "{}". '
                'Não é possível que múltiplas tabelas-chave definam valores para o mesmo parâmetro.\n'
                'Deseja excluir a tabela-chave existente antes de continuar?'.format(
                    cfield, matching_keysched.Name
                ),
                yes=True,
                no=True,
            ):
                if not safe_delete_keysched(doc, matching_keysched):
                    return None
            else:
                return None

    existing_sched = revit.query.get_view_by_name(
        sched_name, view_types=[DB.ViewType.Schedule]
    )
    if existing_sched:
        if forms.alert(
            'Já existe uma tabela com o nome "{}".\n'
            'Deseja escolher um novo nome para esta tabela-chave?'.format(sched_name),
            yes=True,
            no=True,
        ):
            return forms.ask_for_unique_string(
                reserved_values=[x.Name for x in all_schedules],
                default="{} {}".format(sched_name, coreutils.current_date()),
            )
        return None
    return sched_name


def create_key_schedule(category, key_name, sched_name, fields=None, records=None, doc=None):
    doc = doc or revit.doc
    fields = fields or []
    records = records or []

    new_name = resolve_naming_conflicts(category, sched_name, fields[1:], doc=doc)
    if not new_name:
        return

    new_key_sched = DB.ViewSchedule.CreateKeySchedule(doc, category.Id)
    new_key_sched.Name = new_name
    new_key_sched.KeyScheduleParameterName = key_name

    fsched_fields = {
        x.GetName(doc): x for x in new_key_sched.Definition.GetSchedulableFields()
    }

    cancel_txn = False
    for field in fields:
        if field in fsched_fields:
            try:
                new_key_sched.Definition.AddField(fsched_fields[field])
            except Exception:
                logger.debug("Falha ao adicionar campo: %s", field)
        else:
            cancel_txn = True
            logger.error(
                'O campo "%s" não é agendável para a categoria "%s". '
                "Verifique as categorias aplicáveis para este parâmetro de projeto.",
                field,
                category.Name,
            )

    if cancel_txn:
        raise PyRevitException("Cancelando alterações devido a erros")

    if records:
        create_schedule_records(new_key_sched, fields, records)
    return new_key_sched


def find_matching_keyschedule(category, fields, doc=None):
    doc = doc or revit.doc
    all_schedules = revit.query.get_all_views(
        doc=doc, view_types=[DB.ViewType.Schedule]
    )
    return next(
        (
            x
            for x in all_schedules
            if x.Definition.IsKeySchedule
            and x.Definition.CategoryId == category.Id
            and has_matching_fields(x.Definition, fields)
        ),
        None,
    )


def update_key_schedule(keyschedule, category, fields, records, doc=None):
    doc = doc or revit.doc
    if forms.alert(
        'A tabela-chave "{}" já possui campos idênticos.\n'
        'Não é possível que múltiplas tabelas-chave definam valores para o mesmo parâmetro.\n'
        "Deseja atualizar os dados da tabela existente?".format(
            keyschedule.Name
        ),
        yes=True,
        no=True,
    ):
        value_dict = defaultdict(list)
        param_name = keyschedule.KeyScheduleParameterName
        for exst_el in revit.query.get_elements_by_categories(
            [revit.query.get_builtincategory(category.Name)], doc=doc
        ):
            param = exst_el.LookupParameter(param_name)
            if param:
                value_dict[param.AsValueString()].append(exst_el.Id)

        table_data = keyschedule.GetTableData()
        section_data = table_data.GetSectionData(DB.SectionType.Body)
        for idx in range(section_data.NumberOfRows - 1, 0, -1):
            if section_data.CanRemoveRow(idx):
                section_data.RemoveRow(idx)

        create_schedule_records(keyschedule, fields, records)

        schedule_els = revit.query.get_all_elements_in_view(keyschedule)
        first_rec = fields[0]
        sched_items = {
            x.LookupParameter(first_rec).AsString(): x.Id for x in schedule_els
        }
        new_possible_values = [x[0] for x in records]
        for param_value, element_ids in value_dict.items():
            if param_value in new_possible_values:
                for eid in element_ids:
                    exst_el = doc.GetElement(eid)
                    if exst_el:
                        param = exst_el.LookupParameter(param_name)
                        if param:
                            param.Set(sched_items[param_value])


def ensure_schedulable_parameters(category, parameter_defs, doc=None):
    doc = doc or revit.doc
    params_ensured = True
    with revit.DryTransaction(doc):
        temp_key_sched = DB.ViewSchedule.CreateKeySchedule(doc, category.Id)
        fsched_field_names = [
            x.GetName(doc)
            for x in temp_key_sched.Definition.GetSchedulableFields()
        ]

        for param_def in parameter_defs:
            if param_def[0] not in fsched_field_names:
                logger.critical(
                    "Parâmetro agendável ausente.\n"
                    'Nome: "%s"\n'
                    "Tipo: %s\n"
                    "Categoria: %s",
                    param_def[0],
                    param_def[1],
                    category.Name,
                )
                params_ensured = False

    if not params_ensured:
        logger.critical(
            "A API do Revit não permite a criação automática de "
            "Parâmetros de Projeto. Crie manualmente os parâmetros ausentes "
            "antes de importar os dados do arquivo CSV."
        )
    return params_ensured


def ensure_parameters(category, parameter_defs, doc=None):
    doc = doc or revit.doc
    params_ensured = True
    with revit.Transaction("Verificar Campos do CSV"):
        for param_def in parameter_defs:
            if not revit.query.model_has_parameter(param_def[0]):
                logger.critical(
                    "Parâmetro de projeto ausente.\n"
                    'Nome: "%s"\n'
                    "Tipo: %s\n"
                    "Categoria: %s",
                    param_def[0],
                    param_def[1],
                    category.Name,
                )
                params_ensured = False
    if not params_ensured:
        logger.critical(
            "A API do Revit não permite a criação automática de "
            "Parâmetros de Projeto. Crie manualmente os parâmetros ausentes "
            "antes de importar os dados do arquivo CSV."
        )
    return params_ensured


def read_csv_typed_data(csv_file):
    with codecs.open(csv_file, "rb", encoding="utf-8") as csvfile:
        csv_lines = list(csv.reader(csvfile, delimiter=",", quotechar='"'))
        field_defs = []
        for field_def in csv_lines[0]:
            parts = field_def.split("|")
            parts_count = len(parts)
            if HOST_APP.is_newer_than(2022, or_equal=True):
                if parts_count == 1 and parts[0]:
                    field_defs.append((parts[0], DB.SpecTypeId.String))
                elif parts_count == 2 and hasattr(DB.SpecTypeId, parts[1]):
                    field_defs.append((parts[0], getattr(DB.SpecTypeId, parts[1])))
            else:
                if parts_count == 1 and parts[0]:
                    field_defs.append((parts[0], DB.ParameterType.Text))
                elif parts_count == 2:
                    field_defs.append((parts[0], coreutils.get_enum_value(DB.ParameterType, parts[1])))
    return (field_defs, csv_lines[1:])


if __name__ == "__main__":
    source_file = forms.pick_file(file_ext="csv")
    if source_file:
        fname = op.splitext(op.basename(source_file))[0]
        key_sched_cat = forms.SelectFromList.show(
            revit.query.get_key_schedule_categories(),
            name_attr="Name",
            multiselect=False,
            title="Selecione a Categoria da Tabela-Chave",
        )
        if key_sched_cat:
            param_defs, param_data = read_csv_typed_data(source_file)
            param_names = [x[0] for x in param_defs]
            existing_keyschedule = find_matching_keyschedule(
                category=key_sched_cat, fields=param_names
            )
            if existing_keyschedule:
                with revit.Transaction("Atualizar Tabela a partir do CSV", log_errors=False):
                    update_key_schedule(
                        keyschedule=existing_keyschedule,
                        category=key_sched_cat,
                        fields=param_names,
                        records=param_data,
                        doc=revit.doc,
                    )
            else:
                with revit.Transaction("Criar Tabela a partir do CSV", log_errors=False):
                    if ensure_schedulable_parameters(key_sched_cat, param_defs[1:]):
                        create_key_schedule(
                            category=key_sched_cat,
                            key_name=fname,
                            sched_name=fname,
                            fields=param_names,
                            records=param_data,
                            doc=revit.doc,
                        )
