# -*- coding: utf-8 -*-
__title__   = "Gerenciamento de Risco"
___doc__ = """Version = 1.5
Date    = 14.04.2025
Author: THIAGO TONI
"""

from pyrevit import forms, script
import os

logger = script.get_logger()

# Caminho do Excel
excel_path = r"C:\planilhas_dimensionamento\GERENCIAMENTO DE RISCO.xlsm"

# Caixa de diálogo com "Sim" e "Não"
resposta = forms.alert(
    "Você tem a última versão desta Memória de Cálculo?",
    title="Verificação de Memória de Cálculo",
    options=["Sim", "Não"]
)

# Se clicou "Sim"
if resposta == "Sim":
    if os.path.exists(excel_path):
        try:
            os.startfile(excel_path)
            logger.info("Arquivo Excel aberto com sucesso.")
        except Exception as e:
            forms.alert("Erro ao abrir o arquivo:\n{}".format(str(e)), title="Erro")
            logger.error("Erro ao abrir Excel: {}".format(str(e)))
    else:
        forms.alert("Arquivo não encontrado:\n{}".format(excel_path), title="Erro")
        logger.error("Caminho inválido: {}".format(excel_path))