// Runs inside Obsidian through `obsidian eval`. canvas_fit.py fills in __ARGS__.
// The whole run lives here so its cleanup still happens if the calling process dies.
(async function measureNodes() {
  const { path, ids } = __ARGS__;
  const ZOOM_100_PERCENT = 0; // canvas zoom is log2(scale); zooming out far enough unmounts nodes
  const NODE_TIMEOUT_MS = 3000;
  const POLL_MS = 100;
  const STABLE_READS = 3;
  const OPEN_TIMEOUT_MS = 15000;
  const SHOW_TIMEOUT_MS = 5000;
  const LOCK_MAX_AGE_MS = 10 * 60 * 1000;

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  if (window.__obCanvasFitStarted && Date.now() - window.__obCanvasFitStarted < LOCK_MAX_AGE_MS) {
    return { fatal: "another ob-canvas-fit run is using this Obsidian window; retry when it ends" };
  }
  const file = app.vault.getAbstractFileByPath(path);
  if (!file) return { fatal: `Obsidian has no file at ${path}` };

  window.__obCanvasFitStarted = Date.now();

  // A hidden window does not render, so a minimised one is shown without taking focus for the
  // run and put back afterwards. Nothing else may raise it: the user may have minimised it on purpose.
  const obWindow = require("electron").remote.getCurrentWindow();
  const wasMinimized = obWindow.isMinimized();
  const wasVisible = obWindow.isVisible();
  const hadFocus = document.hasFocus();
  const putWindowBack = () => {
    if (wasMinimized) obWindow.minimize();
    else if (!wasVisible) obWindow.hide();
  };
  // Linux window managers report these flags inconsistently (minimised with document.hidden false,
  // or visible while minimised), so only a painted frame proves the window renders.
  const windowIsBack = () => (wasMinimized ? obWindow.isMinimized() : obWindow.isVisible() === wasVisible);
  const paintsFrames = () => Promise.race([
    new Promise((resolve) => requestAnimationFrame(() => resolve(true))),
    sleep(1000).then(() => false),
  ]);
  const shownForRun = wasMinimized || !wasVisible || document.hidden;
  if (shownForRun) {
    obWindow.showInactive();
    const showDeadline = performance.now() + SHOW_TIMEOUT_MS;
    let painting = false;
    while (!painting && performance.now() < showDeadline) {
      await sleep(POLL_MS); // must yield: document.hidden only updates between tasks
      painting = !document.hidden && await paintsFrames();
    }
    if (!painting) {
      putWindowBack();
      delete window.__obCanvasFitStarted;
      return { fatal: "the Obsidian window stays hidden after showing it without focus, so nothing can be measured" };
    }
  }

  const ws = app.workspace;
  const previousLeaf = ws.activeLeaf;
  const countLeaves = () => {
    let count = 0;
    ws.iterateRootLeaves(() => { count += 1; });
    return count;
  };
  const leavesBefore = countLeaves();
  const popoutsBefore = ws.floatingSplit?.children?.length ?? 0;

  // Read one node: the 1px height forces overflow, and is undone before the browser can paint.
  const readContentHeight = (preview) => {
    const original = preview.style.height;
    preview.style.height = "1px";
    const height = preview.scrollHeight;
    preview.style.height = original;
    return height;
  };

  const hasRenderedContent = (preview) =>
    preview.textContent.trim() !== "" || preview.querySelector("img, svg, video, iframe, canvas") !== null;

  const isSettled = (node, preview) => {
    const sections = node.child?.previewMode?.renderer?.sections ?? [];
    const images = [...preview.querySelectorAll("img")];
    return sections.every((section) => section.rendered) && images.every((image) => image.complete);
  };

  const measureNode = async (canvas, node) => {
    if (node.text.trim() === "") return { error: "empty text, nothing to measure" };
    // Fixed zoom instead of zoomToBbox: fitting a tall node into a small window zooms out until it unmounts.
    canvas.setViewport(node.x + node.width / 2, node.y, ZOOM_100_PERCENT);
    const deadline = performance.now() + NODE_TIMEOUT_MS;
    let last = null;
    let same = 0;
    let lastState = "not mounted";
    while (performance.now() < deadline) {
      await sleep(POLL_MS);
      const preview = node.isContentMounted ? node.contentEl?.querySelector(".markdown-preview-view") : null;
      if (!preview) continue;
      if (!isSettled(node, preview)) { lastState = "still rendering"; continue; }
      const height = readContentHeight(preview);
      // An attached preview that has not rendered yet reads as its forced 1px height.
      if (height <= 1 || !hasRenderedContent(preview)) { lastState = "nothing rendered"; same = 0; continue; }
      same = height === last ? same + 1 : 1;
      last = height;
      lastState = `height ${height} not stable`;
      if (same >= STABLE_READS) return { content: height };
    }
    const hidden = document.hidden ? ", Obsidian window is hidden or minimised" : "";
    return { error: `timed out: ${lastState}${hidden}` };
  };

  const nodes = {};
  let leaf = null;
  let canvas = null;
  let startViewport = null;
  let fatal = null;
  try {
    // Always the main window: a popout window hung for 120s when this was tried.
    const anchor = ws.getMostRecentLeaf(ws.rootSplit);
    leaf = anchor ? ws.createLeafInTabGroup(anchor.parent) : ws.getLeaf("tab");
    await Promise.race([
      leaf.openFile(file, { active: false }),
      sleep(OPEN_TIMEOUT_MS).then(() => { throw new Error("opening the canvas timed out"); }),
    ]);
    ws.setActiveLeaf(leaf, { focus: false });
    const view = leaf.view;
    if (view.getViewType() !== "canvas" || !view.canvas) throw new Error("the tab did not open as a canvas");
    // Obsidian or a plugin may re-save the canvas when this tab closes, adding fields such as
    // metadata. This tab only reads, so it must never write the user's file.
    view.save = async () => {};
    view.requestSave = () => {};
    canvas = view.canvas;
    startViewport = [canvas.x, canvas.y, canvas.zoom];

    const loadDeadline = performance.now() + OPEN_TIMEOUT_MS;
    while (ids.length && canvas.nodes.size === 0 && performance.now() < loadDeadline) await sleep(POLL_MS);

    for (const id of ids) {
      if (ws.activeLeaf !== leaf) {
        fatal = "stopped: another tab became active while measuring";
        break;
      }
      const node = canvas.nodes.get(id);
      if (!node) {
        nodes[id] = { error: "Obsidian did not load this node" };
        continue;
      }
      try {
        nodes[id] = await measureNode(canvas, node);
      } catch (error) {
        nodes[id] = { error: String(error) };
      }
    }
  } catch (error) {
    fatal = String(error);
  }

  // Cleanup: leave the tabs, the active tab and this canvas's remembered viewport as they were.
  const stillOnOurTab = ws.activeLeaf === leaf;
  if (canvas && startViewport) canvas.setViewport(...startViewport);
  if (leaf) leaf.detach();
  if (stillOnOurTab && previousLeaf) ws.setActiveLeaf(previousLeaf, { focus: hadFocus });
  await sleep(POLL_MS);
  putWindowBack();
  await sleep(POLL_MS);
  delete window.__obCanvasFitStarted;
  const restored = countLeaves() === leavesBefore
    && (ws.floatingSplit?.children?.length ?? 0) === popoutsBefore
    && (!stillOnOurTab || ws.activeLeaf === previousLeaf)
    && windowIsBack();
  return { nodes, restored, stopped: fatal, shownForRun };
})()
