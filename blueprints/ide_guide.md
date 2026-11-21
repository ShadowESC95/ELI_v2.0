# ELI's built-in code editor (IDE) — a plain-English guide

ELI has a **code editor built in** — you don't need to install VS Code or anything
else. This guide explains what it does and how to use it, whether or not you write
code yourself. Everything runs on your own machine.

---

## What it is

A clean, lightweight editor for looking at and changing code and text files, with:

- **Line numbers** down the side,
- the **current line highlighted** so you don't lose your place,
- **colour-coded Python** (keywords, strings, comments in different colours) so code
  is easy to read,
- **auto-indent** — it lines things up for you as you type,
- a **▶ Run** button, a console for what the code prints, and a **Plot Output** panel.

It's built right into ELI (no extra install, no separate license), so it opens
instantly and works offline.

---

## Opening it

- **Open the Labs tab and pick 🔬 Sim / IDE.** The editor is that panel, inside ELI — no
  juggling separate windows.
- A Python script ELI writes for you opens there by itself.
- Saying *"open the IDE"* or *"open the code editor"* does something else: it opens the code
  editor **installed on your computer** (VS Code, VSCodium, Cursor, Sublime Text, Kate and
  the like), and tells you when there isn't one.

---

## The part that matters if you don't code: **let ELI do it**

You don't have to write anything yourself. Just describe what you want:

- **Write something new:** *"write me a script that renames all the photos in a
  folder by date"* → ELI writes the script, refuses to hand you a template or a stub,
  checks that Python code compiles, saves it, and opens it in Sim / IDE. It does not run it
  for you: press **▶ Run** to try it.
- **Have it written, run and tested:** use the **Coding** tab (type the task, pick the
  language and *Quick* or *Thorough*, press **Solve (verified)**), or ask in chat to
  *"implement binary search and test it"*. This is ELI's **coding assistant**: it plans the
  code, writes it, **runs it and tests it** in a separate, time-limited process, repairs what fails, and
  remembers past bug→fix pairs so it gets better over time. Big jobs run in the background;
  the Tasks tab shows them.
- **Fix a file:** *"fix errors in report.py"* (or *"improve report.py"*) → ELI rewrites the
  file in the background. It **does not ask first**: it saves a backup copy beside the file
  (`report.py.bak.` plus the date and time), then writes the fix. For ELI's own code files it
  also checks the module still loads and its tests still pass, and puts the original back if
  not.
- **Check code for problems:** *"examine my_script.py for errors"* → ELI does a
  layered check (syntax → style → a deeper look by the model) and reports what's wrong,
  then offers to fix it and **waits for your "yes"**. The deeper-look findings are only
  fixed if you say so (*"fix the logic ones too"*). These confirmed fixes are made to ELI's
  own source files only; for a file of yours, use *"fix errors in <file>"*.
- **Understand code:** *"summarise ~/scripts/report.py"* → ELI reads it and explains in
  plain English. In Sim / IDE, **ELI: Explain** does the same for the code in the editor.

---

## The part if you *do* code

- Open a file in Sim / IDE (**Open**), edit it, **Save** it. **New** and **Save As** are
  there too, and a *Starter* menu has a few ready examples.
- **▶ Run** runs the Python in the editor in a separate process, for up to 60 seconds, with
  your own permissions — it is not sandboxed, so only run code you trust.
- **ELI: Fix errors** sends the code and the last error to ELI and shows a corrected version
  beside the editor; **ELI: Explain** walks through what the code does. Neither changes the
  editor — copy in what you want to keep.
- To have ELI change a file on disk, name it: *"fix errors in ~/scripts/report.py"*,
  *"improve ~/scripts/report.py"*.

---

## Making things that run — plots, graphs, and simulations

The editor pairs with ELI's scientific tools (numpy, scipy, matplotlib, plotly), so you can
ask for code that **produces a result**:

- **2D:** *"write a Python script that plots this data as a line chart"*.
- **3D:** *"write a Python script that shows a 3D surface of z = sin(x)·cos(y)"*.
- **4D (things that change over time):** *"write a Python script that simulates a pendulum
  and animates it"*.

ELI writes the code and opens it in Sim / IDE; **▶ Run** it to get the plot, graph, or
animation. The **Plot Output** panel shows the picture the code saves to the Labs plot file
(the *Starter* examples show how); anything else the code saves lands wherever the code says.
(See `blueprints/simulations_and_plots.md` for the full range.)

---

## Quick reference

| You want to… | Do this |
|---|---|
| Open the built-in editor | Labs ▸ 🔬 Sim / IDE |
| Open the code editor installed on your computer | "open the IDE" |
| Have ELI write something | "write me a script that …" |
| Have ELI write, run and test it | the Coding tab, or "implement … and test it" |
| Fix a file | "fix errors in <file>" |
| Check for problems | "examine <file> for errors" |
| Understand code | "summarise <file>", or ELI: Explain in Sim / IDE |
| Make a plot / simulation | "write a Python script that plots / simulates / animates …", then ▶ Run |

You never have to leave ELI, install anything, or know what any of the code means —
just describe what you want.
