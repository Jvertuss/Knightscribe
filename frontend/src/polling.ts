// Runs `tick` now and then every `ms` milliseconds. The next call waits for the
// previous one to finish, nothing runs while the tab is hidden, and it catches up
// as soon as the tab is visible again. Returns a function that stops it.
export function startPolling(tick: () => Promise<void>, ms: number): () => void {
  let stopped = false;
  let running = false;
  let timer: number | undefined;

  async function run() {
    window.clearTimeout(timer);
    if (stopped || running) return;
    if (!document.hidden) {
      running = true;
      try {
        await tick();
      } catch (err) {
        console.warn("background refresh failed:", err);
      } finally {
        running = false;
      }
    }
    if (!stopped) timer = window.setTimeout(run, ms);
  }

  function onVisibility() {
    if (!document.hidden) run();
  }

  document.addEventListener("visibilitychange", onVisibility);
  run();
  return () => {
    stopped = true;
    window.clearTimeout(timer);
    document.removeEventListener("visibilitychange", onVisibility);
  };
}
