---
name: ob-canvas-fit
description: Use when resizing or tidying text nodes on an Obsidian (OB) Canvas, when text in a Canvas node is cut off or leaves too much blank space, or before writing node heights into a .canvas file. Measures each node's content height from real OB rendering instead of estimating from characters or lines.
---

# OB Canvas fit

Never estimate a node's height from characters or lines. Measure it in OB with the bundled command, which needs a running Obsidian and the `obsidian` command.

## Workflow

Progress:
- [ ] Step 1: Measure without writing.
  ```bash
  uv run scripts/canvas_fit.py "<canvas path>" [--vault "<vault name>"]
  ```
  The path is relative to the vault, or absolute. `scripts/` is in this skill's folder.
- [ ] Step 2: Read the output. Rerun or investigate every node under `FAILED` (see Gotchas). A failed node keeps its height.
- [ ] Step 3: Write the heights. Rerun with `--apply`; it measures again and writes only node heights.
- [ ] Step 4: Fix the layout yourself. The command does not move nodes or resize groups. Use `Layout with suggested heights` to find nodes that will overlap or stick out of a group, then adjust positions and group bounds in the file, keeping node widths as they are.
- [ ] Step 5: Look at the canvas in OB. Confirm no text is cut off and no group label or node is covered; the command cannot detect covered labels.

## Output

```text
Canvas: flow.canvas  (3 text nodes, 1 other nodes not measured)
node                current content suggest  text
7b4787b5bca6a3b1        331     372     390  ### prepare env ```python from openai…
f034260cab566a57        120      48      70  Run the job
FAILED, 1 node(s) not measured and never written:
  a1b2c3d4e5f60718: empty text, nothing to measure  []

Layout now:
  overlaps: none
  outside group: none
Layout with suggested heights:
  overlaps:
    7b4787b5bca6a3b1 overlaps f034260cab566a57
  outside group: none
Check by eye: group labels and node labels are not covered. This tool cannot see them.

Dry run: nothing written. 2 height(s) would change; add --apply to write them.
```

`suggest` is `content` + 15px, rounded up to a multiple of 10.

Exit codes: `0` everything measured; `1` some node failed, the file changed during measuring, or OB was not restored; `2` the command could not run.

## Gotchas

- OB unmounts nodes when zoomed out, and the always-render setting cannot go below 88%. A node measured while zoomed out reads 0. Do not call `zoomToBbox` or shrink the window to fit nodes; the command centers on each node at 100% zoom, which works in a very small window.
- Do not open a popout window to measure. It hung for 120s in practice; the command only opens a tab in the main window.
- Do not click in OB during a run. The measured tab must stay active. If another tab becomes active, the run stops, lists the rest as failed and leaves your tab alone. Rerun it.
- A hidden window does not render. The command handles a minimised OB window itself: it shows the window without taking focus, measures, and minimises it again. If the window stays hidden it stops with exit 2. Do not raise the window with a focus-stealing call; the user may have minimised it on purpose.
- `changed during measuring` means someone or something saved the file during the run, so nothing was written. Rerun. Opening a canvas in your own tab can make OB or a plugin save it once with added fields such as `metadata`; the command's own tab never saves.
- An empty text node always shows under `FAILED`, and so does a node whose text renders to nothing, such as only a comment. Leave these alone or size them by hand.
