/* SkillForge client behaviours.
 *
 * Small, dependency-free progressive enhancements. Everything works without
 * JavaScript; these add theme switching, navigation drawers, menus, toasts,
 * autosave, unsaved-work protection, HTMX CSRF headers and charts. No eval,
 * so the page runs under a strict script-src Content-Security-Policy.
 */
(function () {
  "use strict";

  const doc = document.documentElement;
  const csrfToken = () => document.querySelector('meta[name="csrf-token"]')?.content || "";
  const reduceMotion = () =>
    doc.dataset.motion === "reduce" || window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------------------------------------------------------------- HTMX
  document.addEventListener("htmx:configRequest", (event) => {
    event.detail.headers["X-CSRFToken"] = csrfToken();
  });
  document.addEventListener("htmx:responseError", (event) => {
    const xhr = event.detail.xhr;
    const message = xhr.getResponseHeader("X-SF-Message") || "Something went wrong. Please try again.";
    toast(message, "error");
  });
  document.addEventListener("htmx:sendError", () => toast("You appear to be offline. Check your connection.", "error"));
  document.body.addEventListener("sf:toast", (event) => toast(event.detail.message, event.detail.level));
  document.addEventListener("htmx:afterSwap", (event) => {
    initCharts(event.detail.target);
    initEditors(event.detail.target);
    initTimezones(event.detail.target);
    const focusTarget = event.detail.target.querySelector("[data-autofocus]");
    if (focusTarget) focusTarget.focus({ preventScroll: false });
  });

  // ---------------------------------------------------------------- Toasts
  function toast(message, level) {
    const region = document.getElementById("toast-region");
    if (!region || !message) return;
    const node = document.createElement("div");
    node.className = "toast";
    node.setAttribute("role", level === "error" ? "alert" : "status");
    const tone = { error: "text-danger", success: "text-success", warning: "text-warning" }[level] || "text-info";
    const dot = document.createElement("span");
    dot.className = `mt-1.5 size-2 flex-none rounded-full bg-current ${tone}`;
    const text = document.createElement("p");
    text.className = "flex-1 text-sm";
    text.textContent = message;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "btn btn-ghost btn-sm btn-icon -mr-2 -mt-1";
    close.setAttribute("aria-label", "Dismiss notification");
    close.textContent = "×";
    close.addEventListener("click", () => dismiss(node));
    node.append(dot, text, close);
    region.append(node);
    setTimeout(() => dismiss(node), level === "error" ? 9000 : 5500);
  }
  function dismiss(node) {
    if (!node.isConnected || node.classList.contains("is-leaving")) return;
    node.classList.add("is-leaving");
    setTimeout(() => node.remove(), reduceMotion() ? 0 : 220);
  }
  window.sfToast = toast;
  document.querySelectorAll("[data-django-message]").forEach((el) => {
    toast(el.dataset.djangoMessage, el.dataset.level);
    el.remove();
  });

  // ---------------------------------------------------------------- Theme
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-theme-set]");
    if (!button) return;
    const theme = button.dataset.themeSet;
    doc.dataset.theme = theme;
    document.cookie = `sf_theme=${theme}; path=/; max-age=31536000; samesite=lax`;
    document.querySelectorAll("[data-theme-set]").forEach((el) =>
      el.setAttribute("aria-pressed", String(el.dataset.themeSet === theme)),
    );
    const url = button.dataset.themeUrl;
    if (url) {
      const body = new FormData();
      body.append("theme", theme);
      fetch(url, { method: "POST", body, headers: { "X-CSRFToken": csrfToken() }, credentials: "same-origin" });
    }
    refreshCharts();
  });

  // ------------------------------------------------------- Sidebar & drawer
  try {
    if (localStorage.getItem("sf-sidebar") === "collapsed") doc.classList.add("sidebar-collapsed");
  } catch (_) {
    /* storage may be unavailable */
  }
  document.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-sidebar-toggle]");
    if (!toggle) return;
    const collapsed = doc.classList.toggle("sidebar-collapsed");
    toggle.setAttribute("aria-expanded", String(!collapsed));
    try {
      localStorage.setItem("sf-sidebar", collapsed ? "collapsed" : "expanded");
    } catch (_) {
      /* ignore */
    }
  });

  let lastFocus = null;
  function setDrawer(id, open) {
    const drawer = document.getElementById(id);
    const backdrop = document.querySelector(`[data-drawer-backdrop="${id}"]`);
    if (!drawer) return;
    drawer.dataset.open = String(open);
    if (backdrop) backdrop.dataset.open = String(open);
    drawer.toggleAttribute("inert", !open);
    document.querySelectorAll(`[data-drawer-open="${id}"]`).forEach((b) => b.setAttribute("aria-expanded", String(open)));
    document.body.style.overflow = open ? "hidden" : "";
    if (open) {
      lastFocus = document.activeElement;
      drawer.querySelector("a, button")?.focus();
    } else if (lastFocus) {
      lastFocus.focus();
    }
  }
  document.addEventListener("click", (event) => {
    const opener = event.target.closest("[data-drawer-open]");
    if (opener) return setDrawer(opener.dataset.drawerOpen, true);
    const closer = event.target.closest("[data-drawer-close]");
    if (closer) return setDrawer(closer.dataset.drawerClose, false);
  });

  // ---------------------------------------------------------------- Menus
  function closeMenus(except) {
    document.querySelectorAll("[data-menu-button][aria-expanded='true']").forEach((button) => {
      if (button === except) return;
      button.setAttribute("aria-expanded", "false");
      document.getElementById(button.getAttribute("aria-controls"))?.setAttribute("hidden", "");
    });
  }
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-menu-button]");
    if (button) {
      const menu = document.getElementById(button.getAttribute("aria-controls"));
      const open = button.getAttribute("aria-expanded") !== "true";
      closeMenus(button);
      button.setAttribute("aria-expanded", String(open));
      menu?.toggleAttribute("hidden", !open);
      if (open) menu?.querySelector("a, button")?.focus();
      return;
    }
    if (!event.target.closest("[data-menu]")) closeMenus();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const openButton = document.querySelector("[data-menu-button][aria-expanded='true']");
    closeMenus();
    openButton?.focus();
    document.querySelectorAll(".drawer[data-open='true']").forEach((d) => setDrawer(d.id, false));
  });

  // ------------------------------------------------- Confirmations & loading
  document.addEventListener(
    "submit",
    (event) => {
      const form = event.target;
      const message = form.dataset.confirm;
      if (message && !window.confirm(message)) {
        event.preventDefault();
        return;
      }
      form.dataset.submitting = "true";
      const submitter = event.submitter;
      if (submitter && submitter.matches(".btn") && !form.hasAttribute("hx-post")) {
        submitter.classList.add("is-loading");
        setTimeout(() => (submitter.disabled = true), 0);
      }
    },
    true,
  );
  document.addEventListener("click", (event) => {
    const el = event.target.closest("[data-confirm-click]");
    if (el && !window.confirm(el.dataset.confirmClick)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  });

  // ------------------------------------------------ Autosave & unsaved work
  function initAutosave(form) {
    if (form.dataset.autosaveBound) return;
    form.dataset.autosaveBound = "true";
    const status = form.querySelector("[data-autosave-status]");
    let timer = null;
    let dirty = false;
    const save = () => {
      timer = null;
      const body = new FormData(form);
      if (status) status.textContent = "Saving…";
      fetch(form.dataset.autosaveUrl, {
        method: "POST",
        body,
        headers: { "X-CSRFToken": csrfToken(), "HX-Request": "true" },
        credentials: "same-origin",
      })
        .then((response) => {
          if (!response.ok) throw new Error(String(response.status));
          dirty = false;
          if (status) status.textContent = `Draft saved ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
        })
        .catch(() => {
          if (status) status.textContent = "Couldn't save draft — your work is still here.";
        });
    };
    form.addEventListener("input", () => {
      dirty = true;
      if (status) status.textContent = "Unsaved changes";
      clearTimeout(timer);
      timer = setTimeout(save, 1200);
    });
    window.addEventListener("beforeunload", (event) => {
      if (dirty && form.dataset.submitting !== "true") {
        event.preventDefault();
        event.returnValue = "";
      }
    });
  }
  function initAutosaves(root) {
    (root || document).querySelectorAll("form[data-autosave-url]").forEach(initAutosave);
  }

  // ---------------------------------------------------------- Word counts
  document.addEventListener("input", (event) => {
    const field = event.target.closest("[data-word-count]");
    if (!field) return;
    const target = document.getElementById(field.dataset.wordCount);
    if (!target) return;
    const words = (field.value.match(/\b\w+\b/g) || []).length;
    target.textContent = `${words} word${words === 1 ? "" : "s"}`;
  });

  // ------------------------------------------------------------ Timezones
  function initTimezones(root) {
    (root || document).querySelectorAll("input[data-detect-timezone]").forEach((input) => {
      if (input.value) return;
      try {
        input.value = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
      } catch (_) {
        /* ignore */
      }
    });
  }

  // ------------------------------------------------------------- Editors
  function initEditors(root) {
    if (window.SkillForgeEditor) window.SkillForgeEditor.mountAll(root || document);
  }

  // ------------------------------------------------------------ Skill map
  document.addEventListener("pointerover", (event) => highlightNode(event.target.closest(".skill-node")));
  document.addEventListener("focusin", (event) => highlightNode(event.target.closest(".skill-node")));
  document.addEventListener("pointerout", (event) => {
    if (event.target.closest(".skill-node")) highlightNode(null);
  });
  function highlightNode(node) {
    document.querySelectorAll(".skill-map").forEach((map) => {
      map.classList.toggle("has-focus", Boolean(node && map.contains(node)));
      map.querySelectorAll(".is-highlight").forEach((el) => el.classList.remove("is-highlight"));
    });
    if (!node) return;
    const map = node.closest(".skill-map");
    const id = node.dataset.skill;
    node.classList.add("is-highlight");
    map.querySelectorAll(`[data-edge-to="${id}"], [data-edge-from="${id}"]`).forEach((edge) => {
      edge.classList.add("is-highlight");
      const other = edge.dataset.edgeFrom === id ? edge.dataset.edgeTo : edge.dataset.edgeFrom;
      map.querySelector(`.skill-node[data-skill="${other}"]`)?.classList.add("is-highlight");
    });
  }

  // --------------------------------------------------------------- Charts
  const charts = [];
  function cssVar(name) {
    return getComputedStyle(doc).getPropertyValue(name).trim();
  }
  // Chart series keys map onto the brand palette: forest green leads, antique
  // gold is the secondary highlight, beige carries supporting series.
  function palette() {
    return {
      accent: cssVar("--sf-chart-1"),
      info: cssVar("--sf-chart-2"),
      success: cssVar("--sf-chart-1"),
      warning: cssVar("--sf-chart-2"),
      danger: cssVar("--sf-danger"),
      muted: cssVar("--sf-chart-3"),
      text: cssVar("--sf-text-muted"),
      grid: cssVar("--sf-border"),
      surface: cssVar("--sf-surface"),
    };
  }
  function buildChart(canvas) {
    if (!window.Chart) return;
    const source = document.getElementById(canvas.dataset.chart);
    if (!source) return;
    const spec = JSON.parse(source.textContent);
    const colors = palette();
    window.Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    const datasets = spec.datasets.map((ds) => {
      const color = colors[ds.color || "accent"];
      const fill = ds.fill ? `${color}26` : color;
      return {
        label: ds.label,
        data: ds.data,
        type: ds.type,
        borderColor: color,
        backgroundColor: spec.type === "line" || ds.type === "line" ? fill : color,
        fill: Boolean(ds.fill),
        cubicInterpolationMode: "monotone", // never overshoots below zero or above 100%
        borderWidth: 2,
        pointRadius: spec.type === "line" ? 2.5 : 0,
        pointHoverRadius: 5,
        pointBackgroundColor: color,
        borderRadius: 3,
        maxBarThickness: 26,
        yAxisID: ds.axis || "y",
        spanGaps: true,
      };
    });
    const scales = {
      x: { grid: { display: false }, ticks: { color: colors.text, maxRotation: 0, autoSkipPadding: 12 } },
      y: {
        beginAtZero: true,
        suggestedMax: spec.suggestedMax,
        grid: { color: colors.grid },
        ticks: { color: colors.text, precision: 0, callback: spec.percent ? (v) => `${v}%` : undefined },
      },
    };
    if (spec.secondaryAxis) {
      scales.y2 = {
        position: "right",
        beginAtZero: true,
        suggestedMax: spec.secondaryAxis.suggestedMax,
        grid: { display: false },
        ticks: { color: colors.text },
      };
    }
    const chart = new window.Chart(canvas, {
      type: spec.type || "bar",
      data: { labels: spec.labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: reduceMotion() ? false : { duration: 700, easing: "easeOutQuart" },
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            display: datasets.length > 1,
            align: "end",
            labels: { color: colors.text, boxWidth: 8, boxHeight: 8, usePointStyle: true, pointStyle: "rectRounded" },
          },
          tooltip: {
            backgroundColor: colors.surface,
            titleColor: cssVar("--sf-text"),
            bodyColor: colors.text,
            borderColor: cssVar("--sf-border-strong"),
            borderWidth: 1,
            cornerRadius: 8,
            padding: 10,
            boxPadding: 4,
          },
        },
        scales: spec.type === "doughnut" ? {} : scales,
      },
    });
    charts.push({ canvas, chart });
  }
  function initCharts(root) {
    (root || document).querySelectorAll("canvas[data-chart]").forEach((canvas) => {
      if (canvas.dataset.chartReady) return;
      canvas.dataset.chartReady = "true";
      buildChart(canvas);
    });
  }
  function refreshCharts() {
    for (const entry of charts.splice(0)) {
      entry.chart.destroy();
      delete entry.canvas.dataset.chartReady;
    }
    requestAnimationFrame(() => initCharts(document));
  }

  // ----------------------------------------------------------------- Boot
  initTimezones(document);
  initAutosaves(document);
  initCharts(document);
  initEditors(document);
  document.addEventListener("htmx:load", (event) => initAutosaves(event.detail.elt));
})();
