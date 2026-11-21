"""Tiny in-memory stand-in for the parts of PySide6 ZCLA uses.

Only installed by test_ui_smoke.py when real PySide6 is NOT importable, so the
UI wiring can be exercised headlessly in CI/Linux. Signals are synchronous.
"""
import sys
import types


class _Bound:
    def __init__(self):
        self.slots = []

    def connect(self, fn):
        self.slots.append(fn)

    def emit(self, *a):
        for fn in list(self.slots):
            fn(*a)


class Signal:
    def __init__(self, *types_):
        self.name = None

    def __set_name__(self, owner, name):
        self.name = '_sig_' + name

    def __get__(self, obj, owner):
        if obj is None:
            return self
        b = obj.__dict__.get(self.name)
        if b is None:
            b = obj.__dict__[self.name] = _Bound()
        return b


class _AnyMeta(type):
    def __getattr__(cls, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return _Any()


class _Any(metaclass=_AnyMeta):
    """Returned for unknown calls; absorbs everything."""

    def __init__(self, *a, **k):
        pass

    def __call__(self, *a, **k):
        return _Any()

    def __getattr__(self, name):
        return _Any()

    def __or__(self, other):
        return self

    def __int__(self):
        return 0

    def __bool__(self):
        return False

    def __iter__(self):
        return iter(())


class _Base:
    def __init__(self, *a, **k):
        self._text = a[0] if a and isinstance(a[0], str) else ''
        self._visible = False
        self._enabled = True
        self._checked = False
        self._value = 0
        self._props = {}
        self._range = (0, 10 ** 9)

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return _Any()

    def setText(self, t): self._text = t
    def text(self): return self._text
    def show(self): self._visible = True
    def hide(self): self._visible = False
    def setVisible(self, v): self._visible = bool(v)
    def isVisible(self): return self._visible
    def setEnabled(self, v): self._enabled = bool(v)
    def isEnabled(self): return self._enabled
    def setChecked(self, v):
        changed = bool(v) != self._checked
        self._checked = bool(v)
        if changed and hasattr(type(self), 'toggled'):
            self.toggled.emit(self._checked)
    def isChecked(self): return self._checked
    def setRange(self, lo, hi): self._range = (lo, hi)
    def setValue(self, v):
        self._value = max(self._range[0], min(self._range[1], v))
        if hasattr(type(self), 'valueChanged'):
            self.valueChanged.emit(self._value)
    def value(self): return self._value
    def setProperty(self, k, v): self._props[k] = v
    def property(self, k): return self._props.get(k)
    def width(self): return 900
    def height(self): return 980


class QObject(_Base):
    pass


class QWidget(_Base):
    pass


class QPushButton(QWidget):
    clicked = Signal()

    def click(self):
        if self._enabled:
            self.clicked.emit()


class QCheckBox(QWidget):
    toggled = Signal(bool)


class QSpinBox(QWidget):
    valueChanged = Signal(int)


class QDoubleSpinBox(QSpinBox):
    pass


class QSlider(QWidget):
    valueChanged = Signal(int)


class QLabel(QWidget):
    pass


class QMainWindow(QWidget):
    pass


class QDialog(QWidget):
    pass


class QTimer(_Base):
    timeout = Signal()
    pending = []

    def __init__(self, *a):
        super().__init__()
        self.active = False

    def start(self, *a): self.active = True
    def stop(self): self.active = False

    @staticmethod
    def singleShot(ms, fn):
        QTimer.pending.append(fn)

    @staticmethod
    def run_pending():
        while QTimer.pending:
            QTimer.pending.pop(0)()


class QApplication(_Base):
    _inst = None

    @staticmethod
    def screens():
        return []

    @staticmethod
    def instance():
        return QApplication._inst or _Any()


class QGuiApplication(QApplication):
    pass


class QRect:
    def __init__(self, x=0, y=0, w=0, h=0):
        self._r = (x, y, w, h)

    def x(self): return self._r[0]
    def y(self): return self._r[1]
    def width(self): return self._r[2]
    def height(self): return self._r[3]


class _Qt:
    def __getattr__(self, name):
        return 0


def install():
    mods = {}
    core = types.ModuleType('PySide6.QtCore')
    core.QObject, core.Signal, core.QTimer = QObject, Signal, QTimer
    core.Qt = _Qt()
    core.QRect = QRect
    for n in ('QUrl', 'QSize', 'QPoint'):
        setattr(core, n, _Any)
    gui = types.ModuleType('PySide6.QtGui')
    for n in ('QIcon', 'QPixmap', 'QPainter', 'QColor', 'QPen', 'QFont', 'QImage'):
        setattr(gui, n, _Any)
    gui.QGuiApplication = QGuiApplication
    widgets = types.ModuleType('PySide6.QtWidgets')
    for n, v in dict(QApplication=QApplication, QMainWindow=QMainWindow, QWidget=QWidget, QLabel=QLabel,
                     QPushButton=QPushButton, QDialog=QDialog, QSlider=QSlider, QCheckBox=QCheckBox,
                     QSpinBox=QSpinBox, QDoubleSpinBox=QDoubleSpinBox).items():
        setattr(widgets, n, v)
    for n in ('QVBoxLayout', 'QHBoxLayout', 'QFormLayout', 'QTextBrowser', 'QMessageBox'):
        setattr(widgets, n, _Any)
    mm = types.ModuleType('PySide6.QtMultimedia')
    mm.QMediaPlayer = mm.QAudioOutput = _Any
    pkg = types.ModuleType('PySide6')
    mods.update({'PySide6': pkg, 'PySide6.QtCore': core, 'PySide6.QtGui': gui,
                 'PySide6.QtWidgets': widgets, 'PySide6.QtMultimedia': mm})
    sys.modules.update(mods)
