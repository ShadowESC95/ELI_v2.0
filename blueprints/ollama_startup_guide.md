# Using Ollama with ELI — a start-to-finish guide (no tech knowledge needed)

> **Updated for v2.5.36.** The Ollama model picker in Settings / startup works on
> AppImage and portable builds (Qt compat shim exports `QDialogButtonBox`). ELI uses
> Ollama only when you choose it as the backend.

This guide is for anyone who wants ELI to use an **Ollama** model. You don't need
to understand any of the words below — just follow the steps for your computer.

**The good news:** as of **v2.1.29**, once you have chosen Ollama as ELI's backend,
**ELI starts it for you** if it is installed on your machine but not running. Most
people don't have to do anything except install Ollama once and pick a model. The
steps below cover installing it and what to do if anything doesn't work.

---

## What is Ollama (in one sentence)?

Ollama is a free program that runs AI "brains" (models) on your own computer. ELI
can borrow those brains instead of running a model file itself. Everything stays on
your machine.

**You do NOT need Ollama to use ELI** — ELI runs GGUF model files itself (the setup
window it shows when it finds no model offers one to download). Ollama is only if you
*want* to use models you've set up in Ollama.

---

## Step 1 — Install Ollama (once)

Pick your computer:

### Windows
1. Go to **https://ollama.com/download** in your web browser.
2. Click **Download for Windows**, then run the file you downloaded.
3. Click through the installer (Next → Next → Finish). That's it — Ollama now
   starts automatically every time your computer turns on. You'll see a small
   llama icon near your clock.

### macOS (Apple computers)
1. Go to **https://ollama.com/download**.
2. Click **Download for macOS**, open the downloaded file, and drag **Ollama**
   into your Applications folder.
3. Open **Ollama** once from Applications. It runs quietly in the menu bar (top of
   your screen) from now on.

### Linux
1. Open a **Terminal**.
2. Copy-paste this one line and press Enter:
   ```
   curl -fsSL https://ollama.com/install.sh | sh
   ```
3. That installs Ollama and sets it to run in the background.

---

## Step 2 — Get a model (once)

A model is the actual "brain". You download one with a single command. Open a
**Terminal** (macOS/Linux) or **Command Prompt / PowerShell** (Windows) and type:

```
ollama pull llama3.2
```

Wait for it to finish (it downloads a few gigabytes the first time). You can pull
others later — `ollama pull qwen2.5`, `ollama pull mistral`, and so on. Browse them
at **https://ollama.com/library**.

> Tip: a smaller model like `llama3.2` or `qwen2.5:3b` is a good first choice — it
> loads faster and runs on modest computers.

---

## Step 3 — Tell ELI to use Ollama

1. Start ELI. On the **first screen** ("Choose which model to load"), find the
   **Provider** dropdown near the top.
2. Choose **Ollama**. If Ollama is installed but not running, ELI starts it now.
3. In **Ollama model**, click **Refresh Ollama models** and pick the one you pulled
   in Step 2 (for example `llama3.2`).
4. Click **OK**.

That's it — ELI now thinks using your Ollama model.

Switching is done in ELI's menus (below): there is no spoken or typed command that
changes the model or the backend.

---

## Step 4 — Change it whenever you like

- **In the app:** **Settings → Model → Backend = Ollama**, then **Refresh Ollama
  Models** and pick one.
- **From the toolbar:** the Ollama menu lists the models Ollama has; picking one
  switches ELI to it.
- **Back to a GGUF model:** set **Backend** to **Bundled GGUF** or **Custom GGUF**.

---

## If something doesn't work

ELI starts Ollama only when you choose it: pick **Ollama** as the backend in the start-up
dialog or in **Settings → Model**, or pick an Ollama model in the toolbar menu. Then, if the
`ollama` program is installed but stopped on this computer, ELI starts it for you (`ollama
serve`, tried once each time ELI runs): straight away from the start-up dialog or the toolbar,
and with the first reply after **Settings → Model**. With a GGUF model chosen ELI never starts or uses Ollama, listing Ollama's
models never starts it, and an Ollama on another computer is never started by ELI. If you chose
Ollama and still see **"Ollama unreachable"**:

**1. Is Ollama installed?**
Open a Terminal / Command Prompt and type `ollama list`. If it says *command not
found*, go back to **Step 1**.

**2. Is a model downloaded?**
If `ollama list` is empty, do **Step 2** (`ollama pull llama3.2`).

**3. Start it by hand (rarely needed):**
- **Windows / macOS:** just open the **Ollama** app (Start menu / Applications).
- **Linux:** type `sudo systemctl start ollama` (the service Ollama's installer sets
  up) — or `ollama serve` and leave that window open.

**4. Ollama on a *different* computer (advanced):**
You can point ELI at Ollama running on another machine on your home network. In
**Ollama host**, type that machine's address (e.g. `192.168.1.20` — you don't need
`http://` or a port, ELI fills those in). On that other machine, start Ollama with
`OLLAMA_HOST=0.0.0.0:11434 ollama serve` and allow port `11434` through its
firewall (ELI does not start Ollama on another machine for you). ELI treats a
machine you set here as trusted, so the Net toggle can stay **off**.

**5. Turn off auto-start (if you prefer):**
Even with Ollama chosen, ELI starting it for you can be disabled by setting the environment
variable `ELI_OLLAMA_AUTOSTART=0`; you then start Ollama yourself.

---

## The one-minute version

1. Install Ollama from **https://ollama.com/download** (once).
2. `ollama pull llama3.2` (once).
3. In ELI's first screen: **Provider → Ollama → Refresh → pick your model → OK**.
4. From then on ELI starts Ollama for you when it isn't running. Done.
