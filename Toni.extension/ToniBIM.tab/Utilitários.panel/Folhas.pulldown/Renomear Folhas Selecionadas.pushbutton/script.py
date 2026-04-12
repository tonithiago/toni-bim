# -*- coding: utf-8 -*-
"""Alterar os nomes das folhas selecionadas."""

from pyrevit import revit, DB
from pyrevit import forms


def alterar_maiusculas_minusculas(lista_folhas, maiusculas=True, mostrar_relatorio=False):
    with revit.Transaction('Renomear Folhas para Maiúsculas/Minúsculas'):
        for folha in lista_folhas:
            parametro_nome = folha.Parameter[DB.BuiltInParameter.SHEET_NAME]
            nome_original = parametro_nome.AsString()
            novo_nome = nome_original.upper() if maiusculas else nome_original.lower()
            if mostrar_relatorio:
                print('RENOMEANDO:\t{0}\n'
                      '      para:\t{1}\n'.format(nome_original, novo_nome))
            parametro_nome.Set(novo_nome)


folhas_selecionadas = forms.select_sheets(
    title='Selecione as Folhas',
    use_selection=True
)

if folhas_selecionadas:
    opcao_selecionada, opcoes = forms.CommandSwitchWindow.show(
        ['Converter para MAIÚSCULAS',
         'Converter para minúsculas'],
        switches=['Exibir Relatório'],
        message='Selecione a opção de renomeação:'
    )

    if opcao_selecionada:
        alterar_maiusculas_minusculas(
            folhas_selecionadas,
            maiusculas=True if opcao_selecionada == 'Converter para MAIÚSCULAS' else False,
            mostrar_relatorio=opcoes['Exibir Relatório']
        )
