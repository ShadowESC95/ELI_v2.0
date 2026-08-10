# Using Ollama with ELI — a start-to-finish guide (no tech knowledge needed)

This guide is for anyone who wants ELI to use an **Ollama** model. You don't need
to understand any of the words below — just follow the steps for your computer.

**The good news:** as of **v2.1.29**, if Ollama is installed on your machine, **ELI
starts it for you automatically**. Most people don't have to do anything except
install Ollama once and pick a model. The steps below cover installing it and what
to do if anything doesn't work.

---

## What is Ollama (in one sentence)?

Ollama is a free program that runs AI "brains" (models) on your own computer. ELI
can borrow those brains instead of using its own. Everything stays on your machine.

**You do NOT need Ollama to use ELI** — ELI comes with its own brain. Ollama is
only if you *want* to use models you've set up in Ollama.

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
2. Choose **Ollama**.
3. In **Ollama model**, click **Refresh Ollama models** and pick the one you pulled
   in Step 2 (for example `llama3.2`).
4. Click **OK**.

That's it — ELI now thinks using your Ollama model.

You can also just **ask ELI** later: say or type *"switch to Ollama"* or *"use the
llama3.2 model"*.

---

## Step 4 — Change it whenever you like

- **In the app:** **Settings → Model → Backend = Ollama**, then **Refresh Ollama
  Models** and pick one.
- **By talking to ELI:** *"use the mistral model"*, *"what Ollama models do I have"*.
- **Back to ELI's own brain:** set **Backend** to **Bundled** or **Custom GGUF**.

---

## If something doesn't work

ELI tries to start Ollama for you, so most problems fix themselves. If you still see
**"Ollama unreachable"**:

**1. Is Ollama installed?**
Open a Terminal / Command Prompt and type `ollama list`. If it says *command not
found*, go back to **Step 1**.

**2. Is a model downloaded?**
If `ollama list` is empty, do **Step 2** (`ollama pull llama3.2`).

**3. Start it by hand (rarely needed):**
- **Windows / macOS:** just open the **Ollama** app (Start menu / Applications).
- **Linux:** type `systemctl --user start ollama` — or `ollama serve` and leave
  that window open.

**4. Ollama on a *different* computer (advanced):**
You can point ELI at Ollama running on another machine on your home network. In
**Ollama host**, type that machine's address (e.g. `192.168.1.20` — you don't need
`http://` or a port, ELI fills those in). On that other machine, start Ollama with
`OLLAMA_HOST=0.0.0.0:11434 ollama serve` and allow port `11434` through its
firewall. ELI treats a machine you set here as trusted, so the Net toggle can stay
**off**.

**5. Turn off auto-start (if you prefer):**
ELI starting Ollama for you can be disabled by setting the environment variable
`ELI_OLLAMA_AUTOSTART=0`.

---

## The one-minute version

1. Install Ollama from **https://ollama.com/download** (once).
2. `ollama pull llama3.2` (once).
3. In ELI's first screen: **Provider → Ollama → Refresh → pick your model → OK**.
4. ELI starts Ollama for you from then on. Done.
