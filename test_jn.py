"""Testes do Janelas: geometria e casamento com dados falsos, um teste real com QWidget
(topmost/opacidade) e smoke test da GUI offscreen. Rodar: python test_jn.py"""
import os
import sys
import tempfile
import unittest

# Testes reais precisam de HWND de verdade (plataforma windows); o smoke da GUI roda em
# subprocesso com QT_QPA_PLATFORM=offscreen.
if os.environ.get("JN_SMOKE") != "1":
    os.environ["QT_QPA_PLATFORM"] = "windows" if sys.platform == "win32" else "offscreen"
else:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import jn_core as c  # noqa: E402

WORK = (0, 0, 1920, 1040)
WORK2 = (1920, 0, 3840, 1080)


class Geometria(unittest.TestCase):
    def test_metades_e_quadrantes(self):
        self.assertEqual(c.preset_rect("left", WORK), (0, 0, 960, 1040))
        self.assertEqual(c.preset_rect("right", WORK), (960, 0, 1920, 1040))
        self.assertEqual(c.preset_rect("tl", WORK), (0, 0, 960, 520))
        self.assertEqual(c.preset_rect("br", WORK), (960, 520, 1920, 1040))
        self.assertEqual(c.preset_rect("tr", WORK2), (2880, 0, 3840, 540))

    def test_tamanho_fixo_centralizado_e_limitado(self):
        self.assertEqual(c.preset_rect("size:1280x720", WORK), (320, 160, 1600, 880))
        r = c.preset_rect("size:1920x1080", WORK)  # não cabe em 1040 de altura
        self.assertEqual((c.rect_w(r), c.rect_h(r)), (1920, 1040))

    def test_centralizar(self):
        self.assertEqual(c.center_rect((10, 10, 410, 310), WORK), (760, 370, 1160, 670))

    def test_mover_monitor(self):
        r = c.move_to_monitor((0, 0, 960, 520), WORK, WORK2)
        self.assertEqual(r[:2], (1920, 0))
        r = c.move_to_monitor((960, 520, 1920, 1040), WORK, WORK2)
        self.assertTrue(WORK2[0] <= r[0] and r[2] <= WORK2[2] and r[3] <= WORK2[3])
        # maior que o destino: encolhe
        r = c.move_to_monitor((0, 0, 3000, 2000), WORK, WORK2)
        self.assertEqual((c.rect_w(r), c.rect_h(r)), (1920, 1080))

    def test_indice_monitor(self):
        mons = [c.Monitor(1, (0, 0, 1920, 1080), WORK, True),
                c.Monitor(2, (1920, 0, 3840, 1080), WORK2)]
        self.assertEqual(c.monitor_index_for_rect((2000, 100, 2500, 400), mons), 1)
        self.assertEqual(c.monitor_index_for_rect((100, 100, 500, 400), mons), 0)
        self.assertEqual(c.next_monitor_index(1, 2), 0)

    def test_clamp_monitor_desconectado(self):
        mons = [c.Monitor(1, (0, 0, 1920, 1080), WORK, True)]
        r = c.clamp_to_any((5000, 100, 5500, 400), mons)
        self.assertTrue(0 <= r[0] and r[2] <= 1920)
        self.assertEqual(c.clamp_to_any((10, 10, 100, 100), mons), (10, 10, 100, 100))

    def test_alpha(self):
        self.assertEqual(c.percent_to_alpha(100), 255)
        self.assertEqual(c.percent_to_alpha(50), 128)
        self.assertEqual(c.percent_to_alpha(5), c.percent_to_alpha(20))
        self.assertEqual(c.alpha_to_percent(255), 100)


def W(h, title, proc):
    return c.WinInfo(hwnd=h, title=title, proc=proc, rect=(0, 0, 100, 100))


