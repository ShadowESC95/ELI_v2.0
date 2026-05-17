"""
Robust Xi–Chi field viewer (fixed & complete)
"""

from __future__ import annotations
import sys, os, re
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import numpy as np
import pyvista as pv

# GUI imports
try:
    from pyvistaqt import BackgroundPlotter
except Exception as e:
    print("pyvistaqt not available:", e)
    sys.exit(1)

try:
    from PyQt5 import QtWidgets, QtCore
except Exception as e:
    print("PyQt5 not available:", e)
    sys.exit(1)

# Optional local controls
try:
    from ._make_controls import build_controls, dock_controls
except Exception:
    try:
        from _make_controls import build_controls, dock_controls
    except Exception:
        build_controls = None
        dock_controls = None

BASE_DIR = Path(__file__).resolve().parent

# -----------------------
# Discovery
# -----------------------
def discover_vtu_pvd_families(search_dirs: Optional[List[Path]] = None) -> Dict[str, List[Path]]:
    if search_dirs is None:
        search_dirs = [
            BASE_DIR / "modules" / "data",
            BASE_DIR / "data",
            BASE_DIR / "output",
            BASE_DIR / "outputs",
            BASE_DIR / "output_with_u",
            BASE_DIR / "diffAB",
            BASE_DIR / "sims",
        ]
    families: Dict[str, List[Path]] = defaultdict(list)
    for d in search_dirs:
        if not d.exists(): continue
        for ext in ("*.vtu", "*.pvd"):
            for p in sorted(d.glob(ext)):
                core = re.sub(r"\.(pvd|vtu)$", "", p.name, flags=re.I)
                m = re.match(r"^([A-Za-z0-9_\-]+?)(?:[_\-]?0*\d+)?$", core)
                key = m.group(1) if m else core
                families[key].append(p)
    for k, lst in families.items():
        families[k] = sorted(lst, key=lambda p: p.stat().st_mtime)
    return dict(families)

def expand_pvd_to_vtu_list(pvd_path: Path) -> List[Path]:
    try:
        text = pvd_path.read_text()
    except Exception:
        return []
    files = re.findall(r'file="([^"]+)"', text)
    return [(pvd_path.parent / f).resolve() for f in files if (pvd_path.parent / f).exists()]

def families_to_frame_list(families: Dict[str, List[Path]]) -> Dict[str, List[Path]]:
    res: Dict[str, List[Path]] = {}
    for fam, paths in families.items():
        vtu_paths = [p for p in paths if p.suffix.lower() == ".vtu"]
        pvd_paths = [p for p in paths if p.suffix.lower() == ".pvd"]
        if vtu_paths:
            res[fam] = sorted(vtu_paths, key=lambda p: p.stat().st_mtime)
        elif pvd_paths:
            latest_pvd = sorted(pvd_paths, key=lambda p: p.stat().st_mtime)[-1]
            res[fam] = expand_pvd_to_vtu_list(latest_pvd)
    return {k: v for k, v in res.items() if v}

def choose_default_family_and_frame(families_frames: Dict[str, List[Path]]) -> Tuple[Optional[str], Optional[Path]]:
    latest = None
    latest_time = -1.0
    for fam, frames in families_frames.items():
        for f in frames:
            t = f.stat().st_mtime
            if t > latest_time:
                latest_time = t
                latest = (fam, f)
    if latest is None: return None, None
    return latest[0], latest[1]

# -----------------------
# Mesh IO
# -----------------------
def _add_xi(mesh: pv.DataSet, fallback_pts: Optional[np.ndarray] = None) -> pv.DataSet:
    try:
        if "Xi" in mesh.point_data: return mesh
        if "Xi" in mesh.cell_data:
            mesh.set_active_scalars("Xi")
            return mesh
        for name, arr in mesh.point_data.items():
            if hasattr(arr, "dtype") and arr.dtype.kind in ("f","i"):
                mesh.set_active_scalars(name)
                return mesh
        P = getattr(mesh, "points", fallback_pts)
        if P is None or len(P) == 0:
            mesh.point_data["Xi"] = np.zeros(getattr(mesh, "n_points", 0))
            mesh.set_active_scalars("Xi")
            return mesh
        c = (P.max(axis=0)+P.min(axis=0))/2
        r = np.linalg.norm(P - c, axis=1)
        r = r/r.max() if r.max()>0 else r
        mesh.point_data["Xi"] = r.astype(float)
        mesh.set_active_scalars("Xi")
    except Exception as e:
        print("[warn] _add_xi failed:", e)
    return mesh

