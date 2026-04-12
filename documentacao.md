# Documentacao Tecnica dos Scripts pyRevit - ToniBIM

## 1. Visao Geral da Extensao
Esta extensao pyRevit organiza comandos na aba `ToniBIM`, com dois paines principais:
- `BIM.panel`
- `Utilitarios.panel`

Os scripts estao estruturados no padrao pyRevit (`*.pushbutton/script.py` + `bundle.yaml` + recursos opcionais como `*.xaml`).

## 2. Mapa dos Scripts Lidos
Foram lidos todos os `script.py` do projeto:
1. `BIM.panel/ImportarDialux.pushbutton/script.py`
2. `Utilitarios.panel/Tabelas.pulldown/Listar tabelas em folhas.pushbutton/script.py`
3. `Utilitarios.panel/Tabelas.pulldown/Exportar tabelas para o CSV.pushbutton/script.py`
4. `Utilitarios.panel/Tabelas.pulldown/Exportar para XLS.pushbutton/script.py`
5. `Utilitarios.panel/Tabelas.pulldown/Criar tabelas a partir do CSV.pushbutton/script.py`
6. `Utilitarios.panel/Folhas.pulldown/Selecionar Folhas.pushbutton/script.py`
7. `Utilitarios.panel/Folhas.pulldown/ReOrdenar Folhas.pushbutton/script.py`
8. `Utilitarios.panel/Folhas.pulldown/Criar Folhas (em lotes).pushbutton/script.py`
9. `Utilitarios.panel/Folhas.pulldown/Renomear Folhas Selecionadas.pushbutton/script.py`
10. `Utilitarios.panel/Folhas.pulldown/Listar Selos no projeto.pushbutton/script.py`
11. `Utilitarios.panel/Memorias de Calculo.pulldown/BancoCap.pushbutton/script.py`
12. `Utilitarios.panel/Memorias de Calculo.pulldown/DimDutos.pushbutton/script.py`
13. `Utilitarios.panel/Memorias de Calculo.pulldown/GR.pushbutton/script.py`
14. `Utilitarios.panel/Memorias de Calculo.pulldown/InvFre.pushbutton/script.py`
15. `Utilitarios.panel/Memorias de Calculo.pulldown/Softstarter.pushbutton/script.py`
16. `Utilitarios.panel/Memorias de Calculo.pulldown/spda.pushbutton/script.py`

Tambem foram lidos os arquivos de interface:
- `ReOrderWindow.xaml`
- `BatchSheetMakerWindow.xaml`
- `luminarias_dialux.xaml`

## 3. Detalhamento por Script

### 3.1 Importar Luminarias (Dialux)
**Arquivo:** `BIM.panel/ImportarDialux.pushbutton/script.py`

**Objetivo**
Inserir instancias de luminarias Revit a partir de blocos/layers de um DWG (DiaLux), mantendo posicao e rotacao.

**Fluxo funcional**
1. Solicita selecao do vinculo CAD (`ImportInstance`) ou de um bloco interno.
2. Se o usuario nao clicar direto no import, tenta localizar o `ImportInstance` pelo `BoundingBox` no `ActiveView`.
3. Le nome do DWG via `BuiltInParameter.SYMBOL_NAME_PARAM`.
4. Varre subcategorias do CAD e identifica layers no padrao `DLX_FL...LUMx`.
5. Lista tipos de luminaria detectados (LUM1, LUM2, ...).
6. Para cada tipo detectado, solicita mapeamento manual para um `FamilySymbol` da categoria `OST_LightingFixtures`.
7. Extrai `GeometryInstance` raiz do CAD com `Options` (`Fine`, `IncludeNonVisibleObjects=True`).
8. Percorre `SymbolGeometry` recursivamente para encontrar blocos aninhados e acumular transformacoes.
9. Filtra por `GraphicsStyleId`/layer, calcula ponto de insercao e angulo de rotacao (sinal pelo produto vetorial).
10. Remove duplicatas por chave geometrica (tipo + XYZ arredondado + angulo arredondado).
11. Em transacao `revit.Transaction("Alocar Luminarias Dialux")`, ativa simbolos e cria instancias com `NewFamilyInstance`, aplicando rotacao com `ElementTransformUtils.RotateElement`.
12. Exibe total inserido.

**Entradas e dependencias**
- Um DWG importado/vinculado com layers no padrao esperado.
- Familias de luminaria carregadas no projeto.

**Saidas**
- Instancias de luminaria criadas no modelo.
- Mensagens no output/alertas.

**Pontos de atencao**
- Depende rigidamente da nomenclatura de layer (`DLX_FL...LUMx`).
- A selecao por bounding box pode falhar em cenarios de sobreposicao.
- Arquivo `luminarias_dialux.xaml` existe, mas o fluxo atual do script usa dialogs do pyRevit (o XAML nao esta sendo chamado pelo codigo atual).

