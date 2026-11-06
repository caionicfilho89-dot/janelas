"""Janelas - organiza as janelas do seu desktop: sempre no topo, transparência, centralizar,
presets de tamanho, mover de monitor e layouts salvos. Tudo local, via Win32 (ctypes)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import jn_core as core  # noqa: E402

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap  # noqa: E402
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,  # noqa: E402
                             QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMessageBox, QPushButton, QSlider, QVBoxLayout,
                             QWidget)

ACCENT = "#7c5cff"
QSS = """
QWidget { background:#11131a; color:#e7e9f0; font:10pt 'Segoe UI'; }
#title { font:700 18pt 'Segoe UI'; }
#info { color:#8a93a8; }
QLineEdit, QComboBox { background:#1b202b; border:1px solid #2d3550; border-radius:8px;
    padding:6px; }
QListWidget { background:#0c0e14; border:1px solid #2d3550; border-radius:10px; padding:4px; }
QListWidget::item { padding:5px; border-radius:6px; }
QListWidget::item:selected { background:#2d3550; color:#fff; }
QPushButton { background:#222a38; border:0; border-radius:10px; padding:8px 12px; }
QPushButton:hover { background:#2d3550; }
QPushButton:disabled { color:#5b6479; }
#go { background:#7c5cff; color:#fff; font-weight:600; }
#go:hover { background:#8f74ff; }
QCheckBox::indicator { width:18px; height:18px; }
QSlider::groove:horizontal { height:6px; background:#2d3550; border-radius:3px; }
QSlider::handle:horizontal { background:#7c5cff; width:16px; margin:-6px 0; border-radius:8px; }
"""


def app_icon():
    pm = QPixmap(64, 64)
    pm.fill(QColor("transparent"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(ACCENT))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(6, 10, 38, 30, 5, 5)
    p.setBrush(QColor("#e7e9f0"))
    p.drawRoundedRect(22, 24, 36, 30, 5, 5)
    p.end()
    return QIcon(pm)


class Janelas(QWidget):
    def __init__(self, ask_on_exit=True):
        super().__init__()
        self.ask_on_exit = ask_on_exit
        self.mgr = core.Manager()
        self.windows = {}  # hwnd -> WinInfo
        self.layouts = core.load_layouts()
        self.setWindowTitle("Janelas")
        self.setWindowIcon(app_icon())
        self.resize(900, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(9)
        root.addWidget(QLabel("🪟 Janelas", objectName="title"))
        root.addWidget(QLabel("Fixe no topo, deixe transparente, centralize, redimensione e "
                              "salve layouts das suas janelas.", objectName="info"))

        body = QHBoxLayout()
        root.addLayout(body, 1)

        # esquerda: lista
        left = QVBoxLayout()
        sr = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por título ou programa…")
        self.search.textChanged.connect(self.fill)
        sr.addWidget(self.search, 1)
        self.btn_refresh = QPushButton("🔄 Atualizar")
        self.btn_refresh.clicked.connect(self.refresh)
        sr.addWidget(self.btn_refresh)
        left.addLayout(sr)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.itemSelectionChanged.connect(self.sync_controls)
        left.addWidget(self.list, 1)
        self.status = QLabel("", objectName="info")
        left.addWidget(self.status)
        body.addLayout(left, 3)

        # direita: controles
        right = QVBoxLayout()
        right.setSpacing(7)
        self.top_cb = QCheckBox("📌 Sempre no topo")
        self.top_cb.toggled.connect(self.on_topmost)
        right.addWidget(self.top_cb)
        self.op_label = QLabel("Transparência: 100%")
        right.addWidget(self.op_label)
        self.op = QSlider(Qt.Orientation.Horizontal)
        self.op.setRange(20, 100)
        self.op.setValue(100)
        self.op.valueChanged.connect(self.on_opacity)
        right.addWidget(self.op)

        r1 = QHBoxLayout()
        for txt, fn in (("Centralizar", self.on_center), ("Maximizar", self.on_max),
                        ("Restaurar", self.on_restore), ("Minimizar", self.on_min)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            r1.addWidget(b)
        right.addLayout(r1)
        self.btn_mon = QPushButton("🖥️ Mover para outro monitor")
        self.btn_mon.clicked.connect(self.on_monitor)
        right.addWidget(self.btn_mon)

        right.addWidget(QLabel("Tamanho / posição:"))
        self.preset = QComboBox()
        for label, key in core.PRESETS:
            self.preset.addItem(label, key)
        pr = QHBoxLayout()
        pr.addWidget(self.preset, 1)
        b = QPushButton("Aplicar")
        b.clicked.connect(self.on_preset)
        pr.addWidget(b)
        right.addLayout(pr)

        right.addWidget(QLabel("Layouts salvos:"))
        self.layout_combo = QComboBox()
        right.addWidget(self.layout_combo)
        lr = QHBoxLayout()
        b = QPushButton("💾 Salvar selecionadas")
        b.clicked.connect(self.on_save_layout)
        lr.addWidget(b)
        b = QPushButton("▶ Aplicar")
        b.setObjectName("go")
        b.clicked.connect(self.on_apply_layout)
        lr.addWidget(b)
        b = QPushButton("🗑")
        b.setToolTip("Apagar layout")
        b.clicked.connect(self.on_delete_layout)
        lr.addWidget(b)
        right.addLayout(lr)

        right.addStretch(1)
        self.btn_reset = QPushButton("↩ Restaurar tudo")
        self.btn_reset.setToolTip("Remove o topo e a transparência que este app aplicou")
        self.btn_reset.clicked.connect(self.on_restore_all)
        right.addWidget(self.btn_reset)
        body.addLayout(right, 2)

        self.reload_layouts()
        self.refresh()

    # ---- lista
    def refresh(self):
        sel = set(self.selected_hwnds())
        self.windows = {w.hwnd: w for w in core.enum_windows([os.getpid()])}
        self.fill(selected=sel)

    def fill(self, *_a, selected=None):
        sel = set(selected) if selected is not None else set(self.selected_hwnds())
        q = self.search.text().strip().lower()
        self.list.blockSignals(True)
        self.list.clear()
        for w in sorted(self.windows.values(), key=lambda x: (x.proc.lower(), x.title.lower())):
            if q and q not in w.title.lower() and q not in w.proc.lower():
                continue
            flags = ("📌 " if w.topmost else "") + ("🔅 " if w.alpha < 255 else "")
            it = QListWidgetItem("%s%s%s" % (flags, w.title,
                                             ("   —   " + w.proc) if w.proc else ""))
            it.setData(Qt.ItemDataRole.UserRole, w.hwnd)
            self.list.addItem(it)
            if w.hwnd in sel:
                it.setSelected(True)
        self.list.blockSignals(False)
        self.status.setText("%d janelas" % self.list.count())
        self.sync_controls()

    def selected_hwnds(self):
        return [it.data(Qt.ItemDataRole.UserRole) for it in self.list.selectedItems()]

    def selected(self):
        out = []
        for h in self.selected_hwnds():
            if h in self.windows and core.window_exists(h):
                self.windows[h] = core.window_info(h)  # estado fresco
                out.append(self.windows[h])
        return out

    def sync_controls(self):
        sel = self.selected()
        has = bool(sel)
        for w in (self.top_cb, self.op, self.btn_mon):
            w.setEnabled(has)
        if has:
            w = sel[0]
            self.top_cb.blockSignals(True)
            self.top_cb.setChecked(w.topmost)
            self.top_cb.blockSignals(False)
            self.op.blockSignals(True)
            pct = max(20, core.alpha_to_percent(w.alpha))
            self.op.setValue(pct)
            self.op.blockSignals(False)
            self.op_label.setText("Transparência: %d%%" % pct)

    # ---- ações
    def each(self, fn):
        for w in self.selected():
            try:
                fn(w)
            except Exception as e:  # janela fechou no meio, sem permissão etc.
                self.status.setText("Falhou em '%s': %s" % (w.title[:30], e))

    def on_topmost(self, on):
        self.each(lambda w: self.mgr.set_topmost(w.hwnd, on))
        self.refresh_flags()

    def on_opacity(self, v):
        self.op_label.setText("Transparência: %d%%" % v)
        self.each(lambda w: self.mgr.set_opacity(w.hwnd, v))
        self.refresh_flags()

    def refresh_flags(self):
        for h in self.selected_hwnds():
            if h in self.windows and core.window_exists(h):
                self.windows[h] = core.window_info(h)
        sel = set(self.selected_hwnds())
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            it = self.list.item(i)
            w = self.windows.get(it.data(Qt.ItemDataRole.UserRole))
            if w:
                flags = ("📌 " if w.topmost else "") + ("🔅 " if w.alpha < 255 else "")
                it.setText("%s%s%s" % (flags, w.title, ("   —   " + w.proc) if w.proc else ""))
        self.list.blockSignals(False)
        _ = sel

    def on_center(self):
        self.each(self.mgr.center)

    def on_max(self):
        self.each(lambda w: core.show(w.hwnd, core.SW_MAXIMIZE))

    def on_restore(self):
        self.each(lambda w: core.show(w.hwnd, core.SW_RESTORE))

    def on_min(self):
        self.each(lambda w: core.show(w.hwnd, core.SW_MINIMIZE))

    def on_monitor(self):
        if len(core.list_monitors()) < 2:
            self.status.setText("Só há um monitor conectado.")
            return
        self.each(self.mgr.move_next_monitor)

    def on_preset(self):
        key = self.preset.currentData()
        self.each(lambda w: self.mgr.apply_preset(w, key))

    # ---- layouts
    def reload_layouts(self, select=None):
        self.layout_combo.clear()
        self.layout_combo.addItems(sorted(self.layouts))
        if select:
            self.layout_combo.setCurrentText(select)

    def on_save_layout(self):
        sel = self.selected()
        if not sel:
            self.status.setText("Selecione as janelas que entram no layout.")
            return
        name, ok = QInputDialog.getText(self, "Salvar layout", "Nome do layout:",
                                        text=self.layout_combo.currentText())
        name = name.strip()
        if not ok or not name:
            return
        self.layouts[name] = self.mgr.save_layout(sel)
        core.save_layouts(self.layouts)
        self.reload_layouts(name)
        self.status.setText("Layout '%s' salvo (%d janelas)." % (name, len(sel)))

    def on_apply_layout(self):
        name = self.layout_combo.currentText()
        if name not in self.layouts:
            return
        self.refresh()
        ok, miss = self.mgr.apply_layout(self.layouts[name], list(self.windows.values()))
        msg = "Layout '%s': %d aplicadas" % (name, ok)
        if miss:
            msg += ", %d não encontradas (%s)" % (len(miss), ", ".join(m[:20] for m in miss[:3]))
        self.status.setText(msg)

    def on_delete_layout(self):
        name = self.layout_combo.currentText()
        if name in self.layouts:
            del self.layouts[name]
            core.save_layouts(self.layouts)
            self.reload_layouts()

    # ---- restaurar tudo / saída
    def on_restore_all(self):
        n = self.mgr.restore_all()
        self.refresh()
        self.status.setText("%d janelas restauradas." % n)

    def closeEvent(self, ev):
        if self.mgr.changes():
            if self.ask_on_exit:
                r = QMessageBox.question(
                    self, "Janelas", "Remover o 'sempre no topo' e a transparência que você "
                    "aplicou nas janelas antes de sair?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel)
                if r == QMessageBox.StandardButton.Cancel:
                    ev.ignore()
                    return
                if r == QMessageBox.StandardButton.Yes:
                    self.mgr.restore_all()
            else:
                self.mgr.restore_all()
        ev.accept()


def main():
    core.set_dpi_aware()
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    w = Janelas()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
