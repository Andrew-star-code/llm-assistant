// Применяет сохранённую тему до загрузки React (ключ и формат — src/features/theme/store.ts).
(function () {
  var mode = "system";
  try {
    var raw = window.localStorage.getItem("ai-assistant.theme");
    var parsed = raw ? JSON.parse(raw) : null;
    if (parsed && parsed.state && parsed.state.mode) mode = parsed.state.mode;
  } catch (e) {
    /* localStorage недоступен — тема по системе */
  }
  var dark =
    mode === "dark" ||
    (mode === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
})();