def _coerce_scalars_float(mesh: pv.DataSet) -> pv.DataSet:
    try:
        arr = mesh.active_scalars
        if arr is None: return mesh
        if arr.dtype.kind not in ("f","i"):
            mesh[mesh.active_scalars_name] = arr.astype(float)
    except Exception as e:
        print("[warn] _coerce_scalars_float failed:", e)
    return mesh

def load_vtu_flexible(path: Path) -> pv.DataSet:
    try:
        mesh = pv.read(str(path))
    except Exception:
        import meshio
        msh = meshio.read(str(path))
        pts = np.asarray(msh.points, dtype=float)
        kinds = [blk.type.lower() for blk in msh.cells]
        if "triangle" in kinds:
            tri = msh.cells[kinds.index("triangle")].data
            faces = np.hstack([np.full((tri.shape[0],1),3), tri]).ravel()
            mesh = pv.PolyData(pts, faces=faces)
        elif "line" in kinds:
            seg = msh.cells[kinds.index("line")].data
            lines = np.hstack([np.full((seg.shape[0],1),2), seg]).ravel()
            mesh = pv.PolyData(pts, lines=lines)
        else:
            mesh = pv.PolyData(pts)
        xi = next((np.asarray(arr).ravel() for arr in msh.point_data.values() if arr.ndim==1 or (arr.ndim==2 and arr.shape[1]==1)), None)
        if xi is None:
            xi = pts[:,2] if pts.shape[1]>=3 else np.linalg.norm(pts[:,:2],axis=1)
        mesh.point_data["Xi"] = xi
        mesh.set_active_scalars("Xi")
    mesh = _add_xi(mesh)
    mesh = _coerce_scalars_float(mesh)
    return mesh

