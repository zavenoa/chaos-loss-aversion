"""Chaos Loss Aversion 1.1. Windows-only visual alert utility."""
from __future__ import annotations
import ctypes, json, os, random, sys, threading, time, webbrowser
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt, QObject, Signal, QUrl, QTimer, QRect, QPoint, QSize
from PySide6.QtGui import QPixmap, QIcon, QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QDialog, QSlider, QFormLayout, QMessageBox, QTextBrowser, QSpinBox)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

VERSION='1.1'
ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
CONFIG=Path(os.getenv('APPDATA',str(Path.home()))) / 'ChaosLossAversion' / 'config.json'
IMAGES=ROOT/'Images'
AUDIO=ROOT/'Audio Clips'

def load_config():
    try:
        config=json.loads(CONFIG.read_text(encoding='utf-8'))
        config.pop('send_esc',None)
        return config
    except (OSError,ValueError): return {}
def save_config(c):
    CONFIG.parent.mkdir(parents=True,exist_ok=True)
    tmp=CONFIG.with_suffix('.tmp'); tmp.write_text(json.dumps(c,indent=2),encoding='utf-8'); tmp.replace(CONFIG)

def capture(region=None):
    import dxcam
    camera=dxcam.create(output_color='RGB')
    try:
        for _ in range(30):
            img=camera.grab(region=region)
            if img is not None: return img.copy()
            time.sleep(.025)
        raise RuntimeError('Screen capture timed out')
    finally:
        camera.release()

