# ToniBIM (pyRevit Extension)

Extensão pyRevit para automações de produção no Revit, organizada na aba `ToniBIM`.

## Estrutura
- `Toni.extension/ToniBIM.tab/BIM.panel`
- `Toni.extension/ToniBIM.tab/Utilitários.panel`

Cada comando segue o padrão pyRevit:
- `*.pushbutton/script.py`
- `bundle.yaml`
- recursos opcionais (`*.xaml`, ícones)

## Requisitos
- Autodesk Revit 2025.x
- pyRevit instalado e carregando a extensão
- Para exportação NWC: Navisworks Exporter disponível no Revit

## Comandos Disponíveis

### BIM.panel
- `ImportarDialux`
  - Lê blocos/layers de DWG (padrão `DLX_FL...LUMx`) e insere luminárias Revit com posição/rotação.
- `exportar-multiplos-NWC`
  - Exporta um `.nwc` por vista 3D selecionada.
  - Interface WPF própria (`ExportarMultiplosNWCWindow.xaml`) com:
    - escolha de coordenadas (`Ponto base de projeto` ou `Coordenadas Compartilhadas`)
    - seleção de pasta de saída
    - seleção múltipla de vistas com checkboxes
  - Exibe relatório final com sucessos, falhas e tempo total.

### Utilitários.panel > Tabelas
- `Listar tabelas em folhas`
  - Lista schedules colocadas em pranchas.
- `Exportar tabelas para o CSV`
  - Exporta schedules selecionadas para CSV (com opções via Shift+Click).
- `Criar tabelas a partir do CSV`
  - Cria/atualiza Key Schedules a partir de CSV tipado.
- `Exportar para XLS`
  - Script atualmente vazio (sem implementação).

### Utilitários.panel > Folhas
- `Selecionar Folhas`
  - Seleciona múltiplas folhas em lista.
- `ReOrdenar Folhas`
  - Reordena folhas com base em parâmetro inteiro contendo `Order`.
- `Criar Folhas (em lotes)`
  - Cria folhas ou placeholders em lote a partir de texto/tabulação.
- `Renomear Folhas Selecionadas`
  - Converte nomes para maiúsculas/minúsculas.
- `Listar Selos no projeto`
  - Lista ou seleciona title blocks das folhas escolhidas.

## Observações Técnicas
- A API pública do Revit 2025 não expõe leitura direta do estado da janela `Navisworks settings...`.
- No comando de exportação NWC, as opções são definidas programaticamente (preset interno) e `Faceting Factor` está fixo em `40`.
- Há textos com encoding inconsistente em alguns scripts legados.

## Instalação da Extensão
1. Garanta que a pasta `Toni.extension` esteja em um caminho monitorado pelo pyRevit.
2. Recarregue o pyRevit (`pyrevit reload`) ou reinicie o Revit.
3. A aba `ToniBIM` deverá aparecer com os painéis e comandos.

## Desenvolvimento
- Linguagem: Python (pyRevit / Revit API)
- UI: WPF/XAML nos comandos que exigem interface rica
- Boas práticas recomendadas:
  - manter codificação UTF-8
  - validar entradas do usuário
  - tratar exceções por item em operações em lote
