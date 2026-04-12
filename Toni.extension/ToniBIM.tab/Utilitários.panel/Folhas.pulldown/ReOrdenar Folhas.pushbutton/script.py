# -*- coding: utf-8 -*-
"""Imprimir itens em ordem a partir de um índice de folhas.

Esta ferramenta busca por parâmetros de projeto (em Folhas) que sejam
de instância, do tipo Inteiro e que tenham "Order" no nome.
"""
# pylint: disable=W0613,E0401,C0103
# pylint: disable=missing-class-docstring,missing-function-docstring,broad-except
import re

from pyrevit import forms
from pyrevit import revit, DB
from pyrevit import script


logger = script.get_logger()


class ListItem(object):
    def __init__(self, view_sheet):
        self._item = view_sheet
        self.name = self._item.Name
        self.number = self._item.SheetNumber
        self.printable = self._item.CanBePrinted
        self.order_index = 0

    @property
    def revit_item(self):
        return self._item


class ReOrderWindow(forms.WPFWindow):
    @staticmethod
    def ensure_orderable():
        sheets = revit.query.get_sheets()
        if not sheets:
            forms.alert("Não há folhas neste modelo.", exitscript=True)

        sheet = sheets[0]
        int_params = [
            x
            for x in sheet.Parameters
            if "order" in x.Definition.Name.lower()
            and x.StorageType == DB.StorageType.Integer
        ]
        if not int_params:
            forms.alert(
                "Nenhum parâmetro com 'Order' foi encontrado.\n"
                "Defina um parâmetro de projeto do tipo 'Inteiro' e "
                "atribua à categoria 'Folhas'.\n"
                "Esta ferramenta usa esse parâmetro para ordenar as folhas.",
                exitscript=True,
            )

        return len(int_params)

    def __init__(self, xaml_file_name):
        super(ReOrderWindow, self).__init__(xaml_file_name)

        self._config = script.get_config()
        self._setup_item_params_combobox()

        self.grouping_pattern = self._config.get_option(
            "index_grouping_pattern", r"([A-Z])\d"
        )

    @property
    def items_list(self):
        return self.items_dg.ItemsSource or []

    @items_list.setter
    def items_list(self, value):
        self.items_dg.ItemsSource = value
        self._update_order_indices()

    @property
    def selected_item_param(self):
        return self.orderparams_cb.SelectedItem

    @property
    def grouping_pattern(self):
        pattern = self.indexgroup_tb.Text
        try:
            re.compile(pattern)
            return pattern
        except Exception:
            return ""

    @grouping_pattern.setter
    def grouping_pattern(self, value):
        self.indexgroup_tb.Text = value

    def _refresh(self):
        existing_items = self.items_list
        self.items_list = []
        self.items_list = existing_items

    def _update_order_indices(self):
        if self.grouping_pattern:
            last_groupid = ""
            grouping_index = 0
            grouping_range = 1000
            for idx, item in enumerate(self.items_list):
                match = re.search(self.grouping_pattern, item.number)
                if match and match.groups():
                    groupid = match.groups()[0]
                    if groupid != last_groupid:
                        last_groupid = groupid
                        grouping_index += 1
                    item.order_index = (grouping_range * grouping_index) + idx
                else:
                    item.order_index = idx
        else:
            for idx, item in enumerate(self.items_list):
                item.order_index = idx

    def _setup_item_params_combobox(self):
        items = revit.query.get_sheets()
        if items:
            item_sample = items[0]
            item_params = [
                x.Definition.Name
                for x in item_sample.Parameters
                if x.StorageType == DB.StorageType.Integer
            ]

            order_params = [x for x in item_params if "order" in x.lower()]
            self.orderparams_cb.ItemsSource = sorted(order_params)
            self.orderparams_cb.SelectedIndex = 0

    def _get_ordered_items(self):
        items = revit.query.get_sheets(include_noappear=False)
        if self.selected_item_param:
            items = sorted(
                items,
                key=lambda x: x.LookupParameter(
                    self.selected_item_param
                ).AsInteger(),
            )
        return items

    def _get_selected_nonselected(self):
        selected = list(self.items_dg.SelectedItems)
        nonselected = [item for item in self.items_list if item not in selected]
        return selected, nonselected

    def _insert_list_in_list(self, src_list, dest_list, index):
        max_index = len(dest_list)
        index = max(0, min(index, max_index))

        for item in reversed(src_list):
            dest_list.insert(index, item)

        return dest_list

    def selection_changed(self, sender, args):
        if self.selected_item_param:
            items_list = [ListItem(x) for x in self._get_ordered_items()]
            self.items_list = items_list

    def sheet_selection_changed(self, sender, args):
        selected, _ = self._get_selected_nonselected()
        self.shift_buttons.IsEnabled = bool(selected)

    def sorting_changed(self, sender, args):
        order_param = args.Column.SortMemberPath
        if order_param == "number":
            self.items_list = sorted(self.items_list, key=lambda x: x.number)
        elif order_param == "name":
            self.items_list = sorted(self.items_list, key=lambda x: x.name)

    def grouping_pattern_changed(self, sender, args):
        self._refresh()

    def move_to_top(self, sender, args):
        selected, unselected = self._get_selected_nonselected()
        if selected:
            self.items_list = self._insert_list_in_list(selected, unselected, 0)

    def move_10_to_top(self, sender, args):
        selected, unselected = self._get_selected_nonselected()
        if selected:
            index = self.items_dg.ItemsSource.index(selected[0])
            self.items_list = self._insert_list_in_list(selected, unselected, index - 10)

    def move_1_to_top(self, sender, args):
        selected, unselected = self._get_selected_nonselected()
        if selected:
            index = self.items_dg.ItemsSource.index(selected[0])
            self.items_list = self._insert_list_in_list(selected, unselected, index - 1)

    def move_1_to_bottom(self, sender, args):
        selected, unselected = self._get_selected_nonselected()
        if selected:
            index = self.items_dg.ItemsSource.index(selected[0])
            self.items_list = self._insert_list_in_list(selected, unselected, index + 1)

    def move_10_to_bottom(self, sender, args):
        selected, unselected = self._get_selected_nonselected()
        if selected:
            index = self.items_dg.ItemsSource.index(selected[0])
            self.items_list = self._insert_list_in_list(selected, unselected, index + 10)

    def move_to_bottom(self, sender, args):
        selected, unselected = self._get_selected_nonselected()
        if selected:
            self.items_list = self._insert_list_in_list(selected, unselected, len(unselected))

    def reorder_items(self, sender, args):
        self.Close()
        self._config.set_option("index_grouping_pattern", self.grouping_pattern)
        with revit.Transaction("Reordenar Folhas"):
            for item in self.items_list:
                idx_param = item.revit_item.LookupParameter(self.selected_item_param)
                if idx_param:
                    idx_param.Set(item.order_index)


if ReOrderWindow.ensure_orderable():
    ReOrderWindow("ReOrderWindow.xaml").ShowDialog()