# -----------------------
# Viewer + controls
# -----------------------
class FallbackControls(QtWidgets.QWidget):
    def __init__(self, viewer):
        super().__init__()
        self.viewer = viewer
        self._build_ui()
    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        self.family_combo = QtWidgets.QComboBox()
        layout.addWidget(QtWidgets.QLabel("Series family:"))
        layout.addWidget(self.family_combo)
        self.frame_list = QtWidgets.QListWidget()
        layout.addWidget(self.frame_list, stretch=1)
        btns = QtWidgets.QHBoxLayout()
        self.play_btn = QtWidgets.QPushButton("Play")
        self.pause_btn = QtWidgets.QPushButton("Pause")
        self.prev_btn = QtWidgets.QPushButton("Prev")
        self.next_btn = QtWidgets.QPushButton("Next")
        for w in [self.prev_btn,self.play_btn,self.pause_btn,self.next_btn]: btns.addWidget(w)
        layout.addLayout(btns)
        layout.addWidget(QtWidgets.QLabel("Interval (ms):"))
        self.interval_spin = QtWidgets.QSpinBox()
        self.interval_spin.setRange(10,5000)
        self.interval_spin.setValue(250)
        layout.addWidget(self.interval_spin)
        util_row = QtWidgets.QHBoxLayout()
        self.screenshot_btn = QtWidgets.QPushButton("Screenshot")
        self.pick_btn = QtWidgets.QPushButton("Pick file/folder")
        util_row.addWidget(self.pick_btn)
        util_row.addWidget(self.screenshot_btn)
        layout.addLayout(util_row)
        self.axes_cb = QtWidgets.QCheckBox("Show axes")
        self.axes_cb.setChecked(True)
        layout.addWidget(self.axes_cb)
        layout.addWidget(QtWidgets.QLabel("Log:"))
        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(150)
        layout.addWidget(self.log_box)

        # signals
        self.play_btn.clicked.connect(self.viewer.play)
        self.pause_btn.clicked.connect(self.viewer.pause)
        self.prev_btn.clicked.connect(lambda: self.viewer.set_frame(self.viewer.frame_index-1))
        self.next_btn.clicked.connect(lambda: self.viewer.set_frame(self.viewer.frame_index+1))
        self.interval_spin.valueChanged.connect(self.viewer.set_interval_ms)
        self.screenshot_btn.clicked.connect(self.viewer.save_screenshot)
        self.pick_btn.clicked.connect(self._pick_file)
        self.family_combo.currentIndexChanged.connect(self._on_family_change)
        self.frame_list.itemDoubleClicked.connect(lambda it: self.viewer.set_frame(self.frame_list.row(it)))
        self.axes_cb.stateChanged.connect(lambda s:self.viewer.toggle_axes(s==QtCore.Qt.Checked))

    def populate(self, families_frames, default_family, default_frame):
        self.family_combo.clear()
        fams = sorted(families_frames.keys())
        self.family_combo.addItems(fams)
        if default_family in fams:
            idx = fams.index(default_family)
            self.family_combo.setCurrentIndex(idx)
            self._fill_frame_list(families_frames[default_family], default_frame)

    def _fill_frame_list(self, frames, default_frame=None):
        self.frame_list.clear()
        for p in frames: self.frame_list.addItem(str(p.name))
        if default_frame:
            try: self.frame_list.setCurrentRow(frames.index(default_frame))
            except ValueError: pass

    def _on_family_change(self, idx):
        fam = self.family_combo.currentText()
        frames = self.viewer.families_frames.get(fam, [])
        self._fill_frame_list(frames)
        if frames: self.viewer.set_files_and_reset(frames)

    def _pick_file(self):
        start = str(self.viewer.default_dir or BASE_DIR)
        dlg = QtWidgets.QFileDialog(self, "Choose a VTU/PVD", start)
        dlg.setFileMode(QtWidgets.QFileDialog.ExistingFile)
        dlg.setNameFilters(["VTU/PVD files (*.vtu *.pvd)","Any files (*)"])
        if dlg.exec():
            chosen = Path(dlg.selectedFiles()[0])
            frames = [chosen]
            if chosen.suffix.lower()==".pvd": frames=expand_pvd_to_vtu_list(chosen)
            self.viewer.set_files_and_reset(frames)

