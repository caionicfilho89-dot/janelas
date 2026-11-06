# 🪟 Janelas

App offline para Windows (PyQt6 + ctypes/user32) que organiza as janelas do seu desktop.

## O que faz
- Lista as janelas visíveis (título + programa), com busca e botão Atualizar
- 📌 Sempre no topo, transparência (20–100%), centralizar, maximizar/restaurar/minimizar
- Mover para outro monitor; presets 1280×720, 1920×1080, metades e quadrantes
- Compatível com telas de alta densidade (DPI por monitor)
- **Layouts**: salva as posições das janelas selecionadas e restaura depois
  (casa por programa + título) em `%LOCALAPPDATA%\Janelas\layouts.json`
- **Restaurar tudo**: desfaz o topo/transparência que o app aplicou (e pergunta ao sair)

## Rodar
```
pip install -r requirements.txt
python janelas.pyw
```

## Testes
```
python test_jn.py
```
