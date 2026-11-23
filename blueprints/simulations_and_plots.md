# Simulations, dynamics, plots & graphs — 2D, 3D and 4D

ELI can **build things that compute and draw** — from a quick bar chart to a
time-evolving physics simulation. It does this the honest way: it **writes the
maths/simulation code**, and the figure or animation comes from running that code on
your machine. Nothing is faked — if ELI shows you a plot, real code produced it.

---

## How it works (so the claims are grounded, not magic)

Four real pieces combine:

1. **Script requests** — *"write a Python script that plots …"* goes to `GENERATE_SCRIPT`:
   one generation by the local model, refused when it is a template or a stub, checked that
   Python compiles (one retry if not), saved under ELI's `scripts/` folder and opened in
   **Labs ▸ 🔬 Sim / IDE**. It is not run for you.
2. **Labs ▸ Sim / IDE** — **▶ Run** executes the editor's code in a separate process (60 s
   limit, your own permissions, not sandboxed) and the **Plot Output** panel shows the image
   the code saves to the Labs plot file (`ELI_LABS_PLOT_DIR`, else the temp folder; the
   *Starter* examples do this). See `ide_guide.md`.
3. **The coding agent** (`eli/coding/agent.py`, the Coding tab or `CODE_SOLVE`) — plans →
   writes → **runs** → tests → repairs, in the sandbox (`eli/coding/sandbox.py`): a clean temp
   directory with a **non-interactive matplotlib backend** already configured, so plotting
   code runs headlessly. The sandbox folder is deleted after each run, so a figure saved
   there is not kept; what you get is the checked code, saved under `scripts/`.
4. **The scientific stack** (part of ELI's dependencies, so every install has it):
   `scipy`, `matplotlib` (+ 3D via `mpl_toolkits.mplot3d`), `plotly`,
   `pandas`, `meshio`, on top of `numpy`. This is the ceiling of what ELI can build — and
   it's a high one: the same tools professional scientists and engineers use.

A bare *"plot …"* or *"simulate …"* has no rule of its own: the model's intent resolver may
turn it into a script request, or it is answered in chat, where code in the reply is not
run. Asking for a script makes it certain.

So "the most advanced simulations ELI can make" = **anything expressible in Python's
scientific ecosystem**, written for you and run on your machine.

---

## 2D — charts, graphs, plots

Ask for a script that does it (*"write a Python script that …"*), then run it:

- *"plot this data as a line chart"* · *"bar graph of these sales figures"*
- *"histogram of these values"* · *"scatter plot of x vs y with a trend line"*
- *"draw the function y = x² − 3x + 2 from −5 to 5"*
- *"heatmap of this matrix"* · *"pie chart of these percentages"*

Backed by **matplotlib** (publication-quality static images) and **plotly**
(interactive, zoomable HTML charts).

---

## 3D — surfaces, meshes, fields

- *"show a 3D surface of z = sin(x)·cos(y)"*
- *"plot this point cloud in 3D"* · *"3D scatter of these coordinates"*
- *"render this STL/OBJ/VTK mesh and report its bounds, volume and triangle count"*
  (via **meshio**)
- *"draw a vector field"* · *"contour plot of this 2D function"*

Backed by **mplot3d** (static 3D) and **plotly** (rotate/zoom in 3D).

---

## 4D — dynamics, animation, things that change over time

"4D" here means the **3 spatial dimensions plus time** — a simulation you can watch
evolve. ELI writes the update loop, integrates the maths, and renders frames into an
animation (GIF/MP4) or an interactive time-slider figure when the script runs. GIF goes
through Pillow; MP4 needs ffmpeg installed on the machine.

- **Physics:** *"simulate a pendulum and animate it"* · *"model projectile motion
  with air resistance"* · *"animate a bouncing ball"* · *"double pendulum chaos"*
- **Systems / ODEs:** *"solve and plot the Lorenz attractor"* · *"simulate predator-
  prey (Lotka–Volterra) over time"* · *"integrate this differential equation"* —
  powered by **scipy** solvers (`solve_ivp`, `odeint`).
- **Growth / agents:** *"model a population growing logistically for 100 steps"* ·
  *"cellular automaton — Game of Life, animated"* · *"random walk in 2D over time"*.
- **Waves / fields:** *"animate a wave propagating"* · *"heat diffusion across a plate
  over time"* (a simple PDE on a grid).

Backed by **numpy** (the arrays/maths), **scipy** (the solvers — the "dynamics"),
and **matplotlib.animation** / **plotly** (the moving picture).

---

## What you get back

- The **code** it wrote, saved under ELI's `scripts/` folder and opened in ELI's built-in
  editor (Labs ▸ Sim / IDE — see `blueprints/ide_guide.md`), to keep, tweak, or learn from.
- A **saved figure** when the code runs (PNG for static, GIF/MP4 for animation, HTML for
  interactive), written wherever the code saves it. The Plot Output panel shows an image
  saved to the Labs plot file.
- An explanation on request: **ELI: Explain** in Sim / IDE walks through what the code does.

---

## Honest limits

- ELI is bounded by the **Python scientific stack** — extremely capable, but not a
  dedicated CFD/FEA suite or a game engine. For a heavy specialist simulation you'd
  still use purpose-built software; ELI covers the enormous middle ground of
  scientific/engineering plotting, dynamics and modelling.
- Very large simulations run as fast as **your** machine allows — they're computed
  locally, offline. A run from Sim / IDE stops after 60 seconds; run a longer one yourself.
- Code run from Sim / IDE has your own permissions and no sandbox: read what ELI wrote
  before you run it.
- The scientific stack comes with every install, a source checkout's `pip install -e .`
  included.

---

## One-line examples to try

```
write a Python script that plots y = sin(x)/x from -20 to 20
write a Python script that makes a 3D surface plot of a gaussian bump
write a Python script that simulates and animates a simple pendulum
write a Python script that solves the Lorenz system and shows the butterfly attractor
write a Python script that animates Conway's Game of Life on a 50x50 grid
write a Python script that loads model.stl, renders it and prints its dimensions
```