---

### 3.2 Listar tabelas em folhas
**Arquivo:** `Tabelas.pulldown/Listar tabelas em folhas.pushbutton/script.py`

**Objetivo**
Listar tabelas (`ScheduleSheetInstance`) colocadas em folhas.

**Fluxo funcional**
1. Coleta instancias de tabela em folha.
2. Ignora tabelas de revisao do carimbo (`IsTitleblockRevisionSchedule`).
3. Para cada item, resolve:
- Nome da tabela (`ScheduleId`)
- Numero da folha (`SheetNumber`)
- Nome da folha (`Name`)
4. Ordena por nome da tabela e imprime em tabela markdown no output.
5. Se vazio, exibe alerta.

**Saidas**
- Relatorio tabular no painel de saida do pyRevit.

---

### 3.3 Exportar tabelas para CSV
**Arquivo:** `Tabelas.pulldown/Exportar tabelas para o CSV.pushbutton/script.py`

**Objetivo**
Exportar schedules selecionadas para CSV.

**Fluxo funcional**
1. Fluxo normal: escolhe pasta manualmente.
2. `Shift+Click`: abre `CommandSwitchWindow` com destinos pre-definidos e opcoes:
- Abrir arquivo ao final
- Incluir cabecalhos
3. Monta `ViewScheduleExportOptions`.
4. Detecta separador regional (`user_config.get_list_separator`) e pergunta se deseja usar no lugar de virgula.
5. Exporta cada schedule com nome saneado (`coreutils.cleanup_filename`).
6. Corrige encoding do arquivo exportado (`revit.files.correct_text_encoding`).
7. Opcionalmente abre o CSV gerado.

**Entradas e dependencias**
- Schedules selecionadas pelo usuario.
- Pasta de destino valida.

**Saidas**
- Arquivos `.csv` no destino escolhido.

---

### 3.4 Exportar para XLS
**Arquivo:** `Tabelas.pulldown/Exportar para XLS.pushbutton/script.py`

**Status atual**
- Arquivo vazio (sem implementacao).

**Impacto**
- O botao pode existir na interface, mas nao executa logica funcional.

---

### 3.5 Criar tabelas a partir do CSV
**Arquivo:** `Tabelas.pulldown/Criar tabelas a partir do CSV.pushbutton/script.py`

**Objetivo**
Importar CSV e criar/atualizar `Key Schedule` no Revit.

**Fluxo funcional principal**
1. Usuario escolhe arquivo CSV.
2. Usuario escolhe categoria de key schedule.
3. Script le cabecalho tipado (`Campo|Tipo`) com compatibilidade Revit 2022+ (`SpecTypeId`) e versoes anteriores (`ParameterType`).
4. Procura key schedule existente com os mesmos campos.
5. Se existir, oferece atualizar dados da tabela existente.
6. Se nao existir, tenta criar nova tabela:
- Valida conflitos de nome
- Valida conflito de campos com outra key schedule da mesma categoria
- Valida se campos sao agendaveis
- Adiciona campos na definicao
- Cria registros/linhas e preenche parametros por tipo

**Funcoes relevantes**
- `read_csv_typed_data`: interpreta header e dados.
- `ensure_schedulable_parameters`: garante que os campos existem como agendaveis para a categoria.
- `resolve_naming_conflicts`: trata colisao de nome e conflito de campos.
- `update_key_schedule`: limpa linhas antigas, recria linhas e remapeia elementos existentes para novos itens da key schedule.

**Transacoes**
- `revit.Transaction("Atualizar Tabela a partir do CSV")`
- `revit.Transaction("Criar Tabela a partir do CSV")`
- `revit.DryTransaction` para validacoes sem persistencia.

**Pontos de atencao**
- Nao cria parametros de projeto automaticamente (limitacao da API); apenas valida e orienta.
- Converte tipos de parametro com fallback por `StorageType`.

---

### 3.6 Selecionar Folhas
**Arquivo:** `Folhas.pulldown/Selecionar Folhas.pushbutton/script.py`

**Objetivo**
Selecionar multiplas folhas no modelo e aplicar a selecao no Revit.

**Fluxo funcional**
1. Abre seletor `forms.select_sheets`.
2. Se houver selecao, aplica em `revit.get_selection().set_to(...)`.

---

### 3.7 ReOrdenar Folhas
**Arquivo:** `Folhas.pulldown/ReOrdenar Folhas.pushbutton/script.py`

**Objetivo**
Recalcular e gravar um indice inteiro de ordenacao em folhas, com suporte a agrupamento por regex.