def signature(neg, pos):
    # Sample high-contrast, spatially distributed RGB pixels, rejecting edges/hover noise.
    if neg.shape != pos.shape: raise ValueError('Calibration images have different dimensions')
    h,w=neg.shape[:2]
    a=neg.astype(np.int16); b=pos.astype(np.int16)
    diff=np.max(np.abs(a-b),axis=2)
    # Use only the lower horizontal border and lower sections of the vertical
    # borders. Hovering a Chaos Orb can obscure the top half with its tooltip.
    yy,xx=np.indices((h,w))
    band=max(3,min(h,w)//9)
    lower=yy>=int(h*0.55)
    mask=lower & ((xx<band)|(xx>=w-band)|(yy>=h-band))
    mask[:2,:]=False; mask[-2:,:]=False; mask[:,:2]=False; mask[:,-2:]=False
    ranked=np.argsort(np.where(mask,diff,-1).ravel())[::-1]
    picks=[]; spacing=max(3,min(h,w)//24)
    for idx in ranked:
        y,x=divmod(int(idx),w)
        if diff[y,x]<35: break
        if all((x-px)**2+(y-py)**2>=spacing**2 for px,py in picks): picks.append((x,y))
        if len(picks)>=24: break
    if len(picks)<4: raise ValueError('Insufficient LOWER border contrast. Ensure the lower gold border is visible in the positive calibration and recapture.')
    return {'points':picks,'negative':[neg[y,x].tolist() for x,y in picks],
            'positive':[pos[y,x].tolist() for x,y in picks], 'threshold':36, 'region':'lower-border-v2'}

def detect_slot_border(gray):
    """Find a supported, complete rectangular frame, not the largest random contour.

    Only used by the calibration workflow; never imported or executed by Monitor.
    """
    import cv2
    h,w=gray.shape
    if min(h,w)<35: raise ValueError('Selection is too small. Include the entire slot border.')
    blur=cv2.GaussianBlur(gray,(3,3),0)
    edges=cv2.Canny(blur,30,105)
    # Close small decorative gaps while preserving the rectangular frame.
    closed=cv2.morphologyEx(edges,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    contours,_=cv2.findContours(closed,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    candidates=[]
    for contour in contours:
        x,y,cw,ch=cv2.boundingRect(contour)
        if cw<0.62*w or ch<0.62*h or cw>0.995*w or ch>0.995*h: continue
        if x<1 or y<1 or x+cw>=w-1 or y+ch>=h-1: continue
        # Verify all four edges independently; a large interior contour is not enough.
        margin=max(2,min(cw,ch)//30)
        roi=edges[y:y+ch,x:x+cw]
        top=np.mean(np.max(roi[:margin+2,:],axis=0)>0)
        bottom=np.mean(np.max(roi[-margin-2:,:],axis=0)>0)
        left=np.mean(np.max(roi[:,:margin+2],axis=1)>0)
        right=np.mean(np.max(roi[:,-margin-2:],axis=1)>0)
        coverage=min(top,bottom,left,right)
        if coverage<0.52: continue
        area=(cw*ch)/(w*h)
        # Favor the OUTERMOST fully supported border; do not select inner ornamentation.
        candidates.append((coverage*0.35+area*0.65,x,y,cw,ch))
    if not candidates:
        raise ValueError('Could not verify all four outer slot borders. Draw a slightly wider box around the entire slot, leaving a little background outside its frame.')
    _,x,y,cw,ch=max(candidates)
    return x,y,cw,ch

class Bus(QObject):
    state=Signal(str)
    match=Signal(bool)
    overlay_toggle=Signal()
    error=Signal(str)
    calibration_capture=Signal()
    toggle=Signal()

class _CursorPoint(ctypes.Structure):
    _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]

class Monitor:
    def __init__(self,bus):
        self.bus=bus
        self.stop_event=threading.Event()
        self.thread=None
        self._lock=threading.Lock()
    @property
    def running(self):
        with self._lock:
            return self.thread is not None and self.thread.is_alive() and not self.stop_event.is_set()
    def start(self,profile):
        with self._lock:
            if self.thread is not None and self.thread.is_alive():
                return False
            self.stop_event=threading.Event()
            stop=self.stop_event
            self.thread=threading.Thread(target=self._run,args=(profile,stop),daemon=True,name='CLA Monitor')
            self.thread.start()
        return True
    def stop(self, wait=False, timeout=2.5):
        # Snapshot under the lock; never join while holding it.
        with self._lock:
            self.stop_event.set()
            thread=self.thread
        if wait and thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        return thread is None or not thread.is_alive()
    def _run(self,profile,stop):
        cam=None
        try:
            import dxcam
            box=tuple(profile['box']); sig=profile['signature']
            pts=np.array(sig['points'],dtype=np.intp)
            # Older calibrations sampled the upper border, where the Chaos Orb
            # tooltip can obscure the highlight. Require a fresh lower-border
            # calibration instead of silently using those unreliable pixels.
            if sig.get('region') != 'lower-border-v2':
                raise ValueError('v0.14 needs one fresh calibration to sample the lower gold border. Please recalibrate.')
            xs=pts[:,0]; ys=pts[:,1]
            pos=np.array(sig['positive'],dtype=np.int16); neg=np.array(sig['negative'],dtype=np.int16)
            cam=dxcam.create(output_color='RGB')
            self.bus.state.emit('MONITORING')
            was_matching=False
            awaiting_negative=False
            consecutive_negative=0
            transition_started=0.0
            transition_changed=0
            previous_interior=None
            click_baseline=None
            # Read the physical left-button edge in the capture thread, avoiding
            # additional threads, hooks, or latency in the visual detection path.
            user32=ctypes.windll.user32
            user32.GetAsyncKeyState.argtypes=[ctypes.c_int]
            user32.GetAsyncKeyState.restype=ctypes.c_short
            user32.GetCursorPos.argtypes=[ctypes.POINTER(_CursorPoint)]
            user32.GetCursorPos.restype=ctypes.c_int
            user32.GetSystemMetrics.argtypes=[ctypes.c_int]
            user32.GetSystemMetrics.restype=ctypes.c_int
            # dxcam uses physical desktop pixels. GetPhysicalCursorPos also
            # returns physical pixels on DPI-scaled displays.
            get_cursor=getattr(user32,'GetPhysicalCursorPos',user32.GetCursorPos)
            get_cursor.argtypes=[ctypes.POINTER(_CursorPoint)]
            get_cursor.restype=ctypes.c_int
            button_was_down=bool(user32.GetAsyncKeyState(0x01) & 0x8000)
            point=_CursorPoint()
            while not stop.is_set():
                button_down=bool(user32.GetAsyncKeyState(0x01) & 0x8000)
                if button_down and not button_was_down and was_matching:
                    if get_cursor(ctypes.byref(point)):
                        if box[0] <= point.x < box[2] and box[1] <= point.y < box[3]:
                            was_matching=False
                            awaiting_negative=True
                            consecutive_negative=0
                            transition_started=time.perf_counter()
                            transition_changed=0
                            click_baseline=previous_interior
                            self.bus.match.emit(False)
                button_was_down=button_down
                frame=cam.grab(region=box)
                if frame is None:
                    time.sleep(.002); continue
                h,w=frame.shape[:2]
                interior=frame[h//3:2*h//3:4,w//3:2*w//3:4].copy()
                previous_interior=interior
                pixels=frame[ys,xs].astype(np.int16)
                # Evaluate both references on captured frames. After a click,
                # do not permit a new match until two consecutive confirmed
                # negative frames have established that the old item changed.
                dp=np.max(np.abs(pixels-pos),axis=1)
                dn=np.max(np.abs(pixels-neg),axis=1)
                threshold=int(sig.get('threshold',36))
                positive_votes=(dp<=threshold) & (dp+18<dn)
                negative_votes=(dn<=threshold) & (dn+18<dp)
                n=len(dp)
                pos_count=int(np.count_nonzero(positive_votes))
                neg_count=int(np.count_nonzero(negative_votes))
                # Prefer negative when the border is ambiguous. This prevents
                # a previously matching item from staying red after it changes.
                is_matching=(pos_count >= max(4,(n*3+3)//4)
                             and pos_count>neg_count*2
                             and float(np.median(dp)) + 12 < float(np.median(dn)))
                is_negative=(neg_count >= max(4,(n*3+3)//4)
                             and neg_count>pos_count*2
                             and float(np.median(dn)) + 12 < float(np.median(dp)))
                if awaiting_negative:
                    consecutive_negative = consecutive_negative + 1 if is_negative else 0
                    changed=False
                    if click_baseline is not None and click_baseline.shape == interior.shape:
                        delta=np.max(np.abs(interior.astype(np.int16)-click_baseline.astype(np.int16)),axis=2)
                        changed=float(np.mean(delta >= 32)) >= 0.20
                    transition_changed = transition_changed + 1 if changed else 0
                    elapsed=time.perf_counter()-transition_started
                    if (consecutive_negative >= 2 or transition_changed >= 2 or elapsed >= 0.25):
                        awaiting_negative=False
                        consecutive_negative=0
                        transition_changed=0
                        click_baseline=None
                    # Re-evaluate on the next fresh capture, never the transition frame.
                    continue
                if is_matching and not was_matching:
                    was_matching=True
                    self.bus.match.emit(True)
        except Exception as exc:
            if not stop.is_set(): self.bus.error.emit(str(exc))
        finally:
            if cam is not None:
                try: cam.release()
                except Exception: pass
            self.bus.state.emit('NOT MONITORING')

class Selection(QWidget):
    selected=Signal(tuple)
    cancelled=Signal()
    def __init__(self):
        super().__init__(); self.setWindowFlags(Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground); self.setCursor(Qt.CrossCursor)
        self.start=None; self.end=None; self.completed=False
        # Multi-monitor desktop coordinate mapping is supported by Qt virtual geometry.
        rect=QApplication.primaryScreen().virtualGeometry(); self.setGeometry(rect)
    def mousePressEvent(self,e):
        if e.button()==Qt.LeftButton: self.start=e.position().toPoint(); self.end=self.start; self.update()
    def mouseMoveEvent(self,e):
        if self.start: self.end=e.position().toPoint(); self.update()
    def mouseReleaseEvent(self,e):
        if self.start and e.button()==Qt.LeftButton:
            self.end=e.position().toPoint(); r=QRect(self.start,self.end).normalized()
            if r.width()>20 and r.height()>20:
                # Successful selection must not also fire the cancellation path.
                self.completed=True
                g=self.geometry(); self.selected.emit((r.left()+g.left(),r.top()+g.top(),r.right()+g.left()+1,r.bottom()+g.top()+1))
                self.close()
            else: self.start=None; self.update()
    def paintEvent(self,e):
        p=QPainter(self); p.fillRect(self.rect(),QColor(0,0,0,90))
        p.setPen(QColor('#ffffff')); p.setFont(QFont('Segoe UI',15,QFont.Bold))
        p.drawText(30,50,'Drag a rectangle around the CENTER Currency Tab item slot (ESC to cancel)')
        if self.start and self.end:
            r=QRect(self.start,self.end).normalized(); p.setCompositionMode(QPainter.CompositionMode_Clear); p.fillRect(r,Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver); p.setPen(QPen(QColor('#e4b66d'),3)); p.drawRect(r)
    def keyPressEvent(self,e):
        if e.key()==Qt.Key_Escape:
            self.close()
            e.accept()
        else: super().keyPressEvent(e)
    def closeEvent(self,e):
        if not self.completed: self.cancelled.emit()
        super().closeEvent(e)

class MonitorOutline(QWidget):
    """Click-through frame OUTSIDE the captured region; no frame capture or polling.

    Coordinates are native desktop pixels. The 6-pixel exterior gutter avoids
    contaminating the detector's own captured border pixels.
    """
    def __init__(self):
        super().__init__(None)
        self.color=QColor('#35bf73')
        self.thickness=10
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def show_box(self, box, thickness=10, opacity=80, color='#e4b64d'):
        self.thickness=max(5,min(20,int(thickness)))
        self.setWindowOpacity(max(0.2,min(1.0,opacity/100)))
        self.color=QColor(color)
        left,top,right,bottom=map(int,box)
        if right<=left or bottom<=top:
            self.hide(); return
        # 6px gutter puts every drawn pixel OUTSIDE dxcam's region.
        pad=6+self.thickness
        self.setGeometry(left-pad,top-pad,right-left+2*pad,bottom-top+2*pad)
        self.update()
        self.show()
        self._make_windows_click_through()

    def _make_windows_click_through(self):
        if sys.platform!='win32': return
        try:
            import ctypes
            hwnd=int(self.winId())
            GWL_EXSTYLE=-20
            WS_EX_TRANSPARENT=0x20
            WS_EX_LAYERED=0x80000
            WS_EX_NOACTIVATE=0x08000000
            user32=ctypes.windll.user32
            user32.SetWindowLongW(hwnd,GWL_EXSTYLE,
                user32.GetWindowLongW(hwnd,GWL_EXSTYLE) |
                WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE)
        except Exception:
            pass  # Qt's WindowTransparentForInput is the primary safeguard.

    def paintEvent(self,event):
        painter=QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing,False)
        painter.setPen(QPen(self.color,self.thickness))
        inset=self.thickness//2+1
        painter.drawRect(self.rect().adjusted(inset,inset,-inset-1,-inset-1))
        painter.end()

class Settings(QDialog):
    def __init__(self,parent):
        super().__init__(parent); self.parent_app=parent; self.setWindowTitle('CLA Settings'); self.setMinimumWidth(370)
        lay=QVBoxLayout(self)
        lay.addWidget(QLabel('Display/Hide stoplight outline'))
        self.overlay_hot=QPushButton(parent.config.get('overlay_hotkey','F7').upper()); lay.addWidget(self.overlay_hot)
        lay.addWidget(QLabel('Monitor toggle hotkey'))
        self.hot=QPushButton(parent.config.get('hotkey','F8').upper()); lay.addWidget(self.hot)
        lay.addWidget(QLabel('Calibration capture hotkey'))
        self.cap=QPushButton(parent.config.get('capture_hotkey','F9').upper()); lay.addWidget(self.cap)
        self.hot.clicked.connect(lambda:self.bind(self.hot))
        self.cap.clicked.connect(lambda:self.bind(self.cap))
        self.overlay_hot.clicked.connect(lambda:self.bind(self.overlay_hot))
        lay.addWidget(QLabel('Outline thickness (pixels)'))
        self.overlay_width=QSpinBox()
        self.overlay_width.setRange(5,20)
        self.overlay_width.setValue(parent.config.get('overlay_width',10))
        lay.addWidget(self.overlay_width)
        lay.addWidget(QLabel('Outline opacity'))
        self.overlay_opacity=QSlider(Qt.Horizontal)
        self.overlay_opacity.setRange(20,100)
        self.overlay_opacity.setValue(parent.config.get('overlay_opacity',80))
        lay.addWidget(self.overlay_opacity)
        lay.addWidget(QLabel('Notification volume'))
        self.volume=QSlider(Qt.Horizontal); self.volume.setRange(0,100); self.volume.setValue(parent.config.get('volume',70)); lay.addWidget(self.volume)
        done=QPushButton('Save Settings'); lay.addWidget(done); done.clicked.connect(self.commit)
        self._binding=None
    def bind(self,button):
        self._binding=button; button.setText('Press a key…'); button.setFocus()
    def keyPressEvent(self,e):
        if self._binding:
            key=e.key(); name=Qt.Key(key).name if False else e.text().upper()
            mapping={getattr(Qt,'Key_F'+str(i)):'F'+str(i) for i in range(1,13)}
            name=mapping.get(key,name)
            if not name or name in ('ESC','ESCAPE'): QMessageBox.warning(self,'Invalid hotkey','Choose F1–F12 or a printable key.'); return
            self._binding.setText(name); self._binding=None
        else: super().keyPressEvent(e)
    def commit(self):
        bindings=[self.hot.text().upper(),self.cap.text().upper(),self.overlay_hot.text().upper()]
        if len(set(bindings))!=3 or any(v=='PRESS A KEY…' for v in bindings):
            QMessageBox.warning(self,'Conflict','All three hotkeys must be assigned different keys.'); return
        self.parent_app.config.update(hotkey=bindings[0],capture_hotkey=bindings[1],overlay_hotkey=bindings[2],volume=self.volume.value(),overlay_width=self.overlay_width.value(),overlay_opacity=self.overlay_opacity.value())
        # Old versions stored a checkbox preference; F7 is now the sole visibility control.
        self.parent_app.config.pop('overlay_enabled',None)
        save_config(self.parent_app.config); self.parent_app.install_hotkeys(); self.parent_app.refresh(force_outline=True); self.accept()

class BannerStrip(QWidget):
    """Aspect-preserving image banner with optional optical positioning."""
    def __init__(self, image, height, parent=None, optical_offset=0):
        super().__init__(parent)
        self.art = QPixmap(str(IMAGES / image))
        self.optical_offset = optical_offset
        self.setFixedHeight(height)
        self.setStyleSheet('background:transparent')

    def paintEvent(self, event):
        painter = QPainter(self)
        # Blend transparent artwork into the application's background.
        painter.fillRect(self.rect(), QColor('#050506'))
        if not self.art.isNull():
            target = self.art.scaled(self.width(), self.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = (self.width() - target.width()) // 2 + self.optical_offset
            y = (self.height() - target.height()) // 2
            painter.drawPixmap(x, y, target)
        painter.end()

class Main(QMainWindow):
    def __init__(self):
        super().__init__(); self.config=load_config(); self.bus=Bus(); self.monitor=Monitor(self.bus)
        self.bus.state.connect(self.on_state); self.bus.match.connect(self.on_match); self.bus.error.connect(self.on_error)
        self.bus.toggle.connect(self.toggle); self.bus.calibration_capture.connect(self.capture_state); self.bus.overlay_toggle.connect(self.toggle_overlay)
        self._shutting_down=False
        self.stage=0; self.box=None; self.neg=None; self.pos=None; self.hotkeys=[]; self.outline=MonitorOutline(); self.matched=False; self.overlay_visible=True; self.monitor_requested=False
        self.player=QMediaPlayer(self); self.audio=QAudioOutput(self); self.player.setAudioOutput(self.audio)
        self.setWindowTitle(f'Chaos Loss Aversion | Version {VERSION}')
        self.setWindowIcon(QIcon(str(IMAGES/'Chaos Orb.png')))
        self.resize(900,960); self.setMinimumSize(730,780); self._normal_height=960
        self.build_ui(); self.install_hotkeys(); self.refresh()
    def build_ui(self):
        root=QWidget(); self.setCentralWidget(root)
        root.setStyleSheet('''QWidget{background:#050506;color:#f1e7d7;font:17px "Segoe UI"} QPushButton{background:#222126;border:1px solid #79654b;border-radius:7px;padding:10px;color:#f7ead6} QPushButton:hover{background:#3a3030} QLabel{background:transparent}''')
        lay=QVBoxLayout(root); lay.setContentsMargins(22,12,22,12); lay.setSpacing(9)
        # Full-width image strip, with controls over the unused left/right margins.
        self.top_banner=BannerStrip('Chaos Loss Aversion Logo.png', 154)
        top_layout=QHBoxLayout(self.top_banner)
        top_layout.setContentsMargins(5, 8, 5, 8)
        cal=QPushButton('  Calibrate')
        cal.setIcon(QIcon(str(IMAGES/'Calibrate Icon White.png')))
        cal.setIconSize(QSize(16,16))
        cal.setStyleSheet('QPushButton{background:#303035;border:1px solid #79654b;padding:9px 12px;} QPushButton:hover{background:#454047;}')
        cal.clicked.connect(self.calibrate)
        top_layout.addWidget(cal, 0, Qt.AlignTop)
        top_layout.addStretch(1)
        settings=QPushButton('⚙ Settings')
        settings.setStyleSheet('QPushButton{background:#303035;border:1px solid #79654b;padding:9px 12px;} QPushButton:hover{background:#454047;}')
        settings.clicked.connect(self.settings)
        top_layout.addWidget(settings, 0, Qt.AlignTop)
        lay.addWidget(self.top_banner)
        self.note=QLabel('Only the center item slot in the Currency Tab is supported at this time.'); self.note.setAlignment(Qt.AlignCenter)
        self.note.setStyleSheet('color:#e8ba76;font-weight:bold;font-size:18px'); self.note.setWordWrap(True); lay.addWidget(self.note)
        self.panel=QWidget(); self.panel.setStyleSheet('background:rgba(0,0,0,190);border:1px solid #594a36;border-radius:12px')
        panel=QVBoxLayout(self.panel); panel.setContentsMargins(20,20,20,20); panel.setSpacing(12)
        self.status=QLabel(); self.status.setAlignment(Qt.AlignCenter); self.status.setWordWrap(True)
        self.status.setStyleSheet('font-size:27px;font-weight:bold;border:0'); panel.addWidget(self.status,1)
        self.instructions=QLabel(); self.instructions.setAlignment(Qt.AlignCenter); self.instructions.setWordWrap(True)
        self.instructions.setStyleSheet('font-size:17px;border:0'); panel.addWidget(self.instructions)
        self.preview=QLabel(); self.preview.setAlignment(Qt.AlignCenter); self.preview.setStyleSheet('border:0'); self.preview.setSizePolicy(self.preview.sizePolicy().horizontalPolicy(),self.preview.sizePolicy().verticalPolicy()); panel.addWidget(self.preview,0)
        self.confirm=QWidget(); c=QHBoxLayout(self.confirm); self.no=QPushButton('No'); self.yes=QPushButton('Yes'); c.addWidget(self.no); c.addWidget(self.yes)
        for button in (self.no,self.yes):
            button.setMinimumHeight(44)
            button.setStyleSheet('QPushButton{background:#303035;color:#f4eebc;border:1px solid #79654b;border-radius:7px;padding:10px 16px;font:17px "Segoe UI";} QPushButton:hover{background:#454047;border-color:#b58a43;} QPushButton:pressed{background:#55443b;}')
        self.no.clicked.connect(self.restart_selection); self.yes.clicked.connect(self.confirm_slot); panel.addWidget(self.confirm)
        self.warning=QLabel('WARNING: Changing Display Mode or Resolution will require recalibration.')
        self.warning.setAlignment(Qt.AlignCenter); self.warning.setWordWrap(True); self.warning.setStyleSheet('color:#d6a77b;font-size:15px;border:0'); panel.addWidget(self.warning)
        lay.addWidget(self.panel,1)
        self.toggle_btn=QPushButton(); self.toggle_btn.setMinimumHeight(55); self.toggle_btn.clicked.connect(self.toggle); lay.addWidget(self.toggle_btn)
        # Centered PoE2 mark in the formerly empty space above Regex Tools.
        self.poe_logo=QLabel()
        self.poe_logo.setAlignment(Qt.AlignCenter)
        poe_art=QPixmap(str(IMAGES/'PoE2 Logo.png'))
        if not poe_art.isNull():
            self.poe_logo.setPixmap(poe_art.scaled(220,165,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        self.poe_logo.setMinimumHeight(115)
        lay.addWidget(self.poe_logo,1)
        regex=QLabel('REGEX TOOLS'); regex.setAlignment(Qt.AlignCenter)
        regex.setStyleSheet('color:#e8ba76;font-weight:bold;font-size:18px'); lay.addWidget(regex)
        links=QHBoxLayout()
        for label,filename,url in [('Waystones','Waystone Icon.webp','https://poe2.re/waystone/'),('Tablets','Tablet Icon.webp','https://poe2.re/tablet/'),('Equipment','Renlys Tools Icon.svg','https://Renlys.Tools/')]:
            btn=QPushButton(label); btn.setIcon(QIcon(str(IMAGES/filename))); btn.clicked.connect(lambda _,u=url:webbrowser.open(u)); links.addWidget(btn)
        lay.addLayout(links)
        db=QPushButton('PoE2DB  |  Modifiers'); db.clicked.connect(lambda:webbrowser.open('https://poe2db.tw/us/Modifiers'))
        db.setIcon(QIcon(str(IMAGES/'PoE2DB Icon.png'))); db.setMinimumHeight(49); lay.addWidget(db)
        self.bottom_banner=BannerStrip('Tier Twolongs Banner.png', 226, optical_offset=-9)
        bottom_layout=QHBoxLayout(self.bottom_banner)
        bottom_layout.setContentsMargins(0, 0, 0, 2)
        version=QLabel(f'Version {VERSION}')
        version.setStyleSheet('color:#c8c8c8;font-size:14px;background:transparent')
        bottom_layout.addWidget(version, 0, Qt.AlignBottom)
        bottom_layout.addStretch(1)
        about=QPushButton('About')
        about.setStyleSheet('QPushButton{background:transparent;border:0;color:#c8c8c8;font-size:14px;padding:2px 6px;} QPushButton:hover{color:#f4eebc;text-decoration:underline;}')
        about.clicked.connect(self.show_about)
        bottom_layout.addWidget(about,0,Qt.AlignBottom)
        lay.addWidget(self.bottom_banner)
    def install_hotkeys(self):
        if self._shutting_down: return
        try:
            import keyboard
            for h in self.hotkeys: keyboard.remove_hotkey(h)
            self.hotkeys=[]
            self.hotkeys.append(keyboard.add_hotkey(self.config.get('hotkey','f8'),self.bus.toggle.emit,suppress=False))
            self.hotkeys.append(keyboard.add_hotkey(self.config.get('capture_hotkey','f9'),self.bus.calibration_capture.emit,suppress=False))
            self.hotkeys.append(keyboard.add_hotkey(self.config.get('overlay_hotkey','f7'),self.bus.overlay_toggle.emit,suppress=False))
        except Exception as exc: QMessageBox.warning(self,'Hotkeys unavailable',str(exc))
    def refresh(self,force_outline=False):
        if self._shutting_down: return
        profile=self.config.get('profile')
        active=self.monitor_requested
        self.update_outline(force=force_outline)
        self.confirm.hide(); self.preview.hide(); self.warning.setVisible(bool(profile) and self.stage==0)
        self.toggle_btn.setVisible(bool(profile) and self.stage==0)
        hk=self.config.get('hotkey','f8').upper()
        self.toggle_btn.setText(f'{hk} to Stop' if active else f'{hk} to Monitor')
        self.toggle_btn.setStyleSheet('background:#8d242b;color:white;font-weight:bold;font-size:21px' if active else 'background:#186a3b;color:white;font-weight:bold;font-size:21px')
        if self.stage==0:
            if not profile: status='Calibration Required!'
            elif not active: status='READY — NOT MONITORING'
            elif self.matched: status='MATCH DETECTED — MONITORING'
            else: status='MONITORING — NO MATCH'
            self.status.setText(status)
            self.status.setStyleSheet('font-size:32px;font-weight:bold;color:#ff5555;border:0' if not profile else 'font-size:27px;font-weight:bold;color:#f1e7d7;border:0')
            self.instructions.setText('Press '+self.config.get('overlay_hotkey','F7').upper()+' to show/hide the stoplight outline.' if profile else '')
    def update_outline(self,force=False):
        profile=self.config.get('profile')
        if self.stage or not profile or not self.overlay_visible:
            self.outline.hide(); return
        thickness=max(5,min(20,int(self.config.get('overlay_width',10))))
        color='#e4b64d' if not self.monitor_requested else ('#c62828' if self.matched else '#35bf73')
        box=profile['box']; opacity=self.config.get('overlay_opacity',80)
        # Avoid recreating the native overlay window on each capture/transition.
        if (force or not self.outline.isVisible() or self.outline.color != QColor(color)
                or self.outline.thickness != thickness):
            self.outline.show_box(box,thickness,opacity,color=color)
    def toggle_overlay(self):
        if self._shutting_down: return
        self.overlay_visible=not self.overlay_visible
        self.update_outline(force=True)
    def on_state(self,state):
        if self._shutting_down or self.stage: return
        if state=='NOT MONITORING' and self.monitor_requested and not self.monitor.running:
            # The capture thread exited unexpectedly. Don't leave a false green/red state.
            self.monitor_requested=False; self.matched=False
        self.refresh()
    def on_match(self,is_matching):
        if self._shutting_down or not self.monitor_requested or self.stage: return
        was_matching=self.matched
        self.matched=is_matching
        self.refresh()
        if is_matching and not was_matching:
            files=list(AUDIO.glob('*.mp3'))
            if files:
                self.audio.setVolume(self.config.get('volume',70)/100)
                self.player.setSource(QUrl.fromLocalFile(str(random.choice(files))))
                self.player.play()
    def on_error(self,message):
        if self._shutting_down: return
        self.monitor_requested=False; self.matched=False
        self.refresh()
        QMessageBox.warning(self,'CLA Error',message)
    def toggle(self):
        if self._shutting_down or self.stage: return
        if self.monitor_requested:
            self.monitor_requested=False
            self.monitor.stop(); self.matched=False; self.refresh(); return
        profile=self.config.get('profile')
        if not profile: return
        # The previous capture thread may still be releasing dxcam; retry shortly.
        if self.monitor.start(profile):
            self.monitor_requested=True; self.matched=False; self.refresh()
        else:
            QTimer.singleShot(100,self._retry_start)
    def _retry_start(self):
        if self._shutting_down: return
        if not self.monitor_requested and self.stage==0:
            self.toggle()
    def show_about(self):
        dialog=QDialog(self)
        dialog.setWindowTitle(f'About Chaos Loss Aversion — {VERSION}')
        dialog.resize(650,550)
        dialog.setStyleSheet('QDialog{background:#101012;color:#e4d7a0;} QTextBrowser{background:#1b1919;color:#e4d7a0;border:1px solid #956326;border-radius:7px;padding:14px;font:14px "Segoe UI";} QPushButton{background:#303035;color:#f4eebc;border:1px solid #956326;border-radius:6px;padding:8px 22px;}')
        layout=QVBoxLayout(dialog)
        heading=QLabel('CHAOS LOSS AVERSION')
        heading.setAlignment(Qt.AlignCenter)
        heading.setStyleSheet('color:#d0b570;font-size:23px;font-weight:bold;')
        layout.addWidget(heading)
        body=QTextBrowser()
        readme=ROOT/'README.txt'
        try: content=readme.read_text(encoding='utf-8')
        except OSError: content='README not available.'
        import html
        import re
        def fmt(line):
            line=html.escape(line)
            return re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', line)
        lines=[]
        for line in content.splitlines():
            if line.startswith('## '):
                lines.append('<h3 style="color:#d0b570;margin:16px 0 6px">'+fmt(line[3:])+'</h3>')
            elif line.startswith('# '):
                lines.append('<h2 style="color:#f4eebc;margin:8px 0">'+fmt(line[2:])+'</h2>')
            elif line.startswith('- '):
                lines.append('<div style="margin-left:14px">• '+fmt(line[2:])+'</div>')
            elif line.strip():
                lines.append('<div>'+fmt(line)+'</div>')
            else:
                lines.append('<div style="height:9px"></div>')
        body.setHtml('<div style="line-height:1.5;color:#e4d7a0">'+''.join(lines)+'</div>')
        layout.addWidget(body)
        close=QPushButton('Close'); close.clicked.connect(dialog.accept)
        layout.addWidget(close,0,Qt.AlignRight)
        dialog.exec()
    def settings(self): Settings(self).exec()
    def calibrate(self):
        self.monitor.stop(); self.monitor_requested=False; self.outline.hide(); self.preview.setMinimumHeight(0); self.resize(self.width(),self._normal_height); self.stage=1; self.box=None; self.neg=None; self.pos=None
        self.status.setText('Calibration in progress. — Step 1 of 4')
        self.instructions.setText('Left click and drag a box around the CENTER item slot in your Currency Tab. Include its border, but no other slots. A schematic example appears below. Click here to begin selection.')
        self.preview.show(); self.preview.setPixmap(self.example())
        self.warning.hide(); self.toggle_btn.hide()
        self.preview.mousePressEvent=lambda e:self.begin_selection()
        QTimer.singleShot(250,self.begin_selection)
    def example(self):
        pix=QPixmap(300,135); pix.fill(QColor('#151515')); p=QPainter(pix)
        for row in range(2):
            for col in range(4):
                x=30+col*60; y=12+row*58
                p.setPen(QPen(QColor('#e7bb75') if (row,col)==(0,1) else QColor('#555'),3 if (row,col)==(0,1) else 1))
                p.drawRect(x,y,52,52)
        p.end(); return pix
    def begin_selection(self):
        if self.stage!=1:return
        self.hide(); QTimer.singleShot(180,self.show_selection)
    def show_selection(self):
        self.sel=Selection(); self.sel.selected.connect(self.on_selected); self.sel.cancelled.connect(self.on_selection_cancelled)
        self.sel.show(); self.sel.activateWindow(); self.sel.setFocus()
    def on_selection_cancelled(self):
        # Restore the main window immediately; Qt.Tool windows may only hide on close.
        self.stage=0
        self.box=None; self.neg=None; self.pos=None
        self.preview.hide(); self.confirm.hide()
        self.resize(self.width(),self._normal_height)
        self.refresh()
        self.showNormal(); self.raise_(); self.activateWindow()
        self.sel.deleteLater()
        self.sel=None
    def restart_selection(self): self.stage=1; self.calibrate()
    def on_selected(self,box):
        self.box=box; self.stage=2; self.show(); self.raise_(); self.activateWindow()
        try:
            frame=capture(box)
            import cv2
            gray=cv2.cvtColor(frame,cv2.COLOR_RGB2GRAY)
            x,y,cw,ch=detect_slot_border(gray)
            self.box=(box[0]+x,box[1]+y,box[0]+x+cw,box[1]+y+ch)
            exact=frame[y:y+ch,x:x+cw]
            q=QPixmap.fromImage(self.to_qimage(exact)).scaled(250,250,Qt.KeepAspectRatio,Qt.FastTransformation)
            self.status.setText('Calibration in progress. — Step 2 of 4')
            self.instructions.setText('Is this the center item slot of your Currency Tab?')
            self.preview.setPixmap(q); self.preview.setMinimumHeight(q.height()+8)
            self.preview.show(); self.confirm.show()
            self.panel.layout().activate()
            self.centralWidget().layout().activate()
            needed=max(self._normal_height, self.sizeHint().height(), self.height()+max(0,q.height()+8-self.preview.height()))
            available=self.screen().availableGeometry().height() if self.screen() else needed
            self.resize(self.width(),min(needed,available))
            self.updateGeometry()
        except Exception as exc:
            QMessageBox.warning(self,'Slot border not found',str(exc)); self.restart_selection()
    @staticmethod
    def to_qimage(arr):
        from PySide6.QtGui import QImage
        a=np.ascontiguousarray(arr); h,w=a.shape[:2]
        return QImage(a.data,w,h,3*w,QImage.Format_RGB888).copy()
    def confirm_slot(self):
        self.stage=3; self.preview.setMinimumHeight(0); self.confirm.hide(); self.preview.hide(); self.resize(self.width(),self._normal_height); self.instructions.setText('Enter a keyword search in your stash. Place an item that DOES NOT match the search in the center Currency Tab slot. Move the mouse outside the slot, then press '+self.config.get('capture_hotkey','f9').upper()+' to capture NEGATIVE state.')
        self.status.setText('Calibration in progress. — Step 3 of 4')
    def capture_state(self):
        if self.stage not in (3,4): return
        try:
            frame=capture(self.box)
            if self.stage==3:
                self.neg=frame; self.stage=4
                self.status.setText('Calibration in progress. — Step 4 of 4')
                self.instructions.setText('Enter a keyword search in your stash. Place an item that MATCHES the search in the center Currency Tab slot. Move the mouse outside the slot, then press '+self.config.get('capture_hotkey','f9').upper()+' to capture POSITIVE state.')
            else:
                self.pos=frame; sig=signature(self.neg,self.pos)
                self.config['profile']={'box':list(self.box),'signature':sig,'display':self.display_signature()}
                save_config(self.config); self.stage=0; self.matched=False; self.refresh(force_outline=True)
                QMessageBox.information(self,'Calibration complete',f'Calibration saved using {len(sig["points"])} border pixels. Test detection before relying on it.')
        except Exception as exc: self.on_error(str(exc))
    def display_signature(self):
        return [(s.name(),s.geometry().getRect(),s.devicePixelRatio()) for s in QApplication.screens()]
    def shutdown(self):
        """Release all global resources before letting Qt terminate."""
        if self._shutting_down: return
        self._shutting_down=True
        self.monitor_requested=False
        self.monitor.stop()
        # Remove global callbacks before any more keypresses can dispatch Qt signals.
        try:
            import keyboard
            for h in self.hotkeys:
                try: keyboard.remove_hotkey(h)
                except Exception: pass
            self.hotkeys.clear()
            keyboard.unhook_all_hotkeys()
        except Exception: pass
        # Qt multimedia can own resources even after its window has disappeared.
        try: self.player.stop(); self.player.setSource(QUrl())
        except Exception: pass
        # Monitor's camera is released in _run's finally block. Wait briefly for it.
        # A stuck DXGI grab must not leave a zombie process: worker is daemonized.
        self.monitor.stop(wait=True, timeout=2.5)
        try: self.outline.hide(); self.outline.close(); self.outline.deleteLater()
        except Exception: pass

    def closeEvent(self,e):
        self.shutdown()
        e.accept()
        # The click-through top-level overlay can keep Qt alive even after the
        # main window closes. Explicitly quit the application event loop.
        QApplication.instance().quit()

if __name__=='__main__':
    app=QApplication(sys.argv); app.setWindowIcon(QIcon(str(IMAGES/'Chaos Orb.png')))
    app.setQuitOnLastWindowClosed(True)
    window=Main(); app.aboutToQuit.connect(window.shutdown); window.show(); sys.exit(app.exec())