# -----------------------
# Viewer
# -----------------------
class Viewer:
    def __init__(self, families_frames, default_family=None, default_frame=None, interval_ms=250):
        self.families_frames = families_frames
        self.current_family = default_family
        self.files = families_frames.get(default_family,[]) if default_family else []
        self.n_frames = len(self.files)
        self.frame_index = 0
        self.interval_ms = interval_ms
        self.plotter = BackgroundPlotter(title="Ξ–χ Field Viewer", off_screen=False, show=False)
        self.plotter.add_text("Ξ–χ Field Simulation", position="upper_left", font_size=10)
        try: self.plotter.show_axes()
        except Exception: pass
        self._timer = QtCore.QTimer()
        self._timer.timeout.connect(self._tick)
        if build_controls and dock_controls:
            try:
                w=build_controls(self)
                dock_controls(self.plotter,w)
                self.controls_widget=w
            except Exception: self._create_default_controls()
        else:
            self._create_default_controls()
        if self.files:
            if default_frame and default_frame in self.files:
                self.frame_index=self.files.index(default_frame)
            self._show_frame(self.frame_index)
        self.plotter.show()

    def _create_default_controls(self):
        self.controls_widget = FallbackControls(self)
        try: self.controls_widget.populate(self.families_frames, self.current_family, self.files[self.frame_index] if self.files else None)
        except Exception: pass
        try: self.plotter.add_dock_widget(self.controls_widget, area='right')
        except Exception: pass

    # file playback
    def set_files_and_reset(self, files):
        self.files = list(files)
        self.n_frames = len(files)
        self.frame_index = 0
        if files: self._show_frame(0)

    def _tick(self): self.set_frame(self.frame_index+1)
    def set_frame(self, idx):
        if self.n_frames==0: return
        idx = max(0,min(self.n_frames-1,idx))
        if idx==self.frame_index: return
        self.frame_index=idx
        self._show_frame(idx)
    def play(self):
        if not self._timer.isActive(): self._timer.start(self.interval_ms)
    def pause(self):
        if self._timer.isActive(): self._timer.stop()
    def set_interval_ms(self, ms):
        self.interval_ms=int(ms)
        if self._timer.isActive(): self._timer.start(self.interval_ms)

    # rendering
    def _show_frame(self, idx):
        if idx<0 or idx>=len(self.files): return
        p=self.files[idx]
        try: mesh=load_vtu_flexible(p)
        except Exception as e: print(f"[warn] load {p}: {e}"); return
        try:
            if hasattr(self,"mesh_actor") and self.mesh_actor:
                self.plotter.remove_actor(self.mesh_actor)
                self.mesh_actor=None
        except Exception: pass
        try:
            scal=mesh.active_scalars_name or "Xi"
            self.mesh_actor=self.plotter.add_mesh(mesh, scalars=scal, show_edges=False, cmap="viridis")
            self.plotter.add_scalar_bar(title=scal)
        except Exception as e: print(f"[warn] add_mesh failed: {e}")
        try:
            self.plotter.app_window.setWindowTitle(f"PyVista – {p.name} ({idx+1}/{len(self.files)})")
        except Exception: pass

    # utilities
    def save_screenshot(self):
        out=Path.cwd()/f"screenshot_{self.frame_index:04d}.png"
        try:
            self.plotter.screenshot(str(out))
            print(f"Saved screenshot: {out}")
            try: self.controls_widget.log_box.appendPlainText(f"Saved screenshot: {out}")
            except Exception: pass
        except Exception as e: print("[warn] screenshot failed:", e)

    def add_isosurface(self, value=None):
        if not hasattr(self,"mesh_actor") or self.mesh_actor is None: return
        try:
            mesh=self.mesh_actor.mapper.GetInput()
            arr=mesh.point_data.get("Xi", mesh.active_scalars)
            if arr is None: return
            val=float(value) if value is not None else float(np.nanmean(arr))
            iso=pv.wrap(mesh).contour([val])
            self.plotter.add_mesh(iso, opacity=0.6)
        except Exception as e: print("[warn] add_isosurface failed:", e)

    def add_slice_plane(self, normal=(1,0,0)):
        if not hasattr(self,"mesh_actor") or self.mesh_actor is None: return
        try:
            mesh=self.mesh_actor.mapper.GetInput()
            center=pv.wrap(mesh).center
            slicer=pv.wrap(mesh).slice(normal=normal, origin=center)
            self.plotter.add_mesh(slicer)
        except Exception as e: print("[warn] add_slice_plane failed:", e)

    def toggle_axes(self,on:bool):
        try:
            if on: self.plotter.show_axes()
            elif hasattr(self.plotter,"remove_bounds_axes"): self.plotter.remove_bounds_axes()
        except Exception: pass

# -----------------------
# Main
# -----------------------
def _pv_interactive_default() -> bool:
    try:
        return bool(getattr(pv.global_theme,"interactive",True))
    except Exception: return True

def main():
    families = discover_vtu_pvd_families()
    families_frames = families_to_frame_list(families)
    default_family, default_frame = choose_default_family_and_frame(families_frames)
    if not families_frames: print("No VTU/PVD found. You can still pick a file via GUI.")
    if _pv_interactive_default():
        Viewer(families_frames, default_family, default_frame, interval_ms=250)
    elif default_frame:
        mesh = load_vtu_flexible(default_frame)
        pv.plot(mesh, screenshot="frame0.png")
        print("Saved frame0.png")

if __name__=="__main__":
    main()