class Casamento(unittest.TestCase):
    def test_exato_e_parcial(self):
        wins = [W(1, "Sem título - Bloco de Notas", "notepad.exe"),
                W(2, "Google - Edge", "msedge.exe"),
                W(3, "YouTube - Edge", "msedge.exe")]
        entries = [{"proc": "msedge.exe", "title": "YouTube - Edge", "rect": [1, 2, 3, 4]},
                   {"proc": "msedge.exe", "title": "Outra aba - Edge", "rect": [5, 6, 7, 8]},
                   {"proc": "notepad.exe", "title": "nota.txt - Bloco de Notas",
                    "rect": [9, 9, 9, 9]}]
        res = c.match_layout(entries, wins)
        self.assertEqual(res[0][1].hwnd, 3)  # título exato ganha
        self.assertEqual(res[1][1].hwnd, 2)  # sobra a outra do Edge (mesma parte final)
        self.assertEqual(res[2][1].hwnd, 1)  # mesma parte final do título

    def test_processo_diferente_nao_casa_e_sem_reuso(self):
        wins = [W(1, "A", "a.exe")]
        entries = [{"proc": "b.exe", "title": "A"}, {"proc": "a.exe", "title": "A"},
                   {"proc": "a.exe", "title": "A"}]
        res = c.match_layout(entries, wins)
        self.assertIsNone(res[0][1])
        self.assertEqual(sum(1 for _, w in res if w), 1)

    def test_sem_psutil_casa_por_titulo(self):
        res = c.match_layout([{"proc": "", "title": "Foo"}], [W(1, "Foo", "")])
        self.assertEqual(res[0][1].hwnd, 1)
        res = c.match_layout([{"proc": "", "title": "Foo"}], [W(1, "Bar", "")])
        self.assertIsNone(res[0][1])

    def test_persistencia(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "sub", "layouts.json")
            self.assertEqual(c.load_layouts(p), {})
            data = {"Trabalho ç": [c.snapshot_entry(W(1, "Título é", "x.exe"))]}
            c.save_layouts(data, p)
            self.assertEqual(c.load_layouts(p), data)


@unittest.skipUnless(c.IS_WIN, "só Windows")
class Real(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_topmost_opacidade_e_restaurar(self):
        from PyQt6.QtWidgets import QWidget
        w = QWidget()
        w.setWindowTitle("JN-TESTE-JANELA")
        w.resize(300, 200)
        w.show()
        self.app.processEvents()
        hwnd = int(w.winId())
        m = c.Manager()
        self.assertFalse(c.window_info(hwnd).topmost)
        self.assertTrue(m.set_topmost(hwnd, True))
        self.assertTrue(c.window_info(hwnd).topmost)
        self.assertTrue(m.set_opacity(hwnd, 50))
        a = c.window_info(hwnd).alpha
        self.assertTrue(abs(a - 128) <= 1, a)
        self.assertIn(hwnd, m.changes())
        # geometria real
        c.place(hwnd, (100, 100, 500, 400))
        r = c.window_info(hwnd).rect
        self.assertEqual((c.rect_w(r), c.rect_h(r)), (400, 300))
        self.assertEqual(m.restore_all(), 1)
        info = c.window_info(hwnd)
        self.assertFalse(info.topmost)
        self.assertEqual(info.alpha, 255)
        w.close()

    def test_enum_acha_janela_e_exclui_propria(self):
        from PyQt6.QtWidgets import QWidget
        w = QWidget()
        w.setWindowTitle("JN-ENUM-TESTE")
        w.show()
        self.app.processEvents()
        self.assertTrue(any(x.title == "JN-ENUM-TESTE" for x in c.enum_windows()))
        self.assertFalse(any(x.title == "JN-ENUM-TESTE" for x in c.enum_windows([os.getpid()])))
        self.assertTrue(len(c.list_monitors()) >= 1)
        w.close()


class Gui(unittest.TestCase):
    def test_smoke_offscreen(self):
        import subprocess
        env = dict(os.environ, JN_SMOKE="1", PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "Gui.smoke"], env=env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])

    def smoke(self):
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        import importlib.util
        spec = importlib.util.spec_from_file_location("janelas_gui",
                                                      os.path.join(HERE, "janelas.pyw"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        app.setStyleSheet(mod.QSS)
        win = mod.Janelas(ask_on_exit=False)
        win.show()
        app.processEvents()
        win.search.setText("zzzz-nada")
        self.assertEqual(win.list.count(), 0)
        win.search.setText("")
        win.refresh()
        win.close()


if __name__ == "__main__":
    if sys.argv[1:] == ["Gui.smoke"]:
        Gui().smoke()
        print("smoke OK")
    else:
        unittest.main(verbosity=1)
