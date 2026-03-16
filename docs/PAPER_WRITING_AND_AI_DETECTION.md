# Paper Writing and AI-Detection

## Where “paper-writing” lives

- **Table I (experiment results):** Filled by scripts, not by prose-writing agents.
  - `scripts/run_all_experiments_and_update_paper.py` runs E1/E2/E3 and prints (or with `--update-tex` patches) the LaTeX table into `VTS_special_session_march_4/main.tex`.
  - `scripts/run_e1_e2_e3.py` runs the three modes and prints the LaTeX table (no `---` in the script output).
- **Design / Verifier agents:** They generate RTL and testbenches only. They do not draft paper text.
- **Narrative / Framework elaboration:** A system prompt for a future *writing* agent is in `configs/prompt_templates/writing_agent_system.txt`. It is intended for an agent that takes the current Framework section and reference context (refs.bib, professor papers) and produces improved LaTeX prose. That agent is not yet wired into any script; you can use the prompt manually (e.g., paste section + refs into an LLM) or add a small script that calls an API with this system prompt.

## Professor papers and refs

- **Design Agent** now receives a **papers context** built from:
  - Curated list in `src/paper_crawler.py` (CURATED).
  - Optional `configs/professor_papers.json`: add entries like `{"title": "...", "year": 2022, "key": "Elbtity2022APTPU"}` so the Design Agent sees these titles/years as style and topology guidance.
- This makes it easier for the agent to align with the literature when generating RTL and (if you add a writing agent) when elaborating the Framework. Populate `professor_papers.json` with the keys/titles from the professors’ shared papers (and refs.bib) you want in context.

## Framework figure (Fig. 1)

- **In the paper:** `VTS_special_session_march_4/main.tex` includes a TikZ pipeline figure (Fig. 1) that scales to column width.
- **Mermaid placeholder:** `VTS_special_session_march_4/figures/framework.mmd` holds the same pipeline in Mermaid. You can render it with [mermaid-cli](https://github.com/mermaid-js/mermaid-cli) (`mmdc -i framework.mmd -o framework.pdf`) or [mermaid.live](https://mermaid.live) and replace the TikZ with `\includegraphics{framework}` if you prefer.

## AI-writing detection (undetectable.ai, etc.)

**The pipeline does not currently** call undetectable.ai or any other AI-detection / humanization service. There is no automatic step that checks the paper text or script output against such tools or “makes it pass” an AI-writing flag.

If you want to use such a check:

- **Manual:** Run the draft (or selected sections) through the tool of your choice (e.g., undetectable.ai) and edit until it meets your target.
- **Optional automation:** You could add a small script that (1) reads `main.tex` (or a section), (2) calls the service’s API (if they offer one), (3) replaces or flags text. That would require an API key and compliance with the service’s terms; we have not implemented it.

Summary: **No**, the repo is not currently “going to websites such as undetectable ai and checking the output and making it pass the ai writing flag.” You can do that manually or add your own integration.