**Fluxo funcional**
1. `ensure_orderable()` valida pre-requisitos:
- Existem folhas no modelo.
- Existe pelo menos um parametro de instancia inteiro contendo `Order` no nome.
2. Janela WPF (`ReOrderWindow.xaml`) carrega parametros elegiveis.
3. Usuario escolhe parametro de ordem e manipula lista (mover topo/fundo, +/-1, +/-10).
4. `grouping_pattern` (regex) gera blocos de indice em faixas de 1000 por grupo.
5. Ao confirmar, grava `order_index` em cada folha no parametro escolhido dentro de `revit.Transaction("Reordenar Folhas")`.

**Detalhe de algoritmo**
- Sem regex valida: ordem linear.
- Com regex valida: extrai `groupid`, incrementa grupo quando muda, e calcula indice com offset de grupo.

---

### 3.8 Criar Folhas (em lotes)
**Arquivo:** `Folhas.pulldown/Criar Folhas (em lotes).pushbutton/script.py`

**Objetivo**
Criar folhas reais ou placeholders em lote a partir de texto colado.

**Fluxo funcional**
1. Abre janela WPF (`BatchSheetMakerWindow.xaml`).
2. Usuario cola linhas no formato `Numero<TAB>Nome`.
3. `_process_sheet_code()`:
- Normaliza tabs
- Permite intervalos/listas por `coreutils.extract_range`
- Monta dicionario `{numero: nome}`
4. Se modo `Criar Folhas`, pede titleblock.
5. Executa criacao em `DB.TransactionGroup`:
- Folha real: `DB.ViewSheet.Create(doc, titleblock_id)`
- Placeholder: `DB.ViewSheet.CreatePlaceholder(doc)`
6. Cada item abre transacao individual com rollback em falha e log de erro.

**Pontos de atencao**
- Falhas de numero duplicado ou conflito de nome/numero sao registradas no logger.

---

### 3.9 Renomear Folhas Selecionadas
**Arquivo:** `Folhas.pulldown/Renomear Folhas Selecionadas.pushbutton/script.py`

**Objetivo**
Converter nome de folhas selecionadas para maiusculas ou minusculas.

**Fluxo funcional**
1. Seleciona folhas (`use_selection=True`).
2. `CommandSwitchWindow` oferece:
- Converter para MAIUSCULAS
- Converter para minusculas
- Switch: Exibir Relatorio
3. Em transacao, escreve em `BuiltInParameter.SHEET_NAME`.

---

### 3.10 Listar Selos no projeto
**Arquivo:** `Folhas.pulldown/Listar Selos no projeto.pushbutton/script.py`

**Objetivo**
Listar ou selecionar selos (title blocks) das folhas escolhidas.

**Fluxo funcional**
1. Seleciona folhas de origem.
2. Se `Shift+Click`:
- Coleta IDs de todos os selos
- Aplica direto na selecao do Revit
3. Clique normal:
- Imprime relatorio por folha
- Gera link de selecao para todos os selos no output

**Observacao tecnica**
- O arquivo possui bloco de codigo duplicado (imports e funcoes repetidos). Funciona, mas e um ponto de manutencao.

---

## 4. Integracao pyRevit (bundle + UI)
- `bundle.yaml` define titulo/tooltip multilanguage dos botoes.
- `.xaml` define UI de ferramentas com WPF:
  - `ReOrderWindow.xaml`: grid de reordenacao + regex de agrupamento.
  - `BatchSheetMakerWindow.xaml`: entrada tabulada para criacao em lote.
  - `luminarias_dialux.xaml`: layout para mapeamento de luminarias (atualmente nao consumido pelo `script.py`).

## 5. Riscos Tecnicos Identificados
1. **Encoding inconsistente**: varios textos aparecem com caracteres quebrados (ex.: `Ã£`, `Ã¡`) indicando problema de codificacao em arquivos fonte.
2. **Script vazio**: `Exportar para XLS` sem logica implementada.
3. **Codigo duplicado**: `Listar Selos no projeto` contem duplicacao integral de bloco.
4. **Paths locais fixos**: scripts de Memorias dependem de `C:\planilhas_dimensionamento`.
5. **Dependencia de nomenclatura**: ImportarDialux depende de padrao estrito de layers no DWG.

## 6. Recomendacoes de Evolucao
1. Padronizar encoding para `UTF-8` em todos os scripts.
2. Implementar ou remover o comando `Exportar para XLS`.
3. Refatorar `Listar Selos no projeto` removendo duplicacao.
4. Externalizar caminhos das planilhas para configuracao (ex.: JSON, pyRevit config, variavel de ambiente).
5. Adicionar logs mais estruturados e tratamento de excecoes mais granular nas transacoes de criacao em lote.

## 7. Conclusao
Todos os scripts do projeto foram lidos e documentados. A extensao cobre automacoes uteis para folhas, tabelas, importacao de luminarias e abertura de memorias de calculo, com boa base funcional e oportunidades claras de robustez/manutenibilidade para a proxima versao.
